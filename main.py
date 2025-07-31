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
from platform import processor
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

import asyncio
from lib.audio_processor import AudioProcessor
from lib.podcast_rss_processor import PodcastRSSProcessor
from lib.config import Config
from lib.gdrive import GoogleDrive

async def main():
    # Initialize Google Drive service
    try:
        GoogleDrive.instance()
    except Exception as e:
        logger.error(f"Error setting up Google Drive: {e}")
        return

    processor = AudioProcessor()
    podcast_processor = PodcastRSSProcessor()
    rss_drive_id = podcast_processor.get_rss_feed_id()

    results = await processor.check_for_new_m3u8_files()
    # check for an existing playlist
    if not results or len(results) == 0:
        logger.error("M3U8 resulted in no files")
        return
    
    logger.info(f"Processed {len(results)} audio files")
    for result in results:
        logger.info(f"Uploading {result['title']} to Google Drive")
        try:
            drive_file_id = await GoogleDrive.instance().upload_to_drive(result['temp_file'], f"{result['title']}.mp3")
            os.unlink(result['temp_file'])
            result['drive_file_id'] = drive_file_id
        except Exception as e:
            logger.error(f"Failed to upload {result['title']} to Google Drive: {e}")
            return

    xml_feed = podcast_processor.create_rss_xml(results)
    rss_drive_id = await GoogleDrive.instance().upload_string_to_drive(xml_feed, "playrun_addict.xml", mimetype='application/rss+xml', file_id=rss_drive_id)
    rss_download_url = GoogleDrive.generate_download_url(rss_drive_id)
    print(f"RSS Feed Download URL: {rss_download_url}")

if __name__ == "__main__":
    asyncio.run(main())