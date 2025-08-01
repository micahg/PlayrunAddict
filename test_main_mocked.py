#!/usr/bin/env python3
"""
Simple test runner for main() with basic function-level mocking.
Runs a single test focused on testing the main workflow.
"""

import asyncio
import logging
import sys
from unittest.mock import patch, MagicMock

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_simple_main():
    """Simple test that just runs main() and counts method calls"""
    
    # Mock data
    M3U8_CONTENT = """#EXTM3U
#EXT-X-VERSION:3
#EXTINF:180.0,Episode 1 - Introduction
https://example.com/audio/episode1.mp3
#EXTINF:240.0,Episode 2 - Getting Started  
https://example.com/audio/episode2.mp3
#EXT-X-ENDLIST"""

    RSS_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
    <channel>
        <title>Test Feed</title>
        <item>
            <title>Existing Episode</title>
            <enclosure url="https://example.com/existing.mp3" type="audio/mpeg" length="900"/>
        </item>
    </channel>
</rss>'''

    M3U8_FILES = [{'id': 'mock_m3u8_123', 'name': 'test.m3u8', 'modifiedTime': '2025-07-31T12:00:00.000Z'}]
    RSS_FILES = [{'id': 'mock_rss_456', 'name': 'feed.xml', 'modifiedTime': '2025-07-31T11:00:00.000Z'}]

    call_counts = {'gdrive_calls': 0, 'http_calls': 0, 'ffmpeg_calls': 0}

    # Simple mock functions
    def mock_get_files(query, most_recent=False):
        call_counts['gdrive_calls'] += 1
        logger.info(f"MOCK: get_files called with query: {query}")
        if '.m3u' in query:
            return M3U8_FILES
        elif 'xml' in query:
            return RSS_FILES
        return []

    async def mock_download_file_to_string(file_id):
        call_counts['gdrive_calls'] += 1
        logger.info(f"MOCK: download_file_to_string called with: {file_id}")
        if 'mock_m3u8' in file_id:
            return M3U8_CONTENT
        elif 'mock_rss' in file_id:
            return RSS_XML
        return "MOCK_CONTENT"

    async def mock_upload_to_drive(file_path, filename, mimetype='audio/mpeg'):
        call_counts['gdrive_calls'] += 1
        logger.info(f"MOCK: upload_to_drive called: {filename}")
        return f"uploaded_{filename}_id"

    async def mock_upload_string_to_drive(content, filename, mimetype='text/plain', file_id=None):
        call_counts['gdrive_calls'] += 1
        logger.info(f"MOCK: upload_string_to_drive called: {filename}")
        return file_id or f"uploaded_{filename}_id"

    class MockProcess:
        def __init__(self):
            self.returncode = 0
        async def communicate(self):
            return b'mock stdout', b'mock stderr'

    async def mock_subprocess_exec(*args, **kwargs):
        call_counts['ffmpeg_calls'] += 1
        logger.info(f"MOCK: subprocess exec called with: {args[0] if args else 'no args'}")
        return MockProcess()

    class MockResponse:
        def __init__(self):
            self.status = 200
            self.content = MockContent()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass

    class MockContent:
        async def iter_chunked(self, size=8192):
            # Yield some fake audio data
            fake_data = b'FAKE_MP3_DATA' * 100
            for i in range(0, len(fake_data), size):
                yield fake_data[i:i+size]

    class MockSession:
        def __init__(self, *args, **kwargs):
            call_counts['http_calls'] += 1
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def get(self, url):
            logger.info(f"MOCK: HTTP GET called: {url}")
            return MockResponse()

    # Apply patches
    patches = [
        patch('lib.gdrive.GoogleDrive.get_files', side_effect=mock_get_files),
        patch('lib.gdrive.GoogleDrive.download_file_to_string', side_effect=mock_download_file_to_string),
        patch('lib.gdrive.GoogleDrive.upload_to_drive', side_effect=mock_upload_to_drive),
        patch('lib.gdrive.GoogleDrive.upload_string_to_drive', side_effect=mock_upload_string_to_drive),
        patch('asyncio.create_subprocess_exec', side_effect=mock_subprocess_exec),
        patch('aiohttp.ClientSession', MockSession),
        patch('builtins.open', create=True),
        patch('os.unlink', create=True),
        patch('tempfile.NamedTemporaryFile', create=True),
    ]

    # Start all patches
    for p in patches:
        p.start()

    try:
        logger.info("=" * 60)
        logger.info("STARTING MOCKED MAIN() TEST")
        logger.info("=" * 60)
        
        # Import and run main
        from main import main
        result = await main()
        
        logger.info("=" * 60)
        logger.info("MOCKED MAIN() TEST COMPLETED")
        logger.info("=" * 60)
        logger.info(f"Google Drive calls: {call_counts['gdrive_calls']}")
        logger.info(f"HTTP calls: {call_counts['http_calls']}")
        logger.info(f"FFmpeg calls: {call_counts['ffmpeg_calls']}")
        logger.info("=" * 60)
        
        return result
        
    finally:
        # Stop all patches
        for p in patches:
            p.stop()

if __name__ == "__main__":
    asyncio.run(test_simple_main())
