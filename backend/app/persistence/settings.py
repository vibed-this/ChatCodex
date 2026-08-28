# Copyright (c) 2026 ChatCodex contributors.
"""运行时设置:全新项目，仅保留当前所需键。"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .database import Database

DEFAULTS: dict[str, Any] = {
    "public_route_kind": "",
    "tunnel_kind": "",
    "chatgpt_tunnel_enabled": False,
    "chatgpt_tunnel_id": "",
    "tunnel_client_command": "tunnel-client",
    "tunnel_client_release": "v0.0.11-dev",
    "tunnel_auto_restart": True,
    "web_access_token": "",
    "mcp_auth_mode": "token",
    "mcp_access_token": "",
    "oauth_password": "",
    "oauth_callback_protection": False,
    "public_url": "",
    "external_mcp_servers": [],
}


class SettingsStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def all(self) -> dict[str, Any]:
        out = dict(DEFAULTS)
        with self.db.conn() as c:
            rows = c.execute(
                "SELECT key,value FROM kv_config WHERE key LIKE 'set:%'"
            ).fetchall()
        for r in rows:
            key = r["key"][4:]
            if key not in DEFAULTS:
                continue
            with contextlib.suppress(Exception):
                out[key] = json.loads(r["value"])
        return out

    def get(self, key: str) -> Any:
        return self.all().get(key, DEFAULTS.get(key))

    def get_override(self, key: str) -> Any:
        with self.db.conn() as c:
            row = c.execute(
                "SELECT value FROM kv_config WHERE key=?", (f"set:{key}",)
            ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["value"])
        except Exception:
            return None

    def set(self, key: str, value: Any) -> None:
        with self.db.conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO kv_config(key,value) VALUES(?,?)",
                (f"set:{key}", json.dumps(value, ensure_ascii=False)),
            )

    def update(self, kv: dict[str, Any]) -> dict[str, Any]:
        for k, v in kv.items():
            if k in DEFAULTS:
                self.set(k, v)
        return self.all()
