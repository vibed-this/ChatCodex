# Copyright (c) 2026 ChatCodex contributors.
"""Gateway 配置:环境变量驱动,sqlite 默认、可切 PostgreSQL。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)



def _frontend_dist() -> str:
    """Resolve bundled frontend first, while preserving source-tree development."""
    configured = _env("CHATCODEX_FRONTEND_DIST")
    if configured:
        return configured
    bundled = os.path.join(os.path.dirname(__file__), "frontend")
    if os.path.isdir(bundled):
        return bundled
    workspace = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(workspace, "frontend", "dist")


def _legacy_database_path() -> str:
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "chatcodex.db")
    )


def _default_database_path() -> str:
    """Keep credentials and session state out of the source checkout."""
    if os.name == "nt":
        base = _env("LOCALAPPDATA", os.path.expanduser("~"))
        return os.path.join(base, "ChatCodex", "chatcodex.db")
    base = _env(
        "XDG_STATE_HOME", os.path.join(os.path.expanduser("~"), ".local", "state")
    )
    return os.path.join(base, "chatcodex", "chatcodex.db")


@dataclass(frozen=True)
class Settings:
    # HTTP 监听(本机回环;隧道把公网流量打到这里)
    host: str = _env("CHATCODEX_HOST", "127.0.0.1")
    port: int = int(_env("CHATCODEX_PORT", "8000"))

    # 数据库:sqlite:///path 或 postgresql://user:pass@host/db
    database_url: str = (
        _env("CHATCODEX_DATABASE_URL") or "sqlite:///" + _default_database_path()
    )

    bash_max_lines: int = int(_env("CHATCODEX_BASH_MAX_LINES", "2000"))
    bash_max_bytes: int = int(_env("CHATCODEX_BASH_MAX_BYTES", str(50 * 1024)))

    # Web 管理面板/API 与 MCP 使用独立凭据。旧 CHATCODEX_AUTH_* 仅作迁移兜底。
    web_access_token: str = _env(
        "CHATCODEX_WEB_ACCESS_TOKEN", _env("CHATCODEX_AUTH_TOKEN", "")
    )
    # token = 静态 Bearer; oauth = OAuth 2.1; both = 两者都接受; noauth 仅 loopback
    mcp_auth_mode: str = _env(
        "CHATCODEX_MCP_AUTH_MODE",
        {"bearer": "token"}.get(
            _env("CHATCODEX_AUTH_MODE", "token"), _env("CHATCODEX_AUTH_MODE", "token")
        ),
    )
    mcp_access_token: str = _env("CHATCODEX_MCP_ACCESS_TOKEN", "")
    # Optional externally supplied OAuth access token accepted as a Bearer token.
    oauth_access_token: str = _env("CHATCODEX_OAUTH_ACCESS_TOKEN", "")
    oauth_token_secret: str = _env(
        "CHATCODEX_OAUTH_TOKEN_SECRET", "dev-secret-change-me"
    )
    oauth_token_ttl: int = int(_env("CHATCODEX_OAUTH_TOKEN_TTL", "3600"))
    oauth_refresh_token_ttl: int = int(
        _env("CHATCODEX_OAUTH_REFRESH_TOKEN_TTL", "2592000")
    )
    # OAuth 同意页登录密码(oauth 模式必填;空=不校验,仅开发)
    oauth_password: str = _env("CHATCODEX_OAUTH_PASSWORD", "")
    oauth_callback_protection: bool = _env(
        "CHATCODEX_OAUTH_CALLBACK_PROTECTION", "0"
    ).lower() in {"1", "true", "yes", "on"}
    public_url: str = _env("CHATCODEX_PUBLIC_URL", "http://127.0.0.1:8000")


    # 前端构建产物目录(widget 资源);开发期也可内联
    frontend_dist: str = _frontend_dist()


    extra: dict[str, Any] = field(default_factory=dict)


def load_settings() -> Settings:
    return Settings()
