from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, TypeVar
from uuid import uuid4

MAX_RECORDS = 1000
T = TypeVar("T")
_BATCH_CALL_ID: ContextVar[str | None] = ContextVar("batch_call_id", default=None)


def _jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return str(value)


@dataclass(slots=True)
class McpToolCallRecord:
    timestamp: str
    tool: str
    arguments: dict[str, Any]
    success: bool
    duration_ms: float
    result: Any = None
    error: str | None = None
    call_id: str = ""
    parent_call_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "tool": self.tool,
            "arguments": self.arguments,
            "success": self.success,
            "durationMs": self.duration_ms,
            "result": self.result,
            "error": self.error,
            "callId": self.call_id,
            "parentCallId": self.parent_call_id,
        }


@dataclass(slots=True)
class McpAuditLog:
    _records: deque[McpToolCallRecord] = field(
        default_factory=lambda: deque(maxlen=MAX_RECORDS)
    )
    _lock: Lock = field(default_factory=Lock)

    def append(self, record: McpToolCallRecord) -> None:
        with self._lock:
            self._records.append(record)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [record.as_dict() for record in reversed(self._records)]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def count(self) -> int:
        with self._lock:
            return len(self._records)


async def record_mcp_tool_call(
    audit_log: McpAuditLog,
    name: str,
    arguments: dict[str, Any],
    call_next: Callable[[str, dict[str, Any]], Awaitable[T]],
    *,
    call_id: str | None = None,
) -> T:
    started = time.perf_counter()
    timestamp = datetime.now(timezone.utc).isoformat()
    safe_arguments = _jsonable(arguments)
    current_call_id = call_id or uuid4().hex
    parent_call_id = _BATCH_CALL_ID.get()
    token = _BATCH_CALL_ID.set(current_call_id) if name == "batch_call" else None
    try:
        result = await call_next(name, arguments)
    except Exception as exc:
        audit_log.append(
            McpToolCallRecord(
                timestamp=timestamp,
                tool=name,
                arguments=safe_arguments,
                success=False,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                error=str(exc),
                call_id=current_call_id,
                parent_call_id=parent_call_id,
            )
        )
        raise
    finally:
        if token is not None:
            _BATCH_CALL_ID.reset(token)
    audit_log.append(
        McpToolCallRecord(
            timestamp=timestamp,
            tool=name,
            arguments=safe_arguments,
            success=not bool(
                getattr(result, "is_error", False)
                or (isinstance(result, dict) and result.get("isError", False))
            ),
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            call_id=current_call_id,
            parent_call_id=parent_call_id,
            result=_jsonable(
                result.model_dump(mode="json")
                if hasattr(result, "model_dump")
                else result
            ),
        )
    )
    return result


AUDIT_LOG = McpAuditLog()
