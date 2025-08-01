#!/usr/bin/env python3
"""
Targeted test for the main() function workflow.
Mocks only the essential dependencies needed for main().
"""

import asyncio
import logging
import sys
import os
import tempfile
from unittest.mock import patch, MagicMock, AsyncMock
import xml.etree.ElementTree as ET

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Mock the Config class
class MockConfig:
    SCOPES = ['https://www.googleapis.com/auth/drive']
    DEFAULT_SPEED = 1.5
    MAX_WORKERS = 3
    PROJECT_ID = 'mock-project'

# Mock the GoogleDrive class
class MockGoogleDrive:
    _instance = None
    
    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def get_files(self, query, most_recent=False):
        logger.info(f"MOCK GoogleDrive.get_files: {query}")
        if '.m3u' in query:
            return [{'id': 'mock_m3u8_123', 'name': 'test.m3u8', 'modifiedTime': '2025-07-31T12:00:00.000Z'}]
        elif 'xml' in query:
            return [{'id': 'mock_rss_456', 'name': 'feed.xml', 'modifiedTime': '2025-07-31T11:00:00.000Z'}]
        return []
    
    async def download_file_to_string(self, file_id):
        logger.info(f"MOCK GoogleDrive.download_file_to_string: {file_id}")
        if 'mock_m3u8' in file_id:
            return """#EXTM3U
#EXTINF:180.0,Episode 1
https://example.com/audio1.mp3
#EXTINF:240.0,Episode 2  
https://example.com/audio2.mp3
#EXT-X-ENDLIST"""
        elif 'mock_rss' in file_id:
            return '''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Test</title></channel></rss>'''
        return "MOCK_CONTENT"
    
    async def upload_to_drive(self, file_path, filename, mimetype='audio/mpeg'):
        logger.info(f"MOCK GoogleDrive.upload_to_drive: {filename}")
        return f"uploaded_{filename}_id"
    
    async def upload_string_to_drive(self, content, filename, mimetype='text/plain', file_id=None):
        logger.info(f"MOCK GoogleDrive.upload_string_to_drive: {filename}")
        return file_id or f"uploaded_{filename}_id"
    
    @staticmethod
    def generate_download_url(drive_id):
        return f"https://drive.google.com/mock_download/{drive_id}"

# Mock the AudioProcessor class
class MockAudioProcessor:
    def __init__(self):
        pass
    
    async def check_for_new_m3u8_files(self):
        logger.info("MOCK AudioProcessor.check_for_new_m3u8_files")
        # Return mock processed files
        return [
            {
                'title': 'Episode 1',
                'original_duration': 180,
                'new_duration': 120,
                'uuid': 'mock-uuid-1',
                'speed': 1.5,
                'temp_file': '/tmp/mock_episode1.mp3',
                'drive_file_id': 'mock_drive_id_1'
            },
            {
                'title': 'Episode 2',
                'original_duration': 240,
                'new_duration': 160,
                'uuid': 'mock-uuid-2',
                'speed': 1.5,
                'temp_file': '/tmp/mock_episode2.mp3',
                'drive_file_id': 'mock_drive_id_2'
            }
        ]

# Mock the PodcastRSSProcessor class
class MockPodcastRSSProcessor:
    def __init__(self, channel_title="Test Feed"):
        self.channel_title = channel_title
    
    def get_rss_feed_id(self):
        logger.info("MOCK PodcastRSSProcessor.get_rss_feed_id")
        return 'mock_rss_feed_id'
    
    async def download_rss_feed(self, file_id):
        logger.info(f"MOCK PodcastRSSProcessor.download_rss_feed: {file_id}")
        # Return a mock XML element
        rss_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
    <channel>
        <title>Test Feed</title>
        <item>
            <title>Existing Episode</title>
            <enclosure url="https://example.com/existing.mp3" type="audio/mpeg" length="900"/>
        </item>
    </channel>
</rss>'''
        return ET.fromstring(rss_xml)
    
    def extract_episode_mapping(self, root):
        logger.info("MOCK PodcastRSSProcessor.extract_episode_mapping")
        return {
            'Existing Episode': {
                'download_url': 'https://example.com/existing.mp3',
                'length': '900'
            }
        }
    
    def create_rss_xml(self, processed_files):
        logger.info(f"MOCK PodcastRSSProcessor.create_rss_xml: {len(processed_files)} files")
        return f'<?xml version="1.0"?><rss><channel><title>{self.channel_title}</title></channel></rss>'

async def test_main_workflow():
    """Test the main() workflow with mocked dependencies"""
    
    call_counts = {'gdrive': 0, 'audio_processor': 0, 'rss_processor': 0}
    
    # Mock os.unlink
    def mock_unlink(path):
        logger.info(f"MOCK os.unlink: {path}")
    
    try:
        # Patch the imports in main.py
        with patch('lib.config.Config', MockConfig), \
             patch('lib.gdrive.GoogleDrive', MockGoogleDrive), \
             patch('lib.audio_processor.AudioProcessor', MockAudioProcessor), \
             patch('lib.podcast_rss_processor.PodcastRSSProcessor', MockPodcastRSSProcessor), \
             patch('os.unlink', mock_unlink):
            
            logger.info("=" * 60)
            logger.info("TESTING MAIN() WORKFLOW")
            logger.info("=" * 60)
            
            # Import and run main
            from main import main
            result = await main()
            
            logger.info("=" * 60)
            logger.info("MAIN() WORKFLOW COMPLETED SUCCESSFULLY!")
            logger.info("=" * 60)
            
            return result
            
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    asyncio.run(test_main_workflow())
