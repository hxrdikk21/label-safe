"""
Generates unreviewed safety rules for the whole medication catalogue (``make rules``).

- DDInter (https://ddinter.scbdd.com, CC BY-NC-SA 4.0, research use): drug pairs with a
  Major / Moderate / Minor level, mapped to catalogue RxCUIs by name, brand or ingredient.
- FDA label text already ingested into PostgreSQL: a Drug Interactions passage of drug X that
  names catalogue drug Y (or a known food) becomes a rule citing that passage.

Output goes to ``data/generated/*.json``; ``get_safety_rules_repo`` loads it after the curated
rulebook, and curated rules always win. Every generated rule has ``reviewed=False``.
"""

import argparse
import asyncio
import csv
import io
import json
import logging
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from src.labelsafe.core.contracts.evidence import EvidencePassage
from src.labelsafe.core.contracts.medication import MedicationConcept
from src.labelsafe.core.contracts.safety import FindingSeverity
from src.labelsafe.safety.rules_db import GENERATED_RULES_DIR, mentions

logger = logging.getLogger(__name__)

DDINTER_URL = "https://ddinter.scbdd.com/static/media/download/ddinter_downloads_code_{}.csv"
DDINTER_CODES = "ABCDGHJLMNPRSV"  # every ATC anatomical group DDInter publishes
FOODS_FILE = Path(__file__).resolve().parents[3] / "data" / "seed" / "foods.json"
INTERACTION_SECTIONS = {"34073-7", "43685-7"}  # Drug Interactions, Warnings and Precautions

LEVELS = {
    "major": FindingSeverity.MAJOR,
    "moderate": FindingSeverity.MODERATE,
    "minor": FindingSeverity.MINOR,
}
ACTIONS = {
    FindingSeverity.CONTRAINDICATED: "Do not take these together. Ask your prescriber for an alternative.",
    FindingSeverity.MAJOR: "Avoid taking these together unless your prescriber says otherwise.",
    FindingSeverity.MODERATE: "Take together only on your prescriber's or pharmacist's advice; "
    "monitoring or a dose change may be needed.",
    FindingSeverity.MINOR: "Usually minor. Mention it to your pharmacist.",
    FindingSeverity.UNKNOWN_SEVERITY: "An interaction is listed but its severity is unknown. "
    "Ask your pharmacist.",
}
_SENTENCES = re.compile(r"(?<=[.!?])\s+")


def load_foods(path: Path = FOODS_FILE) -> list[dict[str, Any]]:
    foods: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["foods"]
    return foods


def name_index(concepts: Sequence[MedicationConcept]) -> dict[str, set[str]]:
    """Lower-case drug name, brand or active ingredient -> catalogue RxCUIs that contain it."""
    index: dict[str, set[str]] = {}
    for c in concepts:
        names = {c.canonical_name, *c.synonyms, *(i.name for i in c.ingredients if i.is_active)}
        for name in names:
            if len(name) >= 4:
                index.setdefault(name.lower().strip(), set()).add(c.rxcui)
    return index


def _ddi(a: str, b: str, names: dict[str, str], severity: FindingSeverity, **extra: Any) -> dict[str, Any]:
    return {
        "subject_rxcui": a,
        "interacting_rxcui": b,
        "subject_name": names[a].title(),
        "interacting_name": names[b].title(),
        "severity": severity.value,
        "actionable_warning": ACTIONS[severity],
        "reviewed": False,
        **extra,
    }


def ddinter_rules(
    rows: Iterable[dict[str, str]], concepts: Sequence[MedicationConcept]
) -> list[dict[str, Any]]:
    index = name_index(concepts)
    names = {c.rxcui: c.canonical_name for c in concepts}
    rank = {s: i for i, s in enumerate(ACTIONS)}  # earlier in ACTIONS = more severe
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        level = LEVELS.get(row.get("Level", "").strip().lower(), FindingSeverity.UNKNOWN_SEVERITY)
        for a in index.get(row.get("Drug_A", "").lower().strip(), ()):
            for b in index.get(row.get("Drug_B", "").lower().strip(), ()):
                if a == b:
                    continue
                key = (min(a, b), max(a, b))
                current = best.get(key)
                if current and rank[FindingSeverity(current["severity"])] <= rank[level]:
                    continue
                best[key] = _ddi(
                    key[0],
                    key[1],
                    names,
                    level,
                    rule_id=f"DDINTER-{key[0]}-{key[1]}",
                    mechanism_summary=f"DDInter lists {row['Drug_A']} and {row['Drug_B']} as a "
                    f"{level.value.replace('_', ' ').lower()} interaction.",
                    clinical_consequence="Check both drug labels for details. This rule comes from the "
                    "DDInter database (CC BY-NC-SA 4.0) and has not been clinically reviewed.",
                    source_document_ids=["DDInter"],
                    rule_source="ddinter",
                )
    return list(best.values())


