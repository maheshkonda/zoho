"""Acceptance tests — one per requirement in the master prompt (§26),
plus security tests for the approval gate (§6, §30)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from booklender import fields as f
from booklender.pipeline import apollo_discovery, clay_sync, dispatch, engagement, sixsense
from booklender.state_machine import (
    HumanOnlyTransition,
    IllegalTransition,
    Status,
    assert_transition,
)

from conftest import APOLLO_PERSON, CLAY_RESULT_TEMPLATE, GOOD_SIGNAL, make_settings


def run_to_pending(ctx):
    """Drive the pipeline: 6sense -> account -> apollo -> contact -> clay -> PENDING."""
    ctx.apollo.people[GOOD_SIGNAL["domain"]] = [APOLLO_PERSON]
    res = sixsense.handle_intent_signal(ctx, GOOD_SIGNAL)
    assert res["qualified"] and not res["duplicate"]
    contact_ids = apollo_discovery.discover_contacts(
        ctx, account_id=res["account_id"], domain=res["domain"]
    )
    assert len(contact_ids) == 1
    contact_id = contact_ids[0]
    clay_sync.handle_clay_result(
        ctx, {"zoho_contact_id": contact_id, **CLAY_RESULT_TEMPLATE}
    )
    return contact_id


def human_approves(ctx, contact_id, approver="mahesh@booklender.example"):
    """Simulate the human APPROVE click inside the Zoho Blueprint."""
    ctx.zoho.update_contact(
        contact_id,
        {
            f.C_APPROVAL_STATUS: Status.APPROVED.value,
            f.C_APPROVAL_TS: datetime.now(timezone.utc).isoformat(),
            f.C_APPROVED_BY: approver,
        },
    )


# ---- Test 1: new intent account -------------------------------------------
def test_1_new_intent_account_creates_zoho_account(ctx):
    res = sixsense.handle_intent_signal(ctx, GOOD_SIGNAL)
    acc = ctx.zoho.get_account(res["account_id"])
    assert acc[f.A_DOMAIN] == "acme-test.example.com"
    assert acc[f.A_INTENT_SCORE] == 88
    assert acc[f.A_PROSPECT_STATUS] == Status.INTENT_DETECTED.value


def test_1b_duplicate_signal_is_idempotent(ctx):
    r1 = sixsense.handle_intent_signal(ctx, GOOD_SIGNAL)
    r2 = sixsense.handle_intent_signal(ctx, GOOD_SIGNAL)
    assert r2["duplicate"] and r2["account_id"] == r1["account_id"]
    assert len(ctx.zoho.accounts) == 1


def test_1c_low_intent_signal_is_skipped(ctx):
    res = sixsense.handle_intent_signal(ctx, {**GOOD_SIGNAL, "intent_score": 10})
    assert not res["qualified"]
    assert len(ctx.zoho.accounts) == 0


# ---- Test 2: contact discovery ----------------------------------------------
def test_2_apollo_contact_lands_in_zoho_and_clay(ctx):
    ctx.apollo.people[GOOD_SIGNAL["domain"]] = [APOLLO_PERSON, APOLLO_PERSON]  # dup
    res = sixsense.handle_intent_signal(ctx, GOOD_SIGNAL)
    ids = apollo_discovery.discover_contacts(
        ctx, account_id=res["account_id"], domain=res["domain"]
    )
    assert len(ids) == 1  # deduplicated by email
    c = ctx.zoho.get_contact(ids[0])
    assert c[f.C_EMAIL] == APOLLO_PERSON["email"]
    assert c[f.C_APOLLO_ID] == "apollo-p-123"
    assert len(ctx.clay.queue) == 1  # handed off to Clay exactly once


def test_2b_apollo_never_overwrites_verified_crm_identity(ctx):
    # pre-existing verified contact with a corrected name
    cid = ctx.zoho.upsert_contact(
        {f.C_EMAIL: APOLLO_PERSON["email"], f.C_FIRST: "Janet", f.C_LAST: "Smith-Jones"}
    )
    ctx.apollo.people[GOOD_SIGNAL["domain"]] = [APOLLO_PERSON]
    res = sixsense.handle_intent_signal(ctx, GOOD_SIGNAL)
    apollo_discovery.discover_contacts(ctx, account_id=res["account_id"], domain=res["domain"])
    c = ctx.zoho.get_contact(cid)
    assert c[f.C_FIRST] == "Janet"          # CRM wins over Apollo
    assert c[f.C_APOLLO_ID] == "apollo-p-123"  # non-identity enrichment still applied


# ---- Test 3: enrichment -------------------------------------------------------
def test_3_clay_result_updates_zoho(ctx):
    contact_id = run_to_pending(ctx)
    c = ctx.zoho.get_contact(contact_id)
    assert c[f.C_AI_WORK_MODEL] == "HYBRID"
    assert c[f.C_AI_PITCH].startswith("Noticed Acme")
    assert c[f.C_CLAY_STATUS] == "COMPLETE"


def test_3b_duplicate_clay_completion_is_idempotent(ctx):
    contact_id = run_to_pending(ctx)
    r2 = clay_sync.handle_clay_result(
        ctx, {"zoho_contact_id": contact_id, **CLAY_RESULT_TEMPLATE}
    )
    assert r2["duplicate"]


# ---- Test 4: approval gate — nothing reaches Smartlead before approval -------
def test_4_pending_approval_no_smartlead_activity(ctx):
    contact_id = run_to_pending(ctx)
    c = ctx.zoho.get_contact(contact_id)
    assert c[f.C_APPROVAL_STATUS] == Status.PENDING_HUMAN_APPROVAL.value
    assert ctx.smartlead.leads == {}  # NOTHING was sent
    # even a direct (forged) dispatch attempt is refused
    with pytest.raises(dispatch.ApprovalGateError):
        dispatch.dispatch_approved_contact(ctx, zoho_contact_id=contact_id)
    assert ctx.smartlead.leads == {}


def test_4b_middleware_cannot_perform_the_approval_transition():
    with pytest.raises(HumanOnlyTransition):
        assert_transition(Status.PENDING_HUMAN_APPROVAL, Status.APPROVED, actor="system")
    # but the human path is legal
    assert_transition(Status.PENDING_HUMAN_APPROVAL, Status.APPROVED, actor="human")
    # and there is no shortcut around the gate
    with pytest.raises(IllegalTransition):
        assert_transition(Status.PERSONALIZATION_READY, Status.APPROVED, actor="human")
    with pytest.raises(IllegalTransition):
        assert_transition(Status.RESEARCH_COMPLETE, Status.SENT_TO_SMARTLEAD, actor="human")


# ---- Test 5: reject -----------------------------------------------------------
def test_5_rejected_contact_never_reaches_smartlead(ctx):
    contact_id = run_to_pending(ctx)
    ctx.zoho.update_contact(
        contact_id,
        {f.C_APPROVAL_STATUS: Status.REJECTED.value, f.C_REJECTION_REASON: "Not ICP"},
    )
    with pytest.raises(dispatch.ApprovalGateError):
        dispatch.dispatch_approved_contact(ctx, zoho_contact_id=contact_id)
    assert ctx.smartlead.leads == {}


def test_5b_do_not_contact_never_reaches_smartlead(ctx):
    contact_id = run_to_pending(ctx)
    ctx.zoho.update_contact(contact_id, {f.C_APPROVAL_STATUS: Status.DO_NOT_CONTACT.value})
    with pytest.raises(dispatch.ApprovalGateError):
        dispatch.dispatch_approved_contact(ctx, zoho_contact_id=contact_id)
    assert ctx.smartlead.leads == {}


# ---- Test 6: approve ------------------------------------------------------------
def test_6_approved_contact_reaches_smartlead_exactly_once(ctx):
    contact_id = run_to_pending(ctx)
    human_approves(ctx, contact_id)
    res = dispatch.dispatch_approved_contact(ctx, zoho_contact_id=contact_id)
    assert not res["duplicate"]
    assert len(ctx.smartlead.leads) == 1
    lead = ctx.smartlead.leads[res["smartlead_lead_id"]]
    assert lead["campaign_id"] == "CAMP-RH"  # HYBRID routed by config
    assert lead["custom_fields"]["personalized_pitch"].startswith("Noticed Acme")
    c = ctx.zoho.get_contact(contact_id)
    assert c[f.C_APPROVAL_STATUS] == Status.SENT_TO_SMARTLEAD.value
    assert c[f.C_OUTREACH_STATUS] == "ACTIVE"
    assert c[f.C_SMARTLEAD_LEAD_ID] == res["smartlead_lead_id"]


def test_6b_approval_without_approver_identity_is_refused(ctx):
    contact_id = run_to_pending(ctx)
    ctx.zoho.update_contact(contact_id, {f.C_APPROVAL_STATUS: Status.APPROVED.value})
    with pytest.raises(dispatch.ApprovalGateError, match="Approval_Timestamp"):
        dispatch.dispatch_approved_contact(ctx, zoho_contact_id=contact_id)
    assert ctx.smartlead.leads == {}


# ---- Test 7: duplicate approval ---------------------------------------------------
def test_7_duplicate_approval_webhook_creates_no_duplicate_lead(ctx):
    contact_id = run_to_pending(ctx)
    human_approves(ctx, contact_id)
    r1 = dispatch.dispatch_approved_contact(ctx, zoho_contact_id=contact_id)
    r2 = dispatch.dispatch_approved_contact(ctx, zoho_contact_id=contact_id)
    assert r2["duplicate"] and r2["smartlead_lead_id"] == r1["smartlead_lead_id"]
    assert len(ctx.smartlead.leads) == 1


def test_7b_lead_already_in_smartlead_is_linked_not_duplicated(ctx):
    contact_id = run_to_pending(ctx)
    ctx.smartlead.leads["555"] = {
        "id": "555", "campaign_id": "CAMP-RH", "email": APOLLO_PERSON["email"],
    }
    human_approves(ctx, contact_id)
    res = dispatch.dispatch_approved_contact(ctx, zoho_contact_id=contact_id)
    assert res["duplicate"] and res["smartlead_lead_id"] == "555"
    assert len(ctx.smartlead.leads) == 1


# ---- Test 8: opt-out ------------------------------------------------------------------
def test_8_opted_out_contact_is_never_submitted(ctx):
    contact_id = run_to_pending(ctx)
    human_approves(ctx, contact_id)
    ctx.zoho.update_contact(contact_id, {f.C_OPTED_OUT: True})
    with pytest.raises(dispatch.ApprovalGateError, match="opted out"):
        dispatch.dispatch_approved_contact(ctx, zoho_contact_id=contact_id)
    assert ctx.smartlead.leads == {}


# ---- Test 9: API failure -> retry + audit ------------------------------------------------
def test_9a_transient_zoho_failure_is_retried_and_logged(ctx):
    ctx.zoho.fail_next_upsert_account = 2  # two 503s then success
    res = sixsense.handle_intent_signal(ctx, GOOD_SIGNAL)
    assert res["account_id"]
    retries = [e for e in ctx.audit.events_for("account", "6s-acme-001") if e["status"] == "RETRY"]
    assert len(retries) == 2


def test_9b_transient_smartlead_failure_is_retried_then_succeeds(ctx):
    contact_id = run_to_pending(ctx)
    human_approves(ctx, contact_id)
    ctx.smartlead.fail_next_add = 1
    res = dispatch.dispatch_approved_contact(ctx, zoho_contact_id=contact_id)
    assert len(ctx.smartlead.leads) == 1 and not res["duplicate"]


def test_9c_exhausted_retries_log_failure_and_release_idempotency(ctx):
    contact_id = run_to_pending(ctx)
    human_approves(ctx, contact_id)
    ctx.smartlead.fail_next_add = 99
    with pytest.raises(Exception):
        dispatch.dispatch_approved_contact(ctx, zoho_contact_id=contact_id)
    c = ctx.zoho.get_contact(contact_id)
    assert c[f.C_SMARTLEAD_SYNC_STATUS] == "ERROR"
    assert "smartlead 500" in c[f.C_INTEGRATION_ERROR]
    assert ctx.audit.failures()
    # recovery: a later retry succeeds and sends exactly one lead
    ctx.smartlead.fail_next_add = 0
    res = dispatch.dispatch_approved_contact(ctx, zoho_contact_id=contact_id)
    assert len(ctx.smartlead.leads) == 1 and not res["duplicate"]


# ---- Test 10: missing personalization ---------------------------------------------------------
def test_10_missing_personalization_blocks_approval_path(ctx):
    ctx.apollo.people[GOOD_SIGNAL["domain"]] = [APOLLO_PERSON]
    res = sixsense.handle_intent_signal(ctx, GOOD_SIGNAL)
    (contact_id,) = apollo_discovery.discover_contacts(
        ctx, account_id=res["account_id"], domain=res["domain"]
    )
    clay_sync.handle_clay_result(
        ctx,
        {
            "zoho_contact_id": contact_id,
            **{**CLAY_RESULT_TEMPLATE, "personalized_pitch": ""},
        },
    )
    c = ctx.zoho.get_contact(contact_id)
    assert c[f.C_APPROVAL_STATUS] == Status.NEEDS_REVIEW.value  # not PENDING
    # even if someone forces APPROVED in CRM, the gate still refuses
    human_approves(ctx, contact_id)
    with pytest.raises(dispatch.ApprovalGateError, match="personalization"):
        dispatch.dispatch_approved_contact(ctx, zoho_contact_id=contact_id)
    assert ctx.smartlead.leads == {}


# ---- Security extras ------------------------------------------------------------------------------
def test_sec_forged_webhook_payload_cannot_bypass_gate(ctx):
    """A payload claiming APPROVED is irrelevant: dispatch only takes the id
    and re-reads Zoho. Here Zoho says PENDING, so the gate refuses."""
    contact_id = run_to_pending(ctx)
    with pytest.raises(dispatch.ApprovalGateError, match="not APPROVED"):
        dispatch.dispatch_approved_contact(ctx, zoho_contact_id=contact_id)


def test_sec_test_mode_interlock_blocks_live_send(ctx):
    ctx.settings = make_settings(test_mode=True)
    contact_id = run_to_pending(ctx)
    human_approves(ctx, contact_id)
    res = dispatch.dispatch_approved_contact(ctx, zoho_contact_id=contact_id)
    assert res.get("test_mode") is True
    assert ctx.smartlead.leads == {}


def test_sec_unknown_work_model_routes_to_catch_all_campaign(ctx):
    ctx.apollo.people[GOOD_SIGNAL["domain"]] = [APOLLO_PERSON]
    r = sixsense.handle_intent_signal(ctx, GOOD_SIGNAL)
    (contact_id,) = apollo_discovery.discover_contacts(
        ctx, account_id=r["account_id"], domain=r["domain"]
    )
    clay_sync.handle_clay_result(
        ctx,
        {"zoho_contact_id": contact_id, **{**CLAY_RESULT_TEMPLATE, "work_model": "no idea"}},
    )
    human_approves(ctx, contact_id)
    res = dispatch.dispatch_approved_contact(ctx, zoho_contact_id=contact_id)
    assert res["campaign_id"] == "CAMP-GEN"


def test_engagement_events_flow_back_to_zoho(ctx):
    contact_id = run_to_pending(ctx)
    human_approves(ctx, contact_id)
    dispatch.dispatch_approved_contact(ctx, zoho_contact_id=contact_id)
    engagement.handle_smartlead_event(
        ctx,
        {"event_type": "EMAIL_REPLY", "lead_email": APOLLO_PERSON["email"], "event_id": "e1"},
    )
    c = ctx.zoho.get_contact(contact_id)
    assert c[f.C_APPROVAL_STATUS] == Status.REPLIED.value
    # unsubscribe sets the opt-out flag permanently
    engagement.handle_smartlead_event(
        ctx,
        {"event_type": "LEAD_UNSUBSCRIBED", "lead_email": APOLLO_PERSON["email"], "event_id": "e2"},
    )
    assert ctx.zoho.get_contact(contact_id)[f.C_OPTED_OUT] is True
