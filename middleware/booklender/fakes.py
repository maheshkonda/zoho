"""In-memory fake vendor clients.

Used by BOTH the automated test suite and the local client demo
(demo/demo_server.py). They implement the same Protocols as the HTTP
clients, so every pipeline — including the approval gate — runs unmodified.
"""
from __future__ import annotations

import itertools

from .retry import IntegrationError


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

    def list_accounts(self, fields=None):
        return list(self.accounts.values())

    def list_contacts(self, fields=None):
        return list(self.contacts.values())


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
