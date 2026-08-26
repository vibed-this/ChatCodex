"""OAuth client persistence repository."""
from __future__ import annotations

import json
from .database import Database

class OAuthClientRepository:
    def __init__(self, db: Database):
        self.db = db

    def get(self, client_id: str) -> dict | None:
        if not client_id:
            return None
        with self.db.conn() as connection:
            row = connection.execute("SELECT value FROM kv_config WHERE key=?", (f"oauth-client:{client_id}",)).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row["value"])
        except Exception:
            return None
        return value if isinstance(value, dict) and value.get("client_id") == client_id else None

    def save(self, client: dict, max_clients: int) -> None:
        client_id = str(client["client_id"])
        with self.db.conn() as connection:
            rows = connection.execute("SELECT key FROM kv_config WHERE key LIKE 'oauth-client:%' ORDER BY rowid ASC").fetchall()
            excess = max(0, len(rows) - max_clients + 1)
            for row in rows[:excess]:
                connection.execute("DELETE FROM kv_config WHERE key=?", (row["key"],))
            connection.execute("INSERT OR REPLACE INTO kv_config(key,value) VALUES(?,?)", (f"oauth-client:{client_id}", json.dumps(client, separators=(",", ":"))))
