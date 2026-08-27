from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.config import Settings
from app.runtime import create_runtime


class RuntimeCompositionTests(unittest.TestCase):
    def test_runtime_is_constructible_without_starting_network_services(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_url=f"sqlite:///{Path(directory) / 'runtime.db'}",
                mcp_auth_mode="noauth",
            )
            runtime = create_runtime(settings)
            try:
                assert runtime.execution.settings is runtime.settings
                assert runtime.tunnels.settings is runtime.settings
            finally:
                asyncio.run(runtime.close())
