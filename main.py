#!/usr/bin/env python3
"""
M3U8 Audio Processor
Watches Google Drive for M3U8 files using Push notifications, processes audio at configurable speed, 
uploads to cloud storage, and pushes to Playrun API.
"""

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse
import hashlib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiohttp
import requests
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from google.auth import default
from google.cloud import pubsub_v1
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import subprocess
import multiprocessing
from pydantic import BaseModel
import re
import hmac
import base64

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
class Config:
    # Google Drive API - using Application Default Credentials
    SCOPES = ['https://www.googleapis.com/auth/drive']
    
    # Google Cloud Pub/Sub for notifications
    PROJECT_ID = os.getenv('GOOGLE_CLOUD_PROJECT_ID')
    TOPIC_NAME = os.getenv('PUBSUB_TOPIC_NAME', 'm3u8-processor')
    SUBSCRIPTION_NAME = os.getenv('PUBSUB_SUBSCRIPTION_NAME', 'm3u8-processor-sub')
    
    # Webhook for Drive notifications
    WEBHOOK_URL = os.getenv('WEBHOOK_URL')  # Your public webhook URL
    WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', str(uuid.uuid4()))
    
    # Playrun API
    PLAYRUN_BASE_URL = 'https://www.playrun.app'
    PLAYRUN_TOKEN_FILE = 'playrun_token.json'
    
    # Audio processing
    DEFAULT_SPEED = 1.5
    MAX_WORKERS = max(1, multiprocessing.cpu_count() - 1)
    
    # Email notifications
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    EMAIL_USERNAME = os.getenv('EMAIL_USERNAME')
    EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
    NOTIFICATION_EMAIL = os.getenv('NOTIFICATION_EMAIL')
    
    # Fallback polling (if push notifications fail)
    POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', '300'))  # 5 minutes as fallback

# Data models
class ProcessingJob(BaseModel):
    id: str
    status: str  # pending, processing, completed, failed
    m3u8_file_id: str
    m3u8_file_name: str
    speed: float
    created_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    processed_files: List[Dict[str, Any]] = []

class DriveNotification(BaseModel):
    kind: str
    id: str
    resourceId: str
    resourceUri: str
    token: str
    expiration: str

