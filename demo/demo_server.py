#!/usr/bin/env python3
"""BookLender RevOps Console — local sandbox deployment.

Runs the production pipeline modules (qualification, discovery, enrichment
sync, approval gate, engagement) against the in-process sandbox vendor
adapters. Seed data is fictional; no external calls are made and no email
can be sent from this deployment.

Run:
    pip install -r requirements.txt
    python demo/demo_server.py          # http://localhost:8090
"""
from __future__ import annotations

import sys
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "middleware"))

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from booklender import fields as f
from booklender.audit import AuditLog
from booklender.config import (
    CampaignRule, ContactConfig, ICPConfig, IntentConfig, RetryConfig, Settings,
)
from booklender.fakes import FakeApollo, FakeClay, FakeSmartlead, FakeZoho
from booklender.idempotency import IdempotencyStore
from booklender.pipeline import apollo_discovery, clay_sync, dispatch, engagement, sixsense
from booklender.pipeline.context import Context
from booklender.state_machine import Status

ENRICH_DELAY_SECONDS = 2.5  # simulated Clay table turnaround

# --------------------------------------------------------------------------
# Seed dataset (fictional companies and people)
# --------------------------------------------------------------------------
def _ts(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).date().isoformat()


SCENARIOS = {
    "crestline": {
        "signal": {
            "sixsense_account_id": "6s-84213", "company_name": "Crestline Software",
            "domain": "crestlinesoftware.com", "website": "https://crestlinesoftware.com",
            "industry": "Software", "employee_count": 840, "country": "United States",
            "intent_score": 88, "intent_tier": "HIGH",
            "intent_topics": ["Employee Benefits", "Workplace Culture"],
            "signal_timestamp": _ts(0),
        },
        "person": {
            "id": "ap-559102", "first_name": "Jane", "last_name": "Whitfield",
            "title": "VP People", "email": "jane.whitfield@crestlinesoftware.com",
            "linkedin_url": "https://www.linkedin.com/in/jwhitfield-people", "seniority": "vp",
        },
        "clay": {
            "work_model": "Hybrid", "confidence": 0.86,
            "research_summary": "Careers page lists 3-day hybrid schedule across Denver, Austin and Raleigh offices; benefits section highlights a $1,200/yr learning stipend and quarterly team offsites.",
            "personalized_pitch": "Crestline's careers page leads with the learning stipend and hybrid schedule — BookLender runs a rotating curated library for exactly that setup: titles matched to each team, shipped to office or home, zero inventory work for People Ops.",
            "cta": "Open to a 15-minute walkthrough of the hybrid rollout?",
        },
    },
    "meridian": {
        "signal": {
            "sixsense_account_id": "6s-77045", "company_name": "Meridian Health Partners",
            "domain": "meridianhealthpartners.com", "website": "https://meridianhealthpartners.com",
            "industry": "Healthcare", "employee_count": 2400, "country": "United States",
            "intent_score": 92, "intent_tier": "VERY_HIGH",
            "intent_topics": ["Employee Wellness", "Employee Benefits"],
            "signal_timestamp": _ts(0),
        },
        "person": {
            "id": "ap-612384", "first_name": "Ravi", "last_name": "Patel",
            "title": "Chief People Officer", "email": "ravi.patel@meridianhealthpartners.com",
            "linkedin_url": "https://www.linkedin.com/in/ravipatel-cpo", "seniority": "c_suite",
        },
        "clay": {
            "work_model": "Remote", "confidence": 0.91,
            "research_summary": "Remote-first since 2022 (2,400 employees, 38 states). Public benefits page includes a $500 annual wellness budget per employee and a company-wide reading program mentioned in two press releases.",
            "personalized_pitch": "Meridian already funds a wellness budget and runs a reading program — BookLender consolidates both: curated titles shipped to each employee's home, swapped monthly, with utilization reporting your team doesn't have today.",
            "cta": "Worth 15 minutes to compare against the current program's numbers?",
        },
    },
    "hartley": {
        "signal": {
            "sixsense_account_id": "6s-90311", "company_name": "Hartley & Voss LLP",
            "domain": "hartleyvoss.com", "website": "https://hartleyvoss.com",
            "industry": "Legal Services", "employee_count": 410, "country": "United States",
            "intent_score": 75, "intent_tier": "HIGH",
            "intent_topics": ["Workplace Culture"],
            "signal_timestamp": _ts(1),
        },
        "person": {
            "id": "ap-433870", "first_name": "Maria", "last_name": "Gonzalez",
            "title": "HR Director", "email": "maria.gonzalez@hartleyvoss.com",
            "linkedin_url": "https://www.linkedin.com/in/mgonzalez-hr", "seniority": "director",
        },
        "clay": {
            "work_model": "On-site", "confidence": 0.74,
            "research_summary": "Single Chicago office; firm newsletter (public) features a staffed library corner and a monthly associates' book club running since 2023.",
            "personalized_pitch": "Hartley & Voss's book club has been running since 2023 per your newsletter — BookLender keeps that shelf current automatically: monthly curated rotation matched to what associates actually check out.",
            "cta": "Can I send the one-pager your book club lead would want to see?",
        },
    },
    "bluefin": {
        "signal": {
            "sixsense_account_id": "6s-28857", "company_name": "Bluefin Logistics Group",
            "domain": "bluefinlogisticsgroup.com", "website": "https://bluefinlogisticsgroup.com",
            "industry": "Logistics", "employee_count": 5200, "country": "United States",
            "intent_score": 81, "intent_tier": "HIGH",
            "intent_topics": ["Employee Benefits"],
            "signal_timestamp": _ts(1),
        },
        "person": {
            "id": "ap-518226", "first_name": "Dana", "last_name": "Okafor",
            "title": "Total Rewards Lead", "email": "dana.okafor@bluefinlogisticsgroup.com",
            "linkedin_url": "https://www.linkedin.com/in/dokafor-rewards", "seniority": "head",
        },
        # Insufficient public evidence -> UNKNOWN + empty pitch => NEEDS_REVIEW
        "clay": {
            "work_model": "Unknown", "confidence": 0.2,
            "research_summary": "", "personalized_pitch": "", "cta": "",
        },
    },
    "arcadia": {
        "signal": {
            "sixsense_account_id": "6s-66120", "company_name": "Arcadia Learning",
            "domain": "arcadialearning.com", "website": "https://arcadialearning.com",
            "industry": "Education", "employee_count": 620, "country": "United States",
            "intent_score": 84, "intent_tier": "HIGH",
            "intent_topics": ["Learning and Development", "Employee Benefits"],
            "signal_timestamp": _ts(2),
        },
        "person": {
            "id": "ap-701558", "first_name": "Tom", "last_name": "Becker",
            "title": "Head of People & Culture", "email": "tom.becker@arcadialearning.com",
            "linkedin_url": "https://www.linkedin.com/in/tbecker-people", "seniority": "head",
        },
        "clay": {
            "work_model": "Hybrid", "confidence": 0.79,
            "research_summary": "Hybrid (2 days/week) per careers FAQ; L&D page commits to '52 books a year' as a company value and reimburses individual book purchases.",
            "personalized_pitch": "Arcadia literally puts '52 books a year' on its L&D page — BookLender turns the reimbursement process into a managed program: curated delivery, shared team shelves, and a single invoice instead of expense reports.",
            "cta": "15 minutes to see what replacing reimbursements looks like?",
        },
    },
    "nimbus": {
        "signal": {
            "sixsense_account_id": "6s-15408", "company_name": "Nimbus Data Systems",
            "domain": "nimbusdatasystems.com", "industry": "Software",
            "employee_count": 310, "country": "United States",
            "intent_score": 22, "intent_tier": "LOW",
            "intent_topics": ["Cloud Storage"], "signal_timestamp": _ts(0),
        },
        "person": None,  # never reached: signal fails qualification
        "clay": None,
    },
}


