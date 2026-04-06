from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    from ..utils.runtime_paths import runtime_state_file
except ImportError:  # pragma: no cover - supports running report_view as a top-level package
    from utils.runtime_paths import runtime_state_file

MEMORY_DB_FILE = runtime_state_file("relatorios_memory.sqlite3")


class OperationalMemoryStore:
    def __init__(self, db_path: Path = MEMORY_DB_FILE):
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self._initialized = False

    def initialize(self):
        with self._lock:
            if self._initialized:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                self._configure(connection)
                self._create_schema(connection)
            self._initialized = True

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.initialize()
        with self._lock:
            connection = self._connect()
            try:
                self._configure(connection)
                yield connection
                connection.commit()
            finally:
                connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=2.5)
        connection.row_factory = sqlite3.Row
        return connection

    def _configure(self, connection: sqlite3.Connection):
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")

    def _create_schema(self, connection: sqlite3.Connection):
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS query_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_utc TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                raw_query TEXT NOT NULL DEFAULT '',
                normalized_query TEXT NOT NULL DEFAULT '',
                intent TEXT NOT NULL DEFAULT '',
                metric TEXT NOT NULL DEFAULT '',
                entity TEXT NOT NULL DEFAULT '',
                filters_json TEXT NOT NULL DEFAULT '[]',
                hypotheses_json TEXT NOT NULL DEFAULT '[]',
                chosen_hypothesis_json TEXT NOT NULL DEFAULT '{}',
                confidence REAL NOT NULL DEFAULT 0,
                execution_payload_json TEXT NOT NULL DEFAULT '{}',
                execution_result_summary TEXT NOT NULL DEFAULT '',
                success_flag INTEGER,
                error_message TEXT NOT NULL DEFAULT '',
                duration_ms INTEGER NOT NULL DEFAULT 0,
                source_context_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS query_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_history_id INTEGER NOT NULL,
                created_utc TEXT NOT NULL,
                feedback_type TEXT NOT NULL DEFAULT '',
                corrected_intent TEXT NOT NULL DEFAULT '',
                corrected_metric TEXT NOT NULL DEFAULT '',
                corrected_entity TEXT NOT NULL DEFAULT '',
                corrected_filters_json TEXT NOT NULL DEFAULT '[]',
                notes TEXT NOT NULL DEFAULT '',
                user_action_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (query_history_id) REFERENCES query_history(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS semantic_alias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_utc TEXT NOT NULL,
                alias_term TEXT NOT NULL,
                canonical_term TEXT NOT NULL,
                alias_type TEXT NOT NULL DEFAULT '',
                weight REAL NOT NULL DEFAULT 1,
                active INTEGER NOT NULL DEFAULT 1,
                source TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS approved_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_utc TEXT NOT NULL,
                example_query TEXT NOT NULL,
                normalized_query TEXT NOT NULL,
                intent TEXT NOT NULL DEFAULT '',
                metric TEXT NOT NULL DEFAULT '',
                entity TEXT NOT NULL DEFAULT '',
                filters_json TEXT NOT NULL DEFAULT '[]',
                notes TEXT NOT NULL DEFAULT '',
                success_weight REAL NOT NULL DEFAULT 1,
                last_used_utc TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_query_history_session_created
                ON query_history(session_id, created_utc DESC);
            CREATE INDEX IF NOT EXISTS idx_query_history_normalized
                ON query_history(normalized_query);
            CREATE INDEX IF NOT EXISTS idx_query_history_success
                ON query_history(success_flag);
            CREATE INDEX IF NOT EXISTS idx_query_feedback_query
                ON query_feedback(query_history_id, created_utc DESC);
            CREATE INDEX IF NOT EXISTS idx_semantic_alias_active
                ON semantic_alias(alias_term, active);
            CREATE INDEX IF NOT EXISTS idx_approved_examples_active
                ON approved_examples(active, normalized_query);
            """
        )
