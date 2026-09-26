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

    # Persist into the repo-root .env (gitignored). Existing unrelated keys
    # are preserved; ZOHO_* keys are replaced.
    from pathlib import Path
    env_path = Path(__file__).resolve().parents[1] / ".env"
    new_vals = {
        "ZOHO_CLIENT_ID": client_id,
        "ZOHO_CLIENT_SECRET": client_secret,
        "ZOHO_REFRESH_TOKEN": body["refresh_token"],
        "ZOHO_ACCOUNTS_URL": accounts,
        "ZOHO_API_URL": f"https://www.zohoapis.{dc}",
    }
    lines = []
    if env_path.exists():
        lines = [ln for ln in env_path.read_text(encoding="utf-8").splitlines()
                 if not ln.split("=", 1)[0].strip() in new_vals]
    lines += [f"{k}={v}" for k, v in new_vals.items()]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nSUCCESS. Credentials saved to {env_path}")
    print("This file is gitignored — keep it on this machine only.")
    print("\nNext:  python scripts/verify_endpoints.py")
    print("(all scripts and the middleware now read .env automatically)")


if __name__ == "__main__":
    main()
