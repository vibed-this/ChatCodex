from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import Settings
from app.execution import ExecutionService


class SearchUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_excludes_vendor_and_generated_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "node_modules").mkdir()
            (root / "dist").mkdir()
            (root / "src" / "app.py").write_text("needle\n", encoding="utf-8")
            (root / "node_modules" / "bad.py").write_text("needle\n", encoding="utf-8")
            (root / "dist" / "bad.py").write_text("needle\n", encoding="utf-8")
            service = ExecutionService(Settings())
            globbed = await service.glob("**/*.py", str(root))
            assert [item["path"] for item in globbed["files"]] == [
                str(root / "src" / "app.py")
            ]
            grepped = await service.grep("needle", str(root), "*.py")
            assert grepped["matches"] == 1
            assert grepped["rows"][0]["path"] == str(root / "src" / "app.py")
