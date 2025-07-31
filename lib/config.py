import os
import uuid
import multiprocessing


class Config:
    SCOPES = ['https://www.googleapis.com/auth/drive']
    PROJECT_ID = os.getenv('GOOGLE_CLOUD_PROJECT_ID')
    TOPIC_NAME = os.getenv('PUBSUB_TOPIC_NAME', 'm3u8-processor')
    SUBSCRIPTION_NAME = os.getenv('PUBSUB_SUBSCRIPTION_NAME', 'm3u8-processor-sub')
    WEBHOOK_URL = os.getenv('WEBHOOK_URL')
    WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', str(uuid.uuid4()))
    DEFAULT_SPEED = 1.5
    MAX_WORKERS = max(1, multiprocessing.cpu_count() - 1)
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    EMAIL_USERNAME = os.getenv('EMAIL_USERNAME')
    EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
    NOTIFICATION_EMAIL = os.getenv('NOTIFICATION_EMAIL')
    POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', '300'))
