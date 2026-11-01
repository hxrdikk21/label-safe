"""
Automated 50-Scenario Evaluation Harness for LabelSafe.
Loads benchmark scenarios, executes SafetyEngine screening,
and computes clinical metrics (Sensitivity, Specificity, Precision, FNR, Faithfulness).
"""

import json
from pathlib import Path

from pydantic import BaseModel

from src.labelsafe.core.contracts.medication import IngredientReference, MedicationConcept
from src.labelsafe.core.contracts.safety import FindingSeverity
from src.labelsafe.core.contracts.user_context import UserAllergyRecord, UserConditionRecord, UserContext
from src.labelsafe.evaluation.metrics import EvaluationMetrics, calculate_metrics
from src.labelsafe.safety.engine import ClinicalSafetyReport, SafetyEngine


class ScenarioResult(BaseModel):
    scenario_id: str
    category: str
    description: str
    expected_has_risk: bool
    actual_has_risk: bool
    passed: bool
    highest_severity: str
    overall_status: str
    rule_ids: list[str]


class BenchmarkReport(BaseModel):
    total_evaluated: int
    passed_count: int
    failed_count: int
    pass_rate: float
    metrics: EvaluationMetrics
    scenario_results: list[ScenarioResult]


class BenchmarkHarness:
    """Executes clinical benchmark evaluation suites against the safety platform."""

    def __init__(self, safety_engine: SafetyEngine | None = None):
        self.safety_engine = safety_engine or SafetyEngine()

    def run_benchmark(
        self,
        benchmark_file_path: str = "data/benchmark/scenarios_50.json",
    ) -> BenchmarkReport:
        """Executes full benchmark evaluation from scenario JSON."""
        path = Path(benchmark_file_path)
        if not path.exists():
            raise FileNotFoundError(f"Benchmark file not found: {benchmark_file_path}")

        with open(path, encoding="utf-8") as f:
            scenarios = json.load(f)

        y_true: list[bool] = []
        y_pred: list[bool] = []
        scenario_results: list[ScenarioResult] = []

        for sc in scenarios:
            # Parse medications
            med_concepts = []
            for m in sc.get("medications", []):
                ingredients = []
                for ing in m.get("ingredients", []):
                    ingredients.append(
                        IngredientReference(
                            unii=ing.get("unii", "UNKNOWN"),
                            name=ing.get("name", "Unknown"),
                            is_active=ing.get("is_active", True),
                        )
                    )
                med_concepts.append(
                    MedicationConcept(
                        rxcui=m["rxcui"],
                        canonical_name=m["canonical_name"],
                        term_type=m.get("term_type", "IN"),
                        ingredients=ingredients,
                        is_ambiguous=m.get("is_ambiguous", False),
                        ambiguity_candidates=m.get("ambiguity_candidates", []),
                    )
                )

            # Parse user context
            user_context = None
            raw_context = sc.get("user_context")
            if raw_context is not None:
                allergies = [
                    UserAllergyRecord(
                        substance_name=a["substance_name"],
                        severity=a.get("severity", "UNKNOWN"),
                    )
                    for a in raw_context.get("allergies", [])
                ]
                conditions = [
                    UserConditionRecord(
                        condition_name=c["condition_name"],
                        icd10_code=c.get("icd10_code"),
                    )
                    for c in raw_context.get("conditions", [])
                ]
                user_context = UserContext(
                    user_id=raw_context.get("user_id", "pt_bench"),
                    allergies=allergies,
                    conditions=conditions,
                )

            food_items = sc.get("food_items", [])

            # Evaluate through SafetyEngine
            report: ClinicalSafetyReport = self.safety_engine.evaluate(
                medications=med_concepts,
                food_items=food_items,
                user_context=user_context,
            )

            expected_risk = sc["expected_has_risk"]
            actual_risk = len(report.findings) > 0
            y_true.append(expected_risk)
            y_pred.append(actual_risk)

            # Verification logic
            passed = expected_risk == actual_risk
            # Check edge case status expectation if specified
            if "expected_status" in sc:
                passed = passed and (report.overall_status.value == sc["expected_status"])

            rule_ids = [f.rule_id for f in report.findings if f.rule_id]
            # The right risk must come from the right rule, at least as severe as expected.
            if sc.get("expected_rule_id"):
                passed = passed and sc["expected_rule_id"] in rule_ids
            if expected_risk and sc.get("expected_min_severity"):
                rank = SafetyEngine.SEVERITY_RANK
                expected_rank = rank[FindingSeverity(sc["expected_min_severity"])]
                passed = passed and rank[report.highest_severity] >= expected_rank

            scenario_results.append(
                ScenarioResult(
                    scenario_id=sc["scenario_id"],
                    category=sc["category"],
                    description=sc["description"],
                    expected_has_risk=expected_risk,
                    actual_has_risk=actual_risk,
                    passed=passed,
                    highest_severity=report.highest_severity.value,
                    overall_status=report.overall_status.value,
                    rule_ids=rule_ids,
                )
            )

        metrics = calculate_metrics(y_true, y_pred)
        passed_count = sum(1 for r in scenario_results if r.passed)
        failed_count = len(scenario_results) - passed_count
        pass_rate = round(passed_count / len(scenario_results), 4)

        return BenchmarkReport(
            total_evaluated=len(scenario_results),
            passed_count=passed_count,
            failed_count=failed_count,
            pass_rate=pass_rate,
            metrics=metrics,
            scenario_results=scenario_results,
        )
