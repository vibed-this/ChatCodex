# Copyright (c) 2026 ChatCodex contributors.
"""Shared JSON-RPC contracts for the WebSocket App Server client."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.data = data


# 回调签名
ServerRequestHandler = Callable[
    [dict[str, Any]], Awaitable[dict[str, Any]]
]  # 入参完整 request,返回 result(将被包成 response)
NotificationHandler = Callable[[str, Any], Awaitable[None]]  # (method, params)
