"""
Live numbers for the landing page: catalogue, rules by type and source, ingested labels.
Implements GET /api/v1/stats.
"""

from collections import Counter

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.rxguard.api.dependencies import get_safety_engine, get_session_factory
from src.rxguard.api.routes.medications import load_concepts
from src.rxguard.database.models import EvidencePassageRecord
from src.rxguard.safety.engine import SafetyEngine
from src.rxguard.safety.models import AllergyRule, DCIRule, DDIRule, DFIRule

router = APIRouter(tags=["Stats"])

KIND = {DDIRule: "drug_drug", DFIRule: "drug_food", DCIRule: "drug_condition", AllergyRule: "allergy"}


class Stats(BaseModel):
    medicines: int
    medicines_with_rules: int
    rules: int
    rules_by_type: dict[str, int]
    rules_by_source: dict[str, int]
    medicines_with_labels: int
    label_passages: int


@router.get("/stats", response_model=Stats)
async def stats(
    engine: SafetyEngine = Depends(get_safety_engine),
    factory: async_sessionmaker[AsyncSession] | None = Depends(get_session_factory),
) -> Stats:
    concepts = await load_concepts(factory)
    rules = engine.repo.all_rules()
    covered = set(engine.repo.rule_drugs())
    with_labels = passages = 0
    if factory is not None:
        async with factory() as session:
            passages = await session.scalar(select(func.count()).select_from(EvidencePassageRecord)) or 0
            with_labels = (
                await session.scalar(select(func.count(func.distinct(EvidencePassageRecord.rxcui)))) or 0
            )
    return Stats(
        medicines=len(concepts),
        medicines_with_rules=sum(c.rxcui in covered for c in concepts),
        rules=len(rules),
        rules_by_type=dict(Counter(KIND[type(r)] for r in rules)),
        rules_by_source=dict(Counter(r.rule_source for r in rules)),
        medicines_with_labels=with_labels,
        label_passages=passages,
    )
