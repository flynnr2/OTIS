from __future__ import annotations

import json
from pathlib import Path
import subprocess

from host.otis_tools.range_spanning_programme import (
    DEFAULT_PROFILE,
    load_programme,
    programme_summary,
)


ROOT = Path(__file__).resolve().parents[1]


def test_programme_freezes_monotonic_survey_and_separate_fine_gate() -> None:
    programme = load_programme()
    summary = programme_summary()

    assert programme["part_a"]["state"].startswith("survey_frozen")
    assert summary == {
        "programme_id": "CX319_RANGE_SPANNING_BIDIRECTIONAL_HYBRID_PREVIEW_V1",
        "part_a_firmware_profile": "cx319_range_map_part_a",
        "survey_point_count": 30,
        "survey_minimum_physical_duration_s": 63_000,
        "survey_operational_worst_case_duration_s": 81_000,
        "survey_first_code": 0xA800,
        "survey_peak_code": 0xA890,
        "survey_final_code": 0xA800,
        "part_b_endpoints": [0xA800, 0xA890],
        "phase_hybrid_authority": False,
    }
    assert programme["part_a"]["fine_pass"][
        "survey_derived_plan_must_be_frozen_before_fine_physical_entry"
    ] is True


def test_range_map_firmware_profile_has_dac_but_no_control_authority() -> None:
    matrix = json.loads(
        (ROOT / "firmware/arduino/firmware_matrix.json").read_text(
            encoding="utf-8"
        )
    )
    profile = next(
        item for item in matrix["profiles"] if item["id"] == "cx319_range_map_part_a"
    )
    defines = profile["defines"]

    assert defines["OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW"] == "1"
    assert defines["OTIS_ENABLE_CX317_BOUNDED_ACTIVE"] == "0"
    assert defines["OTIS_ENABLE_DAC_AD5693R"] == "1"
    assert defines["OTIS_ENABLE_H1_DAC_SWEEP"] == "0"
    assert defines["OTIS_DAC_MIN_CODE"] == "0xA800u"
    assert defines["OTIS_DAC_MAX_CODE"] == "0xAB00u"
    assert "bench" in profile["verification_tiers"]


def test_range_map_propagates_each_applied_epoch_to_first_preview_consumer() -> None:
    source = (
        ROOT
        / "firmware/arduino/otis_nano_rp2040_connect/otis_nano_rp2040_connect.ino"
    ).read_text(encoding="utf-8")

    assert "dual_core_range_map_dac_epoch++" in source
    assert "propagate_cx317_applied_epoch_to_previews(" in source
    assert "OtisServiceMessageKind::ManualDacApplication" in source
    assert "range_map_application.dac.requested_applied_match = ok" in source
    assert '"rejected_exact_dac_set_required"' in source
    assert "OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW" in source

    config = (
        ROOT / "firmware/arduino/otis_nano_rp2040_connect/otis_config.h"
    ).read_text(encoding="utf-8")
    engine = (
        ROOT
        / "firmware/arduino/otis_nano_rp2040_connect/otis_cx317_i_only_engine.cpp"
    ).read_text(encoding="utf-8")
    live = (
        ROOT
        / "firmware/arduino/otis_nano_rp2040_connect/otis_cx317_preview_live.cpp"
    ).read_text(encoding="utf-8")
    assert "#define OTIS_ENABLE_TIGHT_DEADBAND_OBSERVATION" in config
    assert "OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW)" in config
    assert engine.count("OTIS_ENABLE_TIGHT_DEADBAND_OBSERVATION") >= 10
    assert "const bool tight_evidence_queued = emit_tight_deadband(" in live
    assert "#if OTIS_ENABLE_TIGHT_DEADBAND_OBSERVATION" in live


def test_same_code_manual_application_opens_a_new_epoch(tmp_path: Path) -> None:
    firmware = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
    executable = tmp_path / "cx319_range_map_epoch"
    subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-I",
            str(firmware),
            str(ROOT / "tests/cpp/cx319_range_map_epoch_harness.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
    )
    subprocess.run([str(executable)], check=True)


def test_rollover_callers_have_no_optional_enable_switch() -> None:
    host_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "host/otis_tools").glob("*.py"))
    )
    assert "allow_rp2040_timer0_wrap" not in host_source
    assert "reference_timestamp_modulus_ticks" not in host_source
    assert "timestamp_modulus: int | None" not in host_source


def test_profile_path_is_repository_canonical() -> None:
    assert DEFAULT_PROFILE == (
        ROOT
        / "profiles/qualification/cx319_range_spanning_programme_v1.json"
    )
