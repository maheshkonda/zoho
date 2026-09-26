"""Smartlead engagement events (reply / bounce / unsubscribe) -> Zoho."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import fields as f
from ..retry import PermanentError
from ..state_machine import Status
from .context import Context

_EVENT_MAP = {
    "EMAIL_REPLY": (Status.REPLIED, {f.C_REPLY_STATUS: "REPLIED", f.C_OUTREACH_STATUS: "REPLIED"}),
    "EMAIL_BOUNCE": (Status.BOUNCED, {f.C_BOUNCE_STATUS: "BOUNCED", f.C_OUTREACH_STATUS: "BOUNCED"}),
    "LEAD_UNSUBSCRIBED": (
        Status.UNSUBSCRIBED,
        {f.C_OPTED_OUT: True, f.C_OUTREACH_STATUS: "UNSUBSCRIBED"},
    ),
    "EMAIL_SENT": (Status.ACTIVE_SEQUENCE, {f.C_OUTREACH_STATUS: "ACTIVE"}),
    "CAMPAIGN_COMPLETED": (Status.COMPLETED, {f.C_OUTREACH_STATUS: "COMPLETED"}),
}


def handle_smartlead_event(ctx: Context, event: dict[str, Any]) -> dict[str, Any]:
    event_type = (event.get("event_type") or "").upper()
    email = (event.get("lead_email") or event.get("email") or "").strip().lower()
    event_id = event.get("event_id") or f"{event_type}:{email}:{event.get('timestamp','')}"
    if event_type not in _EVENT_MAP:
        return {"ignored": True, "event_type": event_type}
    if not email:
        raise PermanentError("Smartlead event missing lead email")

    if not ctx.idem.claim(f"sl-event:{event_id}"):
        return {"duplicate": True}

    contact = ctx.zoho.find_contact_by_email(email)
    if contact is None:
        ctx.audit.record(
            source="smartlead", destination="zoho", entity_type="contact",
            entity_id=email, action=event_type, status="FAILURE",
            error="no matching Zoho contact",
        )
        return {"unmatched": True, "email": email}

    status, extra = _EVENT_MAP[event_type]
    fields: dict[str, Any] = {
        f.C_APPROVAL_STATUS: status.value,
        f.C_LAST_OUTREACH: datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **extra,
    }
    ctx.zoho.update_contact(contact["id"], fields)
    ctx.audit.record(
        source="smartlead", destination="zoho", entity_type="contact",
        entity_id=contact["id"], action=event_type, status="SUCCESS",
    )
    return {"contact_id": contact["id"], "status": status.value}
