import logging
from fastapi import FastAPI, HTTPException, Request
from lib.audio_processor import AudioProcessor
import asyncio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="M3U8 Audio Processor", version="1.0.0")
processor = AudioProcessor()

@app.on_event("startup")
async def startup_event():
    await processor.initialize()

@app.get("/")
async def root():
    return {"message": "M3U8 Audio Processor is running"}

@app.post("/webhook/drive")
async def drive_webhook(request: Request):
    return await processor.handle_drive_notification(request)

@app.get("/status")
async def get_status():
    jobs = processor.list_jobs()
    return {
        "total_jobs": len(jobs),
        "pending": len([j for j in jobs if j.status == "pending"]),
        "processing": len([j for j in jobs if j.status == "processing"]),
        "completed": len([j for j in jobs if j.status == "completed"]),
        "failed": len([j for j in jobs if j.status == "failed"])
    }

@app.get("/jobs")
async def list_jobs():
    jobs = processor.list_jobs()
    return {"jobs": [job.dict() for job in jobs]}

@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = processor.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.dict()

@app.post("/auth/playrun")
async def authenticate_playrun(credentials: dict):
    email = credentials.get("email")
    password = credentials.get("password")
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")
    success = await processor.authenticate_playrun(email, password)
    if success:
        return {"message": "Authentication successful"}
    else:
        raise HTTPException(status_code=401, detail="Authentication failed")

@app.post("/manual-check")
async def manual_check():
    await processor.check_for_new_m3u8_files()
    return {"message": "Manual check triggered"}

@app.get("/test-drive")
async def test_drive():
    try:
        if not processor.drive_service:
            return {"error": "Drive service not initialized"}
        results = processor.drive_service.files().list(
            pageSize=5,
            fields="files(id, name)"
        ).execute()
        files = results.get('files', [])
        return {
            "status": "success",
            "message": "Drive API connection working",
            "files_found": len(files),
            "sample_files": [{"id": f["id"], "name": f["name"]} for f in files[:3]]
        }
    except Exception as e:
        return {"error": f"Drive API test failed: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)