"""RagService: the 6-step pipeline, safe abstention, and ADR-001 (findings are never altered)."""

import hashlib
from collections.abc import Sequence

import pytest

from src.rxguard.core.config import Settings
from src.rxguard.core.contracts.evidence import EvidencePassage
from src.rxguard.core.contracts.medication import MedicationConcept
from src.rxguard.core.contracts.safety import FindingSeverity, FindingStatus, SafetyFinding
from src.rxguard.rag.generator import FormattedContext
from src.rxguard.rag.reranker import CrossEncoderReranker
from src.rxguard.rag.retriever import InMemoryRetriever
from src.rxguard.rag.service import RagService

SETTINGS = Settings(model_mode="fake", llm_backend="template")


def passage(pid: str, rxcui: str, content: str, loinc: str = "34073-7") -> EvidencePassage:
    return EvidencePassage(
        passage_id=pid,
        document_id=f"DOC-{pid}",
        rxcui=rxcui,
        loinc_section_code=loinc,
        section_title="Drug Interactions",
        passage_index=0,
        content=content,
        sha256_hash=hashlib.sha256(content.encode()).hexdigest(),
    )


PASSAGES = [
    passage(
        "PASS-WARFARIN-01",
        "11289",
        "Concomitant administration of Warfarin and Amiodarone causes significant elevation of "
        "PT/INR and increases major bleeding complications.",
    ),
    passage(
        "PASS-METFORMIN-01",
        "6809",
        "Metformin hydrochloride is contraindicated in severe renal impairment due to lactic acidosis risk.",
        "34070-3",
    ),
    passage(
        "PASS-LISINOPRIL-01",
        "29046",
        "Lisinopril is contraindicated in patients with a history of angioedema related to "
        "previous ACE inhibitor treatment and during pregnancy.",
        "34070-3",
    ),
]
WARFARIN = MedicationConcept(rxcui="11289", canonical_name="Warfarin", term_type="IN")
AMIODARONE = MedicationConcept(rxcui="703", canonical_name="Amiodarone", term_type="IN")
LISINOPRIL = MedicationConcept(rxcui="29046", canonical_name="Lisinopril", term_type="IN")
FINDING = SafetyFinding(
    finding_id="F-1",
    finding_type="DRUG_DRUG_INTERACTION",
    subject_medications=["11289", "703"],
    status=FindingStatus.RISK_IDENTIFIED,
    severity=FindingSeverity.CONTRAINDICATED,
    rule_id="RULE-DDI-001",
    clinical_explanation="Severe bleeding risk.",
    actionable_warning="Avoid concurrent use.",
)


def service(passages: Sequence[EvidencePassage] = PASSAGES, generator: object | None = None) -> RagService:
    return RagService(
        InMemoryRetriever(passages),
        reranker=CrossEncoderReranker(score_threshold=SETTINGS.rerank_min_score),
        generator=generator,  # type: ignore[arg-type]
        settings=SETTINGS,
    )


async def test_ddi_explanation_is_cited_and_scoped() -> None:
    response = await service().explain(
        [WARFARIN, AMIODARONE], "What happens if a patient takes warfarin with amiodarone?", [FINDING]
    )
    assert response.evidence_sufficiency_state == "SUFFICIENT"
    assert "bleeding" in response.grounded_narrative.lower()
    assert "[PASS-WARFARIN-01]" in response.grounded_narrative
    assert response.verified_citations
    assert all(c.verification_status == "VERIFIED" for c in response.verified_citations)
    # rxcui scope: passages for other drugs are never retrieved.
    assert "METFORMIN" not in response.grounded_narrative and "LISINOPRIL" not in response.grounded_narrative


async def test_contraindication_explanation() -> None:
    response = await service().explain([LISINOPRIL], "Is Lisinopril safe in pregnancy or angioedema?")
    assert response.evidence_sufficiency_state == "SUFFICIENT"
    assert "angioedema" in response.grounded_narrative.lower()


