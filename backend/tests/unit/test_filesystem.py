from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

import pytest

from app.config import Settings
from app.execution import ExecutionService
from app.execution.errors import NotFoundError


class FilesystemUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_extensionless_image_is_detected_from_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image-without-extension"
            path.write_bytes(
                base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                )
            )
            service = ExecutionService(Settings())
            result = await service.read(str(path))
            assert result["mime"] == "image/png"
            assert result["dataBase64"]

    async def test_unicode_crlf_edit_and_atomic_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unicode.txt"
            path.write_bytes("第一行\r\n第二行\r\n".encode())
            service = ExecutionService(Settings())
            result = await service.edit(str(path), "第二行", "修改后")
            assert result["additions"] == 1
            assert result["deletions"] == 1
            assert b"\r\n" in path.read_bytes()
            assert "修改后" in path.read_text(encoding="utf-8")

    async def test_binary_read_is_reported_without_text_decode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.bin"
            path.write_bytes(b"\x00\x01\xff\xfe")
            service = ExecutionService(Settings())
            result = await service.read(str(path))
            assert "dataBase64" in result
            assert result["sizeBytes"] == 4

    async def test_delete_reports_not_found(self) -> None:
        service = ExecutionService(Settings())
        with pytest.raises(NotFoundError):
            await service.delete(
                str(Path(tempfile.gettempdir()) / "chatcodex-definitely-missing")
            )
