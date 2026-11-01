"""
SafetyEngine.get_finding_by_id: resolves recently emitted findings and rule ids
(previously raised AttributeError on every call).
"""

import pytest

from src.rxguard.core.contracts.medication import MedicationConcept
from src.rxguard.core.contracts.safety import FindingSeverity
from src.rxguard.safety.engine import SafetyEngine
from src.rxguard.safety.rules_db import SafetyRulesRepository


@pytest.fixture(scope="module")
def engine() -> SafetyEngine:
    return SafetyEngine()


@pytest.mark.parametrize(
    ("rule_id", "finding_type"),
    [
        ("RULE-DDI-001", "DRUG_DRUG_INTERACTION"),
        ("RULE-DFI-001", "DRUG_FOOD_INTERACTION"),
        ("RULE-DCI-001", "CONTRAINDICATION"),
        ("RULE-ALLERG-001", "ALLERGY_EXCIPIENT"),
    ],
)
def test_rule_ids_resolve_to_findings(engine: SafetyEngine, rule_id: str, finding_type: str) -> None:
    finding = engine.get_finding_by_id(rule_id)
    assert finding is not None
    assert (finding.finding_id, finding.rule_id, finding.finding_type) == (rule_id, rule_id, finding_type)
    assert finding.subject_medications and finding.clinical_explanation and finding.actionable_warning


def test_ddi_rule_lists_both_medications(engine: SafetyEngine) -> None:
    finding = engine.get_finding_by_id("RULE-DDI-001")
    assert finding is not None and finding.subject_medications == ["11289", "5640"]


def test_emitted_findings_are_cached_by_id(engine: SafetyEngine) -> None:
    meds = [
        MedicationConcept(rxcui="11289", canonical_name="Warfarin", term_type="IN"),
        MedicationConcept(rxcui="5640", canonical_name="Ibuprofen", term_type="IN"),
    ]
    report = engine.evaluate(meds)
    emitted = report.findings[0]
    assert engine.get_finding_by_id(emitted.finding_id) == emitted
    assert emitted.severity == FindingSeverity.CONTRAINDICATED


def test_unknown_id_returns_none(engine: SafetyEngine) -> None:
    assert engine.get_finding_by_id("nope") is None


def test_finding_cache_is_bounded() -> None:
    small = SafetyEngine()
    small.FINDING_CACHE_SIZE = 2
    meds = [
        MedicationConcept(rxcui="11289", canonical_name="Warfarin", term_type="IN"),
        MedicationConcept(rxcui="5640", canonical_name="Ibuprofen", term_type="IN"),
    ]
    pairs = [meds, [meds[0], MedicationConcept(rxcui="5640", canonical_name="Ibuprofen", term_type="IN")]]
    first = small.evaluate(pairs[0]).findings[0]
    assert first.finding_id == small.evaluate(pairs[1]).findings[0].finding_id  # same finding, same id
    others = [
        [
            MedicationConcept(rxcui="36567", canonical_name="Simvastatin", term_type="IN"),
            MedicationConcept(rxcui="21212", canonical_name="Clarithromycin", term_type="IN"),
        ],
        [
            MedicationConcept(rxcui="136443", canonical_name="Sildenafil", term_type="IN"),
            MedicationConcept(rxcui="4917", canonical_name="Nitroglycerin", term_type="IN"),
        ],
    ]
    for regimen in others:
        small.evaluate(regimen)
    assert len(small._recent_findings) == 2 and first.finding_id not in small._recent_findings
    # Evicted (or seen by another worker): rebuilt from its rule under the same id.
    rebuilt = small.get_finding_by_id(first.finding_id)
    assert (
        rebuilt is not None and rebuilt.finding_id == first.finding_id and rebuilt.rule_id == "RULE-DDI-001"
    )
    assert small.get_finding_by_id("NO-SUCH-RULE|1+2") is None


def test_repository_get_rule(engine: SafetyEngine) -> None:
    assert engine.repo.get_rule("RULE-DCI-001") is not None
    assert engine.repo.get_rule("missing") is None
    # A fresh repository: the default one is a process-wide singleton.
    empty = SafetyRulesRepository()
    assert empty.get_rule("RULE-DCI-001") is None
    empty.load_from_json()
    assert empty.get_rule("RULE-DCI-001") is not None
    empty.clear()
    assert empty.get_rule("RULE-DCI-001") is None
