from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from database import init_db, get_connection
from models import InstanceUpdate, InstanceAdmin
import os
import json
import urllib.request
import secrets
import ssl
from datetime import date

# On essaye de charger le token depuis le dossier DMS APP voisin s'il est là
INTERNAL_API_TOKEN = "super_secret_token_dms_local"

# 1. On tente d'abord de charger depuis le .env du Monitor lui-même
MONITOR_ENV = os.path.join(os.path.dirname(__file__), ".env")
ROOT_ENV = os.path.join(os.path.dirname(__file__), "..", ".env")
DMS_APP_ENV = os.path.join(os.path.dirname(__file__), "..", "..", "DMS APP", ".env")

def load_token_from_file(path):
    if os.path.exists(path):
        print(f"DEBUG: Found .env in {path}")
        with open(path, "r") as f:
            for line in f:
                if line.startswith("INTERNAL_API_TOKEN="):
                    val = line.split("=", 1)[1].strip()
                    return val.strip('"').strip("'")
    return None

# Priorité : Env var > Monitor .env > Parent .env > DMS APP .env
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN")
if not INTERNAL_API_TOKEN: INTERNAL_API_TOKEN = load_token_from_file(MONITOR_ENV)
if not INTERNAL_API_TOKEN: INTERNAL_API_TOKEN = load_token_from_file(ROOT_ENV)
if not INTERNAL_API_TOKEN: INTERNAL_API_TOKEN = load_token_from_file(DMS_APP_ENV)
if not INTERNAL_API_TOKEN: INTERNAL_API_TOKEN = "super_secret_token_dms_local"

def log_event(category: str, level: str, message: str, instance_id: int = None, details: str = None):
    """Enregistre un événement dans la base de données et dans le fichier de log."""
    try:
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 1. Log en base de données
        conn = get_connection()
        conn.execute(
            "INSERT INTO logs (timestamp, instance_id, category, level, message, details) VALUES (?, ?, ?, ?, ?, ?)",
            (now, instance_id, category, level, message, details)
        )
        conn.commit()
        conn.close()

        # 2. Log dans le fichier pour réversibilité
        log_sync_event(f"[{category}][{level.upper()}] Instance {instance_id if instance_id else 'SYS'}: {message}")
    except Exception as e:
        print(f"FAILED TO LOG EVENT: {e}")

def log_sync_event(msg: str):
    log_path = os.path.join(os.path.dirname(__file__), "sync_debug.log")
    from datetime import datetime
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")


