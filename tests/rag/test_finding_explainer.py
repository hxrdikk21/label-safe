"""Every safety finding is explained from its own label passages: one Gemini call, cited, with a fallback."""

import hashlib
import json

import pytest

from src.labelsafe.core.contracts.evidence import EvidencePassage
from src.labelsafe.core.contracts.medication import MedicationConcept
from src.labelsafe.core.contracts.safety import FindingSeverity, FindingStatus, SafetyFinding
from src.labelsafe.rag.finding_explainer import MAX_EXPLAINED, FindingExplainer, finding_question
from src.labelsafe.safety.rules_db import SafetyRulesRepository

WARFARIN = MedicationConcept(rxcui="11289", canonical_name="warfarin", term_type="IN")
IBUPROFEN = MedicationConcept(rxcui="5640", canonical_name="ibuprofen", term_type="IN")
NAMES = {"11289": "warfarin", "5640": "ibuprofen"}


def passage(pid: str, rxcui: str, text: str) -> EvidencePassage:
    return EvidencePassage(
        passage_id=pid,
        document_id=f"SET-{rxcui}",
        rxcui=rxcui,
        loinc_section_code="34073-7",
        section_title="DRUG INTERACTIONS",
        passage_index=0,
        content=text,
        sha256_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def finding(fid: str, kind: str = "DRUG_DRUG_INTERACTION", severity: str = "MAJOR", meds=("11289", "5640")):  # type: ignore[no-untyped-def]
    return SafetyFinding(
        finding_id=fid,
        finding_type=kind,
        subject_medications=list(meds),
        status=FindingStatus.RISK_IDENTIFIED,
        severity=FindingSeverity(severity),
        clinical_explanation="Bleeding risk.",
        actionable_warning="Avoid.",
    )


class FakeRag:
    def __init__(self, passages_by_word: dict[str, list[EvidencePassage]]) -> None:
        self.passages_by_word = passages_by_word
        self.questions: list[str] = []

    async def retrieve_context(self, medications, question):  # type: ignore[no-untyped-def]
        self.questions.append(question)
        hits = [p for word, ps in self.passages_by_word.items() if word in question for p in ps]
        return hits, None


class FakeChat:
    def __init__(self, text: str | None) -> None:
        self.text = text
        self.calls = 0

    def reply(self, system, history, message, json_output=False, fast=False):  # type: ignore[no-untyped-def]
        self.calls += 1
        assert json_output and fast
        return self.text


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    from src.labelsafe.rag import finding_explainer

    finding_explainer._written_cache.clear()


def explainer(rag: FakeRag, chat: FakeChat | None) -> FindingExplainer:
    return FindingExplainer(rag, SafetyRulesRepository(), chat)  # type: ignore[arg-type]


def test_questions_name_the_drugs_and_what_they_clash_with() -> None:
    repo = SafetyRulesRepository()
    assert finding_question(finding("R|11289+5640"), NAMES, repo).startswith(
        "warfarin and ibuprofen interaction"
    )
    food = finding("R|11289|grapefruit", "DRUG_FOOD_INTERACTION", meds=("11289",))
    assert finding_question(food, NAMES, repo) == "warfarin with grapefruit: food interaction"
    allergy = finding("ALLERGY|5640|nsaids", "ALLERGY_EXCIPIENT", meds=("5640",))
    assert finding_question(allergy, NAMES, repo) == "ibuprofen allergy hypersensitivity nsaids"


async def test_one_gemini_call_explains_every_finding_with_its_own_citations() -> None:
    rag = FakeRag(
        {
            "interaction": [passage("P-DDI", "11289", "NSAIDs increase bleeding.")],
            "grapefruit": [passage("P-FOOD", "11289", "Avoid grapefruit juice.")],
        }
    )
    chat = FakeChat(
        json.dumps(
            [
                {
                    "finding_id": "R1|11289+5640",
                    "explanation": "Together they raise bleeding risk [P-DDI]. Also [P-FOOD].",
                },
                {
                    "finding_id": "R2|11289|grapefruit",
                    "explanation": "Grapefruit changes warfarin levels [P-FOOD].",
                },
            ]
        )
    )
    findings = [
        finding("R1|11289+5640"),
        finding("R2|11289|grapefruit", "DRUG_FOOD_INTERACTION", meds=("11289",)),
    ]
    out = {e.finding_id: e for e in await explainer(rag, chat).explain(findings, [WARFARIN, IBUPROFEN])}
    assert chat.calls == 1
    ddi = out["R1|11289+5640"]
    assert (
        ddi.mode == "gemini" and "[P-DDI]" in ddi.text and "[P-FOOD]" not in ddi.text
    )  # other finding's passage
    assert [s.passage_id for s in ddi.sources] == ["P-DDI"]
    assert out["R2|11289|grapefruit"].sources[0].drug == "warfarin"


async def test_invalid_json_or_no_gemini_quotes_the_label_sentences_about_the_pair() -> None:
    text = "Warfarin is an anticoagulant. Ibuprofen increases bleeding with warfarin. Monitor INR."
    rag = FakeRag({"interaction": [passage("P-DDI", "11289", text)]})
    for chat in (FakeChat("not json"), None):
        [e] = await explainer(rag, chat).explain([finding("R1|11289+5640")], [WARFARIN, IBUPROFEN])
        # The warfarin label's sentence naming ibuprofen is chosen over the label's opening line.
        assert e.mode == "offline" and e.text == "Ibuprofen increases bleeding with warfarin [P-DDI]."


async def test_offline_without_a_sentence_about_the_pair_quotes_nothing() -> None:
    rag = FakeRag({"interaction": [passage("P", "11289", "Warfarin is an anticoagulant. Take it daily.")]})
    [e] = await explainer(rag, None).explain([finding("R1|11289+5640")], [WARFARIN, IBUPROFEN])
    assert e.text is None and e.sources == []


async def test_no_label_text_means_no_explanation_and_no_llm_call() -> None:
    chat = FakeChat("[]")
    [e] = await explainer(FakeRag({}), chat).explain([finding("R1|11289+5640")], [WARFARIN, IBUPROFEN])
    assert e.text is None and e.sources == [] and chat.calls == 0


async def test_only_the_most_severe_findings_are_explained() -> None:
    rag = FakeRag({"interaction": [passage("P", "11289", "Ibuprofen raises bleeding with warfarin.")]})
    findings = [finding(f"M{i}|11289+5640", severity="MINOR") for i in range(MAX_EXPLAINED)]
    findings.append(finding("C|11289+5640", severity="CONTRAINDICATED"))
    out = {e.finding_id: e for e in await explainer(rag, None).explain(findings, [WARFARIN, IBUPROFEN])}
    assert out["C|11289+5640"].text is not None
    assert sum(e.text is None for e in out.values()) == 1  # one MINOR left unexplained


def test_model_inference_never_runs_concurrently() -> None:
    """Parallel retrievals crashed the process when PyTorch ran in two threads at once."""
    import threading
    import time

    from src.labelsafe.rag.reranker import TransformerCrossEncoderReranker
    from src.labelsafe.vector_store.embeddings import SentenceTransformerEmbeddingEngine

    active, peak = 0, 0
    guard = threading.Lock()

    class Model:
        def get_sentence_embedding_dimension(self) -> int:
            return 2

        def _run(self, n: int) -> list:  # type: ignore[type-arg]
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with guard:
                active -= 1
            return [[1.0, 0.0]] * n

        def encode(self, texts, normalize_embeddings=True):  # type: ignore[no-untyped-def]
            return self._run(len(texts))

        def predict(self, pairs):  # type: ignore[no-untyped-def]
            return [0.5 for _ in self._run(len(pairs))]

    engine = SentenceTransformerEmbeddingEngine(model=Model())
    reranker = TransformerCrossEncoderReranker(model=Model())
    p = passage("P", "1", "text")
    threads = [threading.Thread(target=engine.embed_text, args=("q",)) for _ in range(4)]
    threads += [threading.Thread(target=reranker.rerank, args=("q", [p])) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 1


async def test_the_same_check_again_reuses_the_explanation_without_calling_gemini() -> None:
    rag = FakeRag({"interaction": [passage("P-DDI", "11289", "NSAIDs increase bleeding.")]})
    chat = FakeChat(json.dumps([{"finding_id": "R1|11289+5640", "explanation": "Bleeding risk [P-DDI]."}]))
    for _ in range(3):
        [e] = await explainer(rag, chat).explain([finding("R1|11289+5640")], [WARFARIN, IBUPROFEN])
        assert e.mode == "gemini"
    assert chat.calls == 1
