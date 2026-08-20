from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.firmware_matrix import (
    DEFAULT_MATRIX,
    MatrixError,
    _selected_profiles,
    configuration_hash,
    configuration_payload,
    load_matrix,
)


CURRENT_PROFILES = {
    "cx319_tight_lower",
    "cx319_tight_upper",
    "cx319_range_map_part_a",
    "cx319_range_part_b_lower",
    "cx319_range_part_b_upper",
    "cx319_range_part_b_upper_completion",
    "cx320_active_hybrid",
}
CURRENT_GUARDS = {
    "invalid_cx320_active_hybrid_parameters",
    "invalid_active_missing_gnss",
    "invalid_gnss_uart_tx_enabled",
    "invalid_cx319_lower_parameters",
    "invalid_pps_ratio_with_pio_capture",
    "invalid_pseudo_pps_nonisolated_resources",
}


def _profile(matrix: dict, identifier: str) -> dict:
    return next(item for item in matrix["profiles"] if item["id"] == identifier)


def test_matrix_contains_only_current_cx319_cx320_profiles_and_guards() -> None:
    matrix = load_matrix()
    profiles = matrix["profiles"]
    assert {item["id"] for item in profiles} == CURRENT_PROFILES | CURRENT_GUARDS
    assert len(profiles) == 13
    assert {item["lifecycle"] for item in profiles} == {
        "keep_active",
        "keep_compile_only",
    }
    assert not any(
        token in item["id"]
        for item in profiles
        for token in ("h0", "h1", "phase4", "phase5", "cx317", "cx318")
    )


def test_verification_tiers_are_explicit_and_small() -> None:
    matrix = load_matrix()
    assert [item["id"] for item in _selected_profiles(
        matrix, [], False, verification_tier="fast"
    )] == [
        "cx319_tight_lower",
        "cx319_range_map_part_a",
        "cx319_range_part_b_lower",
        "cx319_range_part_b_upper",
        "cx319_range_part_b_upper_completion",
        "cx320_active_hybrid",
    ]
    assert {item["id"] for item in _selected_profiles(
        matrix, [], False, verification_tier="campaign"
    )} == CURRENT_PROFILES
    assert {item["id"] for item in _selected_profiles(
        matrix, [], False, verification_tier="release"
    )} == CURRENT_PROFILES | CURRENT_GUARDS
    assert {item["id"] for item in _selected_profiles(
        matrix, [], False, verification_tier="bench"
    )} == CURRENT_PROFILES


@pytest.mark.parametrize(
    ("identifier", "campaign", "start_code"),
    [
        ("cx319_tight_lower", "OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_LOWER", "0xA808u"),
        ("cx319_tight_upper", "OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_UPPER", "0xA848u"),
    ],
)
def test_current_profiles_freeze_the_cx319_envelope(
    identifier: str, campaign: str, start_code: str
) -> None:
    profile = _profile(load_matrix(), identifier)
    defines = profile["defines"]
    assert profile["expect"] == "pass"
    assert defines["OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW"] == "1"
    assert defines["OTIS_ENABLE_CX317_BOUNDED_ACTIVE"] == "1"
    assert defines["OTIS_ENABLE_CX318_STAGE5_PREVIEW"] == "0"
    assert defines["OTIS_CX317_ACTIVE_CAMPAIGN"] == campaign
    assert defines["OTIS_CX317_ACTIVE_START_CODE"] == start_code
    assert defines["OTIS_DAC_MIN_CODE"] == "0xA800u"
    assert defines["OTIS_DAC_MAX_CODE"] == "0xAB00u"
    assert defines["OTIS_CX317_ACTIVE_CORRECTION_LIMIT"] == "4u"
    assert defines["OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES"] == "84u"
    assert defines["OTIS_CX317_DECISION_CADENCE_S"] == "1800u"


def test_current_cx320_profile_freezes_one_active_hybrid_envelope() -> None:
    profile = _profile(load_matrix(), "cx320_active_hybrid")
    defines = profile["defines"]
    assert profile["expect"] == "pass"
    assert defines["OTIS_ENABLE_CX320_ACTIVE_HYBRID"] == "1"
    assert defines["OTIS_ENABLE_CX317_BOUNDED_ACTIVE"] == "1"
    assert defines["OTIS_CX317_ACTIVE_CAMPAIGN"] == (
        "OTIS_CX317_ACTIVE_CAMPAIGN_CX320_ACTIVE_HYBRID"
    )
    assert defines["OTIS_CX317_ACTIVE_START_CODE"] == "0xA83Cu"
    assert defines["OTIS_CX317_ACTIVE_CORRECTION_LIMIT"] == "4u"
    assert defines["OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES"] == "84u"
    assert defines["OTIS_CX317_MINIMUM_APPLIED_CADENCE_S"] == "1800u"


def test_expected_failures_are_release_only_current_guards() -> None:
    matrix = load_matrix()
    for identifier in CURRENT_GUARDS:
        profile = _profile(matrix, identifier)
        assert profile["expect"] == "fail"
        assert profile["verification_tiers"] == ["release"]
        assert profile["lifecycle"] == "keep_compile_only"
        assert profile["expected_error"]


def test_matrix_rejects_archived_lifecycle_and_retired_tier(tmp_path: Path) -> None:
    value = json.loads(DEFAULT_MATRIX.read_text(encoding="utf-8"))
    value["profiles"][0]["lifecycle"] = "archive_out_of_default_checks"
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(MatrixError, match="invalid lifecycle"):
        load_matrix(path)

    value = json.loads(DEFAULT_MATRIX.read_text(encoding="utf-8"))
    value["profiles"][0]["verification_tiers"] = ["standard_campaign"]
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(MatrixError, match="invalid verification_tiers"):
        load_matrix(path)


def test_configuration_identity_binds_profile_and_source() -> None:
    matrix = load_matrix()
    lower = _profile(matrix, "cx319_tight_lower")
    payload = configuration_payload(
        matrix, lower, config_source_sha256="a" * 64
    )
    assert payload["profile_id"] == "cx319_tight_lower"
    assert payload["config_source_sha256"] == "a" * 64
    assert len(configuration_hash(matrix, lower)) == 64


def test_unknown_profile_is_rejected() -> None:
    with pytest.raises(MatrixError, match="unknown firmware profiles"):
        _selected_profiles(load_matrix(), ["cx318_stage5_tight_lower"], False)
