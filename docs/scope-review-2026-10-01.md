# Client requirements register — meeting of 2026-10-01

This is the full list of what Krishna (the client) raised in the
requirements walk-through. **Every item the earlier draft marked "out of
scope" is now a deliverable.** Krishna's instruction was explicit: if it
can be built, it gets built. Only the phase can change, and each phase
placement needs a written reason. Items that need his accounts, paperwork
or money are assigned to him by name.

---

## 0. Ground rules set by Krishna

1. **"Out of scope" may only mean "this cannot be built or delivered."**
   Large or slow items go into a later phase (P2, P3, P4…) with a written
   reason and a timeline. They do not get dropped.
2. **Anything that needs his resources gets assigned to him,** with an exact
   list of what we need. Examples: RingCentral number / 10DLC registration,
   TCPA consent, vendor admin and billing accounts, calendar choice.
3. **Each item is placed by time, priority and effort.** Every item gets an
   estimate so he can trade them off. Budget and timeline can be reopened
   (Nathan / Praveen to join that discussion).
4. **The architecture is built for the long-term vision from day one.**
   Volume will grow over months and years. When it does, we add components;
   we never re-architect or re-engineer.
5. **One platform for every channel.** He is building this instead of using
   Mailchimp or Constant Contact precisely because single-channel email
   tools aren't enough. Email, LinkedIn / Sales Navigator, SMS, phone and
   social DMs must all live in one portal.
6. **Add a Phase 4 (and later phases if needed).** Send a detailed email
   with the solution and timeline for every item below.

---

## 1. Omnichannel unified inbox: one view per contact (core requirement)

**What Krishna asked**
- One portal and one view for all sales agents, covering every channel and
  every communication.
- If John replies on Sales Navigator, the reply shows in the portal. The
  same goes for his texts, phone calls and emails. John's full communication
  history is in one place.
- Agents **reply from the portal** on any channel. The thread updates and
  shows "replied", who replied and when.
- Agents can **mark the lead status / category** from the portal.
- Two or three agents must never reach the same person at different stages
  without knowing it. That breaks the company's impression and reputation,
  especially while the company is growing.

**Must deliver**
- A contact timeline that merges every inbound and outbound message, call
  and status change on all channels (email, LinkedIn, SMS, phone, other
  social DMs).
- Replies to email, LinkedIn and SMS sent from the portal, with
  click-to-call / call logging for phone.
- Thread status (new, replied, awaiting reply), owner agent, and a lead
  category agents can set from the portal.
- Collision protection:
  - one owner per contact
  - a warning or lock when a second agent tries to contact the same person
  - a recent-touch indicator across all channels
- Each person linked to one contact record across their email, phone
  number and LinkedIn profile (identity resolution).

**Phase:** the core timeline and email in P2. Each other channel joins the
same timeline when it goes live (P3/P4).

---

## 2. LinkedIn Sales Navigator integration

**What Krishna asked**
- His team has done most of its outreach through Sales Navigator for about
  10 months. Sales Navigator's limited features make it very hard to track
  which contacts were reached.
- He wants **automatic integration, direct or indirect**. An
  export/import process alone is not acceptable.
- Agents must **see and reply to Sales Navigator messages from the portal**.
  The portal shows the reply thread, the "replied" status and the lead
  category the agent set.
- Prospects often answer an email campaign on LinkedIn instead. Without
  this sync there are two disconnected views of one conversation, which is
  exactly what he wants to avoid.
- He has seen sales outreach companies pull Sales Navigator contacts and
  statuses into their own dashboards, so he expects this to be doable.
- He doesn't want to risk his account. The integration must not get it
  banned.

**Must deliver**
- Two-way message sync between Sales Navigator / LinkedIn and the portal:
  - inbound messages land on the contact timeline
  - outbound replies are composed in the portal and delivered on LinkedIn
- A one-time backfill of the last ~10 months of Sales Navigator
  conversations and contacts, so past outreach can be tracked.
- LinkedIn connection and message status per contact (invited, connected,
  messaged, replied) shown in the portal and in Zoho.
- LinkedIn profile URLs captured during enrichment (Apollo / Zoho / Clay)
  and stored alongside email, so a LinkedIn thread matches the right
  contact.
