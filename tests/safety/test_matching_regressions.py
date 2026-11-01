"""Regressions from the 2026-10-28 audit: cases where the engine missed a risk or invented one."""

import pytest

from src.rxguard.core.contracts.medication import IngredientReference, MedicationConcept
from src.rxguard.core.contracts.safety import FindingSeverity, FindingStatus
from src.rxguard.core.contracts.user_context import UserAllergyRecord, UserConditionRecord, UserContext
from src.rxguard.safety.engine import SafetyEngine
from src.rxguard.safety.rules_db import SafetyRulesRepository, get_safety_rules_repo, mentions

ENGINE = SafetyEngine()


def med(rxcui: str, name: str, *ingredients: tuple[str, str]) -> MedicationConcept:
    return MedicationConcept(
        rxcui=rxcui,
        canonical_name=name,
        term_type="IN",
        ingredients=[IngredientReference(unii=u, name=n) for n, u in ingredients],
    )


def rules(meds, foods=None, allergies=(), conditions=()):
    report = ENGINE.evaluate(
        medications=meds,
        food_items=foods,
        user_context=UserContext(user_id="t", allergies=list(allergies), conditions=list(conditions)),
    )
    return report, [(f.finding_type, f.rule_id) for f in report.findings]


AMOXICILLIN = med("723", "amoxicillin", ("amoxicillin", "804826J2HU"))
METFORMIN = med("6809", "metformin", ("metformin", "9100L32L2N"))
PROPRANOLOL = med("8787", "propranolol")
CIPRO = med("2551", "ciprofloxacin")


def test_allergy_to_the_drug_itself_is_flagged() -> None:
    report, found = rules([AMOXICILLIN], allergies=[UserAllergyRecord(substance_name="Amoxicillin")])
    assert found == [("ALLERGY_EXCIPIENT", None)]
    assert report.findings[0].severity == FindingSeverity.CONTRAINDICATED


def test_allergy_unii_does_not_flag_unrelated_drugs() -> None:
    allergy = UserAllergyRecord(substance_name="Penicillin", unii="804826J2HU")
    assert rules([METFORMIN], allergies=[allergy])[1] == []
    assert rules([AMOXICILLIN], allergies=[allergy])[1]  # but the allergen's own drug is still flagged


@pytest.mark.parametrize(
    ("rxcui", "name"),
    [("7984", "penicillin V"), ("733", "ampicillin"), ("19711", "amoxicillin / clavulanate")],
)
def test_penicillin_allergy_covers_catalogue_penicillins(rxcui: str, name: str) -> None:
    _, found = rules([med(rxcui, name)], allergies=[UserAllergyRecord(substance_name="Penicillin")])
    assert ("ALLERGY_EXCIPIENT", "RULE-ALLERG-001") in found


def test_sulfa_allergy_covers_catalogue_smx_tmp() -> None:
    _, found = rules(
        [med("10831", "sulfamethoxazole / trimethoprim")],
        allergies=[UserAllergyRecord(substance_name="Sulfonamide")],
    )
    assert found == [("ALLERGY_EXCIPIENT", "RULE-ALLERG-002")]


def test_condition_without_code_matches_by_name() -> None:
    for name in ("Asthma", "asthma", "bronchospasm"):
        _, found = rules([PROPRANOLOL], conditions=[UserConditionRecord(condition_name=name)])
        assert found == [("CONTRAINDICATION", "RULE-DCI-001")], name


def test_condition_codes_match_one_direction_only() -> None:
    repo = get_safety_rules_repo()
    assert repo.find_dci("8787", "J45.909") is not None  # more specific patient code
    assert repo.find_dci("8787", "J") is None  # broader patient code
    assert repo.find_dci("6809", "N18") is None
    for code in ("N18.4", "N18.5", "N18.6"):
        assert repo.find_dci("6809", code) is not None, code


def test_generic_condition_word_alone_matches_nothing() -> None:
    assert get_safety_rules_repo().find_dci_by_name("6809", "kidney disease") is not None
    assert get_safety_rules_repo().find_dci_by_name("6809", "disease") is None


@pytest.mark.parametrize(
    ("food", "hit"),
    [
        ("milk", True),
        ("Greek yogurt", True),
        ("dairy", True),
        ("non-dairy creamer", False),
        ("dairy-free milk", True),  # still says milk
        ("apple juice", False),
    ],
)
def test_food_matching_is_whole_word_with_aliases(food: str, hit: bool) -> None:
    assert bool(rules([CIPRO], foods=[food])[1]) is hit


def test_alcohol_aliases_and_negation() -> None:
    metronidazole = med("6922", "metronidazole")
    assert rules([metronidazole], foods=["red wine"])[1]
    assert rules([metronidazole], foods=["alcohol-free beer"])[1]  # 'beer' is still named
    assert not rules([metronidazole], foods=["alcohol-free"])[1]
    assert not rules([med("83367", "atorvastatin")], foods=["fruit"])[1]


def test_mentions_helper() -> None:
    assert mentions("fresh grapefruit juice", "grapefruit")
    assert not mentions("non-dairy", "dairy")
    assert not mentions("alcohol-free", "alcohol")
    assert not mentions("pineapple", "apple")


def test_duplicates_are_collapsed() -> None:
    _, found = rules([CIPRO, CIPRO], foods=["dairy", "Dairy"])
    assert found == [("DRUG_FOOD_INTERACTION", "RULE-DFI-002")]


def test_uncovered_drug_is_not_reported_as_safe() -> None:
    report, found = rules(
        [med("161", "acetaminophen")],
        allergies=[UserAllergyRecord(substance_name="latex")],
        conditions=[UserConditionRecord(condition_name="Migraine")],
    )
    assert found == []
    assert report.overall_status == FindingStatus.INSUFFICIENT_EVIDENCE
    assert any("no safety rules yet for acetaminophen" in w for w in report.missing_data_warnings)


def test_empty_history_lists_count_as_not_supplied() -> None:
    report, _ = rules([med("11289", "warfarin")])
    assert any("allergy history was not supplied" in w for w in report.missing_data_warnings)
    assert any("condition history was not supplied" in w for w in report.missing_data_warnings)


def test_empty_rulebook_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    get_safety_rules_repo.cache_clear()
    monkeypatch.setattr(SafetyRulesRepository, "load_from_json", lambda self, file_path=None: 0)
    try:
        with pytest.raises(RuntimeError, match="No safety rules loaded"):
            get_safety_rules_repo()
    finally:
        monkeypatch.undo()
        get_safety_rules_repo.cache_clear()
