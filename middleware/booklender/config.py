"""Central configuration layer.

All tunable business rules (ICP, intent thresholds, target titles, campaign
routing, retry limits) live in a YAML file so a RevOps operator can change
them without touching code. All secrets live in environment variables only —
never in YAML, never in code, never in CRM fields.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(Exception):
    pass


@dataclass
class ICPConfig:
    min_employee_count: int = 50
    max_employee_count: int = 100_000
    included_industries: list[str] = field(default_factory=list)  # empty = all
    excluded_industries: list[str] = field(default_factory=list)
    included_countries: list[str] = field(default_factory=list)   # empty = all
    excluded_domains: list[str] = field(default_factory=list)


@dataclass
class IntentConfig:
    min_score: int = 70
    accepted_tiers: list[str] = field(default_factory=lambda: ["HIGH", "VERY_HIGH"])
    relevant_topics: list[str] = field(default_factory=list)  # empty = any topic


@dataclass
class ContactConfig:
    target_titles: list[str] = field(default_factory=list)
    target_seniorities: list[str] = field(default_factory=list)
    max_contacts_per_account: int = 3


@dataclass
class CampaignRule:
    """Route an approved contact to a Smartlead campaign."""
    campaign_id: str
    name: str
    when_work_model: list[str] = field(default_factory=list)  # empty = catch-all


@dataclass
class RetryConfig:
    max_attempts: int = 4
    base_delay_seconds: float = 2.0
    max_delay_seconds: float = 60.0


@dataclass
class Settings:
    icp: ICPConfig
    intent: IntentConfig
    contacts: ContactConfig
    campaigns: list[CampaignRule]
    retry: RetryConfig
    test_mode: bool = True  # safe by default: must be explicitly disabled for prod

    # ----- secrets: environment only -------------------------------------
    @staticmethod
    def secret(name: str, required: bool = True) -> str | None:
        val = os.environ.get(name)
        if required and not val:
            raise ConfigError(f"Missing required secret env var: {name}")
        return val

    def campaign_for(self, work_model: str | None) -> CampaignRule:
        wm = (work_model or "UNKNOWN").upper()
        catch_all = None
        for rule in self.campaigns:
            if not rule.when_work_model:
                catch_all = catch_all or rule
            elif wm in [w.upper() for w in rule.when_work_model]:
                return rule
        if catch_all is None:
            raise ConfigError("No catch-all Smartlead campaign configured")
        return catch_all


def load_settings(path: str | Path) -> Settings:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"Invalid config file: {path}")
    try:
        return Settings(
            icp=ICPConfig(**raw.get("icp", {})),
            intent=IntentConfig(**raw.get("intent", {})),
            contacts=ContactConfig(**raw.get("contacts", {})),
            campaigns=[CampaignRule(**c) for c in raw.get("campaigns", [])],
            retry=RetryConfig(**raw.get("retry", {})),
            test_mode=bool(raw.get("test_mode", True)),
        )
    except TypeError as e:
        raise ConfigError(f"Bad config key: {e}") from e
