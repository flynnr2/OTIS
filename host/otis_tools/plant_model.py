from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import argparse
import hashlib
import json
import math
from typing import Any, Mapping

from jsonschema import Draft202012Validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLANT_MODEL_SCHEMAS = {
    1: REPOSITORY_ROOT / "schemas" / "plant_model_v1.schema.json",
}
@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceAvailability:
    available: bool
    available_artifacts: tuple[str, ...]
    unavailable_artifacts: tuple[str, ...]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelApplicabilityContext:
    hardware_topology_id: str | None
    measurement_backend: str | None
    estimator_method: Mapping[str, object] | None
    dac_code: int | None
    source_run_id: str | None = None
    count_sequence: int | None = None
    gate_duration_s: float | None = None
    temperature_c: float | None = None
    required_model_version: int | None = None


@dataclass(frozen=True)
class ApplicabilityAssessment:
    applicable: bool
    reasons: tuple[str, ...] = ()
    unverified_conditions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ControlEligibility:
    eligible: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlantModel:
    path: Path
    data: dict[str, Any]

    @property
    def model_id(self) -> str:
        return str(self.data["model_id"])

    @property
    def model_version(self) -> int:
        return int(self.data["model_version"])

    @property
    def automatic_control_range(self) -> tuple[int, int]:
        range_data = self.data["dac"]["automatic_control_range_codes"]
        return int(range_data["min"]), int(range_data["max"])

    @property
    def nominal_code(self) -> int:
        return int(self.data["dac"]["nominal_code"])

    @property
    def crossing_code(self) -> int | None:
        crossing = self.data["plant_response"].get("crossing_estimate")
        return int(crossing["code"]) if isinstance(crossing, dict) else None

    @property
    def applicability_range(self) -> tuple[int, int] | None:
        applicability = self.data["plant_response"].get("applicability")
        if not isinstance(applicability, dict):
            return None
        range_data = applicability.get("dac_code_range")
        if not isinstance(range_data, dict):
            return None
        return int(range_data["min"]), int(range_data["max"])

    @property
    def actuation_enabled(self) -> bool:
        return bool(self.data["status"]["actuation_enabled"])

    @property
    def control_ready(self) -> bool:
        return bool(self.data["status"]["control_ready"])


@lru_cache(maxsize=None)
def _schema_validator(schema_version: int) -> Draft202012Validator:
    try:
        schema_path = PLANT_MODEL_SCHEMAS[schema_version]
    except KeyError as exc:
        raise ValueError(
            f"unsupported plant model schema_version: {schema_version!r}"
        ) from exc
    with schema_path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _json_path(parts: tuple[object, ...]) -> str:
    path = "$"
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}"
    return path


