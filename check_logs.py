import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'backend', 'instances.db')

def check():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    print("--- LOGS TABLE CONTENT ---")
    rows = conn.execute("SELECT * FROM logs ORDER BY timestamp DESC").fetchall()
    if not rows:
        print("Table 'logs' is EMPTY")
    for row in rows:
        print(dict(row))
    conn.close()

if __name__ == "__main__":
    check()
