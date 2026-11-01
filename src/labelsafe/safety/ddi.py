"""
Pairwise Drug-Drug Interaction (DDI) screening engine.
Evaluates n(n-1)/2 medication pairs against deterministic symbolic rules.
"""

from itertools import combinations

from src.labelsafe.core.contracts.medication import MedicationConcept
from src.labelsafe.core.contracts.safety import (
    FindingStatus,
    SafetyFinding,
)
from src.labelsafe.safety.rules_db import SafetyRulesRepository, get_safety_rules_repo


class DDIScreeningEngine:
    """Deterministic screener evaluating pairwise drug-drug interactions."""

    def __init__(self, repository: SafetyRulesRepository | None = None) -> None:
        self.repo = repository or get_safety_rules_repo()

    def screen_pairs(self, medications: list[MedicationConcept]) -> list[SafetyFinding]:
        """
        Enumerates all distinct unordered medication pairs and checks for validated DDI rules.
        For n medications, evaluates n(n-1)/2 pairs.
        """
        if not medications or len(medications) < 2:
            return []

        # Deduplicate medications by RxCUI while preserving concept references
        unique_meds: list[MedicationConcept] = []
        seen_rxcuis: set[str] = set()
        for m in medications:
            clean_rxcui = str(m.rxcui).strip()
            if clean_rxcui not in seen_rxcuis:
                seen_rxcuis.add(clean_rxcui)
                unique_meds.append(m)

        if len(unique_meds) < 2:
            return []

        findings: list[SafetyFinding] = []

        # Generate all distinct 2-combinations: n(n-1)/2
        for med_a, med_b in combinations(unique_meds, 2):
            rule = self.repo.find_ddi(med_a.rxcui, med_b.rxcui)
            if rule:
                finding = SafetyFinding(
                    finding_id=f"{rule.rule_id}|{'+'.join(sorted([med_a.rxcui, med_b.rxcui]))}",
                    finding_type="DRUG_DRUG_INTERACTION",
                    subject_medications=[med_a.rxcui, med_b.rxcui],
                    status=FindingStatus.RISK_IDENTIFIED,
                    severity=rule.severity,
                    rule_id=rule.rule_id,
                    rule_source=rule.rule_source,
                    supporting_evidence_ids=rule.source_document_ids,
                    clinical_explanation=(
                        f"Interaction between {med_a.canonical_name} and {med_b.canonical_name}: "
                        f"{rule.mechanism_summary} {rule.clinical_consequence}"
                    ),
                    actionable_warning=rule.actionable_warning,
                    requires_professional_review=True,
                )
                findings.append(finding)

        return findings

    def screen_rxcuis(self, rxcuis: list[str]) -> list[SafetyFinding]:
        """Convenience method to screen raw RxCUI strings without full MedicationConcept objects."""
        clean_rxcuis = sorted(list({str(r).strip() for r in rxcuis if str(r).strip()}))
        if len(clean_rxcuis) < 2:
            return []

        findings: list[SafetyFinding] = []
        for rxcui_a, rxcui_b in combinations(clean_rxcuis, 2):
            rule = self.repo.find_ddi(rxcui_a, rxcui_b)
            if rule:
                name_a = rule.subject_name or rxcui_a
                name_b = rule.interacting_name or rxcui_b
                finding = SafetyFinding(
                    finding_id=f"{rule.rule_id}|{rxcui_a}+{rxcui_b}",
                    finding_type="DRUG_DRUG_INTERACTION",
                    subject_medications=[rxcui_a, rxcui_b],
                    status=FindingStatus.RISK_IDENTIFIED,
                    severity=rule.severity,
                    rule_id=rule.rule_id,
                    rule_source=rule.rule_source,
                    supporting_evidence_ids=rule.source_document_ids,
                    clinical_explanation=(
                        f"Interaction between {name_a} and {name_b}: {rule.mechanism_summary} "
                        f"{rule.clinical_consequence}"
                    ),
                    actionable_warning=rule.actionable_warning,
                    requires_professional_review=True,
                )
                findings.append(finding)

        return findings