def build_ctx() -> Context:
    settings = Settings(
        icp=ICPConfig(min_employee_count=100, max_employee_count=20000,
                      included_countries=["United States"]),
        intent=IntentConfig(min_score=70, accepted_tiers=["HIGH", "VERY_HIGH"],
                            relevant_topics=["Employee Benefits", "Workplace Culture",
                                             "Employee Wellness", "Learning and Development"]),
        contacts=ContactConfig(target_titles=["VP People", "CHRO", "HR Director",
                                              "Chief People Officer", "Total Rewards",
                                              "People & Culture"],
                               target_seniorities=["c_suite", "vp", "director", "head"],
                               max_contacts_per_account=3),
        campaigns=[
            CampaignRule(campaign_id="SL-1180", name="HR Outreach — Remote/Hybrid",
                         when_work_model=["REMOTE", "HYBRID"]),
            CampaignRule(campaign_id="SL-1181", name="HR Outreach — General",
                         when_work_model=[]),
        ],
        retry=RetryConfig(max_attempts=3, base_delay_seconds=0.0, max_delay_seconds=0.0),
        test_mode=False,  # sandbox Smartlead adapter only — no external delivery path
    )
    ctx = Context(settings=settings, zoho=FakeZoho(), apollo=FakeApollo(),
                  clay=FakeClay(), smartlead=FakeSmartlead(),
                  audit=AuditLog(), idem=IdempotencyStore())
    for sc in SCENARIOS.values():
        if sc["person"]:
            ctx.apollo.people[sc["signal"]["domain"]] = [sc["person"]]
    return ctx


