#!/usr/bin/env python3
"""Local test server for the LinkedIn extension.

Serves, on one port:
    /portal                  the BookLender inbox (agents reply from here)
    /linkedin/...            the API the extension and portal call
    /mock-linkedin/...       a mock LinkedIn messaging page and profiles

Nothing here connects to LinkedIn. Seed data is fictional.

Run:
    pip install -r requirements.txt
    python linkedin-extension/dev_server.py        # http://localhost:8091

Agent tokens (dev only): priya -> dev-priya, raj -> dev-raj
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "middleware"))

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse

from booklender.inbox import InboxStore
from booklender.linkedin_api import TOKENS_ENV, make_router

PORT = int(os.environ.get("PORT", "8091"))
os.environ.setdefault(TOKENS_ENV, "priya:dev-priya,raj:dev-raj")


def seed(store: InboxStore) -> None:
    """Jane is already in the CRM from the email campaign, owned by Priya.
    Marcus is not: he appears only when his LinkedIn thread is synced."""
    store.upsert_contact(
        name="Jane Whitfield", profile_url="https://www.linkedin.com/in/jwhitfield-people",
        email="jane.whitfield@crestlinesoftware.com", company="Crestline Software",
        title="VP People", owner="priya", status="WARM", category="HR", source="crm",
    )
    store.sync_thread("priya", {
        "thread_key": "smartlead-ap-559102",
        "participant_name": "Jane Whitfield",
        "profile_url": "https://www.linkedin.com/in/jwhitfield-people",
        "messages": [{
            "id": "sl-msg-1", "from_me": True, "sent_at": "2026-09-24T13:00:00+00:00",
            "text": "Hi Jane, Crestline's careers page leads with the learning stipend and hybrid "
                    "schedule. BookLender runs a curated library for exactly that setup.",
        }],
    }, channel="email")


def create_app(db_path: str = ":memory:") -> FastAPI:
    store = InboxStore(db_path)
    seed(store)
    app = FastAPI(title="BookLender LinkedIn dev server", docs_url=None, redoc_url=None)
    app.state.inbox = store
    app.include_router(make_router(store))

    mock = HERE / "mock"

    @app.get("/")
    def index():
        return RedirectResponse("/portal")

    @app.get("/mock-linkedin/messaging", response_class=HTMLResponse)
    def mock_messaging():
        return (mock / "messaging.html").read_text(encoding="utf-8")

    @app.get("/mock-linkedin/in/{slug}", response_class=HTMLResponse)
    def mock_profile(slug: str):
        return (mock / "profile.html").read_text(encoding="utf-8")

    return app


if __name__ == "__main__":
    print(f"Portal:        http://localhost:{PORT}/portal   (tokens: dev-priya, dev-raj)")
    print(f"Mock LinkedIn: http://localhost:{PORT}/mock-linkedin/messaging")
    uvicorn.run(create_app(), host="127.0.0.1", port=PORT, log_level="warning")
