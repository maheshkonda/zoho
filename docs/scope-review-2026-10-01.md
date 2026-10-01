# Scope review with client — 2026-10-01

Notes from the requirements walk-through with Krishna (client). It covers
items the earlier draft marked "out of scope". This file records what
was decided, how each item is now phased, who owns what, and what is
still open.

## 1. Ground rules agreed in the meeting

1. **"Out of scope" means only "we cannot build or deliver this."** If an
   item is buildable but large, put it in a later phase (P3/P4/P5…) and
   give the reason. Don't mark it out of scope.
2. **Anything that needs the client's resources is assigned to the client,**
   with a precise list of what we need. Examples: phone-number / 10DLC
   registration, vendor admin accounts, billing access, consent paperwork.
3. **Phasing is a trade-off between time, priority and effort.** The
   client is open to reopening budget and timeline. They want each item
   priced and placed in a phase, not dropped.
4. **The architecture is built for the long-term vision from day one.**
   Later features must plug in through defined extension points, not a
   re-architecture. Low volume now doesn't justify a design that has to be
   rebuilt at higher volume in 12–24 months.
5. **North star: one omnichannel portal.** Email, LinkedIn / Sales
   Navigator, SMS, phone and social DMs for a contact all show as one
   thread with one status. Two sales agents must never reach the same
   person through different channels without seeing each other's work.

## 2. Item-by-item disposition

| # | Requirement | Previous position | New position | Phase |
|---|---|---|---|---|
| 1 | Standard prompt templates (AI personalization prompts, not email templates) | Partial | In scope: versioned standard prompt templates. A dedicated prompt-management service is not needed yet | P1 |
| 2 | **Campaign feedback loop**: results, channels, contacts and categories feed the next campaign | Vector DB marked out of scope | **In scope as a core requirement.** Metrics drive campaign tuning as soon as reports exist. A vector DB is optional: propose a low-cost and a high-cost option with tools, costs and staffing | P2 (metrics loop) → P3/P4 (semantic memory) |
| 3 | Kafka / AWS EventBridge | Out of scope | Stays out for now (no current need). The event interface must allow a bus to be added later without rework | Deferred |
| 4 | **LinkedIn Sales Navigator two-way sync**: see and reply to Sales Navigator threads from the portal, with status and lead category | Export/import only | **Research (1 day), then commit.** Official API is off-limits: scraping or unofficial APIs risk banning the paid account. Evaluate compliant options (see §4) | P3/P4 |
| 5 | SMS + phone via RingCentral (incl. DNC / do-not-call) | Out of scope | **In scope, later phase.** 10DLC brand/campaign registration (3–5 weeks) and TCPA consent are **client-owned tasks**. Engineering starts once registration is done | P4 |
| 6 | **Scheduled contact re-validation / re-enrichment** (quarterly + manual "recheck now"), with proposed changes going to a human approval queue | Out of scope | **In scope, core.** Main use case: a contact changes role or company, so outreach to them is wasted or harmful. Client accepts the enrichment cost | P2 (P3 at latest) |
| 7 | Hot-context personalization: recent company news, posts, podcasts, Reddit, etc. | Out of scope (LinkedIn) | **In scope via Clay public-source research** (no LinkedIn scraping). Client is satisfied with this | P2 |
| 8 | Email tracking: open/click, sequences, analytics | In scope | In scope | P1/P2 |
| 9 | **Heat map inside the email body** (not the landing page) | Suggested Microsoft Clarity instead | **Placeholder: revisit.** Clarity covers landing pages only. The client wants engagement inside the email. See note in §4 | P3/P4 (TBD) |
| 10 | Auto-reply / referral handling: "John left, contact Derek" → extract Derek, enrich, link to John, stop outreach to John | Partial | **In scope.** Low volume now, but expected to matter within a year | P3 |
| 11 | Geography check + company-status check (is the company still active?) | Company status out of scope | **Research providers** (people/business directories such as Whitepages, company-registry data). Can be a plugin later | P3/P4 or separate scope |
| 12 | **Cost dashboard + automatic cost thresholds/toggles** | Auto-toggles out of scope | **In scope as one cost view across all vendors.** Use automatic thresholds/kill-switches where a vendor API allows. Pull cost data via API where possible. Otherwise the dashboard shows "check manually here" with a link. Client will provide admin/billing access where needed | P2/P3 |
| 13 | Calendar integration: booking link in outreach; agents see own + org calendar (Calendly for Teams / Zoho Bookings) | Out of scope (built-in sync exists) | **In scope:** configure team scheduling and booking-link insertion, and write booked meetings back to the contact timeline | P2/P3 |

## 3. Proposed phase layout (to be priced)

- **P1 (current):** approval-gated email pipeline (6sense → Zoho → Apollo →
  Clay → human approval → Smartlead → engagement back to Zoho), standard
  prompt templates, open/click tracking.
