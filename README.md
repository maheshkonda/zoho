# BookLender B2B Sales Automation

End-to-end outbound prospecting system: **6sense → Zoho CRM → Apollo →
Clay (research + AI personalization) → Zoho HUMAN APPROVAL GATE →
Smartlead → engagement back to Zoho.**

**The core guarantee: no outreach without an explicit human approval in
Zoho CRM.** The gate is enforced server-side (re-read + re-validation of
the live CRM record, HMAC-authenticated webhooks, idempotency), not by UI
visibility or Make/Zapier filters. See `docs/architecture.md` §3 for the
six enforcement layers.

## Repository layout

```
config/config.example.yaml   central business config (ICP, intent thresholds,
                             titles, campaign routing, retries) — no secrets
middleware/booklender/       FastAPI webhook service (the orchestrator)
  state_machine.py           approval state machine (human-only transitions)
  pipeline/dispatch.py       THE APPROVAL GATE — read this first
  pipeline/…                 6sense, Apollo, Clay, engagement pipelines
  clients/…                  Zoho / Apollo / Clay / Smartlead REST clients
  security.py|audit.py|idempotency.py|retry.py
middleware/tests/            27 acceptance + security tests (offline fakes)
zoho/fields.json             custom field definitions (Accounts + Contacts)
zoho/blueprint.md            Blueprint spec: states, APPROVE/REJECT/DNC, layout, permissions
zoho/deluge/on_approve.dg    Deluge fn fired by the APPROVE transition
scripts/provision_zoho_fields.py   schema-aware field provisioning
scripts/verify_endpoints.py        read-only live smoke test (run first)
docs/                        architecture, field mapping, setup, runbook, test plan
```

## Quick start (development)

```bash
pip install -r requirements.txt
cd middleware && python -m pytest tests/ -v     # 27/27 pass, fully offline
```

Run the service (staging/prod — see `docs/setup-guide.md` for env vars):

```bash
export BOOKLENDER_CONFIG=config/config.yaml BOOKLENDER_DB=/var/lib/booklender/bl.db
uvicorn booklender.app:create_app --factory --port 8080
```

`test_mode: true` (the default) validates everything but never sends to
Smartlead — it stays on until the go-live checklist in
`docs/setup-guide.md` §8 is complete.

## Implementation status — honest ledger

Built and tested here (offline):
- ✅ Middleware: all pipelines, approval gate, state machine, HMAC webhook
  auth, retries w/ exponential backoff, idempotency, audit log, config
  layer, test-mode interlock — 27 automated tests green.
- ✅ Zoho field definitions + schema-aware provisioning script.
- ✅ Deluge approval function + complete Blueprint/permissions spec.
- ✅ Documentation set (architecture, mapping, setup, runbook, test plan).

Requires live credentials / manual configuration (cannot be done from this
environment — vendor APIs unreachable and no accounts provisioned):
- ⚠️ Endpoint smoke test (`scripts/verify_endpoints.py`) — client paths
  follow vendor docs but MUST be verified against live APIs first.
- ⚠️ Zoho: OAuth self-client, integration user, run field provisioning,
  click through the Blueprint (`zoho/blueprint.md`), install the Deluge fn.
- ⚠️ 6sense segment + webhook, Clay table + AI columns, Smartlead
  campaigns/webhooks (exact steps in `docs/setup-guide.md`).
- ⚠️ Deliverability: SPF/DKIM/DMARC/tracking-domain DNS + warm-up
  (`docs/setup-guide.md` §6) before any production send.
