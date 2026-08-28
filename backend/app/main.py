# Copyright (c) 2026 ChatCodex contributors.
"""ChatCodex Gateway - 全新项目，全量放开。"""

from __future__ import annotations

import asyncio
import hmac
import json
import re
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
from typing import Annotated, Any, TypeVar
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .config import Settings
from .mcp.audit import AUDIT_LOG
from .native import NativeRuntimeError
from .oauth import (
    Principal,
    _canonical_scopes_list,
    is_chatgpt_connector_callback,
)
from .runtime import create_runtime

_ALLOWED_SCOPES = {"tools", "codex"}

runtime = None
settings = Settings()
_CLI_SETTINGS_OVERRIDE: Settings | None = None
db = None
settings_store = None
native = None
auth = None
web_auth = None
tunnels = None
orch = None
mcp = None
_GENERATED_WEB_TOKEN = False
_GENERATED_MCP_TOKEN = False

_T = TypeVar("_T")


def _mask_external(config: dict[str, Any]) -> dict[str, Any]:
    value = dict(config)
    value["headers"] = {k: ("********" if v else "") for k, v in (value.get("headers") or {}).items()}
    value["env"] = {k: ("********" if v else "") for k, v in (value.get("env") or {}).items()}
    return value


def _merge_external_secret_fields(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(incoming)
    for field in ("headers", "env"):
        old = current.get(field) or {}
        new = incoming.get(field) or {}
        merged[field] = {k: (old[k] if v == "********" else str(v)) for k, v in new.items()}
    return merged


def _require(value: _T | None) -> _T:
    if value is None:
        msg = "runtime service is not initialized"
        raise RuntimeError(msg)
    return value


_PUBLIC_ROUTE_KINDS = {"direct", "cloudflared-try", "cloudflared-named"}
_PUBLIC_ROUTE_INSTANCE = "public-route"
_CHATGPT_MCP_INSTANCE = "chatgpt-mcp"


class _ReloadableAsgi:
    def __init__(self, target: Any) -> None:
        self.target = target

    def replace(self, target: Any) -> None:
        self.target = target

    async def __call__(self, scope: Any, receive: Any, send: Any) -> Any:
        await self.target(scope, receive, send)


async def _mcp_unavailable(scope: Any, receive: Any, send: Any) -> None:
    if scope.get("type") == "http":
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [(b"content-type", b"text/plain; charset=utf-8")],
            }
        )
        await send(
            {"type": "http.response.body", "body": b"MCP runtime is not initialized"}
        )


_mcp_asgi = _ReloadableAsgi(_mcp_unavailable)


def _valid_runtime_public_root(public_url: str, *, https_required: bool) -> bool:
    try:
        parsed = urlsplit(public_url)
    except ValueError:
        return False
    if (
        parsed.scheme not in ({"https"} if https_required else {"http", "https"})
        or not parsed.hostname
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        return False
    return not (
        https_required and parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}
    )


def _replace_runtime_public_url(public_url: str, *, https_required: bool) -> bool:
    base = str(public_url or "").rstrip("/")
    if not _valid_runtime_public_root(base, https_required=https_required):
        return False
    if auth is None or mcp is None:
        return False
    if _require(auth).public_url == base:
        return True
    _require(auth).set_public_url(base)
    if _require(mcp).settings.auth is not None:
        _require(mcp).settings.auth = (
            _require(mcp)
            .settings._require(auth)
            .model_copy(
                update={"issuer_url": base, "resource_server_url": f"{base}/mcp"}
            )
        )
        _mcp_asgi.replace(_require(mcp).streamable_http_app())
    _require(tunnels).settings = replace(_require(tunnels).settings, public_url=base)
    return True


def _activate_tunnel_public_url(public_url: str) -> None:
    if not _replace_runtime_public_url(public_url, https_required=True):
        msg = "tunnel public URL must be a public HTTPS root URL"
        raise ValueError(msg)


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    global runtime, settings, db, settings_store, native, auth, web_auth, tunnels, orch, mcp
    global _GENERATED_WEB_TOKEN, _GENERATED_MCP_TOKEN
    runtime = create_runtime(_CLI_SETTINGS_OVERRIDE)
    settings = runtime.settings
    db = runtime.db
    settings_store = runtime.settings_store
    native = runtime.native
    auth = runtime.auth
    web_auth = runtime.web_auth
    tunnels = runtime.tunnels
    orch = runtime.execution
    mcp = runtime.mcp
    _require(tunnels).on_public_url = _activate_tunnel_public_url
    _GENERATED_WEB_TOKEN = runtime.generated_web_token
    _GENERATED_MCP_TOKEN = runtime.generated_mcp_token
    _mcp_asgi.replace(_require(mcp).streamable_http_app())
    await _autostart_transports()
    try:
        async with (
            _require(mcp)._mcp_server.lifespan(_require(mcp)._mcp_server),
            _require(mcp).session_manager.run(),
        ):
            yield
    finally:
        await _require(tunnels).stop()
        await runtime.close()


