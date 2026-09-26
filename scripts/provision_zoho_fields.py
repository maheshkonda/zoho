#!/usr/bin/env python3
"""Provision BookLender custom fields in Zoho CRM.

Inspects the live schema FIRST (never creates duplicates), then creates only
the missing fields from zoho/fields.json.

Requires live Zoho credentials in env (ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET,
ZOHO_REFRESH_TOKEN) — cannot run in an offline build environment.

Usage:
    python scripts/provision_zoho_fields.py --dry-run   # report only
    python scripts/provision_zoho_fields.py             # create missing fields
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "middleware"))

from booklender.envfile import load_env  # noqa: E402
load_env()

from booklender.clients.zoho import ZohoHTTPClient  # noqa: E402

FIELDS_FILE = Path(__file__).resolve().parents[1] / "zoho" / "fields.json"

_TYPE_PAYLOAD = {
    "text": lambda f: {"data_type": "text", "length": f.get("length", 255)},
    "textarea": lambda f: {"data_type": "textarea", "length": 32000},
    "integer": lambda f: {"data_type": "integer"},
    "double": lambda f: {"data_type": "double", "decimal_place": 2},
    "date": lambda f: {"data_type": "date"},
    "datetime": lambda f: {"data_type": "datetime"},
    "website": lambda f: {"data_type": "website"},
    "picklist": lambda f: {
        "data_type": "picklist",
        "pick_list_values": [
            {"display_value": v, "actual_value": v} for v in f["pick_list_values"]
        ],
    },
}


def existing_field_names(client: ZohoHTTPClient, module: str) -> set[str]:
    data = client._request("GET", "/crm/v8/settings/fields", params={"module": module})
    return {fld["api_name"] for fld in data.get("fields", [])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    spec = json.loads(FIELDS_FILE.read_text(encoding="utf-8"))
    client = ZohoHTTPClient()
    rc = 0
    for module, fields in spec.items():
        if module.startswith("_"):
            continue
        existing = existing_field_names(client, module)
        for fld in fields:
            name = fld["api_name"]
            if name in existing:
                print(f"[skip] {module}.{name} already exists")
                continue
            payload = {
                "field_label": fld["field_label"],
                **_TYPE_PAYLOAD[fld["data_type"]](fld),
            }
            if fld.get("unique"):
                payload["unique"] = {"casesensitive": False}
            if args.dry_run:
                print(f"[would create] {module}.{name}: {payload}")
                continue
            try:
                client._request(
                    "POST",
                    "/crm/v8/settings/fields",
                    params={"module": module},
                    json={"fields": [payload]},
                )
                print(f"[created] {module}.{name}")
            except Exception as e:  # keep going; report at end
                print(f"[ERROR] {module}.{name}: {e}", file=sys.stderr)
                rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
