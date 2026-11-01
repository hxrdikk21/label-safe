"""
Evaluation Package Initialization.
"""

from src.rxguard.evaluation.harness import BenchmarkHarness, BenchmarkReport, ScenarioResult
from src.rxguard.evaluation.metrics import EvaluationMetrics, calculate_metrics
from src.rxguard.evaluation.rag_benchmarks import (
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