app = FastAPI(title="BookLender RevOps Console")
CTX = build_ctx()
LOG: list[dict] = []
_LOCK = threading.Lock()


def log(level: str, msg: str):
    with _LOCK:
        LOG.append({"t": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                    "level": level, "msg": msg})
        del LOG[:-80]


@app.get("/", response_class=HTMLResponse)
def index():
    return (Path(__file__).parent / "index.html").read_text(encoding="utf-8")


@app.post("/demo/reset")
def reset():
    global CTX
    CTX = build_ctx()
    with _LOCK:
        LOG.clear()
    log("INFO", "sandbox reset · pipeline state cleared")
    return {"ok": True}


def _run_enrichment(contact_id: str):
    """Background enrichment completion (simulated Clay table turnaround)."""
    contact = CTX.zoho.get_contact(contact_id)
    if not contact:
        return
    sc = next((s for s in SCENARIOS.values()
               if s["person"] and s["person"]["email"] == contact.get(f.C_EMAIL)), None)
    if not sc or not sc["clay"]:
        return
    res = clay_sync.handle_clay_result(
        CTX, {"zoho_contact_id": contact_id,
              "clay_record_id": f"clay-{contact_id}", **sc["clay"]})
    if res.get("duplicate"):
        log("INFO", f"clay result redelivered contact={contact_id} · idempotent, no-op")
    elif res["status"] == Status.PENDING_HUMAN_APPROVAL.value:
        log("INFO", f"enrichment complete contact={contact_id} model={sc['clay']['work_model'].upper()} conf={sc['clay']['confidence']}")
        log("INFO", f"status → PENDING_HUMAN_APPROVAL contact={contact_id} · awaiting operator review")
    else:
        log("WARN", f"enrichment incomplete contact={contact_id} · insufficient evidence, status → NEEDS_REVIEW")


@app.post("/demo/signal/{key}")
def fire_signal(key: str):
    sc = SCENARIOS.get(key)
    if not sc:
        raise HTTPException(404, "unknown scenario")
    name = sc["signal"]["company_name"]
    res = sixsense.handle_intent_signal(CTX, sc["signal"])
    if not res.get("qualified"):
        log("WARN", f"6sense signal dropped acct={sc['signal']['domain']} · {res['reason']}")
        return res
    if res.get("duplicate"):
        log("INFO", f"6sense signal duplicate acct={sc['signal']['domain']} · idempotent, no-op")
        return res
    log("INFO", f"6sense signal qualified acct={sc['signal']['domain']} score={sc['signal']['intent_score']} → account upserted")
    ids = apollo_discovery.discover_contacts(CTX, account_id=res["account_id"],
                                             domain=res["domain"])
    if ids:
        c = CTX.zoho.get_contact(ids[0])
        log("INFO", f"apollo matched {len(ids)} contact(s) · {c[f.C_FIRST]} {c[f.C_LAST]} ({c[f.C_TITLE]}) → CRM + enrichment queue")
        for cid in ids:
            threading.Timer(ENRICH_DELAY_SECONDS, _run_enrichment, args=[cid]).start()
    res["contact_ids"] = ids
    return res


@app.post("/demo/clay/{contact_id}")
def rerun_enrichment(contact_id: str):
    """Manual re-run (used from the console for NEEDS_REVIEW records)."""
    if not CTX.zoho.get_contact(contact_id):
        raise HTTPException(404, "no such contact")
    _run_enrichment(contact_id)
    return {"ok": True}


