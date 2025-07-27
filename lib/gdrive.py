import logging
from google.auth import default
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from .config import Config

logger = logging.getLogger(__name__)

class GoogleDrive:
    _instance = None

    def __new__(cls):
        raise RuntimeError("Use GoogleDrive.get_instance() instead of GoogleDrive()")

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

    def service(self):
        return self.instance().drive_service