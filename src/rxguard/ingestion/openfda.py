"""
openFDA drug labeling adapter.

Every request (including retries) passes through a rate limiter capped at
240 requests per rolling minute, and incoming label records are deduplicated
against DailyMed SetIDs and previously seen SHA-256 content fingerprints.
"""

import asyncio
import logging
import re
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import httpx
from pydantic import HttpUrl

from src.rxguard.core.contracts.document import SourceDocument
from src.rxguard.core.contracts.evidence import EvidencePassage
from src.rxguard.core.contracts.product import DrugProduct
from src.rxguard.ingestion.dailymed import (
    CHUNK_VERSION,
    DEFAULT_MAX_PASSAGE_CHARS,
    build_contextual_header,
    pack_blocks,
    pack_with_header,
)
from src.rxguard.ingestion.errors import UpstreamUnavailableError
from src.rxguard.ingestion.hashing import fingerprint_json, fingerprint_text, stable_uuid
from src.rxguard.ingestion.http import RetryPolicy, SleepFn, get_with_retry
from src.rxguard.knowledge.loinc_taxonomy import INACTIVE_INGREDIENTS, TARGET_SECTIONS

logger = logging.getLogger(__name__)

SOURCE_NAME: Final = "openFDA"
DEFAULT_BASE_URL: Final = "https://api.fda.gov/drug/label.json"
MAX_REQUESTS_PER_MINUTE: Final = 240
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.;:])\s+(?=[A-Z0-9(•])")


class SlidingWindowRateLimiter:
    """
    Admits at most ``max_requests`` within any rolling ``period`` seconds.

    A sliding-window log is used rather than a classic token bucket because a
    bucket with a full 240-token burst can admit up to 480 requests inside a
    single 60-second window, which would breach openFDA's per-minute quota.
    """

    def __init__(
        self,
        max_requests: int = MAX_REQUESTS_PER_MINUTE,
        period: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        if max_requests < 1 or period <= 0:
            raise ValueError("max_requests must be >= 1 and period > 0")
        self.max_requests = max_requests
        self.period = period
        self._clock = clock
        self._sleep = sleep
        self._dispatched: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Waits until a request slot is free, then claims it."""
        async with self._lock:
            while True:
                now = self._clock()
                while self._dispatched and self._dispatched[0] <= now - self.period:
                    self._dispatched.popleft()
                if len(self._dispatched) < self.max_requests:
                    self._dispatched.append(now)
                    return
                await self._sleep(self._dispatched[0] + self.period - now)


def label_fingerprint(record: dict[str, Any]) -> str:
    """SHA-256 fingerprint over a label's identity and clinically indexed section text."""
    sections = {s.openfda_field: record.get(s.openfda_field, []) for s in TARGET_SECTIONS}
    return fingerprint_json(
        {"set_id": record.get("set_id"), "version": record.get("version"), "sections": sections}
    )


class LabelDeduplicator:
    """Drops openFDA records already covered by DailyMed or already seen in this or earlier runs."""

    def __init__(self, dailymed_setids: Iterable[str] = (), known_fingerprints: Iterable[str] = ()) -> None:
        self.dailymed_setids = set(dailymed_setids)
        self.seen_fingerprints = set(known_fingerprints)

    def accept(self, record: dict[str, Any]) -> bool:
        """Returns True (and remembers the record) if it is new; False if it is a duplicate."""
        set_id = record.get("set_id")
        if set_id in self.dailymed_setids:
            logger.debug("openFDA record %s skipped: SetID already sourced from DailyMed", set_id)
            return False
        fingerprint = label_fingerprint(record)
        if fingerprint in self.seen_fingerprints:
            logger.debug("openFDA record %s skipped: duplicate fingerprint", set_id)
            return False
        self.seen_fingerprints.add(fingerprint)
        return True


@dataclass(slots=True)
class ParsedOpenFDALabel:
    """Canonical objects derived from a single openFDA label record."""

    fingerprint: str
    set_id: str
    document: SourceDocument
    passages: list[EvidencePassage]
    products: list[DrugProduct]
    missing_excipient_data: bool


def _first(values: Any, default: str = "") -> str:
    if isinstance(values, list) and values:
        return str(values[0])
    return default


def _split_long_block(block: str, max_chars: int) -> list[str]:
    if len(block) <= max_chars:
        return [block]
    return pack_blocks([s for s in _SENTENCE_BOUNDARY.split(block) if s.strip()], max_chars)


def parse_openfda_label(
    record: dict[str, Any],
    *,
    rxcui: str,
    jurisdiction: str = "US",
    max_passage_chars: int = DEFAULT_MAX_PASSAGE_CHARS,
    retrieved_at: datetime | None = None,
) -> ParsedOpenFDALabel:
    """Converts an openFDA label record into canonical contracts."""
    record_id = record.get("id")
    set_id = record.get("set_id")
    if not record_id or not set_id:
        raise UpstreamUnavailableError(SOURCE_NAME, "label record missing id or set_id")
    version = str(record.get("version") or "1")
    document_id = f"openfda:{record_id}"
    meta: dict[str, Any] = record.get("openfda") or {}
    brand = _first(meta.get("brand_name"))
    generic = _first(meta.get("generic_name"))
    effective = str(record.get("effective_time") or "")
    fingerprint = label_fingerprint(record)

    document = SourceDocument(
        document_id=document_id,
        source_name=SOURCE_NAME,
        source_url=HttpUrl(f"{DEFAULT_BASE_URL}?search=id:{record_id}"),
        version=version,
        effective_date=(
            f"{effective[0:4]}-{effective[4:6]}-{effective[6:8]}"
            if len(effective) >= 8 and effective[:8].isdigit()
            else None
        ),
        title=" ".join(p for p in (brand, f"({generic})" if generic else "") if p) or document_id,
        sha256_hash=fingerprint,
        jurisdiction=jurisdiction,
        rxcui_primary=rxcui,
        retrieval_timestamp=retrieved_at or datetime.now(UTC),
    )

    passages: list[EvidencePassage] = []
    for section in TARGET_SECTIONS:
        texts = record.get(section.openfda_field) or []
        header = build_contextual_header(generic or brand or document_id, section.title, section.code, rxcui)
        blocks = [
            piece
            for text in texts
            if isinstance(text, str) and text.strip()
            for piece in _split_long_block(" ".join(text.split()), max_passage_chars - len(header))
        ]
        for index, content in enumerate(pack_with_header(blocks, header, max_passage_chars)):
            passages.append(
                EvidencePassage(
                    passage_id=str(
                        stable_uuid(document_id, version, section.code, str(index), CHUNK_VERSION)
                    ),
                    document_id=document_id,
                    rxcui=rxcui,
                    loinc_section_code=section.code,
                    section_title=section.title,
                    passage_index=index,
                    content=content,
                    token_count=len(content.split()),
                    sha256_hash=fingerprint_text(content),
                    chunk_version=CHUNK_VERSION,
                )
            )

    products = [
        DrugProduct(
            ndc=ndc,
            rxcui=rxcui,
            brand_name=brand or generic or ndc,
            generic_name=generic or brand or ndc,
            dosage_form=_first(meta.get("dosage_form"), "UNKNOWN"),
            route=_first(meta.get("route"), "UNKNOWN"),
            strength="UNKNOWN",
            spl_setid=str(set_id),
            active_ingredient_uniis=[str(u) for u in meta.get("unii", [])],
            marketing_status="OTC" if "OTC" in _first(meta.get("product_type")).upper() else "Prescription",
            jurisdiction=jurisdiction,
        )
        for ndc in (str(n) for n in meta.get("product_ndc", []))
    ]
    has_excipients = any(p.loinc_section_code == INACTIVE_INGREDIENTS.code for p in passages)
    return ParsedOpenFDALabel(
        fingerprint=fingerprint,
        set_id=str(set_id),
        document=document,
        passages=passages,
        products=products,
        missing_excipient_data=not has_excipients,
    )


class OpenFDAClient:
    """Async client for the openFDA drug labeling endpoint."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        rate_limiter: SlidingWindowRateLimiter | None = None,
        retry_policy: RetryPolicy | None = None,
        sleep: SleepFn | None = None,
    ) -> None:
        self._client = client
        self._base_url = base_url
        self._api_key = api_key
        self.rate_limiter = rate_limiter or SlidingWindowRateLimiter()
        self._policy = retry_policy or RetryPolicy()
        self._sleep = sleep

    async def search_labels(self, search: str, *, limit: int = 10, skip: int = 0) -> list[dict[str, Any]]:
        """Runs an openFDA search query. Raises UpstreamNotFoundError when openFDA reports no matches."""
        params: dict[str, str | int] = {"search": search, "limit": limit, "skip": skip}
        if self._api_key:
            params["api_key"] = self._api_key
        response = await get_with_retry(
            self._client,
            self._base_url,
            source=SOURCE_NAME,
            params=params,
            policy=self._policy,
            before_request=self.rate_limiter.acquire,
            sleep=self._sleep,
        )
        try:
            payload = response.json()
            results = payload["results"]
        except (ValueError, KeyError, TypeError) as exc:
            raise UpstreamUnavailableError(SOURCE_NAME, f"malformed payload: {exc}") from exc
        if not isinstance(results, list):
            raise UpstreamUnavailableError(SOURCE_NAME, "results is not a list")
        return [r for r in results if isinstance(r, dict)]

    async def fetch_labels_for_generic(
        self,
        generic_name: str,
        *,
        rxcui: str,
        deduplicator: LabelDeduplicator,
        limit: int = 10,
        jurisdiction: str = "US",
    ) -> list[ParsedOpenFDALabel]:
        """Fetches labels for a generic name and returns only records the deduplicator accepts."""
        safe_name = generic_name.replace('"', "")
        records = await self.search_labels(f'openfda.generic_name:"{safe_name}"', limit=limit)
        return [
            parse_openfda_label(record, rxcui=rxcui, jurisdiction=jurisdiction)
            for record in records
            if deduplicator.accept(record)
        ]
