from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from database import init_db, get_connection
from models import InstanceUpdate
import os
from datetime import date

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
        pass # Column already exists
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
                "UPDATE instances SET status='available', used_by=NULL, date_from=NULL, date_to=NULL, password=NULL WHERE id=?",
                (inst["id"],)
            )
            conn.commit()
            conn.close()
            inst["status"] = "available"
            inst["used_by"] = None
            inst["date_from"] = None
            inst["date_to"] = None
            inst["password"] = None

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
    conn.execute(
        """
        UPDATE instances
        SET status=?, used_by=?, date_from=?, date_to=?, notes=?, password=?
        WHERE id=?
        """,
        (
            payload.status,
            payload.used_by   if keep_fields else None,
            payload.date_from if keep_fields else None,
            payload.date_to   if keep_fields else None,
            payload.notes     if keep_fields else None,
            payload.password  if keep_fields else None,
            instance_id,
        )
    )
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
        "UPDATE instances SET status='available', used_by=NULL, date_from=NULL, date_to=NULL, notes=NULL, password=NULL WHERE id=?",
        (instance_id,)
    )
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
        "UPDATE instances SET status='maintenance', used_by=NULL, date_from=NULL, date_to=NULL, notes=NULL, password=NULL WHERE id=?",
        (instance_id,)
    )
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
