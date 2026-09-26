#!/usr/bin/env python3
"""BookLender prototype demo — runs the REAL pipeline code locally against
in-memory fake vendors (no credentials, no network, no real data, nothing
is ever emailed).

Everything the dashboard shows is produced by the same production modules
that would talk to the live systems: qualification, discovery, enrichment
sync, the approval state machine, and — crucially — the server-side
approval gate in booklender/pipeline/dispatch.py.

Run:
    pip install -r requirements.txt
    python demo/demo_server.py          # http://localhost:8090

Demo talk track: demo/README.md
"""
from __future__ import annotations

import sys
import webbrowser
from datetime import datetime, timezone
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

# --------------------------------------------------------------------------
# Fictional demo dataset (no real companies or people)
# --------------------------------------------------------------------------
SCENARIOS = {
    "acme": {
        "signal": {
            "sixsense_account_id": "6s-0001", "company_name": "Acme Robotics",
            "domain": "acme-robotics.example", "website": "https://acme-robotics.example",
            "industry": "Software", "employee_count": 850, "country": "United States",
            "intent_score": 88, "intent_tier": "HIGH",
            "intent_topics": ["Employee Benefits", "Workplace Culture"],
            "signal_timestamp": "2026-09-24",
        },
        "person": {
            "id": "ap-1001", "first_name": "Jane", "last_name": "Smith",
            "title": "VP People", "email": "jane.smith@acme-robotics.example",
            "linkedin_url": "https://linkedin.example/janesmith", "seniority": "vp",
        },
        "clay": {
            "work_model": "Hybrid", "confidence": 0.86,
            "research_summary": "Acme Robotics runs a hybrid workforce across 12 US offices; careers page highlights a 'learning stipend' and quarterly culture weeks.",
            "personalized_pitch": "Saw Acme's careers page leads with the learning stipend and hybrid culture weeks — BookLender puts a rotating, curated library on every employee's desk (or doorstep) without HR managing inventory.",
            "cta": "Open to a 15-minute look at how hybrid People teams run it?",
        },
    },
    "northwind": {
        "signal": {
            "sixsense_account_id": "6s-0002", "company_name": "Northwind Health",
            "domain": "northwind-health.example", "website": "https://northwind-health.example",
            "industry": "Healthcare", "employee_count": 2400, "country": "United States",
            "intent_score": 92, "intent_tier": "VERY_HIGH",
            "intent_topics": ["Employee Wellness", "Employee Benefits"],
            "signal_timestamp": "2026-09-25",
        },
        "person": {
            "id": "ap-1002", "first_name": "Ravi", "last_name": "Patel",
            "title": "Chief People Officer", "email": "ravi.patel@northwind-health.example",
            "linkedin_url": "https://linkedin.example/ravipatel", "seniority": "c_suite",
        },
        "clay": {
            "work_model": "Remote", "confidence": 0.91,
            "research_summary": "Northwind Health is remote-first (2,400 employees, 38 states) and publicly promotes a wellness-benefits budget per employee.",
            "personalized_pitch": "Northwind's remote-first wellness budget caught my eye — BookLender is the benefit remote teams actually use: curated books shipped home, swapped monthly, zero admin for your team.",
            "cta": "Worth 15 minutes to see the remote rollout playbook?",
        },
    },
    "initech": {
        "signal": {
            "sixsense_account_id": "6s-0003", "company_name": "Initech Software",
            "domain": "initech.example", "website": "https://initech.example",
            "industry": "Software", "employee_count": 400, "country": "United States",
            "intent_score": 75, "intent_tier": "HIGH",
            "intent_topics": ["Workplace Culture"],
            "signal_timestamp": "2026-09-25",
        },
        "person": {
            "id": "ap-1003", "first_name": "Maria", "last_name": "Gonzalez",
            "title": "HR Director", "email": "maria.gonzalez@initech.example",
            "linkedin_url": "https://linkedin.example/mgonzalez", "seniority": "director",
        },
        "clay": {
            "work_model": "On-site", "confidence": 0.74,
            "research_summary": "Initech operates a single Austin campus; blog posts feature an office library corner and monthly book-club photos.",
            "personalized_pitch": "Initech's book-club posts made this an easy note — BookLender keeps that shelf fresh automatically: curated titles rotated monthly, matched to what your teams actually read.",
            "cta": "Can I send the 2-pager your book club would want to see?",
        },
    },
    "lowsignal": {
        "signal": {
            "sixsense_account_id": "6s-0004", "company_name": "LowSignal Corp",
            "domain": "lowsignal.example", "industry": "Software",
            "employee_count": 300, "country": "United States",
            "intent_score": 22, "intent_tier": "LOW",
            "intent_topics": ["Cloud Storage"], "signal_timestamp": "2026-09-25",
        },
        "person": None,  # never reached: disqualified by config rules
        "clay": None,
    },
    "globex": {
        "signal": {
            "sixsense_account_id": "6s-0005", "company_name": "Globex Industrial",
            "domain": "globex-industrial.example", "industry": "Manufacturing",
            "employee_count": 5200, "country": "United States",
            "intent_score": 81, "intent_tier": "HIGH",
            "intent_topics": ["Employee Benefits"], "signal_timestamp": "2026-09-25",
        },
        "person": {
            "id": "ap-1005", "first_name": "Dana", "last_name": "Okafor",
            "title": "Total Rewards Lead", "email": "dana.okafor@globex-industrial.example",
            "linkedin_url": "https://linkedin.example/dokafor", "seniority": "head",
        },
        # Insufficient evidence -> UNKNOWN + empty pitch => NEEDS_REVIEW path
        "clay": {
            "work_model": "Unknown", "confidence": 0.2,
            "research_summary": "", "personalized_pitch": "", "cta": "",
        },
    },
}


