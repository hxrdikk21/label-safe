"""
Search for the Check form's foods, conditions and allergies (medications live in medications.py).
Implements GET /api/v1/vocab/{foods,conditions,allergens}/search.
"""

import logging
from collections import OrderedDict

import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.rxguard.api.dependencies import get_safety_engine, get_session_factory, per_ip_limit
from src.rxguard.api.routes.medications import load_concepts
from src.rxguard.safety.build_rules import load_foods
from src.rxguard.safety.engine import SafetyEngine
from src.rxguard.safety.models import AllergyRule, DCIRule, DFIRule

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/vocab",
    tags=["Vocabulary"],
    dependencies=[per_ip_limit("search", "rate_limit_search_per_minute")],
)

NLM_ICD10_URL = "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search"
_icd_cache: OrderedDict[str, list[tuple[str, str]]] = OrderedDict()


class VocabHit(BaseModel):
    label: str
    value: str
    code: str | None = None
    unii: str | None = None
    has_rules: bool


def _rank(text: str, query: str) -> int | None:
    t = text.lower()
    if not query or t == query:
        return 0
    if t.startswith(query):
        return 1
    if query in t:
        return 2
    return None


def _top(hits: list[tuple[int, VocabHit]], limit: int) -> list[VocabHit]:
    hits.sort(key=lambda h: (h[0], not h[1].has_rules, h[1].label.lower()))
    return [h for _, h in hits[:limit]]


@router.get("/foods/search", response_model=list[VocabHit])
async def search_foods(
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=8, ge=1, le=50),
    engine: SafetyEngine = Depends(get_safety_engine),
) -> list[VocabHit]:
    rule_terms: set[str] = set()
    for rule in engine.repo.all_rules():
        if isinstance(rule, DFIRule):
            rule_terms |= {rule.food_identifier.lower(), *(a.lower() for a in rule.food_aliases)}
    names: dict[str, None] = {}
    for food in load_foods():
        names.update(dict.fromkeys([food["name"], *food.get("aliases", [])]))
    names.update(dict.fromkeys(rule_terms))
    query = q.strip().lower()
    hits = [
        (rank, VocabHit(label=name, value=name, has_rules=name.lower() in rule_terms))
        for name in names
        if (rank := _rank(name, query)) is not None
    ]
    return _top(hits, limit)


async def _icd10(query: str, limit: int) -> list[tuple[str, str]]:
    """(code, name) pairs from NLM Clinical Tables; cached; raises httpx.HTTPError when unreachable."""
    key = f"{query}|{limit}"
    if key in _icd_cache:
        _icd_cache.move_to_end(key)
        return _icd_cache[key]
    async with httpx.AsyncClient(timeout=3) as http:
        response = await http.get(NLM_ICD10_URL, params={"sf": "code,name", "terms": query, "maxList": limit})
        response.raise_for_status()
        rows = [(code, name) for code, name in response.json()[3]]
    _icd_cache[key] = rows
    if len(_icd_cache) > 512:
        _icd_cache.popitem(last=False)
    return rows


@router.get("/conditions/search", response_model=list[VocabHit])
async def search_conditions(
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=8, ge=1, le=50),
    engine: SafetyEngine = Depends(get_safety_engine),
) -> list[VocabHit]:
    """Full ICD-10-CM via NLM; the rulebook's own conditions when NLM is unreachable or q is empty."""
    rule_conditions = {
        code: rule.condition_display
        for rule in engine.repo.all_rules()
        if isinstance(rule, DCIRule)
        for code in (rule.condition_code, *rule.additional_codes)
    }

    def checked(code: str) -> bool:
        return any(code.upper().startswith(rule_code.upper()) for rule_code in rule_conditions)

    query = q.strip().lower()
    if query:
        try:
            rows = await _icd10(query, limit)
            return [
                VocabHit(label=name, value=name, code=code, has_rules=checked(code)) for code, name in rows
            ]
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            logger.warning("ICD-10 search unavailable, using rulebook conditions: %s", exc)
    hits: list[tuple[int, VocabHit]] = []
    for code, name in rule_conditions.items():
        ranks = [r for r in (_rank(name, query), _rank(code, query)) if r is not None]
        if ranks:
            hits.append((min(ranks), VocabHit(label=name, value=name, code=code, has_rules=True)))
    return _top(hits, limit)


@router.get("/allergens/search", response_model=list[VocabHit])
async def search_allergens(
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=8, ge=1, le=50),
    engine: SafetyEngine = Depends(get_safety_engine),
    factory: async_sessionmaker[AsyncSession] | None = Depends(get_session_factory),
) -> list[VocabHit]:
    """Allergy rule groups plus every active catalogue ingredient (drug allergies are checked directly)."""
    entries: dict[str, VocabHit] = {}
    for rule in engine.repo.all_rules():
        if isinstance(rule, AllergyRule):
            entries[rule.allergen_name.lower()] = VocabHit(
                label=rule.allergen_name, value=rule.allergen_name, has_rules=True
            )
    for concept in await load_concepts(factory):
        for ingredient in concept.ingredients:
            if ingredient.is_active:
                entries.setdefault(
                    ingredient.name.lower(),
                    VocabHit(
                        label=ingredient.name, value=ingredient.name, unii=ingredient.unii, has_rules=True
                    ),
                )
    query = q.strip().lower()
    hits = [(rank, hit) for hit in entries.values() if (rank := _rank(hit.label, query)) is not None]
    return _top(hits, limit)
