from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from database import init_db, get_connection
from models import InstanceUpdate
import os
import json
import urllib.request
import secrets
from datetime import date

INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "super_secret_token_dms_local")

def send_passwords_to_instance(instance_url: str, passwords: dict):
    """Envoie les nouveaux mots de passe à l'API interne de l'instance DMS ciblée."""
    endpoint = f"{instance_url.rstrip('/')}/api/internal/reset-credentials"
    data = json.dumps({"passwords": passwords}).encode("utf-8")
    
    req = urllib.request.Request(endpoint, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Internal-Token", INTERNAL_API_TOKEN)
    
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status == 200
    except Exception as e:
        print(f"Failed to update passwords for {instance_url}: {e}")
        return False

app = FastAPI(title="DMS Instance Tracker", version="1.0.0")

# CORS — allow frontend (same machine or any origin in dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Startup: initialize database
@app.on_event("startup")
def startup_event():
    init_db()
    # Migrate legacy 'unknown' status to 'maintenance'
    conn = get_connection()
    conn.execute("UPDATE instances SET status='maintenance' WHERE status='unknown'")
    try:
        conn.execute("ALTER TABLE instances ADD COLUMN password TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE instances ADD COLUMN pwd_arrival TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE instances ADD COLUMN pwd_desk TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE instances ADD COLUMN pwd_display TEXT")
    except Exception:
        pass
    
    # Check if 'test' instance exists
    row = conn.execute("SELECT id FROM instances WHERE port='test'").fetchone()
    if not row:
        conn.execute("INSERT INTO instances (id, port, url, status) VALUES (30, 'test', 'https://dms.cphlby.com', 'available')")

    conn.commit()
    conn.close()


# ─── API Routes ───────────────────────────────────────────────────────────────

@app.get("/api/instances")
def get_all_instances():
    """Return all 29 instances with their current status."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM instances ORDER BY id").fetchall()
    conn.close()
    instances = [dict(row) for row in rows]

    # Auto-expire: if date_to is past today, mark as available
    today = date.today().isoformat()
    for inst in instances:
        if inst["status"] == "in_use" and inst["date_to"] and inst["date_to"] < today:
            conn = get_connection()
            conn.execute(
                "UPDATE instances SET status='available', used_by=NULL, date_from=NULL, date_to=NULL, password=NULL, pwd_arrival=NULL, pwd_desk=NULL, pwd_display=NULL WHERE id=?",
                (inst["id"],)
            )
            conn.commit()
            conn.close()
            inst["status"] = "available"
            inst["used_by"] = None
            inst["date_from"] = None
            inst["date_to"] = None
            inst["password"] = None
            inst["pwd_arrival"] = None
            inst["pwd_desk"] = None
            inst["pwd_display"] = None

    return instances


@app.get("/api/instances/{instance_id}")
def get_instance(instance_id: int):
    """Return details for a single instance."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM instances WHERE id=?", (instance_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found")
    return dict(row)


@app.put("/api/instances/{instance_id}")
def update_instance(instance_id: int, payload: InstanceUpdate):
    """Update an instance's assignment info."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM instances WHERE id=?", (instance_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Instance not found")

    # Only 'in_use' keeps assignment fields; available and maintenance clear them
    keep_fields = payload.status == "in_use"
    # Génération automatique des mots de passe enfants si password est founi et qu'ils sont vides
    if keep_fields and payload.password:
        import random
        if not payload.pwd_arrival:
            payload.pwd_arrival = f"A{random.randint(100000, 999999)}"
        if not payload.pwd_desk:
            payload.pwd_desk = f"D{random.randint(100000, 999999)}"
        if not payload.pwd_display:
            payload.pwd_display = f"M{random.randint(100000, 999999)}"
            
    conn.execute(
        """
        UPDATE instances
        SET status=?, used_by=?, date_from=?, date_to=?, notes=?, password=?, pwd_arrival=?, pwd_desk=?, pwd_display=?
        WHERE id=?
        """,
        (
            payload.status,
            payload.used_by   if keep_fields else None,
            payload.date_from if keep_fields else None,
            payload.date_to   if keep_fields else None,
            payload.notes     if keep_fields else None,
            payload.password  if keep_fields else None,
            payload.pwd_arrival if keep_fields else None,
            payload.pwd_desk  if keep_fields else None,
            payload.pwd_display if keep_fields else None,
            instance_id,
        )
    )
    
    # ─── COMMUNICATION AVEC L'INSTANCE DMS ───
    if keep_fields and payload.password:
        passwords_pkg = {
            "admin": payload.password,
            "arrival": payload.pwd_arrival,
            "desk": payload.pwd_desk,
            "display": payload.pwd_display
        }
        send_passwords_to_instance(row["url"], passwords_pkg)
        
    conn.commit()
    updated = conn.execute("SELECT * FROM instances WHERE id=?", (instance_id,)).fetchone()
    conn.close()
    return dict(updated)


@app.post("/api/instances/{instance_id}/free")
def free_instance(instance_id: int):
    """Quickly mark an instance as available and clear all assignment data."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM instances WHERE id=?", (instance_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Instance not found")

    conn.execute(
        "UPDATE instances SET status='available', used_by=NULL, date_from=NULL, date_to=NULL, notes=NULL, password=NULL, pwd_arrival=NULL, pwd_desk=NULL, pwd_display=NULL WHERE id=?",
        (instance_id,)
    )
    
    # ─── VERROUILLAGE DE L'INSTANCE DMS ───
    # Génère un mot de passe impossible à deviner pour révoquer les accès actuels
    lock_passwords = {
        "admin": secrets.token_urlsafe(32),
        "arrival": secrets.token_urlsafe(32),
        "desk": secrets.token_urlsafe(32),
        "display": secrets.token_urlsafe(32)
    }
    send_passwords_to_instance(row["url"], lock_passwords)

    conn.commit()
    updated = conn.execute("SELECT * FROM instances WHERE id=?", (instance_id,)).fetchone()
    conn.close()
    return dict(updated)


@app.post("/api/instances/{instance_id}/maintenance")
def maintenance_instance(instance_id: int):
    """Mark an instance as in maintenance (fields cleared)."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM instances WHERE id=?", (instance_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Instance not found")

    conn.execute(
        "UPDATE instances SET status='maintenance', used_by=NULL, date_from=NULL, date_to=NULL, notes=NULL, password=NULL, pwd_arrival=NULL, pwd_desk=NULL, pwd_display=NULL WHERE id=?",
        (instance_id,)
    )
    
    # ─── VERROUILLAGE DE L'INSTANCE DMS ───
    lock_passwords = {
        "admin": secrets.token_urlsafe(32),
        "arrival": secrets.token_urlsafe(32),
        "desk": secrets.token_urlsafe(32),
        "display": secrets.token_urlsafe(32)
    }
    send_passwords_to_instance(row["url"], lock_passwords)

    conn.commit()
    updated = conn.execute("SELECT * FROM instances WHERE id=?", (instance_id,)).fetchone()
    conn.close()
    return dict(updated)


# ─── Serve Frontend ──────────────────────────────────────────────────────────

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
