from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tools.firmware_matrix import (
    MatrixError,
    _git_identity,
    build_provenance,
    configuration_hash,
    load_matrix,
    provenance_header,
)


MATRIX_PATH = Path("firmware/arduino/firmware_matrix.json")
FIRMWARE = Path("firmware/arduino/otis_nano_rp2040_connect")


def _profile(matrix: dict, profile_id: str) -> dict:
    return next(item for item in matrix["profiles"] if item["id"] == profile_id)


def _environment() -> dict[str, str]:
    return {
        "arduino_cli_version": "1.4.1",
        "compiler_identity": (
            "pqt-gcc@5.0.0-9576866/arm-none-eabi-g++@16.1.0"
        ),
        "compiler_path": "/pinned/arm-none-eabi-g++",
    }


def test_matrix_is_intentional_and_covers_required_profiles() -> None:
    matrix = load_matrix(MATRIX_PATH)
    profiles = {profile["id"]: profile for profile in matrix["profiles"]}

    assert {
        "phase5_qualification",
        "phase4_observe_only",
        "h1_characterization",
        "h1_lab_actuator",
        "synthetic_usb",
        "gpio_loopback_pio_capture",
        "gps_pps_irq_capture",
        "tcxo_fc0_observe",
    } <= set(profiles)
    assert sum(item["expect"] == "pass" for item in profiles.values()) == 8
    assert sum(item["expect"] == "fail" for item in profiles.values()) == 3


def test_config_hash_is_deterministic_and_changes_with_configuration() -> None:
    matrix = load_matrix(MATRIX_PATH)
    profile = _profile(matrix, "phase5_qualification")
    first = configuration_hash(matrix, profile)
    second = configuration_hash(matrix, copy.deepcopy(profile))
    changed = copy.deepcopy(profile)
    changed["defines"]["OTIS_ENABLE_PPS_DUAL_OBSERVER"] = "0"

    assert first == second
    assert len(first) == 64
    assert configuration_hash(matrix, changed) != first


def test_config_hash_changes_when_header_defined_defaults_change(
    tmp_path: Path,
) -> None:
    matrix = load_matrix(MATRIX_PATH)
    profile = _profile(matrix, "phase5_qualification")
    source = FIRMWARE / "otis_config.h"
    changed = tmp_path / "otis_config.h"
    changed.write_bytes(source.read_bytes() + b"\n// changed configuration source\n")

    assert configuration_hash(matrix, profile, config_path=source) != (
        configuration_hash(matrix, profile, config_path=changed)
    )


def test_generated_provenance_contains_exact_source_target_and_toolchain() -> None:
    matrix = load_matrix(MATRIX_PATH)
    profile = _profile(matrix, "phase4_observe_only")
    provenance = build_provenance(
        matrix,
        profile,
        _environment(),
        git_commit="d" * 40,
        source_state="dirty",
        source_sha256="e" * 64,
    )

    assert provenance["source"] == {
        "git_commit": "d" * 40,
        "state": "dirty",
        "sha256": "e" * 64,
    }
    assert provenance["target"]["fqbn"] == (
        "rp2040:rp2040:arduino_nano_connect"
    )
    assert provenance["target"]["core_version"] == "6.0.0"
    assert provenance["configuration"]["profile_id"] == "phase4_observe_only"
    assert provenance["configuration"]["sha256"] == configuration_hash(
        matrix, profile
    )
    assert provenance["toolchain"]["compiler_identity"].endswith("@16.1.0")
    assert len(provenance["invocation"]["id"]) == 64
    header = provenance_header(provenance)
    assert '#define OTIS_BUILD_GIT_COMMIT "' in header
    assert '#define OTIS_BUILD_CONFIG_SHA256 "' in header
    assert '#define OTIS_BUILD_INVOCATION_ID "' in header


def test_git_identity_reports_exact_commit_and_dirty_state(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "source.txt"
    source.write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "add", "source.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=OTIS Test",
            "-c",
            "user.email=otis-test@example.invalid",
            "commit",
            "-q",
            "-m",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert _git_identity(tmp_path) == (expected, "clean")
    source.write_text("dirty\n", encoding="utf-8")
    assert _git_identity(tmp_path) == (expected, "dirty")


def test_profile_cannot_override_or_fake_generated_identity(tmp_path: Path) -> None:
    matrix = load_matrix(MATRIX_PATH)
    matrix["profiles"][0]["defines"]["OTIS_BUILD_GIT_COMMIT"] = '"stale"'
    path = tmp_path / "matrix.json"

    path.write_text(json.dumps(matrix), encoding="utf-8")
    with pytest.raises(MatrixError, match="may not define generated identity"):
        load_matrix(path)


def test_arduino_preprocessing_rejects_unprovenanced_compile(
    tmp_path: Path,
) -> None:
    if shutil.which("c++") is None:
        pytest.skip("host C++ preprocessor is not available")
    harness = tmp_path / "unprovenanced.cpp"
    harness.write_text('#include "otis_config.h"\n', encoding="utf-8")
    result = subprocess.run(
        [
            "c++",
            "-E",
            "-DARDUINO=1",
            "-I",
            str(FIRMWARE),
            str(harness),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "generated provenance is required" in result.stderr


def test_source_has_no_manual_commit_literal_and_requires_builder() -> None:
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )

    assert '#error "Build OTIS firmware with tools/firmware_matrix.py' in config
    assert "#define OTIS_FIRMWARE_GIT_COMMIT OTIS_BUILD_GIT_COMMIT" in config
    assert "1095a16dc0c4e6f9ce875032fbe64209c2832b41" not in config
    for token in (
        "OTIS_BUILD_SOURCE_STATE",
        "OTIS_BUILD_SOURCE_SHA256",
        "OTIS_BUILD_CONFIG_SHA256",
        "OTIS_BUILD_FQBN",
        "OTIS_BUILD_CORE_VERSION",
        "OTIS_BUILD_COMPILER",
        "OTIS_BUILD_INVOCATION_ID",
    ):
        assert token in sketch