class AudioProcessor:
    def __init__(self):
        self.drive_service = None
        self.pubsub_client = None
        self.playrun_token = None
        self.executor = ThreadPoolExecutor(max_workers=Config.MAX_WORKERS)
        self.jobs: Dict[str, ProcessingJob] = {}
        self.processed_files = set()  # Track processed files to avoid duplicates
        self.notification_channels = {}  # Track active notification channels
        
    async def initialize(self):
        """Initialize Google Drive and Pub/Sub connections"""
        await self.setup_google_services()
        await self.setup_playrun_auth()
        await self.setup_push_notifications()
        
    async def setup_google_services(self):
        """Setup Google services using Application Default Credentials"""
        try:
            # Use Application Default Credentials
            credentials, project_id = default(scopes=Config.SCOPES)
            
            # Set project ID if not already set
            if not Config.PROJECT_ID:
                Config.PROJECT_ID = project_id
            
            # Initialize Drive service
            self.drive_service = build('drive', 'v3', credentials=credentials)
            
            # Initialize Pub/Sub client
            self.pubsub_client = pubsub_v1.PublisherClient()
            
            logger.info(f"Google services initialized with project: {Config.PROJECT_ID}")
            
        except Exception as e:
            logger.error(f"Failed to initialize Google services: {e}")
            logger.info("Make sure you've run 'gcloud auth application-default login'")
            raise
    
    async def setup_playrun_auth(self):
        """Setup Playrun API authentication"""
        if os.path.exists(Config.PLAYRUN_TOKEN_FILE):
            with open(Config.PLAYRUN_TOKEN_FILE, 'r') as f:
                data = json.load(f)
                self.playrun_token = data.get('token')
                logger.info("Loaded existing Playrun token")
        else:
            logger.warning("No Playrun token found. Use /auth/playrun endpoint to authenticate")
    
    async def setup_push_notifications(self):
        """Setup Google Drive Push notifications"""
        try:
            # Create Pub/Sub topic if it doesn't exist
            await self.create_pubsub_topic()
            
            # Setup Drive notification channel
            if Config.WEBHOOK_URL:
                await self.setup_drive_webhook()
            else:
                logger.warning("No WEBHOOK_URL configured. Falling back to polling mode.")
                asyncio.create_task(self.fallback_polling())
                
        except Exception as e:
            logger.error(f"Failed to setup push notifications: {e}")
            logger.info("Falling back to polling mode")
            asyncio.create_task(self.fallback_polling())
    
    async def create_pubsub_topic(self):
        """Create Pub/Sub topic for notifications"""
        try:
            topic_path = self.pubsub_client.topic_path(Config.PROJECT_ID, Config.TOPIC_NAME)
            
            # Try to create topic
            try:
                topic = self.pubsub_client.create_topic(request={"name": topic_path})
                logger.info(f"Created Pub/Sub topic: {topic.name}")
            except Exception as e:
                if "already exists" in str(e).lower():
                    logger.info(f"Pub/Sub topic already exists: {topic_path}")
                else:
                    raise
            
            # Create subscription
            subscriber = pubsub_v1.SubscriberClient()
            subscription_path = subscriber.subscription_path(Config.PROJECT_ID, Config.SUBSCRIPTION_NAME)
            
            try:
                subscription = subscriber.create_subscription(
                    request={"name": subscription_path, "topic": topic_path}
                )
                logger.info(f"Created Pub/Sub subscription: {subscription.name}")
            except Exception as e:
                if "already exists" in str(e).lower():
                    logger.info(f"Pub/Sub subscription already exists: {subscription_path}")
                else:
                    raise
                    
        except Exception as e:
            logger.error(f"Error setting up Pub/Sub: {e}")
            raise
    
    async def setup_drive_webhook(self):
        """Setup Google Drive webhook for file notifications"""
        try:
            # Create notification channel for changes
            channel_id = str(uuid.uuid4())
            
            channel = {
                'id': channel_id,
                'type': 'web_hook',
                'address': Config.WEBHOOK_URL,
                'token': Config.WEBHOOK_SECRET,
                'expiration': int((time.time() + 86400) * 1000)  # 24 hours
            }
            
            # Watch for changes to files (M3U8 files specifically)
            result = self.drive_service.files().watch(
                fileId='root',  # Watch root folder, or specify folder ID
                body=channel
            ).execute()
            
            self.notification_channels[channel_id] = result
            logger.info(f"Drive webhook setup successful: {channel_id}")
            
        except Exception as e:
            logger.error(f"Failed to setup Drive webhook: {e}")
            raise
    
    async def authenticate_playrun(self, email: str, password: str):
        """Authenticate with Playrun API"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{Config.PLAYRUN_BASE_URL}/api/auth",
                    json={"email": email, "password": password}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        self.playrun_token = data.get('token')
                        
                        # Save token
                        with open(Config.PLAYRUN_TOKEN_FILE, 'w') as f:
                            json.dump({"token": self.playrun_token}, f)
                        
                        logger.info("Playrun authentication successful")
                        return True
                    else:
                        logger.error(f"Playrun authentication failed: {response.status}")
                        return False
            except Exception as e:
                logger.error(f"Error authenticating with Playrun: {e}")
                return False
    
    async def handle_drive_notification(self, request: Request):
        """Handle incoming Drive webhook notifications"""
        try:
            # Verify webhook signature
            signature = request.headers.get('X-Goog-Channel-Token')
            if signature != Config.WEBHOOK_SECRET:
                logger.warning("Invalid webhook signature")
                return {"error": "Invalid signature"}
            
            # Get notification data
            body = await request.body()
            headers = dict(request.headers)
            
            # Extract resource information
            resource_id = headers.get('X-Goog-Resource-ID')
            resource_uri = headers.get('X-Goog-Resource-URI')
            
            logger.info(f"Received Drive notification for resource: {resource_id}")
            
            # Check for M3U8 files
            await self.check_for_new_m3u8_files()
            
            return {"status": "processed"}
            
        except Exception as e:
            logger.error(f"Error handling Drive notification: {e}")
            return {"error": str(e)}
    
    async def check_for_new_m3u8_files(self):
        """Check for new M3U8 files and process them"""
        try:
            # Search for M3U8 files
            results = self.drive_service.files().list(
                q="name contains '.m3u' and trashed=false",
                # q="trashed=false",
                fields="files(id, name, modifiedTime)"
            ).execute()
            
            files = results.get('files', [])
            
            for file in files:
                file_id = file['id']
                file_name = file['name']
                
                # Skip if already processed
                if file_id in self.processed_files:
                    continue
                
                logger.info(f"Found new M3U8 file: {file_name}")
                
                # Create processing job
                job_id = str(uuid.uuid4())
                job = ProcessingJob(
                    id=job_id,
                    status="pending",
                    m3u8_file_id=file_id,
                    m3u8_file_name=file_name,
                    speed=Config.DEFAULT_SPEED,
                    created_at=datetime.now(timezone.utc)
                )
                
                self.jobs[job_id] = job
                self.processed_files.add(file_id)
                
                # Start processing in background
                asyncio.create_task(self.process_m3u8_file(job_id))
                
        except Exception as e:
            logger.error(f"Error checking for new M3U8 files: {e}")
    
    async def fallback_polling(self):
        """Fallback polling mechanism when push notifications aren't available"""
        logger.info("Starting fallback polling mode...")
        
        while True:
            try:
                await self.check_for_new_m3u8_files()
                await asyncio.sleep(Config.POLL_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in fallback polling: {e}")
                await asyncio.sleep(Config.POLL_INTERVAL)
    
    async def process_m3u8_file(self, job_id: str):
        """Process M3U8 file and handle all audio files"""
        job = self.jobs[job_id]
        
        try:
            job.status = "processing"
            logger.info(f"Processing job {job_id}: {job.m3u8_file_name}")
            
            # Download M3U8 file
            m3u8_content = await self.download_drive_file(job.m3u8_file_id)
            
            # Parse M3U8 content
            audio_entries = self.parse_m3u8(m3u8_content)
            
            if not audio_entries:
                raise Exception("No audio files found in M3U8 playlist")
            
            logger.info(f"Found {len(audio_entries)} audio files to process")
            
            # Process files in parallel
            tasks = []
            for entry in audio_entries:
                task = asyncio.create_task(self.process_audio_file(entry, job.speed))
                tasks.append(task)
            
            # Wait for all files to be processed
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Collect successful results
            successful_results = []
            errors = []
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    errors.append(f"File {i+1}: {str(result)}")
                else:
                    successful_results.append(result)
            
            job.processed_files = successful_results
            
            if errors:
                job.error = f"Some files failed: {'; '.join(errors)}"
                job.status = "completed" if successful_results else "failed"
            else:
                job.status = "completed"
            
            job.completed_at = datetime.now(timezone.utc)
            
            # Send notification
            await self.send_notification(
                f"Job {job_id} completed. "
                f"Successfully processed {len(successful_results)}/{len(audio_entries)} files. "
                f"Errors: {len(errors)}"
            )
            
            logger.info(f"Job {job_id} completed with {len(successful_results)} successful files")
            
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.completed_at = datetime.now(timezone.utc)
            
            await self.send_notification(f"Job {job_id} failed: {str(e)}")
            logger.error(f"Job {job_id} failed: {e}")
    
    def parse_m3u8(self, content: str) -> List[Dict[str, Any]]:
        """Parse M3U8 content to extract audio file information"""
        lines = content.strip().split('\n')
        entries = []
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            if line.startswith('#EXTINF:'):
                # Parse EXTINF line
                # Format: #EXTINF:duration,title
                match = re.match(r'#EXTINF:([0-9.]+),(.+)', line)
                if match:
                    duration = float(match.group(1))
                    title = match.group(2).strip()
                    
                    # Next line should be the URL
                    if i + 1 < len(lines):
                        url = lines[i + 1].strip()
                        if url and not url.startswith('#'):
                            entries.append({
                                'title': title,
                                'duration': duration,
                                'url': url,
                                'uuid': str(uuid.uuid4())
                            })
                            i += 2
                            continue
            
            i += 1
        
        return entries
    
    async def download_drive_file(self, file_id: str) -> str:
        """Download file content from Google Drive"""
        try:
            request = self.drive_service.files().get_media(fileId=file_id)
            content = request.execute()
            return content.decode('utf-8')
        except Exception as e:
            logger.error(f"Error downloading file {file_id}: {e}")
            raise
    
    async def process_audio_file(self, entry: Dict[str, Any], speed: float) -> Dict[str, Any]:
        """Process a single audio file"""
        try:
            url = entry['url']
            title = entry['title']
            duration = entry['duration']
            file_uuid = entry['uuid']
            
            logger.info(f"Processing audio file: {title}")
            
            # Download audio file
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_input:
                await self.download_audio_file(url, temp_input.name)
                
                # Process audio with FFmpeg
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_output:
                    await self.process_audio_with_ffmpeg(temp_input.name, temp_output.name, speed)
                    
                    # Upload to Google Drive
                    drive_url = await self.upload_to_drive(temp_output.name, f"{title}_speedup.mp3")
                    
                    # Calculate new duration
                    new_duration = int(duration / speed)
                    
                    # Push to Playrun API
                    await self.push_to_playrun({
                        'title': title,
                        'published': datetime.now(timezone.utc).isoformat(),
                        'duration': new_duration,
                        'url': drive_url,
                        'uuid': file_uuid,
                        'type': 'mp3',
                        'podcast': {
                            'title': 'Processed Podcast',
                            'author': 'Audio Processor',
                            'uuid': str(uuid.uuid4()),
                            'logoUrl': ''
                        },
                        'podcast_uuid': str(uuid.uuid4())
                    })
                    
                    # Clean up temp files
                    os.unlink(temp_input.name)
                    os.unlink(temp_output.name)
                    
                    return {
                        'title': title,
                        'original_url': url,
                        'processed_url': drive_url,
                        'original_duration': duration,
                        'new_duration': new_duration,
                        'uuid': file_uuid,
                        'speed': speed
                    }
        
        except Exception as e:
            logger.error(f"Error processing audio file {title}: {e}")
            raise
    
    async def download_audio_file(self, url: str, output_path: str):
        """Download audio file from URL"""
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    with open(output_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)
                else:
                    raise Exception(f"Failed to download audio file: HTTP {response.status}")
    
    async def process_audio_with_ffmpeg(self, input_path: str, output_path: str, speed: float):
        """Process audio file with FFmpeg to change speed while preserving pitch"""
        try:
            # Use atempo filter to change speed while preserving pitch
            cmd = [
                'ffmpeg',
                '-i', input_path,
                '-filter:a', f'atempo={speed}',
                '-y',  # Overwrite output file
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise Exception(f"FFmpeg error: {result.stderr}")
            
            logger.info(f"Audio processed successfully: {speed}x speed")
            
        except Exception as e:
            logger.error(f"Error processing audio with FFmpeg: {e}")
            raise
    
    async def upload_to_drive(self, file_path: str, filename: str) -> str:
        """Upload file to Google Drive with public access"""
        try:
            # Create file metadata
            file_metadata = {
                'name': filename,
                'parents': []  # You can specify a folder ID here if needed
            }
            
            # Upload file
            media = MediaFileUpload(file_path, mimetype='audio/mpeg')
            file = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            
            file_id = file.get('id')
            
            # Make file publicly accessible
            permission = {
                'type': 'anyone',
                'role': 'reader'
            }
            
            self.drive_service.permissions().create(
                fileId=file_id,
                body=permission
            ).execute()
            
            # Return direct download URL
            return f"https://drive.google.com/uc?id={file_id}"
            
        except Exception as e:
            logger.error(f"Error uploading to Google Drive: {e}")
            raise
    
    async def push_to_playrun(self, episode_data: Dict[str, Any]):
        """Push episode data to Playrun API"""
        if not self.playrun_token:
            raise Exception("No Playrun token available")
        
        async with aiohttp.ClientSession() as session:
            headers = {
                'Authorization': f'Bearer {self.playrun_token}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'episode': episode_data
            }
            
            async with session.post(
                f"{Config.PLAYRUN_BASE_URL}/api/playlist/subscribe",
                headers=headers,
                json=payload
            ) as response:
                if response.status == 200:
                    logger.info(f"Successfully pushed to Playrun: {episode_data['title']}")
                else:
                    error_text = await response.text()
                    raise Exception(f"Failed to push to Playrun: HTTP {response.status} - {error_text}")
    
    async def send_notification(self, message: str):
        """Send email notification"""
        if not all([Config.EMAIL_USERNAME, Config.EMAIL_PASSWORD, Config.NOTIFICATION_EMAIL]):
            logger.warning("Email configuration not complete, skipping notification")
            return
        
        try:
            msg = MIMEMultipart()
            msg['From'] = Config.EMAIL_USERNAME
            msg['To'] = Config.NOTIFICATION_EMAIL
            msg['Subject'] = "M3U8 Audio Processor Notification"
            
            msg.attach(MIMEText(message, 'plain'))
            
            server = smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT)
            server.starttls()
            server.login(Config.EMAIL_USERNAME, Config.EMAIL_PASSWORD)
            
            server.send_message(msg)
            server.quit()
            
            logger.info("Notification sent successfully")
            
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    def get_job_status(self, job_id: str) -> Optional[ProcessingJob]:
        """Get status of a processing job"""
        return self.jobs.get(job_id)
    
    def list_jobs(self) -> List[ProcessingJob]:
        """List all processing jobs"""
        return list(self.jobs.values())

# FastAPI app for status and control
app = FastAPI(title="M3U8 Audio Processor", version="1.0.0")
processor = AudioProcessor()

@app.on_event("startup")
async def startup_event():
    await processor.initialize()

@app.get("/")
async def root():
    return {"message": "M3U8 Audio Processor is running"}

@app.post("/webhook/drive")
async def drive_webhook(request: Request):
    """Handle Google Drive webhook notifications"""
    return await processor.handle_drive_notification(request)

@app.get("/status")
async def get_status():
    jobs = processor.list_jobs()
    return {
        "total_jobs": len(jobs),
        "pending": len([j for j in jobs if j.status == "pending"]),
        "processing": len([j for j in jobs if j.status == "processing"]),
        "completed": len([j for j in jobs if j.status == "completed"]),
        "failed": len([j for j in jobs if j.status == "failed"])
    }

@app.get("/jobs")
async def list_jobs():
    jobs = processor.list_jobs()
    return {"jobs": [job.dict() for job in jobs]}

@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = processor.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.dict()

@app.post("/auth/playrun")
async def authenticate_playrun(credentials: dict):
    email = credentials.get("email")
    password = credentials.get("password")
    
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")
    
    success = await processor.authenticate_playrun(email, password)
    if success:
        return {"message": "Authentication successful"}
    else:
        raise HTTPException(status_code=401, detail="Authentication failed")

@app.post("/manual-check")
async def manual_check():
    """Manually trigger a check for new M3U8 files"""
    await processor.check_for_new_m3u8_files()
    return {"message": "Manual check triggered"}

@app.get("/test-drive")
async def test_drive():
    """Test Google Drive API connectivity"""
    try:
        if not processor.drive_service:
            return {"error": "Drive service not initialized"}
        
        # Simple test - list files (limited to 5)
        results = processor.drive_service.files().list(
            pageSize=5,
            fields="files(id, name)"
        ).execute()
        
        files = results.get('files', [])
        return {
            "status": "success",
            "message": "Drive API connection working",
            "files_found": len(files),
            "sample_files": [{"id": f["id"], "name": f["name"]} for f in files[:3]]
        }
    except Exception as e:
        return {"error": f"Drive API test failed: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)