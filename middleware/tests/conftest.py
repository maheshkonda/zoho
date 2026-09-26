"""Test harness: in-memory fakes for Zoho / Apollo / Clay / Smartlead.

These implement the same Protocols as the HTTP clients, so the entire
pipeline — including the approval gate — runs unmodified against them.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from booklender.audit import AuditLog
from booklender.config import (
    CampaignRule,
    ContactConfig,
    ICPConfig,
    IntentConfig,
    RetryConfig,
    Settings,
)
from booklender.idempotency import IdempotencyStore
from booklender.pipeline.context import Context
from booklender.retry import IntegrationError


class FakeZoho:
    def __init__(self):
        self.accounts: dict[str, dict] = {}
        self.contacts: dict[str, dict] = {}
        self._ids = itertools.count(1)
        self.fail_next_upsert_account = 0  # inject transient failures

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids):06d}"

    # Accounts
    def upsert_account(self, account: dict) -> str:
        if self.fail_next_upsert_account > 0:
            self.fail_next_upsert_account -= 1
            raise IntegrationError("zoho 503", status_code=503)
        domain = account.get("Company_Domain")
        existing = self.find_account_by_domain(domain) if domain else None
        if existing:
            existing.update(account)
            return existing["id"]
        aid = self._new_id("acc")
        self.accounts[aid] = {"id": aid, **account}
        return aid

    def get_account(self, account_id):
        return self.accounts.get(account_id)

    def find_account_by_domain(self, domain):
        for a in self.accounts.values():
            if a.get("Company_Domain") == domain:
                return a
        return None

    def update_account(self, account_id, fields):
        self.accounts[account_id].update(fields)

    # Contacts
    def upsert_contact(self, contact: dict) -> str:
        existing = self.find_contact_by_email(contact.get("Email", ""))
        if existing:
            existing.update(contact)
            return existing["id"]
        cid = self._new_id("con")
        self.contacts[cid] = {"id": cid, **contact}
        return cid

    def get_contact(self, contact_id):
        return self.contacts.get(contact_id)

    def find_contact_by_email(self, email):
        for c in self.contacts.values():
            if (c.get("Email") or "").lower() == (email or "").lower():
                return c
        return None

    def update_contact(self, contact_id, fields):
        self.contacts[contact_id].update(fields)


class FakeApollo:
    def __init__(self):
        self.people: dict[str, list[dict]] = {}  # domain -> people

    def search_people(self, *, domain, titles, seniorities, limit):
        return self.people.get(domain, [])[:limit]


class FakeClay:
    def __init__(self):
        self.queue: list[dict] = []

    def enqueue_contact(self, payload):
        self.queue.append(payload)
        return payload["zoho_contact_id"]


class FakeSmartlead:
    def __init__(self):
        self.leads: dict[str, dict] = {}  # lead_id -> lead (with campaign_id)
        self._ids = itertools.count(9000)
        self.fail_next_add = 0

    def find_lead_by_email(self, campaign_id, email):
        for lead in self.leads.values():
            if lead["email"] == email:
                return lead
        return None

    def add_lead(self, campaign_id, lead):
        if self.fail_next_add > 0:
            self.fail_next_add -= 1
            raise IntegrationError("smartlead 500", status_code=500)
        lead_id = str(next(self._ids))
        self.leads[lead_id] = {"id": lead_id, "campaign_id": campaign_id, **lead}
        return lead_id


def make_settings(**overrides) -> Settings:
    base = dict(
        icp=ICPConfig(
            min_employee_count=100,
            max_employee_count=20000,
            excluded_industries=["Tobacco"],
            included_countries=["United States"],
            excluded_domains=["blocked.example.com"],
        ),
        intent=IntentConfig(
            min_score=70,
            accepted_tiers=["HIGH", "VERY_HIGH"],
            relevant_topics=["Employee Benefits", "Workplace Culture"],
        ),
        contacts=ContactConfig(
            target_titles=["VP People", "CHRO", "HR Director"],
            target_seniorities=["vp", "c_suite", "director"],
            max_contacts_per_account=3,
        ),
        campaigns=[
            CampaignRule(
                campaign_id="CAMP-RH", name="Remote/Hybrid",
                when_work_model=["REMOTE", "HYBRID"],
            ),
            CampaignRule(campaign_id="CAMP-GEN", name="General", when_work_model=[]),
        ],
        retry=RetryConfig(max_attempts=3, base_delay_seconds=0.0, max_delay_seconds=0.0),
        test_mode=False,  # fakes are safe; test_mode interlock has its own test
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def ctx() -> Context:
    return Context(
        settings=make_settings(),
        zoho=FakeZoho(),
        apollo=FakeApollo(),
        clay=FakeClay(),
        smartlead=FakeSmartlead(),
        audit=AuditLog(),
        idem=IdempotencyStore(),
    )


# --- canonical test data (fake company / test contact only) ----------------
GOOD_SIGNAL = {
    "sixsense_account_id": "6s-acme-001",
    "company_name": "Acme Test Corporation",
    "domain": "acme-test.example.com",
    "website": "https://www.acme-test.example.com",
    "industry": "Software",
    "employee_count": 800,
    "country": "United States",
    "intent_score": 88,
    "intent_tier": "HIGH",
    "intent_topics": ["Employee Benefits", "Workplace Culture"],
    "signal_timestamp": "2026-09-25",
}

APOLLO_PERSON = {
    "id": "apollo-p-123",
    "first_name": "Jane",
    "last_name": "Smith",
    "title": "VP People",
    "email": "jane.smith@acme-test.example.com",
    "linkedin_url": "https://linkedin.com/in/janesmith-test",
    "seniority": "vp",
    "department": "HR",
}

CLAY_RESULT_TEMPLATE = {
    "clay_record_id": "clay-rec-777",
    "work_model": "Hybrid",
    "confidence": 0.86,
    "research_summary": "Acme runs a distributed-first workforce across 12 US states.",
    "personalized_pitch": "Noticed Acme's hybrid team spans 12 states — BookLender ships curated books to every employee's door.",
    "cta": "Worth a 15-minute look at how other hybrid HR teams use it?",
}
