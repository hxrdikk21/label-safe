"""
Medication Allergy & Inactive Excipient screening engine.
Evaluates medications against patient allergy history and excipient cross-sensitivities.
"""

from src.labelsafe.core.contracts.medication import MedicationConcept
from src.labelsafe.core.contracts.product import DrugProduct
from src.labelsafe.core.contracts.safety import (
    FindingSeverity,
    FindingStatus,
    SafetyFinding,
)
from src.labelsafe.core.contracts.user_context import UserAllergyRecord
from src.labelsafe.safety.rules_db import SafetyRulesRepository, get_safety_rules_repo, mentions


class AllergyScreeningEngine:
    """Deterministic screener evaluating allergy and excipient cross-sensitivities."""

    def __init__(self, repository: SafetyRulesRepository | None = None) -> None:
        self.repo = repository or get_safety_rules_repo()

    def screen_allergies(
        self,
        medications: list[MedicationConcept | DrugProduct | str],
        allergies: list[UserAllergyRecord | str],
    ) -> list[SafetyFinding]:
        """
        Cross-matches patient reported allergies against medication active moieties and excipients.
        """
        if not medications or not allergies:
            return []

        findings: list[SafetyFinding] = []

        for med in medications:
            # Extract target RxCUI, active UNIIs, and inactive UNIIs depending on input type
            target_rxcui: str | None = None
            med_name: str = ""
            target_uniis: set[str] = set()
            # Names that identify this drug's own substance (for direct allergy matches).
            own_names: set[str] = set()
            own_uniis: set[str] = set()

            if isinstance(med, MedicationConcept):
                target_rxcui = med.rxcui
                med_name = med.canonical_name
                own_names.update([med.canonical_name, *med.synonyms])
                for ing in med.ingredients:
                    if ing.is_active:
                        own_names.add(ing.name)
                        if ing.unii:
                            own_uniis.add(ing.unii.strip().upper())
                    if ing.unii:
                        target_uniis.add(ing.unii.strip().upper())
            elif isinstance(med, DrugProduct):
                target_rxcui = med.rxcui
                med_name = med.brand_name
                own_names.update([med.brand_name, med.generic_name])
                own_uniis.update(u.strip().upper() for u in med.active_ingredient_uniis if u)
                for u in med.active_ingredient_uniis + med.inactive_excipient_uniis:
                    if u:
                        target_uniis.add(u.strip().upper())
            else:
                target_rxcui = str(med).strip()
                med_name = target_rxcui

            for allergy_entry in allergies:
                allergen_unii: str | None = None
                if isinstance(allergy_entry, UserAllergyRecord):
                    allergen_name = allergy_entry.substance_name
                    allergen_unii = allergy_entry.unii.strip().upper() if allergy_entry.unii else None
                else:
                    allergen_name = str(allergy_entry).strip()

                disp_drug = med_name or target_rxcui or "Prescribed Medication"
                direct = (allergen_unii is not None and allergen_unii in own_uniis) or any(
                    mentions(allergen_name, n) for n in own_names if n
                )
                if direct:
                    # Allergy to this medicine's own active substance: no rule needed.
                    findings.append(
                        SafetyFinding(
                            finding_id=f"ALLERGY|{target_rxcui}|{allergen_name.lower()}",
                            finding_type="ALLERGY_EXCIPIENT",
                            subject_medications=[target_rxcui] if target_rxcui else [],
                            status=FindingStatus.RISK_IDENTIFIED,
                            severity=FindingSeverity.CONTRAINDICATED,
                            rule_id=None,
                            clinical_explanation=(
                                f"Reported allergy '{allergen_name}' names an active ingredient "
                                f"of {disp_drug}."
                            ),
                            actionable_warning=(
                                f"Do not take {disp_drug}. Ask the prescriber for an alternative."
                            ),
                            requires_professional_review=True,
                        )
                    )
                    continue

                rule = self.repo.find_allergy_match(
                    reported_allergen=allergen_name,
                    target_rxcui=target_rxcui,
                    target_uniis=list(target_uniis),
                    allergen_unii=allergen_unii,
                )

                if rule:
                    severity = (
                        FindingSeverity.CONTRAINDICATED
                        if rule.risk_level == "HIGH"
                        else FindingSeverity.MAJOR
                    )
                    finding = SafetyFinding(
                        finding_id=f"{rule.rule_id}|{target_rxcui}|{allergen_name.lower()}",
                        finding_type="ALLERGY_EXCIPIENT",
                        subject_medications=[target_rxcui] if target_rxcui else [],
                        status=FindingStatus.RISK_IDENTIFIED,
                        severity=severity,
                        rule_id=rule.rule_id,
                        rule_source=rule.rule_source,
                        supporting_evidence_ids=rule.source_document_ids,
                        clinical_explanation=(
                            f"Allergy/Excipient match for {disp_drug} against reported allergy "
                            f"'{allergen_name}': "
                            f"Triggers {rule.allergen_name} ({rule.allergen_group_id}). "
                            f"Expected risk: {rule.clinical_manifestation}"
                        ),
                        actionable_warning=rule.actionable_warning,
                        requires_professional_review=True,
                    )
                    findings.append(finding)

        return findings
