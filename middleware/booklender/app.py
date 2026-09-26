"""FastAPI webhook service.

Endpoints (all HMAC-authenticated, see security.py):
    POST /webhooks/sixsense        6sense intent signal
    POST /webhooks/clay            Clay enrichment completion
    POST /webhooks/zoho/approval   fired by the Zoho Blueprint APPROVE
                                   transition; payload is only a hint —
                                   dispatch re-validates against live Zoho
    POST /webhooks/smartlead       Smartlead engagement events
    GET  /healthz

Run: uvicorn booklender.app:create_app --factory
Env: BOOKLENDER_CONFIG=/path/to/config.yaml + secrets (docs/setup-guide.md)
"""
from __future__ import annotations

import json
import os

from fastapi import FastAPI, HTTPException, Request

from .audit import AuditLog
from .clients.vendors import ApolloHTTPClient, ClayHTTPClient, SmartleadHTTPClient
from .clients.zoho import ZohoHTTPClient
from .config import load_settings
from .idempotency import IdempotencyStore
from .pipeline import apollo_discovery, clay_sync, dispatch, engagement, sixsense
from .pipeline.context import Context
from .retry import PermanentError
from .security import SIGNATURE_HEADER, WebhookAuthError, verify


def build_context() -> Context:
    settings = load_settings(os.environ.get("BOOKLENDER_CONFIG", "config/config.yaml"))
    db = os.environ.get("BOOKLENDER_DB", "booklender.db")
    return Context(
        settings=settings,
        zoho=ZohoHTTPClient(),
        apollo=ApolloHTTPClient(),
        clay=ClayHTTPClient(),
        smartlead=SmartleadHTTPClient(),
        audit=AuditLog(db),
        idem=IdempotencyStore(db + ".idem"),
    )


def create_app(ctx: Context | None = None) -> FastAPI:
    app = FastAPI(title="BookLender Sales Automation", docs_url=None, redoc_url=None)
    app.state.ctx = ctx or build_context()

    async def _authenticated_body(request: Request, source: str) -> dict:
        body = await request.body()
        try:
            verify(source, body, request.headers.get(SIGNATURE_HEADER))
        except WebhookAuthError as e:
            raise HTTPException(status_code=401, detail=str(e))
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="invalid JSON")

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "test_mode": app.state.ctx.settings.test_mode}

    @app.post("/webhooks/sixsense")
    async def sixsense_webhook(request: Request):
        payload = await _authenticated_body(request, "sixsense")
        ctx: Context = app.state.ctx
        result = sixsense.handle_intent_signal(ctx, payload)
        if result.get("qualified") and not result.get("duplicate"):
            contacts = apollo_discovery.discover_contacts(
                ctx, account_id=result["account_id"], domain=result["domain"]
            )
            result["contact_ids"] = contacts
        return result

    @app.post("/webhooks/clay")
    async def clay_webhook(request: Request):
        payload = await _authenticated_body(request, "clay")
        try:
            return clay_sync.handle_clay_result(app.state.ctx, payload)
        except PermanentError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @app.post("/webhooks/zoho/approval")
    async def zoho_approval_webhook(request: Request):
        payload = await _authenticated_body(request, "zoho")
        contact_id = payload.get("zoho_contact_id")
        if not contact_id:
            raise HTTPException(status_code=400, detail="zoho_contact_id required")
        # SECURITY: nothing else from the payload is trusted. dispatch()
        # re-reads the live Zoho record and enforces the approval gate.
        try:
            return dispatch.dispatch_approved_contact(
                app.state.ctx, zoho_contact_id=contact_id
            )
        except dispatch.ApprovalGateError as e:
            raise HTTPException(status_code=403, detail=str(e))

    @app.post("/webhooks/smartlead")
    async def smartlead_webhook(request: Request):
        payload = await _authenticated_body(request, "smartlead")
        try:
            return engagement.handle_smartlead_event(app.state.ctx, payload)
        except PermanentError as e:
            raise HTTPException(status_code=422, detail=str(e))

    return app
