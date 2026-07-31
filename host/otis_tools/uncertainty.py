from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Mapping


UNCERTAINTY_MODEL_VERSION = "phase4_uncertainty_budget_v1"
UNCERTAINTY_COMPONENT_FIELDS = (
    "count_quantization_standard_uncertainty_hz",
    "counter_aperture_standard_uncertainty_hz",
    "reference_standard_uncertainty_hz",
    "calibration_standard_uncertainty_hz",
    "model_standard_uncertainty_hz",
)
UNCERTAINTY_COMPONENT_REASON_CODES = {
    "count_quantization_standard_uncertainty_hz":
        "count_quantization_model_unavailable",
    "counter_aperture_standard_uncertainty_hz":
        "counter_aperture_unavailable",
    "reference_standard_uncertainty_hz":
        "reference_uncertainty_unavailable",
    "calibration_standard_uncertainty_hz":
        "calibration_uncertainty_unavailable",
    "model_standard_uncertainty_hz": "model_uncertainty_unavailable",
}
ALLOWED_CORRELATION_POLICIES = {
    "independent_root_sum_square",
    "single_component_no_correlation",
    "not_combined_missing_components",
}


def _canonical_model_payload(required_components: tuple[str, ...]) -> bytes:
    payload = {
        "combination_policy": "independent_root_sum_square",
        "required_components": list(required_components),
        "schema_version": 1,
        "version": UNCERTAINTY_MODEL_VERSION,
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")


DEFAULT_REQUIRED_COMPONENTS = UNCERTAINTY_COMPONENT_FIELDS
UNCERTAINTY_MODEL_HASH = hashlib.sha256(
    _canonical_model_payload(DEFAULT_REQUIRED_COMPONENTS)
).hexdigest()
UNCERTAINTY_MODEL_REF = (
    f"{UNCERTAINTY_MODEL_VERSION}#sha256:{UNCERTAINTY_MODEL_HASH}"
)


def uncertainty_model_ref(required_components: tuple[str, ...]) -> str:
    digest = hashlib.sha256(
        _canonical_model_payload(required_components)
    ).hexdigest()
    return f"{UNCERTAINTY_MODEL_VERSION}#sha256:{digest}"


@dataclass(frozen=True)
class UncertaintyResult:
    status: str
    reason_codes: tuple[str, ...]
    components: Mapping[str, float | None]
    combined_standard_uncertainty_hz: float | None
    coverage_factor: float | None
    expanded_uncertainty_hz: float | None
    correlation_policy: str
    model_ref: str


def evaluate_uncertainty(
    components: Mapping[str, float | None],
    *,
    estimate_available: bool,
    required_components: tuple[str, ...] = DEFAULT_REQUIRED_COMPONENTS,
    coverage_factor: float | None = None,
) -> UncertaintyResult:
    unknown = sorted(set(components) - set(UNCERTAINTY_COMPONENT_FIELDS))
    if unknown:
        raise ValueError(f"unknown uncertainty components: {', '.join(unknown)}")
    if not required_components or any(
        field not in UNCERTAINTY_COMPONENT_FIELDS for field in required_components
    ):
        raise ValueError("required_components must name supported components")
    normalized = {
        field: components.get(field) for field in UNCERTAINTY_COMPONENT_FIELDS
    }
    model_ref = uncertainty_model_ref(required_components)
    for field, value in normalized.items():
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError(f"{field} must be a finite non-negative value")
    if coverage_factor is not None and (
        not math.isfinite(coverage_factor) or coverage_factor <= 0
    ):
        raise ValueError("coverage_factor must be finite and positive")
    if not estimate_available:
        return UncertaintyResult(
            "unavailable",
            ("estimate_unavailable",),
            normalized,
            None,
            None,
            None,
            "not_combined_missing_components",
            model_ref,
        )
    missing = tuple(
        field for field in required_components if normalized[field] is None
    )
    if missing:
        return UncertaintyResult(
            "incomplete",
            tuple(UNCERTAINTY_COMPONENT_REASON_CODES[field] for field in missing),
            normalized,
            None,
            None,
            None,
            "not_combined_missing_components",
            model_ref,
        )
    values = [normalized[field] for field in required_components]
    assert all(value is not None for value in values)
    combined = math.sqrt(sum(float(value) ** 2 for value in values))
    correlation_policy = (
        "single_component_no_correlation"
        if len(required_components) == 1
        else "independent_root_sum_square"
    )
    return UncertaintyResult(
        "available",
        ("uncertainty_complete",),
        normalized,
        combined,
        coverage_factor,
        combined * coverage_factor if coverage_factor is not None else None,
        correlation_policy,
        model_ref,
    )
