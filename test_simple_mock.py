#!/usr/bin/env python3
"""
Simple test runner that patches the imports dynamically.
"""

import asyncio
import logging
import sys
from unittest.mock import patch, MagicMock

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def run_mocked_main():
    """Run main() with all external dependencies mocked"""
    
    call_counts = {'gdrive': 0, 'http': 0, 'ffmpeg': 0, 'files': 0}
    
    # Mock data
    M3U8_CONTENT = """#EXTM3U
#EXTINF:180.0,Episode 1
https://example.com/audio1.mp3
#EXTINF:240.0,Episode 2
https://example.com/audio2.mp3
#EXT-X-ENDLIST"""

    RSS_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel><title>Test</title>
<item><title>Existing</title><enclosure url="https://example.com/existing.mp3" type="audio/mpeg" length="900"/></item>
</channel></rss>'''

    # Mock responses
    def mock_get_files(query, most_recent=False):
        call_counts['gdrive'] += 1
        logger.info(f"MOCK get_files: {query}")
        if '.m3u' in query:
            return [{'id': 'mock_m3u8_123', 'name': 'test.m3u8', 'modifiedTime': '2025-07-31T12:00:00.000Z'}]
        elif 'xml' in query:
            return [{'id': 'mock_rss_456', 'name': 'feed.xml', 'modifiedTime': '2025-07-31T11:00:00.000Z'}]
        return []

    async def mock_download(file_id):
        call_counts['gdrive'] += 1
        logger.info(f"MOCK download: {file_id}")
        if 'mock_m3u8' in file_id:
            return M3U8_CONTENT
        elif 'mock_rss' in file_id:
            return RSS_XML
        return "MOCK_CONTENT"

    async def mock_upload_file(file_path, filename, mimetype='audio/mpeg'):
        call_counts['gdrive'] += 1
        logger.info(f"MOCK upload file: {filename}")
        return f"uploaded_{filename}_id"

    async def mock_upload_string(content, filename, mimetype='text/plain', file_id=None):
        call_counts['gdrive'] += 1
        logger.info(f"MOCK upload string: {filename}")
        return file_id or f"uploaded_{filename}_id"

    class MockProcess:
        def __init__(self):
            self.returncode = 0
        async def communicate(self):
            return b'FFmpeg done', b''

    async def mock_subprocess(*args, **kwargs):
        call_counts['ffmpeg'] += 1
        logger.info(f"MOCK FFmpeg: {args[0] if args else 'ffmpeg'}")
        return MockProcess()

    class MockFile:
        def __init__(self, *args, **kwargs):
            call_counts['files'] += 1
            self.name = '/tmp/mock_temp_file.mp3'
        def close(self):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def write(self, data):
            pass

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
            data = b'FAKE_MP3' * 1000
            for i in range(0, len(data), size):
                yield data[i:i+size]

    class MockSession:
        def __init__(self, *args, **kwargs):
            call_counts['http'] += 1
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def get(self, url):
            logger.info(f"MOCK HTTP GET: {url}")
            return MockResponse()

    # Create comprehensive patches
    patches = {
        # Mock all the Google/external imports
        'google': MagicMock(),
        'google.auth': MagicMock(),
        'google.auth.default': MagicMock(return_value=(MagicMock(), 'mock-project')),
        'googleapiclient': MagicMock(),
        'googleapiclient.discovery': MagicMock(),
        'googleapiclient.discovery.build': MagicMock(),
        'googleapiclient.http': MagicMock(),
        'aiohttp': MagicMock(),
        'requests': MagicMock(),
        'fastapi': MagicMock(),
        'google.cloud': MagicMock(),
        'pydantic': MagicMock(),
    }
    
    # Patch sys.modules
    original_modules = sys.modules.copy()
    
    try:
        # Add mock modules
        sys.modules.update(patches)
        
        # Now patch the specific functions we need
        with patch('tempfile.NamedTemporaryFile', MockFile), \
             patch('asyncio.create_subprocess_exec', mock_subprocess), \
             patch('aiohttp.ClientSession', MockSession), \
             patch('os.unlink', MagicMock()), \
             patch('builtins.open', MockFile):
            
            # Import main and its dependencies
            from main import main
            
            # Patch the GoogleDrive methods after import
            with patch('lib.gdrive.GoogleDrive.get_files', mock_get_files), \
                 patch('lib.gdrive.GoogleDrive.download_file_to_string', mock_download), \
                 patch('lib.gdrive.GoogleDrive.upload_to_drive', mock_upload_file), \
                 patch('lib.gdrive.GoogleDrive.upload_string_to_drive', mock_upload_string):
                
                logger.info("=" * 60)
                logger.info("RUNNING MAIN() WITH ALL MOCKS")
                logger.info("=" * 60)
                
                result = await main()
                
                logger.info("=" * 60)
                logger.info("MAIN() COMPLETED SUCCESSFULLY")
                logger.info("=" * 60)
                logger.info(f"Google Drive calls: {call_counts['gdrive']}")
                logger.info(f"HTTP calls: {call_counts['http']}")
                logger.info(f"FFmpeg calls: {call_counts['ffmpeg']}")
                logger.info(f"File operations: {call_counts['files']}")
                logger.info("=" * 60)
                
                return result
    
    finally:
        # Restore original modules
        sys.modules.clear()
        sys.modules.update(original_modules)

if __name__ == "__main__":
    asyncio.run(run_mocked_main())
