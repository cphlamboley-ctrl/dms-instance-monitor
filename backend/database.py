import sqlite3
import os
from datetime import date

DB_PATH = os.path.join(os.path.dirname(__file__), "instances.db")

INSTANCES = [
    {"id": i + 1, "port": 9091 + i, "url": f"https://dms.sportdata.org:{9091 + i}"}
    for i in range(29)
]
INSTANCES.append({"id": 30, "port": "test", "url": "https://dms.cphlby.com"})


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS instances (
            id          INTEGER PRIMARY KEY,
            port        INTEGER NOT NULL,
            url         TEXT NOT NULL,
            internal_url TEXT,
            status      TEXT NOT NULL DEFAULT 'available',
            used_by     TEXT,
            date_from   TEXT,
            date_to     TEXT,
            notes       TEXT,
            password    TEXT,
            pwd_arrival TEXT,
            pwd_desk    TEXT,
            pwd_display TEXT
        )
    """)

    # Seed instances if table is empty
    cursor.execute("SELECT COUNT(*) FROM instances")
    count = cursor.fetchone()[0]
    if count == 0:
        for inst in INSTANCES:
            cursor.execute(
                "INSERT INTO instances (id, port, url, status) VALUES (?, ?, ?, 'available')",
                (inst["id"], str(inst["port"]), inst["url"])
            )

    conn.commit()
    conn.close()
