#!/usr/bin/env python3
"""
Podcast RSS Processor
Generates podcast RSS XML files from processed audio files.
"""

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Dict, List, Any
import re
import logging

logger = logging.getLogger(__name__)


class PodcastRSSProcessor:
    """
    Handles the generation of podcast RSS XML files from processed audio files.
    """
    
    def __init__(self, channel_title: str = "Playrun Addict Custom Feed"):
        self.channel_title = channel_title
        
    def extract_drive_id(self, drive_url: str) -> str:
        """
        Extract the Google Drive file ID from a drive.google.com URL.
        
        Args:
            drive_url: Google Drive URL (e.g., https://drive.google.com/uc?id=FILE_ID)
            
        Returns:
            The extracted file ID
            
        Raises:
            ValueError: If the drive ID cannot be extracted
        """
        # Pattern to match various Google Drive URL formats
        patterns = [
            r'id=([a-zA-Z0-9_-]+)',  # ?id=FILE_ID format
            r'/file/d/([a-zA-Z0-9_-]+)',  # /file/d/FILE_ID format
            r'/d/([a-zA-Z0-9_-]+)',  # /d/FILE_ID format
        ]
        
        for pattern in patterns:
            match = re.search(pattern, drive_url)
            if match:
                return match.group(1)
        
        raise ValueError(f"Could not extract Drive ID from URL: {drive_url}")
    
    def generate_download_url(self, drive_url: str) -> str:
        """
        Convert a Google Drive URL to a direct download URL.
        
        Args:
            drive_url: Original Google Drive URL
            
        Returns:
            Direct download URL in the format required
        """
        drive_id = self.extract_drive_id(drive_url)
        return f"https://drive.usercontent.google.com/download?id={drive_id}&export=download&authuser=0&confirm=t"
    
    def create_rss_xml(self, processed_files: List[Dict[str, Any]], 
                       feed_description: str = "Custom podcast feed generated from processed audio files",
                       feed_link: str = "https://example.com") -> str:
        """
        Generate RSS XML from processed files.
        
        Args:
            processed_files: List of processed file dictionaries from a job
            feed_description: Description for the RSS feed
            feed_link: Link for the RSS feed
            
        Returns:
            RSS XML as a string
        """
        # Create root RSS element
        rss = ET.Element("rss")
        rss.set("version", "2.0")
        rss.set("xmlns:itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
        
        # Create channel element
        channel = ET.SubElement(rss, "channel")
        
        # Add channel metadata
        title_elem = ET.SubElement(channel, "title")
        title_elem.text = self.channel_title
        
        description_elem = ET.SubElement(channel, "description")
        description_elem.text = feed_description
        
        link_elem = ET.SubElement(channel, "link")
        link_elem.text = feed_link
        
        language_elem = ET.SubElement(channel, "language")
        language_elem.text = "en-us"
        
        # Add build date
        last_build_date = ET.SubElement(channel, "lastBuildDate")
        last_build_date.text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
        
        # Add iTunes specific tags
        itunes_author = ET.SubElement(channel, "itunes:author")
        itunes_author.text = "Playrun Addict"
        
        itunes_summary = ET.SubElement(channel, "itunes:summary")
        itunes_summary.text = feed_description
        
        itunes_category = ET.SubElement(channel, "itunes:category")
        itunes_category.set("text", "Technology")
        
        itunes_explicit = ET.SubElement(channel, "itunes:explicit")
        itunes_explicit.text = "false"
        
        # Add items for each processed file
        for file_data in processed_files:
            self._add_item_to_channel(channel, file_data)
        
        # Convert to string with proper XML declaration
        xml_str = ET.tostring(rss, encoding='unicode')
        return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}'
    
    def _add_item_to_channel(self, channel: ET.Element, file_data: Dict[str, Any]):
        """
        Add an item element to the channel for a processed file.
        
        Args:
            channel: The channel XML element
            file_data: Dictionary containing processed file information
        """
        item = ET.SubElement(channel, "item")
        
        # Title
        title = ET.SubElement(item, "title")
        title.text = file_data.get('title', 'Untitled Episode')
        
        # Description (use title as description if not provided)
        description = ET.SubElement(item, "description")
        description.text = file_data.get('description', file_data.get('title', 'No description available'))
        
        # GUID
        guid = ET.SubElement(item, "guid")
        guid.text = file_data.get('uuid', f"episode-{hash(file_data.get('title', ''))}")
        guid.set("isPermaLink", "false")
        
        # Publication date (use current time if not provided)
        pub_date = ET.SubElement(item, "pubDate")
        if 'published' in file_data:
            # If published is already a datetime string, use it
            if isinstance(file_data['published'], str):
                try:
                    dt = datetime.fromisoformat(file_data['published'].replace('Z', '+00:00'))
                    pub_date.text = dt.strftime("%a, %d %b %Y %H:%M:%S %z")
                except ValueError:
                    pub_date.text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
            else:
                pub_date.text = file_data['published'].strftime("%a, %d %b %Y %H:%M:%S %z")
        else:
            pub_date.text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
        
        # Enclosure (the actual audio file)
        enclosure = ET.SubElement(item, "enclosure")
        
        # Convert Google Drive URL to download URL
        processed_url = file_data.get('processed_url', '')
        if processed_url:
            try:
                download_url = self.generate_download_url(processed_url)
                enclosure.set("url", download_url)
            except ValueError as e:
                logger.warning(f"Could not generate download URL for {processed_url}: {e}")
                enclosure.set("url", processed_url)  # Fallback to original URL
        
        # Set enclosure type (MIME type)
        enclosure.set("type", "audio/mpeg")
        
        # Set length (duration in seconds, or file size if available)
        duration = file_data.get('new_duration', file_data.get('duration', 0))
        if isinstance(duration, (int, float)):
            # If we have duration, use it (RSS length is typically file size in bytes, 
            # but for podcasts, duration in seconds is also acceptable)
            enclosure.set("length", str(int(duration)))
        else:
            # Default length if not available
            enclosure.set("length", "0")
        
        # iTunes specific item tags
        itunes_duration = ET.SubElement(item, "itunes:duration")
        if duration:
            # Convert seconds to HH:MM:SS format
            hours = int(duration // 3600)
            minutes = int((duration % 3600) // 60)
            seconds = int(duration % 60)
            itunes_duration.text = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            itunes_duration.text = "00:00:00"
        
        itunes_explicit = ET.SubElement(item, "itunes:explicit")
        itunes_explicit.text = "false"
    
    def save_rss_to_file(self, processed_files: List[Dict[str, Any]], 
                         output_path: str,
                         feed_description: str = "Custom podcast feed generated from processed audio files",
                         feed_link: str = "https://example.com"):
        """
        Generate RSS XML and save it to a file.
        
        Args:
            processed_files: List of processed file dictionaries
            output_path: Path to save the RSS file
            feed_description: Description for the RSS feed
            feed_link: Link for the RSS feed
        """
        rss_xml = self.create_rss_xml(processed_files, feed_description, feed_link)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(rss_xml)
        
        logger.info(f"RSS feed saved to {output_path}")
    
    def format_rss_xml(self, xml_string: str) -> str:
        """
        Format RSS XML with proper indentation for readability.
        
        Args:
            xml_string: Raw XML string
            
        Returns:
            Formatted XML string
        """
        try:
            import xml.dom.minidom as minidom
            dom = minidom.parseString(xml_string)
            return dom.toprettyxml(indent="  ")
        except ImportError:
            # Fallback if minidom is not available
            return xml_string


# Example usage
if __name__ == "__main__":
    # Example processed files data
    sample_processed_files = [
        {
            'title': 'Episode 1: Introduction to AI',
            'processed_url': 'https://drive.google.com/uc?id=1ABC123DEF456',
            'new_duration': 1800,  # 30 minutes
            'uuid': 'episode-001',
            'published': '2024-01-15T10:00:00Z'
        },
        {
            'title': 'Episode 2: Machine Learning Basics',
            'processed_url': 'https://drive.google.com/uc?id=2XYZ789GHI012',
            'new_duration': 2400,  # 40 minutes
            'uuid': 'episode-002',
            'published': '2024-01-22T10:00:00Z'
        }
    ]
    
    # Create processor and generate RSS
    processor = PodcastRSSProcessor()
    rss_xml = processor.create_rss_xml(sample_processed_files)
    
    # Format and print
    formatted_xml = processor.format_rss_xml(rss_xml)
    print(formatted_xml)
