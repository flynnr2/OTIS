from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import argparse
import json
from typing import Any

from .phase4_boundary_estimator import estimator_method_contract


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


def load_plant_model(path: Path | str) -> PlantModel:
    model_path = Path(path)
    with model_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    validate_plant_model(data)
    return PlantModel(path=model_path, data=data)


def validate_plant_model(data: dict[str, Any]) -> None:
    errors: list[str] = []
    _require(data, "schema_version", int, errors)
    _require(data, "model_id", str, errors)
    _require(data, "model_version", int, errors)

    if data.get("schema_version") != 1:
        errors.append(f"unsupported plant model schema_version: {data.get('schema_version')!r}")
    if isinstance(data.get("model_version"), int) and data["model_version"] < 1:
        errors.append("model_version must be a positive integer")

    for section in ("status", "oscillator", "hardware_topology", "dac", "control_path", "plant_response", "source_evidence"):
        _require(data, section, dict, errors)

    if errors:
        raise ValueError("; ".join(errors))

    _reject_empty_strings(data, errors)
    _validate_status(data["status"], errors)
    _validate_dac(data["dac"], errors)
    _validate_plant_response(data["plant_response"], errors)
    _validate_model_envelopes(data, errors)
    _validate_source_evidence(data["source_evidence"], errors)

    for field_name in ("invalidation_conditions", "unresolved_fields"):
        _require(data, field_name, list, errors)
    if isinstance(data.get("invalidation_conditions"), list) and not data["invalidation_conditions"]:
        errors.append("invalidation_conditions must not be empty")

    if errors:
        raise ValueError("; ".join(errors))


def _require(parent: dict[str, Any], key: str, expected_type: type, errors: list[str]) -> None:
    if key not in parent:
        errors.append(f"missing required field: {key}")
        return
    if not isinstance(parent[key], expected_type):
        errors.append(f"{key} must be {expected_type.__name__}")


