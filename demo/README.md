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

`↺ Reset demo` in the header returns to a clean slate between runs.

## Suggested 7-minute talk track

1. **Filtering works before anything is created** — click *LowSignal Corp*
   (intent 22). Audit feed: *disqualified by config rules, nothing created*.
   Point out thresholds/ICP live in one YAML config, not code.

2. **The machine does the grunt work** — click *Acme Robotics* (intent 88).
   Watch: Zoho Account appears with 6sense intent data → Apollo finds the
   VP People → Zoho Contact → queued to Clay. Zero human effort so far.

3. **Try to cheat early** — on Jane Smith's card click
   *⚡ Attack: forged "APPROVED" webhook*. The gate refuses:
   `Approval_Status is 'CONTACT_IDENTIFIED', not APPROVED`. Explain: the
   webhook payload is never trusted; the dispatcher re-reads the CRM
   record server-side.

4. **Research + AI pitch, then a hard stop** — click *▶ Clay finishes
   research + AI pitch*. The card now shows work model, research summary,
   and the personalized pitch — everything the operator needs on one
   screen (this mirrors the Zoho Blueprint layout). Status:
   **PENDING HUMAN APPROVAL**. Feed: *⛔ Machine STOPPED*. Smartlead panel:
   still empty. Click the attack button again — still refused.

5. **The one human action** — click **✓ APPROVE**. Feed shows: human
   approval recorded (who + when) → gate re-validates → *exactly one* lead
   lands in Smartlead with `{{personalized_pitch}}` / `{{cta}}` merge vars,
   routed to the Remote/Hybrid campaign because Clay classified Acme as
   hybrid (routing is config, not code).

6. **No duplicates, ever** — click *↻ Re-deliver approval webhook*. Feed:
   duplicate delivery returned the *same* lead id. Smartlead count stays 1.

7. **Engagement closes the loop** — click *💬 Simulate reply* → contact
   flips to REPLIED in Zoho. *🚫 Simulate unsubscribe* → opt-out flag set;
   this contact can never be dispatched again.

8. **Honest AI** — fire *Globex Industrial*, run Clay: insufficient public
   evidence → work model UNKNOWN, empty pitch → **NEEDS_REVIEW**, and
   approval is blocked until a human fixes the data. The AI never
   fabricates, and incomplete records can't slip through.

9. **Rejection is final** — fire *Northwind Health*, run Clay, click
   **✕ REJECT** → attack it → still refused.

## What's different in production

Same code, different wiring: fakes are replaced by the real REST clients
(Zoho OAuth, Apollo, Clay, Smartlead), the APPROVE button lives in the Zoho
CRM Blueprint (restricted to the Approver profile), and webhooks are
HMAC-signed. See `docs/setup-guide.md` for the go-live path.