@app.post("/demo/approve/{contact_id}")
def approve(contact_id: str, approver: str = "m.konda@booklender.com"):
    """Operator APPROVE (in production this is the Zoho Blueprint transition:
    Zoho stamps approver + timestamp, then the signed webhook hands only the
    record id to the dispatcher, which re-validates against the CRM)."""
    contact = CTX.zoho.get_contact(contact_id)
    if not contact:
        raise HTTPException(404, "no such contact")
    if contact.get(f.C_APPROVAL_STATUS) == Status.PENDING_HUMAN_APPROVAL.value:
        CTX.zoho.update_contact(contact_id, {
            f.C_APPROVAL_STATUS: Status.APPROVED.value,
            f.C_APPROVAL_TS: datetime.now(timezone.utc).isoformat(),
            f.C_APPROVED_BY: approver,
        })
        log("INFO", f"approval recorded contact={contact_id} by={approver}")
    try:
        res = dispatch.dispatch_approved_contact(CTX, zoho_contact_id=contact_id)
    except dispatch.ApprovalGateError as e:
        log("ERROR", f"dispatch blocked contact={contact_id} · {e}")
        raise HTTPException(403, str(e))
    if res.get("duplicate"):
        log("INFO", f"dispatch replay contact={contact_id} · existing lead {res['smartlead_lead_id']} returned, no duplicate created")
    else:
        log("INFO", f"lead created id={res['smartlead_lead_id']} campaign={res['campaign_id']} contact={contact_id}")
    return res


@app.post("/demo/reject/{contact_id}")
def reject(contact_id: str, reason: str = "Not a fit at this time"):
    if not CTX.zoho.get_contact(contact_id):
        raise HTTPException(404, "no such contact")
    CTX.zoho.update_contact(contact_id, {
        f.C_APPROVAL_STATUS: Status.REJECTED.value,
        f.C_REJECTION_REASON: reason, f.C_OUTREACH_STATUS: "NONE"})
    log("INFO", f"prospect rejected contact={contact_id} reason=\"{reason}\"")
    return {"ok": True}


@app.post("/demo/dnc/{contact_id}")
def do_not_contact(contact_id: str):
    if not CTX.zoho.get_contact(contact_id):
        raise HTTPException(404, "no such contact")
    CTX.zoho.update_contact(contact_id, {
        f.C_APPROVAL_STATUS: Status.DO_NOT_CONTACT.value,
        f.C_OPTED_OUT: True, f.C_OUTREACH_STATUS: "NONE"})
    log("WARN", f"do-not-contact set contact={contact_id} · opt-out flag written, terminal state")
    return {"ok": True}


@app.post("/demo/attack/{contact_id}")
def gate_selftest(contact_id: str):
    """Gate self-test: replays a dispatch webhook for a record that has no
    valid approval on file. Expected result: refusal."""
    log("WARN", f"gate self-test · replaying dispatch webhook contact={contact_id} without valid approval")
    try:
        dispatch.dispatch_approved_contact(CTX, zoho_contact_id=contact_id)
    except dispatch.ApprovalGateError as e:
        log("ERROR", f"dispatch blocked contact={contact_id} · {e}")
        return {"blocked": True, "reason": str(e)}
    log("INFO", f"dispatch permitted contact={contact_id} · record holds a valid approval (idempotency still enforces single lead)")
    return {"blocked": False}


@app.post("/demo/event/{etype}/{contact_id}")
def engagement_event(etype: str, contact_id: str):
    contact = CTX.zoho.get_contact(contact_id)
    if not contact:
        raise HTTPException(404, "no such contact")
    mapping = {"reply": "EMAIL_REPLY", "bounce": "EMAIL_BOUNCE", "unsub": "LEAD_UNSUBSCRIBED"}
    if etype not in mapping:
        raise HTTPException(400, "reply|bounce|unsub")
    res = engagement.handle_smartlead_event(CTX, {
        "event_type": mapping[etype], "lead_email": contact.get(f.C_EMAIL),
        "event_id": f"evt-{etype}-{contact_id}-{len(LOG)}"})
    log("INFO", f"smartlead webhook {mapping[etype]} contact={contact_id} → CRM updated")
    return res


@app.get("/demo/state")
def state():
    contacts = []
    for c in CTX.zoho.contacts.values():
        acc = None
        acc_ref = c.get(f.C_ACCOUNT)
        if isinstance(acc_ref, dict):
            acc = CTX.zoho.get_account(acc_ref.get("id", ""))
        contacts.append({**c, "_account": acc})
    return {
        "accounts": list(CTX.zoho.accounts.values()),
        "contacts": contacts,
        "smartlead": list(CTX.smartlead.leads.values()),
        "log": LOG[::-1],
        "scenarios": {k: {"name": v["signal"]["company_name"],
                          "score": v["signal"]["intent_score"],
                          "tier": v["signal"]["intent_tier"],
                          "topics": ", ".join(v["signal"]["intent_topics"]),
                          "received": v["signal"]["signal_timestamp"]}
                      for k, v in SCENARIOS.items()},
    }


if __name__ == "__main__":
    url = "http://localhost:8090"
    print(f"\n  BookLender RevOps Console (sandbox) → {url}\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run(app, host="127.0.0.1", port=8090, log_level="warning")
