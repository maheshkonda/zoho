# Setup Guide

Everything in this guide requires live vendor accounts/credentials and DNS
access — none of it could be executed from the offline build environment,
so each step is written to be followed exactly. Endpoint paths in the
clients follow current vendor docs; run `scripts/verify_endpoints.py`
(read-only) as the very first live step and fix any drift before deploying.

## 0. Deploy the middleware

Any host that can receive HTTPS (Cloud Run / Fly.io / a VM behind nginx):

```bash
pip install -r requirements.txt
export BOOKLENDER_CONFIG=/etc/booklender/config.yaml   # copy from config/config.example.yaml
export BOOKLENDER_DB=/var/lib/booklender/booklender.db
uvicorn booklender.app:create_app --factory --host 0.0.0.0 --port 8080
```

Environment variables (secrets manager → env; never files/CRM):

| Variable | Purpose |
|---|---|
| ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET / ZOHO_REFRESH_TOKEN | Zoho OAuth (self-client, integration user) |
| ZOHO_ACCOUNTS_URL / ZOHO_API_URL | DC-specific (default .com; use .eu/.in as applicable) |
| APOLLO_API_KEY | Apollo master API key |
| CLAY_WEBHOOK_URL / CLAY_WEBHOOK_TOKEN | Clay table HTTP source |
| SMARTLEAD_API_KEY | Smartlead API key |
| WEBHOOK_SECRET_SIXSENSE / _CLAY / _ZOHO / _SMARTLEAD | HMAC secrets you generate (`openssl rand -hex 32`, one per source) |

`test_mode: true` stays on until the go-live checklist (§8) is complete.

## 1. Zoho CRM

1. Create an **integration user** (e.g. api@booklender…) with a profile that
   can read/write Accounts+Contacts but is **not** "BookLender Approver".
2. Setup → Developer Space → Self Client → generate refresh token with scopes
   `ZohoCRM.modules.accounts.ALL,ZohoCRM.modules.contacts.ALL,ZohoCRM.settings.fields.READ,ZohoCRM.settings.fields.CREATE`.
3. `python scripts/provision_zoho_fields.py --dry-run` → review → run for real.
   (Inspects existing schema; never duplicates fields.)
4. Build the Blueprint + layout + profiles exactly per `zoho/blueprint.md`.
5. Create the Deluge function from `zoho/deluge/on_approve.dg`; set the
   middleware URL; store the `WEBHOOK_SECRET_ZOHO` value per that file's
   security note (verify the `zoho.encryption.hmacsha256` builtin signature
   in your DC; if unavailable, fall back to a static bearer header over
   HTTPS and set the same value as the secret).
6. Dashboards per `zoho/blueprint.md` §Dashboards.

## 2. 6sense

6sense Segments → create a segment from the ICP + intent criteria (mirror
config.yaml; the middleware re-checks everything, so the segment can be
broad). Delivery options, in order of preference:
1. **6sense webhook / Orchestration "Send to Webhook"** → point at
   `POST https://<host>/webhooks/sixsense`. If 6sense cannot add a custom
   HMAC header, front this one endpoint with a Make/Zapier scenario that
   receives 6sense's native integration and forwards a signed request
   (signing module: HMAC-SHA256 of raw body with WEBHOOK_SECRET_SIXSENSE).
2. Fallback: scheduled pull of segment accounts via 6sense API into the
   same handler.
Payload mapping is in docs/field-mapping.md; adapt key names in the
scenario, not in code.

## 3. Apollo

Nothing to configure server-side; the middleware calls People Search with
config-driven titles/seniorities/domains and verified-email filter. Ensure
the API plan includes people search + email reveal credits.

## 4. Clay