async def _autostart_transports() -> None:
    route = settings.public_route_kind.strip()
    if route:
        try:
            if route == "cloudflared-try":
                await _require(tunnels).start(
                    "cloudflared", mode="try", instance_id=_PUBLIC_ROUTE_INSTANCE
                )
            elif route == "cloudflared-named":
                await _require(tunnels).start(
                    "cloudflared",
                    mode="named",
                    token=settings.cloudflared_token,
                    instance_id=_PUBLIC_ROUTE_INSTANCE,
                )
            else:
                await _require(tunnels).start(
                    "direct", instance_id=_PUBLIC_ROUTE_INSTANCE
                )
        except Exception:
            pass
    if settings.chatgpt_tunnel_enabled:
        with suppress(Exception):
            await _require(tunnels).start(
                "chatgpt",
                tunnel_id=settings.chatgpt_tunnel_id,
                api_key=settings.chatgpt_api_key,
                client_bin=settings.tunnel_client_command,
                instance_id=_CHATGPT_MCP_INSTANCE,
            )


def _print_startup_banner() -> None:
    if _GENERATED_WEB_TOKEN:
        pass
    else:
        pass
    if settings.mcp_auth_mode in ("token", "both"):
        if _GENERATED_MCP_TOKEN:
            pass
        else:
            pass


app = FastAPI(title="ChatCodex Gateway", version="0.1.0", lifespan=lifespan)