- **Method:** pick the account-safe way to do this, the same approach the
  outreach companies he mentioned use. Options:
  - a sync agent or extension running in each agent's own logged-in session
  - a vetted third-party LinkedIn messaging/inbox provider
  - Sales Navigator's official CRM sync, where it applies

  No scraping and no direct use of the LinkedIn API on his account. Put the
  chosen method, its cost and its account-risk assessment in the follow-up
  email. The developer committed to a one-day research turnaround and said
  this is achievable.

**Phase:** P3. The method decision and the history backfill go first.

---

## 3. SMS and phone via RingCentral (including do-not-call)

**What Krishna asked**
- Text and phone are part of the omnichannel requirement, and he already
  has RingCentral.
- The registration and paperwork (10DLC, TCPA consent, numbers) is **his
  job**. Assign it to him and tell him exactly what we need. That paperwork
  is not a reason to call the feature out of scope.
- Phone do-not-call handling is included.

**Must deliver**
- Two-way SMS through RingCentral APIs: send from the portal, receive into
  the contact timeline.
- Click-to-call from the portal, plus call logging (outcome, notes,
  duration) on the timeline.
- DNC / opt-out handling across all channels. STOP replies, DNC lists and
  Zoho DNC flags block SMS, calls and email automatically.
- A consent record per contact (TCPA).

**Client-owned:** RingCentral 10DLC brand + campaign registration (3–5
weeks), the TCPA consent process, and number provisioning. We send the
checklist first.

**Phase:** P4. The reason is the 3–5 week registration lead time. The
engineering can start in parallel and go live once registration clears.

---

## 4. Campaign feedback loop and historical campaign learning (core requirement)

**What Krishna asked**
- A complete feedback loop. Campaign results, channels, contacts and
  categories all feed back to improve the next campaign, cycle after cycle.
- From the day reports exist, metrics must drive the campaigns.
- He is not tied to any tool. A vector DB is fine if it's needed, and so is
  a cheaper alternative. What he wants is the vision built in now, so that
  in one to two years, at higher volume, nothing has to be re-engineered.
  New parts should simply plug in.
- He wants a proposal: low-cost vs high-cost options, tools, costs, and
  whether we can build it or need to hire someone.

**Must deliver**
- A store of campaign outcomes by campaign, channel, segment, contact
  category, prompt version and message angle. The outcomes tracked are
  sent, open, click, reply, positive reply, meeting, bounce and
  unsubscribe.
- An automatic loop that feeds the best-performing segments, prompts and
  angles into the next campaign's targeting, Clay prompts and routing.
  Every change goes through human approval.
- Semantic memory of past campaigns, messages and replies (a vector store)
  so new campaigns can retrieve similar winning past ones. Built on the
  same outcome store, so it can be switched on without rework.
- A written proposal with the options and their monthly costs:
  - low cost: SQL / pgvector on our existing database
  - high cost: a managed vector DB plus analytics
  - staffing: whether a specialist hire is needed

**Phase:** the metrics loop in P2, semantic memory in P3/P4.

---

## 5. Standard prompt templates

**What Krishna asked:** standard, fixed templates for the AI prompts used
inside the system (not email templates).

**Must deliver:** a versioned library of standard prompt templates, with an
approval step before a new version goes live. Each version is linked to
campaign results (feeds §4). A separate prompt-management service is not
needed.

**Phase:** P1.

---

## 6. Scheduled contact re-validation and re-enrichment (core requirement)

**What Krishna asked**
- Re-enrich and re-validate contacts **at least quarterly, automatically**.
  He knows it costs money.
- A **human approval** decides whether to overwrite the record.
- A **manual trigger** so someone can run it sooner than quarterly when
  needed.
- Main reason: people change roles or companies. Stale contacts make the
  whole campaign pointless.
- He wants it automated so the system maintains itself. The developer
  agreed this is "the core essence" of the requirement.

**Must deliver**
- A scheduled job (quarterly by default, configurable) plus a manual
  "recheck now" button for a single contact, a list or a campaign.
- Re-checks against Apollo / Clay / email verification for title, company,
  email validity and LinkedIn URL.
- Detected changes go to an approval queue in Zoho / the portal. Nothing is
  overwritten without approval.
- A job change pauses the old sequence. It creates a new linked contact at
  the new company, and finds a replacement contact at the old account.
- Each run's cost is shown on the cost dashboard (§10).

**Phase:** P2 (P3 at the latest; Krishna accepted either).

---

## 7. Hot-context personalization

**What Krishna asked**
- Personalize from what the person or company is doing right now: recent
  news, expansions, conference appearances, blog posts, social posts. This
  gets traction much faster than generic campaigns.
