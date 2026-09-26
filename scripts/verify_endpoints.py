#!/usr/bin/env python3
"""Pre-deployment smoke test for all vendor APIs.

Run this with live credentials BEFORE enabling any workflow. It performs
read-only calls only (no records created, no emails sent) and reports which
integrations are reachable and authenticated.

    python scripts/verify_endpoints.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "middleware"))

from booklender.envfile import load_env  # noqa: E402
load_env()


def check(name: str, fn) -> bool:
    try:
        fn()
        print(f"[OK]   {name}")
        return True
    except Exception as e:
        print(f"[FAIL] {name}: {e}")
        return False


def main() -> int:
    results = []
    http = httpx.Client(timeout=20)

    def zoho():
        from booklender.clients.zoho import ZohoHTTPClient
        c = ZohoHTTPClient(http)
        c._request("GET", "/crm/v8/settings/modules")  # read-only

    def apollo():
        r = http.get(
            "https://api.apollo.io/api/v1/auth/health",
            headers={"X-Api-Key": os.environ["APOLLO_API_KEY"]},
        )
        r.raise_for_status()

    def smartlead():
        r = http.get(
            "https://server.smartlead.ai/api/v1/campaigns",
            params={"api_key": os.environ["SMARTLEAD_API_KEY"]},
        )
        r.raise_for_status()

    def clay():
        # Clay webhook URLs accept POST only; an OPTIONS/HEAD reachability
        # probe is the safest read-only check.
        r = http.head(os.environ["CLAY_WEBHOOK_URL"])
        assert r.status_code < 500, f"status {r.status_code}"

    results.append(check("Zoho CRM (OAuth + modules)", zoho))
    results.append(check("Apollo.io (auth health)", apollo))
    results.append(check("Smartlead (list campaigns)", smartlead))
    results.append(check("Clay (webhook reachability)", clay))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
