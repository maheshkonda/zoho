"""Approval / prospect state machine.

Zoho CRM is the system of record for these states; this module is the single
authoritative definition of which transitions are legal. Every workflow that
changes a prospect's status MUST go through ``assert_transition``.

The only path into outreach is:

    PENDING_HUMAN_APPROVAL -> APPROVED -> QUEUED_FOR_OUTREACH -> SENT_TO_SMARTLEAD

and the PENDING_HUMAN_APPROVAL -> APPROVED edge may only ever be performed by
a human inside Zoho CRM (the middleware refuses to perform it, see
``HUMAN_ONLY_TRANSITIONS``).
"""
from __future__ import annotations

from enum import Enum


class Status(str, Enum):
    NEW = "NEW"
    INTENT_DETECTED = "INTENT_DETECTED"
    CONTACT_IDENTIFIED = "CONTACT_IDENTIFIED"
    RESEARCH_COMPLETE = "RESEARCH_COMPLETE"
    PERSONALIZATION_READY = "PERSONALIZATION_READY"
    PENDING_HUMAN_APPROVAL = "PENDING_HUMAN_APPROVAL"
    APPROVED = "APPROVED"
    QUEUED_FOR_OUTREACH = "QUEUED_FOR_OUTREACH"
    SENT_TO_SMARTLEAD = "SENT_TO_SMARTLEAD"
    ACTIVE_SEQUENCE = "ACTIVE_SEQUENCE"
    REPLIED = "REPLIED"
    BOUNCED = "BOUNCED"
    UNSUBSCRIBED = "UNSUBSCRIBED"
    COMPLETED = "COMPLETED"
    # Exception states
    REJECTED = "REJECTED"
    DO_NOT_CONTACT = "DO_NOT_CONTACT"
    ERROR = "ERROR"
    NEEDS_REVIEW = "NEEDS_REVIEW"


# Every state may additionally move to ERROR / NEEDS_REVIEW (operational
# escapes) and, for compliance, to DO_NOT_CONTACT at any time.
_UNIVERSAL_TARGETS = {Status.ERROR, Status.NEEDS_REVIEW, Status.DO_NOT_CONTACT}

TRANSITIONS: dict[Status, set[Status]] = {
    Status.NEW: {Status.INTENT_DETECTED},
    Status.INTENT_DETECTED: {Status.CONTACT_IDENTIFIED},
    Status.CONTACT_IDENTIFIED: {Status.RESEARCH_COMPLETE},
    Status.RESEARCH_COMPLETE: {Status.PERSONALIZATION_READY},
    Status.PERSONALIZATION_READY: {Status.PENDING_HUMAN_APPROVAL},
    Status.PENDING_HUMAN_APPROVAL: {Status.APPROVED, Status.REJECTED},
    Status.APPROVED: {Status.QUEUED_FOR_OUTREACH},
    Status.QUEUED_FOR_OUTREACH: {Status.SENT_TO_SMARTLEAD},
    Status.SENT_TO_SMARTLEAD: {Status.ACTIVE_SEQUENCE},
    Status.ACTIVE_SEQUENCE: {
        Status.REPLIED,
        Status.BOUNCED,
        Status.UNSUBSCRIBED,
        Status.COMPLETED,
    },
    Status.REPLIED: {Status.COMPLETED},
    Status.BOUNCED: {Status.COMPLETED},
    Status.UNSUBSCRIBED: set(),          # terminal for outreach purposes
    Status.COMPLETED: set(),
    Status.REJECTED: {Status.NEEDS_REVIEW},  # a human may re-open for review
    Status.DO_NOT_CONTACT: set(),        # terminal; admin override is manual in CRM
    Status.ERROR: {Status.NEEDS_REVIEW, Status.PENDING_HUMAN_APPROVAL},
    Status.NEEDS_REVIEW: {Status.PENDING_HUMAN_APPROVAL, Status.REJECTED},
}

# Transitions the middleware must NEVER perform on its own. Only a human
# acting inside the Zoho CRM Blueprint may execute these.
HUMAN_ONLY_TRANSITIONS: set[tuple[Status, Status]] = {
    (Status.PENDING_HUMAN_APPROVAL, Status.APPROVED),
    (Status.PENDING_HUMAN_APPROVAL, Status.REJECTED),
    (Status.NEEDS_REVIEW, Status.PENDING_HUMAN_APPROVAL),
    (Status.NEEDS_REVIEW, Status.REJECTED),
}

# The only states from which a Smartlead submission is ever allowed to start.
DISPATCHABLE_STATES = {Status.APPROVED, Status.QUEUED_FOR_OUTREACH}


class IllegalTransition(Exception):
    pass


class HumanOnlyTransition(IllegalTransition):
    pass


def can_transition(src: Status, dst: Status) -> bool:
    return dst in TRANSITIONS.get(src, set()) or dst in _UNIVERSAL_TARGETS


def assert_transition(src: Status, dst: Status, *, actor: str = "system") -> None:
    """Validate a transition. ``actor='system'`` for automated workflows,
    ``actor='human'`` only when relaying a change already made by a human
    inside Zoho CRM."""
    if not can_transition(src, dst):
        raise IllegalTransition(f"{src.value} -> {dst.value} is not a legal transition")
    if actor != "human" and (src, dst) in HUMAN_ONLY_TRANSITIONS:
        raise HumanOnlyTransition(
            f"{src.value} -> {dst.value} may only be performed by a human in Zoho CRM"
        )
