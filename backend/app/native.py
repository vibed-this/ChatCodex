# Copyright (c) 2026 ChatCodex contributors.
"""Download and resolve native Codex and tunnel-client runtime packages."""

from __future__ import annotations

import contextlib
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

TUNNEL_PUBLIC_URLS = (
    "https://github.com/openai/tunnel-client/releases/download/"
    "{release}/PUBLIC_URLS.txt"
)
MAX_NATIVE_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_NATIVE_UNPACKED_BYTES = 4 * 1024 * 1024 * 1024
MAX_NATIVE_ARCHIVE_MEMBERS = 50_000


class NativeRuntimeError(RuntimeError):
    pass


class NativeRuntimeManager:
    def __init__(self, root: str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def codex_target(self) -> str:
        arch = _arch()
        system = platform.system().lower()
        if system == "windows":
            return f"{arch}-pc-windows-msvc"
        if system == "darwin":
            return f"{arch}-apple-darwin"
        if system == "linux":
            # Official complete Codex packages are published as static musl builds.
            return f"{arch}-unknown-linux-musl"
        msg = f"unsupported operating system: {system}"
        raise NativeRuntimeError(msg)

    @property
    def tunnel_target(self) -> str:
        arch = {"x86_64": "amd64", "aarch64": "arm64"}[_arch()]
        system = platform.system().lower()
        if system not in {"windows", "darwin", "linux"}:
            msg = f"unsupported operating system: {system}"
            raise NativeRuntimeError(msg)
        return f"{system}-{arch}"

    def internal_token_file(self, token: str) -> str:
        secret_dir = self.root / "secrets"
        secret_dir.mkdir(parents=True, exist_ok=True)
        path = secret_dir / "codex-app-server.token"
        current = path.read_text(encoding="utf-8").strip() if path.exists() else ""
        if current != token:
            path.write_text(token + "\n", encoding="utf-8")
        with contextlib.suppress(OSError):
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return str(path)

    def codex_command(self) -> str:
        base = self.root / "codex" / "current"
        name = "codex.exe" if os.name == "nt" else "codex"
        candidates = [
            base / "codex" / "bin" / name,
            base / "bin" / name,
            base / name,
        ]
        return _first_executable(candidates)

    def tunnel_command(self) -> str:
        base = self.root / "tunnel-client" / "current"
        name = "tunnel-client.exe" if os.name == "nt" else "tunnel-client"
        candidates = [base / "bin" / name, base / name]
        return _first_executable(candidates)

    def status(self) -> dict[str, Any]:
        return {
            "nativeDir": str(self.root),
            "codexTarget": self.codex_target,
            "tunnelTarget": self.tunnel_target,
            "codexCommand": self.codex_command(),
            "tunnelCommand": self.tunnel_command(),
            "codexInstalled": bool(self.codex_command()),
            "tunnelInstalled": bool(self.tunnel_command()),
        }

    def install_codex(
        self,
        *,
        repository: str,
        source_url: str = "",
        archive_path: str = "",
        github_token: str = "",
    ) -> dict[str, Any]:
        if archive_path:
            archive = Path(archive_path).expanduser().resolve()
            if not archive.is_file():
                msg = f"Codex archive does not exist: {archive}"
                raise NativeRuntimeError(msg)
            _reject_wrong_target(archive.name, self.codex_target)
        else:
            url = source_url or self._latest_release_asset(repository, github_token)
            archive = self._download(
                url,
                _download_name(url, f"codex-package-{self.codex_target}.tar.gz"),
                github_token,
            )
            _reject_wrong_target(archive.name, self.codex_target)
        destination = self.root / "codex" / "current"
        self._install_archive(archive, destination)
        command = self.codex_command()
        if not command:
            msg = "Codex package is missing codex/bin/codex for this platform"
            raise NativeRuntimeError(msg)
        _make_executable(Path(command))
        return {**self.status(), "component": "codex", "source": archive.name}

    def install_tunnel_client(self, release: str) -> dict[str, Any]:
        manifest_url = TUNNEL_PUBLIC_URLS.format(release=release)
        raw = self._read_url(manifest_url).decode("utf-8", "replace")
        urls = [
            line.strip()
            for line in raw.splitlines()
            if line.strip().startswith("https://")
        ]
        suffix = f"-{self.tunnel_target}.zip"
        url = next((item for item in urls if item.endswith(suffix)), "")
        if not url:
            msg = f"tunnel-client {release} has no {self.tunnel_target} package"
            raise NativeRuntimeError(msg)
        archive = self._download(url, Path(url).name)
        destination = self.root / "tunnel-client" / "current"
        self._install_archive(archive, destination)
        command = self.tunnel_command()
        if not command:
            msg = "tunnel-client package does not contain its executable"
            raise NativeRuntimeError(msg)
        _make_executable(Path(command))
        return {**self.status(), "component": "tunnel-client", "release": release}

    def _latest_release_asset(self, repository: str, token: str) -> str:
        if "/" not in repository:
            msg = "Codex release repository must use owner/name form"
            raise NativeRuntimeError(msg)
        url = f"https://api.github.com/repos/{repository}/releases/latest"
        data = json.loads(self._read_url(url, token).decode("utf-8"))
        asset_name = f"codex-package-{self.codex_target}.tar.gz"
        asset = next(
            (item for item in data.get("assets", []) if item.get("name") == asset_name),
            None,
        )
        if not asset or not asset.get("browser_download_url"):
            msg = f"latest {repository} release does not contain {asset_name}"
            raise NativeRuntimeError(msg)
        return str(asset["browser_download_url"])

    def _download(self, url: str, filename: str, token: str = "") -> Path:
        if urlparse(url).scheme.lower() != "https":
            msg = "native runtime downloads must use HTTPS"
            raise NativeRuntimeError(msg)
        downloads = self.root / ".downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        destination = downloads / filename
        request = _request(url, token)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with (
                    _urlopen(request, timeout=120) as response,
                    destination.open("wb") as output,
                ):
                    _copy_stream(response, output, MAX_NATIVE_ARCHIVE_BYTES)
                return destination
            except Exception as exc:
                last_error = exc
                destination.unlink(missing_ok=True)
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        try:
            self._curl_download(url, destination, token)
            if destination.stat().st_size > MAX_NATIVE_ARCHIVE_BYTES:
                msg = "native runtime archive exceeds the 1 GiB limit"
                raise NativeRuntimeError(msg)
        except Exception as exc:
            destination.unlink(missing_ok=True)
            msg = f"native runtime download failed: {last_error}; curl fallback: {exc}"
            raise NativeRuntimeError(msg) from exc
        return destination

    def _curl_download(self, url: str, destination: Path, token: str) -> None:
        curl = shutil.which("curl") or shutil.which("curl.exe")
        if not curl:
            msg = "curl is unavailable"
            raise NativeRuntimeError(msg)
        argv = [
            curl,
            "--fail",
            "--location",
            "--retry",
            "3",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--user-agent",
            "ChatCodex/0.1",
            "--output",
            str(destination),
        ]
        config_path: Path | None = None
        token = token or os.environ.get("GITHUB_TOKEN", "")
        hostname = (urlparse(url).hostname or "").lower()
        if token and _is_trusted_github_host(hostname):
            fd, config_name = tempfile.mkstemp(
                prefix="chatcodex-curl-", suffix=".conf", dir=self.root
            )
            os.close(fd)
            config_path = Path(config_name)
            config_path.write_text(
                f'header = "Authorization: Bearer {token}"\n', encoding="utf-8"
            )
            with contextlib.suppress(OSError):
                config_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            argv += ["--config", str(config_path)]
        argv.append(url)
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=300,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
                check=False,
            )
            if completed.returncode != 0:
                raise NativeRuntimeError(
                    (
                        completed.stderr
                        or completed.stdout
                        or f"curl exited with {completed.returncode}"
                    )[-1000:]
                )
        finally:
            if config_path:
                config_path.unlink(missing_ok=True)

    @staticmethod
    def _read_url(url: str, token: str = "") -> bytes:
        try:
            with _urlopen(_request(url, token), timeout=30) as response:
                return bytes(response.read())
        except Exception as exc:
            msg = f"cannot read native runtime manifest: {exc}"
            raise NativeRuntimeError(msg) from exc

    def _install_archive(self, archive: Path, destination: Path) -> None:
        if archive.stat().st_size > MAX_NATIVE_ARCHIVE_BYTES:
            msg = "native runtime archive exceeds the 1 GiB limit"
            raise NativeRuntimeError(msg)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="chatcodex-native-", dir=self.root
        ) as tmp:
            staging = Path(tmp) / "payload"
            staging.mkdir()
            _extract_archive(archive, staging)
            payload = _single_directory_or_self(staging)
            incoming = destination.with_name(destination.name + ".incoming")
            if incoming.exists():
                shutil.rmtree(incoming)
            shutil.copytree(payload, incoming)
            previous = destination.with_name(destination.name + ".previous")
            if previous.exists():
                shutil.rmtree(previous)
            if destination.exists():
                destination.replace(previous)
            incoming.replace(destination)
            if previous.exists():
                shutil.rmtree(previous)


