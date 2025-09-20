# zoom_attendance.py
from fastapi import FastAPI, Request, HTTPException
from datetime import datetime
import uvicorn
import hashlib
import hmac
from typing import List, Dict, Any

app = FastAPI()

# ===== CONFIGURATION =====
# Get this from your Zoom App → App Credentials → Verification Token
ZOOM_VERIFICATION_TOKEN = "V4LV-kEORHuMQpSXHn6qvQ"
PORT = 8000

# ===== IN-MEMORY STORAGE =====
attendance_log: List[Dict[str, Any]] = []

# ===== HELPER FUNCTIONS =====
def hash_token(token: str) -> str:
    """Hash the token using your verification token"""
    return hmac.new(
        ZOOM_VERIFICATION_TOKEN.encode('utf-8'),
        token.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

def log_join(meeting_id: str, user_id: str, user_name: str, join_time: str):
    """Log when a participant joins"""
    log_entry = {
        "event": "joined",
        "meeting_id": meeting_id,
        "user_id": user_id,
        "user_name": user_name,
        "join_time": join_time,
        "leave_time": None,
        "timestamp": datetime.now().isoformat()
    }
    attendance_log.append(log_entry)
    print(f"✅ JOIN: {user_name} ({user_id}) joined meeting {meeting_id} at {join_time}")

def log_leave(meeting_id: str, user_id: str, leave_time: str):
    """Log when a participant leaves and calculate duration"""
    # Find the most recent join without a leave time for this user
    for entry in reversed(attendance_log):
        if (entry["event"] == "joined" and 
            entry["meeting_id"] == meeting_id and 
            entry["user_id"] == user_id and 
            entry["leave_time"] is None):
            
            entry["leave_time"] = leave_time
            entry["event"] = "left"
            
            duration = calculate_duration(entry["join_time"], leave_time)
            print(f"❌ LEAVE: {entry['user_name']} ({user_id}) left meeting {meeting_id}")
            print(f"   ⏱️  Duration: {duration:.1f} minutes")
            return
    
    print(f"⚠️  LEAVE: No matching join found for user {user_id} in meeting {meeting_id}")

def calculate_duration(join_time: str, leave_time: str) -> float:
    """Calculate duration in minutes between join and leave times"""
    try:
        j = datetime.fromisoformat(join_time.replace("Z", "+00:00"))
        l = datetime.fromisoformat(leave_time.replace("Z", "+00:00"))
        return (l - j).total_seconds() / 60  # minutes
    except (ValueError, AttributeError):
        return 0.0

def calculate_durations(meeting_id: str) -> Dict[str, Dict[str, Any]]:
    """Calculate total durations for all participants in a meeting"""
    durations = {}
    
    for entry in attendance_log:
        if (entry["meeting_id"] == meeting_id and 
            entry["join_time"] and entry["leave_time"]):
            
            user_id = entry["user_id"]
            duration = calculate_duration(entry["join_time"], entry["leave_time"])
            
            if user_id not in durations:
                durations[user_id] = {
                    "user_name": entry["user_name"],
                    "total_minutes": 0.0,
                    "sessions": 0
                }
            
            durations[user_id]["total_minutes"] += duration
            durations[user_id]["sessions"] += 1
    
    return durations

# ===== FASTAPI ENDPOINTS =====
@app.post("/zoom/webhook")
async def zoom_webhook(request: Request):
    """Main webhook endpoint for Zoom events"""
    try:
        body = await request.json()
        
        # Handle Zoom verification challenge
        if body.get("event") == "endpoint.url_validation":
            plain_token = body.get("payload", {}).get("plainToken")
            if not plain_token:
                raise HTTPException(status_code=400, detail="No plainToken provided")
            
            encrypted_token = hash_token(plain_token)
            print(f"🔐 Verification challenge received and responded")
            return {
                "plainToken": plain_token,
                "encryptedToken": encrypted_token
            }
        
        # Handle actual Zoom events
        event = body.get("event")
        payload = body.get("payload", {}).get("object", {})
        
        if not payload:
            raise HTTPException(status_code=400, detail="No payload object found")
        
        meeting_id = str(payload.get("id", "unknown"))
        participant = payload.get("participant", {})
        user_id = participant.get("user_id") or participant.get("id") or "unknown"
        user_name = participant.get("user_name", "Unknown User")
        
        print(f"📨 Received event: {event} for meeting: {meeting_id}")
        
        if event == "meeting.participant_joined":
            join_time = participant.get("join_time")
            if join_time:
                log_join(meeting_id, user_id, user_name, join_time)
            else:
                print(f"⚠️  No join_time provided for join event")
                
        elif event == "meeting.participant_left":
            leave_time = participant.get("leave_time")
            if leave_time:
                log_leave(meeting_id, user_id, leave_time)
            else:
                print(f"⚠️  No leave_time provided for leave event")
                
        else:
            print(f"ℹ️  Unhandled event type: {event}")
        
        return {"status": "ok", "event": event}
    
    except Exception as e:
        print(f"💥 Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/report/{meeting_id}")
def report(meeting_id: str):
    """Get attendance report for a specific meeting"""
    durations = calculate_durations(meeting_id)
    
    print(f"\n📊 REPORT for Meeting: {meeting_id}")
    print("=" * 50)
    
    if not durations:
        print("No attendance data found for this meeting")
    else:
        for user_id, data in durations.items():
            status = data.get("status", "completed")
            if status == "active":
                print(f"👤 {data['user_name']}: {data['total_minutes']:.1f} minutes (ACTIVE NOW)")
            else:
                print(f"👤 {data['user_name']}: {data['total_minutes']:.1f} minutes ({data['sessions']} sessions)")
    
    return {
        "meeting_id": meeting_id,
        "attendance": durations,
        "total_participants": len(durations)
    }

@app.get("/logs")
def get_logs(meeting_id: str = None):
    """Get all logs or filter by meeting_id"""
    if meeting_id:
        filtered_logs = [log for log in attendance_log if log["meeting_id"] == meeting_id]
        return {"logs": filtered_logs, "filtered_by_meeting": meeting_id}
    return {"logs": attendance_log, "total_entries": len(attendance_log)}

@app.get("/")
def home():
    """Home page with instructions"""
    return {
        "message": "Zoom Attendance Tracker API",
        "endpoints": {
            "POST /zoom/webhook": "Receive Zoom webhook events",
            "GET /report/{meeting_id}": "Get attendance report",
            "GET /logs": "View all logs (add ?meeting_id=xxx to filter)",
            "GET /": "This help page"
        },
        "status": "running"
    }

@app.delete("/logs")
def clear_logs():
    """Clear all logs (for testing)"""
    global attendance_log
    count = len(attendance_log)
    attendance_log = []
    print(f"🧹 Cleared {count} log entries")
    return {"message": f"Cleared {count} log entries", "remaining": 0}

# ===== MAIN =====
if __name__ == "__main__":
    print("🚀 Starting Zoom Attendance Tracker Server")
    print("=" * 50)
    
    if ZOOM_VERIFICATION_TOKEN == "YOUR_VERIFICATION_TOKEN_HERE":
        print("⚠️  WARNING: Please set ZOOM_VERIFICATION_TOKEN in the code!")
        print("   Get it from: Zoom App → App Credentials → Verification Token")
    
    print(f"🌐 Server will run on: http://localhost:{PORT}")
    print("📋 Available endpoints:")
    print(f"   POST http://localhost:{PORT}/zoom/webhook")
    print(f"   GET  http://localhost:{PORT}/report/{{meeting_id}}")
    print(f"   GET  http://localhost:{PORT}/logs")
    print(f"   GET  http://localhost:{PORT}/")
    print(f"   DELETE http://localhost:{PORT}/logs (clear logs)")
    print("\n🔐 Remember to:")
    print("   1. Create Zoom app at https://marketplace.zoom.us/")
    print("   2. Enable webhooks and subscribe to events")
    print("   3. Set webhook URL to your server's /zoom/webhook")
    print("   4. Copy Verification Token to ZOOM_VERIFICATION_TOKEN")
    print("   5. Use ngrok for local testing: 'ngrok http 8000'")
    print("=" * 50)
    
    # uvicorn.run(app, host="0.0.0.0", port=PORT, reload=True)
    uvicorn.run("attendance_app:app", host="0.0.0.0", port=PORT, reload=True)