def build_ctx() -> Context:
    settings = Settings(
        icp=ICPConfig(min_employee_count=100, max_employee_count=20000,
                      included_countries=["United States"]),
        intent=IntentConfig(min_score=70, accepted_tiers=["HIGH", "VERY_HIGH"],
                            relevant_topics=["Employee Benefits", "Workplace Culture",
                                             "Employee Wellness"]),
        contacts=ContactConfig(target_titles=["VP People", "CHRO", "HR Director",
                                              "Chief People Officer", "Total Rewards"],
                               target_seniorities=["c_suite", "vp", "director", "head"],
                               max_contacts_per_account=3),
        campaigns=[
            CampaignRule(campaign_id="SL-DEMO-REMOTE", name="BookLender HR Outreach — Remote/Hybrid",
                         when_work_model=["REMOTE", "HYBRID"]),
            CampaignRule(campaign_id="SL-DEMO-GENERAL", name="BookLender HR Outreach — General",
                         when_work_model=[]),
        ],
        retry=RetryConfig(max_attempts=3, base_delay_seconds=0.0, max_delay_seconds=0.0),
        test_mode=False,  # fake Smartlead only — nothing real can be sent
    )
    ctx = Context(settings=settings, zoho=FakeZoho(), apollo=FakeApollo(),
                  clay=FakeClay(), smartlead=FakeSmartlead(),
                  audit=AuditLog(), idem=IdempotencyStore())
    for sc in SCENARIOS.values():
        if sc["person"]:
            ctx.apollo.people[sc["signal"]["domain"]] = [sc["person"]]
    return ctx


app = FastAPI(title="BookLender Prototype Demo")
CTX = build_ctx()
FEED: list[dict] = []  # narrative event feed for the dashboard


def note(kind: str, text: str):
    FEED.append({"t": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                 "kind": kind, "text": text})
    del FEED[:-60]


@app.get("/", response_class=HTMLResponse)
def index():
    return (Path(__file__).parent / "index.html").read_text(encoding="utf-8")


@app.post("/demo/reset")
def reset():
    global CTX
    CTX = build_ctx()
    FEED.clear()
    note("info", "Demo reset — clean slate.")
    return {"ok": True}


@app.post("/demo/signal/{key}")
def fire_signal(key: str):
    sc = SCENARIOS.get(key)
    if not sc:
        raise HTTPException(404, "unknown scenario")
    res = sixsense.handle_intent_signal(CTX, sc["signal"])
    name = sc["signal"]["company_name"]
    if not res.get("qualified"):
        note("skip", f"6sense signal: {name} — DISQUALIFIED by config rules ({res['reason']}). Nothing created.")
        return res
    if res.get("duplicate"):
        note("skip", f"6sense signal: {name} — duplicate signal, idempotent skip.")
        return res
    note("ok", f"6sense signal: {name} qualified → Zoho Account created (intent {sc['signal']['intent_score']}).")
    ids = apollo_discovery.discover_contacts(CTX, account_id=res["account_id"],
                                             domain=res["domain"])
    if ids:
        c = CTX.zoho.get_contact(ids[0])
        note("ok", f"Apollo found {c[f.C_FIRST]} {c[f.C_LAST]} ({c[f.C_TITLE]}) → Zoho Contact → queued to Clay.")
    res["contact_ids"] = ids
    return res


