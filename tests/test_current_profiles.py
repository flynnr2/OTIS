from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
PROFILE_SCHEMA_PAIRS = (
    (
        "profiles/discipline/adaptive_hybrid_regulation_v1.json",
        "schemas/adaptive_hybrid_regulation_v1.schema.json",
    ),
    (
        "profiles/estimators/pps_gated_frequency_estimator_v1.json",
        "schemas/pps_gated_frequency_estimator_v1.schema.json",
    ),
    (
        "profiles/estimators/relative_phase_estimator_v1.json",
        "schemas/relative_phase_estimator_v1.schema.json",
    ),
    (
        "profiles/discipline/response_classification_v1.json",
        "schemas/response_classification_v1.schema.json",
    ),
    (
        "profiles/plant_models/pps_gated_oscillator_plant_v1.json",
        "schemas/plant_model_v1.schema.json",
    ),
)


def _read(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _validation_errors(profile_path: str, schema_path: str, profile: dict) -> list:
    validator = Draft202012Validator(_read(schema_path))
    return sorted(
        validator.iter_errors(profile),
        key=lambda error: tuple(str(part) for part in error.path),
    )


def _nested(document: dict, path: tuple[str, ...]) -> dict:
    value = document
    for part in path:
        value = value[part]
    assert isinstance(value, dict)
    return value


def test_current_profiles_validate_against_current_schemas() -> None:
    for profile_path, schema_path in PROFILE_SCHEMA_PAIRS:
        errors = _validation_errors(profile_path, schema_path, _read(profile_path))
        assert not errors, f"{profile_path}: {[error.message for error in errors]}"


@pytest.mark.parametrize(
    ("profile_path", "schema_path", "object_path"),
    (
        (*PROFILE_SCHEMA_PAIRS[0], ("frequency_control", "authority")),
        (*PROFILE_SCHEMA_PAIRS[1], ("authoritative_policy",)),
        (*PROFILE_SCHEMA_PAIRS[2], ("epoch_and_reset",)),
        (*PROFILE_SCHEMA_PAIRS[3], ("authority",)),
        (*PROFILE_SCHEMA_PAIRS[4], ("topology",)),
    ),
)
def test_current_profile_schemas_reject_nested_extra_fields(
    profile_path: str,
    schema_path: str,
    object_path: tuple[str, ...],
) -> None:
    profile = deepcopy(_read(profile_path))
    _nested(profile, object_path)["unexpected_authority_escape"] = True

    assert _validation_errors(profile_path, schema_path, profile)


@pytest.mark.parametrize(
    ("profile_path", "schema_path", "object_path", "field"),
    (
        (*PROFILE_SCHEMA_PAIRS[0], ("frequency_control", "authority"), "arming_required"),
        (*PROFILE_SCHEMA_PAIRS[1], ("authoritative_policy",), "fresh_support_recovery_time_s"),
        (*PROFILE_SCHEMA_PAIRS[2], ("epoch_and_reset",), "preserve_raw_epoch_on"),
        (*PROFILE_SCHEMA_PAIRS[3], ("authority",), "automatic_restore"),
        (*PROFILE_SCHEMA_PAIRS[4], ("topology",), "external_event_authority"),
    ),
)
def test_current_profile_schemas_reject_missing_nested_fields(
    profile_path: str,
    schema_path: str,
    object_path: tuple[str, ...],
    field: str,
) -> None:
    profile = deepcopy(_read(profile_path))
    del _nested(profile, object_path)[field]

    assert _validation_errors(profile_path, schema_path, profile)


@pytest.mark.parametrize(
    ("profile_path", "schema_path", "object_path", "field", "wrong_value"),
    (
        (
            *PROFILE_SCHEMA_PAIRS[0],
            ("frequency_control", "authority"),
            "D10_external_event_excluded",
            False,
        ),
        (
            *PROFILE_SCHEMA_PAIRS[1],
            ("invalidation_policy",),
            "D10_external_event_anomaly_resets_estimator",
            True,
        ),
        (
            *PROFILE_SCHEMA_PAIRS[2],
            ("epoch_and_reset",),
            "preserve_raw_epoch_on",
            ["healthy_dac_epoch_transition", "visible_phase_step_with_valid_continuity"],
        ),
        (
            *PROFILE_SCHEMA_PAIRS[3],
            ("authority",),
            "D10_external_event_required_for_response_classification",
            True,
        ),
        (
            *PROFILE_SCHEMA_PAIRS[4],
            ("topology",),
            "external_event_authority",
            True,
        ),
    ),
)
def test_current_profile_schemas_reject_wrong_authority_semantics(
    profile_path: str,
    schema_path: str,
    object_path: tuple[str, ...],
    field: str,
    wrong_value: object,
) -> None:
    profile = deepcopy(_read(profile_path))
    _nested(profile, object_path)[field] = wrong_value

    assert _validation_errors(profile_path, schema_path, profile)


def test_adaptive_policy_is_duration_independent_and_topology_exact() -> None:
    policy = _read("profiles/discipline/adaptive_hybrid_regulation_v1.json")
    serialized = json.dumps(policy, sort_keys=True).lower()
    assert policy["policy_id"] == "OTIS_ADAPTIVE_HYBRID_REGULATION_V1"
    assert "duration" not in serialized
    assert "259200" not in serialized
    assert policy["topology"]["reference_input"] == "D14_authoritative_PPS"
    assert policy["topology"]["oscillator_count_input"] == (
        "D8_authoritative_oscillator_count"
    )
    assert policy["topology"]["external_event_input"] == (
        "D10_optional_EVT_zero_reference_and_control_authority"
    )


def test_profiles_directory_contains_only_current_semantic_inputs() -> None:
    assert {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "profiles").rglob("*")
        if path.is_file()
    } == {
        "profiles/discipline/adaptive_hybrid_regulation_v1.json",
        "profiles/discipline/response_classification_v1.json",
        "profiles/estimators/pps_gated_frequency_estimator_v1.json",
        "profiles/estimators/relative_phase_estimator_v1.json",
        "profiles/plant_models/pps_gated_oscillator_plant_v1.json",
    }
