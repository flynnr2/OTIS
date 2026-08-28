from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.firmware_matrix import (
    DEFAULT_MATRIX,
    GNSS_BAUD_CHARACTERIZATION_BINARY_MARKERS,
    GNSS_BAUD_CHARACTERIZATION_CONTRACT_SHA256,
    GNSS_BAUD_CHARACTERIZATION_PACKETS,
    GNSS_BAUD_CHARACTERIZATION_PROFILE_ID,
    GNSS_BAUD_CONTINUATION_CONTRACT_SHA256,
    GNSS_BAUD_CONTINUATION_PROFILE_ID,
    GNSS_BAUD_RESUME_CONTRACT_SHA256,
    GNSS_BAUD_RESUME_PROFILE_ID,
    MatrixError,
    _gnss_binary_contract,
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
    "cx321_active_hybrid",
    "cx322_direct_hybrid",
    "otis_sustained_hybrid_regulation_v1",
    "d9_forwarded_output_no_control",
    GNSS_BAUD_CHARACTERIZATION_PROFILE_ID,
    GNSS_BAUD_CONTINUATION_PROFILE_ID,
    GNSS_BAUD_RESUME_PROFILE_ID,
}
CURRENT_GUARDS = {
    "invalid_cx320_active_hybrid_parameters",
    "invalid_cx321_enable_value",
    "invalid_cx321_active_hybrid_parameters",
    "invalid_active_missing_gnss",
    "invalid_gnss_uart_tx_disabled",
    "invalid_cx319_lower_parameters",
    "invalid_pps_ratio_with_pio_capture",
    "invalid_pseudo_pps_nonisolated_resources",
}


def _profile(matrix: dict, identifier: str) -> dict:
    return next(item for item in matrix["profiles"] if item["id"] == identifier)


def test_matrix_contains_only_current_profiles_and_guards() -> None:
    matrix = load_matrix()
    profiles = matrix["profiles"]
    assert {item["id"] for item in profiles} == CURRENT_PROFILES | CURRENT_GUARDS
    assert len(profiles) == 22
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
        "cx321_active_hybrid",
        "cx322_direct_hybrid",
        "otis_sustained_hybrid_regulation_v1",
        GNSS_BAUD_CHARACTERIZATION_PROFILE_ID,
        GNSS_BAUD_CONTINUATION_PROFILE_ID,
        GNSS_BAUD_RESUME_PROFILE_ID,
        "d9_forwarded_output_no_control",
    ]
    assert {item["id"] for item in _selected_profiles(
        matrix, [], False, verification_tier="campaign"
    )} == CURRENT_PROFILES


def test_ordinary_gnss_profiles_select_characterized_115200_baud() -> None:
    matrix = load_matrix()
    ordinary = [
        item
        for item in matrix["profiles"]
        if item["defines"].get("OTIS_ENABLE_GNSS_RECEIVER") == "1"
        and item["defines"].get(
            "OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION", "0"
        )
        != "1"
    ]
    assert ordinary
    assert all(
        item["defines"].get("OTIS_GNSS_UART_BAUD") == "115200u"
        for item in ordinary
    )
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


def test_current_cx321_profile_freezes_plant_sign_successor_envelope() -> None:
    profile = _profile(load_matrix(), "cx321_active_hybrid")
    defines = profile["defines"]
    assert profile["expect"] == "pass"
    assert defines["OTIS_ENABLE_CX320_ACTIVE_HYBRID"] == "1"
    assert defines["OTIS_ENABLE_CX321_ACTIVE_HYBRID"] == "1"
    assert defines["OTIS_CX317_ACTIVE_CAMPAIGN"] == (
        "OTIS_CX317_ACTIVE_CAMPAIGN_CX321_ACTIVE_HYBRID"
    )
    assert defines["OTIS_CX317_ACTIVE_START_CODE"] == "0xA83Cu"
    assert defines["OTIS_CX317_ACTIVE_CORRECTION_LIMIT"] == "4u"
    assert defines["OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES"] == "84u"


