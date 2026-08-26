# Copyright (c) 2026 ChatCodex contributors.
"""Persistence adapter for approval audit records."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .database import Database


class AuditRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record_pending(
        self,
        *,
        audit_id: str,
        conversation_id: str,
        operation_id: str,
        source: str,
        state: str,
        kind: str,
        request_id: str,
        summary: str,
        payload: dict[str, Any],
        action_digest: str,
        context_version: int,
        request_version: int,
        created_at: float,
    ) -> None:
        with self.db.conn() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO approval_audit
                   (id,conversation_id,operation_id,source,state,kind,request_id,summary,payload,decision,decided_by,action_digest,context_version,request_version,created_at,decided_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    audit_id,
                    conversation_id,
                    operation_id,
                    source,
                    state,
                    kind,
                    request_id,
                    summary,
                    json.dumps(payload, ensure_ascii=False),
                    None,
                    None,
                    action_digest,
                    context_version,
                    request_version,
                    int(created_at),
                    None,
                ),
            )

    def record_decision(
        self,
        *,
        audit_id: str,
        decision: dict[str, Any],
        decided_by: str | None,
        state: str,
        request_version: int,
    ) -> None:
        with self.db.conn() as connection:
            connection.execute(
                """UPDATE approval_audit SET decision=?,decided_by=?,decided_at=?,state=?,request_version=? WHERE id=?""",
                (
                    json.dumps(decision, ensure_ascii=False),
                    decided_by,
                    int(time.time()),
                    state,
                    request_version,
                    audit_id,
                ),
            )
