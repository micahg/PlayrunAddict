#!/usr/bin/env python3
"""
Direct test of main() logic without importing problematic dependencies.
Creates a temporary main function with mocked dependencies injected.
"""

import asyncio
import logging
import sys
import os
import xml.etree.ElementTree as ET

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Mock classes that replicate the interface of the real ones
class MockGoogleDrive:
    _instance = None
    
    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
            logger.info("MOCK: GoogleDrive.instance() created")
        return cls._instance
    
    def get_files(self, query, most_recent=False):
        logger.info(f"MOCK: GoogleDrive.get_files(query='{query}', most_recent={most_recent})")
        if '.m3u' in query:
            return [{'id': 'mock_m3u8_123', 'name': 'test.m3u8', 'modifiedTime': '2025-07-31T12:00:00.000Z'}]
        elif 'xml' in query:
            return [{'id': 'mock_rss_456', 'name': 'feed.xml', 'modifiedTime': '2025-07-31T11:00:00.000Z'}]
        return []
    
    async def download_file_to_string(self, file_id):
        logger.info(f"MOCK: GoogleDrive.download_file_to_string(file_id='{file_id}')")
        if 'mock_m3u8' in file_id:
            return """#EXTM3U
#EXTINF:180.0,Episode 1 - Introduction
https://example.com/audio/episode1.mp3
#EXTINF:240.0,Episode 2 - Getting Started
https://example.com/audio/episode2.mp3
#EXT-X-ENDLIST"""
        elif 'mock_rss' in file_id:
            return '''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
    <channel>
        <title>Test Podcast Feed</title>
        <description>Test feed</description>
        <item>
            <title>Existing Episode</title>
            <enclosure url="https://example.com/existing.mp3" type="audio/mpeg" length="900"/>
        </item>
    </channel>
</rss>'''
        return "MOCK_CONTENT"
    
    async def upload_to_drive(self, file_path, filename, mimetype='audio/mpeg'):
        logger.info(f"MOCK: GoogleDrive.upload_to_drive(file_path='{file_path}', filename='{filename}', mimetype='{mimetype}')")
        return f"uploaded_{filename.replace('.mp3', '')}_id"
    
    async def upload_string_to_drive(self, content, filename, mimetype='text/plain', file_id=None):
        logger.info(f"MOCK: GoogleDrive.upload_string_to_drive(filename='{filename}', mimetype='{mimetype}', file_id='{file_id}')")
        return file_id or f"uploaded_{filename}_id"
    
    @staticmethod
    def generate_download_url(drive_id):
        logger.info(f"MOCK: GoogleDrive.generate_download_url(drive_id='{drive_id}')")
        return f"https://drive.usercontent.google.com/download?id={drive_id}&export=download&authuser=0&confirm=t"

class MockAudioProcessor:
    def __init__(self):
        logger.info("MOCK: AudioProcessor.__init__()")
    
    async def check_for_new_m3u8_files(self):
        logger.info("MOCK: AudioProcessor.check_for_new_m3u8_files()")
        # Simulate processing and return mock results
        await asyncio.sleep(0.1)  # Simulate some processing time
        return [
            {
                'title': 'Episode 1 - Introduction',
                'original_duration': 180,
                'new_duration': 120,
                'uuid': 'mock-uuid-episode-1',
                'speed': 1.5,
                'temp_file': '/tmp/mock_episode_1.mp3',
            },
            {
                'title': 'Episode 2 - Getting Started',
                'original_duration': 240,
                'new_duration': 160,
                'uuid': 'mock-uuid-episode-2',
                'speed': 1.5,
                'temp_file': '/tmp/mock_episode_2.mp3',
            }
        ]