def test_expected_failures_are_release_only_current_guards() -> None:
    matrix = load_matrix()
    for identifier in CURRENT_GUARDS:
        profile = _profile(matrix, identifier)
        assert profile["expect"] == "fail"
        assert profile["verification_tiers"] == ["release"]
        assert profile["lifecycle"] == "keep_compile_only"
        assert profile["expected_error"]


def test_gnss_baud_characterization_profile_is_exactly_non_actuating() -> None:
    matrix = load_matrix()
    profile = _profile(matrix, GNSS_BAUD_CHARACTERIZATION_PROFILE_ID)
    defines = profile["defines"]

    assert profile["expect"] == "pass"
    assert profile["verification_tiers"] == [
        "fast",
        "campaign",
        "release",
        "bench",
    ]
    assert defines["OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION"] == "1"
    assert defines["OTIS_ENABLE_GNSS_RECEIVER"] == "1"
    assert defines["OTIS_GNSS_UART_TX_ENABLED"] == "1"
    assert defines["OTIS_GNSS_UART_BAUD"] == "9600u"
    assert defines["OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS"] == "2000u"
    assert defines["OTIS_PPS_GATE_STATUS_PERIOD_MS"] == "1000u"
    assert defines["OTIS_ENABLE_DUAL_CORE_PARTITION"] == "1"
    for selector in (
        "OTIS_ENABLE_DAC_AD5693R",
        "OTIS_ENABLE_H1_DAC_SWEEP",
        "OTIS_ENABLE_CX317_BOUNDED_ACTIVE",
        "OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP",
        "OTIS_ENABLE_CX320_ACTIVE_HYBRID",
        "OTIS_ENABLE_CX321_ACTIVE_HYBRID",
        "OTIS_ENABLE_CX322_DIRECT_HYBRID",
        "OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION",
    ):
        assert defines[selector] == "0"
    enabled_profiles = {
        item["id"]
        for item in matrix["profiles"]
        if item["defines"].get("OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION", "0")
        == "1"
    }
    assert enabled_profiles == {
        GNSS_BAUD_CHARACTERIZATION_PROFILE_ID,
        GNSS_BAUD_CONTINUATION_PROFILE_ID,
        GNSS_BAUD_RESUME_PROFILE_ID,
    }


def test_gnss_baud_continuation_profile_is_distinct_and_hint_bound() -> None:
    matrix = load_matrix()
    original = _profile(matrix, GNSS_BAUD_CHARACTERIZATION_PROFILE_ID)
    continuation = _profile(matrix, GNSS_BAUD_CONTINUATION_PROFILE_ID)

    assert continuation["expect"] == "pass"
    assert continuation["defines"]["OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION"] == "1"
    assert continuation["defines"]["OTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT"] == "57600u"
    assert continuation["defines"][
        "OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD"
    ] == "1"
    assert "OTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT" not in original["defines"]
    assert (
        "OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD"
        not in original["defines"]
    )
    assert GNSS_BAUD_CONTINUATION_CONTRACT_SHA256 != (
        GNSS_BAUD_CHARACTERIZATION_CONTRACT_SHA256
    )


def test_gnss_baud_resume_profile_is_distinct_and_115200_hint_bound() -> None:
    matrix = load_matrix()
    resume = _profile(matrix, GNSS_BAUD_RESUME_PROFILE_ID)
    assert resume["expect"] == "pass"
    assert resume["defines"]["OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION"] == "1"
    assert resume["defines"]["OTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT"] == "115200u"
    assert resume["defines"][
        "OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD"
    ] == "1"
    assert GNSS_BAUD_RESUME_CONTRACT_SHA256 not in {
        GNSS_BAUD_CHARACTERIZATION_CONTRACT_SHA256,
        GNSS_BAUD_CONTINUATION_CONTRACT_SHA256,
    }