def estimator_contract_definition_hash(
    contract: Mapping[str, object],
) -> str:
    definition = {
        key: value
        for key, value in contract.items()
        if key != "method_definition_hash"
    }
    canonical = json.dumps(
        definition,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_plant_model_structure(data: object) -> ValidationResult:
    """Validate only the versioned JSON structure.

    JSON Schema is the sole structural authority. Runtime semantic policy must
    not add fields, required keys, or type rules that contradict this result.
    """

    if not isinstance(data, dict):
        return ValidationResult(False, ("$: plant model must be an object",))
    schema_version = data.get("schema_version")
    if type(schema_version) is not int:
        return ValidationResult(
            False, ("$.schema_version: must be an integer",)
        )
    try:
        validator = _schema_validator(schema_version)
    except ValueError as exc:
        return ValidationResult(False, (str(exc),))
    errors = tuple(
        f"{_json_path(tuple(error.absolute_path))}: {error.message}"
        for error in sorted(
            validator.iter_errors(data),
            key=lambda item: (
                tuple(str(part) for part in item.absolute_path),
                item.message,
            ),
        )
    )
    return ValidationResult(not errors, errors)


def validate_plant_model_semantics(data: dict[str, Any]) -> ValidationResult:
    """Validate cross-field meaning without redefining JSON structure."""

    structural = validate_plant_model_structure(data)
    if not structural.valid:
        return ValidationResult(
            False,
            (
                "semantic validation requires a structurally valid model",
                *structural.errors,
            ),
        )

    errors: list[str] = []
    _reject_non_finite_numbers(data, errors)
    _validate_status(data["status"], errors)
    _validate_dac(data["dac"], errors)
    _validate_plant_response(
        data["plant_response"], int(data["model_version"]), errors
    )
    _validate_model_envelopes(data, errors)
    _validate_source_evidence(data["source_evidence"], errors)
    return ValidationResult(not errors, tuple(errors))


def validate_plant_model(data: dict[str, Any]) -> None:
    structural = validate_plant_model_structure(data)
    if not structural.valid:
        raise ValueError(
            "structural validation failed: " + "; ".join(structural.errors)
        )
    semantic = validate_plant_model_semantics(data)
    if not semantic.valid:
        raise ValueError(
            "semantic validation failed: " + "; ".join(semantic.errors)
        )


def load_plant_model(path: Path | str) -> PlantModel:
    model_path = Path(path)
    with model_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("$: plant model must be an object")
    validate_plant_model(data)
    return PlantModel(path=model_path, data=data)


def assess_evidence_availability(
    model: PlantModel,
    repository_root: Path | str = REPOSITORY_ROOT,
) -> EvidenceAvailability:
    """Report whether every declared source artifact is locally available.

    Missing evidence does not make the JSON artifact structurally or
    semantically invalid. It does make the model ineligible for control.
    """

    root = Path(repository_root).resolve()
    available: list[str] = []
    unavailable: list[str] = []
    errors: list[str] = []
    artifacts = model.data["source_evidence"]["source_artifacts"]
    source_hashes = model.data["source_evidence"].get("source_hashes", {})
    for artifact in artifacts:
        candidate = (root / artifact).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            errors.append(f"source artifact escapes repository root: {artifact}")
            continue
        if candidate.is_file():
            expected_hash = source_hashes.get(artifact)
            if expected_hash is not None:
                actual_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
                if actual_hash != expected_hash:
                    errors.append(f"source artifact hash mismatch: {artifact}")
                    continue
            available.append(artifact)
        else:
            unavailable.append(artifact)
    return EvidenceAvailability(
        available=not errors and not unavailable,
        available_artifacts=tuple(available),
        unavailable_artifacts=tuple(unavailable),
        errors=tuple(errors),
    )


def assess_model_applicability(
    model: PlantModel,
    context: ModelApplicabilityContext,
) -> ApplicabilityAssessment:
    """Compare a valid model with a concrete use context.

    Unknown environmental observations are exposed separately from definite
    mismatches. They do not turn structural or semantic validity into an
    applicability failure, but control eligibility treats them conservatively.
    """

    response = model.data["plant_response"]
    applicability = response.get("applicability")
    if not isinstance(applicability, dict):
        return ApplicabilityAssessment(
            False, ("plant_model_applicability_unavailable",)
        )

    reasons: list[str] = []
    unverified: list[str] = []
    if (
        context.required_model_version is not None
        and model.model_version != context.required_model_version
    ):
        reasons.append(
            f"plant_model_version_not_{context.required_model_version}"
        )
    if context.hardware_topology_id is None:
        reasons.append("plant_model_input_identity_unavailable")
    elif (
        context.hardware_topology_id
        != model.data["hardware_topology"]["topology_id"]
    ):
        reasons.append("plant_model_topology_mismatch")

    expected_backend = applicability["measurement_backend"]
    if context.measurement_backend is None:
        if "plant_model_input_identity_unavailable" not in reasons:
            reasons.append("plant_model_input_identity_unavailable")
    elif context.measurement_backend != expected_backend:
        reasons.append("plant_model_backend_mismatch")

    expected_method = applicability.get("estimator_method_contract")
    if expected_method is None:
        reasons.append("plant_model_estimator_method_unavailable")
    elif context.estimator_method is None:
        reasons.append("plant_model_estimator_method_unavailable")
    elif dict(context.estimator_method) != expected_method:
        reasons.append("plant_model_estimator_method_mismatch")

    range_data = applicability["dac_code_range"]
    if context.dac_code is None:
        reasons.append("dac_state_unavailable")
    elif not range_data["min"] <= context.dac_code <= range_data["max"]:
        reasons.append("input_outside_model_applicability")

    source_run_ids = model.data["source_evidence"]["source_run_ids"]
    replaying_model_source = (
        context.source_run_id is not None
        and any(
            context.source_run_id == source_run_id
            or source_run_id.endswith(f"/{context.source_run_id}")
            or context.source_run_id.endswith(f"/{source_run_id}")
            for source_run_id in source_run_ids
        )
    )
    excluded = set(applicability["excluded_count_sequences"])
    if (
        replaying_model_source
        and context.count_sequence is not None
        and context.count_sequence in excluded
    ):
        reasons.append("plant_model_excluded_count_sequence")

    if context.gate_duration_s is None:
        unverified.append("gate_duration_not_observed")
    elif not math.isclose(
        context.gate_duration_s,
        float(applicability["gate_duration_s"]),
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        reasons.append("plant_model_gate_duration_mismatch")

    temperature = applicability["temperature_range_c"]
    if context.temperature_c is None:
        unverified.append("temperature_not_observed")
    elif not (
        temperature["min_c"]
        <= context.temperature_c
        <= temperature["max_c"]
    ):
        reasons.append("input_outside_model_temperature_range")

    return ApplicabilityAssessment(
        applicable=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        unverified_conditions=tuple(unverified),
    )


def assess_control_eligibility(
    model: PlantModel,
    *,
    evidence: EvidenceAvailability,
    applicability: ApplicabilityAssessment,
) -> ControlEligibility:
    """Apply the conservative active-control gate to an already valid model."""

    reasons: list[str] = []
    if not model.control_ready:
        reasons.append("plant_model_not_control_ready")
    if not model.actuation_enabled:
        reasons.append("plant_model_actuation_disabled")
    if not evidence.available:
        reasons.append("plant_model_source_evidence_unavailable")
    if not applicability.applicable:
        reasons.extend(applicability.reasons)
    if applicability.unverified_conditions:
        reasons.append("plant_model_applicability_conditions_unverified")
    if model.data["unresolved_fields"]:
        reasons.append("plant_model_has_unresolved_fields")
    return ControlEligibility(
        eligible=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _reject_non_finite_numbers(
    value: Any, errors: list[str], path: str = "$"
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_non_finite_numbers(child, errors, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_non_finite_numbers(child, errors, f"{path}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{path} must be finite")


def _validate_status(status: dict[str, Any], errors: list[str]) -> None:
    if status["control_ready"]:
        errors.append("status.control_ready must remain false for the current plant model")
    if status["actuation_enabled"]:
        errors.append("status.actuation_enabled must remain false for the current plant model")


def _validate_dac(dac: dict[str, Any], errors: list[str]) -> None:
    for key in ("manual_safe_range_codes", "automatic_control_range_codes"):
        range_data = dac[key]
        if range_data["min"] > range_data["max"]:
            errors.append(f"dac.{key}.min must be <= max")

    auto_range = dac["automatic_control_range_codes"]
    manual_range = dac["manual_safe_range_codes"]
    if auto_range["min"] < manual_range["min"]:
        errors.append(
            "dac.automatic_control_range_codes.min is below "
            "manual_safe_range_codes.min"
        )
    if auto_range["max"] > manual_range["max"]:
        errors.append(
            "dac.automatic_control_range_codes.max is above "
            "manual_safe_range_codes.max"
        )
    if dac["nominal_code"] < auto_range["min"]:
        errors.append("dac.nominal_code is below automatic_control_range_codes.min")
    if dac["nominal_code"] > auto_range["max"]:
        errors.append("dac.nominal_code is above automatic_control_range_codes.max")


def _validate_plant_response(
    plant_response: dict[str, Any],
    model_version: int,
    errors: list[str],
) -> None:
    slope = plant_response["local_slope"]
    sign = slope["sign"]
    for key in ("hz_per_v", "ppm_per_v", "hz_per_code", "ppm_per_code"):
        value = slope[key]
        if value == 0:
            errors.append(
                f"plant_response.local_slope.{key} must be null when unknown, "
                "not zero"
            )
        if value is not None and sign == "positive" and value <= 0:
            errors.append(f"positive local_slope.sign requires {key} > 0")
        if value is not None and sign == "negative" and value >= 0:
            errors.append(f"negative local_slope.sign requires {key} < 0")
    if sign == "unknown" and any(
        slope[key] is not None
        for key in ("hz_per_v", "ppm_per_v", "hz_per_code", "ppm_per_code")
    ):
        errors.append("unknown local_slope.sign requires all slope values to be null")

    uncertainty = slope["uncertainty"]
    minimum = uncertainty["hz_per_v_min"]
    maximum = uncertainty["hz_per_v_max"]
    if minimum is not None and maximum is not None and minimum > maximum:
        errors.append(
            "plant_response.local_slope.uncertainty.hz_per_v_min must be <= "
            "hz_per_v_max"
        )

    crossing = plant_response.get("crossing_estimate")
    applicability = plant_response.get("applicability")
    repeatability = plant_response.get("repeatability_evidence")
    if model_version >= 3:
        for key, value in (
            ("crossing_estimate", crossing),
            ("repeatability_evidence", repeatability),
            ("applicability", applicability),
        ):
            if not isinstance(value, dict):
                errors.append(f"model_version >= 3 requires plant_response.{key}")
        for key in ("hz_per_v_stdev", "hz_per_v_iqr"):
            if uncertainty.get(key) is None:
                errors.append(
                    f"model_version >= 3 requires "
                    f"plant_response.local_slope.uncertainty.{key}"
                )

    if isinstance(crossing, dict):
        _validate_crossing_estimate(crossing, errors)
    if isinstance(applicability, dict):
        _validate_applicability(applicability, model_version, errors)


def _validate_crossing_estimate(
    crossing: dict[str, Any], errors: list[str]
) -> None:
    if crossing["code_min"] > crossing["code_max"]:
        errors.append("plant_response.crossing_estimate.code_min must be <= code_max")
    if crossing["code"] < crossing["code_min"]:
        errors.append("plant_response.crossing_estimate.code is below code_min")
    if crossing["code"] > crossing["code_max"]:
        errors.append("plant_response.crossing_estimate.code is above code_max")


def _validate_applicability(
    applicability: dict[str, Any],
    model_version: int,
    errors: list[str],
) -> None:
    range_data = applicability["dac_code_range"]
    if range_data["min"] > range_data["max"]:
        errors.append("plant_response.applicability.dac_code_range.min must be <= max")

    temperature = applicability["temperature_range_c"]
    if temperature["min_c"] > temperature["max_c"]:
        errors.append(
            "plant_response.applicability.temperature_range_c.min_c must be <= max_c"
        )

    method_contract = applicability.get("estimator_method_contract")
    if model_version >= 4:
        if not isinstance(method_contract, dict):
            errors.append(
                "model_version >= 4 requires "
                "plant_response.applicability.estimator_method_contract"
            )
    if isinstance(method_contract, dict):
        if (
            applicability["measurement_backend"]
            != method_contract["measurement_backend"]
        ):
            errors.append(
                "plant_response.applicability.measurement_backend must equal "
                "estimator_method_contract.measurement_backend"
            )
        try:
            expected_hash = estimator_contract_definition_hash(method_contract)
        except (TypeError, ValueError):
            expected_hash = None
        if expected_hash is None:
            errors.append(
                "plant_response.applicability.estimator_method_contract "
                "definition must have a canonical finite JSON representation"
            )
        elif method_contract["method_definition_hash"] != expected_hash:
            errors.append(
                "plant_response.applicability.estimator_method_contract."
                "method_definition_hash does not match its contract definition"
            )
        if (
            method_contract["reference_interval_min_s"]
            > method_contract["reference_interval_max_s"]
        ):
            errors.append(
                "plant_response.applicability.estimator_method_contract."
                "reference_interval_min_s must be <= reference_interval_max_s"
            )


def _validate_model_envelopes(
    data: dict[str, Any], errors: list[str]
) -> None:
    dac = data["dac"]
    plant_response = data["plant_response"]
    auto_range = dac["automatic_control_range_codes"]
    manual_range = dac["manual_safe_range_codes"]
    crossing = plant_response.get("crossing_estimate")
    applicability = plant_response.get("applicability")

    if isinstance(crossing, dict):
        if auto_range["min"] > crossing["code_min"]:
            errors.append(
                "dac.automatic_control_range_codes.min does not contain "
                "crossing_estimate.code_min"
            )
        if auto_range["max"] < crossing["code_max"]:
            errors.append(
                "dac.automatic_control_range_codes.max does not contain "
                "crossing_estimate.code_max"
            )

    if isinstance(applicability, dict):
        applicable_range = applicability["dac_code_range"]
        if applicable_range["min"] < manual_range["min"]:
            errors.append(
                "plant_response.applicability.dac_code_range.min is below "
                "manual_safe_range_codes.min"
            )
        if applicable_range["max"] > manual_range["max"]:
            errors.append(
                "plant_response.applicability.dac_code_range.max is above "
                "manual_safe_range_codes.max"
            )
        if auto_range["min"] < applicable_range["min"]:
            errors.append(
                "dac.automatic_control_range_codes.min is below the model "
                "applicability range"
            )
        if auto_range["max"] > applicable_range["max"]:
            errors.append(
                "dac.automatic_control_range_codes.max is above the model "
                "applicability range"
            )


def _validate_source_evidence(
    source_evidence: dict[str, Any], errors: list[str]
) -> None:
    source_hashes = source_evidence.get("source_hashes")
    if source_hashes is not None:
        artifacts = set(source_evidence["source_artifacts"])
        hashed = set(source_hashes)
        if artifacts != hashed:
            errors.append(
                "source_evidence.source_hashes keys must exactly match source_artifacts"
            )
    commits = source_evidence["source_commits"]
    if not any(value is not None for value in commits.values()):
        errors.append("source_evidence.source_commits must contain a known commit")
    versions = source_evidence["source_versions"]
    if not any(value is not None for value in versions.values()):
        errors.append("source_evidence.source_versions must contain a known version")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an OTIS plant model.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)

    try:
        model = load_plant_model(args.path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR {args.path}: {exc}")
        return 1

    evidence = assess_evidence_availability(model)
    auto_min, auto_max = model.automatic_control_range
    crossing = (
        f"0x{model.crossing_code:04X}"
        if model.crossing_code is not None
        else "unavailable"
    )
    evidence_state = "available" if evidence.available else "partial"
    print(
        f"OK {args.path}: structural=valid, semantic=valid, "
        f"evidence={evidence_state}, {model.model_id} v{model.model_version}, "
        f"nominal_code=0x{model.nominal_code:04X}, crossing_code={crossing}, "
        f"automatic_control_range=0x{auto_min:04X}..0x{auto_max:04X}, "
        f"control_ready={str(model.control_ready).lower()}, "
        f"actuation_enabled={str(model.actuation_enabled).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
