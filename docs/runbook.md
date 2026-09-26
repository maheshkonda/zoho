# Operations Runbook & Troubleshooting

## Daily operator loop (Zoho only — no other tools needed)

1. Open the pinned view **"Awaiting approval"**
   (`Approval_Status = PENDING_HUMAN_APPROVAL`).
2. For each contact, read the BookLender Review section (who / why this
   account / company / why BookLender).
3. Click **APPROVE**, **REJECT** (+reason), **DO NOT CONTACT**, or
   **NEEDS REVIEW**.
4. Check the **Integration health** dashboard for `Smartlead_Sync_Status =
   ERROR` or `Clay_Enrichment_Status = INCOMPLETE/ERROR` records.

## "What happened to this prospect?"

- On the record: `Approval_Status`, `Clay_Enrichment_Status`,
  `Smartlead_Sync_Status`, `Integration_Error`, `Last_Integration_Attempt`.
- Full trail: query the audit DB —
  `sqlite3 $BOOKLENDER_DB "select timestamp,source_system,destination_system,action,status,error from audit_events where entity_id='<zoho id>' order by timestamp"`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Approved but `Smartlead_Sync_Status=ERROR`, `Integration_Error` = "HTTP 403 … gate refused" | A validation failed at dispatch (opt-out, missing pitch, missing approver stamp) | Read the reason in Integration_Error; fix the record; re-run the Blueprint transition NEEDS_REVIEW → PENDING → APPROVE |
| Approved, error mentions 429/5xx | Vendor outage; retries exhausted | Re-fire: POST the signed approval webhook again with the contact id (idempotent — safe) |
| Contact stuck in CONTACT_IDENTIFIED, Clay_Enrichment_Status=QUEUED | Clay row failed / webhook back never fired | Re-run the row in Clay; the result webhook is idempotent per clay_record_id |
| Contact went to NEEDS_REVIEW after enrichment | Clay produced empty pitch/summary (insufficient evidence — by design, no fabrication) | Write/fix manually or reject; approval is blocked until both fields exist |
| Webhook returns 401 | HMAC secret mismatch / missing header | Compare `WEBHOOK_SECRET_*` with the sender's signing config; check raw-body signing (no re-serialization) |
| Duplicate accounts in Zoho | Domain not normalized upstream | Domain is the upsert key; merge in Zoho, keep `Company_Domain` canonical (lowercase, no www) |
| Nothing arrives from 6sense | Segment/webhook misconfigured or qualification skipping | Audit log shows `qualify SKIPPED` with the exact reason (score/tier/topic/ICP); adjust config.yaml or the segment |
| Lead in Smartlead but Zoho not updated | Crash between add_lead and CRM write-back | Dispatch re-run links the existing lead (`LINKED_EXISTING`) instead of duplicating; then updates Zoho |
| Unsubscribed contact re-entered pipeline | — | Impossible to send: `Email_Opt_Out=true` blocks the gate; DNC state is terminal. If seen pending again, mark DO_NOT_CONTACT and report a bug |

## Emergency stop

1. Fastest: set `test_mode: true` in config.yaml and restart the service —
   every dispatch validates but nothing reaches Smartlead.
2. Also/or: pause the Smartlead campaign(s) in Smartlead.
3. The approval queue keeps accumulating safely — nothing auto-sends.

## Rotation / recovery

- Rotate any secret by updating the env var and the counterpart system; no
  code change. Zoho refresh token: re-generate self-client grant.
- The service is stateless except the SQLite audit/idempotency DB. Losing
  the idempotency DB does NOT enable duplicate sends: `Smartlead_Lead_ID`
  on the Zoho record and the live Smartlead email lookup are the second and
  third duplicate barriers.
- Back up `$BOOKLENDER_DB*` daily (cron + object storage) for audit history.

## Monitoring

- `GET /healthz` (uptime probe; also exposes test_mode so a prod monitor
  can alarm if it flips unexpectedly).
- Alert on: audit `FAILURE` rate > 0 in 15 min window (query the DB or ship
  it to your log stack), bounce rate > 3% (Smartlead dashboard/webhooks),
  approval queue age > 3 business days (Zoho view sorted by Last_Enriched).
