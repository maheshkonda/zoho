"""Apollo, Clay and Smartlead HTTP clients.

Secrets from environment only:
    APOLLO_API_KEY
    CLAY_WEBHOOK_URL, CLAY_WEBHOOK_TOKEN   (Clay HTTP-source webhook for the table)
    SMARTLEAD_API_KEY

NOTE (deploy-time verification required): this build environment has no
network path to these vendors, so endpoint paths follow their public API
documentation as of the design date and MUST be smoke-tested with
`scripts/verify_endpoints.py` before production (docs/setup-guide.md).
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from ..retry import IntegrationError, PermanentError


def _check(resp: httpx.Response, vendor: str) -> None:
    if resp.status_code in (401, 403):
        raise PermanentError(f"{vendor} auth error {resp.status_code}", status_code=resp.status_code)
    if resp.status_code >= 400:
        raise IntegrationError(
            f"{vendor} API error {resp.status_code}: {resp.text[:200]}",
            status_code=resp.status_code,
        )


class ApolloHTTPClient:
    """Apollo.io People Search (POST /api/v1/mixed_people/search)."""

    BASE = "https://api.apollo.io"

    def __init__(self, http: httpx.Client | None = None):
        self._http = http or httpx.Client(timeout=30)

    def search_people(
        self, *, domain: str, titles: list[str], seniorities: list[str], limit: int
    ) -> list[dict[str, Any]]:
        try:
            resp = self._http.post(
                f"{self.BASE}/api/v1/mixed_people/search",
                headers={"X-Api-Key": os.environ["APOLLO_API_KEY"]},
                json={
                    "q_organization_domains_list": [domain],
                    "person_titles": titles,
                    "person_seniorities": seniorities,
                    "contact_email_status": ["verified"],
                    "per_page": limit,
                },
            )
        except httpx.TransportError as e:
            raise IntegrationError(f"Apollo network error: {e}") from e
        _check(resp, "Apollo")
        return resp.json().get("people", [])


class ClayHTTPClient:
    """Push a contact into a Clay table via its HTTP-source webhook.

    Clay has no public pull API for this flow: the table's 'Webhook' source
    URL + auth token are created in the Clay UI (docs/setup-guide.md §Clay)
    and stored in env vars.
    """

    def __init__(self, http: httpx.Client | None = None):
        self._http = http or httpx.Client(timeout=30)

    def enqueue_contact(self, payload: dict[str, Any]) -> str:
        try:
            resp = self._http.post(
                os.environ["CLAY_WEBHOOK_URL"],
                headers={"x-clay-webhook-auth": os.environ["CLAY_WEBHOOK_TOKEN"]},
                json=payload,
            )
        except httpx.TransportError as e:
            raise IntegrationError(f"Clay network error: {e}") from e
        _check(resp, "Clay")
        return payload.get("zoho_contact_id", "")


class SmartleadHTTPClient:
    """Smartlead campaign/lead API."""

    BASE = "https://server.smartlead.ai/api/v1"

    def __init__(self, http: httpx.Client | None = None):
        self._http = http or httpx.Client(timeout=30)

    def _params(self) -> dict[str, str]:
        return {"api_key": os.environ["SMARTLEAD_API_KEY"]}

    def find_lead_by_email(self, campaign_id: str, email: str) -> dict[str, Any] | None:
        try:
            resp = self._http.get(
                f"{self.BASE}/leads", params={**self._params(), "email": email}
            )
        except httpx.TransportError as e:
            raise IntegrationError(f"Smartlead network error: {e}") from e
        _check(resp, "Smartlead")
        data = resp.json()
        if not data or not data.get("id"):
            return None
        return data

    def add_lead(self, campaign_id: str, lead: dict[str, Any]) -> str:
        try:
            resp = self._http.post(
                f"{self.BASE}/campaigns/{campaign_id}/leads",
                params=self._params(),
                json={"lead_list": [lead], "settings": {"ignore_global_block_list": False}},
            )
        except httpx.TransportError as e:
            raise IntegrationError(f"Smartlead network error: {e}") from e
        _check(resp, "Smartlead")
        body = resp.json()
        ids = body.get("upload_stats", {}).get("lead_ids") or []
        return str(ids[0]) if ids else ""
