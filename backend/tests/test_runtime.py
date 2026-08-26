from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.config import Settings
from app.runtime import create_runtime


class RuntimeCompositionTests(unittest.TestCase):
    def test_runtime_is_constructible_without_starting_network_services(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(database_url=f"sqlite:///{Path(directory) / 'runtime.db'}", mcp_auth_mode="noauth")
            runtime = create_runtime(settings)
            try:
                self.assertIs(runtime.execution.settings, runtime.settings)
                self.assertIs(runtime.appserver.settings, runtime.settings)
                self.assertIs(runtime.tunnels.settings, runtime.settings)
            finally:
                runtime.close()
