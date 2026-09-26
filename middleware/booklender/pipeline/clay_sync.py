"""Clay enrichment results -> Zoho contact -> PENDING_HUMAN_APPROVAL.

This is the critical STOP point. After this pipeline runs, the machine does
NOTHING further until a human acts inside Zoho CRM. There is deliberately no
code path from here to Smartlead.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import fields as f
from ..retry import PermanentError, with_retry
from ..state_machine import Status
from .context import Context

VALID_WORK_MODELS = {"REMOTE", "HYBRID", "ON_SITE", "UNKNOWN"}


def handle_clay_result(ctx: Context, result: dict[str, Any]) -> dict[str, Any]:
    """Apply a completed Clay enrichment to the Zoho contact.

    Expected payload from the Clay table's final HTTP-API column:
        zoho_contact_id, clay_record_id, work_model, confidence,
        research_summary, personalized_pitch, cta
    """
    contact_id = result.get("zoho_contact_id")
    if not contact_id:
        raise PermanentError("Clay result missing zoho_contact_id")

    clay_record_id = result.get("clay_record_id") or contact_id
    idem_key = f"clay-result:{clay_record_id}"
    if not ctx.idem.claim(idem_key):
        ctx.audit.record(
            source="clay", destination="zoho", entity_type="contact",
            entity_id=contact_id, action="apply_enrichment", status="SKIPPED",
            error="duplicate Clay completion (idempotent)",
        )
        return {"duplicate": True, "contact_id": contact_id}

    contact = ctx.zoho.get_contact(contact_id)
    if contact is None:
        ctx.idem.release(idem_key)
        raise PermanentError(f"Zoho contact {contact_id} not found (deleted?)")

    # Compliance / terminal states always win over enrichment.
    status = contact.get(f.C_APPROVAL_STATUS)
    if status in (Status.DO_NOT_CONTACT.value, Status.REJECTED.value, Status.UNSUBSCRIBED.value):
        ctx.audit.record(
            source="clay", destination="zoho", entity_type="contact",
            entity_id=contact_id, action="apply_enrichment", status="SKIPPED",
            error=f"contact in terminal state {status}",
        )
        return {"skipped": True, "reason": status, "contact_id": contact_id}

    work_model = (result.get("work_model") or "UNKNOWN").upper().replace("-", "_").replace(" ", "_")
    if work_model == "ONSITE":
        work_model = "ON_SITE"
    if work_model not in VALID_WORK_MODELS:
        work_model = "UNKNOWN"
    confidence = result.get("confidence")
    pitch = (result.get("personalized_pitch") or "").strip()
    research = (result.get("research_summary") or "").strip()

    # If personalization failed / is empty, route to NEEDS_REVIEW instead of
    # PENDING_HUMAN_APPROVAL — the operator sees why, and the approval
    # transition would refuse it anyway (missing-personalization validation).
    complete = bool(pitch and research)
    new_status = Status.PENDING_HUMAN_APPROVAL if complete else Status.NEEDS_REVIEW

    fields: dict[str, Any] = {
        f.C_AI_WORK_MODEL: work_model,
        f.C_WORK_MODEL: work_model,
        f.C_AI_CONFIDENCE: confidence,
        f.C_AI_RESEARCH: research or None,
        f.C_AI_PITCH: pitch or None,
        f.C_AI_CTA: result.get("cta"),
        f.C_CLAY_ID: clay_record_id,
        f.C_CLAY_STATUS: "COMPLETE" if complete else "INCOMPLETE",
        f.C_LAST_ENRICHED: datetime.now(timezone.utc).isoformat(timespec="seconds"),
        f.C_APPROVAL_STATUS: new_status.value,
    }
    fields = {k: v for k, v in fields.items() if v is not None}

    r = ctx.settings.retry
    try:
        with_retry(
            lambda: ctx.zoho.update_contact(contact_id, fields),
            max_attempts=r.max_attempts, base_delay=r.base_delay_seconds,
            max_delay=r.max_delay_seconds,
            on_retry=lambda n, e: ctx.audit.record(
                source="clay", destination="zoho", entity_type="contact",
                entity_id=contact_id, action="apply_enrichment", status="RETRY",
                error=str(e), retry_count=n,
            ),
        )
    except Exception as e:
        ctx.idem.release(idem_key)
        ctx.audit.record(
            source="clay", destination="zoho", entity_type="contact",
            entity_id=contact_id, action="apply_enrichment", status="FAILURE",
            error=str(e),
        )
        raise
    ctx.audit.record(
        source="clay", destination="zoho", entity_type="contact",
        entity_id=contact_id, action="apply_enrichment", status="SUCCESS",
        response_ref=new_status.value,
    )
    # HARD STOP. A human must now act in Zoho CRM. No Smartlead call exists here.
    return {"contact_id": contact_id, "status": new_status.value, "complete": complete}
