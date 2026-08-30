"""Real-process Web Token, MCP Token, and OAuth integration smoke test."""

from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, cast


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    backend = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="chatcodex-auth-") as directory:
        env = {
            **os.environ,
            "CHATCODEX_PORT": str(port),
            "CHATCODEX_DATABASE_URL": f"sqlite:///{Path(directory, 'test.db').as_posix()}",
            "CHATCODEX_WEB_ACCESS_TOKEN": "env-web-secret",
            "CHATCODEX_MCP_ACCESS_TOKEN": "env-mcp-secret",
            "CHATCODEX_MCP_AUTH_MODE": "token",
            "CHATCODEX_OAUTH_TOKEN_SECRET": "integration-oauth-signing-secret-32-bytes",
            "CHATCODEX_OAUTH_PASSWORD": "oauth-consent-secret",
            "CHATCODEX_PUBLIC_URL": base,
        }
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "app.main",
                "--oauth-token",
                "oauth-cli-secret",
                "--mcp-auth-mode",
                "both",
                "--mcp-token",
                "mcp-cli-secret",
                "--web-token",
                "web-cli-secret",
            ],
            cwd=backend,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )
        try:
            for _ in range(100):
                if process.poll() is not None:
                    msg = f"Gateway exited with {process.returncode}"
                    raise RuntimeError(msg)
                if request(base, "/healthz")[0] == 200:
                    break
                time.sleep(0.2)
            else:
                msg = "Gateway did not become ready"
                raise RuntimeError(msg)
            status, _, raw = request(base, "/healthz")
            health = json.loads(raw) if status == 200 else {}
            if health.get("auth", {}).get("mcp") != "both":
                raise AssertionError({"cli_mcp_auth_mode": health.get("auth")})
            checks = run_checks(base)
            expected = {
                "web_wrong_login": 401,
                "web_login": 200,
                "web_cookie_api": 200,
                "web_rejects_mcp_token": 401,
                "mcp_rejects_web_token": 401,
                "mcp_static_token": 200,
                "oauth_register": 200,
                "oauth_consent_page": 200,
                "oauth_authorize": 302,
                "oauth_token_exchange": 200,
                "mcp_oauth_token": 200,
                "mcp_cli_oauth_token": 200,
                "oauth_refresh_token": 200,
                "mcp_refreshed_oauth_token": 200,
                "mcp_rejects_refresh_token": 401,
                "oauth_prmd": 200,
                "oauth_as_metadata": 200,
            }
            failed = {
                key: (checks.get(key), value)
                for key, value in expected.items()
                if checks.get(key) != value
            }
            if failed:
                raise AssertionError(failed)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            # Windows may release SQLite/WAL handles one scheduler tick after
            # the terminated process reports its exit code.
            time.sleep(0.2)


