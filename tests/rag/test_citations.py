"""Deterministic citation check: only sentences citing a retrieved passage survive."""

from src.labelsafe.rag.citations import check_citations

RETRIEVED = {"P-1", "P-2"}


def test_cited_sentences_are_verified() -> None:
    text, citations = check_citations("Bleeding risk rises [P-1]. INR must be monitored [P-2].", RETRIEVED)
    assert text == "Bleeding risk rises [P-1]. INR must be monitored [P-2]."
    assert [c.passage_id for c in citations] == ["P-1", "P-2"]
    assert {c.verification_status for c in citations} == {"VERIFIED"}
    assert {c.entailment_score for c in citations} == {1.0}


def test_uncited_and_unknown_citations_are_removed() -> None:
    text, citations = check_citations(
        "Bleeding risk rises [P-1]. It is otherwise safe. Monitoring is optional [P-9].", RETRIEVED
    )
    assert text == "Bleeding risk rises [P-1]."
    assert [c.verification_status for c in citations] == ["VERIFIED", "UNVERIFIED", "UNVERIFIED"]
    assert citations[1].passage_id == "NONE" and citations[2].passage_id == "P-9"


def test_one_unknown_id_fails_the_whole_sentence() -> None:
    text, citations = check_citations("Bleeding risk rises [P-1][P-404].", RETRIEVED)
    assert text == "" and citations[0].verification_status == "UNVERIFIED"


def test_contextual_header_brackets_are_not_citations() -> None:
    text, _ = check_citations("[DRUG: warfarin] [SECTION: Drug Interactions] Bleeding risk.", RETRIEVED)
    assert text == ""
