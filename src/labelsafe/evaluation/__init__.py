"""
Evaluation Package Initialization.
"""

from src.labelsafe.evaluation.harness import BenchmarkHarness, BenchmarkReport, ScenarioResult
from src.labelsafe.evaluation.metrics import EvaluationMetrics, calculate_metrics
from src.labelsafe.evaluation.rag_benchmarks import (
    BenchmarkScenario,
    RAGBenchmarkHarness,
    RAGComparisonReport,
    TierMetrics,
)

__all__ = [
    "BenchmarkHarness",
    "BenchmarkReport",
    "BenchmarkScenario",
    "EvaluationMetrics",
    "RAGBenchmarkHarness",
    "RAGComparisonReport",
    "ScenarioResult",
    "TierMetrics",
    "calculate_metrics",
]
