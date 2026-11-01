"""
Live RAG evaluation over the real label corpus (``make rag-eval``).

Unlike ``rag_benchmarks.py`` (a synthetic in-memory corpus), this runs RagService against PostgreSQL
with the configured models. Each case is a question phrased the way people type it, often without
naming the drug, and a pattern the right label passage must contain. Reports hit@5 after reranking,
MRR, the gate decision, abstention and latency; with ``--generate`` it also runs ``explain()``.
Exits non-zero when hit@5 < 0.9 or a should-abstain case answers, so it doubles as a regression check.
"""

import argparse
import asyncio
import re
import statistics
import sys
import time
from dataclasses import dataclass

from src.rxguard.api.dependencies import get_rag_service
from src.rxguard.api.routes.medications import seed_concepts
from src.rxguard.rag.gate import GateAction


@dataclass(frozen=True)
class Case:
    medicines: tuple[str, ...]
    question: str
    expect: str | None  # regex the right passage contains; None means the pipeline should abstain


CASES = [
    Case(("warfarin", "ibuprofen"), "Why is this combination risky?", r"bleed"),
    Case(("warfarin", "ibuprofen"), "Can I take warfarin with ibuprofen?", r"bleed"),
    Case(("amiodarone", "digoxin"), "What happens if I take these together?", r"digoxin"),
    Case(
        ("simvastatin", "clarithromycin"), "Is it safe to combine these?", r"clarithromycin|CYP3A4|myopathy"
    ),
    Case(("sertraline", "tramadol"), "Any danger taking both?", r"serotonin"),
    Case(("lisinopril", "spironolactone"), "Should I worry about potassium?", r"potassium|hyperkalemia"),
    Case(("metformin",), "Can I drink alcohol on this?", r"alcohol"),
    Case(("clopidogrel", "omeprazole"), "Does omeprazole affect clopidogrel?", r"omeprazole|CYP2C19"),
    Case(("lithium", "ibuprofen"), "Is ibuprofen ok with lithium?", r"lithium|NSAID"),
    Case(("methotrexate",), "What are the serious warnings?", r"toxicit|death|bone marrow"),
    Case(
        ("warfarin", "fluconazole"), "Does fluconazole change how warfarin works?", r"fluconazole|CYP2C9|INR"
    ),
    Case(("warfarin", "aspirin"), "Is aspirin with this a problem?", r"aspirin|bleed"),
    Case(("simvastatin", "amlodipine"), "Is there a dose limit with these?", r"amlodipine|20 mg"),
    Case(("amiodarone", "simvastatin"), "Is this combination risky?", r"simvastatin|myopathy"),
    Case(("digoxin",), "What are signs of toxicity?", r"toxicity"),
    Case(("warfarin",), "What is the capital of France?", None),
    Case(("ibuprofen",), "Recommend a good laptop for programming", None),
]


async def run(generate: bool) -> int:
    rag = get_rag_service()
    concepts = {c.canonical_name.lower(): c for c in seed_concepts()}
    hits, reciprocal, latencies, wrong_answers = 0, 0.0, [], 0
    answerable = [c for c in CASES if c.expect]
    for case in CASES:
        meds = [concepts[m] for m in case.medicines]
        started = time.perf_counter()
        passages, action = await rag.retrieve_context(meds, case.question)
        latencies.append(time.perf_counter() - started)
        rank = next(
            (
                i + 1
                for i, p in enumerate(passages)
                if case.expect and re.search(case.expect, p.content, re.I)
            ),
            None,
        )
        if case.expect:
            hits += rank is not None
            reciprocal += 1 / rank if rank else 0.0
            verdict = f"hit@{rank}" if rank else "MISS"
        else:
            wrong_answers += action != GateAction.ABSTAIN
            verdict = "abstained" if action == GateAction.ABSTAIN else "ANSWERED (should abstain)"
        line = f"{'+'.join(case.medicines):28} {case.question[:44]:44} {action.value:8} {verdict:26}"
        if generate and case.expect:
            explained = await rag.explain(meds, case.question)
            line += f" explain={explained.evidence_sufficiency_state} sources={len(explained.sources)}"
        print(f"{line} {latencies[-1]:.2f}s", flush=True)

    hit_rate = hits / len(answerable)
    print(
        f"\nhit@5 {hit_rate:.2f} ({hits}/{len(answerable)})  MRR {reciprocal / len(answerable):.2f}  "
        f"should-abstain answered {wrong_answers}  latency p50 {statistics.median(latencies):.2f}s "
        f"p95 {sorted(latencies)[int(0.95 * (len(latencies) - 1))]:.2f}s"
    )
    return 0 if hit_rate >= 0.9 and wrong_answers == 0 else 1


def main() -> None:  # pragma: no cover - CLI
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval on the live label corpus.")
    parser.add_argument("--generate", action="store_true", help="also run explain() (calls the LLM)")
    sys.exit(asyncio.run(run(parser.parse_args().generate)))


if __name__ == "__main__":  # pragma: no cover
    main()
