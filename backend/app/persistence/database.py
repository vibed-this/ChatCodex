# Copyright (c) 2026 ChatCodex contributors.
"""数据库层:全新项目，仅创建当前所需表。"""

from __future__ import annotations

import os
import sqlite3
import threading
import warnings
from contextlib import contextmanager
from typing import TYPE_CHECKING

from app.config import Settings, _default_database_path
from app.file_security import restrict_path_to_owner

if TYPE_CHECKING:
    from collections.abc import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_audit (
  id              TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  operation_id    TEXT,
  source          TEXT NOT NULL,
  state           TEXT NOT NULL,
  kind            TEXT,
  request_id      TEXT,
  summary         TEXT,
  payload         TEXT,
  decision        TEXT,
  decided_by      TEXT,
  action_digest   TEXT,
  context_version INTEGER,
  request_version INTEGER,
  created_at      INTEGER,
  decided_at      INTEGER
);

CREATE TABLE IF NOT EXISTS kv_config (
  key   TEXT PRIMARY KEY,
  value TEXT
);
"""


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._local = threading.local()
        url = settings.database_url
        if url.startswith("sqlite:///"):
            self.kind = "sqlite"
            self.path = os.path.abspath(os.path.expanduser(url[len("sqlite:///") :]))
        else:
            msg = f"unsupported database_url: {url}"
            raise ValueError(msg)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        if os.path.normcase(self.path) == os.path.normcase(_default_database_path()):
            self._try_restrict(os.path.dirname(self.path), directory=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        self._restrict_sqlite_files()
        return conn

    def _restrict_sqlite_files(self) -> None:
        for candidate in (self.path, self.path + "-wal", self.path + "-shm"):
            if os.path.exists(candidate):
                self._try_restrict(candidate)

    @staticmethod
    def _try_restrict(path: str, *, directory: bool = False) -> None:
        try:
            restrict_path_to_owner(path, directory=directory)
        except OSError as exc:
            warnings.warn(
                f"could not restrict local ChatCodex state permissions for {path}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._connect()
            self._local.conn = c
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None

    def _init_schema(self) -> None:
        with self.conn() as c:
            c.executescript(SCHEMA)