def _request(url: str, token: str = "") -> urllib.request.Request:
    hostname = (urlparse(url).hostname or "").lower()
    if hostname == "api.github.com":
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ChatCodex/0.1",
        }
    else:
        headers = {
            "Accept": "application/octet-stream",
            "User-Agent": "ChatCodex/0.1",
        }
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if token and _is_trusted_github_host(hostname):
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


class _SameOriginAuthRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward a bearer token across an HTTP redirect origin boundary."""

    def redirect_request(
        self, req: Any, fp: Any, code: Any, msg: Any, headers: Any, newurl: Any
    ) -> Any:
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old = urlparse(req.full_url)
        new = urlparse(newurl)
        if (old.scheme.lower(), old.hostname, old.port) != (
            new.scheme.lower(),
            new.hostname,
            new.port,
        ):
            redirected.remove_header("Authorization")
        return redirected


def _urlopen(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.build_opener(_SameOriginAuthRedirectHandler()).open(
        request, timeout=timeout
    )


def _is_trusted_github_host(hostname: str) -> bool:
    return hostname in {"github.com", "api.github.com"} or hostname.endswith(
        (".githubusercontent.com", ".oaiusercontent.com")
    )


def _download_name(url: str, fallback: str) -> str:
    """Keep the archive suffix from a direct/release URL for safe extraction."""
    name = Path(urlparse(url).path).name
    return name if name.lower().endswith((".zip", ".tar.gz", ".tgz")) else fallback


def _arch() -> str:
    value = platform.machine().lower()
    if value in {"amd64", "x86_64", "x64"}:
        return "x86_64"
    if value in {"arm64", "aarch64"}:
        return "aarch64"
    msg = f"unsupported architecture: {value}"
    raise NativeRuntimeError(msg)


def _first_executable(candidates: list[Path]) -> str:
    return next((str(path.resolve()) for path in candidates if path.is_file()), "")


def _make_executable(path: Path) -> None:
    if os.name != "nt":
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)


def _reject_wrong_target(filename: str, target: str) -> None:
    known = ("pc-windows", "unknown-linux", "apple-darwin")
    if any(marker in filename for marker in known) and target not in filename:
        msg = f"archive target does not match this host ({target}): {filename}"
        raise NativeRuntimeError(msg)


def _safe_target(root: Path, member: str) -> Path:
    target = (root / member).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        msg = f"archive entry escapes destination: {member}"
        raise NativeRuntimeError(msg) from exc
    return target


def _copy_stream(source: Any, destination: Any, limit: int) -> int:
    total = 0
    while True:
        chunk = source.read(1024 * 1024)
        if not chunk:
            return total
        total += len(chunk)
        if total > limit:
            msg = "native runtime archive exceeds its size limit"
            raise NativeRuntimeError(msg)
        destination.write(chunk)


def _validate_archive_size(sizes: list[int], members: int) -> None:
    if members > MAX_NATIVE_ARCHIVE_MEMBERS:
        msg = "native runtime archive contains too many entries"
        raise NativeRuntimeError(msg)
    if any(size < 0 for size in sizes) or sum(sizes) > MAX_NATIVE_UNPACKED_BYTES:
        msg = "native runtime archive exceeds the 4 GiB unpacked limit"
        raise NativeRuntimeError(msg)


def _extract_archive(archive: Path, destination: Path) -> None:
    lower = archive.name.lower()
    if lower.endswith(".zip"):
        with zipfile.ZipFile(archive) as zip_package:
            zip_members = zip_package.infolist()
            _validate_archive_size(
                [info.file_size for info in zip_members], len(zip_members)
            )
            for info in zip_members:
                target = _safe_target(destination, info.filename)
                mode = info.external_attr >> 16
                if info.flag_bits & 0x1:
                    msg = "encrypted native runtime archives are not supported"
                    raise NativeRuntimeError(msg)
                if stat.S_ISLNK(mode):
                    msg = "native runtime archives may not contain links"
                    raise NativeRuntimeError(msg)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zip_package.open(info) as zip_source, target.open("wb") as output:
                    _copy_stream(zip_source, output, info.file_size)
        return
    if lower.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive, "r:gz") as tar_package:
            tar_members = tar_package.getmembers()
            _validate_archive_size(
                [member.size for member in tar_members if member.isfile()],
                len(tar_members),
            )
            for member in tar_members:
                target = _safe_target(destination, member.name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    target.chmod(member.mode & 0o777)
                    continue
                if not member.isfile():
                    msg = (
                        "native runtime archives may contain only files and directories"
                    )
                    raise NativeRuntimeError(msg)
                tar_source = tar_package.extractfile(member)
                if tar_source is None:
                    msg = f"cannot read native runtime archive entry: {member.name}"
                    raise NativeRuntimeError(msg)
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar_source, target.open("wb") as output:
                    _copy_stream(tar_source, output, member.size)
                target.chmod(member.mode & 0o777)
        return
    msg = f"unsupported native runtime archive: {archive.name}"
    raise NativeRuntimeError(msg)


def _single_directory_or_self(root: Path) -> Path:
    entries = list(root.iterdir())
    return entries[0] if len(entries) == 1 and entries[0].is_dir() else root
