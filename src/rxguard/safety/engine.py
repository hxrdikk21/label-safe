"""
Master Deterministic Safety Orchestrator.
Coordinates pairwise DDI, DFI, DCI, and allergy screening engines into a unified clinical report.
"""

import uuid
from collections import OrderedDict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from src.rxguard.core.config import get_settings
from src.rxguard.core.contracts.medication import MedicationConcept
from src.rxguard.core.contracts.product import DrugProduct
from src.rxguard.core.contracts.rag_response import RAGResponse
from src.rxguard.core.contracts.safety import (
    FindingSeverity,
    FindingStatus,
    SafetyFinding,
)
from src.rxguard.core.contracts.user_context import (
    UserAllergyRecord,
    UserConditionRecord,
)
from src.rxguard.safety.allergies import AllergyScreeningEngine
from src.rxguard.safety.contraindications import DCIScreeningEngine
from src.rxguard.safety.ddi import DDIScreeningEngine
from src.rxguard.safety.dfi import DFIScreeningEngine
from src.rxguard.safety.models import AllergyRule, DCIRule, DDIRule, DFIRule
from src.rxguard.safety.rules_db import SafetyRulesRepository, get_safety_rules_repo


class ClinicalSafetyReport(BaseModel):
    """Unified result emitted by the Master Safety Engine."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(..., min_length=1, description="Unique UUID for this clinical safety evaluation")
    execution_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Evaluation timestamp"
    )
    evaluated_medication_count: int = Field(default=0, ge=0)
    findings: list[SafetyFinding] = Field(default_factory=list)
    highest_severity: FindingSeverity = Field(default=FindingSeverity.UNKNOWN_SEVERITY)
    overall_status: FindingStatus = Field(default=FindingStatus.NO_ISSUE_FOUND_IN_CHECKED_SOURCES)
    missing_data_warnings: list[str] = Field(default_factory=list)
    checked_sources: list[str] = Field(default_factory=list)
    disclaimer: str = Field(..., min_length=1)
    grounded_explanation: RAGResponse | None = Field(
        default=None,
        description="Self-RAG narrative with verified citations (when include_explanation is requested)",
    )


class SafetyEngine:
    """Master orchestrator executing all deterministic clinical safety workflows."""

    # Severity hierarchy for calculating highest severity
    SEVERITY_RANK: ClassVar[dict[FindingSeverity, int]] = {
        FindingSeverity.CONTRAINDICATED: 60,
        FindingSeverity.MAJOR: 50,
        FindingSeverity.MODERATE: 40,
        FindingSeverity.MINOR: 30,
        FindingSeverity.PRECAUTION: 20,
        FindingSeverity.UNKNOWN_SEVERITY: 10,
    }

    # Findings emitted by evaluate() stay addressable for the Evidence Navigator.
    FINDING_CACHE_SIZE = 1024

    def __init__(self, repository: SafetyRulesRepository | None = None) -> None:
        self.repo = repository or get_safety_rules_repo()
        self._recent_findings: OrderedDict[str, SafetyFinding] = OrderedDict()
        self.ddi_engine = DDIScreeningEngine(repository=self.repo)
        self.dfi_engine = DFIScreeningEngine(repository=self.repo)
        self.dci_engine = DCIScreeningEngine(repository=self.repo)
        self.allergy_engine = AllergyScreeningEngine(repository=self.repo)

    def evaluate(
        self,
        medications: Sequence[MedicationConcept | DrugProduct | str],
        food_items: list[str] | None = None,
        user_context: Any | None = None,
    ) -> ClinicalSafetyReport:
        """Convenience method that unpacks UserContext and delegates to evaluate_clinical_profile."""
        conditions = user_context.conditions if user_context else None
        allergies = user_context.allergies if user_context else None
        return self.evaluate_clinical_profile(
            medications=medications,
            conditions=conditions,
            allergies=allergies,
            food_items=food_items,
        )

    def evaluate_clinical_profile(
        self,
        medications: Sequence[MedicationConcept | DrugProduct | str],
        conditions: list[UserConditionRecord | str] | None = None,
        allergies: list[UserAllergyRecord | str] | None = None,
        food_items: list[str] | None = None,
    ) -> ClinicalSafetyReport:
        """
        Executes end-to-end deterministic screening across DDI, DFI, DCI, and allergy matching.
        Strictly enforces that absence of retrieved data is never equated with safety.
        """
        settings = get_settings()
        missing_data_warnings: list[str] = []
        checked_sources: list[str] = [
            f"RxGuard curated safety rules ({self.repo.stats()['total_rules']} rules)"
        ]

        # Repeated entries would produce duplicate findings.
        medications = list({self._med_key(m): m for m in medications}.values())
        food_items = list({f.strip().lower(): f.strip() for f in food_items or [] if f.strip()}.values())

        # 1. Normalize medications into list of MedicationConcept objects or RxCUIs
        med_concepts: list[MedicationConcept] = []
        raw_med_targets: list[MedicationConcept | DrugProduct | str] = []

        for m in medications:
            raw_med_targets.append(m)
            if isinstance(m, MedicationConcept):
                med_concepts.append(m)
                if m.is_ambiguous:
                    missing_data_warnings.append(
                        f"Medication '{m.canonical_name}' resolved to ambiguous formulations: "
                        f"{m.ambiguity_candidates}. "
                        "Safety screening may be incomplete without specific formulation disambiguation."
                    )
            elif isinstance(m, DrugProduct):
                med_concepts.append(
                    MedicationConcept(
                        rxcui=m.rxcui,
                        canonical_name=m.brand_name,
                        term_type="SCD",
                    )
                )
            else:
                med_concepts.append(
                    MedicationConcept(
                        rxcui=str(m).strip(),
                        canonical_name=str(m).strip(),
                        term_type="IN",
                    )
                )

        all_findings: list[SafetyFinding] = []

        # 2. Drug-Drug Interactions (Pairwise)
        if len(med_concepts) >= 2:
            ddi_findings = self.ddi_engine.screen_pairs(med_concepts)
            all_findings.extend(ddi_findings)
        elif len(med_concepts) == 1:
            # Informative single-drug note
            pass

        # Drugs no rule mentions were not really checked; say so instead of implying safety.
        covered = self.repo.rule_drugs()
        unchecked = [m.canonical_name for m in med_concepts if m.rxcui not in covered]
        if unchecked:
            missing_data_warnings.append(
                f"RxGuard has no safety rules yet for {', '.join(unchecked)}, so interactions involving "
                f"{'it' if len(unchecked) == 1 else 'them'} were not checked."
            )

        # 3. Drug-Food Interactions
        if food_items:
            dfi_findings = self.dfi_engine.screen_food_interactions(list(med_concepts), food_items)
            all_findings.extend(dfi_findings)

        # 4. Drug-Condition Contraindications (an empty list means nothing was supplied)
        if conditions:
            dci_findings = self.dci_engine.screen_contraindications(list(med_concepts), conditions)
            all_findings.extend(dci_findings)
        else:
            missing_data_warnings.append(
                "Patient medical condition history was not supplied. Contraindication screening was not "
                "evaluated."
            )

        # 5. Medication Allergy & Inactive Excipients
        if allergies:
            allergy_findings = self.allergy_engine.screen_allergies(raw_med_targets, allergies)
            all_findings.extend(allergy_findings)
        else:
            missing_data_warnings.append(
                "Patient allergy history was not supplied. Absence of allergy record is not proof of safety."
            )

        # 6. Compute highest severity
        highest_severity = FindingSeverity.UNKNOWN_SEVERITY
        max_rank = 0
        for f in all_findings:
            rank = self.SEVERITY_RANK.get(f.severity, 0)
            if rank > max_rank:
                max_rank = rank
                highest_severity = f.severity

        # 7. Compute overall clinical finding status
        if any(f.severity in (FindingSeverity.CONTRAINDICATED, FindingSeverity.MAJOR) for f in all_findings):
            overall_status = FindingStatus.RISK_IDENTIFIED
        elif any(m.is_ambiguous for m in med_concepts):
            overall_status = FindingStatus.AMBIGUOUS_MEDICATION_IDENTITY
        elif all_findings:
            overall_status = FindingStatus.RISK_IDENTIFIED
        elif missing_data_warnings:
            # When no findings exist, but user context was omitted, signal insufficient evidence
            overall_status = FindingStatus.INSUFFICIENT_EVIDENCE
        else:
            overall_status = FindingStatus.NO_ISSUE_FOUND_IN_CHECKED_SOURCES

        for finding in all_findings:
            self._remember(finding)

        return ClinicalSafetyReport(
            report_id=f"REPORT-SAFETY-{uuid.uuid4().hex[:8].upper()}",
            execution_timestamp=datetime.now(UTC),
            evaluated_medication_count=len(med_concepts),
            findings=all_findings,
            highest_severity=highest_severity,
            overall_status=overall_status,
            missing_data_warnings=missing_data_warnings,
            checked_sources=checked_sources,
            disclaimer=settings.clinical_disclaimer,
        )

    @staticmethod
    def _med_key(m: MedicationConcept | DrugProduct | str) -> str:
        if isinstance(m, MedicationConcept | DrugProduct):
            return m.rxcui
        return str(m).strip()

    def _remember(self, finding: SafetyFinding) -> None:
        self._recent_findings[finding.finding_id] = finding
        self._recent_findings.move_to_end(finding.finding_id)
        while len(self._recent_findings) > self.FINDING_CACHE_SIZE:
            self._recent_findings.popitem(last=False)

    def get_finding_by_id(self, finding_id: str) -> SafetyFinding | None:
        """
        Resolves a finding for the Evidence Navigator: first a finding emitted by a
        recent evaluate() call, otherwise the rule it was codified by (``rule_id``).
        """
        cached = self._recent_findings.get(finding_id)
        if cached is not None:
            return cached
        # Finding IDs are "<rule_id>|<subjects>[|<item>]", so a finding this process never saw
        # (restart, another worker) is rebuilt from its rule.
        rule = self.repo.get_rule(finding_id.split("|", 1)[0])
        if rule is None:
            return None
        return self._finding_from_rule(rule).model_copy(update={"finding_id": finding_id})

    @staticmethod
    def _finding_from_rule(rule: DDIRule | DFIRule | DCIRule | AllergyRule) -> SafetyFinding:
        if isinstance(rule, AllergyRule):
            return SafetyFinding(
                finding_id=rule.rule_id,
                finding_type="ALLERGY_EXCIPIENT",
                subject_medications=list(rule.cross_reactive_rxcuis) or [rule.allergen_group_id],
                status=FindingStatus.RISK_IDENTIFIED,
                severity=(
                    FindingSeverity.CONTRAINDICATED if rule.risk_level == "HIGH" else FindingSeverity.MAJOR
                ),
                rule_id=rule.rule_id,
                rule_source=rule.rule_source,
                supporting_evidence_ids=list(rule.source_document_ids),
                clinical_explanation=(
                    f"{rule.allergen_name} ({rule.allergen_group_id}): {rule.clinical_manifestation}"
                ),
                actionable_warning=rule.actionable_warning,
                requires_professional_review=True,
            )
        if isinstance(rule, DDIRule):
            finding_type = "DRUG_DRUG_INTERACTION"
            subjects = [rule.subject_rxcui, rule.interacting_rxcui]
        elif isinstance(rule, DFIRule):
            finding_type = "DRUG_FOOD_INTERACTION"
            subjects = [rule.subject_rxcui]
        else:
            finding_type = "CONTRAINDICATION"
            subjects = [rule.subject_rxcui]
        return SafetyFinding(
            finding_id=rule.rule_id,
            finding_type=finding_type,
            subject_medications=subjects,
            status=FindingStatus.RISK_IDENTIFIED,
            severity=rule.severity,
            rule_id=rule.rule_id,
            rule_source=rule.rule_source,
            supporting_evidence_ids=list(rule.source_document_ids),
            clinical_explanation=f"{rule.mechanism_summary} {rule.clinical_consequence}",
            actionable_warning=rule.actionable_warning,
            requires_professional_review=True,
        )
