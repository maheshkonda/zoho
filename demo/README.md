# BookLender Prototype Demo

A fully local, self-contained demo of the sales-automation ecosystem for
client presentations. It runs the **real production pipeline code**
(qualification, discovery, enrichment sync, state machine, and the
server-side approval gate) against in-memory fake vendors with fictional
companies — **no credentials, no network calls, no real data, and nothing
can ever be emailed.**

## Run it

```bash
pip install -r requirements.txt
python demo/demo_server.py
# opens http://localhost:8090
```

*Reset data* in the header returns to a clean slate between runs.

## Suggested 7-minute walkthrough

1. **Qualification** — Ingest *Nimbus Data Systems* (score 22). The log
   shows the signal dropped by the configured threshold; nothing is created.
2. **Automation** — Ingest *Crestline Software* (score 88). Account and VP
   People appear in CRM; enrichment runs in the background (~3s) and the
   record lands in the **Approval queue** with research, work model and the
   drafted opening. Outreach panel stays empty.
3. **The gate** — On the pending card click *Run gate self-test*: the log
   shows `ERROR dispatch blocked … not APPROVED`. Explain: the dispatcher
   re-reads the CRM record server-side; a webhook alone can never send.
4. **The one human action** — Click **Approve for outreach**. Approval is
   recorded (who/when), the gate re-validates, and exactly one lead appears
   under Outreach, routed to the Remote/Hybrid campaign by config.
5. **Idempotency** — In *All prospects*, click *Replay webhook*: the log
   shows the existing lead returned; the lead count stays at 1.
6. **Honest AI** — Ingest *Bluefin Logistics*: insufficient public evidence
   → NEEDS_REVIEW, no fabricated pitch, approval blocked until fixed.
7. **Close the loop** — *Sim. reply* flips the contact to Replied;
   *Sim. unsubscribe* sets the opt-out flag — that record can never be
   dispatched again.

## What's different in production

Same code, different wiring: the sandbox adapters are replaced by the real
REST clients (Zoho OAuth, Apollo, Clay, Smartlead), the Approve button lives
in the Zoho CRM Blueprint (restricted to the Approver profile), and webhooks
are HMAC-signed. See `docs/setup-guide.md` for the go-live path.
