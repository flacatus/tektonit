"""SQLite-backed state persistence for the monitor.

Tracks which resources have been processed, their PR status,
and allows resuming after pod restarts without duplicating work.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("tektonit")

STATE_DB_PATH = os.environ.get("STATE_DB_PATH", "/tmp/tektonit-state.db")


@dataclass
class ProcessedResource:
    resource_name: str
    resource_kind: str
    source_path: str
    branch_name: str
    pr_url: str
    status: str
    tests_pass: bool
    fix_attempts: int
    created_at: str
    updated_at: str


@dataclass
class FailurePattern:
    """A learned pattern from past test generation failures."""

    pattern_key: str  # e.g. "bash:jq_pipe", "python:urllib_mock"
    failure_type: str  # mock_mismatch, assertion_mismatch, syntax, timeout, script_bug
    description: str  # human-readable lesson
    fix_that_worked: str  # what resolved the issue
    occurrences: int
    last_seen: str


@dataclass
class PRFeedback:
    """Feedback extracted from PR reviews."""

    resource_kind: str
    feedback_text: str
    pr_url: str
    created_at: str


class StateStore:
    """SQLite state store — lightweight, no external dependencies."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or STATE_DB_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_resources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resource_name TEXT NOT NULL,
                    resource_kind TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    branch_name TEXT NOT NULL,
                    pr_url TEXT DEFAULT '',
                    status TEXT NOT NULL,
                    tests_pass INTEGER DEFAULT 0,
                    fix_attempts INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(resource_name, resource_kind, source_path)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cycle_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    total_resources INTEGER DEFAULT 0,
                    testable INTEGER DEFAULT 0,
                    untested INTEGER DEFAULT 0,
                    prs_created INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'running'
                )
            """)
            # Episodic memory: learned failure patterns
            conn.execute("""
                CREATE TABLE IF NOT EXISTS failure_patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_key TEXT NOT NULL UNIQUE,
                    failure_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    fix_that_worked TEXT NOT NULL,
                    occurrences INTEGER DEFAULT 1,
                    last_seen TEXT NOT NULL
                )
            """)
            # PR review feedback for learning
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pr_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resource_kind TEXT NOT NULL,
                    feedback_text TEXT NOT NULL,
                    pr_url TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def mark_processed(
        self,
        resource_name: str,
        resource_kind: str,
        source_path: str,
        branch_name: str,
        pr_url: str = "",
        status: str = "pr_created",
        tests_pass: bool = False,
        fix_attempts: int = 0,
    ):
        """Record a processed resource."""
        now = self._now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO processed_resources
                    (resource_name, resource_kind, source_path, branch_name,
                     pr_url, status, tests_pass, fix_attempts, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(resource_name, resource_kind, source_path) DO UPDATE SET
                    branch_name=excluded.branch_name,
                    pr_url=excluded.pr_url,
                    status=excluded.status,
                    tests_pass=excluded.tests_pass,
                    fix_attempts=excluded.fix_attempts,
                    updated_at=excluded.updated_at
                """,
                (
                    resource_name,
                    resource_kind,
                    source_path,
                    branch_name,
                    pr_url,
                    status,
                    int(tests_pass),
                    fix_attempts,
                    now,
                    now,
                ),
            )
            conn.commit()

    def is_processed(self, resource_name: str, resource_kind: str, source_path: str) -> bool:
        """Check if a resource was successfully processed (has PR)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT status FROM processed_resources WHERE resource_name=? AND resource_kind=? AND source_path=?",
                (resource_name, resource_kind, source_path),
            ).fetchone()
            return row is not None and row[0] == "pr_created"

    def get_all_processed(self) -> list[ProcessedResource]:
        """Get all processed resources."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT resource_name, resource_kind, source_path, branch_name, "
                "pr_url, status, tests_pass, fix_attempts, created_at, updated_at "
                "FROM processed_resources ORDER BY updated_at DESC"
            ).fetchall()
            return [ProcessedResource(*r) for r in rows]

    def start_cycle(self) -> int:
        """Record the start of a monitoring cycle. Returns cycle ID."""
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT INTO cycle_history (started_at, status) VALUES (?, 'running')",
                (self._now(),),
            )
            conn.commit()
            return cursor.lastrowid

    def finish_cycle(self, cycle_id: int, summary: dict):
        """Record the end of a monitoring cycle."""
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE cycle_history SET
                    finished_at=?, total_resources=?, testable=?,
                    untested=?, prs_created=?, errors=?, status='done'
                WHERE id=?
                """,
                (
                    self._now(),
                    summary.get("total", 0),
                    summary.get("testable", 0),
                    summary.get("untested", 0),
                    summary.get("prs_created", 0),
                    summary.get("errors", 0),
                    cycle_id,
                ),
            )
            conn.commit()

    # -- Episodic memory -------------------------------------------------------

    def record_failure_pattern(
        self,
        pattern_key: str,
        failure_type: str,
        description: str,
        fix_that_worked: str,
    ):
        """Store a learned failure pattern (upsert — increments occurrences)."""
        now = self._now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO failure_patterns
                    (pattern_key, failure_type, description, fix_that_worked, occurrences, last_seen)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(pattern_key) DO UPDATE SET
                    description=excluded.description,
                    fix_that_worked=excluded.fix_that_worked,
                    occurrences=occurrences + 1,
                    last_seen=excluded.last_seen
                """,
                (pattern_key, failure_type, description, fix_that_worked, now),
            )
            conn.commit()

    def get_relevant_patterns(self, language: str, script_features: list[str]) -> list[FailurePattern]:
        """Query episodic memory for patterns relevant to this generation task.

        Matches on language prefix and any script feature keywords.
        Returns top patterns ordered by occurrences (most common first).
        """
        with self._conn() as conn:
            # Build WHERE clause: match language prefix OR any feature keyword
            conditions = [f"pattern_key LIKE '{language}:%'"]
            for feat in script_features[:10]:
                safe = feat.replace("'", "''")
                conditions.append(f"pattern_key LIKE '%{safe}%'")

            where = " OR ".join(conditions)
            rows = conn.execute(
                f"SELECT pattern_key, failure_type, description, fix_that_worked, "
                f"occurrences, last_seen FROM failure_patterns "
                f"WHERE {where} ORDER BY occurrences DESC LIMIT 10"
            ).fetchall()
            return [FailurePattern(*r) for r in rows]

    def get_all_patterns(self) -> list[FailurePattern]:
        """Get all failure patterns (for diagnostics)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT pattern_key, failure_type, description, fix_that_worked, "
                "occurrences, last_seen FROM failure_patterns "
                "ORDER BY occurrences DESC"
            ).fetchall()
            return [FailurePattern(*r) for r in rows]

    # -- PR feedback -----------------------------------------------------------

    def store_pr_feedback(self, resource_kind: str, feedback_text: str, pr_url: str):
        """Store feedback from a PR review."""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO pr_feedback (resource_kind, feedback_text, pr_url, created_at) VALUES (?, ?, ?, ?)",
                (resource_kind, feedback_text, pr_url, self._now()),
            )
            conn.commit()

    def get_pr_feedback(self, resource_kind: str, limit: int = 5) -> list[PRFeedback]:
        """Get recent PR feedback for a resource kind."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT resource_kind, feedback_text, pr_url, created_at "
                "FROM pr_feedback WHERE resource_kind=? "
                "ORDER BY created_at DESC LIMIT ?",
                (resource_kind, limit),
            ).fetchall()
            return [PRFeedback(*r) for r in rows]

    # -- Stats -----------------------------------------------------------------

    def get_stats(self) -> dict:
        """Get aggregate stats for the health endpoint."""
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM processed_resources").fetchone()[0]
            success = conn.execute("SELECT COUNT(*) FROM processed_resources WHERE status='pr_created'").fetchone()[0]
            passing = conn.execute("SELECT COUNT(*) FROM processed_resources WHERE tests_pass=1").fetchone()[0]
            cycles = conn.execute("SELECT COUNT(*) FROM cycle_history").fetchone()[0]
            return {
                "total_processed": total,
                "successful_prs": success,
                "tests_passing": passing,
                "total_cycles": cycles,
            }
