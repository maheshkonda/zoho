"""Retry with exponential backoff.

Retryable:      HTTP 429, 500, 502, 503, 504, network/timeout errors.
Non-retryable:  validation errors, auth failures (401/403), 4xx business
                errors, and anything raised as PermanentError.
"""
from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class IntegrationError(Exception):
    """Base error for any external API failure."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code

    @property
    def retryable(self) -> bool:
        return self.status_code is None or self.status_code in RETRYABLE_STATUS


class PermanentError(IntegrationError):
    """Never retried: invalid email, opted-out contact, auth failure, malformed request."""

    @property
    def retryable(self) -> bool:
        return False


def with_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 4,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> T:
    """Run ``fn``; retry transient failures with exponential backoff (2s, 4s, 8s...)."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except IntegrationError as e:
            if not e.retryable or attempt >= max_attempts:
                raise
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            if on_retry:
                on_retry(attempt, e)
            sleep(delay)
