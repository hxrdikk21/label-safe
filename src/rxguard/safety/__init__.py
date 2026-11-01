"""
Deterministic safety engine package.
Contains symbolic screening rules, clinical matchers, rule repository, and master orchestrator.
"""

from .allergies import AllergyScreeningEngine
from .contraindications import DCIScreeningEngine
from .ddi import DDIScreeningEngine
from .dfi import DFIScreeningEngine
from .engine import ClinicalSafetyReport, SafetyEngine
from .models import (
    AllergyRule,
    BaseSafetyRule,
    DCIRule,
    DDIRule,
    DFIRule,
    RuleStatus,
)
from .rules_db import SafetyRulesRepository, get_safety_rules_repo

__all__ = [
    "AllergyRule",
    "AllergyScreeningEngine",
    "BaseSafetyRule",
    "ClinicalSafetyReport",
    "DCIRule",
    "DCIScreeningEngine",
    "DDIRule",
    "DDIScreeningEngine",
    "DFIRule",
    "DFIScreeningEngine",
    "RuleStatus",
    "SafetyEngine",
    "SafetyRulesRepository",
    "get_safety_rules_repo",
]