- **P2:** campaign metrics feedback loop (rules/statistics based), scheduled
  + manual re-enrichment through the approval queue, Clay hot-context
  research, cost dashboard v1, calendar/booking integration.
- **P3:** unified contact timeline in the portal, auto-reply/referral
  extraction, LinkedIn Sales Navigator integration (pending research),
  cost thresholds/toggles where vendors allow, company-status check.
- **P4:** SMS + phone via RingCentral (after client-owned 10DLC/TCPA
  registration), semantic campaign memory (vector store) if volume
  justifies it, in-email engagement heat map.

Each phase gets an effort estimate and a written reason for its placement
in the follow-up email.

## 4. Technical notes for the follow-up proposal

- **Feedback loop without a vector DB (low cost).** Store per-campaign,
  per-segment and per-prompt-version outcomes (sent / open / click / reply /
  positive reply / meeting / bounce / unsub) in a reporting table. Feed the
  top-performing prompt versions, angles and segments into the next
  campaign's Clay prompt and routing config. That closes the loop with plain
  SQL. **Higher-cost upgrade:** add embeddings of messages and replies
  (pgvector on the same Postgres, or a managed vector DB) for "similar past
  campaigns" retrieval. Both use the same outcome table, so the upgrade adds
  to the design without rebuilding it.
- **LinkedIn.** No scraping and no automation of the client's Sales
  Navigator session: account bans are close to certain. Options to
  evaluate: Sales Navigator's official CRM sync, which is partner-only and
  limited (activity logging for supported CRMs), and third-party
  unified-inbox providers that sales teams use. Each needs its ToS / account
  risk assessed and documented before the client decides. Fallback: manual
  "log LinkedIn touch" in the portal, so the timeline is complete even
  without automation.
- **In-email heat map.** Email clients don't run scripts, so cursor/scroll
  heat maps inside an email aren't technically possible. What is possible:
  track every link and image region with its own ID and draw a **click
  map** over the rendered email, plus image-load-based open tracking. Check
  that this meets the intent before committing.
- **Cost controls.** Three tiers per vendor. (a) API exposes usage and
  limits: show usage and set an automatic threshold. (b) API exposes usage
  only: show usage and alert. (c) Nothing exposed: a "check manually" link.
  A middleware-side budget guard can still pause *our own* calls to any
  vendor once a configured spend estimate is reached.
- **Re-enrichment.** A scheduled job plus a manual trigger re-run Apollo/Clay
  on contacts that are due. Diffs (title, company, email validity) go to the
  existing Zoho human-approval pattern; nothing is overwritten
  automatically. A changed company ends the old sequence and creates a
  linked new contact.

## 5. Extension points in the current codebase

All of these attach to existing seams. None requires re-architecture.

| Future capability | Plugs into |
|---|---|
| New channels (LinkedIn, SMS, phone) | New client in `middleware/booklender/clients/` + new signed webhook route in `app.py`. Events map onto the same engagement pipeline (`pipeline/engagement.py`) and Zoho timeline |
| Re-enrichment | Reuse `pipeline/apollo_discovery.py` / `pipeline/clay_sync.py`, triggered by a scheduler. Results land in a pending-approval state guarded by `state_machine.py` |
| Referral / auto-reply extraction | Branch in `pipeline/engagement.py` reply handling → contact upsert + link |
| Feedback loop | Outcome events already flow through `pipeline/engagement.py` and `audit.py`. Add a reporting store, and feed results into `config` / prompt versions |
| Event bus (Kafka/EventBridge) | Replace the in-process dispatch behind the same webhook handlers |

## 6. Action items

**Us**
- [ ] Send the detailed follow-up email: revised phases P1–P4, per-item effort, and the reason for each placement.
- [ ] Feedback loop proposal: low-cost vs high-cost options, tools, monthly costs, and whether a specialist hire is needed.
- [ ] LinkedIn Sales Navigator research (≈1 day): compliant way to bring threads and status into the portal and reply from it.
- [ ] RingCentral SMS/voice plan, including the exact list of registration items the client must supply.
- [ ] Cost-dashboard vendor matrix: which APIs expose usage/limits and which need admin access.
- [ ] Heat-map follow-up: confirm the click-map approach with the client, and note Microsoft Clarity for landing pages.
- [ ] Company-status / geography data provider research.
- [ ] Share implementation notes for the vector-memory option so it can be added later.

**Client (Krishna)**
- [ ] RingCentral 10DLC brand + campaign registration and TCPA consent process (we send the checklist).
- [ ] Admin / billing-level access for vendors that support cost thresholds.
- [ ] Decide on Calendly for Teams vs Zoho Bookings for org-wide scheduling.
- [ ] Confirm priorities and budget per phase once estimates arrive.

## 7. Open questions

- Which social platforms besides LinkedIn are in the DM scope?
- Re-enrichment cadence: is quarterly the default for every segment, or does it vary by segment?
- Does a click map inside the email meet the heat-map requirement?
- Phone: is click-to-call plus call logging enough, or are recording and transcription required?
