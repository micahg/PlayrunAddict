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
from pydantic import BaseModel
from .config import Config
from .gdrive import GoogleDrive

logger = logging.getLogger(__name__)

M3U_QUERY = "name contains '.m3u' and trashed=false"

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
        self.executor = ThreadPoolExecutor(max_workers=Config.MAX_WORKERS)
        self.jobs: Dict[str, ProcessingJob] = {}
        self.processed_files = set()
        self.notification_channels = {}

    async def initialize(self):
        await self.setup_google_services()
        # this is triggering another call to check_for_new_m3u8_files because it starts fallback polling
        # await self.setup_push_notifications()

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
            most_recent_file = GoogleDrive.instance().get_files(M3U_QUERY, most_recent=True)[0]
                
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
            
            # Download files sequentially and start processing as each completes
            logger.info("Starting downloads and processing...")
            tasks = []
            for entry in audio_entries:
                temp_file = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
                temp_file.close()  # Close file handle but keep the file
                
                download_start = time.time()
                await self.download_audio_file(entry['url'], temp_file.name)
                download_time = time.time() - download_start
                logger.info(f"Downloaded {entry['title']} in {download_time:.2f} seconds")
                
                # Add local file path to entry
                entry['local_file'] = temp_file.name
                
                # Start processing immediately after download
                task = asyncio.create_task(self.process_audio_file(entry, job.speed), name=entry['title'])
                tasks.append(task)

            logger.info(f"All downloads complete, {len(tasks)} processing tasks running...")
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
            # TODO not sure the value of this
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
            request = GoogleDrive.instance().service().files().get_media(fileId=file_id)
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
            local_file = entry['local_file']
            
            logger.info(f"Processing audio file: {title}")
            
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_output:
                ffmpeg_start = time.time()
                await self.process_audio_with_ffmpeg(local_file, temp_output.name, speed)
                ffmpeg_time = time.time() - ffmpeg_start
                logger.info(f"FFmpeg processed {title} in {ffmpeg_time:.2f} seconds")
                
                new_duration = int(duration / speed)
                
                # Clean up input file
                os.unlink(local_file)
                
                return {
                    'title': title,
                    'original_url': url,
                    'original_duration': duration,
                    'new_duration': new_duration,
                    'uuid': file_uuid,
                    'speed': speed,
                    'temp_file': temp_output.name,
                }
        except Exception as e:
            logger.error(f"Error processing audio file {title}: {e}")
            # Clean up input file on error
            if 'local_file' in entry and os.path.exists(entry['local_file']):
                os.unlink(entry['local_file'])
            raise

    async def download_audio_file(self, url: str, output_path: str):
        logger.info(f"Downloading audio from: {url}")
        timeout = aiohttp.ClientTimeout(total=None, connect=15, sock_read=10)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        with open(output_path, 'wb') as f:
                            async for chunk in response.content.iter_chunked(8192):
                                f.write(chunk)
                    else:
                        raise Exception(f"Failed to download audio file: HTTP {response.status}")
        except asyncio.TimeoutError as e:
            raise Exception(f"Download timeout for {url}: Connection timeout or no data received for 10 seconds")
        except Exception as e:
            # Re-raise other exceptions as-is
            raise

    async def process_audio_with_ffmpeg(self, input_path: str, output_path: str, speed: float):
        try:
            cmd = [
                'ffmpeg',
                '-i', input_path,
                # '-t', '10',
                '-filter:a', f'atempo={speed}',
                '-y',
                output_path
            ]
            
            logger.info(f"Starting FFmpeg processing with {speed}x speed...")
            
            # Use async subprocess instead of blocking subprocess.run()
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                stderr_text = stderr.decode() if stderr else "Unknown error"
                raise Exception(f"FFmpeg error (code {process.returncode}): {stderr_text}")
                
            logger.info(f"Audio processed successfully: {speed}x speed")
        except Exception as e:
            logger.error(f"Error processing audio with FFmpeg: {e}")
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
