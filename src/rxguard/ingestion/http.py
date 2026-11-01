"""
Resilient HTTP helper shared by the source adapters.
Retries transient failures with exponential backoff and maps responses onto
the explicit adapter failure states in :mod:`rxguard.ingestion.errors`.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import httpx

from src.rxguard.ingestion.errors import UpstreamNotFoundError, UpstreamUnavailableError

logger = logging.getLogger(__name__)

SleepFn = Callable[[float], Awaitable[None]]
BeforeRequestHook = Callable[[], Awaitable[None]]

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential backoff policy: delay = base_delay * 2**attempt, capped at max_delay."""

    max_attempts: int = 4
    base_delay: float = 0.5
    max_delay: float = 8.0

    def delay_for(self, attempt: int) -> float:
        return float(min(self.base_delay * (2**attempt), self.max_delay))


async def get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    source: str,
    params: Mapping[str, str | int] | None = None,
    policy: RetryPolicy | None = None,
    sleep: SleepFn | None = None,
    before_request: BeforeRequestHook | None = None,
) -> httpx.Response:
    """
    Performs a GET request with retries.

    Raises:
        UpstreamNotFoundError: on HTTP 404 (authoritative absence, eligible for negative caching).
        UpstreamUnavailableError: on transport errors or retryable statuses once retries are exhausted,
            and immediately on any other non-success status.
    """
    policy = policy or RetryPolicy()
    sleep = sleep or asyncio.sleep
    last_error = "no attempt made"
    for attempt in range(policy.max_attempts):
        if before_request is not None:
            await before_request()
        try:
            response = await client.get(url, params=params)
        except httpx.TransportError as exc:
            last_error = f"transport error: {exc.__class__.__name__}"
        else:
            if response.status_code == 404:
                raise UpstreamNotFoundError(source, f"404 for {url}")
            if response.is_success:
                return response
            if response.status_code not in RETRYABLE_STATUS:
                raise UpstreamUnavailableError(source, f"HTTP {response.status_code} for {url}")
            last_error = f"HTTP {response.status_code}"
        if attempt < policy.max_attempts - 1:
            delay = policy.delay_for(attempt)
            logger.warning("%s request failed (%s); retrying in %.2fs", source, last_error, delay)
            await sleep(delay)
    raise UpstreamUnavailableError(source, f"{last_error} for {url} after {policy.max_attempts} attempts")