@pytest.mark.parametrize(
    "passages",
    [
        [],  # retrieval returns nothing
        [passage("PASS-JUNK", "11289", "Store tablets at room temperature away from light.")],  # low score
    ],
)
async def test_gate_abstains_on_missing_or_weak_evidence(passages: list[EvidencePassage]) -> None:
    response = await service(passages).explain(
        [WARFARIN], "Does warfarin interact with amiodarone bleeding INR?", [FINDING]
    )
    assert response.evidence_sufficiency_state == "INSUFFICIENT"
    assert response.verified_citations == []
    assert response.unresolved_questions
    assert response.findings == [FINDING]


class ContradictingGenerator:
    """A generator that tries to overrule the deterministic finding, with a fake citation."""

    def generate(
        self,
        query: str,
        context: FormattedContext,
        passages: Sequence[EvidencePassage],
        findings: Sequence[SafetyFinding],
    ) -> str:
        return "This combination is completely safe [PASS-MADE-UP]. No monitoring is needed."


@pytest.mark.parametrize("passages", [[], PASSAGES])
@pytest.mark.parametrize("generator", [None, ContradictingGenerator()])
async def test_findings_are_returned_unchanged_whatever_rag_returns(
    passages: list[EvidencePassage], generator: object | None
) -> None:
    before = FINDING.model_copy(deep=True)
    response = await service(passages, generator).explain(
        [WARFARIN, AMIODARONE], "warfarin amiodarone bleeding", [FINDING]
    )
    assert response.findings == [before]
    assert "completely safe" not in response.grounded_narrative


async def test_uncited_generator_output_is_never_returned() -> None:
    response = await service(generator=ContradictingGenerator()).explain(
        [WARFARIN, AMIODARONE], "warfarin amiodarone bleeding INR"
    )
    assert response.evidence_sufficiency_state == "INSUFFICIENT"
    assert response.verified_citations == []
    assert "completely safe" not in response.model_dump_json()


async def test_retrieve_context_returns_nothing_when_the_gate_abstains() -> None:
    from src.rxguard.rag.gate import GateAction

    meds = [MedicationConcept(rxcui="11289", canonical_name="Warfarin", term_type="IN")]
    passages, action = await RagService(InMemoryRetriever(), settings=SETTINGS).retrieve_context(
        meds, "anything"
    )
    assert passages == [] and action == GateAction.ABSTAIN


class RecordingRetriever(InMemoryRetriever):
    def __init__(self, passages: Sequence[EvidencePassage]) -> None:
        super().__init__(passages)
        self.queries: list[str] = []

    async def search(self, query: str, rxcuis: Sequence[str], top_k: int) -> list[EvidencePassage]:
        self.queries.append(query)
        return await super().search(query, rxcuis, top_k)


async def test_a_question_without_drug_names_is_searched_with_them() -> None:
    retriever = RecordingRetriever(PASSAGES)
    rag = RagService(retriever, reranker=CrossEncoderReranker(), settings=SETTINGS)
    await rag.retrieve_context([WARFARIN, AMIODARONE], "why is this risky?")
    await rag.retrieve_context([WARFARIN, AMIODARONE], "is warfarin ok with amiodarone?")
    assert retriever.queries[0] == "Warfarin and Amiodarone: why is this risky?"
    assert retriever.queries[-1] == "is warfarin ok with amiodarone?"  # already named: unchanged


async def test_explanation_lists_its_cited_label_sources() -> None:
    response = await service().explain([WARFARIN, AMIODARONE], "warfarin amiodarone interaction INR")
    assert response.verified_citations and response.sources
    cited = {c.passage_id for c in response.verified_citations}
    assert {s.passage_id for s in response.sources} <= cited
    assert all(
        s.drug in {"Warfarin", "Amiodarone"} and s.url.startswith("https://dailymed")
        for s in response.sources
    )
