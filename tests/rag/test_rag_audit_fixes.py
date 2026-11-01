"""RAG regressions from the 2026-10-28 audit: failures never cost the safety report; models load lazily."""

import importlib.util
from collections.abc import Iterator
from typing import Any

import pytest
from starlette.testclient import TestClient

from src.rxguard.api.dependencies import get_rag_service
from src.rxguard.api.main import app
from src.rxguard.core import config
from src.rxguard.rag import service as service_module
from src.rxguard.rag.retriever import InMemoryRetriever
from src.rxguard.rag.service import RagService

WARFARIN = {"rxcui": "11289", "canonical_name": "Warfarin", "term_type": "IN"}
IBUPROFEN = {"rxcui": "5640", "canonical_name": "Ibuprofen", "term_type": "IN"}


class BrokenRag:
    async def explain(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("model server down")


@pytest.fixture
def client() -> Iterator[TestClient]:
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_failed_explanation_keeps_the_safety_report(client: TestClient) -> None:
    app.dependency_overrides[get_rag_service] = BrokenRag
    res = client.post(
        "/api/v1/safety/analyze", json={"medications": [WARFARIN, IBUPROFEN], "include_explanation": True}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["highest_severity"] == "CONTRAINDICATED"
    assert body["grounded_explanation"]["evidence_sufficiency_state"] == "INSUFFICIENT"
    assert body["grounded_explanation"]["findings"] == body["findings"]


def test_rag_service_does_not_load_models_until_it_explains(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> Any:
        raise AssertionError("reranker loaded eagerly")

    monkeypatch.setattr(service_module, "get_reranker", boom)
    RagService(InMemoryRetriever())  # building it (as the safety route does) must stay cheap


def test_model_mode_defaults_to_fake_without_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL_MODE", raising=False)
    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: None if name == "sentence_transformers" else real_find_spec(name, *a),
    )
    assert config.Settings(_env_file=None).model_mode == "fake"


def test_thresholds_follow_model_mode() -> None:
    fake = config.Settings(model_mode="fake", _env_file=None)
    real = config.Settings(model_mode="real", _env_file=None)
    assert fake.rag_thresholds() == (0.20, 0.55, 0.40)
    assert real.rag_thresholds() == (0.02, 0.35, 0.05)
