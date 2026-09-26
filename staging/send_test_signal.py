#!/usr/bin/env python3
"""Simulate a 6sense intent signal against the running middleware.

Computes the HMAC signature for you (reads WEBHOOK_SECRET_SIXSENSE from the
environment) and POSTs a qualified signal for the company you name.

    python staging/send_test_signal.py --domain example-target.com \
        --company "Example Target Inc" --score 88 --employees 800

Downstream of this call everything is real: Apollo lookup, Clay research,
Zoho records, the approval queue.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "middleware"))
from booklender.security import SIGNATURE_HEADER, sign  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8080/webhooks/sixsense")
    ap.add_argument("--company", required=True)
    ap.add_argument("--domain", required=True)
    ap.add_argument("--score", type=int, default=88)
    ap.add_argument("--tier", default="HIGH")
    ap.add_argument("--employees", type=int, default=800)
    ap.add_argument("--country", default="United States")
    ap.add_argument("--industry", default="Software")
    ap.add_argument("--topics", default="Employee Benefits,Workplace Culture")
    args = ap.parse_args()

    secret = os.environ.get("WEBHOOK_SECRET_SIXSENSE")
    if not secret:
        raise SystemExit("Set WEBHOOK_SECRET_SIXSENSE first (same value the middleware has).")

    payload = {
        "sixsense_account_id": f"staging-{args.domain}",
        "company_name": args.company,
        "domain": args.domain,
        "website": f"https://{args.domain}",
        "industry": args.industry,
        "employee_count": args.employees,
        "country": args.country,
        "intent_score": args.score,
        "intent_tier": args.tier,
        "intent_topics": [t.strip() for t in args.topics.split(",")],
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        args.url, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 SIGNATURE_HEADER: sign(secret, body)},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            print(resp.status, resp.read().decode())
    except urllib.error.HTTPError as e:
        print(e.code, e.read().decode())
        raise SystemExit(1)


if __name__ == "__main__":
    main()