_WEB_COOKIE = "chatcodex_web_session"
_SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def _origin_tuple(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme, parsed.hostname.lower(), port


def _request_origin(request: Request) -> tuple[str, str, int] | None:
    proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    host = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    return _origin_tuple(
        f"{proto or request.url.scheme}://{host or request.headers.get('host', '')}"
    )


def web_principal(
    authorization: str | None = Header(default=None), *, request: Request
) -> Principal:
    token = ""
    cookie_authenticated = False
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif request:
        token = request.cookies.get(_WEB_COOKIE, "")
        cookie_authenticated = bool(token)
    p = _require(web_auth).authenticate(token)
    if not p:
        raise HTTPException(
            status_code=401,
            detail="unauthorized",
            headers={"WWW-Authenticate": 'Bearer realm="ChatCodex Web"'},
        )
    if request is None:
        return p
    if request is None:
        return p
    if (
        cookie_authenticated
        and request.method.upper() not in _SAFE_HTTP_METHODS
        and _origin_tuple(request.headers.get("origin", "")) != _request_origin(request)
    ):
        raise HTTPException(
            status_code=403, detail="cross-origin admin request rejected"
        )
    return p


principal = web_principal


@app.get("/healthz")
async def healthz() -> Any:
    return {
        "ok": True,
        "healthy": True,
        "auth": {"web": "token", "mcp": settings.mcp_auth_mode},
        "tools": _require(orch).capabilities(),
    }


@app.get("/")
@app.get("/panel")
async def panel() -> Any:
    import os

    from fastapi.responses import FileResponse

    index = os.path.join(settings.frontend_dist, "panel", "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return {
        "service": "chatcodex",
        "mcp": "/mcp",
        "healthz": "/healthz",
        "hint": "frontend 未构建:cd frontend && npm install && npm run build",
    }


@app.post("/api/auth/session")
async def create_web_session(request: Request) -> Any:
    try:
        body = await _read_json_body_limited(request, 8 * 1024)
    except HTTPException:
        raise
    except Exception:
        body = {}
    if not _require(web_auth).authenticate(str(body.get("token", ""))):
        raise HTTPException(401, "invalid Web Access Token")
    response = JSONResponse({"authenticated": True})
    forwarded_proto = (
        request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    )
    response.set_cookie(
        _WEB_COOKIE,
        settings.web_access_token,
        httponly=True,
        secure=request.url.scheme == "https" or forwarded_proto == "https",
        samesite="strict",
        path="/",
    )
    return response


@app.get("/api/auth/session")
async def web_session_status(p: Annotated[Principal, Depends(web_principal)]) -> Any:
    return {"authenticated": True, "user": p.user_id}


@app.delete("/api/auth/session")
async def delete_web_session() -> Any:
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(_WEB_COOKIE, path="/")
    return response


app.mount("/mcp", _mcp_asgi)


def _protected_resource_metadata() -> dict[str, Any]:
    return {
        "resource": _require(auth).resource,
        "authorization_servers": [_require(auth).public_url],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["tools", "codex"],
    }


def _authorization_server_metadata() -> dict[str, Any]:
    base = _require(auth).public_url
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "response_types_supported": ["code"],
        "scopes_supported": ["tools", "codex"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


def _oauth_metadata_audit() -> dict[str, Any]:
    issues: list[str] = []
    try:
        parsed = urlsplit(_require(auth).public_url)
    except ValueError:
        parsed = None
    if not parsed or parsed.scheme != "https" or not parsed.hostname:
        issues.append("OAuth issuer 必须是可公网访问的 HTTPS 根地址")
    elif parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
        issues.append("OAuth issuer 不能是 loopback 地址")
    if parsed and (
        parsed.query or parsed.fragment or parsed.username or parsed.password
    ):
        issues.append("OAuth issuer 不能包含认证信息、query 或 fragment")
    if parsed and parsed.path not in {"", "/"}:
        issues.append("当前内置 OAuth 仅支持站点根路径 issuer")
    return {
        "enabled": settings.mcp_auth_mode in {"oauth", "both"},
        "complete": settings.mcp_auth_mode in {"oauth", "both"} and not issues,
        "issues": issues,
        "registrationMode": "dcr",
        "pkce": "S256",
        "protectedResource": _protected_resource_metadata(),
        "authorizationServer": _authorization_server_metadata(),
        "publicUrlSource": "cloudflared-runtime"
        if _require(auth).public_url != settings.public_url
        else "configured",
        "note": "Secure MCP Tunnel rewrites resource/resource_metadata to its public endpoint; authorization_servers[0] remains this public HTTPS issuer.",
    }


@app.get("/.well-known/oauth-protected-resource")
@app.get("/.well-known/oauth-protected-resource/mcp")
async def opr() -> Any:
    _require_oauth_mode()
    return _protected_resource_metadata()


@app.get("/.well-known/oauth-authorization-server")
async def oas() -> Any:
    _require_oauth_mode()
    return _authorization_server_metadata()


@app.post("/oauth/register")
async def oauth_register(request: Request) -> Any:
    _require_oauth_mode()
    try:
        return _require(auth).store.register_client(
            await _read_json_body_limited(request, 32 * 1024) or {}
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


async def _read_json_body_limited(request: Request, max_bytes: int) -> dict[str, Any]:
    body = await _read_body_limited(request, max_bytes)
    try:
        value = json.loads(body or b"{}")
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "invalid JSON body") from exc
    if not isinstance(value, dict):
        raise HTTPException(400, "JSON body must be an object")
    return value


async def _read_body_limited(request: Request, max_bytes: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > max_bytes:
                raise HTTPException(413, "request body is too large")
        except ValueError:
            raise HTTPException(400, "invalid content-length")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            raise HTTPException(413, "request body is too large")
    return bytes(body)


_CONSENT_HTML = """<!doctype html><html lang=zh><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>授权 · ChatCodex</title><style>:root{color-scheme:light}*{box-sizing:border-box}body{font-family:ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto;margin:0;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#fff;color:#0d0d0d}.card{width:100%;max-width:400px;padding:40px 32px}.logo{display:flex;align-items:center;gap:10px;margin-bottom:28px}.logo .mark{width:34px;height:34px;border-radius:9px;background:#10a37f;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:17px}.logo .name{font-size:17px;font-weight:600}h1{font-size:22px;margin:0 0 8px;letter-spacing:-.01em}.sub{color:#6e6e6e;font-size:14px;margin:0 0 22px;line-height:1.5}.client,.scope{background:#f7f7f8;border:1px solid #ececf1;border-radius:10px;padding:12px 14px;font-size:13px;margin-bottom:14px}.scope{display:flex;gap:8px;align-items:flex-start}.scope .dot{color:#10a37f;margin-top:1px}label{display:block;font-size:13px;font-weight:600;margin:0 0 6px}input[type=password]{width:100%;padding:11px 13px;border:1px solid #d9d9e3;border-radius:9px;font-size:14px;outline:none;margin-bottom:6px}input[type=password]:focus{border-color:#10a37f;box-shadow:0 0 0 3px rgba(16,163,127,.15)}.err{color:#d92d20;font-size:13px;min-height:18px;margin-bottom:6px}button{width:100%;padding:12px;border:0;border-radius:9px;background:#10a37f;color:#fff;font-size:15px;font-weight:600;cursor:pointer}button:hover{background:#0e8f6f}.deny{background:transparent;color:#6e6e6e;border:1px solid #d9d9e3;margin-top:10px}.deny:hover{background:#f7f7f8}.foot{text-align:center;color:#9b9b9b;font-size:12px;margin-top:22px}</style></head><body><div class=card><div class=logo><div class=mark>C</div><div class=name>ChatCodex</div></div><h1>授权访问本地工具</h1><p class=sub>应用请求访问你的本地工作区，以读写文件、运行命令。</p><div class=client>应用:<b>{client}</b></div><div class=scope><span class=dot>●</span><span>权限范围:{scope}</span></div><form method=post action="/oauth/authorize">{hidden}{password_field}<div class=err>{error}</div><button type=submit>允许并继续</button></form><form method=post action="/oauth/authorize">{hidden}<input type=hidden name=deny value=1><button type=submit class=deny>拒绝</button></form><div class=foot>授权即代表你信任此应用访问本地工作区</div></div></body></html>"""


def _consent_page(
    client_id: Any, scope: Any, hidden: Any, need_password: Any, error: Any = ""
) -> Any:
    import html

    pf = (
        (
            '<label for=pw>访问密码</label><input id=pw type=password name=password placeholder="输入访问密码" required autofocus>'
        )
        if need_password
        else ""
    )
    page = _CONSENT_HTML
    replacements = {
        "{client}": html.escape(str(client_id)),
        "{scope}": html.escape(str(scope)),
        "{hidden}": hidden,
        "{password_field}": pf,
        "{error}": html.escape(str(error)),
    }
    for marker, value in replacements.items():
        page = page.replace(marker, value)
    return page


def _oauth_redirect_origin(redirect_uri: str) -> str:
    try:
        parsed = urlsplit(redirect_uri)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            return ""
        port = parsed.port
    except ValueError:
        return ""
    hostname = parsed.hostname
    if ":" in hostname:
        hostname = f"[{hostname}]"
    return f"{parsed.scheme}://{hostname}{f':{port}' if port is not None else ''}"


def _oauth_consent_response(
    content: str, redirect_uri: str, status_code: int = 200
) -> Any:
    from fastapi.responses import HTMLResponse

    callback_origin = _oauth_redirect_origin(redirect_uri)
    form_action = f"'self' {callback_origin}" if callback_origin else "'self'"
    return HTMLResponse(
        content,
        status_code=status_code,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": f"default-src 'none'; style-src 'unsafe-inline'; form-action {form_action}; base-uri 'none'; frame-ancestors 'none'",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        },
    )


def _hidden(**kv: Any) -> Any:
    import html as _h

    return "".join(
        f'<input type=hidden name={k} value="{_h.escape(str(v))}">'
        for k, v in kv.items()
    )


@app.get("/oauth/authorize")
async def oauth_authorize_get(
    request: Request,
    client_id: str = "",
    redirect_uri: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    scope: str = "tools",
    state: str = "",
    resource: str = "",
) -> Any:
    resource = resource or _require(auth).resource
    if len(state) > 2048:
        raise HTTPException(400, "invalid_state")
    _validate_authorization(
        client_id, redirect_uri, code_challenge, code_challenge_method, scope, resource
    )
    hidden = _hidden(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        scope=scope,
        state=state,
        resource=resource,
    )
    return _oauth_consent_response(
        _consent_page(client_id, scope, hidden, bool(settings.oauth_password)),
        redirect_uri,
    )


@app.post("/oauth/authorize")
async def oauth_authorize_post(request: Request) -> Any:
    from urllib.parse import parse_qs

    if "application/x-www-form-urlencoded" not in request.headers.get(
        "content-type", ""
    ):
        raise HTTPException(415, "authorization form must be urlencoded")
    try:
        form = {
            key: values[0]
            for key, values in parse_qs(
                (await _read_body_limited(request, 32 * 1024)).decode("utf-8"),
                keep_blank_values=True,
            ).items()
        }
    except UnicodeDecodeError as exc:
        raise HTTPException(400, "invalid authorization form") from exc
    client_id = str(form.get("client_id", ""))
    redirect_uri = str(form.get("redirect_uri", ""))
    code_challenge = str(form.get("code_challenge", ""))
    method = str(form.get("code_challenge_method", "S256"))
    scope = str(form.get("scope", "tools"))
    state = str(form.get("state", ""))
    if len(state) > 2048:
        raise HTTPException(400, "invalid_state")
    resource = str(form.get("resource", "")) or _require(auth).resource
    _validate_authorization(
        client_id, redirect_uri, code_challenge, method, scope, resource
    )
    if form.get("deny"):
        return RedirectResponse(
            _oauth_redirect(redirect_uri, error="access_denied", state=state),
            status_code=302,
        )
    if settings.oauth_password and not hmac.compare_digest(
        str(form.get("password", "")), settings.oauth_password
    ):
        hidden = _hidden(
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=method,
            scope=scope,
            state=state,
            resource=resource,
        )
        return _oauth_consent_response(
            _consent_page(client_id, scope, hidden, True, "密码错误,请重试"),
            redirect_uri,
            status_code=401,
        )
    code = _require(auth).store.issue_code(
        client_id, redirect_uri, code_challenge, method, "user", scope, resource
    )
    return RedirectResponse(
        _oauth_redirect(redirect_uri, code=code, state=state), status_code=302
    )


@app.post("/oauth/token")
async def oauth_token(request: Request) -> Any:
    _require_oauth_mode()
    body = await _read_body_limited(request, 32 * 1024)
    if "application/x-www-form-urlencoded" in request.headers.get("content-type", ""):
        from urllib.parse import parse_qs

        try:
            form = {
                k: v[0]
                for k, v in parse_qs(
                    body.decode("utf-8"), keep_blank_values=True
                ).items()
            }
        except UnicodeDecodeError as exc:
            raise HTTPException(400, "invalid token request") from exc
    else:
        try:
            form = json.loads(body or b"{}")
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(400, "invalid token request") from exc
    if not isinstance(form, dict):
        raise HTTPException(400, "invalid token request")
    grant_type = form.get("grant_type")
    if grant_type == "authorization_code":
        rec = _require(auth).store.redeem_code(
            form.get("code", ""),
            form.get("client_id", ""),
            form.get("redirect_uri", ""),
            form.get("code_verifier", ""),
        )
        if not rec:
            raise HTTPException(400, "invalid_grant")
        if form.get("resource") != rec.get("resource"):
            raise HTTPException(400, "invalid_target")
        client = _require(auth).store.get_client(rec.get("client_id", ""))
        if not client or "authorization_code" not in (
            client.get("grant_types") or ["authorization_code"]
        ):
            raise HTTPException(400, "invalid_client")
        return _oauth_token_response(
            rec["user_id"],
            _canonical_scopes_list(rec.get("scope", "tools").split()),
            rec.get("resource", ""),
            rec.get("client_id", ""),
            client,
        )
    if grant_type == "refresh_token":
        principal = _require(auth).signer.verify_refresh(
            str(form.get("refresh_token") or ""), _require(auth).accepts_resource
        )
        client_id = str(form.get("client_id") or "")
        client = _require(auth).store.get_client(client_id)
        if (
            not principal
            or not client
            or principal.client_id != client_id
            or "refresh_token" not in (client.get("grant_types") or [])
        ):
            raise HTTPException(400, "invalid_grant")
        resource = str(form.get("resource") or principal.audience)
        if resource != principal.audience or not _require(auth).accepts_resource(
            resource
        ):
            raise HTTPException(400, "invalid_target")
        scopes = _canonical_scopes_list(principal.scopes)
        if "scope" in form:
            requested_scopes = _canonical_scopes_list(
                str(form.get("scope") or "").split()
            )
            if not requested_scopes or not set(requested_scopes).issubset(
                set(scopes)
            ):
                raise HTTPException(400, "invalid_scope")
            scopes = requested_scopes
        return _oauth_token_response(
            principal.user_id, scopes, resource, client_id, client
        )
    raise HTTPException(400, "unsupported_grant_type")


def _oauth_token_response(
    user_id: str,
    scopes: list[str],
    resource: str,
    client_id: str,
    client: dict[str, Any],
) -> JSONResponse:
    canon_scopes = _canonical_scopes_list(scopes)
    payload = {
        "access_token": _require(auth).signer.issue(
            user_id, canon_scopes, audience=resource, client_id=client_id
        ),
        "token_type": "Bearer",
        "expires_in": settings.oauth_token_ttl,
        "scope": " ".join(canon_scopes),
    }
    if "refresh_token" in (client.get("grant_types") or []):
        payload["refresh_token"] = _require(auth).signer.issue(
            user_id,
            canon_scopes,
            audience=resource,
            client_id=client_id,
            token_use="refresh",
            ttl=settings.oauth_refresh_token_ttl,
        )
    return JSONResponse(
        payload, headers={"Cache-Control": "no-store", "Pragma": "no-cache"}
    )


def _require_oauth_mode() -> None:
    if settings.mcp_auth_mode not in {"oauth", "both"}:
        raise HTTPException(404, "oauth is not enabled")


def _validate_authorization(
    client_id: str,
    redirect_uri: str,
    challenge: str,
    method: str,
    scope: str,
    resource: str,
) -> None:
    _require_oauth_mode()
    if len(client_id) > 128 or len(redirect_uri) > 2048 or len(resource) > 2048:
        raise HTTPException(400, "invalid_request")
    client = _require(auth).store.get_client(client_id)
    if not client or redirect_uri not in client.get("redirect_uris", []):
        raise HTTPException(400, "invalid_client_or_redirect_uri")
    if settings.oauth_callback_protection and not is_chatgpt_connector_callback(
        redirect_uri
    ):
        raise HTTPException(400, "redirect_uri_not_allowed")
    if method != "S256" or not re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge):
        raise HTTPException(400, "invalid_code_challenge")
    scopes = set(scope.split())
    if not scopes or not scopes.issubset(_ALLOWED_SCOPES):
        raise HTTPException(400, "invalid_scope")
    if not _require(auth).accepts_resource(resource):
        raise HTTPException(400, "invalid_target")


def _oauth_redirect(redirect_uri: str, **params: str) -> str:
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parsed = urlsplit(redirect_uri)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend((k, v) for k, v in params.items() if v != "")
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


@app.post("/api/native/tunnel-client/install")
async def native_tunnel_install(
    request: Request, p: Annotated[Principal, Depends(principal)]
) -> Any:
    body = await request.json()
    try:
        result = await asyncio.to_thread(
            _require(native).install_tunnel_client,
            body.get("release") or settings.tunnel_client_release,
        )
        _require(settings_store).set("tunnel_client_command", result["tunnelCommand"])
        _require(tunnels).settings = replace(
            _require(tunnels).settings, tunnel_client_command=result["tunnelCommand"]
        )
        return result
    except NativeRuntimeError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/overview")
async def overview(p: Annotated[Principal, Depends(principal)]) -> Any:
    return {
        "publicRoute": _require(tunnels).status(_PUBLIC_ROUTE_INSTANCE),
        "chatgptTunnel": _require(tunnels).status(_CHATGPT_MCP_INSTANCE),
        "executionCapabilities": _require(orch).capabilities(),
        "auth": {"web": "token", "mcp": settings.mcp_auth_mode},
    }


@app.get("/api/settings")
async def get_settings(p: Annotated[Principal, Depends(principal)]) -> Any:
    return {
        "settings": _masked_settings(_effective_settings()),
        "defaultsEditable": True,
    }


@app.get("/api/oauth/metadata-audit")
async def oauth_metadata_audit(p: Annotated[Principal, Depends(principal)]) -> Any:
    return _oauth_metadata_audit()


@app.get("/api/mcp-audit")
async def get_mcp_audit(p: Annotated[Principal, Depends(principal)]) -> Any:
    return {"records": AUDIT_LOG.list(), "active": AUDIT_LOG.active(), "count": AUDIT_LOG.count(), "maxRecords": 1000}


@app.delete("/api/mcp-audit")
async def clear_mcp_audit(p: Annotated[Principal, Depends(principal)]) -> Any:
    AUDIT_LOG.clear()
    return {"ok": True}


@app.get("/api/shells")
async def get_shells(p: Annotated[Principal, Depends(principal)]) -> Any:
    return await _require(orch).shell_list()


@app.post("/api/shells/{shell_id}/kill")
async def kill_shell(shell_id: str, p: Annotated[Principal, Depends(principal)]) -> Any:
    return await _require(orch).shell_kill(shell_id)


@app.post("/api/shell-waits/{wait_id}/cancel")
async def cancel_shell_wait(
    wait_id: str, request: Request, p: Annotated[Principal, Depends(principal)]
) -> Any:
    body = await _read_json_body_limited(request, 16 * 1024)
    return await _require(orch).shell_cancel_wait(wait_id, str(body.get("reason", "")))


@app.get("/api/external-mcp")
async def get_external_mcp(p: Annotated[Principal, Depends(principal)]) -> Any:
    manager = _require(runtime).external_mcp
    status = {item["id"]: item for item in manager.status()}
    servers = []
    for config in manager.configs():
        item = _mask_external(config)
        item.update(status.get(config["id"], {}))
        servers.append(item)
    return {"servers": servers, "transports": ["stdio", "sse", "streamable_http"]}


@app.put("/api/external-mcp")
async def set_external_mcp(request: Request, p: Annotated[Principal, Depends(principal)]) -> Any:
    body = await _read_json_body_limited(request, 256 * 1024)
    servers = body.get("servers")
    if not isinstance(servers, list):
        raise HTTPException(422, "servers must be a list")
    current = {item["id"]: item for item in _require(runtime).external_mcp.configs()}
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in servers:
        if not isinstance(item, dict):
            raise HTTPException(422, "each external MCP server must be an object")
        server_id = str(item.get("id") or item.get("name") or "").strip()
        if not server_id:
            raise HTTPException(422, "external MCP server id/name is required")
        if server_id in seen:
            raise HTTPException(422, f"duplicate external MCP server: {server_id}")
        seen.add(server_id)
        existing = current.get(server_id, {})
        merged.append(_merge_external_secret_fields(existing, item))
    try:
        from .mcp.external import _normalize_config
        normalized = [_normalize_config(item) for item in merged]
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _require(settings_store).set("external_mcp_servers", normalized)
    await _require(runtime).external_mcp.replace_configs(normalized)
    manager = _require(runtime).external_mcp
    status = {item["id"]: item for item in manager.status()}
    servers = []
    for config in manager.configs():
        item = _mask_external(config)
        item.update(status.get(config["id"], {}))
        servers.append(item)
    return {"servers": servers}


@app.post("/api/external-mcp/test")
async def test_external_mcp(request: Request, p: Annotated[Principal, Depends(principal)]) -> Any:
    body = await _read_json_body_limited(request, 128 * 1024)
    if not isinstance(body, dict):
        raise HTTPException(422, "server must be an object")
    try:
        from .mcp.external import _normalize_config
        config = _normalize_config(body)
        from .mcp.external import ExternalMcpManager
        manager = ExternalMcpManager([config])
        try:
            tools = await manager.list_tools()
            return {"ok": True, "server": config["id"], "tools": [tool.model_dump(mode="json") for tool in tools]}
        finally:
            await manager.close()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/mcp-tools")
async def get_mcp_tools(p: Annotated[Principal, Depends(principal)]) -> Any:
    tools = await _require(mcp).list_tools()
    return {
        "tools": [tool.model_dump(mode="json") for tool in tools],
        "policy": "full-access",
        "default": "allow",
        "mcpForwarding": True,
    }


@app.post("/api/settings")
async def set_settings(
    request: Request, p: Annotated[Principal, Depends(principal)]
) -> Any:
    body = await _read_json_body_limited(request, 128 * 1024)
    body = {k: v for k, v in body.items() if v != "********"}
    body.pop("runtime_public_url", None)
    if "mcp_auth_mode" in body and body["mcp_auth_mode"] not in {
        "token",
        "oauth",
        "both",
        "noauth",
    }:
        raise HTTPException(422, "mcp_auth_mode must be token, oauth, both, or noauth")
    if "public_route_kind" in body and body[
        "public_route_kind"
    ] not in _PUBLIC_ROUTE_KINDS | {""}:
        raise HTTPException(
            422,
            "public_route_kind must be direct, cloudflared-try, or cloudflared-named",
        )
    bool_settings = {
        "oauth_callback_protection",
        "tunnel_auto_restart",
        "chatgpt_tunnel_enabled",
    }
    invalid_bools = sorted(
        key for key in bool_settings if key in body and not isinstance(body[key], bool)
    )
    if invalid_bools:
        raise HTTPException(
            422, f"settings must be boolean: {', '.join(invalid_bools)}"
        )
    body.pop("tunnel_kind", None)
    body.pop("chatgpt_api_key", None)
    body.pop("cloudflared_token", None)
    updated = _require(settings_store).update(body)
    if "chatgpt_tunnel_id" in body:
        _require(auth).set_chatgpt_tunnel_id(
            str(updated.get("chatgpt_tunnel_id") or "")
        )
    if any(
        key in body
        for key in (
            "tunnel_client_command",
            "tunnel_client_release",
            "tunnel_auto_restart",
            "chatgpt_tunnel_enabled",
            "chatgpt_tunnel_id",
            "public_route_kind",
        )
    ):
        runtime_settings = replace(
            settings,
            tunnel_client_command=(
                updated.get("tunnel_client_command") or settings.tunnel_client_command
            ),
            tunnel_client_release=(
                updated.get("tunnel_client_release") or settings.tunnel_client_release
            ),
            tunnel_auto_restart=bool(updated.get("tunnel_auto_restart", True)),
            chatgpt_tunnel_enabled=bool(updated.get("chatgpt_tunnel_enabled", False)),
            chatgpt_tunnel_id=(
                updated.get("chatgpt_tunnel_id") or settings.chatgpt_tunnel_id
            ),
            public_route_kind=(updated.get("public_route_kind") or ""),
            tunnel_kind=(updated.get("public_route_kind") or ""),
        )
        _require(tunnels).settings = runtime_settings
    restart_required = sorted(
        set(body)
        & {
            "web_access_token",
            "mcp_auth_mode",
            "mcp_access_token",
            "oauth_password",
            "oauth_callback_protection",
            "public_url",
        }
    )
    return {
        "settings": _masked_settings(_effective_settings()),
        "restartRequired": restart_required,
    }


def _masked_settings(values: dict[str, Any]) -> dict[str, Any]:
    values = dict(values)
    for key in (
        "web_access_token",
        "mcp_access_token",
        "oauth_password",
        "cloudflared_token",
        "chatgpt_api_key",
    ):
        values[key] = "********" if values.get(key) else ""
    return values


def _effective_settings() -> dict[str, Any]:
    values = _require(settings_store).all()
    fallbacks = {
        "public_route_kind": settings.public_route_kind,
        "tunnel_kind": settings.public_route_kind,
        "chatgpt_tunnel_enabled": settings.chatgpt_tunnel_enabled,
        "chatgpt_tunnel_id": settings.chatgpt_tunnel_id,
        "tunnel_client_command": settings.tunnel_client_command,
        "tunnel_client_release": settings.tunnel_client_release,
        "tunnel_auto_restart": settings.tunnel_auto_restart,
        "web_access_token": settings.web_access_token,
        "mcp_auth_mode": settings.mcp_auth_mode,
        "mcp_access_token": settings.mcp_access_token,
        "oauth_password": settings.oauth_password,
        "oauth_callback_protection": settings.oauth_callback_protection,
        "public_url": settings.public_url,
    }
    for key, fallback in fallbacks.items():
        override = _require(settings_store).get_override(key)
        values[key] = fallback if override is None or override == "" else override
    values["runtime_public_url"] = _require(auth).public_url
    return values


@app.get("/api/public-route/status")
@app.get("/api/tunnel/status")
async def public_route_status(p: Annotated[Principal, Depends(principal)]) -> Any:
    return _require(tunnels).status(_PUBLIC_ROUTE_INSTANCE)


@app.post("/api/public-route/start")
@app.post("/api/tunnel/start")
async def public_route_start(
    request: Request, p: Annotated[Principal, Depends(principal)]
) -> Any:
    body = await request.json()
    kind = body.get("kind", "direct")
    if kind not in {"direct", "cloudflared"}:
        raise HTTPException(
            422, "global public route only supports direct or cloudflared"
        )
    mode = body.get("mode", "try") if kind == "cloudflared" else ""
    if kind == "cloudflared" and mode not in {"try", "named"}:
        raise HTTPException(422, "cloudflared mode must be try or named")
    stored_kind = f"cloudflared-{mode}" if kind == "cloudflared" else "direct"
    _require(settings_store).set("public_route_kind", stored_kind)
    _require(tunnels).settings = replace(
        _require(tunnels).settings, public_url=settings.public_url
    )
    options = {"instance_id": _PUBLIC_ROUTE_INSTANCE}
    if kind == "cloudflared":
        options.update(mode=mode, token=body.get("token", ""))
    return await _require(tunnels).start(kind, **options)


@app.post("/api/public-route/stop")
@app.post("/api/tunnel/stop")
async def public_route_stop(p: Annotated[Principal, Depends(principal)]) -> Any:
    await _require(tunnels).stop(_PUBLIC_ROUTE_INSTANCE)
    _replace_runtime_public_url(settings.public_url, https_required=False)
    return {"ok": True}


@app.get("/api/chatgpt-tunnel/status")
async def chatgpt_tunnel_status(p: Annotated[Principal, Depends(principal)]) -> Any:
    return _require(tunnels).status(_CHATGPT_MCP_INSTANCE)


@app.post("/api/chatgpt-tunnel/start")
async def chatgpt_tunnel_start(
    request: Request, p: Annotated[Principal, Depends(principal)]
) -> Any:
    body = await request.json()
    tunnel_id = str(body.get("tunnel_id") or settings.chatgpt_tunnel_id)
    if body.get("tunnel_id"):
        _require(settings_store).set("chatgpt_tunnel_id", tunnel_id)
    _require(auth).set_chatgpt_tunnel_id(tunnel_id)
    _require(settings_store).set("chatgpt_tunnel_enabled", True)
    return await _require(tunnels).start(
        "chatgpt",
        instance_id=_CHATGPT_MCP_INSTANCE,
        tunnel_id=tunnel_id,
        api_key=body.get("api_key", ""),
        client_bin=body.get("client_bin", ""),
    )


@app.post("/api/chatgpt-tunnel/stop")
async def chatgpt_tunnel_stop(p: Annotated[Principal, Depends(principal)]) -> Any:
    _require(settings_store).set("chatgpt_tunnel_enabled", False)
    await _require(tunnels).stop(_CHATGPT_MCP_INSTANCE)
    return {"ok": True}


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(prog="chatcodex-gateway")
    parser.add_argument(
        "--oauth-token",
        metavar="TOKEN",
        help="Accept TOKEN as the Gateway's OAuth Bearer access token.",
    )
    args = parser.parse_args()

    global _CLI_SETTINGS_OVERRIDE
    if args.oauth_token:
        launch_base = Settings()
        _CLI_SETTINGS_OVERRIDE = replace(
            launch_base,
            oauth_access_token=args.oauth_token,
            mcp_auth_mode=(
                launch_base.mcp_auth_mode
                if launch_base.mcp_auth_mode != "token"
                else "both"
            ),
        )

    from .config import load_settings

    launch_settings = settings if runtime is not None else load_settings()
    uvicorn.run(
        app,
        host=launch_settings.host,
        port=launch_settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
