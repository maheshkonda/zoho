"""HTTP API for the LinkedIn browser extension and the portal inbox.

Extension (called from the extension's background worker):
    GET  /linkedin/ext/me                       which agent this token is
    POST /linkedin/ext/sync                     conversations read from the page
    GET  /linkedin/ext/outbox                   portal replies waiting for this agent
    POST /linkedin/ext/outbox/{id}/status       FILLED | SENT | CANCELLED
    GET  /linkedin/ext/profile?url=...          ownership banner for a profile

Portal (the inbox page at /portal):
    GET  /linkedin/portal/threads
    GET  /linkedin/portal/threads/{id}
    POST /linkedin/portal/threads/{id}/reply    queue a reply for the browser
    POST /linkedin/portal/contacts/{id}         set lead status / category

Every call carries ``Authorization: Bearer <agent token>``. Tokens are
configured per agent in ``LINKEDIN_AGENT_TOKENS`` as ``name:token,name:token``.
"""
from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .inbox import LEAD_STATUSES, InboxError, InboxStore, OwnershipError

TOKENS_ENV = "LINKEDIN_AGENT_TOKENS"
_PORTAL_HTML = Path(__file__).with_name("static") / "portal.html"


def _agent_tokens() -> dict[str, str]:
    pairs = {}
    for item in os.environ.get(TOKENS_ENV, "").split(","):
        name, _, token = item.strip().partition(":")
        if name and token:
            pairs[token] = name
    return pairs


def current_agent(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    presented = auth[7:] if auth.startswith("Bearer ") else ""
    if presented:
        for token, name in _agent_tokens().items():
            if hmac.compare_digest(token, presented):
                return name
    raise HTTPException(status_code=401, detail="invalid or missing agent token")


class Message(BaseModel):
    id: str
    from_me: bool = False
    text: str
    sent_at: str | None = None


class Thread(BaseModel):
    thread_key: str
    participant_name: str
    profile_url: str | None = None
    thread_url: str | None = None
    messages: list[Message] = []


class SyncBody(BaseModel):
    threads: list[Thread]


class OutboxStatus(BaseModel):
    status: str
    body: str | None = None   # final text, if the agent edited it before Send


class Reply(BaseModel):
    text: str


class ContactUpdate(BaseModel):
    status: str | None = None
    category: str | None = None


def _http(e: InboxError) -> HTTPException:
    if isinstance(e, OwnershipError):
        return HTTPException(status_code=409, detail=str(e))
    return HTTPException(status_code=400, detail=str(e))


def make_router(store: InboxStore) -> APIRouter:
    r = APIRouter()

    # ------------------------------------------------------------ extension
    @r.get("/linkedin/ext/me")
    def me(agent: str = Depends(current_agent)):
        return {"agent": agent}

    @r.post("/linkedin/ext/sync")
    def sync(body: SyncBody, agent: str = Depends(current_agent)):
        results = []
        for t in body.threads:
            try:
                results.append(store.sync_thread(agent, t.model_dump()))
            except InboxError as e:
                raise _http(e)
        return {"agent": agent, "threads": results}

    @r.get("/linkedin/ext/outbox")
    def outbox(agent: str = Depends(current_agent)):
        return {"items": store.pending_outbox(agent)}

    @r.post("/linkedin/ext/outbox/{outbox_id}/status")
    def outbox_status(outbox_id: str, body: OutboxStatus, agent: str = Depends(current_agent)):
        try:
            return store.mark_outbox(outbox_id, agent, body.status, body.body)
        except InboxError as e:
            raise _http(e)

    @r.get("/linkedin/ext/profile")
    def profile(url: str, agent: str = Depends(current_agent)):
        c = store.contact_by_profile(url)
        if not c:
            return {"known": False}
        return {
            "known": True, "contact_id": c["contact_id"], "name": c["name"],
            "owner": c["owner"], "owned_by_you": c["owner"] == agent,
            "status": c["status"], "category": c["category"],
            "last_touch": store.last_touch(c["contact_id"]),
        }

    # --------------------------------------------------------------- portal
    @r.get("/portal", response_class=HTMLResponse)
    def portal_page():
        return _PORTAL_HTML.read_text(encoding="utf-8")

    @r.get("/linkedin/portal/threads")
    def threads(agent: str = Depends(current_agent)):
        return {"agent": agent, "statuses": LEAD_STATUSES, "threads": store.list_threads()}

    @r.get("/linkedin/portal/threads/{thread_id}")
    def thread(thread_id: str, agent: str = Depends(current_agent)):
        try:
            return store.thread_detail(thread_id)
        except InboxError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @r.post("/linkedin/portal/threads/{thread_id}/reply")
    def reply(thread_id: str, body: Reply, agent: str = Depends(current_agent)):
        try:
            return store.queue_reply(thread_id, agent, body.text)
        except InboxError as e:
            raise _http(e)

    @r.post("/linkedin/portal/contacts/{contact_id}")
    def update_contact(contact_id: str, body: ContactUpdate, agent: str = Depends(current_agent)):
        try:
            return store.update_contact(contact_id, agent, status=body.status, category=body.category)
        except InboxError as e:
            raise _http(e)

    return r