def _reject_empty_strings(value: Any, errors: list[str], path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_empty_strings(child, errors, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_empty_strings(child, errors, f"{path}[{index}]")
    elif value == "":
        errors.append(f"{path} must be null when unknown, not an empty string")


def _validate_status(status: dict[str, Any], errors: list[str]) -> None:
    for key in ("control_ready", "actuation_enabled"):
        if not isinstance(status.get(key), bool):
            errors.append(f"status.{key} must be boolean")
    if status.get("control_ready"):
        errors.append("status.control_ready must remain false for H1 plant models")
    if status.get("actuation_enabled"):
        errors.append("status.actuation_enabled must remain false for H1 plant models")


def _validate_dac(dac: dict[str, Any], errors: list[str]) -> None:
    for key in ("nominal_code", "manual_preview_max_step_codes"):
        _check_code(dac.get(key), f"dac.{key}", errors)

    for key in ("manual_safe_range_codes", "automatic_control_range_codes"):
        range_data = dac.get(key)
        if not isinstance(range_data, dict):
            errors.append(f"dac.{key} must be an object")
            continue
        _check_code(range_data.get("min"), f"dac.{key}.min", errors)
        _check_code(range_data.get("max"), f"dac.{key}.max", errors)
        if isinstance(range_data.get("min"), int) and isinstance(range_data.get("max"), int):
            if range_data["min"] > range_data["max"]:
                errors.append(f"dac.{key}.min must be <= max")

    auto_range = dac.get("automatic_control_range_codes", {})
    manual_range = dac.get("manual_safe_range_codes", {})
    if isinstance(auto_range, dict):
        min_code = auto_range.get("min")
        max_code = auto_range.get("max")
        if isinstance(manual_range, dict):
            manual_min = manual_range.get("min")
            manual_max = manual_range.get("max")
            if isinstance(min_code, int) and isinstance(manual_min, int) and min_code < manual_min:
                errors.append("dac.automatic_control_range_codes.min is below manual_safe_range_codes.min")
            if isinstance(max_code, int) and isinstance(manual_max, int) and max_code > manual_max:
                errors.append("dac.automatic_control_range_codes.max is above manual_safe_range_codes.max")
        nominal_code = dac.get("nominal_code")
        if isinstance(nominal_code, int) and isinstance(min_code, int) and nominal_code < min_code:
            errors.append("dac.nominal_code is below automatic_control_range_codes.min")
        if isinstance(nominal_code, int) and isinstance(max_code, int) and nominal_code > max_code:
            errors.append("dac.nominal_code is above automatic_control_range_codes.max")


def _validate_plant_response(plant_response: dict[str, Any], errors: list[str]) -> None:
    slope = plant_response.get("local_slope")
    if not isinstance(slope, dict):
        errors.append("plant_response.local_slope must be an object")
        return

    sign = slope.get("sign")
    if sign not in {"positive", "negative", "unknown"}:
        errors.append("plant_response.local_slope.sign must be positive, negative, or unknown")
    hz_per_v = slope.get("hz_per_v")
    if hz_per_v is not None and not isinstance(hz_per_v, (int, float)):
        errors.append("plant_response.local_slope.hz_per_v must be numeric or null")
    if hz_per_v == 0:
        errors.append("plant_response.local_slope.hz_per_v must be null when unknown, not zero")
    if hz_per_v is not None and sign == "positive" and hz_per_v <= 0:
        errors.append("positive local_slope.sign requires hz_per_v > 0")
    if hz_per_v is not None and sign == "negative" and hz_per_v >= 0:
        errors.append("negative local_slope.sign requires hz_per_v < 0")

    crossing = plant_response.get("crossing_estimate")
    if crossing is not None:
        _validate_crossing_estimate(crossing, errors)

    applicability = plant_response.get("applicability")
    if applicability is not None:
        _validate_applicability(applicability, errors)


def _validate_crossing_estimate(crossing: Any, errors: list[str]) -> None:
    if not isinstance(crossing, dict):
        errors.append("plant_response.crossing_estimate must be an object")
        return

    for key in ("code", "code_min", "code_max"):
        _check_code(crossing.get(key), f"plant_response.crossing_estimate.{key}", errors)

    code = crossing.get("code")
    code_min = crossing.get("code_min")
    code_max = crossing.get("code_max")
    if isinstance(code_min, int) and isinstance(code_max, int) and code_min > code_max:
        errors.append("plant_response.crossing_estimate.code_min must be <= code_max")
    if isinstance(code, int) and isinstance(code_min, int) and code < code_min:
        errors.append("plant_response.crossing_estimate.code is below code_min")
    if isinstance(code, int) and isinstance(code_max, int) and code > code_max:
        errors.append("plant_response.crossing_estimate.code is above code_max")

    target_hz = crossing.get("target_frequency_hz")
    if not isinstance(target_hz, (int, float)) or target_hz <= 0:
        errors.append("plant_response.crossing_estimate.target_frequency_hz must be positive")


def _validate_applicability(applicability: Any, errors: list[str]) -> None:
    if not isinstance(applicability, dict):
        errors.append("plant_response.applicability must be an object")
        return
    if applicability.get("mode") != "observe_only":
        errors.append("plant_response.applicability.mode must be observe_only for H1 plant models")
    method_contract = applicability.get("estimator_method_contract")
    if method_contract is not None and not isinstance(method_contract, dict):
        errors.append(
            "plant_response.applicability.estimator_method_contract must be an object"
        )
    elif isinstance(method_contract, dict):
        expected_contract = estimator_method_contract()
        if method_contract.get("method_definition_hash") != expected_contract[
            "method_definition_hash"
        ]:
            errors.append(
                "plant_response.applicability.estimator_method_contract "
                "has an unknown method_definition_hash"
            )
    range_data = applicability.get("dac_code_range")
    if not isinstance(range_data, dict):
        errors.append("plant_response.applicability.dac_code_range must be an object")
        return
    _check_code(range_data.get("min"), "plant_response.applicability.dac_code_range.min", errors)
    _check_code(range_data.get("max"), "plant_response.applicability.dac_code_range.max", errors)
    if isinstance(range_data.get("min"), int) and isinstance(range_data.get("max"), int):
        if range_data["min"] > range_data["max"]:
            errors.append("plant_response.applicability.dac_code_range.min must be <= max")


def _validate_model_envelopes(data: dict[str, Any], errors: list[str]) -> None:
    dac = data["dac"]
    plant_response = data["plant_response"]
    auto_range = dac.get("automatic_control_range_codes")
    manual_range = dac.get("manual_safe_range_codes")
    crossing = plant_response.get("crossing_estimate")
    applicability = plant_response.get("applicability")
    if data.get("model_version", 0) >= 4 and isinstance(applicability, dict):
        if not isinstance(applicability.get("estimator_method_contract"), dict):
            errors.append(
                "model_version >= 4 requires "
                "plant_response.applicability.estimator_method_contract"
            )
    if not isinstance(auto_range, dict) or not isinstance(manual_range, dict):
        return

    auto_min = auto_range.get("min")
    auto_max = auto_range.get("max")
    if isinstance(crossing, dict) and isinstance(auto_min, int) and isinstance(auto_max, int):
        crossing_min = crossing.get("code_min")
        crossing_max = crossing.get("code_max")
        if isinstance(crossing_min, int) and auto_min > crossing_min:
            errors.append("dac.automatic_control_range_codes.min does not contain crossing_estimate.code_min")
        if isinstance(crossing_max, int) and auto_max < crossing_max:
            errors.append("dac.automatic_control_range_codes.max does not contain crossing_estimate.code_max")

    if isinstance(applicability, dict):
        applicable_range = applicability.get("dac_code_range")
        if isinstance(applicable_range, dict):
            applicable_min = applicable_range.get("min")
            applicable_max = applicable_range.get("max")
            manual_min = manual_range.get("min")
            manual_max = manual_range.get("max")
            if isinstance(applicable_min, int) and isinstance(manual_min, int) and applicable_min < manual_min:
                errors.append("plant_response.applicability.dac_code_range.min is below manual_safe_range_codes.min")
            if isinstance(applicable_max, int) and isinstance(manual_max, int) and applicable_max > manual_max:
                errors.append("plant_response.applicability.dac_code_range.max is above manual_safe_range_codes.max")
            if isinstance(auto_min, int) and isinstance(applicable_min, int) and auto_min < applicable_min:
                errors.append("dac.automatic_control_range_codes.min is below the model applicability range")
            if isinstance(auto_max, int) and isinstance(applicable_max, int) and auto_max > applicable_max:
                errors.append("dac.automatic_control_range_codes.max is above the model applicability range")


def _validate_source_evidence(source_evidence: dict[str, Any], errors: list[str]) -> None:
    run_ids = source_evidence.get("source_run_ids")
    artifacts = source_evidence.get("source_artifacts")
    if not isinstance(run_ids, list) or not run_ids:
        errors.append("source_evidence.source_run_ids must be a non-empty list")
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("source_evidence.source_artifacts must be a non-empty list")
    if not isinstance(source_evidence.get("source_commits"), dict):
        errors.append("source_evidence.source_commits must be an object")
    if not isinstance(source_evidence.get("source_versions"), dict):
        errors.append("source_evidence.source_versions must be an object")


def _check_code(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, int):
        errors.append(f"{path} must be an integer DAC code")
    elif not 0 <= value <= 0xFFFF:
        errors.append(f"{path} must be in 0..65535")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an OTIS plant model.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)

    try:
        model = load_plant_model(args.path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR {args.path}: {exc}")
        return 1

    auto_min, auto_max = model.automatic_control_range
    crossing = f"0x{model.crossing_code:04X}" if model.crossing_code is not None else "unavailable"
    print(
        f"OK {args.path}: {model.model_id} v{model.model_version}, "
        f"nominal_code=0x{model.nominal_code:04X}, crossing_code={crossing}, "
        f"automatic_control_range=0x{auto_min:04X}..0x{auto_max:04X}, "
        f"actuation_enabled={str(model.actuation_enabled).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
