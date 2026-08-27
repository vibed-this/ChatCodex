from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Awaitable, Callable, TypeVar

MAX_RECORDS = 1000
T = TypeVar("T")


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

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "tool": self.tool,
            "arguments": self.arguments,
            "success": self.success,
            "durationMs": self.duration_ms,
            "result": self.result,
            "error": self.error,
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
) -> T:
    started = time.perf_counter()
    timestamp = datetime.now(timezone.utc).isoformat()
    safe_arguments = _jsonable(arguments)
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
            )
        )
        raise
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
            result=_jsonable(
                result.model_dump(mode="json")
                if hasattr(result, "model_dump")
                else result
            ),
        )
    )
    return result


AUDIT_LOG = McpAuditLog()
