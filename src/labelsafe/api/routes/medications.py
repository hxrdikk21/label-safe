"""
Medication search for the Check form.
Implements GET /api/v1/medications/search over the medication catalog.
"""

from functools import lru_cache

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.labelsafe.api.dependencies import get_safety_engine, get_session_factory, per_ip_limit
from src.labelsafe.core.contracts.medication import MedicationConcept
from src.labelsafe.database.models import MedicationConceptRecord
from src.labelsafe.ingestion.seed_loader import load_catalog
from src.labelsafe.safety.engine import SafetyEngine

router = APIRouter(prefix="/medications", tags=["Medications"])


class MedicationHit(BaseModel):
    concept: MedicationConcept
    has_rules: bool


@lru_cache
def seed_concepts() -> tuple[MedicationConcept, ...]:
    return tuple(entry.concept for entry in load_catalog().concepts)


async def load_concepts(factory: async_sessionmaker[AsyncSession] | None) -> list[MedicationConcept]:
    """The seeded `medication_concepts` table when configured, else the seed catalog file."""
    if factory is None:
        return list(seed_concepts())
    # shortcut: loads the whole table (~500 rows) and filters in Python; move to SQL ILIKE if it grows.
    async with factory() as session:
        concepts = [record.to_contract() for record in await session.scalars(select(MedicationConceptRecord))]
    return concepts or list(seed_concepts())


def match_rank(concept: MedicationConcept, query: str) -> int | None:
    """0 exact, 1 prefix, 2 substring match on the name or a brand synonym; None if no match."""
    names = [n.lower() for n in (concept.canonical_name, *concept.synonyms)]
    if query in names:
        return 0
    if any(n.startswith(query) for n in names):
        return 1
    if any(query in n for n in names):
        return 2
    return None


@router.get(
    "/search",
    response_model=list[MedicationHit],
    summary="Search medications by name or brand",
    dependencies=[per_ip_limit("search", "rate_limit_search_per_minute")],
)
async def search_medications(
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
    factory: async_sessionmaker[AsyncSession] | None = Depends(get_session_factory),
    safety_engine: SafetyEngine = Depends(get_safety_engine),
) -> list[MedicationHit]:
    """Catalog drugs plus any drug named only in the safety rules; drugs with rules rank first on ties."""
    rule_drugs = safety_engine.repo.rule_drugs()
    concepts = await load_concepts(factory)
    known = {c.rxcui for c in concepts}
    concepts += [
        MedicationConcept(rxcui=rxcui, canonical_name=name.lower(), term_type="IN")
        for rxcui, name in rule_drugs.items()
        if name and rxcui not in known
    ]

    query = q.strip().lower()
    scored = []
    for order, concept in enumerate(concepts):
        rank = match_rank(concept, query) if query else 0
        if rank is not None:
            scored.append((rank, concept.rxcui not in rule_drugs, order, concept))
    scored.sort(key=lambda s: s[:3])
    return [MedicationHit(concept=c, has_rules=c.rxcui in rule_drugs) for *_, c in scored[:limit]]
