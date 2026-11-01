"""
NIH NLM RxNav (RxNorm) REST client.

Thin, typed wrappers over the RxNav endpoints used for terminology
normalization: exact/normalized name lookup, approximate matching,
concept properties, related concepts by term type, and UNII codes.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

import httpx

from src.labelsafe.ingestion.errors import UpstreamNotFoundError, UpstreamUnavailableError
from src.labelsafe.ingestion.http import RetryPolicy, SleepFn, get_with_retry

SOURCE_NAME: Final = "RxNav"
DEFAULT_BASE_URL: Final = "https://rxnav.nlm.nih.gov/REST"


@dataclass(frozen=True, slots=True)
class RxConcept:
    """An RxNorm concept as returned by RxNav."""

    rxcui: str
    name: str
    tty: str


class RxNavClient:
    """Async client for the RxNav REST API."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str = DEFAULT_BASE_URL,
        retry_policy: RetryPolicy | None = None,
        sleep: SleepFn | None = None,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._policy = retry_policy or RetryPolicy()
        self._sleep = sleep

    async def _get_json(self, path: str, params: dict[str, str | int] | None = None) -> dict[str, Any]:
        response = await get_with_retry(
            self._client,
            f"{self._base_url}/{path}",
            source=SOURCE_NAME,
            params=params,
            policy=self._policy,
            sleep=self._sleep,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamUnavailableError(SOURCE_NAME, f"non-JSON response for {path}") from exc
        if not isinstance(payload, dict):
            raise UpstreamUnavailableError(SOURCE_NAME, f"unexpected payload for {path}")
        return payload

    async def find_rxcuis(self, name: str) -> list[str]:
        """
        Resolves a drug string to RxCUIs using RxNorm normalized matching (search=2).
        Raises UpstreamNotFoundError if RxNorm has no matching concept.
        """
        payload = await self._get_json("rxcui.json", {"name": name, "search": 2})
        ids = (payload.get("idGroup") or {}).get("rxnormId") or []
        if not ids:
            raise UpstreamNotFoundError(SOURCE_NAME, f"no RxCUI for {name!r}")
        return [str(i) for i in ids]

    async def approximate_rxcuis(self, term: str, *, max_entries: int = 5) -> list[str]:
        """Returns distinct RxCUIs from approximate (fuzzy) matching, best first."""
        payload = await self._get_json("approximateTerm.json", {"term": term, "maxEntries": max_entries})
        candidates = (payload.get("approximateGroup") or {}).get("candidate") or []
        ordered: list[str] = []
        for candidate in candidates:
            rxcui = str(candidate.get("rxcui") or "")
            if rxcui and rxcui not in ordered:
                ordered.append(rxcui)
        if not ordered:
            raise UpstreamNotFoundError(SOURCE_NAME, f"no approximate match for {term!r}")
        return ordered

    async def get_properties(self, rxcui: str) -> RxConcept:
        """Returns name and term type for an RxCUI."""
        payload = await self._get_json(f"rxcui/{rxcui}/properties.json")
        props = payload.get("properties")
        if not props:
            raise UpstreamNotFoundError(SOURCE_NAME, f"RxCUI {rxcui} has no properties")
        return RxConcept(rxcui=str(props["rxcui"]), name=str(props["name"]), tty=str(props["tty"]))

    async def get_related(self, rxcui: str, ttys: Iterable[str]) -> dict[str, list[RxConcept]]:
        """Returns related concepts grouped by term type (e.g. IN, PIN, MIN, BN)."""
        wanted = list(ttys)
        payload = await self._get_json(f"rxcui/{rxcui}/related.json", {"tty": " ".join(wanted)})
        grouped: dict[str, list[RxConcept]] = {tty: [] for tty in wanted}
        for group in (payload.get("relatedGroup") or {}).get("conceptGroup") or []:
            tty = str(group.get("tty", ""))
            for prop in group.get("conceptProperties") or []:
                grouped.setdefault(tty, []).append(
                    RxConcept(rxcui=str(prop["rxcui"]), name=str(prop["name"]), tty=tty)
                )
        return grouped

    async def get_unii(self, rxcui: str) -> str | None:
        """Returns the FDA UNII for an ingredient RxCUI, or None if RxNorm carries no UNII."""
        try:
            payload = await self._get_json(f"rxcui/{rxcui}/property.json", {"propName": "UNII_CODE"})
        except UpstreamNotFoundError:
            return None
        concepts = (payload.get("propConceptGroup") or {}).get("propConcept") or []
        for concept in concepts:
            if concept.get("propName") == "UNII_CODE" and concept.get("propValue"):
                return str(concept["propValue"])
        return None
