# Copyright (c) 2026 ChatCodex contributors.
"""Application composition root.

This module owns construction of long-lived services. Route modules should consume
the resulting Runtime instead of constructing persistence, execution, or transport
objects themselves.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .approval import ApprovalBridge
from .appserver import AppServerManager
from .config import Settings, load_settings
from .events import EventBroker
from .execution import ExecutionService
from .mcp.server import build_mcp
from .native import NativeRuntimeManager
from .oauth import Authenticator, WebAuthenticator
from .persistence.database import Database
from .persistence.settings import SettingsStore
from .tunnel import TunnelManager

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


@dataclass
class Runtime:
    settings: Settings
    db: Database
    settings_store: SettingsStore
    native: NativeRuntimeManager
    auth: Authenticator
    web_auth: WebAuthenticator
    appserver: AppServerManager
    tunnels: TunnelManager
    events: EventBroker
    approval: ApprovalBridge
    execution: ExecutionService
    mcp: FastMCP
    generated_web_token: bool
    generated_mcp_token: bool

    def close(self) -> None:
        self.db.close()


def create_runtime(base_settings: Settings | None = None) -> Runtime:
    settings = base_settings or load_settings()
    db = Database(settings)
    settings_store = SettingsStore(db)

    def override(key: str, fallback: Any) -> Any:
        value = settings_store.get_override(key)
        return fallback if value is None or value == "" else value

    web_access_token = override("web_access_token", settings.web_access_token)
    generated_web_token = not bool(web_access_token)
    if generated_web_token:
        web_access_token = secrets.token_urlsafe(24)
        settings_store.set("web_access_token", web_access_token)

    mcp_access_token = override("mcp_access_token", settings.mcp_access_token)
    generated_mcp_token = not bool(mcp_access_token)
    if generated_mcp_token:
        mcp_access_token = secrets.token_urlsafe(24)
        settings_store.set("mcp_access_token", mcp_access_token)

    mcp_auth_mode = {"bearer": "token"}.get(
        str(override("mcp_auth_mode", settings.mcp_auth_mode)),
        str(override("mcp_auth_mode", settings.mcp_auth_mode)),
    )
    if mcp_auth_mode not in {"token", "oauth", "both", "noauth"}:
        db.close()
        msg = "CHATCODEX_MCP_AUTH_MODE must be token, oauth, both, or noauth"
        raise ValueError(msg)

    internal_ws_key = override(
        "codex_internal_ws_key", settings.codex_internal_ws_key
    ) or secrets.token_urlsafe(48)
    settings_store.set("codex_internal_ws_key", internal_ws_key)
    oauth_token_secret = override("oauth_token_secret", settings.oauth_token_secret)
    if not oauth_token_secret or oauth_token_secret == "dev-secret-change-me":
        oauth_token_secret = secrets.token_urlsafe(48)
        settings_store.set("oauth_token_secret", oauth_token_secret)

    public_route_kind = override("public_route_kind", settings.public_route_kind)
    public_url = str(override("public_url", settings.public_url)).rstrip("/")
    settings = Settings(
        **{
            **settings.__dict__,
            "web_access_token": web_access_token,
            "mcp_auth_mode": mcp_auth_mode,
            "mcp_access_token": mcp_access_token,
            "oauth_token_secret": oauth_token_secret,
            "oauth_password": override("oauth_password", settings.oauth_password)
            or web_access_token,
            "oauth_callback_protection": bool(
                override(
                    "oauth_callback_protection", settings.oauth_callback_protection
                )
            ),
            "public_url": public_url,
            "public_route_kind": public_route_kind
            if public_route_kind in {"direct", "cloudflared-try", "cloudflared-named"}
            else "",
            "tunnel_kind": public_route_kind
            if public_route_kind in {"direct", "cloudflared-try", "cloudflared-named"}
            else "",
            "chatgpt_tunnel_enabled": bool(
                override("chatgpt_tunnel_enabled", settings.chatgpt_tunnel_enabled)
            ),
            "chatgpt_tunnel_id": override(
                "chatgpt_tunnel_id", settings.chatgpt_tunnel_id
            ),
            "codex_app_mode": override("codex_app_mode", settings.codex_app_mode),
            "codex_command": override("codex_command", settings.codex_command),
            "codex_external_ws_url": override(
                "codex_external_ws_url", settings.codex_external_ws_url
            ),
            "codex_external_ws_key": override(
                "codex_external_ws_key", settings.codex_external_ws_key
            ),
            "codex_internal_ws_key": internal_ws_key,
            "codex_release_repo": override(
                "codex_release_repo", settings.codex_release_repo
            ),
            "codex_download_url": override(
                "codex_download_url", settings.codex_download_url
            ),
            "tunnel_client_command": override(
                "tunnel_client_command", settings.tunnel_client_command
            ),
            "tunnel_client_release": override(
                "tunnel_client_release", settings.tunnel_client_release
            ),
            "tunnel_auto_restart": bool(
                override("tunnel_auto_restart", settings.tunnel_auto_restart)
            ),
        }
    )

    native = NativeRuntimeManager(settings.native_dir)
    auth = Authenticator(settings, db=db)
    web_auth = WebAuthenticator(settings.web_access_token)
    appserver = AppServerManager(
        settings,
        port=int(override("codex_ws_port", settings.codex_ws_port)),
        auto_restart=bool(override("codex_auto_restart", True)),
        native=native,
    )
    tunnels = TunnelManager(settings, native=native)
    events = EventBroker()
    approval = ApprovalBridge(appserver, db, events=events)
    execution = ExecutionService(settings)
    mcp = build_mcp(settings, execution, auth, appserver)
    return Runtime(
        settings,
        db,
        settings_store,
        native,
        auth,
        web_auth,
        appserver,
        tunnels,
        events,
        approval,
        execution,
        mcp,
        generated_web_token,
        generated_mcp_token,
    )
