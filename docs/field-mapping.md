# Field Mapping

Canonical constants: `middleware/booklender/fields.py`.
Provisioning source: `zoho/fields.json` (run `scripts/provision_zoho_fields.py`).

## 6sense signal → Zoho Account

| 6sense payload | Zoho Accounts field | Notes |
|---|---|---|
| company_name | Account_Name | fallback: domain |
| website / domain | Website, Company_Domain | domain normalized (lowercase, no www/scheme); **upsert key** |
| industry | Industry | |
| employee_count | Employees | |
| country | Billing_Country | |
| sixsense_account_id | SixSense_Account_ID | idempotency component |
| intent_score | SixSense_Intent_Score | qualification threshold: config `intent.min_score` |
| intent_tier | SixSense_Intent_Tier | config `intent.accepted_tiers` |
| intent_topics[] | SixSense_Intent_Topics | comma-joined; config `intent.relevant_topics` |
| signal_timestamp | SixSense_Last_Activity | idempotency component |
| (constant) | SixSense_Source = "6sense" | |
| (state) | Prospect_Status = INTENT_DETECTED | |

## Apollo person → Zoho Contact

| Apollo | Zoho Contacts | Precedence |
|---|---|---|
| first_name / last_name | First_Name / Last_Name | never overwrites populated CRM value |
| title | Title | never overwrites populated CRM value |
| email | Email | **upsert key**; verified emails only; never overwrites |
| linkedin_url | LinkedIn_URL | never overwrites |
| department | Department | default "HR/People" |
| seniority | Seniority | |
| id | Apollo_Person_ID | idempotency key `apollo:<id>` |
| (lookup) | Account_Name → Account id | |
| (state) | Approval_Status = CONTACT_IDENTIFIED | not applied if record already progressed |

## Middleware → Clay (enqueue payload)

`zoho_contact_id, zoho_account_id, first_name, last_name, title, email,
linkedin_url, company_domain`

## Clay result → Zoho Contact

| Clay output | Zoho Contacts | Notes |
|---|---|---|
| work_model | AI_Work_Model, Work_Model | normalized to REMOTE/HYBRID/ON_SITE/UNKNOWN |
| confidence | AI_Confidence | 0–1 |
| research_summary | AI_Research_Summary | required for approval |
| personalized_pitch | AI_Personalization | required for approval |
| cta | AI_CTA | |
| clay_record_id | Clay_Record_ID | idempotency key `clay-result:<id>` |
| (state) | Clay_Enrichment_Status = COMPLETE/INCOMPLETE | |
| (state) | Approval_Status = PENDING_HUMAN_APPROVAL (complete) / NEEDS_REVIEW (incomplete) | **hard stop** |
| (ts) | Last_Enriched | |

## Zoho APPROVE → middleware webhook

Payload: `{ "zoho_contact_id": "<id>" }` — nothing else is trusted.
Deluge stamps `Approved_By` (login user) + `Approval_Timestamp` first.

## Zoho Contact → Smartlead lead

| Zoho | Smartlead | Template variable |
|---|---|---|
| Email | email | |
| First_Name / Last_Name | first_name / last_name | `{{first_name}}` |
| Account_Name | company_name | `{{company}}` |
| Title | custom_fields.job_title | `{{job_title}}` |
| AI_Personalization | custom_fields.personalized_pitch | `{{personalized_pitch}}` |
| AI_CTA | custom_fields.cta | `{{cta}}` |
| AI_Work_Model | custom_fields.work_model | campaign routing (config `campaigns:`) |
| id | custom_fields.zoho_contact_id | reverse lookup |
| ← lead id | Smartlead_Lead_ID | + Smartlead_Campaign_ID, Sync status/timestamp |

## Smartlead event → Zoho Contact

| Event | Approval_Status | Other fields |
|---|---|---|
| EMAIL_SENT | ACTIVE_SEQUENCE | Outreach_Status=ACTIVE |
| EMAIL_REPLY | REPLIED | Reply_Status=REPLIED |
| EMAIL_BOUNCE | BOUNCED | Bounce_Status=BOUNCED |
| LEAD_UNSUBSCRIBED | UNSUBSCRIBED | **Email_Opt_Out=true** |
| CAMPAIGN_COMPLETED | COMPLETED | Outreach_Status=COMPLETED |

Match key: lead email → `find_contact_by_email`; idempotent per event id.
