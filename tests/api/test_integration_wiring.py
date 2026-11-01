"""
Cross-workstream wiring in the API:
- /evidence/subgraph serializes the finding's provenance in-process.
- /safety/analyze can attach a RagService grounded explanation.
PostgreSQL is replaced by an in-memory retriever through FastAPI dependency overrides.
"""

import hashlib
from collections.abc import Iterator, Sequence
from typing import Any, TypeVar

import pytest
from starlette.testclient import TestClient

from src.rxguard.api.dependencies import get_rag_service
from src.rxguard.api.main import app
from src.rxguard.core.contracts.evidence import EvidencePassage
from src.rxguard.rag.retriever import InMemoryRetriever, PostgresRetriever
from src.rxguard.rag.service import RagService

T = TypeVar("T")

WARFARIN = {"rxcui": "11289", "canonical_name": "Warfarin", "term_type": "IN"}
IBUPROFEN = {"rxcui": "5640", "canonical_name": "Ibuprofen", "term_type": "IN"}


class RecordingRetriever(InMemoryRetriever):
    def __init__(self, passages: list[EvidencePassage]) -> None:
        super().__init__(passages)
        self.scopes: list[list[str]] = []

    async def search(self, query: str, rxcuis: Sequence[str], top_k: int) -> list[EvidencePassage]:
        self.scopes.append(list(rxcuis))
        return await super().search(query, rxcuis, top_k)


def passage(passage_id: str, rxcui: str, content: str) -> EvidencePassage:
    return EvidencePassage(
        passage_id=passage_id,
        document_id=f"SPL-{rxcui}",
        rxcui=rxcui,
        loinc_section_code="34073-7",
        section_title="Drug Interactions",
        passage_index=0,
        content=content,
        sha256_hash=hashlib.sha256(content.encode()).hexdigest(),
    )


@pytest.fixture
def overrides() -> Iterator[dict[Any, Any]]:
    yield app.dependency_overrides
    app.dependency_overrides.clear()


def test_evidence_route_serializes_finding_in_process() -> None:
    assert TestClient(app).get("/api/v1/evidence/subgraph/NOPE").status_code == 404
    res = TestClient(app).get("/api/v1/evidence/subgraph/RULE-DDI-001")
    assert res.status_code == 200, res.text
    assert res.json()["finding_id"] == "RULE-DDI-001"
    assert any(n["type"] == "MEDICATION" for n in res.json()["nodes"])


def test_analyze_without_explanation_keeps_previous_shape() -> None:
    res = TestClient(app).post("/api/v1/safety/analyze", json={"medications": [WARFARIN, IBUPROFEN]})
    assert res.json()["grounded_explanation"] is None


def test_analyze_with_explanation_cites_canonical_passages(overrides: dict[Any, Any]) -> None:
    retriever = RecordingRetriever(
        [
            passage(
                "P-WARF-1",
                "11289",
                "Concomitant use of warfarin and ibuprofen increases the risk of serious gastrointestinal "
                "bleeding. Monitor INR closely.",
            )
        ]
    )
    overrides[get_rag_service] = lambda: RagService(retriever)
    res = TestClient(app).post(
        "/api/v1/safety/analyze",
        json={
            "medications": [WARFARIN, IBUPROFEN],
            "include_explanation": True,
            "clinical_question": "Can warfarin be taken with ibuprofen? What is the bleeding risk?",
        },
    )
    assert res.status_code == 200, res.text
    explanation = res.json()["grounded_explanation"]
    assert retriever.scopes[0] == ["11289", "5640"]
    assert explanation["disclaimer"]
    # Deterministic findings are carried through unchanged (ADR-001).
    assert [f["finding_id"] for f in explanation["findings"]] == [
        f["finding_id"] for f in res.json()["findings"]
    ]
    assert explanation["evidence_sufficiency_state"] == "SUFFICIENT"
    cited = {(c["passage_id"], c["verification_status"]) for c in explanation["verified_citations"]}
    assert cited == {("P-WARF-1", "VERIFIED")}


def test_analyze_explanation_abstains_without_passages() -> None:
    res = TestClient(app).post(
        "/api/v1/safety/analyze",
        json={"medications": [WARFARIN, IBUPROFEN], "include_explanation": True},
    )
    assert res.status_code == 200
    assert res.json()["grounded_explanation"]["verified_citations"] == []


def test_retriever_dependency_is_env_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.rxguard.api import dependencies

    dependencies.get_retriever.cache_clear()
    dependencies.get_session_factory.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "")  # explicit opt-out, also overriding a local .env
    assert isinstance(dependencies.get_retriever(), InMemoryRetriever)
    dependencies.get_retriever.cache_clear()
    dependencies.get_session_factory.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    assert isinstance(dependencies.get_retriever(), PostgresRetriever)
    dependencies.get_retriever.cache_clear()
    dependencies.get_session_factory.cache_clear()


def test_explain_findings_explains_server_side_findings() -> None:
    res = TestClient(app).post("/api/v1/safety/explain-findings", json={"medications": [WARFARIN, IBUPROFEN]})
    assert res.status_code == 200, res.text
    [explanation] = res.json()["explanations"]
    assert explanation["finding_id"].startswith(
        "RULE-DDI-001"
    )  # re-derived by the rules, not sent by the client
    assert explanation["text"] is None  # no label corpus in tests: nothing is invented
