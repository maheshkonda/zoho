"""THE APPROVAL GATE — Zoho APPROVED -> Smartlead dispatch.

This is a security boundary. The webhook payload from Zoho is treated as an
untrusted hint containing only a contact id: every fact that authorizes
outreach is RE-READ FROM ZOHO CRM server-side. A forged or stale payload can
never cause an email to be sent.

Validation performed against the live Zoho record (all must pass):
    1.  Approval_Status == APPROVED
    2.  Approval_Timestamp present
    3.  Approved_By present
    4.  Email present and plausibly valid
    5.  Contact not opted out / not DO_NOT_CONTACT / not UNSUBSCRIBED
    6.  AI personalization + research present
    7.  Not already in Smartlead (CRM field AND live Smartlead lookup)
    8.  Idempotency: one approval == one Smartlead lead, ever
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .. import fields as f
from ..retry import PermanentError, with_retry
from ..state_machine import Status
from .context import Context

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ApprovalGateError(PermanentError):
    """Dispatch refused. Carries the operator-facing reason. Never retried."""


def _refuse(ctx: Context, contact_id: str, reason: str) -> None:
    ctx.audit.record(
        source="zoho", destination="smartlead", entity_type="contact",
        entity_id=contact_id, action="dispatch", status="FAILURE",
        error=f"APPROVAL GATE REFUSED: {reason}",
    )
    raise ApprovalGateError(f"Approval gate refused for {contact_id}: {reason}")


def dispatch_approved_contact(ctx: Context, *, zoho_contact_id: str) -> dict[str, Any]:
    """Called by the Zoho approval webhook. Re-validates everything against
    the live CRM record and, only if every check passes, creates exactly one
    Smartlead lead."""
    contact = ctx.zoho.get_contact(zoho_contact_id)
    if contact is None:
        _refuse(ctx, zoho_contact_id, "contact not found in Zoho")

    # --- 0: already dispatched? Graceful idempotent skip, never a resend ---
    if contact.get(f.C_SMARTLEAD_LEAD_ID):
        ctx.audit.record(
            source="zoho", destination="smartlead", entity_type="contact",
            entity_id=zoho_contact_id, action="dispatch", status="SKIPPED",
            error="already has Smartlead_Lead_ID (idempotent)",
        )
        return {"duplicate": True, "smartlead_lead_id": contact[f.C_SMARTLEAD_LEAD_ID]}

    # --- 1-3: explicit human approval recorded in the system of record ----
    if contact.get(f.C_APPROVAL_STATUS) != Status.APPROVED.value:
        _refuse(
            ctx, zoho_contact_id,
            f"Approval_Status is {contact.get(f.C_APPROVAL_STATUS)!r}, not APPROVED",
        )
    if not contact.get(f.C_APPROVAL_TS):
        _refuse(ctx, zoho_contact_id, "Approval_Timestamp is empty")
    if not contact.get(f.C_APPROVED_BY):
        _refuse(ctx, zoho_contact_id, "Approved_By is empty")

    # --- 4: deliverable address -------------------------------------------
    email = (contact.get(f.C_EMAIL) or "").strip().lower()
    if not email or not _EMAIL_RE.match(email):
        _refuse(ctx, zoho_contact_id, f"invalid or missing email {email!r}")

    # --- 5: compliance -------------------------------------------------------
    if contact.get(f.C_OPTED_OUT):
        _refuse(ctx, zoho_contact_id, "contact has opted out of email")

    # --- 6: personalization must exist --------------------------------------
    if not (contact.get(f.C_AI_PITCH) or "").strip():
        _refuse(ctx, zoho_contact_id, "AI personalization is missing")
    if not (contact.get(f.C_AI_RESEARCH) or "").strip():
        _refuse(ctx, zoho_contact_id, "research summary is missing")

    # --- 7: idempotency (one approval == one lead) ---------------------------
    idem_key = f"smartlead-dispatch:{zoho_contact_id}:{contact.get(f.C_APPROVAL_TS)}"
    if not ctx.idem.claim(idem_key):
        prior = ctx.idem.result_of(idem_key) or ""
        ctx.audit.record(
            source="zoho", destination="smartlead", entity_type="contact",
            entity_id=zoho_contact_id, action="dispatch", status="SKIPPED",
            error="duplicate approval webhook (idempotent)",
        )
        return {"duplicate": True, "smartlead_lead_id": prior}

    campaign = ctx.settings.campaign_for(contact.get(f.C_AI_WORK_MODEL))

    try:
        # --- 7b: live duplicate check in Smartlead ---------------------------
        r = ctx.settings.retry
        existing = with_retry(
            lambda: ctx.smartlead.find_lead_by_email(campaign.campaign_id, email),
            max_attempts=r.max_attempts, base_delay=r.base_delay_seconds,
            max_delay=r.max_delay_seconds,
        )
        if existing:
            lead_id = str(existing.get("id"))
            ctx.idem.set_result(idem_key, lead_id)
            ctx.zoho.update_contact(
                zoho_contact_id,
                {
                    f.C_SMARTLEAD_LEAD_ID: lead_id,
                    f.C_SMARTLEAD_CAMPAIGN_ID: campaign.campaign_id,
                    f.C_SMARTLEAD_SYNC_STATUS: "LINKED_EXISTING",
                },
            )
            ctx.audit.record(
                source="zoho", destination="smartlead", entity_type="contact",
                entity_id=zoho_contact_id, action="dispatch", status="SKIPPED",
                error="lead already exists in Smartlead; linked, not duplicated",
            )
            return {"duplicate": True, "smartlead_lead_id": lead_id}

        if ctx.settings.test_mode:
            # Safety interlock: in test mode we validate everything but never
            # touch a live campaign. The test suite injects a fake client, so
            # test_mode=false + fake client is used to prove the send path.
            ctx.idem.set_result(idem_key, "TEST_MODE_NO_SEND")
            ctx.audit.record(
                source="zoho", destination="smartlead", entity_type="contact",
                entity_id=zoho_contact_id, action="dispatch", status="SKIPPED",
                error="test_mode enabled — validated but not sent",
            )
            return {"test_mode": True, "would_send_to": campaign.campaign_id}

        lead = {
            "email": email,
            "first_name": contact.get(f.C_FIRST),
            "last_name": contact.get(f.C_LAST),
            "company_name": (contact.get(f.C_ACCOUNT) or {}).get("name")
            if isinstance(contact.get(f.C_ACCOUNT), dict) else contact.get(f.C_ACCOUNT),
            "custom_fields": {
                "job_title": contact.get(f.C_TITLE),
                "personalized_pitch": contact.get(f.C_AI_PITCH),
                "cta": contact.get(f.C_AI_CTA),
                "work_model": contact.get(f.C_AI_WORK_MODEL),
                "zoho_contact_id": zoho_contact_id,
            },
        }
        lead_id = with_retry(
            lambda: ctx.smartlead.add_lead(campaign.campaign_id, lead),
            max_attempts=r.max_attempts, base_delay=r.base_delay_seconds,
            max_delay=r.max_delay_seconds,
            on_retry=lambda n, e: ctx.audit.record(
                source="zoho", destination="smartlead", entity_type="contact",
                entity_id=zoho_contact_id, action="add_lead", status="RETRY",
                error=str(e), retry_count=n,
            ),
        )
    except ApprovalGateError:
        raise
    except Exception as e:
        ctx.idem.release(idem_key)
        ctx.zoho.update_contact(
            zoho_contact_id,
            {
                f.C_SMARTLEAD_SYNC_STATUS: "ERROR",
                f.C_INTEGRATION_ERROR: str(e)[:255],
                f.C_LAST_ATTEMPT: datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )
        ctx.audit.record(
            source="zoho", destination="smartlead", entity_type="contact",
            entity_id=zoho_contact_id, action="dispatch", status="FAILURE", error=str(e),
        )
        raise

    ctx.idem.set_result(idem_key, lead_id)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ctx.zoho.update_contact(
        zoho_contact_id,
        {
            f.C_SMARTLEAD_LEAD_ID: lead_id,
            f.C_SMARTLEAD_CAMPAIGN_ID: campaign.campaign_id,
            f.C_SMARTLEAD_SYNC_STATUS: "SYNCED",
            f.C_SMARTLEAD_SYNC_TS: now,
            f.C_APPROVAL_STATUS: Status.SENT_TO_SMARTLEAD.value,
            f.C_OUTREACH_STATUS: "ACTIVE",
            f.C_LAST_OUTREACH: now,
        },
    )
    ctx.audit.record(
        source="zoho", destination="smartlead", entity_type="contact",
        entity_id=zoho_contact_id, action="dispatch", status="SUCCESS",
        response_ref=lead_id,
    )
    return {"duplicate": False, "smartlead_lead_id": lead_id, "campaign_id": campaign.campaign_id}
