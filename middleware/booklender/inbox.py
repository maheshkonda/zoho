"""Unified inbox store: contacts, conversation threads, messages and the
portal → browser outbox for channels that are worked from the agent's own
browser (LinkedIn / Sales Navigator via the BookLender Chrome extension).

Design rules (see docs/linkedin-integration.md):
- One contact per person, keyed by the LinkedIn profile slug (``in/<slug>``)
  so a LinkedIn thread lands on the same record as the person's email.
- One owner per contact. Only the owner can reply from the portal; the first
  agent to reply to an unowned contact becomes the owner. Activity by another
  agent is still recorded, but flagged as a collision.
- Messages are deduplicated by (thread, external message id), and a reply sent
  from the portal is linked to the copy the extension later reads back from
  the page, so it is never stored twice.
- Nothing here sends anything by itself: an outbox item is only filled into
  the agent's LinkedIn compose box, and the agent clicks Send.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

LEAD_STATUSES = [
    "NEW", "COLD", "FOLLOW_UP", "WARM", "HOT", "IMMEDIATE", "ARCHIVE", "REJECT",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    contact_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    linkedin_key TEXT UNIQUE,
    profile_url TEXT,
    email TEXT,
    company TEXT,
    title TEXT,
    owner TEXT,
    status TEXT NOT NULL DEFAULT 'NEW',
    category TEXT,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS threads (
    thread_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    external_key TEXT NOT NULL,
    contact_id TEXT NOT NULL REFERENCES contacts(contact_id),
    thread_url TEXT,
    last_synced_by TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(channel, external_key)
);
CREATE TABLE IF NOT EXISTS messages (
    thread_id TEXT NOT NULL REFERENCES threads(thread_id),
    external_id TEXT NOT NULL,
    direction TEXT NOT NULL,            -- IN | OUT
    agent TEXT,                         -- who sent it (OUT only)
    body TEXT NOT NULL,
    sent_at TEXT,
    recorded_at TEXT NOT NULL,
    via TEXT NOT NULL,                  -- browser | portal
    collision INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (thread_id, external_id)
);
CREATE TABLE IF NOT EXISTS outbox (
    outbox_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(thread_id),
    agent TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL,               -- QUEUED | FILLED | SENT | CANCELLED
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    linked_external_id TEXT
);
"""

_SLUG = re.compile(r"/in/([^/?#]+)", re.I)
_SALES_LEAD = re.compile(r"/sales/lead/([^,/?#]+)", re.I)


class InboxError(Exception):
    pass


class OwnershipError(InboxError):
    def __init__(self, owner: str):
        super().__init__(f"contact is owned by {owner}")
        self.owner = owner


