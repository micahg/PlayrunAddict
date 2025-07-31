# M3U8 Audio Processor Setup Instructions

## Prerequisites

1. **Python 3.8 or higher**
2. **FFmpeg** - Install from [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html)
3. **Google Cloud CLI** - Install from [https://cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install)
4. **Playrun account credentials**

## Installation

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Install FFmpeg:**
   - **Ubuntu/Debian:** `sudo apt install ffmpeg`
   - **macOS:** `brew install ffmpeg`
   - **Windows:** Download from FFmpeg website and add to PATH

3. **Install Google Cloud CLI:**
   - Follow instructions at [https://cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install)

## Google Cloud Setup (No Credentials Files Needed!)

### Step 1: Authentication
```bash
# Authenticate with your Google account
gcloud auth login

# Set up Application Default Credentials
# THIS IS DONE IN STEP 3 and probably doens't need to be here.
gcloud auth application-default login

# Set your project ID
gcloud config set project YOUR_PROJECT_ID
```

### Step 2: Enable APIs
```bash
# Enable required APIs
gcloud services enable drive.googleapis.com
gcloud services enable pubsub.googleapis.com
```

### Step 3: Enable Scopes
```bash
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/cloud-platform
```

## Environment Variables

Create a `.env` file or set these environment variables:

```bash
# Google Cloud (required)
GOOGLE_CLOUD_PROJECT_ID=your-project-id

# Webhook for real-time notifications (optional)
WEBHOOK_URL=https://your-domain.com/webhook/drive
WEBHOOK_SECRET=your-secret-key

# Email notifications (optional)
EMAIL_USERNAME=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
NOTIFICATION_EMAIL=notifications@example.com
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587

# Polling fallback (optional, default: 300 seconds)
POLL_INTERVAL=300
```

## Real-time Notifications Setup (Optional)

### Option 1: Using ngrok (Development)
```bash
# Install ngrok
npm install -g ngrok

# Start your app first
python main.py

# In another terminal, expose port 8000
ngrok http 8000

# Copy the HTTPS URL and set as WEBHOOK_URL
export WEBHOOK_URL=https://abc123.ngrok.io/webhook/drive
```

### Option 2: Public Server (Production)
Set up your server with a public domain and SSL certificate, then:
```bash
export WEBHOOK_URL=https://yourdomain.com/webhook/drive
```

### Option 3: No Webhook (Fallback)
If you don't set `WEBHOOK_URL`, the app will automatically fall back to polling mode every 5 minutes.

## Playrun Setup
Assuming you already have a playrun account, just run:

```
curl 'https://www.playrun.app/api/auth' -X POST -H 'Content-Type: application/json' -H 'Origin: https://www.playrun.app' --data-raw '{"email":"EMAIL","password":"PASS"}' -o playrun_token.json
```

## Running the Application

1. **Start the application:**
   ```bash
   python main.py
   ```

2. **The application will:**
   - Automatically use your Google credentials (no files needed!)
   - Set up Pub/Sub for notifications
   - Start monitoring Google Drive for M


# TODO

- review this document for accuracy (set it up somewhere and ensure its tight)
- _add_item_to_channel is looking for new_duration, which is too specific.
  - refactor so it comes through as duration (we should still have original duration)
- vibe some unit tests
- ensure local files are deleted
- ensure remote files are deleted (maybe we can pull the playlist before we update it)