# Copyright (c) 2026 ChatCodex contributors.
"""MCP 认证:静态 Token + OAuth 2.1(PKCE S256,stdlib 实现)。

无第三方 JWT 库:用 hmac 自签 HS256 token。模式:
  token  — MCP Access Token 直接比对
  oauth  — Authorization Code + PKCE;/.well-known/* + /oauth/register|authorize|token
  both   — 同时接受 MCP Access Token 和 OAuth access token
  noauth — 仅 loopback
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from .persistence.oauth import OAuthClientRepository

if TYPE_CHECKING:
    from collections.abc import Callable

    from .config import Settings

MAX_OAUTH_CLIENTS = 512
MAX_OAUTH_CODES = 1024
MAX_CLIENT_METADATA_BYTES = 32 * 1024
MAX_REDIRECT_URIS = 10

# codex 为 tools 的别名，兼容 ChatGPT Connector 固定请求 scope=codex
_CANONICAL_SCOPE_ALIASES = {"codex": "tools"}
_ALLOWED_SCOPES = {"tools", "codex"}


def _canonical_scope(scope: str) -> str:
    """将别名 codex 归一为 tools，并去重保持顺序。"""
    parts = scope.split()
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        canon = _CANONICAL_SCOPE_ALIASES.get(part, part)
        if canon not in seen:
            seen.add(canon)
            out.append(canon)
    return " ".join(out)


def _canonical_scopes_list(scopes: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for scope in scopes:
        canon = _CANONICAL_SCOPE_ALIASES.get(scope, scope)
        if canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@dataclass
class Principal:
    user_id: str
    scopes: list[str]
    client_id: str = ""
    audience: str = ""


class TokenSigner:
    """HS256 自签 token(JSON header.payload.sig)。"""

    def __init__(self, secret: str, ttl: int, issuer: str, audience: str) -> None:
        self.secret = secret.encode()
        self.ttl = ttl
        self.issuer = issuer.rstrip("/")
        self.audience = audience

    def set_issuer(self, issuer: str, audience: str) -> None:
        """Switch future token issuance and verification to a runtime URL."""
        self.issuer = issuer.rstrip("/")
        self.audience = audience

    def issue(
        self,
        subject: str,
        scopes: list[str] | None = None,
        audience: str | None = None,
        client_id: str = "",
        token_use: str = "access",
        ttl: int | None = None,
    ) -> str:
        now = int(time.time())
        header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        canon_scopes = _canonical_scopes_list(scopes or ["tools"])
        payload = _b64url(
            json.dumps(
                {
                    "sub": subject,
                    "iat": now,
                    "exp": now + (self.ttl if ttl is None else ttl),
                    "iss": self.issuer,
                    "aud": audience or self.audience,
                    "scope": " ".join(canon_scopes),
                    "client_id": client_id,
                    "token_use": token_use,
                },
                separators=(",", ":"),
            ).encode()
        )
        sig = _b64url(
            hmac.new(
                self.secret, f"{header}.{payload}".encode(), hashlib.sha256
            ).digest()
        )
        return f"{header}.{payload}.{sig}"

    def verify(
        self, token: str, audience_validator: Callable[[str], bool] | None = None
    ) -> Principal | None:
        return self._verify(token, "access", audience_validator)

    def verify_refresh(
        self, token: str, audience_validator: Callable[[str], bool] | None = None
    ) -> Principal | None:
        """Verify a refresh token without allowing it as an MCP access token."""
        return self._verify(token, "refresh", audience_validator)

    def _verify(
        self,
        token: str,
        expected_use: str,
        audience_validator: Callable[[str], bool] | None,
    ) -> Principal | None:
        try:
            header, payload, sig = token.split(".")
            if json.loads(_b64url_decode(header)).get("alg") != "HS256":
                return None
            expect = _b64url(
                hmac.new(
                    self.secret, f"{header}.{payload}".encode(), hashlib.sha256
                ).digest()
            )
            if not hmac.compare_digest(expect, sig):
                return None
            data = json.loads(_b64url_decode(payload))
            if data.get("exp", 0) <= int(time.time()):
                return None
            # Tokens issued before token_use was added are access tokens.
            if str(data.get("token_use") or "access") != expected_use:
                return None
            audience = data.get("aud", "")
            audience_ok = (
                audience_validator(audience)
                if audience_validator
                else audience == self.audience
            )
            if data.get("iss") != self.issuer or not audience_ok:
                return None
            return Principal(
                user_id=data.get("sub", "unknown"),
                scopes=_canonical_scopes_list(data.get("scope", "").split()),
                client_id=str(data.get("client_id") or ""),
                audience=str(audience),
            )
        except Exception:
            return None


class OAuthStore:
    """Short-lived codes in memory; DCR clients optionally persisted in sqlite."""

    def __init__(self, callback_protection: bool = False, db: Any = None) -> None:
        self.clients: dict[str, dict[str, Any]] = {}
        self.codes: dict[str, dict[str, Any]] = {}
        self.callback_protection = callback_protection
        self.client_repository = OAuthClientRepository(db) if db is not None else None

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        client = self.clients.get(client_id)
        if client is not None or self.client_repository is None or not client_id:
            return client
        client = self.client_repository.get(client_id)
        if client is not None:
            self.clients[client_id] = client
        return client

    def register_client(self, meta: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(meta, dict):
            msg = "client metadata must be an object"
            raise ValueError(msg)
        if (
            len(json.dumps(meta, ensure_ascii=False).encode("utf-8"))
            > MAX_CLIENT_METADATA_BYTES
        ):
            msg = "client metadata is too large"
            raise ValueError(msg)
        redirect_uris = meta.get("redirect_uris")
        if (
            not isinstance(redirect_uris, list)
            or not redirect_uris
            or len(redirect_uris) > MAX_REDIRECT_URIS
        ):
            msg = "redirect_uris is required"
            raise ValueError(msg)
        if not all(
            isinstance(uri, str) and len(uri) <= 2048 and _valid_redirect_uri(uri)
            for uri in redirect_uris
        ):
            msg = "redirect_uris must use HTTPS (localhost HTTP is allowed)"
            raise ValueError(msg)
        if self.callback_protection and not all(
            is_chatgpt_connector_callback(str(uri)) for uri in redirect_uris
        ):
            msg = (
                "redirect_uris are restricted to https://chatgpt.com/connector/oauth/*"
            )
            raise ValueError(msg)
        if meta.get("token_endpoint_auth_method", "none") != "none":
            msg = "only public PKCE clients are supported"
            raise ValueError(msg)
        grant_types = meta.get("grant_types", ["authorization_code"])
        if (
            not isinstance(grant_types, list)
            or not all(isinstance(grant, str) for grant in grant_types)
            or len(grant_types) != len(set(grant_types))
            or "authorization_code" not in grant_types
            or not set(grant_types).issubset({"authorization_code", "refresh_token"})
        ):
            msg = "grant_types must include authorization_code and may include refresh_token"
            raise ValueError(msg)
        response_types = meta.get("response_types", ["code"])
        if (
            not isinstance(response_types, list)
            or set(response_types) != {"code"}
            or len(response_types) != 1
        ):
            msg = "response_types must be ['code']"
            raise ValueError(msg)
        if "scope" in meta and (
            not isinstance(meta.get("scope"), str)
            or not set(meta["scope"].split())
            or not set(meta["scope"].split()).issubset(_ALLOWED_SCOPES)
        ):
            msg = "scope must contain only tools"
            raise ValueError(msg)
        # 归一化注册的 scope，别名 codex -> tools
        if "scope" in meta and isinstance(meta.get("scope"), str):
            meta = dict(meta)
            meta["scope"] = _canonical_scope(str(meta["scope"]))
        cid = secrets.token_hex(16)
        allowed = {
            k: meta[k]
            for k in (
                "redirect_uris",
                "client_name",
                "client_uri",
                "logo_uri",
                "scope",
                "token_endpoint_auth_method",
            )
            if k in meta
        }
        rec = {
            **allowed,
            "grant_types": grant_types,
            "response_types": response_types,
            "client_id": cid,
            "client_id_issued_at": int(time.time()),
            "token_endpoint_auth_method": "none",
        }
        # 公共客户端(PKCE)无 secret
        while len(self.clients) >= MAX_OAUTH_CLIENTS:
            oldest = min(
                self.clients,
                key=lambda key: int(self.clients[key].get("client_id_issued_at") or 0),
            )
            self.clients.pop(oldest, None)
        self.clients[cid] = rec
        if self.client_repository is not None:
            self.client_repository.save(rec, MAX_OAUTH_CLIENTS)
        return rec

    def issue_code(
        self,
        client_id: str,
        redirect_uri: str,
        challenge: str,
        method: str,
        user_id: str,
        scope: str,
        resource: str,
    ) -> str:
        now = int(time.time())
        self.codes = {
            key: value
            for key, value in self.codes.items()
            if int(value.get("exp") or 0) >= now
        }
        while len(self.codes) >= MAX_OAUTH_CODES:
            oldest = min(
                self.codes,
                key=lambda key: int(self.codes[key].get("issued_at") or 0),
            )
            self.codes.pop(oldest, None)
        code = secrets.token_urlsafe(32)
        self.codes[code] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": method,
            "user_id": user_id,
            "scope": _canonical_scope(scope),
            "issued_at": now,
            "exp": now + 600,
            "resource": resource,
        }
        return code

    def redeem_code(
        self, code: str, client_id: str, redirect_uri: str, verifier: str
    ) -> dict[str, Any] | None:
        if not all(
            isinstance(value, str)
            for value in (code, client_id, redirect_uri, verifier)
        ):
            return None
        if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
            return None
        rec = self.codes.pop(code, None)
        if not rec or rec["exp"] < int(time.time()):
            return None
        if rec["client_id"] != client_id or rec["redirect_uri"] != redirect_uri:
            return None
        # PKCE S256 校验
        digest = _b64url(hashlib.sha256(verifier.encode()).digest())
        if not hmac.compare_digest(digest, rec["code_challenge"]):
            return None
        return rec


class Authenticator:
    def __init__(self, settings: Settings, db: Any = None) -> None:
        self.settings = settings
        self.mode = settings.mcp_auth_mode
        self.public_url = settings.public_url.rstrip("/")
        self.resource = f"{self.public_url}/mcp"
        self.signer = TokenSigner(
            settings.oauth_token_secret,
            settings.oauth_token_ttl,
            self.public_url,
            self.resource,
        )
        self.store = OAuthStore(settings.oauth_callback_protection, db=db)

    def accepts_resource(self, resource: str) -> bool:
        """Accept only the configured MCP resource URL (tunnel support removed)."""
        return resource == self.resource

    def set_public_url(self, public_url: str) -> None:
        """Update the issuer/resource used by the current running instance."""
        base = public_url.rstrip("/")
        resource = f"{base}/mcp"
        self.public_url = base
        self.resource = resource
        self.signer.set_issuer(base, resource)

    def authenticate(
        self, authorization_header: str | None, remote_addr: str = ""
    ) -> Principal | None:
        if self.mode == "noauth":
            if remote_addr in ("127.0.0.1", "::1", ""):
                return Principal(user_id="local", scopes=["tools"])
            return None
        if not authorization_header or not authorization_header.lower().startswith(
            "bearer "
        ):
            return None
        token = authorization_header[7:].strip()
        if self.mode in ("token", "both"):
            if self.settings.mcp_access_token and hmac.compare_digest(
                token, self.settings.mcp_access_token
            ):
                return Principal(
                    user_id="mcp-token", scopes=["tools"], client_id="mcp-token"
                )
            if self.mode == "token":
                return None
        if self.mode in ("oauth", "both"):
            if self.settings.oauth_access_token and hmac.compare_digest(
                token, self.settings.oauth_access_token
            ):
                return Principal(
                    user_id="oauth-token", scopes=["tools"], client_id="oauth-token"
                )
            return self.signer.verify(token, self.accepts_resource)
        return None


class WebAuthenticator:
    """Authenticate the admin SPA and REST API with the Web Access Token."""

    def __init__(self, token: str) -> None:
        self.token = token

    def authenticate(self, token: str | None) -> Principal | None:
        if token and self.token and hmac.compare_digest(token, self.token):
            return Principal(user_id="web-admin", scopes=["admin"])
        return None


def verify_pkce_challenge(verifier: str, challenge: str) -> bool:
    return hmac.compare_digest(
        _b64url(hashlib.sha256(verifier.encode()).digest()), challenge
    )


def _valid_redirect_uri(uri: str) -> bool:
    try:
        parsed = urlparse(uri)
        if parsed.fragment or parsed.username or parsed.password or not parsed.hostname:
            return False
        if parsed.scheme == "https" and parsed.netloc:
            return True
        return parsed.scheme == "http" and (
            parsed.hostname in ("127.0.0.1", "localhost", "::1")
        )
    except Exception:
        return False


def is_chatgpt_connector_callback(uri: str) -> bool:
    """Return whether a redirect URI is a production ChatGPT connector callback."""
    try:
        parsed = urlparse(uri)
        prefix = "/connector/oauth/"
        suffix = parsed.path[len(prefix) :] if parsed.path.startswith(prefix) else ""
        return (
            parsed.scheme == "https"
            and parsed.hostname == "chatgpt.com"
            and parsed.port is None
            and bool(suffix)
            and "/" not in suffix
            and "%2f" not in suffix.lower()
            and "%5c" not in suffix.lower()
            and not parsed.fragment
            and not parsed.username
            and not parsed.password
        )
    except Exception:
        return False
