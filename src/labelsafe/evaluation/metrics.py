"""
Benchmark evaluation metrics module.
Calculates clinical safety metrics:
- Sensitivity (Recall on critical contraindications: must be 1.0 / zero false negatives)
- Specificity
- Precision
- F1-Score
- False Negative Rate (FNR)
- NLI Claim Faithfulness Rate
"""

from pydantic import BaseModel, Field


class EvaluationMetrics(BaseModel):
    total_scenarios: int
    true_positives: int
    true_negatives: int
    false_positives: int
    false_negatives: int
    sensitivity: float = Field(..., ge=0.0, le=1.0, description="Recall on clinical risks (TP / (TP + FN))")
    specificity: float = Field(..., ge=0.0, le=1.0, description="TN / (TN + FP)")
    precision: float = Field(..., ge=0.0, le=1.0, description="TP / (TP + FP)")
    f1_score: float = Field(..., ge=0.0, le=1.0)
    false_negative_rate: float = Field(..., ge=0.0, le=1.0, description="FN / (TP + FN), target = 0.0")
    claim_faithfulness_rate: float = Field(default=1.0, ge=0.0, le=1.0)


def calculate_metrics(
    y_true_has_risk: list[bool],
    y_pred_has_risk: list[bool],
    claim_supported_flags: list[bool] | None = None,
) -> EvaluationMetrics:
    """Computes comprehensive clinical safety evaluation metrics."""
    if len(y_true_has_risk) != len(y_pred_has_risk):
        raise ValueError("Ground truth and prediction lengths must match.")

    n = len(y_true_has_risk)
    tp = sum(1 for yt, yp in zip(y_true_has_risk, y_pred_has_risk, strict=True) if yt and yp)
    tn = sum(1 for yt, yp in zip(y_true_has_risk, y_pred_has_risk, strict=True) if not yt and not yp)
    fp = sum(1 for yt, yp in zip(y_true_has_risk, y_pred_has_risk, strict=True) if not yt and yp)
    fn = sum(1 for yt, yp in zip(y_true_has_risk, y_pred_has_risk, strict=True) if yt and not yp)

    sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 1.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    f1 = (2 * precision * sensitivity) / (precision + sensitivity) if (precision + sensitivity) > 0 else 0.0
    fnr = fn / (tp + fn) if (tp + fn) > 0 else 0.0

    faithfulness = 1.0
    if claim_supported_flags:
        faithfulness = sum(1 for s in claim_supported_flags if s) / len(claim_supported_flags)

    return EvaluationMetrics(
        total_scenarios=n,
        true_positives=tp,
        true_negatives=tn,
        false_positives=fp,
        false_negatives=fn,
        sensitivity=round(sensitivity, 4),
        specificity=round(specificity, 4),
        precision=round(precision, 4),
        f1_score=round(f1, 4),
        false_negative_rate=round(fnr, 4),
        claim_faithfulness_rate=round(faithfulness, 4),
    )