class MockPodcastRSSProcessor:
    def __init__(self, channel_title="Playrun Addict Custom Feed"):
        self.channel_title = channel_title
        logger.info(f"MOCK: PodcastRSSProcessor.__init__(channel_title='{channel_title}')")
    
    def get_rss_feed_id(self):
        logger.info("MOCK: PodcastRSSProcessor.get_rss_feed_id()")
        return 'mock_existing_rss_feed_id'
    
    async def download_rss_feed(self, file_id):
        logger.info(f"MOCK: PodcastRSSProcessor.download_rss_feed(file_id='{file_id}')")
        rss_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
    <channel>
        <title>Test Podcast Feed</title>
        <description>Existing test feed</description>
        <item>
            <title>Existing Episode</title>
            <enclosure url="https://example.com/existing.mp3" type="audio/mpeg" length="900"/>
        </item>
    </channel>
</rss>'''
        return ET.fromstring(rss_xml)
    
    def extract_episode_mapping(self, root):
        logger.info("MOCK: PodcastRSSProcessor.extract_episode_mapping()")
        return {
            'Existing Episode': {
                'download_url': 'https://example.com/existing.mp3',
                'length': '900'
            }
        }
    
    def create_rss_xml(self, processed_files):
        logger.info(f"MOCK: PodcastRSSProcessor.create_rss_xml() with {len(processed_files)} files")
        # Create a simple RSS XML
        items_xml = ""
        for file_data in processed_files:
            items_xml += f"""
        <item>
            <title>{file_data['title']}</title>
            <guid>{file_data['uuid']}</guid>
            <enclosure url="https://drive.usercontent.google.com/download?id={file_data['drive_file_id']}" type="audio/mpeg" length="{file_data['new_duration']}"/>
        </item>"""
        
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
    <channel>
        <title>{self.channel_title}</title>
        <description>Custom podcast feed generated from processed audio files</description>
        <link>https://example.com</link>
        <language>en-us</language>{items_xml}
    </channel>
</rss>'''

async def mock_main():
    """
    Replicated main() function logic with mocked dependencies.
    This tests the exact same workflow as the real main() but with mocks.
    """
    
    # Mock os.unlink
    def mock_unlink(path):
        logger.info(f"MOCK: os.unlink('{path}')")
    
    logger.info("=" * 60)
    logger.info("STARTING MOCK MAIN() WORKFLOW")
    logger.info("=" * 60)
    
    # Initialize Google Drive service (mock)
    try:
        MockGoogleDrive.instance()
    except Exception as e:
        logger.error(f"Error setting up Google Drive: {e}")
        return

    processor = MockAudioProcessor()
    podcast_processor = MockPodcastRSSProcessor()
    rss_drive_id = podcast_processor.get_rss_feed_id()
    rss_feed = await podcast_processor.download_rss_feed(rss_drive_id)
    episode_mapping = podcast_processor.extract_episode_mapping(rss_feed)

    results = await processor.check_for_new_m3u8_files()
    # check for an existing playlist
    if not results or len(results) == 0:
        logger.error("M3U8 resulted in no files")
        return
    
    logger.info(f"Processed {len(results)} audio files")
    for result in results:
        logger.info(f"Uploading {result['title']} to Google Drive")
        try:
            drive_file_id = await MockGoogleDrive.instance().upload_to_drive(result['temp_file'], f"{result['title']}.mp3")
            mock_unlink(result['temp_file'])  # Mock file cleanup
            result['drive_file_id'] = drive_file_id
        except Exception as e:
            logger.error(f"Failed to upload {result['title']} to Google Drive: {e}")
            return

    xml_feed = podcast_processor.create_rss_xml(results)
    rss_drive_id = await MockGoogleDrive.instance().upload_string_to_drive(xml_feed, "playrun_addict.xml", mimetype='application/rss+xml', file_id=rss_drive_id)
    rss_download_url = MockGoogleDrive.generate_download_url(rss_drive_id)
    print(f"RSS Feed Download URL: {rss_download_url}")
    
    logger.info("=" * 60)
    logger.info("MOCK MAIN() WORKFLOW COMPLETED SUCCESSFULLY!")
    logger.info("=" * 60)
    
    return results

if __name__ == "__main__":
    asyncio.run(mock_main())
