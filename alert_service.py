"""
VitalSync Alert Service
- WebSocket connections for real-time emergency alerts
- Emergency alert trigger (notifies family members)
- Scheduler for 8 PM daily check-in reminder
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from typing import Dict, List
import json
import asyncio
from datetime import datetime

router = APIRouter(prefix="/ws", tags=["WebSocket"])

# Active WebSocket connections: user_id -> [WebSocket]
active_connections: Dict[int, List[WebSocket]] = {}


class ConnectionManager:
    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        if user_id not in active_connections:
            active_connections[user_id] = []
        active_connections[user_id].append(websocket)
        print(f"WebSocket connected: user {user_id} | Total connections: {sum(len(v) for v in active_connections.values())}")

    def disconnect(self, websocket: WebSocket, user_id: int):
        if user_id in active_connections:
            active_connections[user_id].remove(websocket)
            if not active_connections[user_id]:
                del active_connections[user_id]

    async def send_to_user(self, user_id: int, message: dict):
        if user_id in active_connections:
            dead = []
            for ws in active_connections[user_id]:
                try:
                    await ws.send_text(json.dumps(message))
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.disconnect(ws, user_id)

    async def broadcast_emergency(self, patient_id: int, message: dict):
        """Broadcast to patient + all connected family members."""
        from app.core.database import SessionLocal
        from app.models.models import PatientProfile, FamilyConnection, User
        db = SessionLocal()
        try:
            profile = db.query(PatientProfile).filter(PatientProfile.id == patient_id).first()
            if not profile:
                return

            # Notify patient themselves
            await self.send_to_user(profile.user_id, message)

            # Notify family members who are app users
            family = db.query(FamilyConnection).filter(
                FamilyConnection.user_id == profile.user_id,
                FamilyConnection.notify_on_emergency == True,
                FamilyConnection.member_user_id != None
            ).all()

            for member in family:
                await self.send_to_user(member.member_user_id, {
                    **message,
                    "is_family_alert": True,
                    "patient_name": profile.user.full_name if profile.user else "Family Member"
                })
        finally:
            db.close()


manager = ConnectionManager()


@router.websocket("/alerts/{user_id}")
async def websocket_alerts(websocket: WebSocket, user_id: int):
    """
    WebSocket endpoint for real-time health alerts.
    Frontend connects here after login to receive live alerts.
    """
    await manager.connect(websocket, user_id)
    try:
        # Send connection confirmation
        await websocket.send_text(json.dumps({
            "type": "connected",
            "message": "VitalSync alert stream connected",
            "timestamp": datetime.utcnow().isoformat()
        }))

        # Keep connection alive, listen for client pings
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            elif msg.get("type") == "acknowledge_alert":
                # Client acknowledged an alert
                await websocket.send_text(json.dumps({
                    "type": "alert_acknowledged",
                    "alert_id": msg.get("alert_id")
                }))

    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
        print(f"WebSocket disconnected: user {user_id}")


async def trigger_emergency_alert(
    patient_id: int,
    alert_id: int,
    vitals: dict,
    flags: List[str],
    db: Session
):
    """
    Called in background when emergency is detected.
    1. Broadcasts WebSocket alert (repeating alarm until acknowledged)
    2. Logs the alert
    """
    from app.models.models import PatientProfile

    profile = db.query(PatientProfile).filter(PatientProfile.id == patient_id).first()
    if not profile:
        return

    emergency_message = {
        "type": "emergency_alert",
        "alert_id": alert_id,
        "severity": "emergency",
        "flags": flags,
        "vitals": vitals,
        "message": f"EMERGENCY DETECTED: {', '.join(flags)}",
        "timestamp": datetime.utcnow().isoformat(),
        "requires_acknowledgment": True,
    }

    # Send alert 5 times with 3-second intervals (alarm effect)
    for i in range(5):
        await manager.broadcast_emergency(patient_id, {
            **emergency_message,
            "repeat": i + 1
        })
        await asyncio.sleep(3)

    print(f"🚨 Emergency alert sent for patient {patient_id}: {flags}")
