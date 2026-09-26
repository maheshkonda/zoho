# Test Plan

## Automated acceptance suite (runs offline, no live systems)

`cd middleware && python -m pytest tests/ -v` — 27 tests, all passing.
The suite drives the real pipeline code against in-memory fakes that
implement the same client interfaces as the HTTP clients.

| # | Requirement (§26) | Test(s) | Result |
|---|---|---|---|
| 1 | New intent account → Zoho Account | test_1, test_1b (idempotent), test_1c (below threshold skipped) | ✅ |
| 2 | Apollo → Zoho Contact | test_2 (dedupe + Clay handoff), test_2b (CRM precedence) | ✅ |
| 3 | Clay → Zoho | test_3, test_3b (duplicate completion idempotent) | ✅ |
| 4 | Approval gate: PENDING + no Smartlead activity | test_4, test_4b (middleware cannot perform APPROVE transition) | ✅ |
| 5 | Reject → no Smartlead activity | test_5, test_5b (DNC) | ✅ |
| 6 | Approve → Smartlead receives lead | test_6, test_6b (approval without approver stamp refused) | ✅ |
| 7 | Duplicate approval → no duplicate lead | test_7, test_7b (pre-existing Smartlead lead linked, not duplicated) | ✅ |
| 8 | Opt-out → no submission | test_8 | ✅ |
| 9 | API failure → logged + retried | test_9a (Zoho 503 ×2 then success), test_9b (Smartlead 500), test_9c (exhaustion → ERROR on record → later recovery, still one lead) | ✅ |
| 10 | Missing personalization blocks approval | test_10 (NEEDS_REVIEW + gate refusal even if status forced) | ✅ |
| — | Forged webhook payload cannot bypass gate | test_sec_forged_webhook_payload…, test_wrongly_signed_webhook… (HTTP 401) | ✅ |
| — | test_mode interlock | test_sec_test_mode_interlock… | ✅ |
| — | Campaign routing by work model | test_6 (HYBRID→CAMP-RH), test_sec_unknown_work_model… (→ catch-all) | ✅ |
| — | Engagement events → Zoho (reply, unsubscribe→opt-out) | test_engagement_events… | ✅ |
| — | Full flow over HTTP incl. HMAC auth | test_full_flow_over_http | ✅ |

## Live staging verification (manual, after credentials exist)

Use only: fake company (`acme-test.example.com`-style domain you control or
a sandbox record), your own mailbox as the contact email, a **test
Smartlead campaign** with sending disabled or pointed at seed inboxes.

1. `scripts/verify_endpoints.py` → all OK.
2. Fire a test 6sense payload (curl with HMAC) → Account + Contact appear
   in Zoho; Clay row created.
3. Clay completes → Contact shows research/pitch, status
   PENDING_HUMAN_APPROVAL. **Confirm Smartlead test campaign has 0 leads.**
4. Click REJECT → confirm 0 leads; reopen via NEEDS_REVIEW.
5. Click DO NOT CONTACT on a second test contact → confirm 0 leads and
   Email_Opt_Out set.
6. Click APPROVE → exactly 1 lead in the test campaign; Zoho shows
   SENT_TO_SMARTLEAD / ACTIVE + lead id.
7. Re-fire the approval webhook manually (curl, same id) → still 1 lead.
8. Reply from the seed inbox → Zoho contact shows REPLIED.
9. Unsubscribe link → Zoho shows UNSUBSCRIBED + Email_Opt_Out.
10. Log in as the integration user → verify the APPROVE button is not
    available in the Blueprint.