def linkedin_key(url: str | None) -> str | None:
    """Canonical person key from any LinkedIn / Sales Navigator profile URL."""
    if not url:
        return None
    m = _SLUG.search(url)
    if m:
        return "in/" + m.group(1).lower().rstrip("/")
    m = _SALES_LEAD.search(url)
    if m:
        return "sales/" + m.group(1)
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class InboxStore:
    def __init__(self, db_path: str = ":memory:"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------ util
    def _one(self, sql: str, args=()) -> dict | None:
        row = self._conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, args=()) -> list[dict]:
        return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    # -------------------------------------------------------------- contacts
    def upsert_contact(
        self, *, name: str, profile_url: str | None = None, email: str | None = None,
        company: str | None = None, title: str | None = None, owner: str | None = None,
        status: str = "NEW", category: str | None = None, source: str = "crm",
    ) -> dict:
        key = linkedin_key(profile_url)
        with self._lock:
            existing = self._one("SELECT * FROM contacts WHERE linkedin_key=?", (key,)) if key else None
            if existing:
                return existing
            cid = "c-" + uuid.uuid4().hex[:10]
            self._conn.execute(
                "INSERT INTO contacts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, name, key, profile_url, email, company, title, owner,
                 status, category, source, _now()),
            )
            self._conn.commit()
            return self.contact(cid)

    def contact(self, contact_id: str) -> dict:
        c = self._one("SELECT * FROM contacts WHERE contact_id=?", (contact_id,))
        if not c:
            raise InboxError(f"unknown contact {contact_id}")
        return c

    def contact_by_profile(self, url: str) -> dict | None:
        key = linkedin_key(url)
        return self._one("SELECT * FROM contacts WHERE linkedin_key=?", (key,)) if key else None

    def update_contact(self, contact_id: str, agent: str, *, status: str | None = None,
                       category: str | None = None) -> dict:
        c = self.contact(contact_id)
        if c["owner"] and c["owner"] != agent:
            raise OwnershipError(c["owner"])
        if status is not None and status not in LEAD_STATUSES:
            raise InboxError(f"invalid status {status}")
        with self._lock:
            self._conn.execute(
                "UPDATE contacts SET status=COALESCE(?,status), category=COALESCE(?,category),"
                " owner=COALESCE(owner,?) WHERE contact_id=?",
                (status, category, agent, contact_id),
            )
            self._conn.commit()
        return self.contact(contact_id)

    def last_touch(self, contact_id: str) -> dict | None:
        return self._one(
            "SELECT m.direction, m.agent, m.body, m.sent_at, m.recorded_at, t.channel"
            " FROM messages m JOIN threads t USING(thread_id) WHERE t.contact_id=?"
            " ORDER BY COALESCE(m.sent_at, m.recorded_at) DESC LIMIT 1",
            (contact_id,),
        )

    # ------------------------------------------------------- browser sync
    def sync_thread(self, agent: str, thread: dict, channel: str = "linkedin") -> dict:
        """Record one conversation read from the agent's browser.

        ``thread`` = {thread_key, participant_name, profile_url?, thread_url?,
        messages: [{id, from_me, text, sent_at?}]}
        """
        tkey = (thread.get("thread_key") or "").strip()
        name = (thread.get("participant_name") or "").strip()
        if not tkey or not name:
            raise InboxError("thread_key and participant_name are required")
        with self._lock:
            t = self._one("SELECT * FROM threads WHERE channel=? AND external_key=?", (channel, tkey))
            if t is None:
                contact = None
                if thread.get("profile_url"):
                    contact = self.contact_by_profile(thread["profile_url"])
                if contact is None:
                    contact = self.upsert_contact(
                        name=name, profile_url=thread.get("profile_url"),
                        source=f"{channel}-inbox", owner=agent,
                    )
                tid = "t-" + uuid.uuid4().hex[:10]
                self._conn.execute(
                    "INSERT INTO threads VALUES (?,?,?,?,?,?,?)",
                    (tid, channel, tkey, contact["contact_id"], thread.get("thread_url"), agent, _now()),
                )
                t = self._one("SELECT * FROM threads WHERE thread_id=?", (tid,))
            else:
                self._conn.execute(
                    "UPDATE threads SET last_synced_by=?, thread_url=COALESCE(?,thread_url) WHERE thread_id=?",
                    (agent, thread.get("thread_url"), t["thread_id"]),
                )
            contact = self.contact(t["contact_id"])
            collision = int(bool(contact["owner"]) and contact["owner"] != agent)
            added = 0
            for m in thread.get("messages") or []:
                added += self._record_message(t["thread_id"], agent, m, collision)
            self._conn.commit()
        return {"thread_id": t["thread_id"], "contact_id": contact["contact_id"],
                "added": added, "collision": bool(collision)}

    def _record_message(self, thread_id: str, agent: str, m: dict, collision: int) -> int:
        ext_id, text = str(m.get("id") or ""), (m.get("text") or "").strip()
        if not ext_id or not text:
            return 0
        if self._one("SELECT 1 FROM messages WHERE thread_id=? AND external_id=?", (thread_id, ext_id)):
            return 0
        if self._one("SELECT 1 FROM outbox WHERE thread_id=? AND linked_external_id=?", (thread_id, ext_id)):
            return 0  # page copy of a portal reply, already linked on an earlier sync
        from_me = bool(m.get("from_me"))
        if from_me:
            # Is this the page copy of a reply already sent from the portal?
            sent = self._one(
                "SELECT * FROM outbox WHERE thread_id=? AND status='SENT' AND body=?"
                " AND linked_external_id IS NULL ORDER BY updated_at LIMIT 1",
                (thread_id, text),
            )
            if sent:
                self._conn.execute(
                    "UPDATE outbox SET linked_external_id=? WHERE outbox_id=?", (ext_id, sent["outbox_id"]))
                return 0
        self._conn.execute(
            "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?)",
            (thread_id, ext_id, "OUT" if from_me else "IN", agent if from_me else None,
             text, m.get("sent_at"), _now(), "browser", collision if from_me else 0),
        )
        return 1

    # ---------------------------------------------------------------- outbox
    def queue_reply(self, thread_id: str, agent: str, body: str) -> dict:
        body = (body or "").strip()
        if not body:
            raise InboxError("reply is empty")
        with self._lock:
            t = self.thread(thread_id)
            c = self.contact(t["contact_id"])
            if c["owner"] and c["owner"] != agent:
                raise OwnershipError(c["owner"])
            if not c["owner"]:
                self._conn.execute("UPDATE contacts SET owner=? WHERE contact_id=?", (agent, c["contact_id"]))
            oid = "o-" + uuid.uuid4().hex[:10]
            now = _now()
            self._conn.execute(
                "INSERT INTO outbox VALUES (?,?,?,?,?,?,?,?)",
                (oid, thread_id, agent, body, "QUEUED", now, now, None),
            )
            self._conn.commit()
            return self._one("SELECT * FROM outbox WHERE outbox_id=?", (oid,))

    def pending_outbox(self, agent: str) -> list[dict]:
        return self._all(
            "SELECT o.*, t.external_key AS thread_key, t.thread_url, c.name AS participant_name"
            " FROM outbox o JOIN threads t USING(thread_id) JOIN contacts c ON c.contact_id=t.contact_id"
            " WHERE o.agent=? AND o.status IN ('QUEUED','FILLED') ORDER BY o.created_at",
            (agent,),
        )

    def mark_outbox(self, outbox_id: str, agent: str, status: str,
                    final_body: str | None = None) -> dict:
        """``final_body`` is the text actually sent, if the agent edited the
        filled-in reply before clicking Send."""
        if status not in ("FILLED", "SENT", "CANCELLED"):
            raise InboxError(f"invalid outbox status {status}")
        with self._lock:
            o = self._one("SELECT * FROM outbox WHERE outbox_id=?", (outbox_id,))
            if not o or o["agent"] != agent:
                raise InboxError("unknown outbox item")
            if o["status"] in ("SENT", "CANCELLED"):
                return o  # idempotent: a retry after Send never re-records it
            now = _now()
            body = (final_body or "").strip() or o["body"]
            self._conn.execute(
                "UPDATE outbox SET status=?, body=?, updated_at=? WHERE outbox_id=?",
                (status, body, now, outbox_id))
            o["body"] = body
            if status == "SENT":
                self._conn.execute(
                    "INSERT OR IGNORE INTO messages VALUES (?,?,?,?,?,?,?,?,?)",
                    (o["thread_id"], "outbox:" + outbox_id, "OUT", agent, o["body"], now, now, "portal", 0),
                )
            self._conn.commit()
            return self._one("SELECT * FROM outbox WHERE outbox_id=?", (outbox_id,))

    # ---------------------------------------------------------------- portal
    def thread(self, thread_id: str) -> dict:
        t = self._one("SELECT * FROM threads WHERE thread_id=?", (thread_id,))
        if not t:
            raise InboxError(f"unknown thread {thread_id}")
        return t

    def list_threads(self) -> list[dict]:
        out = []
        for t in self._all("SELECT * FROM threads"):
            c = self.contact(t["contact_id"])
            last = self._one(
                "SELECT * FROM messages WHERE thread_id=? ORDER BY COALESCE(sent_at, recorded_at) DESC,"
                " recorded_at DESC LIMIT 1", (t["thread_id"],))
            pending = self._one(
                "SELECT COUNT(*) AS n FROM outbox WHERE thread_id=? AND status IN ('QUEUED','FILLED')",
                (t["thread_id"],))["n"]
            out.append({
                **t, "contact": c, "last_message": last, "pending_replies": pending,
                "awaiting_reply": bool(last and last["direction"] == "IN" and not pending),
            })
        out.sort(key=lambda x: (x["last_message"] or {}).get("recorded_at", ""), reverse=True)
        return out

    def thread_detail(self, thread_id: str) -> dict:
        t = self.thread(thread_id)
        return {
            **t,
            "contact": self.contact(t["contact_id"]),
            # every channel for this person, not just this thread
            "timeline": self.contact_timeline(t["contact_id"]),
            "outbox": self._all(
                "SELECT * FROM outbox WHERE thread_id=? AND status IN ('QUEUED','FILLED') ORDER BY created_at",
                (thread_id,)),
        }

    def contact_timeline(self, contact_id: str) -> list[dict]:
        return self._all(
            "SELECT m.*, t.channel FROM messages m JOIN threads t USING(thread_id)"
            " WHERE t.contact_id=? ORDER BY COALESCE(m.sent_at, m.recorded_at), m.recorded_at",
            (contact_id,))