@pytest.mark.parametrize(
    ("define", "value"),
    [
        ("OTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT", "38400u"),
        (
            "OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD",
            "0",
        ),
    ],
)
def test_matrix_rejects_changed_continuation_startup_selectors(
    tmp_path: Path, define: str, value: str
) -> None:
    matrix = json.loads(DEFAULT_MATRIX.read_text(encoding="utf-8"))
    continuation = _profile(matrix, GNSS_BAUD_CONTINUATION_PROFILE_ID)
    continuation["defines"][define] = value
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(matrix), encoding="utf-8")

    with pytest.raises(MatrixError, match="authority or topology differs"):
        load_matrix(path)


def test_matrix_rejects_continuation_hint_on_immutable_original_profile(
    tmp_path: Path,
) -> None:
    matrix = json.loads(DEFAULT_MATRIX.read_text(encoding="utf-8"))
    original = _profile(matrix, GNSS_BAUD_CHARACTERIZATION_PROFILE_ID)
    original["defines"]["OTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT"] = "57600u"
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(matrix), encoding="utf-8")

    with pytest.raises(MatrixError, match="cannot carry continuation startup selectors"):
        load_matrix(path)


def test_matrix_rejects_characterization_surface_in_another_profile(
    tmp_path: Path,
) -> None:
    value = json.loads(DEFAULT_MATRIX.read_text(encoding="utf-8"))
    value["profiles"][0]["defines"][
        "OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION"
    ] = "1"
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(
        MatrixError,
        match="GNSS baud characterization is restricted to its exact profile",
    ):
        load_matrix(path)


def test_gnss_binary_contract_requires_exact_five_packets_and_topology(
    tmp_path: Path,
) -> None:
    profile = _profile(load_matrix(), GNSS_BAUD_CHARACTERIZATION_PROFILE_ID)
    elf = tmp_path / "candidate.elf"
    elf.write_bytes(
        b"synthetic ELF D14 D8_GPIO20_GPIN0\x00"
        + b"\x00".join(sorted(GNSS_BAUD_CHARACTERIZATION_PACKETS))
        + b"\x00"
        + b"\x00".join(GNSS_BAUD_CHARACTERIZATION_BINARY_MARKERS.values())
    )

    report = _gnss_binary_contract(profile, tmp_path)

    assert report["status"] == "verified"
    assert report["characterization_transition_surface"] == "enabled"
    assert len(report["pmtk251_packets"]) == 5
    assert set(report["dac_and_control_write_authority"].values()) == {"0"}
    assert all(report["topology_markers_present"].values())
    assert all(report["characterization_markers"].values())
    assert report["campaign_contract"] == {
        "path": (
            "profiles/qualification/"
            "otis_gnss_baud_envelope_characterization_v1.json"
        ),
        "sha256": GNSS_BAUD_CHARACTERIZATION_CONTRACT_SHA256,
    }

    elf.write_bytes(elf.read_bytes() + b"$PMTK251,4800*14\r\n")
    with pytest.raises(MatrixError, match="packet set differs"):
        _gnss_binary_contract(profile, tmp_path)


def test_gnss_baud_characterization_packets_have_exact_checksums() -> None:
    assert {
        int(packet[len(b"$PMTK251,") : packet.index(b"*")])
        for packet in GNSS_BAUD_CHARACTERIZATION_PACKETS
    } == {9600, 19200, 38400, 57600, 115200}
    for packet in GNSS_BAUD_CHARACTERIZATION_PACKETS:
        body, checksum_and_terminator = packet[1:].split(b"*", 1)
        checksum = 0
        for byte in body:
            checksum ^= byte
        assert checksum_and_terminator == f"{checksum:02X}\r\n".encode("ascii")


def test_ordinary_gnss_binary_contract_omits_characterization_table(
    tmp_path: Path,
) -> None:
    profile = _profile(load_matrix(), "cx319_tight_lower")
    (tmp_path / "candidate.elf").write_bytes(
        b"synthetic ELF\x00$PMTK251,115200*1F\r\n\x00"
    )

    report = _gnss_binary_contract(profile, tmp_path)

    assert report["characterization_transition_surface"] == "disabled"
    assert report["pmtk251_packets"] == ["$PMTK251,115200*1F\r\n"]
    assert report["campaign_contract"] is None


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
