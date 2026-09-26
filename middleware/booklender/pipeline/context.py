"""Shared pipeline context: injected clients + infrastructure."""
from __future__ import annotations

from dataclasses import dataclass

from ..audit import AuditLog
from ..config import Settings
from ..idempotency import IdempotencyStore
from ..clients.interfaces import ApolloClient, ClayClient, SmartleadClient, ZohoClient


@dataclass
class Context:
    settings: Settings
    zoho: ZohoClient
    apollo: ApolloClient
    clay: ClayClient
    smartlead: SmartleadClient
    audit: AuditLog
    idem: IdempotencyStore
