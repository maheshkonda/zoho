"""HTTP-level security tests for the webhook service (HMAC auth + gate)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from booklender import fields as f
from booklender.app import create_app
from booklender.security import sign
from booklender.state_machine import Status

from conftest import APOLLO_PERSON, CLAY_RESULT_TEMPLATE, GOOD_SIGNAL


SECRETS = {
    "WEBHOOK_SECRET_SIXSENSE": "s6-test-secret",
    "WEBHOOK_SECRET_CLAY": "clay-test-secret",
    "WEBHOOK_SECRET_ZOHO": "zoho-test-secret",
    "WEBHOOK_SECRET_SMARTLEAD": "sl-test-secret",
}


@pytest.fixture
def client(ctx, monkeypatch):
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    app = create_app(ctx)
    return TestClient(app, raise_server_exceptions=False)


def _post(client, path, secret_env, payload, secret_override=None):
    body = json.dumps(payload).encode()
    secret = secret_override if secret_override is not None else SECRETS[secret_env]
    return client.post(
        path, content=body,
        headers={
            "Content-Type": "application/json",
            "X-BookLender-Signature": sign(secret, body),
        },
    )


def test_unsigned_webhook_is_rejected(client):
    r = client.post("/webhooks/sixsense", json=GOOD_SIGNAL)
    assert r.status_code == 401


def test_wrongly_signed_webhook_is_rejected(client):
    r = _post(client, "/webhooks/zoho/approval", "WEBHOOK_SECRET_ZOHO",
              {"zoho_contact_id": "x"}, secret_override="attacker-guess")
    assert r.status_code == 401


def test_full_flow_over_http(client, ctx):
    ctx.apollo.people[GOOD_SIGNAL["domain"]] = [APOLLO_PERSON]
    r = _post(client, "/webhooks/sixsense", "WEBHOOK_SECRET_SIXSENSE", GOOD_SIGNAL)
    assert r.status_code == 200
    contact_id = r.json()["contact_ids"][0]

    r = _post(client, "/webhooks/clay", "WEBHOOK_SECRET_CLAY",
              {"zoho_contact_id": contact_id, **CLAY_RESULT_TEMPLATE})
    assert r.status_code == 200
    assert r.json()["status"] == Status.PENDING_HUMAN_APPROVAL.value

    # approval webhook BEFORE the human approves -> 403, nothing sent
    r = _post(client, "/webhooks/zoho/approval", "WEBHOOK_SECRET_ZOHO",
              {"zoho_contact_id": contact_id, "approval_status": "APPROVED"})  # forged field ignored
    assert r.status_code == 403
    assert ctx.smartlead.leads == {}

    # human approves in Zoho
    ctx.zoho.update_contact(contact_id, {
        f.C_APPROVAL_STATUS: Status.APPROVED.value,
        f.C_APPROVAL_TS: datetime.now(timezone.utc).isoformat(),
        f.C_APPROVED_BY: "operator@booklender.example",
    })
    r = _post(client, "/webhooks/zoho/approval", "WEBHOOK_SECRET_ZOHO",
              {"zoho_contact_id": contact_id})
    assert r.status_code == 200
    assert len(ctx.smartlead.leads) == 1

    # duplicate delivery -> still one lead
    r = _post(client, "/webhooks/zoho/approval", "WEBHOOK_SECRET_ZOHO",
              {"zoho_contact_id": contact_id})
    assert r.status_code == 200 and r.json()["duplicate"] is True
    assert len(ctx.smartlead.leads) == 1

    # engagement event flows back
    r = _post(client, "/webhooks/smartlead", "WEBHOOK_SECRET_SMARTLEAD",
              {"event_type": "EMAIL_REPLY", "lead_email": APOLLO_PERSON["email"], "event_id": "ev-1"})
    assert r.status_code == 200
    assert ctx.zoho.get_contact(contact_id)[f.C_APPROVAL_STATUS] == Status.REPLIED.value
