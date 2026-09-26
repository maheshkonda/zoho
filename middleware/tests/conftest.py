"""Test harness wiring: settings factory + fixtures.

The in-memory fakes live in booklender.fakes (shared with the client demo).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from booklender.audit import AuditLog
from booklender.fakes import FakeApollo, FakeClay, FakeSmartlead, FakeZoho  # noqa: F401
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