def send_passwords_to_instance(public_url: str, passwords: dict, internal_url: str = None):
    """
    Envoie les nouveaux mots de passe à l'API interne de l'instance DMS ciblée.
    Tente l'URL interne en priorité (si on est dans le réseau Docker), 
    puis l'URL publique en cas d'échec.
    """
    targets = []
    if internal_url:
        targets.append(internal_url)
    if public_url:
        targets.append(public_url)
    
    last_error = "No target URL provided"
    
    # Contextes SSL : standard puis unvérifié si nécessaire
    ssl_contexts = [None, ssl._create_unverified_context()]
    
    for context in ssl_contexts:
        is_insecure = context is not None
        for target in targets:
            endpoint = f"{target.rstrip('/')}/api/internal/reset-credentials"
            data = json.dumps({"passwords": passwords}).encode("utf-8")
            
            req = urllib.request.Request(endpoint, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("X-Internal-Token", INTERNAL_API_TOKEN.strip())
            
            try:
                # On utilise un timeout court pour ne pas bloquer l'UI
                with urllib.request.urlopen(req, data=data, timeout=5, context=context) as response:
                    if response.status == 200:
                        mode = "INSECURE" if is_insecure else "SECURE"
                        success_msg = f"Update successful via {target}"
                        # On ne log pas instance_id ici car on n'en a pas, mais on le fera dans l'appelant
                        return True, success_msg
            except Exception as e:
                # Capture standard Python errors (might be in FR on this OS)
                last_error = f"Connection failed ({type(e).__name__})"
                continue 
            
    return False, last_error

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
    try:
        conn.execute("ALTER TABLE instances ADD COLUMN internal_url TEXT")
    except Exception:
        pass
    
    # Check if 'test' instance exists
    row = conn.execute("SELECT id FROM instances WHERE port='test'").fetchone()
    if not row:
        conn.execute("INSERT INTO instances (id, port, url, status) VALUES (30, 'test', 'https://dms.cphlby.com', 'available')")

    # Auto-fill internal_url for standard production instances (1-29) if empty
    for i in range(1, 30):
        conn.execute(
            "UPDATE instances SET internal_url=? WHERE id=? AND (internal_url IS NULL OR internal_url = '')",
            (f"http://dms-instance{i}:8000", i)
        )

    conn.commit()
    conn.close()
    
    # Masked token for debugging mismatch errors (403 Forbidden)
    mask = f"{INTERNAL_API_TOKEN[:3]}...{INTERNAL_API_TOKEN[-3:]}" if len(INTERNAL_API_TOKEN) > 6 else "*" * len(INTERNAL_API_TOKEN)
    print("--- DMS MONITOR STARTUP ---")
    print(f"DEBUG: Using TOKEN: {mask}")
    print("---------------------------")
    
    log_event("SYSTEM", "info", "Monitor startup completed.")


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
    sync_ok = True
    sync_msg = "OK"
    if keep_fields and payload.password:
        passwords_pkg = {
            "admin": payload.password,
            "arrival": payload.pwd_arrival,
            "desk": payload.pwd_desk,
            "display": payload.pwd_display
        }
        sync_ok, sync_msg = send_passwords_to_instance(row["url"], passwords_pkg, row["internal_url"])
        
    conn.commit()
    row = conn.execute("SELECT * FROM instances WHERE id=?", (instance_id,)).fetchone()
    result = dict(row)
    conn.close()
    
    # Log the event without sync details in message
    log_msg = f"Status updated to: {payload.status.upper()}"
    if payload.status == "in_use" and payload.used_by:
        log_msg = f"Assigned to: {payload.used_by}"
    
    log_event(
        category="STATUS", 
        level="success" if sync_ok else "error",
        message=f"Instance {instance_id}: {log_msg}",
        instance_id=instance_id
    )

    result["sync_ok"] = sync_ok
    result["sync_msg"] = sync_msg
    return result


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
    sync_ok, sync_msg = send_passwords_to_instance(row["url"], lock_passwords, row["internal_url"])

    conn.commit()
    row = conn.execute("SELECT * FROM instances WHERE id=?", (instance_id,)).fetchone()
    result = dict(row)
    conn.close()

    # Log the event without sync details
    log_event(
        category="STATUS", 
        level="success" if sync_ok else "error",
        message=f"Instance {instance_id}: Released (Status: AVAILABLE)",
        instance_id=instance_id
    )

    result["sync_ok"] = sync_ok
    result["sync_msg"] = sync_msg
    return result


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
    sync_ok, sync_msg = send_passwords_to_instance(row["url"], lock_passwords, row["internal_url"])

    # Log the event
    conn.commit()
    row = conn.execute("SELECT * FROM instances WHERE id=?", (instance_id,)).fetchone()
    result = dict(row)
    conn.close()

    # Log the event WITHOUT sync details
    log_event(
        category="STATUS", 
        level="success" if sync_ok else "error",
        message=f"Instance {instance_id}: Set to MAINTENANCE",
        instance_id=instance_id
    )

    result["sync_ok"] = sync_ok
    result["sync_msg"] = sync_msg
    return result



@app.get("/api/logs")
def get_logs(limit: int = 50, instance_id: int = None):
    """Récupère les derniers événements enregistrés avec les infos d'instance."""
    conn = get_connection()
    query = """
        SELECT l.*, i.port, i.used_by 
        FROM logs l
        LEFT JOIN instances i ON l.instance_id = i.id
    """
    params = []
    if instance_id:
        query += " WHERE l.instance_id=?"
        params.append(instance_id)
    query += " ORDER BY l.id DESC LIMIT ?"
    params.append(limit)
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.delete("/api/logs")
def clear_all_logs():
    """Purge tout l'historique d'activité."""
    conn = get_connection()
    conn.execute("DELETE FROM logs")
    conn.commit()
    conn.close()
    log_event("ADMIN", "warning", "Activity Journal cleared (Manual purge).")
    return {"ok": True}


@app.post("/api/external/log")
def receive_external_log(payload: dict, request: Request):
    """Reçoit un log envoyé par une instance DMS distante."""
    token = request.headers.get("X-Internal-Token", "").strip()
    if not INTERNAL_API_TOKEN or token != INTERNAL_API_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    log_event(
        category=payload.get("category", "EXTERNAL"),
        level=payload.get("level", "info"),
        message=payload.get("message", "External event"),
        instance_id=payload.get("instance_id"),
        details=payload.get("details")
    )
    return {"ok": True}


# ─── ADMIN ROUTES ─────────────────────────────────────────────────────────────

@app.post("/api/admin/instances")
def create_instance(payload: InstanceAdmin):
    """Add a new instance to the monitor."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO instances (port, url, internal_url, status) VALUES (?, ?, ?, 'available')",
            (payload.port, payload.url, payload.internal_url)
        )
        new_id = cursor.lastrowid
        log_event("ADMIN", "info", f"New instance added (Port: {payload.port})", instance_id=new_id)
        conn.commit()
        row = conn.execute("SELECT * FROM instances WHERE id=?", (new_id,)).fetchone()
        return dict(row)
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@app.put("/api/admin/instances/{instance_id}")
def update_instance_config(instance_id: int, payload: InstanceAdmin):
    """Update an instance's configuration (port, urls)."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM instances WHERE id=?", (instance_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Instance not found")

    conn.execute(
        "UPDATE instances SET port=?, url=?, internal_url=? WHERE id=?",
        (payload.port, payload.url, payload.internal_url, instance_id)
    )
    log_event("ADMIN", "info", f"Configuration updated (Port: {payload.port})", instance_id=instance_id)
    conn.commit()
    updated = conn.execute("SELECT * FROM instances WHERE id=?", (instance_id,)).fetchone()
    conn.close()
    return dict(updated)


@app.delete("/api/admin/instances/{instance_id}")
def delete_instance(instance_id: int):
    """Remove an instance from the monitor."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM instances WHERE id=?", (instance_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Instance not found")

    conn.execute("DELETE FROM instances WHERE id=?", (instance_id,))
    log_event("ADMIN", "warning", f"Instance deleted (ID: {instance_id}, Port: {row['port']})")
    conn.commit()
    conn.close()
    return {"status": "deleted", "id": instance_id}


@app.post("/api/admin/test-connection")
async def test_instance_connection(payload: dict):
    """Test simple GET connectivity."""
    url = payload.get("url")
    if not url: raise HTTPException(status_code=400, detail="URL required")
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as res:
            return {"status": "ok", "code": res.status}
    except Exception as e:
        return {"status": "failed", "detail": str(e)}

@app.post("/api/admin/test-sync")
async def test_instance_sync(payload: dict):
    """Test POST connectivity with Internal Token."""
    url = payload.get("url")
    if not url: raise HTTPException(status_code=400, detail="URL required")
    last_error = "Unknown"
    
    # On teste les deux modes SSL
    for context in [None, ssl._create_unverified_context()]:
        try:
            endpoint = f"{url.rstrip('/')}/api/internal/reset-credentials"
            data = json.dumps({"passwords": {}}).encode("utf-8")
            req = urllib.request.Request(endpoint, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("X-Internal-Token", INTERNAL_API_TOKEN.strip())
            
            with urllib.request.urlopen(req, timeout=3, context=context) as res:
                return {"status": "ok", "code": res.status, "insecure": context is not None}
        except Exception as e:
            last_error = str(e)
            continue
            
    return {"status": "failed", "detail": last_error}

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/manager")
def serve_manager():
    return FileResponse(os.path.join(FRONTEND_DIR, "manager.html"))


@app.get("/logs")
def serve_logs():
    return FileResponse(os.path.join(FRONTEND_DIR, "logs.html"))
