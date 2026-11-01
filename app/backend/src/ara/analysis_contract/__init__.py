"""Executable Linting/Merge contract 0.1.0, independent of application services."""

from .models import AnalysisRequest, AnalysisResult, ValidatedAnalysis
from .validation import ContractValidationError, validate_request, validate_result

__all__ = [
    "AnalysisRequest",
    "AnalysisResult",
    "ContractValidationError",
    "ValidatedAnalysis",
    "json_schemas",
    "validate_request",
    "validate_result",
]


def json_schemas() -> dict:
    """Return fresh schemas; saving schema artifacts is a development operation."""
    return {
        "request": AnalysisRequest.model_json_schema(),
        "result": AnalysisResult.model_json_schema(),
    }
