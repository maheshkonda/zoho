# Zoho CRM Blueprint — BookLender Approval Gate

Module: **Contacts** · Field: **Approval_Status**

The Blueprint makes the approval flow the *only* way to move a contact
through outreach states in the UI, and restricts who may approve.
(Manual configuration in Zoho: Setup → Process Management → Blueprint.
Blueprints cannot be fully created via public API — this file is the exact
spec to click through, ~30 minutes.)

## States (Blueprint "States" = Approval_Status picklist values)

```
NEW → INTENT_DETECTED → CONTACT_IDENTIFIED → RESEARCH_COMPLETE
    → PERSONALIZATION_READY → PENDING_HUMAN_APPROVAL
PENDING_HUMAN_APPROVAL → APPROVED | REJECTED | NEEDS_REVIEW | DO_NOT_CONTACT
APPROVED → QUEUED_FOR_OUTREACH → SENT_TO_SMARTLEAD → ACTIVE_SEQUENCE
ACTIVE_SEQUENCE → REPLIED | BOUNCED | UNSUBSCRIBED | COMPLETED
NEEDS_REVIEW → PENDING_HUMAN_APPROVAL | REJECTED
DO_NOT_CONTACT: terminal (no outbound transition configured)
```

Automated states (everything except the four human transitions below) are
written by the middleware through the API; the Blueprint marks them as
"executed by: system/integration user" so humans cannot drag records
through them.

## Human transitions (buttons on the record)

### 1. `APPROVE`  (PENDING_HUMAN_APPROVAL → APPROVED)
- **Who**: profile "BookLender Approver" only (create this profile;
  assign to authorized operators; the API/integration user must NOT have it).
- **Before (criteria to enter transition)** — all mandatory:
  - `Email` is not empty
  - `Email_Opt_Out` is false
  - `AI_Personalization` is not empty
  - `AI_Research_Summary` is not empty
  - `Smartlead_Lead_ID` is empty
- **During**: show read-only review fields (see layout below); no inputs
  required from the operator.
- **After**:
  - Call Deluge function `booklender_on_approve(contactId)`
    (zoho/deluge/on_approve.dg): stamps `Approved_By` (from the logged-in
    user, server-side) + `Approval_Timestamp`, then fires the signed
    webhook to the middleware with the contact id only.
- Note: these Blueprint validations are UX-level. The middleware re-runs
  every check server-side (dispatch.py) — the Blueprint failing to enforce
  them can never cause an unauthorized send.

### 2. `REJECT`  (PENDING_HUMAN_APPROVAL → REJECTED)
- **During**: mandatory field `Rejection_Reason`.
- **After**: field update `Outreach_Status = NONE`. No webhook fires.

### 3. `DO NOT CONTACT`  (any state → DO_NOT_CONTACT)
- **Who**: BookLender Approver + Administrator.
- **After**: field updates `Email_Opt_Out = true`, `Outreach_Status = NONE`.
- Terminal: configure **no** outgoing transition. Re-opening requires an
  Administrator editing the record outside the Blueprint (deliberate
  friction), and even then the middleware still refuses while
  `Email_Opt_Out` is true.

### 4. `NEEDS REVIEW`  (PENDING_HUMAN_APPROVAL ↔ NEEDS_REVIEW)
- Round-trips a prospect for data fixes; `NEEDS_REVIEW → PENDING_HUMAN_APPROVAL`
  is allowed for the Approver profile once fields are corrected.

## Review layout (the "single pane" the operator sees)

Create a Contacts layout section **"BookLender Review"** ordered:

| Block | Fields |
|---|---|
| WHO | Full Name, Title, Email, LinkedIn_URL, Account_Name |
| WHY THIS ACCOUNT | Account.SixSense_Intent_Score, SixSense_Intent_Tier, SixSense_Intent_Topics |
| COMPANY | AI_Work_Model, AI_Confidence, Account.Employees, Account.Industry, AI_Research_Summary |
| WHY BOOKLENDER | AI_Personalization, AI_CTA |
| APPROVAL | Approval_Status, Approved_By, Approval_Timestamp, Rejection_Reason |
| OUTREACH | Smartlead_Sync_Status, Smartlead_Campaign_ID, Outreach_Status, Reply_Status, Bounce_Status |

The operator never needs to open 6sense, Apollo, Clay, Make, or Smartlead.

## Permissions hardening (required)

1. Create dedicated **integration user** for the middleware with a profile
   that can read/write Contacts+Accounts fields but is NOT in the
   "BookLender Approver" profile → the middleware physically cannot perform
   the APPROVE Blueprint transition. (Belt) 
2. Field-level security: make `Approval_Timestamp`, `Approved_By`,
   `Smartlead_Lead_ID` read-only for all non-admin human profiles — only
   the Blueprint/Deluge and the integration user write them. (Suspenders)
3. The middleware refuses dispatch unless status+timestamp+approver are all
   present and consistent, re-read live from Zoho. (Actual boundary)

## Dashboards (Setup → Analytics)

- **Pipeline funnel**: count of Contacts by Approval_Status.
- **Awaiting approval**: list view `Approval_Status = PENDING_HUMAN_APPROVAL`
  (this powers the "12 new high-intent accounts" experience — pin it to the
  operator home page).
- **Outreach outcomes**: Replied / Bounced / Unsubscribed by week.
- **Integration health**: Contacts with `Smartlead_Sync_Status = ERROR` or
  non-empty `Integration_Error`; Accounts by SixSense_Intent_Tier.
