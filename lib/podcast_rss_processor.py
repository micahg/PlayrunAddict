#!/usr/bin/env python3
"""
Podcast RSS Processor
Generates podcast RSS XML files from processed audio files.
"""

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Dict, List, Any
import logging
from .gdrive import GoogleDrive

logger = logging.getLogger(__name__)

RSS_QUERY = "name = 'playrun_addict.xml' and trashed=false"

NAMESPACES = {
    'playrunaddict': 'http://playrunaddict.com/rss/1.0',
    'itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd'
}

class PodcastRSSProcessor:
    """
    Handles the generation of podcast RSS XML files from processed audio files.
    """
    
    def __init__(self, channel_title: str = "Playrun Addict Custom Feed"):
        self.channel_title = channel_title
    
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
        rss.set("xmlns:playrunaddict", "http://playrunaddict.com/rss/1.0")
        
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
        
        # GUID
        guid = ET.SubElement(item, "guid")
        guid.text = file_data.get('uuid', f"episode-{hash(file_data.get('title', ''))}")
        guid.set("isPermaLink", "false")

        # Original duration (custom namespace)
        original_duration = ET.SubElement(item, "playrunaddict:originalduration")
        original_duration.text = str(file_data.get('original_duration', 0))
        
        # Publication date (use current time if not provided)
        # pub_date = ET.SubElement(item, "pubDate")
        # if 'published' in file_data:
        #     # If published is already a datetime string, use it
        #     if isinstance(file_data['published'], str):
        #         try:
        #             dt = datetime.fromisoformat(file_data['published'].replace('Z', '+00:00'))
        #             pub_date.text = dt.strftime("%a, %d %b %Y %H:%M:%S %z")
        #         except ValueError:
        #             pub_date.text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
        #     else:
        #         pub_date.text = file_data['published'].strftime("%a, %d %b %Y %H:%M:%S %z")
        # else:
        #     pub_date.text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
        
        # Enclosure (the actual audio file)
        enclosure = ET.SubElement(item, "enclosure")
        
        # Convert Google Drive URL to download URL
        download_url = GoogleDrive.generate_download_url(file_data['drive_file_id'])
        enclosure.set("url", download_url)
        
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

    def get_rss_feed_id(self):
        files = GoogleDrive.instance().get_files(RSS_QUERY, most_recent=True)
        if not files:
            logger.warning("No RSS feed file found in Google Drive.")
            return None
        return files[0]['id']
    
    def download_rss_feed(self, file_id: str) -> ET.Element:
        """
        Download the RSS feed file from Google Drive and parse it as XML.
        
        Args:
            file_id: The ID of the RSS feed file
            
        Returns:
            The parsed XML root element
        """
        try:
            xml_content = GoogleDrive.instance().download_file(file_id)
            root = ET.fromstring(xml_content)
            logger.info(f"Successfully downloaded and parsed RSS feed {file_id}")
            return root

        except Exception as e:
            logger.error(f"Error downloading and parsing RSS feed file {file_id}: {e}")
            raise

    def extract_episode_mapping(self, root: ET.Element) -> Dict[str, Dict[str, str]]:
        """
        Extract episode mapping from RSS XML root element.
        
        Args:
            root: The RSS XML root element
            
        Returns:
            Dictionary mapping episode titles to their download info:
            {
                "Episode Title": {
                    "download_url": "https://...",
                    "length": "12345"
                }
            }
        """
        episode_mapping = {}
        
        try:
            # Find the channel element
            channel = root.find('channel')
            if channel is None:
                logger.warning("No channel element found in RSS XML")
                return episode_mapping
            
            # Find all item elements
            items = channel.findall('item')
            logger.info(f"Found {len(items)} episodes in RSS feed")
            
            for item in items:
                # Get title
                title_elem = item.find('title')
                title = title_elem.text if title_elem is not None and title_elem.text else "Untitled Episode"
                
                # Get original duration from custom namespace
                original_duration_elem = item.find('playrunaddict:originalduration', NAMESPACES)
                original_duration = original_duration_elem.text if original_duration_elem is not None and original_duration_elem.text else "0"
                
                # Get enclosure info
                enclosure = item.find('enclosure')
                if enclosure is not None:
                    download_url = enclosure.get('url', '')
                    length = enclosure.get('length', '0')
                    
                    episode_mapping[title] = {
                        'download_url': download_url,
                        'length': length,
                        'original_duration': original_duration
                    }
                else:
                    logger.warning(f"No enclosure found for episode: {title}")
            
            logger.info(f"Successfully extracted {len(episode_mapping)} episode mappings")
            return episode_mapping
            
        except Exception as e:
            logger.error(f"Error extracting episode mapping from RSS XML: {e}")
            raise