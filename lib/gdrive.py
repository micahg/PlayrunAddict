import io
import logging
from google.auth import default
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
from .config import Config

logger = logging.getLogger(__name__)

class GoogleDrive:
    _instance = None

    def __new__(cls):
        raise RuntimeError("Use GoogleDrive.get_instance() instead of GoogleDrive()")

    def service(self):
        """
        TODO DELETE THIS -- refactor so we're not just handling the service around.z
        """
        return self.instance().drive_service

    @classmethod
    def instance(cls):
        if cls._instance is None:
            try:
                credentials, project_id = default(scopes=Config.SCOPES)
                if not Config.PROJECT_ID:
                    Config.PROJECT_ID = project_id
                cls.drive_service = build('drive', 'v3', credentials=credentials)
                logger.info(f"Google services initialized with project: {Config.PROJECT_ID}")
            except Exception as e:
                logger.error(f"Failed to initialize Google services: {e}")
                logger.info("Make sure you've run 'gcloud auth application-default login'")
                raise
            cls._instance = object.__new__(cls)
        return cls._instance

    @classmethod
    def generate_download_url(cls, drive_id: str) -> str:
        """
        Convert a Google Drive URL to a direct download URL.
        
        Args:
            drive_id: Google Drive file ID
            
        Returns:
            Direct download URL in the format required
        """
        return f"https://drive.usercontent.google.com/download?id={drive_id}&export=download&authuser=0&confirm=t"


    async def upload_to_drive(self, file_path: str, filename: str, mimetype='audio/mpeg') -> str:
        try:
            file_metadata = {
                'name': filename,
                'parents': []
            }
            media = MediaFileUpload(file_path, mimetype)
            file = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            file_id = file.get('id')
            permission = {
                'type': 'anyone',
                'role': 'reader'
            }
            self.drive_service.permissions().create(
                fileId=file_id,
                body=permission
            ).execute()
            return file_id
        except Exception as e:
            logger.error(f"Error uploading to Google Drive: {e}")
            raise

    async def upload_string_to_drive(self, content: str, filename: str, mimetype='text/plain') -> str:
        try:
            file_metadata = {
                'name': filename,
                'parents': []
            }
            media = MediaIoBaseUpload(io.BytesIO(content.encode('utf-8')),
                          mimetype=mimetype,
                          resumable=True)
            file = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            file_id = file.get('id')
            permission = {
                'type': 'anyone',
                'role': 'reader'
            }
            self.drive_service.permissions().create(
                fileId=file_id,
                body=permission
            ).execute()
            return file_id
        except Exception as e:
            logger.error(f"Error uploading string to Google Drive: {e}")
            raise