"""Generated rules: DDInter mapping, label extraction, and curated-rule precedence."""

import hashlib
import json
from pathlib import Path

import pytest

from src.rxguard.core.contracts.evidence import EvidencePassage
from src.rxguard.core.contracts.medication import IngredientReference, MedicationConcept
from src.rxguard.safety.build_rules import ddinter_rules, label_rules, load_foods, write_rules
from src.rxguard.safety.rules_db import SafetyRulesRepository


def concept(rxcui: str, name: str, *synonyms: str, ingredients: tuple[str, ...] = ()) -> MedicationConcept:
    return MedicationConcept(
        rxcui=rxcui,
        canonical_name=name,
        term_type="IN",
        synonyms=list(synonyms),
        ingredients=[IngredientReference(unii=f"U{i}", name=n) for i, n in enumerate(ingredients)],
    )


CONCEPTS = [
    concept("703", "amiodarone", "Pacerone"),
    concept("3407", "digoxin", "Lanoxin"),
    concept("11289", "warfarin", "Coumadin"),
    concept("19711", "amoxicillin / clavulanate", ingredients=("amoxicillin", "clavulanate")),
    concept("723", "amoxicillin", ingredients=("amoxicillin",)),
]


def test_ddinter_maps_names_brands_and_ingredients_and_keeps_most_severe() -> None:
    rows = [
        {"Drug_A": "Amiodarone", "Drug_B": "Digoxin", "Level": "Moderate"},
        {"Drug_A": "Lanoxin", "Drug_B": "Pacerone", "Level": "Major"},  # same pair via brand names
        {"Drug_A": "Amoxicillin", "Drug_B": "Warfarin", "Level": "Minor"},
        {"Drug_A": "Unknown drug", "Drug_B": "Warfarin", "Level": "Major"},
    ]
    rules = {(r["subject_rxcui"], r["interacting_rxcui"]): r for r in ddinter_rules(rows, CONCEPTS)}
    assert rules[("3407", "703")]["severity"] == "MAJOR"
    # The amoxicillin ingredient maps to both the single drug and the combination.
    assert {("11289", "19711"), ("11289", "723")} <= set(rules)
    assert all(not r["reviewed"] and r["rule_source"] == "ddinter" for r in rules.values())
    assert len(rules) == 3


def test_label_rules_cite_the_passage_and_grade_by_wording() -> None:
    text = (
        "Concomitant use of amiodarone is contraindicated. Digoxin levels may rise. "
        "Avoid grapefruit juice during treatment."
    )
    passage = EvidencePassage(
        passage_id="P-1",
        document_id="SPL-W",
        rxcui="11289",
        loinc_section_code="34073-7",
        section_title="Drug Interactions",
        passage_index=0,
        content=text,
        sha256_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    out = label_rules([passage], CONCEPTS, load_foods())
    ddi = {(r["subject_rxcui"], r["interacting_rxcui"]): r for r in out["ddi_rules"]}
    assert ddi[("11289", "703")]["severity"] == "CONTRAINDICATED"
    assert ddi[("11289", "3407")]["severity"] == "MODERATE"
    assert ddi[("11289", "703")]["source_document_ids"] == ["P-1"]
    [food] = out["dfi_rules"]
    assert (food["food_identifier"], food["severity"]) == ("grapefruit", "MAJOR")


def test_generated_rules_never_override_curated_ones(tmp_path: Path) -> None:
    repo = SafetyRulesRepository()
    repo.load_from_json()  # curated seed: warfarin + ibuprofen is RULE-DDI-001
    base = {"mechanism_summary": "x", "clinical_consequence": "x", "actionable_warning": "x"}
    path = write_rules(
        "ddinter_rules.json",
        {
            "ddi_rules": [
                {
                    "rule_id": "DDINTER-11289-5640",
                    "subject_rxcui": "11289",
                    "interacting_rxcui": "5640",
                    "severity": "MINOR",
                    "rule_source": "ddinter",
                    "reviewed": False,
                    **base,
                },
                {
                    "rule_id": "DDINTER-3407-703",
                    "subject_rxcui": "3407",
                    "interacting_rxcui": "703",
                    "severity": "MAJOR",
                    "rule_source": "ddinter",
                    "reviewed": False,
                    **base,
                },
            ]
        },
        directory=tmp_path,
    )
    assert json.loads(path.read_text())["ddi_rules"]
    repo.load_from_json(path, replace=False)
    curated = repo.find_ddi("11289", "5640")
    assert curated is not None and curated.rule_id == "RULE-DDI-001" and curated.rule_source == "curated"
    generated = repo.find_ddi("703", "3407")
    assert generated is not None and generated.rule_source == "ddinter" and not generated.reviewed


def test_ddinter_rules_can_be_switched_off_for_commercial_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.rxguard.core.config import get_settings
    from src.rxguard.safety import rules_db

    base = {"mechanism_summary": "x", "clinical_consequence": "x", "actionable_warning": "x"}
    rule = {
        "subject_rxcui": "3407",
        "interacting_rxcui": "703",
        "severity": "MAJOR",
        "reviewed": False,
        **base,
    }
    write_rules(
        "ddinter_rules.json", {"ddi_rules": [{**rule, "rule_id": "D1", "rule_source": "ddinter"}]}, tmp_path
    )
    monkeypatch.setattr(rules_db, "GENERATED_RULES_DIR", tmp_path)
    load = rules_db.get_safety_rules_repo.__wrapped__  # uncached: the app caches the loaded rulebook
    assert load().find_ddi("703", "3407") is not None
    monkeypatch.setattr(get_settings(), "include_ddinter", False)
    assert load().find_ddi("703", "3407") is None
