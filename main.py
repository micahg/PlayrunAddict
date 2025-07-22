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

async def main():
    processor = AudioProcessor()
    await processor.initialize()
    await processor.check_for_new_m3u8_files()
    print("ALL DONE")

if __name__ == "__main__":
    asyncio.run(main())