"""6sense intent signal -> Zoho Account -> Apollo contact discovery trigger.

Qualification rules are pure configuration (config.yaml): intent threshold,
tiers, topics, ICP filters, exclusions. Nothing is hard-coded.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from .. import fields as f
from ..retry import with_retry
from ..state_machine import Status
from .context import Context


def normalize_domain(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower()
    if "//" in v:
        v = urlparse(v).netloc or v
    v = v.split("/")[0]
    if v.startswith("www."):
        v = v[4:]
    return v or None


def qualifies(ctx: Context, signal: dict[str, Any]) -> tuple[bool, str]:
    s, icp, intent = ctx.settings, ctx.settings.icp, ctx.settings.intent
    domain = normalize_domain(signal.get("domain") or signal.get("website"))
    if not domain:
        return False, "missing domain"
    if domain in [d.lower() for d in icp.excluded_domains]:
        return False, "excluded domain"
    score = int(signal.get("intent_score") or 0)
    if score < intent.min_score:
        return False, f"intent score {score} below threshold {intent.min_score}"
    tier = (signal.get("intent_tier") or "").upper()
    if intent.accepted_tiers and tier not in [t.upper() for t in intent.accepted_tiers]:
        return False, f"tier {tier or 'NONE'} not accepted"
    topics = signal.get("intent_topics") or []
    if intent.relevant_topics and not (
        {t.lower() for t in topics} & {t.lower() for t in intent.relevant_topics}
    ):
        return False, "no relevant intent topic"
    industry = signal.get("industry") or ""
    if industry and industry in icp.excluded_industries:
        return False, f"excluded industry {industry}"
    if icp.included_industries and industry and industry not in icp.included_industries:
        return False, f"industry {industry} outside ICP"
    employees = signal.get("employee_count")
    if employees is not None and not (
        icp.min_employee_count <= int(employees) <= icp.max_employee_count
    ):
        return False, f"employee count {employees} outside ICP"
    country = signal.get("country") or ""
    if icp.included_countries and country and country not in icp.included_countries:
        return False, f"country {country} outside ICP"
    return True, "qualified"


def handle_intent_signal(ctx: Context, signal: dict[str, Any]) -> dict[str, Any]:
    """Process one 6sense signal. Idempotent per (6sense account id, signal date)."""
    domain = normalize_domain(signal.get("domain") or signal.get("website"))
    six_id = signal.get("sixsense_account_id") or domain or "unknown"
    signal_ts = signal.get("signal_timestamp") or datetime.now(timezone.utc).date().isoformat()
    idem_key = f"6sense:{six_id}:{signal_ts}"

    ok, reason = qualifies(ctx, signal)
    if not ok:
        ctx.audit.record(
            source="6sense", destination="zoho", entity_type="account",
            entity_id=six_id, action="qualify", status="SKIPPED", error=reason,
        )
        return {"qualified": False, "reason": reason}

    if not ctx.idem.claim(idem_key):
        account_id = ctx.idem.result_of(idem_key) or ""
        ctx.audit.record(
            source="6sense", destination="zoho", entity_type="account",
            entity_id=account_id or six_id, action="upsert_account",
            status="SKIPPED", error="duplicate signal (idempotent)",
        )
        return {"qualified": True, "duplicate": True, "account_id": account_id}

    account = {
        f.A_NAME: signal.get("company_name") or domain,
        f.A_WEBSITE: signal.get("website") or f"https://{domain}",
        f.A_DOMAIN: domain,
        f.A_INDUSTRY: signal.get("industry"),
        f.A_EMPLOYEES: signal.get("employee_count"),
        f.A_COUNTRY: signal.get("country"),
        f.A_SIXSENSE_ID: signal.get("sixsense_account_id"),
        f.A_INTENT_SCORE: signal.get("intent_score"),
        f.A_INTENT_TIER: signal.get("intent_tier"),
        f.A_INTENT_TOPICS: ", ".join(signal.get("intent_topics") or []),
        f.A_LAST_ACTIVITY: signal_ts,
        f.A_SOURCE: "6sense",
        f.A_PROSPECT_STATUS: Status.INTENT_DETECTED.value,
    }
    account = {k: v for k, v in account.items() if v is not None}

    try:
        r = ctx.settings.retry
        account_id = with_retry(
            lambda: ctx.zoho.upsert_account(account),
            max_attempts=r.max_attempts, base_delay=r.base_delay_seconds,
            max_delay=r.max_delay_seconds,
            on_retry=lambda n, e: ctx.audit.record(
                source="6sense", destination="zoho", entity_type="account",
                entity_id=six_id, action="upsert_account", status="RETRY",
                error=str(e), retry_count=n,
            ),
        )
    except Exception as e:
        ctx.idem.release(idem_key)  # allow a later redelivery to retry
        ctx.audit.record(
            source="6sense", destination="zoho", entity_type="account",
            entity_id=six_id, action="upsert_account", status="FAILURE", error=str(e),
        )
        raise
    ctx.idem.set_result(idem_key, account_id)
    ctx.audit.record(
        source="6sense", destination="zoho", entity_type="account",
        entity_id=account_id, action="upsert_account", status="SUCCESS",
        request_ref=idem_key,
    )
    return {"qualified": True, "duplicate": False, "account_id": account_id, "domain": domain}
