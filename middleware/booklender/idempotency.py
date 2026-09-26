"""Idempotency store.

Stable external IDs (6sense account id, Apollo person id, Zoho record id,
approval timestamp) are combined into idempotency keys so that duplicate
webhook deliveries / re-runs never create duplicate records or duplicate
Smartlead leads.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone


class IdempotencyStore:
    def __init__(self, db_path: str = ":memory:"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS idempotency_keys (
                       key TEXT PRIMARY KEY,
                       result TEXT,
                       created_at TEXT NOT NULL
                   )"""
            )
            self._conn.commit()

    def claim(self, key: str, result: str = "") -> bool:
        """Atomically claim a key. Returns True if this caller won (first
        time seen), False if the operation already happened."""
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO idempotency_keys VALUES (?,?,?)",
                    (key, result, datetime.now(timezone.utc).isoformat()),
                )
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def result_of(self, key: str) -> str | None:
        cur = self._conn.execute(
            "SELECT result FROM idempotency_keys WHERE key=?", (key,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    def set_result(self, key: str, result: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE idempotency_keys SET result=? WHERE key=?", (result, key)
            )
            self._conn.commit()

    def release(self, key: str) -> None:
        """Release a claimed key after a failed attempt so a retry can re-claim it."""
        with self._lock:
            self._conn.execute("DELETE FROM idempotency_keys WHERE key=?", (key,))
            self._conn.commit()
