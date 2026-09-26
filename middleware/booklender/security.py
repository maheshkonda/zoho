"""Webhook authentication.

Every inbound webhook (6sense, Clay, Zoho approval, Smartlead events) must be
signed with a per-source shared secret using HMAC-SHA256 over the raw body.
Secrets are read from environment variables only:

    WEBHOOK_SECRET_SIXSENSE
    WEBHOOK_SECRET_CLAY
    WEBHOOK_SECRET_ZOHO
    WEBHOOK_SECRET_SMARTLEAD

Header: X-BookLender-Signature: sha256=<hexdigest>
"""
from __future__ import annotations

import hashlib
import hmac
import os

SIGNATURE_HEADER = "X-BookLender-Signature"


class WebhookAuthError(Exception):
    pass


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(source: str, body: bytes, signature_header: str | None) -> None:
    """Verify an inbound webhook body against the per-source secret.

    Raises WebhookAuthError on any failure. Constant-time comparison.
    """
    env_var = f"WEBHOOK_SECRET_{source.upper()}"
    secret = os.environ.get(env_var)
    if not secret:
        raise WebhookAuthError(f"Webhook secret not configured ({env_var})")
    if not signature_header:
        raise WebhookAuthError("Missing signature header")
    expected = sign(secret, body)
    if not hmac.compare_digest(expected, signature_header):
        raise WebhookAuthError("Invalid webhook signature")
