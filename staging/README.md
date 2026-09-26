# Staging Kit — real vendor trials, safe end-to-end run

Everything here runs on YOUR machine. Credentials live only in environment
variables — never in files, chat, the repo, or CRM fields. If a secret ever
leaks (pasted somewhere, screenshotted), regenerate it at the vendor and
move on.

## Checklist

### A. Zoho (15-day Enterprise trial)
- [ ] api-console.zoho.in (or .com) → **Self Client** → note Client ID + Secret
- [ ] Generate Code tab → scope:
      `ZohoCRM.modules.accounts.ALL,ZohoCRM.modules.contacts.ALL,ZohoCRM.settings.fields.ALL,ZohoCRM.settings.modules.READ`
      → 10 minutes → copy code
- [ ] `python staging/exchange_token.py`  (interactive; prints your env vars)
- [ ] Set the five `ZOHO_*` env vars it prints
- [ ] `python scripts/verify_endpoints.py` → expect `[OK] Zoho CRM`
- [ ] `python scripts/provision_zoho_fields.py --dry-run` → review → run without flag
- [ ] Click through the Blueprint per `zoho/blueprint.md`

### B. Apollo (free tier / trial)
- [ ] app.apollo.io → Settings → Integrations → API → create key
- [ ] Set `APOLLO_API_KEY`

### C. Clay (14-day Pro trial)
- [ ] Create table "BookLender Prospects" with a **Webhook** source
- [ ] Set `CLAY_WEBHOOK_URL` + `CLAY_WEBHOOK_TOKEN`
- [ ] Add columns per `docs/setup-guide.md` §4 (scrape + 3 AI columns + HTTP API out)

### D. Smartlead (trial)
- [ ] Create a TEST campaign; connect YOUR OWN mailbox only
- [ ] Settings → API key → set `SMARTLEAD_API_KEY`
- [ ] Put the test campaign id in `config/config.yaml` under `campaigns:`

### E. Middleware (local)
- [ ] `pip install -r requirements.txt`
- [ ] Generate webhook secrets: `python -c "import secrets;print(secrets.token_hex(32))"`
      once per source → set `WEBHOOK_SECRET_SIXSENSE/_CLAY/_ZOHO/_SMARTLEAD`
- [ ] Copy `config/config.example.yaml` → `config/config.yaml`; keep `test_mode: true`
- [ ] Set `BOOKLENDER_CONFIG=config/config.yaml`
- [ ] `uvicorn booklender.app:create_app --factory --port 8080` (run from `middleware/`,
      or set PYTHONPATH=middleware)
- [ ] For Clay/Zoho → laptop webhooks: expose port 8080 with a tunnel
      (`cloudflared tunnel --url http://localhost:8080` or ngrok) and use that
      URL in the Clay HTTP column and Zoho Deluge function

### F. The run
- [ ] `python staging/send_test_signal.py --company "..." --domain realcompany.com`
- [ ] Watch Zoho: Account + Contact appear; Clay row runs; contact reaches
      PENDING_HUMAN_APPROVAL
- [ ] **Before approving**: edit the contact's Email in Zoho to YOUR OWN address
      (never cold-email a real person from staging)
- [ ] Confirm the Smartlead test campaign has 0 leads
- [ ] Approve in Zoho → with `test_mode: true` the log shows
      "validated but not sent" (gate works, nothing sent)
- [ ] Flip `test_mode: false`, restart, approve → exactly 1 lead; email lands
      in your inbox
- [ ] Re-fire the approval webhook → still 1 lead
- [ ] Full pass/fail list: `docs/test-plan.md` §Live staging

## Ground rules
1. Real companies as research targets: fine. Real strangers as email
   recipients: never in staging — swap in your own address before approval.
2. `test_mode: true` until step F says otherwise.
3. Rotate any credential that was ever exposed (Zoho: API Console →
   regenerate Client Secret; the old refresh token can be revoked at
   accounts.zoho.in → Security → Connected Apps).