@app.post("/demo/clay/{contact_id}")
def clay_completes(contact_id: str):
    contact = CTX.zoho.get_contact(contact_id)
    if not contact:
        raise HTTPException(404, "no such contact")
    sc = next((s for s in SCENARIOS.values()
               if s["person"] and s["person"]["email"] == contact.get(f.C_EMAIL)), None)
    if not sc or not sc["clay"]:
        raise HTTPException(400, "no Clay scenario for this contact")
    res = clay_sync.handle_clay_result(
        CTX, {"zoho_contact_id": contact_id,
              "clay_record_id": f"clay-{contact_id}", **sc["clay"]})
    if res.get("duplicate"):
        note("skip", "Clay completion re-delivered — idempotent skip, nothing changed.")
    elif res["status"] == Status.PENDING_HUMAN_APPROVAL.value:
        note("stop", f"Clay research + AI pitch written to Zoho. STATUS = PENDING_HUMAN_APPROVAL. ⛔ Machine STOPPED — waiting for a human.")
    else:
        note("warn", f"Clay returned insufficient evidence → NEEDS_REVIEW (no fabrication, approval blocked).")
    return res


@app.post("/demo/approve/{contact_id}")
def human_approve(contact_id: str, approver: str = "operator@booklender.demo"):
    """Simulates the human clicking APPROVE in the Zoho Blueprint: Zoho
    stamps who/when, then the signed webhook hands ONLY the id to dispatch,
    which re-validates everything against the record."""
    contact = CTX.zoho.get_contact(contact_id)
    if not contact:
        raise HTTPException(404, "no such contact")
    if contact.get(f.C_APPROVAL_STATUS) == Status.PENDING_HUMAN_APPROVAL.value:
        CTX.zoho.update_contact(contact_id, {
            f.C_APPROVAL_STATUS: Status.APPROVED.value,
            f.C_APPROVAL_TS: datetime.now(timezone.utc).isoformat(),
            f.C_APPROVED_BY: approver,
        })
        note("human", f"HUMAN clicked APPROVE in Zoho ({approver}).")
    try:
        res = dispatch.dispatch_approved_contact(CTX, zoho_contact_id=contact_id)
    except dispatch.ApprovalGateError as e:
        note("block", f"APPROVAL GATE REFUSED: {e}")
        raise HTTPException(403, str(e))
    if res.get("duplicate"):
        note("skip", f"Duplicate approval delivery — gate returned the SAME lead (id {res['smartlead_lead_id']}). No duplicate email.")
    else:
        note("send", f"Gate re-validated the Zoho record → EXACTLY ONE lead sent to Smartlead campaign {res['campaign_id']}.")
    return res


@app.post("/demo/reject/{contact_id}")
def human_reject(contact_id: str, reason: str = "Not a fit right now"):
    if not CTX.zoho.get_contact(contact_id):
        raise HTTPException(404, "no such contact")
    CTX.zoho.update_contact(contact_id, {
        f.C_APPROVAL_STATUS: Status.REJECTED.value,
        f.C_REJECTION_REASON: reason, f.C_OUTREACH_STATUS: "NONE"})
    note("human", f"HUMAN clicked REJECT ({reason}). Outreach permanently blocked for this prospect.")
    return {"ok": True}


@app.post("/demo/dnc/{contact_id}")
def human_dnc(contact_id: str):
    if not CTX.zoho.get_contact(contact_id):
        raise HTTPException(404, "no such contact")
    CTX.zoho.update_contact(contact_id, {
        f.C_APPROVAL_STATUS: Status.DO_NOT_CONTACT.value,
        f.C_OPTED_OUT: True, f.C_OUTREACH_STATUS: "NONE"})
    note("human", "HUMAN clicked DO NOT CONTACT — terminal state, opt-out flag set.")
    return {"ok": True}


@app.post("/demo/attack/{contact_id}")
def attack_gate(contact_id: str):
    """The demo's proof moment: a forged 'APPROVED' webhook straight at the
    dispatcher, without any human approval in Zoho. The gate re-reads the
    record and refuses."""
    note("attack", "⚠ Simulating a forged/premature webhook claiming the contact is APPROVED…")
    try:
        dispatch.dispatch_approved_contact(CTX, zoho_contact_id=contact_id)
    except dispatch.ApprovalGateError as e:
        note("block", f"GATE HELD: {e}")
        return {"blocked": True, "reason": str(e)}
    note("send", "Gate allowed it — record was genuinely approved (idempotency still guarantees one lead).")
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
        "event_id": f"demo-{etype}-{contact_id}-{len(FEED)}"})
    note("ok", f"Smartlead event {mapping[etype]} → synced back to Zoho.")
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
        "feed": FEED[::-1],
        "scenarios": {k: {"name": v["signal"]["company_name"],
                          "score": v["signal"]["intent_score"]}
                      for k, v in SCENARIOS.items()},
    }


if __name__ == "__main__":
    url = "http://localhost:8090"
    print(f"\n  BookLender prototype demo → {url}\n  (all vendors are in-memory fakes; nothing leaves this machine)\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run(app, host="127.0.0.1", port=8090, log_level="warning")
