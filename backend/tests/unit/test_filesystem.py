from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.config import Settings
from app.execution import ExecutionService
from app.execution.errors import NotFoundError


class FilesystemUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_unicode_crlf_edit_and_atomic_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unicode.txt"
            path.write_bytes("第一行\r\n第二行\r\n".encode("utf-8"))
            service = ExecutionService(Settings())
            result = await service.edit(str(path), "第二行", "修改后")
            self.assertEqual(result["additions"], 1)
            self.assertEqual(result["deletions"], 1)
            self.assertIn(b"\r\n", path.read_bytes())
            self.assertIn("修改后", path.read_text(encoding="utf-8"))

    async def test_binary_read_is_reported_without_text_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.bin"
            path.write_bytes(b"\x00\x01\xff\xfe")
            service = ExecutionService(Settings())
            result = await service.read(str(path))
            self.assertIn("dataBase64", result)
            self.assertEqual(result["sizeBytes"], 4)

    async def test_delete_reports_not_found(self):
        service = ExecutionService(Settings())
        with self.assertRaises(NotFoundError):
            await service.delete(str(Path(tempfile.gettempdir()) / "chatcodex-definitely-missing"))
