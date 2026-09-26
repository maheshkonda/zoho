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
    "textarea": lambda f: {"data_type": "textarea"},  # sub-type added per attempt, see _TEXTAREA_VARIANTS
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


# Zoho requires a nested "textarea" object naming the sub-type; the accepted
# enum differs between API versions/DCs, so try known variants in order.
_TEXTAREA_VARIANTS = [
    {"textarea": {"type": "plain_text_large"}},
    {"textarea": {"type": "plain_text_small"}},
    {"textarea": {"type": "plain"}},
    {"textarea": {"type": "large"}},
]


def create_field(client: ZohoHTTPClient, module: str, payload: dict) -> None:
    if payload.get("data_type") != "textarea":
        client._request("POST", "/crm/v8/settings/fields",
                        params={"module": module}, json={"fields": [payload]})
        return
    last_err: Exception | None = None
    for variant in _TEXTAREA_VARIANTS:
        try:
            client._request("POST", "/crm/v8/settings/fields",
                            params={"module": module},
                            json={"fields": [{**payload, **variant}]})
            return
        except Exception as e:  # try the next enum spelling on 400s
            last_err = e
            if "400" not in str(e):
                raise
    raise last_err  # none of the variants was accepted


def existing_fields(client: ZohoHTTPClient, module: str) -> dict[str, dict]:
    """api_name -> field metadata (includes id and field_label)."""
    data = client._request("GET", "/crm/v8/settings/fields", params={"module": module})
    return {fld["api_name"]: fld for fld in data.get("fields", [])}


def delete_field(client: ZohoHTTPClient, module: str, field_id: str) -> None:
    client._request("DELETE", f"/crm/v8/settings/fields/{field_id}",
                    params={"module": module, "delete_all_associated_data": "true"})


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
        existing = existing_fields(client, module)
        by_label = {meta.get("field_label"): (api, meta)
                    for api, meta in existing.items()}
        for fld in fields:
            name = fld["api_name"]
            if name in existing:
                print(f"[skip] {module}.{name} already exists")
                continue
            # Repair: same label exists under a Zoho-derived api_name (this
            # happens for labels Zoho can't turn into the intended api_name,
            # e.g. leading digits in "6sense ..."). Delete and recreate with
            # the explicit api_name so the pipeline's writes land.
            mismatch = by_label.get(fld["field_label"])
            if mismatch and mismatch[0] != name:
                bad_api, meta = mismatch
                if args.dry_run:
                    print(f"[would rename] {module}: '{fld['field_label']}' is "
                          f"{bad_api}, will delete + recreate as {name}")
                else:
                    try:
                        delete_field(client, module, meta["id"])
                        print(f"[deleted] {module}.{bad_api} (wrong api_name for '{fld['field_label']}')")
                    except Exception as e:
                        print(f"[ERROR] deleting {module}.{bad_api}: {e}", file=sys.stderr)
                        rc = 1
                        continue
            payload = {
                "api_name": name,
                "field_label": fld["field_label"],
                **_TYPE_PAYLOAD[fld["data_type"]](fld),
            }
            if fld.get("unique"):
                payload["unique"] = {"casesensitive": False}
            if args.dry_run:
                print(f"[would create] {module}.{name}: {payload}")
                continue
            try:
                create_field(client, module, payload)
                print(f"[created] {module}.{name}")
            except Exception as e:  # keep going; report at end
                print(f"[ERROR] {module}.{name}: {e}", file=sys.stderr)
                rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
