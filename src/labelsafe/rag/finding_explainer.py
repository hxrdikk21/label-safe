"""
RAG for every safety check: each rule finding is explained from its own FDA label passages.

1. Per finding, a retrieval question names the drugs and what they clash with (food, condition,
   allergen), searched with ``RagService.retrieve_context`` (hybrid search, rerank, relevance gate).
2. One Gemini call (JSON) explains all findings at once: free-tier quotas allow few calls per minute.
3. Each explanation keeps only citations to its own finding's passages and lists them as sources.
Without Gemini, or if it fails, a finding gets the first sentences of its best passage, quoted and cited.
The findings themselves are never changed (ADR-001): this only explains them.
"""

import asyncio
import json
import logging
from collections import OrderedDict
from collections.abc import Sequence

from pydantic import BaseModel, TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool

from src.labelsafe.core.contracts.evidence import EvidencePassage
from src.labelsafe.core.contracts.medication import MedicationConcept
from src.labelsafe.core.contracts.rag_response import FindingExplanation
from src.labelsafe.core.contracts.safety import SafetyFinding
from src.labelsafe.rag.citations import label_sources, split_sentences, strip_unknown_citations
from src.labelsafe.rag.generator import GeminiChat, cite_sentences
from src.labelsafe.rag.service import RagService
from src.labelsafe.safety.models import DCIRule, DFIRule
from src.labelsafe.safety.rules_db import SafetyRulesRepository, mentions

logger = logging.getLogger(__name__)

MAX_EXPLAINED = 8  # most severe first; bounds prompt size and keeps it to one LLM call
CACHE_SIZE = 256
# Gemini explanations by (finding, passages) set: the same check again costs no LLM call or quota.
_written_cache: OrderedDict[tuple[tuple[str, tuple[str, ...]], ...], dict[str, str]] = OrderedDict()
PASSAGES_PER_FINDING = 3
PASSAGE_CHARS = 900  # with 8 findings the prompt stays ~22k chars, within Gemini's 30 s timeout
SEVERITY_RANK = ["CONTRAINDICATED", "MAJOR", "MODERATE", "MINOR", "PRECAUTION", "UNKNOWN_SEVERITY"]

SYSTEM = """You explain medication-safety findings to a member of the public, using FDA drug-label passages.
For EACH finding, write 2-3 short plain-language sentences: why the combination is risky and what to do.
- After a sentence taken from a passage, add that passage's id in square brackets, e.g. [4f1c...].
  Cite only passages listed under the same finding; copy ids exactly; never invent one.
- The finding is authoritative: never contradict, soften or dismiss it.
- Plain text only, no markdown. Tell the reader to check with their pharmacist or doctor when it matters.
Return JSON: [{"finding_id": "...", "explanation": "..."}] with one item per finding."""


class _Item(BaseModel):
    finding_id: str
    explanation: str


def _counterpart(finding: SafetyFinding, repo: SafetyRulesRepository) -> str:
    """The food, condition or allergen a finding is about ("" for drug-drug)."""
    rule = repo.get_rule(finding.rule_id) if finding.rule_id else None
    if isinstance(rule, DFIRule):
        return rule.food_identifier
    if isinstance(rule, DCIRule):
        return rule.condition_display
    return finding.finding_id.split("|")[2] if finding.finding_id.count("|") >= 2 else ""


def finding_question(finding: SafetyFinding, names: dict[str, str], repo: SafetyRulesRepository) -> str:
    """What to search the labels for: the drugs, plus the food, condition or allergen involved."""
    drugs = " and ".join(names.get(m, m) for m in finding.subject_medications)
    item = _counterpart(finding, repo)
    if finding.finding_type == "DRUG_FOOD_INTERACTION":
        return f"{drugs} with {item}: food interaction"
    if finding.finding_type == "CONTRAINDICATION":
        return f"{drugs} in patients with {item}: contraindication"
    if finding.finding_type == "ALLERGY_EXCIPIENT":
        return f"{drugs} allergy hypersensitivity {item}"
    return f"{drugs} interaction: {finding.clinical_explanation}"


