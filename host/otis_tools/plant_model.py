from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import argparse
import json
from typing import Any


MAX_FIRST_H1_AUTO_MIN_CODE = 0x7000
MAX_FIRST_H1_AUTO_MAX_CODE = 0x9000


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
        if isinstance(min_code, int) and min_code < MAX_FIRST_H1_AUTO_MIN_CODE:
            errors.append("dac.automatic_control_range_codes.min is below 0x7000")
        if isinstance(max_code, int) and max_code > MAX_FIRST_H1_AUTO_MAX_CODE:
            errors.append("dac.automatic_control_range_codes.max is above 0x9000")
        if isinstance(manual_range, dict):
            manual_min = manual_range.get("min")
            manual_max = manual_range.get("max")
            if isinstance(min_code, int) and isinstance(manual_min, int) and min_code < manual_min:
                errors.append("dac.automatic_control_range_codes.min is below manual_safe_range_codes.min")
            if isinstance(max_code, int) and isinstance(manual_max, int) and max_code > manual_max:
                errors.append("dac.automatic_control_range_codes.max is above manual_safe_range_codes.max")


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
    print(
        f"OK {args.path}: {model.model_id} v{model.model_version}, "
        f"automatic_control_range=0x{auto_min:04X}..0x{auto_max:04X}, "
        f"actuation_enabled={str(model.actuation_enabled).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