Create table **"BookLender Prospects"**:
1. Source: **Webhook** → copy URL+token into `CLAY_WEBHOOK_URL/_TOKEN`.
2. Columns (in order):
   - Inputs: zoho_contact_id, zoho_account_id, first_name, last_name,
     title, email, linkedin_url, company_domain.
   - Enrichment: "Scrape Website" on company_domain (+ careers page).
   - **AI column "Work model"** — prompt (temperature low):
     > Using ONLY the scraped website/careers content provided, classify the
     > company's work model as REMOTE, HYBRID, ON_SITE, or UNKNOWN. Do not
     > guess: if evidence is insufficient, answer UNKNOWN with confidence
     > ≤ 0.3. Return JSON: {"work_model": "...", "confidence": 0.0-1.0,
     > "evidence": "verbatim snippets"}.
   - **AI column "Research summary"**: 2–3 factual sentences on HR/benefits/
     culture signals relevant to a corporate book-lending benefit, citing
     only provided content; empty string if nothing verifiable.
   - **AI column "Pitch"** — prompt guardrails:
     > Write a 2-sentence opening for {first_name}, {title} at {company},
     > referencing ONLY facts in the research. Forbidden: generic flattery,
     > invented facts, claims of prior conversations, spammy language,
     > over-familiarity. Then a one-line CTA. Return JSON:
     > {"personalized_pitch": "...", "cta": "..."}.
   - Output: **HTTP API column** → POST to
     `https://<host>/webhooks/clay` with header
     `X-BookLender-Signature: sha256=<HMAC of body>` — Clay's HTTP column
     supports static headers only, so either (a) route via a tiny Make
     scenario that signs, or (b) use a long random bearer token as the
     Clay→middleware secret and set `WEBHOOK_SECRET_CLAY` accordingly.
     Body: `{zoho_contact_id, clay_record_id, work_model, confidence,
     research_summary, personalized_pitch, cta}`.
3. Run-once per row (Clay's default); the middleware is idempotent on
   `clay_record_id` regardless.

## 5. Smartlead

1. Create campaigns (test + production, e.g. "BookLender HR Outreach —
   Remote/Hybrid", "— General"). Put their IDs ONLY in `config.yaml
   campaigns:` — nowhere else.
2. Sequence templates using `{{first_name}} {{company}} {{job_title}}
   {{personalized_pitch}} {{cta}}` custom variables.
3. Webhooks (Settings → Webhooks): EMAIL_SENT, EMAIL_REPLY, EMAIL_BOUNCE,
   LEAD_UNSUBSCRIBED → `https://<host>/webhooks/smartlead`; include the
   secret per §0 (Smartlead sends a configurable secret field — verify the
   exact mechanism on your plan; if header signing is unavailable, use the
   bearer-token fallback as with Clay).
4. Enable global block list; unsubscribes must also flow back (handled →
   `Email_Opt_Out=true` in Zoho).

## 6. Deliverability (before ANY production send)

Use dedicated sending domains (e.g. `trybooklender.com`,
`getbooklender.com`), never the primary corporate domain.

Checklist per sending domain:
- [ ] SPF: `v=spf1 include:<esp-include-per-mailbox-provider> ~all` (one SPF record only)
- [ ] DKIM: provider-issued selector CNAMEs/TXT published and verified
- [ ] DMARC: start `v=DMARC1; p=none; rua=mailto:dmarc@<domain>` → tighten to `p=quarantine` after 2–4 clean weeks
- [ ] Custom tracking domain CNAME (Smartlead settings) — no shared tracking domain
- [ ] MX + valid A record + HTTPS redirect of the bare domain to the main site
- [ ] 2–3 mailboxes per domain, max ~30–50 sends/day/mailbox after warm-up
- [ ] Smartlead warm-up enabled ≥ 3 weeks before campaign start; ramp 10→30/day
- [ ] Validate: `dig txt <domain>`, `dig txt _dmarc.<domain>`, and a seed-list test (GlockApps or similar)
- [ ] Bounce threshold alarm: pause campaign if bounce rate > 3%

## 7. Make/Zapier (optional glue only)

Allowed uses: 6sense→middleware relay signing (§2), Clay→middleware signing
(§4), Slack notification "N contacts awaiting approval". NOT allowed: any
scenario that writes to Smartlead — the middleware is the only Smartlead
writer, and it only acts after re-validating approval in Zoho.

## 8. Production go-live checklist

1. [ ] `scripts/verify_endpoints.py` all green
2. [ ] `pytest middleware/tests` green in CI
3. [ ] Field provisioning done; Blueprint + profiles configured; integration user cannot see APPROVE button (verify by logging in as it)
4. [ ] End-to-end test in `test_mode: true` with a fake company/test contact per docs/test-plan.md — Smartlead receives nothing
5. [ ] Repeat with `test_mode: false` + **test campaign + your own mailbox** — exactly one lead arrives, duplicate approval sends nothing
6. [ ] Deliverability checklist (§6) complete; warm-up matured
7. [ ] Switch config campaigns to production IDs, set `test_mode: false`, deploy
8. [ ] First week: cap 6sense segment volume; review every approval queue daily; watch bounce dashboard
