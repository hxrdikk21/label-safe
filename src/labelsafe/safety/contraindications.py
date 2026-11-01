"""
Drug-Condition Contraindication (DCI) screening engine.
Evaluates medications against patient pre-existing conditions and diagnoses.
"""

import re

from src.labelsafe.core.contracts.medication import MedicationConcept
from src.labelsafe.core.contracts.safety import (
    FindingStatus,
    SafetyFinding,
)
from src.labelsafe.core.contracts.user_context import UserConditionRecord
from src.labelsafe.safety.rules_db import SafetyRulesRepository, get_safety_rules_repo

# A bare string like 'J45' or 'N18.4' is a code; anything else is a condition name.
ICD10_SHAPE = re.compile(r"[A-Za-z]\d[\w.]*")


class DCIScreeningEngine:
    """Deterministic screener evaluating drug-condition contraindications and warnings."""

    def __init__(self, repository: SafetyRulesRepository | None = None) -> None:
        self.repo = repository or get_safety_rules_repo()

    def screen_contraindications(
        self,
        medications: list[MedicationConcept | str],
        conditions: list[UserConditionRecord | str],
    ) -> list[SafetyFinding]:
        """
        Cross-checks medications against patient conditions using ICD-10 codes and descriptions.
        """
        if not medications or not conditions:
            return []

        findings: list[SafetyFinding] = []

        for med in medications:
            if isinstance(med, MedicationConcept):
                rxcui = med.rxcui
                med_name = med.canonical_name
            else:
                rxcui = str(med).strip()
                med_name = rxcui

            for cond in conditions:
                if isinstance(cond, UserConditionRecord):
                    code = cond.icd10_code
                    cond_name = cond.condition_name
                else:
                    cond_name = str(cond).strip()
                    code = cond_name if ICD10_SHAPE.fullmatch(cond_name) else None

                # The ICD-10 code decides when given; a bare name falls back to matching the rule's name.
                rule = self.repo.find_dci(rxcui, code) if code else None
                rule = rule or self.repo.find_dci_by_name(rxcui, cond_name)
                if rule:
                    disp_drug = med_name or rule.subject_name or rxcui
                    disp_cond = rule.condition_display if rule.condition_display else cond_name
                    contra_type = (
                        "ABSOLUTE CONTRAINDICATION"
                        if rule.is_absolute_contraindication
                        else "WARNING / PRECAUTION"
                    )
                    finding = SafetyFinding(
                        finding_id=f"{rule.rule_id}|{rxcui}|{(code or cond_name).lower()}",
                        finding_type="CONTRAINDICATION",
                        subject_medications=[rxcui],
                        status=FindingStatus.RISK_IDENTIFIED,
                        severity=rule.severity,
                        rule_id=rule.rule_id,
                        rule_source=rule.rule_source,
                        supporting_evidence_ids=rule.source_document_ids,
                        clinical_explanation=(
                            f"[{contra_type}] {disp_drug} in patient with {disp_cond} "
                            f"({rule.condition_code}): "
                            f"{rule.mechanism_summary} {rule.clinical_consequence}"
                        ),
                        actionable_warning=rule.actionable_warning,
                        requires_professional_review=True,
                    )
                    findings.append(finding)

        return findings