- Not only LinkedIn. People post on Reddit and other places, so reach them
  in that context.
- Use Clay for the public sources, and stretch to LinkedIn where it can be
  done safely.

**Must deliver**
- Clay research columns covering company news, funding and expansion,
  conferences, podcasts, blogs, and public social posts (Reddit and others).
- Hooks fed into the personalization prompt, with the source cited so the
  approver can check it.
- LinkedIn activity added where an account-safe method from §2 allows.

**Phase:** P2.

---

## 8. Email tracking, analytics and in-email heat map

**What Krishna asked**
- Sequence tracking, open and click tracking, and Google Analytics. He
  called these basic and long-proven.
- A **visual heat map of the email body itself**, not the landing page.
  Opens alone aren't enough. He wants to know which parts of the email
  people actually engaged with.
- Getting this to P3 or P4 is fine, but it must be delivered.
- The developer suggested Microsoft Clarity. That covers landing pages
  only, so it doesn't replace the in-email heat map.

**Must deliver**
- Sequence, open, click and reply metrics per campaign, contact and link.
- UTM tagging plus Google Analytics for traffic that lands on the site.
- Microsoft Clarity heat maps and session recordings on landing pages.
- **In-email heat map:**
  - every link, button and image area in the email gets its own tracking ID
  - clicks are drawn as a heat overlay on the rendered email
  - results can be broken down by campaign, segment and variant

  Email programs don't run scripts, so scroll and hover inside an inbox
  can't be measured. The overlay is built from click and image-load data.
  Say this in the follow-up email.

**Phase:** basic tracking in P1/P2. The in-email heat map is in P3/P4
(placeholder agreed in the meeting; confirm the approach with Krishna).

---

## 9. Out-of-office, referral and "left the company" replies

**What Krishna asked**
- Example: we email John. John has left, and the auto-reply says "contact
  Derek from now on". The system should:
  - capture Derek
  - enrich Derek
  - link John and Derek
  - stop contacting John
- These replies are rare today, but roles change fast. If this isn't built
  now, it will hurt within a year.

**Must deliver**
- Classify replies into: out-of-office (with a return date), left the
  company, referral to someone else, wrong person, or a real reply.
- Extract the new contact's name, email and title. Enrich them, and send
  them to approval as a new contact linked to the original.
- The original contact is paused or retired automatically. Out-of-office
  contacts resume after their return date.

**Phase:** P3.

---

## 10. Cost dashboard with automatic thresholds and toggles

**What Krishna asked**
- One place showing what each API and account is costing.
- Automatic controls, thresholds and triggers. He has heard of many
  companies overspending on APIs and wants to avoid that.
- Set a threshold wherever a vendor API allows it. Pull cost data wherever
  an API provides it.
- If a vendor exposes nothing, the dashboard still lists it with a "check
  manually here" link. That way he knows both what is visible and what
  isn't.
- Use admin or billing accounts if they're needed. He will provide them.

**Must deliver**
- A dashboard covering every vendor: 6sense, Apollo, Clay, Smartlead, Zoho,
  RingCentral, LinkedIn tooling, the LLM provider, and hosting.
- For each vendor, the best tier available:
  - live usage and an automatic limit
  - usage and an alert
  - a manual-check link
- A middleware budget guard that pauses our own calls to any vendor when a
  configured daily or monthly budget is reached. This works even when the
  vendor has no billing API.
- Alerts by email/Slack at configurable percentages of budget.

**Client-owned:** admin / billing-level access for each vendor that
supports it.

**Phase:** P2 (dashboard and budget guard), P3 (vendor-side thresholds).

---

## 11. Logging and troubleshooting

**Must deliver:** a central log and error view in the portal, failed-job
retry, and a runbook. This extends the existing console and
`docs/runbook.md`.

**Phase:** P1/P2.

---

## 12. Calendar integration and meeting booking

**What Krishna asked**
- Sync with Calendly or Zoho Calendar, not just a link.
- Organization-level scheduling. The prospect picks an agent and a time
  slot and books themselves.
- Whoever is booking a meeting can see their own calendar and the
  organization's calendar.
- (The recording ends partway through this point. Confirm the rest with
  Krishna.)

**Must deliver**
- Org-level scheduling through Calendly for Teams or Zoho Bookings, with
  round-robin or agent selection.
- The booking link is inserted into outreach automatically.
- Booked, rescheduled and cancelled meetings write back to the contact
  timeline and Zoho, and stop the active sequence.
