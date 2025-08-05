### unip *backup
### load db
### episodes have title in name,podcast_id,position_to_resume
### podcast_id from episodes corresponds to _id in podcasts table

import sqlite3
import zipfile
import tempfile
import os
import shutil
import logging
from typing import List, Dict, Any
from .gdrive import GoogleDrive

logger = logging.getLogger(__name__)

class PodcastAddictProcessor:
    """Extract listening progress from PodcastAddict backup files stored in Google Drive"""
    
    def __init__(self):
        self.gdrive = GoogleDrive.instance()

    async def add_listening_progress(self, ep_map: Dict[str, Dict[str, str]]):
        """
        Download most recent PodcastAddict backup and add the listening progress to the episode map

        :param ep_map: The episode map containing episode information
        :type ep_map: Dict[str, Dict[str, str]]
        :return: List of dictionaries with podcast, episode, and offset information
        :rtype: List[Dict[str, Any]]
        """
        backup_file_path = None
        temp_dir = None
        
        try:
            # Search for most recent PodcastAddict backup file
            backup_file_path = await self._download_latest_backup()
            
            # Extract backup to temp folder
            temp_dir = await self._extract_backup(backup_file_path)
            
            # Delete the downloaded backup file
            if backup_file_path and os.path.exists(backup_file_path):
                os.remove(backup_file_path)
                logger.info(f"Deleted downloaded backup file: {backup_file_path}")
            
            # Find and load the database
            db_path = self._find_database_file(temp_dir)
            
            # Query for listening progress
            progress_data = self._query_listening_progress(db_path)

            self._update_episode_map(progress_data, ep_map)
            
            return progress_data
            
        except Exception as e:
            logger.error(f"Failed to extract listening progress: {e}")
            raise
        finally:
            # Cleanup temp directory
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                logger.info(f"Deleted temp directory: {temp_dir}")
    
    async def _download_latest_backup(self) -> str:
        """Find and download the most recent PodcastAddict backup file"""
        # Search for backup files
        query = "name contains 'PodcastAddict' and name contains '.backup'"
        files = self.gdrive.get_files(query, most_recent=True)
        
        if not files:
            raise FileNotFoundError("No PodcastAddict backup files found in Google Drive")
        
        latest_file = files[0]
        file_id = latest_file['id']
        file_name = latest_file['name']
        
        logger.info(f"Found latest backup: {file_name}")
        
        # Download to temp file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.backup')
        temp_file_path = temp_file.name
        temp_file.close()
        
        # Download file content as bytes
        file_content = self.gdrive.download_file_to_bytes(file_id)
        
        # Write to temp file
        with open(temp_file_path, 'wb') as f:
            f.write(file_content)
        
        logger.info(f"Downloaded backup to: {temp_file_path}")
        return temp_file_path
    
    async def _extract_backup(self, backup_file_path: str) -> str:
        """Extract backup file to temporary directory"""
        temp_dir = tempfile.mkdtemp()
        
        try:
            with zipfile.ZipFile(backup_file_path, 'r') as zip_file:
                zip_file.extractall(temp_dir)
                logger.info(f"Extracted backup to: {temp_dir}")
                
            return temp_dir
            
        except zipfile.BadZipFile:
            raise ValueError(f"Invalid zip file: {backup_file_path}")
    
    def _find_database_file(self, temp_dir: str) -> str:
        """Find the SQLite database file in the extracted backup"""
        for file_name in os.listdir(temp_dir):
            if file_name.endswith('.db'):
                db_path = os.path.join(temp_dir, file_name)
                logger.info(f"Found database file: {db_path}")
                return db_path
        
        raise FileNotFoundError("No .db file found in backup")
    
    def _query_listening_progress(self, db_path: str) -> List[Dict[str, Any]]:
        """Query the database for episodes with listening progress"""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        try:
            cursor = conn.cursor()
            
            query = """
            SELECT 
                p.name as podcast,
                e.position_to_resume as offset,
                e.name as episode
            FROM episodes e
            JOIN podcasts p ON p._id = e.podcast_id
            JOIN ordered_list ol ON ol.id = e._id
            WHERE e.position_to_resume > 0 AND ol.type = 1
            ORDER BY e.position_to_resume DESC
            """
            
            cursor.execute(query)
            rows = cursor.fetchall()
            
            # Convert to list of dictionaries
            progress_data = []
            for row in rows:
                progress_data.append({
                    'podcast': row['podcast'],
                    'offset': row['offset'],
                    'episode': row['episode']
                })
            
            logger.info(f"Found {len(progress_data)} episodes with listening progress")
            return progress_data
            
        finally:
            conn.close()
    
    def _update_episode_map(self, progress_data: List[Dict[str, Any]], ep_map: Dict[str, Dict[str, str]]) -> None:
        """
        Update episode map with offset values from progress data

        :param progress_data: List of dictionaries containing podcast, episode, and offset information
        :type progress_data: List[Dict[str, Any]]
        :param ep_map: The episode map to update with offset values
        :type ep_map: Dict[str, Dict[str, str]]
        """
        for progress in progress_data:
            podcast = progress['podcast']
            episode = progress['episode']
            offset = progress['offset']
            
            # Create key by combining podcast and episode with a dash
            key = f"{podcast} - {episode}"
            
            # Update or create episode map entry with offset
            ep_map.setdefault(key, {})['offset'] = offset