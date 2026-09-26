"""Apollo contact discovery -> Zoho Contacts -> Clay enqueue.

Field precedence (never overwrite better data with worse):
    1. Verified CRM data       (highest)
    2. Apollo
    3. Clay enrichment
    4. AI inference            (never overwrites contact identity fields)
"""
from __future__ import annotations

from typing import Any

from .. import fields as f
from ..retry import with_retry
from ..state_machine import Status
from .context import Context

# Contact identity fields that Apollo may only fill when empty in CRM.
_PROTECTED_WHEN_PRESENT = [f.C_FIRST, f.C_LAST, f.C_EMAIL, f.C_TITLE, f.C_LINKEDIN]


def discover_contacts(ctx: Context, *, account_id: str, domain: str) -> list[str]:
    """Find HR/People contacts for a qualified account, upsert them into Zoho,
    and enqueue each new contact into Clay. Returns Zoho contact ids."""
    cfg = ctx.settings.contacts
    r = ctx.settings.retry

    try:
        people = with_retry(
            lambda: ctx.apollo.search_people(
                domain=domain,
                titles=cfg.target_titles,
                seniorities=cfg.target_seniorities,
                limit=cfg.max_contacts_per_account,
            ),
            max_attempts=r.max_attempts, base_delay=r.base_delay_seconds,
            max_delay=r.max_delay_seconds,
            on_retry=lambda n, e: ctx.audit.record(
                source="apollo", destination="middleware", entity_type="account",
                entity_id=account_id, action="search_people", status="RETRY",
                error=str(e), retry_count=n,
            ),
        )
    except Exception as e:
        ctx.audit.record(
            source="apollo", destination="middleware", entity_type="account",
            entity_id=account_id, action="search_people", status="FAILURE", error=str(e),
        )
        raise

    contact_ids: list[str] = []
    seen_emails: set[str] = set()
    for person in people[: cfg.max_contacts_per_account]:
        email = (person.get("email") or "").strip().lower()
        apollo_id = person.get("id") or email
        if not email or email in seen_emails:
            continue
        seen_emails.add(email)

        idem_key = f"apollo:{apollo_id}"
        if not ctx.idem.claim(idem_key):
            existing_id = ctx.idem.result_of(idem_key)
            if existing_id:
                contact_ids.append(existing_id)
            continue

        existing = ctx.zoho.find_contact_by_email(email)
        payload: dict[str, Any] = {
            f.C_FIRST: person.get("first_name"),
            f.C_LAST: person.get("last_name"),
            f.C_TITLE: person.get("title"),
            f.C_EMAIL: email,
            f.C_LINKEDIN: person.get("linkedin_url"),
            f.C_DEPARTMENT: person.get("department") or "HR/People",
            f.C_SENIORITY: person.get("seniority"),
            f.C_ACCOUNT: {"id": account_id},
            f.C_APOLLO_ID: apollo_id,
            f.C_APPROVAL_STATUS: Status.CONTACT_IDENTIFIED.value,
            f.C_OUTREACH_STATUS: "NONE",
        }
        if existing:
            # precedence: never blindly overwrite verified CRM identity data
            for key in _PROTECTED_WHEN_PRESENT:
                if existing.get(key):
                    payload.pop(key, None)
            # never regress an approval state that is already past discovery
            if existing.get(f.C_APPROVAL_STATUS) not in (None, "", Status.NEW.value):
                payload.pop(f.C_APPROVAL_STATUS, None)
        payload = {k: v for k, v in payload.items() if v is not None}

        try:
            if existing:
                contact_id = existing["id"]
                ctx.zoho.update_contact(contact_id, payload)
            else:
                contact_id = ctx.zoho.upsert_contact(payload)
        except Exception as e:
            ctx.idem.release(idem_key)
            ctx.audit.record(
                source="apollo", destination="zoho", entity_type="contact",
                entity_id=email, action="upsert_contact", status="FAILURE", error=str(e),
            )
            raise
        ctx.idem.set_result(idem_key, contact_id)
        contact_ids.append(contact_id)
        ctx.audit.record(
            source="apollo", destination="zoho", entity_type="contact",
            entity_id=contact_id, action="upsert_contact", status="SUCCESS",
            request_ref=idem_key,
        )

        # hand off to Clay for research + personalization
        clay_key = f"clay-enqueue:{contact_id}"
        if ctx.idem.claim(clay_key):
            try:
                ctx.clay.enqueue_contact(
                    {
                        "zoho_contact_id": contact_id,
                        "zoho_account_id": account_id,
                        "first_name": person.get("first_name"),
                        "last_name": person.get("last_name"),
                        "title": person.get("title"),
                        "email": email,
                        "linkedin_url": person.get("linkedin_url"),
                        "company_domain": domain,
                    }
                )
                ctx.zoho.update_contact(
                    contact_id, {f.C_CLAY_STATUS: "QUEUED"}
                )
                ctx.audit.record(
                    source="zoho", destination="clay", entity_type="contact",
                    entity_id=contact_id, action="enqueue_clay", status="SUCCESS",
                )
            except Exception as e:
                ctx.idem.release(clay_key)
                ctx.audit.record(
                    source="zoho", destination="clay", entity_type="contact",
                    entity_id=contact_id, action="enqueue_clay", status="FAILURE",
                    error=str(e),
                )
                raise
    return contact_ids
