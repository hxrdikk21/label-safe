"""
Drug-Food Interaction (DFI) screening engine.
Evaluates medications against patient diet and food substances.
"""

from src.labelsafe.core.contracts.medication import MedicationConcept
from src.labelsafe.core.contracts.safety import (
    FindingStatus,
    SafetyFinding,
)
from src.labelsafe.safety.rules_db import SafetyRulesRepository, get_safety_rules_repo


class DFIScreeningEngine:
    """Deterministic screener evaluating drug-food and dietary interactions."""

    def __init__(self, repository: SafetyRulesRepository | None = None) -> None:
        self.repo = repository or get_safety_rules_repo()

    def screen_food_interactions(
        self,
        medications: list[MedicationConcept | str],
        food_items: list[str],
    ) -> list[SafetyFinding]:
        """
        Cross-checks each medication against supplied dietary/food substances.
        """
        if not medications or not food_items:
            return []

        findings: list[SafetyFinding] = []
        clean_foods = [f.strip() for f in food_items if f.strip()]

        for med in medications:
            if isinstance(med, MedicationConcept):
                rxcui = med.rxcui
                med_name = med.canonical_name
            else:
                rxcui = str(med).strip()
                med_name = rxcui

            for food in clean_foods:
                rule = self.repo.find_dfi(rxcui, food)
                if rule:
                    disp_drug = med_name or rule.subject_name or rxcui
                    timing_text = (
                        f" Timing instruction: {rule.timing_qualifier}" if rule.timing_qualifier else ""
                    )
                    finding = SafetyFinding(
                        finding_id=f"{rule.rule_id}|{rxcui}|{food.lower()}",
                        finding_type="DRUG_FOOD_INTERACTION",
                        subject_medications=[rxcui],
                        status=FindingStatus.RISK_IDENTIFIED,
                        severity=rule.severity,
                        rule_id=rule.rule_id,
                        rule_source=rule.rule_source,
                        supporting_evidence_ids=rule.source_document_ids,
                        clinical_explanation=(
                            f"Food interaction between {disp_drug} and {food}: "
                            f"{rule.mechanism_summary} {rule.clinical_consequence}"
                        ),
                        actionable_warning=f"{rule.actionable_warning}{timing_text}",
                        requires_professional_review=True,
                    )
                    findings.append(finding)

        return findings
