"""Minimal operation routing: all mutations auto-approved (full access)."""
from __future__ import annotations

from typing import Any


class OperationRouter:
    """Compatibility shim retained for ExecutionOrchestrator imports."""

    def __init__(self, appserver: Any, settings: Any):
        self.appserver = appserver
        self.settings = settings

    def capabilities(self) -> dict[str, Any]:
        return {
            "appServerMode": str(getattr(self.settings, "codex_app_mode", "internal")),
            "nativeStandaloneApprovals": [],
            "execPolicyMode": "disabled",
            "fallbackApproval": False,
            "eventTransport": "sse",
            "codexAgentSessions": False,
            "mcpForwarding": True,
            "standaloneFilesystem": "available",
            "remoteFilesystemBoundary": "disabled",
            "fullAccess": True,
        }
