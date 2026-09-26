"""Integration audit log.

Every cross-system event is recorded so an operator can answer
"what happened to this prospect?" — the log is also mirrored into the Zoho
custom module ``Integration_Logs`` (see zoho/modules.md) by the pipelines.

Never log secrets, full request bodies with PII beyond what is needed, or
AI chain-of-thought.
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    source_system TEXT NOT NULL,
    destination_system TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,               -- SUCCESS | FAILURE | RETRY | SKIPPED
    request_reference TEXT,
    response_reference TEXT,
    error TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_events(entity_type, entity_id);
"""


class AuditLog:
    def __init__(self, db_path: str = ":memory:"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)

    def record(
        self,
        *,
        source: str,
        destination: str,
        entity_type: str,
        entity_id: str,
        action: str,
        status: str,
        request_ref: str | None = None,
        response_ref: str | None = None,
        error: str | None = None,
        retry_count: int = 0,
    ) -> str:
        event_id = str(uuid.uuid4())
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    datetime.now(timezone.utc).isoformat(),
                    source,
                    destination,
                    entity_type,
                    entity_id,
                    action,
                    status,
                    request_ref,
                    response_ref,
                    error,
                    retry_count,
                ),
            )
            self._conn.commit()
        return event_id

    def events_for(self, entity_type: str, entity_id: str) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM audit_events WHERE entity_type=? AND entity_id=? ORDER BY timestamp",
            (entity_type, entity_id),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def failures(self) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM audit_events WHERE status='FAILURE' ORDER BY timestamp"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
