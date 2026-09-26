#!/usr/bin/env python3
"""Exchange a Zoho Self Client grant code for a permanent refresh token.

Run on YOUR machine (needs internet access to Zoho). Prompts interactively
so credentials never land in shell history or files.

    python staging/exchange_token.py
"""
from __future__ import annotations

import getpass
import json
import urllib.parse
import urllib.request


def main() -> None:
    print("Zoho Self Client -> refresh token exchange")
    print("-" * 50)
    dc = input("Data center [.in for crm.zoho.in / .com for crm.zoho.com] (in/com): ").strip().lower().lstrip(".") or "in"
    if dc not in {"in", "com", "eu", "com.au", "jp", "sa", "com.cn", "ca"}:
        raise SystemExit(f"Unknown data center {dc!r} — expected one of: in, com, eu, com.au, jp, sa, ca")
    accounts = f"https://accounts.zoho.{dc}"
    client_id = input("Client ID: ").strip()
    client_secret = getpass.getpass("Client Secret (hidden): ").strip()
    code = getpass.getpass("Grant code from 'Generate Code' tab (hidden, expires ~10 min): ").strip()

    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
    }).encode()
    req = urllib.request.Request(f"{accounts}/oauth/v2/token", data=data, method="POST")
    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read())

    if "refresh_token" not in body:
        print(f"\nFAILED: {json.dumps(body)}")
        if body.get("error") == "invalid_code":
            print("The grant code expired or was already used. Generate a fresh one "
                  "in the API Console (Generate Code tab) and re-run this script.")
        raise SystemExit(1)

    print("\nSUCCESS. Set these environment variables (PowerShell shown):\n")
    print(f'  $env:ZOHO_CLIENT_ID     = "{client_id}"')
    print(f'  $env:ZOHO_CLIENT_SECRET = "<the client secret>"')
    print(f'  $env:ZOHO_REFRESH_TOKEN = "{body["refresh_token"]}"')
    print(f'  $env:ZOHO_ACCOUNTS_URL  = "{accounts}"')
    print(f'  $env:ZOHO_API_URL       = "https://www.zohoapis.{dc}"')
    print("\nThen run:  python scripts/verify_endpoints.py")
    print("\nNote: the refresh token above was printed to your terminal only. "
          "Do not commit it, share it, or store it outside env vars / a secrets manager.")


if __name__ == "__main__":
    main()
