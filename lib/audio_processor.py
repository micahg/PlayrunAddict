import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import aiohttp
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.auth import default
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import subprocess
import multiprocessing
from pydantic import BaseModel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Config:
    SCOPES = ['https://www.googleapis.com/auth/drive']
    PROJECT_ID = os.getenv('GOOGLE_CLOUD_PROJECT_ID')
    TOPIC_NAME = os.getenv('PUBSUB_TOPIC_NAME', 'm3u8-processor')
    SUBSCRIPTION_NAME = os.getenv('PUBSUB_SUBSCRIPTION_NAME', 'm3u8-processor-sub')
    WEBHOOK_URL = os.getenv('WEBHOOK_URL')
    WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', str(uuid.uuid4()))
    DEFAULT_SPEED = 1.5
    MAX_WORKERS = max(1, multiprocessing.cpu_count() - 1)
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    EMAIL_USERNAME = os.getenv('EMAIL_USERNAME')
    EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
    NOTIFICATION_EMAIL = os.getenv('NOTIFICATION_EMAIL')
    POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', '300'))

class ProcessingJob(BaseModel):
    id: str
    status: str
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
        self.executor = ThreadPoolExecutor(max_workers=Config.MAX_WORKERS)
        self.jobs: Dict[str, ProcessingJob] = {}
        self.processed_files = set()
        self.notification_channels = {}

    async def initialize(self):
        await self.setup_google_services()
        # this is triggering another call to check_for_new_m3u8_files because it starts fallback polling
        # await self.setup_push_notifications()

    async def setup_google_services(self):
        try:
            credentials, project_id = default(scopes=Config.SCOPES)
            if not Config.PROJECT_ID:
                Config.PROJECT_ID = project_id
            self.drive_service = build('drive', 'v3', credentials=credentials)
            logger.info(f"Google services initialized with project: {Config.PROJECT_ID}")
        except Exception as e:
            logger.error(f"Failed to initialize Google services: {e}")
            logger.info("Make sure you've run 'gcloud auth application-default login'")
            raise

    def get_most_recent_file(self, files: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Get the most recently modified file from a list of files"""
        if not files:
            return None
            
        most_recent = None
        most_recent_time = None
        
        for file in files:
            modified_time_str = file.get('modifiedTime')
            if not modified_time_str:
                continue
                
            # Convert ISO formatted timestamp to datetime
            try:
                modified_time = datetime.fromisoformat(modified_time_str.replace('Z', '+00:00'))
                if most_recent_time is None or modified_time > most_recent_time:
                    most_recent_time = modified_time
                    most_recent = file
            except ValueError as e:
                logger.warning(f"Could not parse modifiedTime '{modified_time_str}' for file {file.get('name', 'unknown')}: {e}")
                continue
                
        return most_recent

    async def check_for_new_m3u8_files(self):
        try:
            results = self.drive_service.files().list(
                q="name contains '.m3u' and trashed=false",
                fields="files(id, name, modifiedTime)"
            ).execute()
            files = results.get('files', [])
            
            # Get only the most recent file
            most_recent_file = self.get_most_recent_file(files)
            if not most_recent_file:
                logger.info("No M3U8 files found")
                return
                
            file_id = most_recent_file['id']
            file_name = most_recent_file['name']
            
            if file_id in self.processed_files:
                logger.info(f"Most recent M3U8 file '{file_name}' already processed")
                return
                
            logger.info(f"Found new M3U8 file: {file_name}")
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
            results = await asyncio.create_task(self.process_m3u8_file(job_id))
            logger.info(f"CHECK self.jobs: {self.jobs}")
        except Exception as e:
            logger.error(f"Error checking for new M3U8 files: {e}")
        return results

    async def fallback_polling(self):
        logger.info("Starting fallback polling mode...")
        while True:
            try:
                await self.check_for_new_m3u8_files()
                await asyncio.sleep(Config.POLL_INTERVAL)
            except Exception as e:
                logger.error(f"Error in fallback polling: {e}")
                await asyncio.sleep(Config.POLL_INTERVAL)

    async def process_m3u8_file(self, job_id: str):
        job = self.jobs[job_id]
        try:
            job.status = "processing"
            logger.info(f"Processing job {job_id}: {job.m3u8_file_name}")
            m3u8_content = await self.download_drive_file(job.m3u8_file_id)
            audio_entries = self.parse_m3u8(m3u8_content)
            if not audio_entries:
                raise Exception("No audio files found in M3U8 playlist")
            logger.info(f"Found {len(audio_entries)} audio files to process")
            tasks = []
            for entry in audio_entries:
                task = asyncio.create_task(self.process_audio_file(entry, job.speed), name=entry['title'])
                tasks.append(task)
                break  # Limit to processing one file at a time for testing MICAH TODO DELETE THIS

            logger.info(f"Created {len(tasks)} tasks, starting processing...")
            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                logger.info(f"All tasks completed, processing {len(results)} results...")
            except Exception as e:
                logger.error("Tasks timed out after 5 minutes")
                raise Exception("Processing timed out after 5 minutes")
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
            await self.send_notification(
                f"Job {job_id} completed. "
                f"Successfully processed {len(successful_results)}/{len(audio_entries)} files. "
                f"Errors: {len(errors)}"
            )
            logger.info(f"Job {job_id} completed with {len(successful_results)} successful files")
            return successful_results
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.completed_at = datetime.now(timezone.utc)
            await self.send_notification(f"Job {job_id} failed: {str(e)}")
            logger.error(f"Job {job_id} failed: {e}")

    def parse_m3u8(self, content: str) -> List[Dict[str, Any]]:
        lines = content.strip().split('\n')
        entries = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('#EXTINF:'):
                match = re.match(r'#EXTINF:([0-9.]+),(.+)', line)
                if match:
                    duration = float(match.group(1))
                    title = match.group(2).strip()
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
        try:
            request = self.drive_service.files().get_media(fileId=file_id)
            content = request.execute()
            return content.decode('utf-8')
        except Exception as e:
            logger.error(f"Error downloading file {file_id}: {e}")
            raise

    async def process_audio_file(self, entry: Dict[str, Any], speed: float) -> Dict[str, Any]:
        try:
            url = entry['url']
            title = entry['title']
            duration = entry['duration']
            file_uuid = entry['uuid']
            logger.info(f"Processing audio file: {title}")
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_input:
                await self.download_audio_file(url, temp_input.name)
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_output:
                    await self.process_audio_with_ffmpeg(temp_input.name, temp_output.name, speed)
                    drive_file_id = await self.upload_to_drive(temp_output.name, f"{title}_speedup.mp3")
                    new_duration = int(duration / speed)
                    os.unlink(temp_input.name)
                    os.unlink(temp_output.name)
                    return {
                        'title': title,
                        'original_url': url,
                        'drive_file_id': drive_file_id,
                        'original_duration': duration,
                        'new_duration': new_duration,
                        'uuid': file_uuid,
                        'speed': speed
                    }
        except Exception as e:
            logger.error(f"Error processing audio file {title}: {e}")
            raise

    async def download_audio_file(self, url: str, output_path: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    with open(output_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)
                else:
                    raise Exception(f"Failed to download audio file: HTTP {response.status}")

    async def process_audio_with_ffmpeg(self, input_path: str, output_path: str, speed: float):
        try:
            cmd = [
                'ffmpeg',
                '-i', input_path,
                '-t', '10',
                '-filter:a', f'atempo={speed}',
                '-y',
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
        try:
            file_metadata = {
                'name': filename,
                'parents': []
            }
            media = MediaFileUpload(file_path, mimetype='audio/mpeg')
            file = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            file_id = file.get('id')
            permission = {
                'type': 'anyone',
                'role': 'reader'
            }
            self.drive_service.permissions().create(
                fileId=file_id,
                body=permission
            ).execute()
            return file_id
        except Exception as e:
            logger.error(f"Error uploading to Google Drive: {e}")
            raise

    async def send_notification(self, message: str):
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
        return self.jobs.get(job_id)

    def list_jobs(self) -> List[ProcessingJob]:
        return list(self.jobs.values())
