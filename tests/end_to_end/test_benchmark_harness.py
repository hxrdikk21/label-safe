"""
End-to-End System Integration Tests.
Executes the full 50-scenario benchmark suite and tests end-to-end integration workflows.
"""

import pytest

from src.labelsafe.evaluation.harness import BenchmarkHarness
from src.labelsafe.evaluation.metrics import calculate_metrics


class TestEndToEndBenchmarkSuite:
    """Verifies that the platform executes all 50 clinical benchmark scenarios with zero critical misses."""

    @pytest.fixture(scope="class")
    def harness(self):
        return BenchmarkHarness()

    def test_run_50_scenario_benchmark(self, harness):
        """Executes full 50-scenario gold-standard evaluation harness."""
        report = harness.run_benchmark("data/benchmark/scenarios_50.json")

        assert report.total_evaluated == 50
        assert report.failed_count == 0, (
            f"Failed scenarios: {[r.scenario_id for r in report.scenario_results if not r.passed]}"
        )
        assert report.pass_rate == 1.0

        # Safety-critical criteria:
        # Zero false negatives on contraindications (Sensitivity must be 1.0)
        assert report.metrics.sensitivity == 1.0
        assert report.metrics.false_negative_rate == 0.0
        assert report.metrics.precision == 1.0
        assert report.metrics.specificity == 1.0
        assert report.metrics.f1_score == 1.0

    def test_metrics_calculation_edge_cases(self):
        """Validates metric calculation on synthetic distributions."""
        y_true = [True, True, False, False]
        y_pred = [True, False, False, True]  # 1 TP, 1 FN, 1 TN, 1 FP

        metrics = calculate_metrics(y_true, y_pred, [True, True])
        assert metrics.true_positives == 1
        assert metrics.false_negatives == 1
        assert metrics.true_negatives == 1
        assert metrics.false_positives == 1
        assert metrics.sensitivity == 0.5
        assert metrics.specificity == 0.5
        assert metrics.false_negative_rate == 0.5
        assert metrics.claim_faithfulness_rate == 1.0
