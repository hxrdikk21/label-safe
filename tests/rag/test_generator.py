"""
Narrative generators (rag/generator.py): template (default) and Gemini-backed synthesis.
The Gemini client is a fake; no network calls are made.
"""

import hashlib
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from google import genai
from google.genai import errors, types

from src.labelsafe.core.config import Settings
from src.labelsafe.core.contracts.evidence import EvidencePassage
from src.labelsafe.core.contracts.medication import MedicationConcept
from src.labelsafe.core.contracts.safety import FindingSeverity, FindingStatus, SafetyFinding
from src.labelsafe.rag.generator import (
    ContextBuilder,
    GeminiNarrativeGenerator,
    TemplateNarrativeGenerator,
    cite_sentences,
    get_narrative_generator,
)
from src.labelsafe.rag.reranker import CrossEncoderReranker
from src.labelsafe.rag.retriever import InMemoryRetriever
from src.labelsafe.rag.service import RagService

CONTENT = "Concomitant use of warfarin and ibuprofen increases the risk of serious gastrointestinal bleeding."
PASSAGES = [
    EvidencePassage(
        passage_id="P-1",
        document_id="SPL-W",
        rxcui="11289",
        loinc_section_code="34073-7",
        section_title="Drug Interactions",
        passage_index=0,
        content=CONTENT,
        sha256_hash=hashlib.sha256(CONTENT.encode()).hexdigest(),
    )
]
FINDING = SafetyFinding(
    finding_id="F-1",
    finding_type="DRUG_DRUG_INTERACTION",
    subject_medications=["11289", "5640"],
    status=FindingStatus.RISK_IDENTIFIED,
    severity=FindingSeverity.CONTRAINDICATED,
    rule_id="RULE-DDI-001",
    clinical_explanation="Severe bleeding risk.",
    actionable_warning="Avoid concurrent use.",
)
QUERY = "Can I take warfarin with ibuprofen?"
CITED = CONTENT[:-1] + " [P-1]."


def args() -> tuple[Any, ...]:
    context = ContextBuilder().build_context(PASSAGES, [])
    return QUERY, context, PASSAGES, [FINDING]


class FakeModels:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def fake_client(result: Any) -> tuple[Any, FakeModels]:
    models = FakeModels(result)
    return SimpleNamespace(models=models), models


def reply(text: str, finish: types.FinishReason = types.FinishReason.STOP) -> Any:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text=text)]), finish_reason=finish
            )
        ]
    )


def test_template_generator_cites_every_sentence() -> None:
    assert TemplateNarrativeGenerator().generate(*args()) == CITED


def test_cite_sentences_strips_contextual_header() -> None:
    headed = PASSAGES[0].model_copy(
        update={"content": "[DRUG: warfarin] [SECTION: Drug Interactions]\nFirst point. Second point"}
    )
    assert cite_sentences(headed) == "First point [P-1]. Second point [P-1]"


def test_context_builder_budget_and_formatting() -> None:
    formatted = ContextBuilder(max_passages=2, max_characters=1000).build_context(
        PASSAGES * 3, patient_conditions=["Chronic Kidney Disease"]
    )
    assert "Chronic Kidney Disease" in formatted.context_text
    assert "EVIDENCE [P-1]" in formatted.context_text
    assert formatted.passage_count == 2


def test_gemini_generator_sends_grounded_request() -> None:
    client, models = fake_client(reply("Warfarin with ibuprofen raises bleeding risk [P-1]."))
    text = GeminiNarrativeGenerator(client=client).generate(*args())
    assert text == "Warfarin with ibuprofen raises bleeding risk [P-1]."
    call = models.calls[0]
    assert call["model"] == "gemini-3.8-flash"
    user = call["contents"]
    assert f"<user_query>{QUERY}</user_query>" in user  # untrusted text is fenced
    assert "EVIDENCE [P-1]" in user and "RULE-DDI-001" in user and "CONTRAINDICATED" in user
    assert "never contradict" in call["config"].system_instruction


@pytest.mark.parametrize(
    "result",
    [
        reply("Blocked.", finish=types.FinishReason.SAFETY),
        reply("Verbatim label text", finish=types.FinishReason.RECITATION),
        reply("Cut off mid", finish=types.FinishReason.MAX_TOKENS),
        reply("   "),
        types.GenerateContentResponse(candidates=[]),  # prompt blocked
        httpx.ConnectError("offline"),
        errors.ClientError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}}),
        errors.ServerError(500, {"error": {"message": "boom", "status": "INTERNAL"}}),
    ],
)
def test_gemini_generator_falls_back_to_template(result: Any) -> None:
    client, _ = fake_client(result)
    assert GeminiNarrativeGenerator(client=client).generate(*args()) == CITED


def test_factory_selects_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(get_narrative_generator(Settings(llm_backend="template")), TemplateNarrativeGenerator)
    created: list[dict[str, Any]] = []
    monkeypatch.setattr(genai, "Client", lambda **kw: created.append(kw) or object())
    gen = get_narrative_generator(
        Settings(llm_backend="gemini", gemini_api_key="g-test", gemini_model="gemini-3.6-flash")
    )
    assert isinstance(gen, GeminiNarrativeGenerator) and created[0]["api_key"] == "g-test"
    assert created[0]["http_options"].timeout == 30_000  # bounded wait under load
    assert gen._model == "gemini-3.6-flash"
    get_narrative_generator(Settings(llm_backend="gemini", gemini_api_key=None))
    assert "api_key" not in created[-1]  # SDK reads GEMINI_API_KEY itself


async def test_service_uses_injected_generator() -> None:
    client, models = fake_client(reply("Bleeding risk is increased [P-1]."))
    rag = RagService(
        InMemoryRetriever(PASSAGES),
        reranker=CrossEncoderReranker(),
        generator=GeminiNarrativeGenerator(client=client),
        settings=Settings(model_mode="fake"),
    )
    meds = [
        MedicationConcept(rxcui="11289", canonical_name="Warfarin", term_type="IN"),
        MedicationConcept(rxcui="5640", canonical_name="Ibuprofen", term_type="IN"),
    ]
    response = await rag.explain(
        meds, "Can warfarin be taken with ibuprofen? What is the bleeding risk?", [FINDING]
    )
    assert models.calls, "generator was not consulted"
    assert response.grounded_narrative == "Bleeding risk is increased [P-1]."
    assert response.findings == [FINDING]  # deterministic findings carried through unchanged
