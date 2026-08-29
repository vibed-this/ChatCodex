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

from .config import Settings, load_settings
from .execution import ExecutionService
from .mcp.external import ExternalMcpManager
from .mcp.server import build_mcp
from .oauth import Authenticator, WebAuthenticator
from .persistence.database import Database
from .persistence.settings import SettingsStore

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


@dataclass
class Runtime:
    settings: Settings
    db: Database
    settings_store: SettingsStore
    auth: Authenticator
    web_auth: WebAuthenticator
    execution: ExecutionService
    mcp: FastMCP
    external_mcp: ExternalMcpManager
    generated_web_token: bool
    generated_mcp_token: bool

    async def close(self) -> None:
        await self.external_mcp.close()
        await self.execution.close()
        self.db.close()


def create_runtime(base_settings: Settings | None = None) -> Runtime:
    settings = base_settings or load_settings()
    db = Database(settings)
    settings_store = SettingsStore(db)

    cli_overrides = settings.extra.get("cli_overrides", {})

    def override(key: str, fallback: Any) -> Any:
        if key in cli_overrides:
            return cli_overrides[key]
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

    oauth_token_secret = override("oauth_token_secret", settings.oauth_token_secret)
    if not oauth_token_secret or oauth_token_secret == "dev-secret-change-me":
        oauth_token_secret = secrets.token_urlsafe(48)
        settings_store.set("oauth_token_secret", oauth_token_secret)

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
            "public_url": public_url
        }
    )

    auth = Authenticator(settings, db=db)
    web_auth = WebAuthenticator(settings.web_access_token)
    execution = ExecutionService(settings)
    external_mcp = ExternalMcpManager(settings_store.get("external_mcp_servers") or [])
    mcp = build_mcp(settings, execution, auth, external_mcp)
    return Runtime(
        settings,
        db,
        settings_store,
        auth,
        web_auth,
        execution,
        mcp,
        external_mcp,
        generated_web_token,
        generated_mcp_token,
    )
