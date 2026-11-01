"""
Evidence Navigator REST routes.
Implements GET /api/v1/evidence/subgraph/{finding_id}.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.rxguard.api.dependencies import get_safety_engine, get_session_factory
from src.rxguard.api.routes.medications import load_concepts
from src.rxguard.core.contracts.evidence import EvidencePassage
from src.rxguard.database.passage_repository import PassageRepository
from src.rxguard.evidence.navigator import (
    EvidenceNavigatorSerializer,
    EvidenceProvenanceGraph,
    select_passages,
)
from src.rxguard.safety.engine import SafetyEngine

router = APIRouter(prefix="/evidence", tags=["Evidence Navigator"])


@router.get(
    "/subgraph/{finding_id}",
    response_model=EvidenceProvenanceGraph,
    summary="Retrieve Cytoscape/NetworkX-compatible provenance subgraph for a clinical finding",
)
async def get_evidence_subgraph(
    finding_id: str,
    safety_engine: SafetyEngine = Depends(get_safety_engine),
    factory: async_sessionmaker[AsyncSession] | None = Depends(get_session_factory),
) -> EvidenceProvenanceGraph:
    """Finding -> medicines and ingredients -> rule -> FDA label passages -> DailyMed documents."""
    finding = safety_engine.get_finding_by_id(finding_id)
    if not finding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Safety finding '{finding_id}' not found in active session cache",
        )
    rule = safety_engine.repo.get_rule(finding.rule_id) if finding.rule_id else None
    concepts = {c.rxcui: c for c in await load_concepts(factory)}
    passages: list[EvidencePassage] = []
    if factory is not None:
        repo = PassageRepository(factory)
        by_rxcui = {rxcui: await repo.get_passages_by_rxcui(rxcui) for rxcui in finding.subject_medications}
        passages = select_passages(finding, rule, concepts, by_rxcui)
    return EvidenceNavigatorSerializer.serialize_finding_subgraph(finding, passages, rule, concepts)
