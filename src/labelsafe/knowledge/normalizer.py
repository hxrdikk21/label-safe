"""
Medication normalization: free-text drug strings to canonical ``MedicationConcept``.

Resolution rules:
  * Brand names (BN) and clinical/branded drugs collapse to their single active
    ingredient (IN), e.g. "Lipitor" -> atorvastatin (RxCUI 83367).
  * Multi-ingredient products resolve to the multiple-ingredient concept (MIN)
    and list every active moiety, e.g. Augmentin -> amoxicillin + clavulanate.
  * Salt-form queries (PIN) keep the precise salt and list the base moiety.
  * A bare ingredient whose marketed single-ingredient clinical drugs (SCDs)
    use more than one salt (metoprolol tartrate IR vs succinate ER), a query
    matching several distinct concepts, or an approximate (fuzzy) match is
    flagged ``is_ambiguous=True`` with all candidate RxCUIs. Hydrates and
    salts that never appear in a marketed SCD name are not treated as distinct.
"""

import re
from dataclasses import dataclass, field
from typing import Final

from src.labelsafe.core.contracts.medication import IngredientReference, MedicationConcept
from src.labelsafe.ingestion.cache_manager import CacheManager, LookupStatus
from src.labelsafe.ingestion.errors import UpstreamNotFoundError, UpstreamUnavailableError
from src.labelsafe.ingestion.rxnav import SOURCE_NAME as RXNAV_SOURCE
from src.labelsafe.ingestion.rxnav import RxConcept, RxNavClient

CACHE_SOURCE: Final = "rxnav-normalize"
MAX_BRAND_SYNONYMS: Final = 10
_BRACKETED_BRAND = re.compile(r"\[([^\]]+)\]\s*$")
_COMBINATION = " / "


class MedicationNotFoundError(UpstreamNotFoundError):
    """No RxNorm concept matches the medication query."""


@dataclass(frozen=True, slots=True)
class _Anchor:
    concept: RxConcept
    ingredients: list[RxConcept]
    brands: list[str]
    marketed_salts: list[str] = field(default_factory=list)


def normalize_query(query: str) -> str:
    return " ".join(query.split())


def single_ingredient_brands(branded_drugs: list[RxConcept]) -> list[str]:
    """Extracts brand names from single-ingredient SBD names, e.g. '... Oral Tablet [Lipitor]'."""
    brands: set[str] = set()
    for sbd in branded_drugs:
        match = _BRACKETED_BRAND.search(sbd.name)
        if match and _COMBINATION not in sbd.name:
            brands.add(match.group(1).strip())
    return sorted(brands)[:MAX_BRAND_SYNONYMS]


def marketed_salt_forms(salt_forms: list[RxConcept], clinical_drugs: list[RxConcept]) -> list[str]:
    """
    Returns the PIN RxCUIs whose name appears in at least one single-ingredient SCD name.
    The longest matching PIN wins, so 'X sodium anhydrous' does not shadow 'X sodium'.
    """
    pins = sorted(salt_forms, key=lambda p: len(p.name), reverse=True)
    used: list[str] = []
    for scd in clinical_drugs:
        name = f" {scd.name.lower()} "
        if _COMBINATION in name:
            continue
        for pin in pins:
            if f" {pin.name.lower()} " in name:
                if pin.rxcui not in used:
                    used.append(pin.rxcui)
                break
    return sorted(used)


