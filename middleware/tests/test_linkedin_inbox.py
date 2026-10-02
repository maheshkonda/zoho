"""LinkedIn extension + portal inbox: sync, ownership, outbox, dedupe."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from booklender.inbox import InboxStore, linkedin_key
from booklender.linkedin_api import TOKENS_ENV, make_router

PRIYA = {"Authorization": "Bearer tok-priya"}
RAJ = {"Authorization": "Bearer tok-raj"}

JANE_URL = "https://www.linkedin.com/in/jwhitfield-people/"
THREAD = {
    "thread_key": "thread-2a9f",
    "participant_name": "Jane Whitfield",
    "profile_url": JANE_URL,
    "thread_url": "https://www.linkedin.com/messaging/thread/thread-2a9f/",
    "messages": [
        {"id": "urn-1", "from_me": True, "text": "Hi Jane", "sent_at": "2026-09-28T14:05:00Z"},
        {"id": "urn-2", "from_me": False, "text": "Pricing for 800 people?", "sent_at": "2026-10-01T09:12:00Z"},
    ],
}


@pytest.fixture
def store():
    return InboxStore()


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setenv(TOKENS_ENV, "priya:tok-priya,raj:tok-raj")
    app = FastAPI()
    app.include_router(make_router(store))
    return TestClient(app)


def _sync(client, headers, thread=THREAD):
    r = client.post("/linkedin/ext/sync", json={"threads": [thread]}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["threads"][0]


def test_linkedin_key_normalises_profile_urls():
    assert linkedin_key("https://www.linkedin.com/in/JWhitfield-People/?trk=x") == "in/jwhitfield-people"
    assert linkedin_key("https://linkedin.com/in/jwhitfield-people") == "in/jwhitfield-people"
    assert linkedin_key("https://www.linkedin.com/sales/lead/ACwAAA123,NAME_SEARCH") == "sales/ACwAAA123"
    assert linkedin_key("https://example.com/profile") is None


def test_requests_without_valid_agent_token_are_rejected(client):
    assert client.get("/linkedin/ext/me").status_code == 401
    assert client.get("/linkedin/ext/me", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/linkedin/ext/me", headers=PRIYA).json() == {"agent": "priya"}


def test_sync_attaches_thread_to_existing_crm_contact(client, store):
    jane = store.upsert_contact(name="Jane Whitfield", profile_url="https://linkedin.com/in/jwhitfield-people",
                                email="jane@example.com", owner="priya", source="crm")
    res = _sync(client, PRIYA)
    assert res["contact_id"] == jane["contact_id"]
    assert res["added"] == 2 and res["collision"] is False


def test_sync_unknown_person_creates_contact_owned_by_syncing_agent(client, store):
    res = _sync(client, PRIYA)
    c = store.contact(res["contact_id"])
    assert c["name"] == "Jane Whitfield" and c["owner"] == "priya" and c["source"] == "linkedin-inbox"


def test_resync_does_not_duplicate_messages(client, store):
    first = _sync(client, PRIYA)
    again = _sync(client, PRIYA)
    assert again["added"] == 0
    assert len(store.thread_detail(first["thread_id"])["timeline"]) == 2


def test_portal_shows_thread_awaiting_reply(client):
    _sync(client, PRIYA)
    threads = client.get("/linkedin/portal/threads", headers=PRIYA).json()["threads"]
    assert threads[0]["awaiting_reply"] is True and threads[0]["contact"]["name"] == "Jane Whitfield"


def test_reply_flow_queue_fill_send_and_no_duplicate_on_resync(client, store):
    tid = _sync(client, PRIYA)["thread_id"]
    o = client.post(f"/linkedin/portal/threads/{tid}/reply", json={"text": "About $4 per employee."},
                    headers=PRIYA).json()
    items = client.get("/linkedin/ext/outbox", headers=PRIYA).json()["items"]
    assert [i["outbox_id"] for i in items] == [o["outbox_id"]]
    assert items[0]["thread_key"] == "thread-2a9f"
    # Raj's browser never receives Priya's replies
    assert client.get("/linkedin/ext/outbox", headers=RAJ).json()["items"] == []

    client.post(f"/linkedin/ext/outbox/{o['outbox_id']}/status", json={"status": "FILLED"}, headers=PRIYA)
    sent = client.post(f"/linkedin/ext/outbox/{o['outbox_id']}/status",
                       json={"status": "SENT", "body": "About $4 per employee per month."}, headers=PRIYA).json()
    assert sent["status"] == "SENT" and sent["body"] == "About $4 per employee per month."
    assert client.get("/linkedin/ext/outbox", headers=PRIYA).json()["items"] == []

    # The extension later reads the same message back from the page
    page = dict(THREAD, messages=THREAD["messages"] + [
        {"id": "urn-3", "from_me": True, "text": "About $4 per employee per month."}])
    assert _sync(client, PRIYA, page)["added"] == 0
    # ...and again on every later sync (e.g. when a new message arrives)
    page["messages"] = page["messages"] + [{"id": "urn-4", "from_me": False, "text": "Thanks!"}]
    assert _sync(client, PRIYA, page)["added"] == 1
    timeline = store.thread_detail(tid)["timeline"]
    out = [m for m in timeline if m["body"] == "About $4 per employee per month."]
    assert len(out) == 1 and out[0]["via"] == "portal" and out[0]["agent"] == "priya"
    # A second SENT (retry) is idempotent
    client.post(f"/linkedin/ext/outbox/{o['outbox_id']}/status", json={"status": "SENT"}, headers=PRIYA)
    assert len(store.thread_detail(tid)["timeline"]) == 4


def test_non_owner_cannot_reply_or_change_status(client):
    tid = _sync(client, PRIYA)["thread_id"]
    r = client.post(f"/linkedin/portal/threads/{tid}/reply", json={"text": "Hi from Raj"}, headers=RAJ)
    assert r.status_code == 409 and "priya" in r.json()["detail"]
    cid = client.get(f"/linkedin/portal/threads/{tid}", headers=RAJ).json()["contact_id"]
    r = client.post(f"/linkedin/portal/contacts/{cid}", json={"status": "HOT"}, headers=RAJ)
    assert r.status_code == 409


def test_non_owner_browser_activity_is_recorded_and_flagged(client, store):
    tid = _sync(client, PRIYA)["thread_id"]
    raj_thread = dict(THREAD, messages=[{"id": "urn-9", "from_me": True, "text": "Hi Jane, Raj here"}])
    res = _sync(client, RAJ, raj_thread)
    assert res["collision"] is True
    msg = [m for m in store.thread_detail(tid)["timeline"] if m["external_id"] == "urn-9"][0]
    assert msg["collision"] == 1 and msg["agent"] == "raj"


def test_owner_sets_status_and_category(client):
    tid = _sync(client, PRIYA)["thread_id"]
    cid = client.get(f"/linkedin/portal/threads/{tid}", headers=PRIYA).json()["contact_id"]
    r = client.post(f"/linkedin/portal/contacts/{cid}", json={"status": "HOT", "category": "HR"}, headers=PRIYA)
    assert r.status_code == 200 and r.json()["status"] == "HOT" and r.json()["category"] == "HR"
    bad = client.post(f"/linkedin/portal/contacts/{cid}", json={"status": "MAYBE"}, headers=PRIYA)
    assert bad.status_code == 400


def test_profile_lookup_shows_owner_and_last_touch_across_channels(client, store):
    store.upsert_contact(name="Jane Whitfield", profile_url=JANE_URL, owner="priya", status="WARM", source="crm")
    store.sync_thread("priya", {"thread_key": "sl-1", "participant_name": "Jane Whitfield",
                                "profile_url": JANE_URL, "messages": [
                                    {"id": "e1", "from_me": True, "text": "Email 1",
                                     "sent_at": "2026-09-24T13:00:00+00:00"}]}, channel="email")
    d = client.get("/linkedin/ext/profile", params={"url": JANE_URL + "?miniProfile=1"}, headers=RAJ).json()
    assert d["known"] and d["owner"] == "priya" and d["owned_by_you"] is False and d["status"] == "WARM"
    assert d["last_touch"]["channel"] == "email"
    assert client.get("/linkedin/ext/profile", params={"url": "https://www.linkedin.com/in/nobody"},
                      headers=RAJ).json() == {"known": False}


def test_contact_timeline_merges_email_and_linkedin(client, store):
    store.upsert_contact(name="Jane Whitfield", profile_url=JANE_URL, owner="priya", source="crm")
    store.sync_thread("priya", {"thread_key": "sl-1", "participant_name": "Jane Whitfield",
                                "profile_url": JANE_URL, "messages": [
                                    {"id": "e1", "from_me": True, "text": "Email 1",
                                     "sent_at": "2026-09-24T13:00:00+00:00"}]}, channel="email")
    tid = _sync(client, PRIYA)["thread_id"]
    channels = [m["channel"] for m in client.get(f"/linkedin/portal/threads/{tid}", headers=PRIYA).json()["timeline"]]
    assert channels == ["email", "linkedin", "linkedin"]
