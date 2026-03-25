from fastapi import FastAPI, HTTPException
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
ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "DMS APP", ".env")

if os.path.exists(ENV_PATH):
    print(f"DEBUG: Found .env in {ENV_PATH}")
    with open(ENV_PATH, "r") as f:
        for line in f:
            if line.startswith("INTERNAL_API_TOKEN="):
                INTERNAL_API_TOKEN = line.split("=", 1)[1].strip()
                # On enlève les éventuels guillemets
                INTERNAL_API_TOKEN = INTERNAL_API_TOKEN.strip('"').strip("'")
                break
else:
    # Fallback sur l'env var système
    INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", INTERNAL_API_TOKEN)

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
                        print(f"[{mode}] Successfully updated passwords for {public_url} via {target}")
                        return True, "OK"
            except Exception as e:
                last_error = str(e)
                print(f"Sync attempt failed for {public_url} via {target} (Insecure={is_insecure}): {e}")
                continue # Essaye la cible suivante ou le mode suivant
            
    print(f"CRITICAL: Failed to update passwords after trying all targets and SSL modes. Last error: {last_error}")
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
    conn.close()
    
    result = dict(row)
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
    conn.close()
    
    result = dict(row)
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

    conn.commit()
    row = conn.execute("SELECT * FROM instances WHERE id=?", (instance_id,)).fetchone()
    conn.close()
    
    result = dict(row)
    result["sync_ok"] = sync_ok
    result["sync_msg"] = sync_msg
    return result



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