def _quoted(
    passages: list[EvidencePassage], finding: SafetyFinding, names: dict[str, str], counterpart: str
) -> FindingExplanation:
    """No language model: up to two label sentences that name the other drug (or the food/condition),
    cited. None when no sentence does: an off-topic quote would look like evidence for this finding."""
    finding_id = finding.finding_id
    terms = [counterpart] if counterpart else []
    if finding.finding_type == "DRUG_DRUG_INTERACTION":
        terms = [names.get(m, m) for m in finding.subject_medications]
    sentences = [
        (p.rxcui, s)
        for p in passages
        for s in split_sentences(cite_sentences(p))
        if "|" not in s and len(s) >= 40  # table rows and headings read badly out of context
    ]
    # A sentence in drug A's label that names drug B (or the food/condition) is about this finding.
    relevant = [
        s for rxcui, s in sentences if any(mentions(s, t) for t in terms if t and t != names.get(rxcui))
    ]
    if not relevant:
        return FindingExplanation(finding_id=finding_id)
    text = " ".join(relevant[:2])
    return FindingExplanation(
        finding_id=finding_id, text=text, sources=label_sources(text, passages, names), mode="offline"
    )


class FindingExplainer:
    def __init__(self, rag: RagService, repo: SafetyRulesRepository, chat: GeminiChat | None = None) -> None:
        self.rag = rag
        self.repo = repo
        self.chat = chat

    async def explain(
        self, findings: Sequence[SafetyFinding], medications: Sequence[MedicationConcept]
    ) -> list[FindingExplanation]:
        names = {m.rxcui: m.canonical_name for m in medications}
        by_rxcui = {m.rxcui: m for m in medications}
        ranked = sorted(
            findings,
            key=lambda f: SEVERITY_RANK.index(f.severity.value) if f.severity.value in SEVERITY_RANK else 99,
        )
        chosen = ranked[:MAX_EXPLAINED]

        async def passages_for(f: SafetyFinding) -> list[EvidencePassage]:
            meds = [by_rxcui[r] for r in f.subject_medications if r in by_rxcui]
            if not meds:
                return []
            passages, _ = await self.rag.retrieve_context(meds, finding_question(f, names, self.repo))
            return passages[:PASSAGES_PER_FINDING]

        found = await asyncio.gather(*(passages_for(f) for f in chosen))
        answered = {f.finding_id: p for f, p in zip(chosen, found, strict=True) if p}

        cache_key = tuple(sorted((fid, tuple(p.passage_id for p in ps)) for fid, ps in answered.items()))
        written: dict[str, str] = dict(_written_cache.get(cache_key, {}))
        if written:
            _written_cache.move_to_end(cache_key)
        elif self.chat is not None and answered:
            blocks = []
            for f in chosen:
                if f.finding_id not in answered:
                    continue
                cited = "\n".join(
                    f"[{p.passage_id}] {p.content[:PASSAGE_CHARS]}" for p in answered[f.finding_id]
                )
                blocks.append(
                    f"FINDING {f.finding_id}\n{f.finding_type} ({f.severity.value}): "
                    f"{f.clinical_explanation} What to do: {f.actionable_warning}\nPASSAGES:\n{cited}"
                )
            raw = await run_in_threadpool(self.chat.reply, SYSTEM, [], "\n\n".join(blocks), True, True)
            if raw:
                try:
                    items = TypeAdapter(list[_Item]).validate_python(json.loads(raw))
                    written = {i.finding_id: i.explanation for i in items}
                    _written_cache[cache_key] = written
                    if len(_written_cache) > CACHE_SIZE:
                        _written_cache.popitem(last=False)
                except (json.JSONDecodeError, ValidationError) as exc:
                    logger.warning("Gemini finding explanations were not valid JSON; quoting labels: %s", exc)

        results = []
        for f in findings:
            passages = answered.get(f.finding_id)
            if not passages:
                results.append(FindingExplanation(finding_id=f.finding_id))
                continue
            text = strip_unknown_citations(written.get(f.finding_id, ""), {p.passage_id for p in passages})
            if text:
                results.append(
                    FindingExplanation(
                        finding_id=f.finding_id,
                        text=text,
                        sources=label_sources(text, passages, names),
                        mode="gemini",
                    )
                )
            else:
                results.append(_quoted(passages, f, names, _counterpart(f, self.repo)))
        return results