def _label_severity(sentence: str) -> FindingSeverity:
    s = sentence.lower()
    if "contraindicat" in s:
        return FindingSeverity.CONTRAINDICATED
    if "avoid" in s or "do not" in s:
        return FindingSeverity.MAJOR
    return FindingSeverity.MODERATE


def label_rules(
    passages: Sequence[EvidencePassage],
    concepts: Sequence[MedicationConcept],
    foods: Sequence[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Rules from label sentences that name another catalogue drug or a known food."""
    index = name_index(concepts)
    names = {c.rxcui: c.canonical_name for c in concepts}
    ddi: dict[tuple[str, str], dict[str, Any]] = {}
    dfi: dict[tuple[str, str], dict[str, Any]] = {}
    for p in passages:
        if p.loinc_section_code not in INTERACTION_SECTIONS or p.rxcui not in names:
            continue
        for sentence in _SENTENCES.split(p.content):
            words = set(re.findall(r"[a-z0-9]+", sentence.lower()))
            for name, rxcuis in index.items():
                if name.split()[0] not in words or not mentions(sentence, name):
                    continue
                for other in rxcuis - {p.rxcui}:
                    key = (min(p.rxcui, other), max(p.rxcui, other))
                    if key in ddi:
                        continue
                    ddi[key] = _ddi(
                        key[0],
                        key[1],
                        names,
                        _label_severity(sentence),
                        rule_id=f"LABEL-DDI-{key[0]}-{key[1]}",
                        mechanism_summary=sentence.strip()[:500],
                        clinical_consequence=f"From the {p.section_title} section of the "
                        f"{names[p.rxcui]} label. Extracted automatically; not clinically reviewed.",
                        source_document_ids=[p.passage_id],
                        rule_source="fda_label",
                    )
            for food in foods:
                terms = [food["name"], *food.get("aliases", [])]
                if (p.rxcui, food["name"]) in dfi or not any(mentions(sentence, t) for t in terms):
                    continue
                severity = _label_severity(sentence)
                dfi[(p.rxcui, food["name"])] = {
                    "rule_id": f"LABEL-DFI-{p.rxcui}-{re.sub(r'[^a-z0-9]+', '-', food['name'])}",
                    "subject_rxcui": p.rxcui,
                    "subject_name": names[p.rxcui].title(),
                    "food_identifier": food["name"],
                    "food_aliases": food.get("aliases", []),
                    "severity": severity.value,
                    "mechanism_summary": sentence.strip()[:500],
                    "clinical_consequence": f"From the {p.section_title} section of the {names[p.rxcui]} "
                    "label. Extracted automatically; not clinically reviewed.",
                    "actionable_warning": ACTIONS[severity],
                    "source_document_ids": [p.passage_id],
                    "rule_source": "fda_label",
                    "reviewed": False,
                }
    return {"ddi_rules": list(ddi.values()), "dfi_rules": list(dfi.values())}


def write_rules(
    name: str, rules: dict[str, list[dict[str, Any]]], directory: Path = GENERATED_RULES_DIR
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps({"version": "generated", **rules}, indent=1), encoding="utf-8")
    return path


async def _main(argv: list[str] | None = None) -> None:  # pragma: no cover - thin CLI wrapper
    import httpx
    from sqlalchemy import select

    from src.labelsafe.api.routes.medications import load_concepts
    from src.labelsafe.core.config import get_settings
    from src.labelsafe.database.connection import create_engine, create_session_factory
    from src.labelsafe.database.models import EvidencePassageRecord

    parser = argparse.ArgumentParser(description="Generate unreviewed rules from DDInter and FDA labels.")
    parser.add_argument("--skip-ddinter", action="store_true")
    parser.add_argument("--skip-labels", action="store_true")
    args = parser.parse_args(argv)

    engine = create_engine(get_settings().database_url)
    factory = create_session_factory(engine)
    try:
        concepts = await load_concepts(factory)
        if not args.skip_ddinter:
            rows: list[dict[str, str]] = []
            # The CSVs are large and the server is slow; 60 s timed out.
            async with httpx.AsyncClient(timeout=300, follow_redirects=True) as http:
                for code in DDINTER_CODES:
                    response = await http.get(DDINTER_URL.format(code))
                    response.raise_for_status()
                    rows += list(csv.DictReader(io.StringIO(response.text)))
            rules = ddinter_rules(rows, concepts)
            path = write_rules("ddinter_rules.json", {"ddi_rules": rules})
            print(f"DDInter: {len(rows)} pairs read, {len(rules)} rules for catalogue drugs -> {path}")
        if not args.skip_labels:
            async with factory() as session:
                records = await session.scalars(
                    select(EvidencePassageRecord).where(
                        EvidencePassageRecord.loinc_section_code.in_(INTERACTION_SECTIONS)
                    )
                )
                passages = [r.to_contract() for r in records]
            generated = label_rules(passages, concepts, load_foods())
            path = write_rules("fda_label_rules.json", generated)
            print(
                f"FDA labels: {len(passages)} passages -> {len(generated['ddi_rules'])} drug and "
                f"{len(generated['dfi_rules'])} food rules -> {path}"
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