class MedicationNormalizer:
    """Resolves user-entered medication strings to canonical concepts, cache-first."""

    def __init__(
        self,
        rxnav: RxNavClient,
        cache: CacheManager | None = None,
        *,
        allow_approximate: bool = True,
    ) -> None:
        self._rxnav = rxnav
        self._cache = cache
        self._allow_approximate = allow_approximate

    async def normalize(self, query: str, jurisdiction: str = "US") -> MedicationConcept:
        """
        Resolves a user-entered medication string to a canonical MedicationConcept.
        Checks the local PostgreSQL cache first and queries RxNav only on a cache miss.

        Raises:
            ValueError: for an empty query.
            MedicationNotFoundError: if RxNorm has no matching concept (negatively cached for 7 days).
            UpstreamUnavailableError: if RxNav is down and no local snapshot exists.
        """
        cleaned = normalize_query(query)
        if not cleaned:
            raise ValueError("medication query must not be empty")
        if self._cache is None:
            return await self.resolve(cleaned, jurisdiction)

        async def fetch() -> dict[str, object]:
            return (await self.resolve(cleaned, jurisdiction)).model_dump(mode="json")

        result = await self._cache.get_or_fetch(CACHE_SOURCE, f"{jurisdiction}:{cleaned}", fetch)
        if result.status is LookupStatus.NOT_FOUND:
            raise MedicationNotFoundError(RXNAV_SOURCE, f"no RxNorm concept for {cleaned!r}")
        if result.payload is None:
            raise UpstreamUnavailableError(RXNAV_SOURCE, result.error or f"lookup failed for {cleaned!r}")
        return MedicationConcept.model_validate(result.payload)

    async def resolve(self, query: str, jurisdiction: str = "US") -> MedicationConcept:
        """Resolves directly against RxNav, bypassing the cache."""
        approximate = False
        try:
            rxcuis = await self._rxnav.find_rxcuis(query)
        except UpstreamNotFoundError:
            if not self._allow_approximate:
                raise MedicationNotFoundError(RXNAV_SOURCE, f"no RxNorm concept for {query!r}") from None
            try:
                rxcuis = await self._rxnav.approximate_rxcuis(query)
            except UpstreamNotFoundError:
                raise MedicationNotFoundError(RXNAV_SOURCE, f"no RxNorm concept for {query!r}") from None
            approximate = True

        matched: list[RxConcept] = []
        for rxcui in rxcuis:
            try:
                matched.append(await self._rxnav.get_properties(rxcui))
            except UpstreamNotFoundError:
                continue  # Retired or non-RxNorm candidate.
        if not matched:
            raise MedicationNotFoundError(RXNAV_SOURCE, f"no active RxNorm concept for {query!r}")

        anchors: list[_Anchor] = []
        for concept in matched:
            resolved = await self._anchor(concept)
            if all(resolved.concept.rxcui != a.concept.rxcui for a in anchors):
                anchors.append(resolved)

        primary = anchors[0]
        anchor = primary.concept
        candidates = [a.concept.rxcui for a in anchors]
        is_ambiguous = approximate or len(anchors) > 1
        if not is_ambiguous and len(primary.marketed_salts) > 1:
            is_ambiguous, candidates = True, primary.marketed_salts

        typed = [] if approximate else [query]
        matched_brands = [c.name for c in matched if c.tty == "BN"]
        synonyms: list[str] = []
        for name in (*typed, *matched_brands, *primary.brands):
            if name.lower() != anchor.name.lower() and name.lower() not in {s.lower() for s in synonyms}:
                synonyms.append(name)

        return MedicationConcept(
            rxcui=anchor.rxcui,
            canonical_name=anchor.name,
            term_type=anchor.tty,
            ingredients=[await self._ingredient_reference(i) for i in primary.ingredients],
            synonyms=synonyms,
            jurisdiction=jurisdiction,
            is_ambiguous=is_ambiguous,
            ambiguity_candidates=candidates if is_ambiguous else [],
        )

    async def _anchor(self, concept: RxConcept) -> _Anchor:
        """Maps a matched concept to its canonical anchor, active ingredients and brand names."""
        if concept.tty == "IN":
            # Salt forms only matter for a bare-ingredient query; brands imply a specific salt.
            related = await self._rxnav.get_related(concept.rxcui, ["PIN", "SCD", "SBD"])
            return _Anchor(
                concept,
                [concept],
                single_ingredient_brands(related["SBD"]),
                marketed_salt_forms(related["PIN"], related["SCD"]),
            )
        if concept.tty == "PIN":
            related = await self._rxnav.get_related(concept.rxcui, ["IN", "SBD"])
            return _Anchor(concept, related["IN"], single_ingredient_brands(related["SBD"]))
        if concept.tty == "MIN":
            related = await self._rxnav.get_related(concept.rxcui, ["IN", "BN"])
            return _Anchor(
                concept, related["IN"], sorted({b.name for b in related["BN"]})[:MAX_BRAND_SYNONYMS]
            )

        related = await self._rxnav.get_related(concept.rxcui, ["IN", "MIN"])
        ingredients = related["IN"]
        brands = [concept.name] if concept.tty == "BN" else []
        if len(ingredients) == 1:
            return _Anchor(ingredients[0], ingredients, brands)
        if len(ingredients) > 1 and len(related["MIN"]) == 1:
            return _Anchor(related["MIN"][0], ingredients, brands)
        return _Anchor(concept, ingredients, brands)

    async def _ingredient_reference(self, ingredient: RxConcept) -> IngredientReference:
        unii = await self._rxnav.get_unii(ingredient.rxcui)
        # RXCUI-prefixed fallback keeps the identifier unique and visibly not a UNII.
        return IngredientReference(
            unii=unii or f"RXCUI:{ingredient.rxcui}", name=ingredient.name, is_active=True
        )