def request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    body: Any = None,
    token: str = "",
    opener: Any = None,
    form: bool = False,
) -> tuple[int, dict[str, str], str]:
    data, headers = None, {}
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            headers["content-type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            headers["content-type"] = "application/json"
    if token:
        headers["authorization"] = f"Bearer {token}"
    if method not in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        headers["origin"] = base
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        response = (
            opener.open(req, timeout=15)
            if opener
            else urllib.request.urlopen(req, timeout=15)
        )
        return response.status, dict(response.headers), response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read().decode()
    except urllib.error.URLError:
        return 0, {}, ""


def mcp_initialize(base: str, token: str) -> int:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "auth-integration", "version": "1"},
        },
    }
    req = urllib.request.Request(
        base + "/mcp/",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            response.read()
            return cast("int", response.status)
    except urllib.error.HTTPError as exc:
        exc.read()
        return exc.code


def run_checks(base: str) -> dict[str, int]:
    checks: dict[str, int] = {}
    checks["web_wrong_login"] = request(
        base, "/api/auth/session", method="POST", body={"token": "wrong"}
    )[0]
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    checks["web_login"] = request(
        base,
        "/api/auth/session",
        method="POST",
        body={"token": "web-cli-secret"},
        opener=opener,
    )[0]
    checks["web_cookie_api"] = request(base, "/api/settings", opener=opener)[0]
    status, _, raw = request(base, "/.well-known/oauth-protected-resource/mcp")
    prmd = json.loads(raw) if status == 200 else {}
    checks["oauth_prmd"] = (
        200
        if (
            status == 200
            and prmd.get("resource") == base + "/mcp"
            and prmd.get("authorization_servers") == [base]
            and prmd.get("scopes_supported") == ["tools", "codex"]
        )
        else 0
    )
    status, _, raw = request(base, "/.well-known/oauth-authorization-server")
    metadata = json.loads(raw) if status == 200 else {}
    checks["oauth_as_metadata"] = (
        200
        if (
            status == 200
            and metadata.get("issuer") == base
            and metadata.get("registration_endpoint") == base + "/oauth/register"
            and metadata.get("grant_types_supported")
            == ["authorization_code", "refresh_token"]
            and metadata.get("code_challenge_methods_supported") == ["S256"]
            and metadata.get("token_endpoint_auth_methods_supported") == ["none"]
        )
        else 0
    )
    checks["web_rejects_mcp_token"] = request(
        base, "/api/settings", token="mcp-cli-secret"
    )[0]
    checks["mcp_rejects_web_token"] = mcp_initialize(base, "web-cli-secret")
    checks["mcp_static_token"] = mcp_initialize(base, "mcp-cli-secret")

    status, _, raw = request(
        base,
        "/oauth/register",
        method="POST",
        body={
            "redirect_uris": ["http://localhost/callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    checks["oauth_register"] = status
    client_id = json.loads(raw)["client_id"]
    verifier = "v" * 64
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    params = {
        "client_id": client_id,
        "redirect_uri": "http://localhost/callback",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": "tools",
        "state": "state-1",
        "resource": base + "/mcp",
    }
    status, headers, _ = request(
        base, "/oauth/authorize?" + urllib.parse.urlencode(params)
    )
    checks["oauth_consent_page"] = (
        200
        if (
            status == 200
            and "form-action 'self' http://localhost"
            in (
                headers.get("Content-Security-Policy")
                or headers.get("content-security-policy")
                or ""
            )
        )
        else 0
    )

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(
            self,
            req: Any,
            fp: Any,
            code: Any,
            msg: Any,
            headers: Any,
            newurl: Any,
        ) -> None:
            return None

    no_redirect = urllib.request.build_opener(NoRedirect)
    status, headers, _ = request(
        base,
        "/oauth/authorize",
        method="POST",
        body={**params, "password": "oauth-consent-secret"},
        opener=no_redirect,
        form=True,
    )
    checks["oauth_authorize"] = status
    location = headers.get("Location") or headers.get("location") or ""
    code = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)["code"][0]
    status, _, raw = request(
        base,
        "/oauth/token",
        method="POST",
        form=True,
        body={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": "http://localhost/callback",
            "code_verifier": verifier,
            "resource": base + "/mcp",
        },
    )
    checks["oauth_token_exchange"] = status
    tokens = json.loads(raw)
    checks["mcp_oauth_token"] = mcp_initialize(base, tokens["access_token"])
    checks["mcp_cli_oauth_token"] = mcp_initialize(base, "oauth-cli-secret")
    checks["mcp_rejects_refresh_token"] = mcp_initialize(base, tokens["refresh_token"])
    status, _, raw = request(
        base,
        "/oauth/token",
        method="POST",
        form=True,
        body={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": client_id,
            "resource": base + "/mcp",
        },
    )
    checks["oauth_refresh_token"] = status
    refreshed_tokens = json.loads(raw)
    checks["mcp_refreshed_oauth_token"] = mcp_initialize(
        base, refreshed_tokens["access_token"]
    )
    return checks


if __name__ == "__main__":
    main()