- An agent calendar plus an org-wide availability view in the portal.

**Client-owned:** choose Calendly for Teams or Zoho Bookings, and provide
the admin account.

**Phase:** P2.

---

## 13. Geography check and company-status check

**What Krishna asked**
- Check geography and whether the company is still operating.
- Services like Whitepages and similar providers exist and may be easy to
  plug in.
- This can wait until P3/P4 or a later scope, but it must be planned.

**Must deliver:** a pluggable data-provider check (company registry /
business-status data, Whitepages-type services) that runs at enrichment and
re-validation. Inactive or out-of-geography companies are flagged and
blocked.

**Phase:** P3/P4.

---

## 14. Architecture and scaling (Kafka / EventBridge, vector DB)

**What Krishna asked:** no re-engineering later. Components must plug in as
volume grows.

**Must deliver**
- An event interface that the in-process dispatch uses today. A message bus
  (Kafka or EventBridge) can sit behind it later without code changes to
  the pipelines.
- A vector store that can be added to the same outcome data (§4).
- A channel-adapter pattern, so LinkedIn, SMS, phone and future social
  channels each plug into the same timeline and engagement pipeline.

| Future capability | Plugs into |
|---|---|
| New channels (LinkedIn, SMS, phone, social DMs) | New client in `middleware/booklender/clients/` + signed webhook route in `app.py` → `pipeline/engagement.py` → contact timeline |
| Re-enrichment | `pipeline/apollo_discovery.py` / `pipeline/clay_sync.py`, run by a scheduler; changes held for approval by `state_machine.py` |
| Referral / out-of-office extraction | Reply branch in `pipeline/engagement.py` → contact upsert + link |
| Feedback loop | Outcome events already pass through `pipeline/engagement.py` / `audit.py` → reporting store → config / prompt versions |
| Event bus | Replaces in-process dispatch behind the same handlers |

---

## 15. Phase plan (to be estimated and priced)

| Phase | Contents |
|---|---|
| **P1** | Approval-gated email pipeline (current build), standard prompt templates, basic open/click tracking, logging |
| **P2** | Unified contact timeline + email replies from the portal, collision protection, campaign metrics feedback loop, quarterly + manual re-enrichment with approval, Clay hot-context research, cost dashboard + budget guard, calendar integration, UTM/GA + Clarity |
| **P3** | LinkedIn Sales Navigator two-way sync + 10-month backfill, out-of-office/referral handling, vendor-side cost thresholds, company-status/geography check, in-email heat map |
| **P4** | RingCentral SMS + phone + DNC (after 10DLC/TCPA clears), semantic campaign memory (vector store), other social DM channels |

Every row in the follow-up email needs an effort estimate, a timeline and
the reason it sits in that phase.

---

## 16. Action items

**Developer**
- [ ] Send a detailed email covering every item above: solution, phase, effort, timeline and the reason for each placement.
- [ ] LinkedIn Sales Navigator: within one day, pick an account-safe two-way sync method. Include cost, risk, and the plan for backfilling past conversations.
- [ ] Feedback-loop proposal: low-cost vs high-cost options, tools, monthly cost, staffing (build in-house or hire).
- [ ] Implementation notes for vector memory, so it can be added later.
- [ ] RingCentral SMS/voice design, plus a checklist of what Krishna must register and provide.
- [ ] Cost-dashboard vendor matrix: which vendors give usage data, which allow limits, which need admin access.
- [ ] In-email heat map approach. Confirm it with Krishna, and include Clarity for landing pages.
- [ ] Evaluate data providers for the company-status and geography check.
- [ ] Revised budget discussion with Nathan / Praveen.

**Krishna (client)**
- [ ] RingCentral 10DLC brand + campaign registration, TCPA consent, and phone numbers.
- [ ] Admin / billing access for vendors that support cost limits.
- [ ] Choose Calendly for Teams or Zoho Bookings, and provide admin access.
- [ ] Sales Navigator seat details for each agent, for the LinkedIn sync.
- [ ] Rank the phases by priority and confirm budget once estimates arrive.

## 17. Open questions to confirm with Krishna

- Which social platforms besides LinkedIn need DM sync?
- Calendar requirement: the recording ends partway through. Confirm the remaining asks.
- Phone: is click-to-call plus logging enough, or are call recording and transcription required?
- Re-enrichment: is quarterly the default for every segment?
- Does a click-based heat map overlaid on the email body meet the heat-map requirement?
