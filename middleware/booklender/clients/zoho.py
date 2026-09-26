"""Zoho CRM REST client (API v8).

Auth: OAuth2 refresh-token grant. Secrets from environment only:
    ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN
    ZOHO_ACCOUNTS_URL (default https://accounts.zoho.com)
    ZOHO_API_URL      (default https://www.zohoapis.com)

NOTE (deploy-time verification required): endpoint paths below follow the
Zoho CRM v8 REST API as documented. This environment has no network access
to Zoho, so run `scripts/verify_endpoints.py` against a sandbox org before
production use (see docs/setup-guide.md §Credentials).
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

from ..retry import IntegrationError, PermanentError


class ZohoHTTPClient:
    def __init__(self, http: httpx.Client | None = None):
        self._http = http or httpx.Client(timeout=30)
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._api = os.environ.get("ZOHO_API_URL", "https://www.zohoapis.com")
        self._accounts = os.environ.get("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com")

    # ----- auth -----------------------------------------------------------
    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        resp = self._http.post(
            f"{self._accounts}/oauth/v2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": os.environ["ZOHO_CLIENT_ID"],
                "client_secret": os.environ["ZOHO_CLIENT_SECRET"],
                "refresh_token": os.environ["ZOHO_REFRESH_TOKEN"],
            },
        )
        if resp.status_code != 200:
            raise PermanentError(f"Zoho token refresh failed: {resp.status_code}")
        data = resp.json()
        # Zoho returns HTTP 200 with {"error": "..."} for bad credentials
        if "access_token" not in data:
            raise PermanentError(
                f"Zoho token refresh rejected: {data.get('error', data)} — "
                "check ZOHO_REFRESH_TOKEN (must be the refresh token from the "
                "code exchange, NOT the grant code) and the data-center URLs"
            )
        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        try:
            resp = self._http.request(
                method,
                f"{self._api}{path}",
                headers={"Authorization": f"Zoho-oauthtoken {self._access_token()}"},
                **kwargs,
            )
        except httpx.TransportError as e:
            raise IntegrationError(f"Zoho network error: {e}") from e
        if resp.status_code in (401, 403):
            raise PermanentError(f"Zoho auth error {resp.status_code}", status_code=resp.status_code)
        if resp.status_code >= 400 and resp.status_code != 404:
            raise IntegrationError(
                f"Zoho API error {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
            )
        if resp.status_code in (204, 404):
            return {}
        return resp.json()

    # ----- Accounts ---------------------------------------------------------
    def upsert_account(self, account: dict[str, Any]) -> str:
        # duplicate_check_fields keys the upsert on the normalized domain
        data = self._request(
            "POST",
            "/crm/v8/Accounts/upsert",
            json={"data": [account], "duplicate_check_fields": ["Company_Domain"]},
        )
        return data["data"][0]["details"]["id"]

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        data = self._request("GET", f"/crm/v8/Accounts/{account_id}")
        return (data.get("data") or [None])[0]

    def find_account_by_domain(self, domain: str) -> dict[str, Any] | None:
        data = self._request(
            "GET", "/crm/v8/Accounts/search", params={"criteria": f"(Company_Domain:equals:{domain})"}
        )
        return (data.get("data") or [None])[0]

    def update_account(self, account_id: str, fields: dict[str, Any]) -> None:
        self._request("PUT", f"/crm/v8/Accounts/{account_id}", json={"data": [fields]})

    # ----- Contacts ----------------------------------------------------------
    def upsert_contact(self, contact: dict[str, Any]) -> str:
        data = self._request(
            "POST",
            "/crm/v8/Contacts/upsert",
            json={"data": [contact], "duplicate_check_fields": ["Email"]},
        )
        return data["data"][0]["details"]["id"]

    def get_contact(self, contact_id: str) -> dict[str, Any] | None:
        data = self._request("GET", f"/crm/v8/Contacts/{contact_id}")
        return (data.get("data") or [None])[0]

    def find_contact_by_email(self, email: str) -> dict[str, Any] | None:
        data = self._request(
            "GET", "/crm/v8/Contacts/search", params={"email": email}
        )
        return (data.get("data") or [None])[0]

    def update_contact(self, contact_id: str, fields: dict[str, Any]) -> None:
        self._request("PUT", f"/crm/v8/Contacts/{contact_id}", json={"data": [fields]})

    # ----- listing (console/dashboard reads) --------------------------------
    def list_accounts(self, fields: list[str]) -> list[dict[str, Any]]:
        data = self._request(
            "GET", "/crm/v8/Accounts",
            params={"fields": ",".join(fields), "per_page": 200},
        )
        return data.get("data") or []

    def list_contacts(self, fields: list[str]) -> list[dict[str, Any]]:
        data = self._request(
            "GET", "/crm/v8/Contacts",
            params={"fields": ",".join(fields), "per_page": 200},
        )
        return data.get("data") or []
