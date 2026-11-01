"""
Step 6 of the RAG pipeline: deterministic citation check (no NLI model).

Every factual sentence must cite a ``[passage_id]`` that was actually retrieved. Sentences that
cite nothing, or cite an unknown passage, are dropped from the narrative and recorded as UNVERIFIED.
"""

import re
from collections.abc import Collection, Mapping, Sequence

from src.labelsafe.core.contracts.evidence import EvidencePassage
from src.labelsafe.core.contracts.rag_response import LabelSource, VerifiedCitation
from src.labelsafe.ingestion.dailymed import LABEL_URL_TEMPLATE

# Passage ids have no spaces or colons, so contextual headers like "[DRUG: warfarin]" never match.
_CITATION = re.compile(r"\[([A-Za-z0-9_\-]+)\]")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_HEADER = re.compile(r"^(\[[A-Z]+: [^\]]*\]\s*)+")


def strip_unknown_citations(text: str, passage_ids: Collection[str]) -> str:
    """Removes ``[id]`` markers that don't name one of ``passage_ids`` (invented or from elsewhere)."""
    return re.sub(
        r"\s*\[([A-Za-z0-9_\-]+)\]", lambda m: m.group(0) if m.group(1) in passage_ids else "", text
    ).strip()


def label_sources(
    text: str, passages: Sequence[EvidencePassage], names: Mapping[str, str]
) -> list[LabelSource]:
    """The retrieved passages ``text`` cites, in order of first citation, as displayable sources."""
    by_id = {p.passage_id: p for p in passages}
    cited = [pid for pid in dict.fromkeys(_CITATION.findall(text)) if pid in by_id]
    return [
        LabelSource(
            passage_id=pid,
            drug=names.get(by_id[pid].rxcui, by_id[pid].rxcui),
            section=by_id[pid].section_title,
            quote=_HEADER.sub("", by_id[pid].content).strip()[:300],
            url=LABEL_URL_TEMPLATE.format(setid=by_id[pid].document_id),
        )
        for pid in cited
    ]


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if len(s.strip()) > 3]


def check_citations(narrative: str, retrieved_ids: Collection[str]) -> tuple[str, list[VerifiedCitation]]:
    """Returns the narrative reduced to verified sentences, plus one citation record per sentence."""
    kept: list[str] = []
    citations: list[VerifiedCitation] = []
    for idx, sentence in enumerate(split_sentences(narrative), start=1):
        cited = _CITATION.findall(sentence)
        verified = bool(cited) and all(pid in retrieved_ids for pid in cited)
        if verified:
            kept.append(sentence)
        citations.append(
            VerifiedCitation(
                citation_id=f"CITE-{idx:03d}",
                passage_id=cited[0] if cited else "NONE",
                cited_sentence=sentence,
                entailment_score=1.0 if verified else 0.0,
                verification_status="VERIFIED" if verified else "UNVERIFIED",
            )
        )
    return " ".join(kept), citations
