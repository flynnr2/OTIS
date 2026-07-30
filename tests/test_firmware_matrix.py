from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

import tools.firmware_matrix as firmware_matrix
from tools.firmware_matrix import (
    MatrixError,
    _compile_profile,
    _git_identity,
    _require_installed_hash,
    build_provenance,
    configuration_hash,
    load_matrix,
    provenance_header,
)


MATRIX_PATH = Path("firmware/arduino/firmware_matrix.json")
FIRMWARE = Path("firmware/arduino/otis_nano_rp2040_connect")
TEST_BUILD_SESSION = "0123456789abcdef"


def _profile(matrix: dict, profile_id: str) -> dict:
    return next(item for item in matrix["profiles"] if item["id"] == profile_id)


def _environment() -> dict[str, str]:
    return {
        "arduino_cli_version": "1.4.1",
        "compiler_identity": (
            "pqt-gcc@5.0.0-9576866/arm-none-eabi-g++@16.1.0"
        ),
        "compiler_path": "/pinned/arm-none-eabi-g++",
        "board_id": "arduino_nano_connect",
        "board_name": "Arduino Nano RP2040 Connect",
        "core_installed_sha256": "1" * 64,
        "toolchain_installed_sha256": "2" * 64,
        "core_path": "/pinned/core",
        "toolchain_path": "/pinned/toolchain",
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
        "gps_pps_pio_capture",
        "h1_pio_capture_long_gate",
        "tcxo_gpio_irq_divided",
    } <= set(profiles)
    assert sum(item["expect"] == "pass" for item in profiles.values()) == 11
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
        build_session_id=TEST_BUILD_SESSION,
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
    assert provenance["target"]["board_id"] == "arduino_nano_connect"
    assert provenance["target"]["board_name"] == "Arduino Nano RP2040 Connect"
    assert provenance["target"]["core_installed_sha256"] == "1" * 64
    assert provenance["configuration"]["profile_id"] == "phase4_observe_only"
    assert provenance["configuration"]["sha256"] == configuration_hash(
        matrix, profile
    )
    assert provenance["toolchain"]["compiler_identity"].endswith("@16.1.0")
    assert provenance["toolchain"]["installed_sha256"] == "2" * 64
    assert len(provenance["invocation"]["id"]) == 64
    assert provenance["invocation"]["build_session_id"] == TEST_BUILD_SESSION
    header = provenance_header(provenance)
    assert '#define OTIS_BUILD_GIT_COMMIT "' in header
    assert '#define OTIS_BUILD_CONFIG_SHA256 "' in header
    assert '#define OTIS_BUILD_INVOCATION_ID "' in header
    assert '#define OTIS_BUILD_BOARD_ID "arduino_nano_connect"' in header
    assert "#ifdef OTIS_CAPTURE_BACKEND" in header
    assert "#define OTIS_BUILD_EXPECTED_OTIS_CAPTURE_BACKEND" in header


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
    assert "otis_build_profile.generated.h" in result.stderr


def test_generated_header_is_included_before_any_profile_selector() -> None:
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")
    include_offset = config.index('#include "otis_build_profile.generated.h"')
    first_selector_offset = min(
        config.index(f"#define {name}") for name in firmware_matrix.PROFILE_SELECTOR_NAMES
    )

    assert include_offset < first_selector_offset


def test_complete_stale_header_cannot_authorize_ordinary_raw_compile(
    tmp_path: Path,
) -> None:
    if shutil.which("c++") is None:
        pytest.skip("host C++ preprocessor is not available")
    matrix = load_matrix(MATRIX_PATH)
    profile = _profile(matrix, "synthetic_usb")
    provenance = build_provenance(
        matrix,
        profile,
        _environment(),
        git_commit="d" * 40,
        source_state="clean",
        source_sha256="e" * 64,
        build_session_id=TEST_BUILD_SESSION,
    )
    shutil.copyfile(FIRMWARE / "otis_config.h", tmp_path / "otis_config.h")
    (tmp_path / firmware_matrix.GENERATED_HEADER_NAME).write_text(
        provenance_header(provenance),
        encoding="utf-8",
    )
    harness = tmp_path / "raw_stale.cpp"
    harness.write_text('#include "otis_config.h"\n', encoding="utf-8")

    result = subprocess.run(
        ["c++", "-E", "-DARDUINO=1", "-I", str(tmp_path), str(harness)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "builder session flag is required" in result.stderr


def test_generated_header_rejects_external_selector_override(
    tmp_path: Path,
) -> None:
    if shutil.which("c++") is None:
        pytest.skip("host C++ preprocessor is not available")
    matrix = load_matrix(MATRIX_PATH)
    profile = _profile(matrix, "synthetic_usb")
    provenance = build_provenance(
        matrix,
        profile,
        _environment(),
        git_commit="d" * 40,
        source_state="clean",
        source_sha256="e" * 64,
        build_session_id=TEST_BUILD_SESSION,
    )
    (tmp_path / "otis_build_profile.generated.h").write_text(
        provenance_header(provenance),
        encoding="utf-8",
    )
    harness = tmp_path / "override.cpp"
    harness.write_text(
        "#define OTIS_CAPTURE_BACKEND 999\n"
        '#include "otis_build_profile.generated.h"\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "c++",
            "-E",
            f"-DOTIS_BUILD_SESSION_ID=0x{TEST_BUILD_SESSION}ULL",
            str(harness),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "OTIS_CAPTURE_BACKEND was externally pre-defined" in result.stderr


def test_stale_generated_header_effective_selector_mismatch_is_rejected(
    tmp_path: Path,
) -> None:
    if shutil.which("c++") is None:
        pytest.skip("host C++ preprocessor is not available")
    matrix = load_matrix(MATRIX_PATH)
    profile = _profile(matrix, "synthetic_usb")
    provenance = build_provenance(
        matrix,
        profile,
        _environment(),
        git_commit="d" * 40,
        source_state="clean",
        source_sha256="e" * 64,
        build_session_id=TEST_BUILD_SESSION,
    )
    header = provenance_header(provenance).replace(
        "#define OTIS_CAPTURE_BACKEND OTIS_CAPTURE_BACKEND_IRQ",
        "#define OTIS_CAPTURE_BACKEND OTIS_CAPTURE_BACKEND_PIO_FIFO",
        1,
    )
    (tmp_path / "otis_build_profile.generated.h").write_text(
        header,
        encoding="utf-8",
    )
    shutil.copyfile(FIRMWARE / "otis_config.h", tmp_path / "otis_config.h")
    harness = tmp_path / "stale.cpp"
    harness.write_text('#include "otis_config.h"\n', encoding="utf-8")
    result = subprocess.run(
        [
            "c++",
            "-E",
            "-DARDUINO=1",
            f"-DOTIS_BUILD_SESSION_ID=0x{TEST_BUILD_SESSION}ULL",
            "-I",
            str(tmp_path),
            str(harness),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Effective OTIS_CAPTURE_BACKEND differs" in result.stderr


def test_installed_byte_pin_rejects_mutated_package(tmp_path: Path) -> None:
    package = tmp_path / "installed"
    package.mkdir()
    binary = package / "compiler"
    binary.write_bytes(b"pinned bytes")
    expected = firmware_matrix.installed_tree_hash(package)

    assert _require_installed_hash("test package", package, expected) == expected
    binary.write_bytes(b"mutated bytes")
    with pytest.raises(MatrixError, match="installed-byte SHA-256 mismatch"):
        _require_installed_hash("test package", package, expected)


def test_compile_uses_disposable_sketch_supports_spaces_and_hashes_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix = load_matrix(MATRIX_PATH)
    profile = _profile(matrix, "synthetic_usb")
    snapshot = {
        "git_commit": "d" * 40,
        "source_state": "clean",
        "source_sha256": "e" * 64,
        "config_source_sha256": "f" * 64,
        "config_sha256": configuration_hash(matrix, profile),
    }
    provenance = build_provenance(
        matrix,
        profile,
        _environment(),
        git_commit=snapshot["git_commit"],
        source_state=snapshot["source_state"],
        source_sha256=snapshot["source_sha256"],
        build_session_id=TEST_BUILD_SESSION,
        config_source_sha256=snapshot["config_source_sha256"],
    )
    snapshot["config_sha256"] = provenance["configuration"]["sha256"]
    compiled_sketch: Path | None = None

    def fake_run(
        arguments: list[str],
        *,
        cwd: Path = firmware_matrix.REPO_ROOT,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal compiled_sketch
        assert arguments[1] == "compile"
        property_index = arguments.index("--build-property")
        assert arguments[property_index + 1] == (
            "compiler.cpp.extra_flags="
            f"-DOTIS_BUILD_SESSION_ID=0x{TEST_BUILD_SESSION}ULL"
        )
        compiled_sketch = Path(arguments[-1])
        assert compiled_sketch.is_dir()
        assert " " in str(compiled_sketch)
        header = compiled_sketch / firmware_matrix.GENERATED_HEADER_NAME
        assert header.is_file()
        assert not (FIRMWARE / firmware_matrix.GENERATED_HEADER_NAME).exists()
        artifacts = Path(arguments[arguments.index("--output-dir") + 1])
        for suffix in firmware_matrix.EXPECTED_ARTIFACT_SUFFIXES:
            (artifacts / f"firmware{suffix}").write_bytes(
                f"artifact {suffix}".encode()
            )
        return subprocess.CompletedProcess(arguments, 0, "compiled\n", "")

    monkeypatch.setattr(firmware_matrix, "_run", fake_run)
    monkeypatch.setattr(
        firmware_matrix,
        "_capture_source_state",
        lambda *args, **kwargs: dict(snapshot),
    )
    monkeypatch.setattr(
        firmware_matrix,
        "_verify_installed_environment",
        lambda environment: None,
    )
    output = tmp_path / "output path with spaces"
    result = _compile_profile(
        matrix,
        profile,
        provenance,
        output,
        "fake-arduino-cli",
        environment=_environment(),
        source_snapshot=snapshot,
    )

    assert compiled_sketch is not None and not compiled_sketch.exists()
    manifest = json.loads(
        Path(result["build_manifest"]).read_text(encoding="utf-8")
    )
    assert len(manifest["artifacts"]) == len(
        firmware_matrix.EXPECTED_ARTIFACT_SUFFIXES
    )
    for artifact in manifest["artifacts"]:
        path = output / profile["id"] / "artifacts" / artifact["name"]
        assert artifact["sha256"] == firmware_matrix.sha256(
            path.read_bytes()
        ).hexdigest()


def test_post_build_source_mutation_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix = load_matrix(MATRIX_PATH)
    profile = _profile(matrix, "synthetic_usb")
    before = {
        "git_commit": "a" * 40,
        "source_state": "clean",
        "source_sha256": "b" * 64,
        "config_source_sha256": "c" * 64,
        "config_sha256": "d" * 64,
    }
    provenance = build_provenance(
        matrix,
        profile,
        _environment(),
        git_commit=before["git_commit"],
        source_state=before["source_state"],
        source_sha256=before["source_sha256"],
        build_session_id=TEST_BUILD_SESSION,
        config_source_sha256=before["config_source_sha256"],
    )
    before["config_sha256"] = provenance["configuration"]["sha256"]
    after = dict(before)
    after["config_source_sha256"] = "e" * 64

    def fake_run(
        arguments: list[str],
        *,
        cwd: Path = firmware_matrix.REPO_ROOT,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        artifacts = Path(arguments[arguments.index("--output-dir") + 1])
        (artifacts / "untrusted.bin").write_bytes(b"must be removed")
        return subprocess.CompletedProcess(arguments, 0, "compiled\n", "")

    monkeypatch.setattr(firmware_matrix, "_run", fake_run)
    monkeypatch.setattr(
        firmware_matrix,
        "_capture_source_state",
        lambda *args, **kwargs: dict(after),
    )
    monkeypatch.setattr(
        firmware_matrix,
        "_verify_installed_environment",
        lambda environment: None,
    )

    with pytest.raises(MatrixError, match="changed during compilation"):
        _compile_profile(
            matrix,
            profile,
            provenance,
            tmp_path / "race output",
            "fake-arduino-cli",
            environment=_environment(),
            source_snapshot=before,
        )
    assert not list((tmp_path / "race output").rglob("untrusted.bin"))


def test_post_compile_installed_package_mutation_rejects_and_cleans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix = load_matrix(MATRIX_PATH)
    profile = _profile(matrix, "synthetic_usb")
    core = tmp_path / "core"
    toolchain = tmp_path / "toolchain"
    core.mkdir()
    toolchain.mkdir()
    (core / "platform.txt").write_bytes(b"pinned core")
    compiler = toolchain / "compiler"
    compiler.write_bytes(b"pinned toolchain")
    environment = _environment()
    environment.update(
        {
            "core_path": str(core),
            "toolchain_path": str(toolchain),
            "core_installed_sha256": firmware_matrix.installed_tree_hash(core),
            "toolchain_installed_sha256": firmware_matrix.installed_tree_hash(
                toolchain
            ),
        }
    )
    snapshot = {
        "git_commit": "a" * 40,
        "source_state": "clean",
        "source_sha256": "b" * 64,
        "config_source_sha256": "c" * 64,
        "config_sha256": "d" * 64,
    }
    provenance = build_provenance(
        matrix,
        profile,
        environment,
        git_commit=snapshot["git_commit"],
        source_state=snapshot["source_state"],
        source_sha256=snapshot["source_sha256"],
        build_session_id=TEST_BUILD_SESSION,
        config_source_sha256=snapshot["config_source_sha256"],
    )
    snapshot["config_sha256"] = provenance["configuration"]["sha256"]

    def fake_run(
        arguments: list[str],
        *,
        cwd: Path = firmware_matrix.REPO_ROOT,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        artifacts = Path(arguments[arguments.index("--output-dir") + 1])
        for suffix in firmware_matrix.EXPECTED_ARTIFACT_SUFFIXES:
            (artifacts / f"untrusted{suffix}").write_bytes(b"untrusted")
        compiler.write_bytes(b"mutated during compile")
        return subprocess.CompletedProcess(arguments, 0, "compiled\n", "")

    monkeypatch.setattr(firmware_matrix, "_run", fake_run)
    monkeypatch.setattr(
        firmware_matrix,
        "_capture_source_state",
        lambda *args, **kwargs: dict(snapshot),
    )

    with pytest.raises(MatrixError, match="installed-byte SHA-256 mismatch"):
        _compile_profile(
            matrix,
            profile,
            provenance,
            tmp_path / "installed race output",
            "fake-arduino-cli",
            environment=environment,
            source_snapshot=snapshot,
        )
    assert not list((tmp_path / "installed race output").rglob("untrusted.*"))


def test_installed_bytes_are_rechecked_after_artifact_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix = load_matrix(MATRIX_PATH)
    profile = _profile(matrix, "synthetic_usb")
    snapshot = {
        "git_commit": "a" * 40,
        "source_state": "clean",
        "source_sha256": "b" * 64,
        "config_source_sha256": "c" * 64,
        "config_sha256": "d" * 64,
    }
    provenance = build_provenance(
        matrix,
        profile,
        _environment(),
        git_commit=snapshot["git_commit"],
        source_state=snapshot["source_state"],
        source_sha256=snapshot["source_sha256"],
        build_session_id=TEST_BUILD_SESSION,
        config_source_sha256=snapshot["config_source_sha256"],
    )
    snapshot["config_sha256"] = provenance["configuration"]["sha256"]

    def fake_run(
        arguments: list[str],
        *,
        cwd: Path = firmware_matrix.REPO_ROOT,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        artifacts = Path(arguments[arguments.index("--output-dir") + 1])
        for suffix in firmware_matrix.EXPECTED_ARTIFACT_SUFFIXES:
            (artifacts / f"untrusted{suffix}").write_bytes(b"untrusted")
        return subprocess.CompletedProcess(arguments, 0, "compiled\n", "")

    verification_count = 0

    def verify_then_reject(environment: dict[str, str]) -> None:
        nonlocal verification_count
        verification_count += 1
        if verification_count == 2:
            raise MatrixError("installed bytes changed after artifact hashing")

    monkeypatch.setattr(firmware_matrix, "_run", fake_run)
    monkeypatch.setattr(
        firmware_matrix,
        "_capture_source_state",
        lambda *args, **kwargs: dict(snapshot),
    )
    monkeypatch.setattr(
        firmware_matrix,
        "_verify_installed_environment",
        verify_then_reject,
    )

    with pytest.raises(MatrixError, match="after artifact hashing"):
        _compile_profile(
            matrix,
            profile,
            provenance,
            tmp_path / "artifact hash race output",
            "fake-arduino-cli",
            environment=_environment(),
            source_snapshot=snapshot,
        )
    assert verification_count == 2
    assert not list(
        (tmp_path / "artifact hash race output").rglob("untrusted.*")
    )


def test_matrix_wide_source_identity_change_aborts_and_cleans_prior_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix = load_matrix(MATRIX_PATH)
    profiles = [
        _profile(matrix, "synthetic_usb"),
        _profile(matrix, "gps_pps_irq_capture"),
    ]
    base = {
        "git_commit": "a" * 40,
        "source_state": "clean",
        "source_sha256": "b" * 64,
        "config_source_sha256": "c" * 64,
        "config_sha256": "d" * 64,
    }
    changed = dict(base)
    changed["source_sha256"] = "e" * 64
    captures = iter([dict(base), dict(base), changed])

    monkeypatch.setattr(
        firmware_matrix,
        "verify_environment",
        lambda matrix, arduino_cli: _environment(),
    )
    monkeypatch.setattr(
        firmware_matrix,
        "_verify_installed_environment",
        lambda environment: None,
    )
    monkeypatch.setattr(
        firmware_matrix,
        "_capture_source_state",
        lambda *args, **kwargs: next(captures),
    )

    def fake_compile(
        matrix: dict,
        profile: dict,
        provenance: dict,
        output_dir: Path,
        arduino_cli: str,
        **kwargs: object,
    ) -> dict[str, object]:
        artifacts = output_dir / profile["id"] / "artifacts"
        artifacts.mkdir(parents=True)
        (artifacts / "accepted.bin").write_bytes(b"must be discarded")
        return {"outcome": "pass", "verified": True}

    monkeypatch.setattr(firmware_matrix, "_compile_profile", fake_compile)
    output = tmp_path / "matrix race output"
    output.mkdir()
    (output / "matrix_summary.json").write_text(
        '{"all_verified": true}\n',
        encoding="utf-8",
    )

    with pytest.raises(MatrixError, match="changed during compilation"):
        firmware_matrix.run_matrix(
            matrix,
            profiles,
            output,
            arduino_cli="fake-arduino-cli",
        )
    assert not list(output.rglob("accepted.bin"))
    assert not (output / "matrix_summary.json").exists()


def test_source_has_no_manual_commit_literal_and_requires_builder() -> None:
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")
    board = (FIRMWARE / "otis_board.h").read_text(encoding="utf-8")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )

    assert '#error "Build OTIS firmware with tools/firmware_matrix.py' in config
    assert '#include "otis_build_profile.generated.h"' in config
    assert "#define OTIS_FIRMWARE_GIT_COMMIT OTIS_BUILD_GIT_COMMIT" in config
    assert "#define OTIS_TARGET_BOARD OTIS_BUILD_BOARD_ID" in board
    assert '"arduino_nano_rp2040_connect"' not in board
    assert "1095a16dc0c4e6f9ce875032fbe64209c2832b41" not in config
    for token in (
        "OTIS_BUILD_SOURCE_STATE",
        "OTIS_BUILD_SOURCE_SHA256",
        "OTIS_BUILD_CONFIG_SHA256",
        "OTIS_BUILD_FQBN",
        "OTIS_BUILD_CORE_VERSION",
        "OTIS_BUILD_CORE_INSTALLED_SHA256",
        "OTIS_BUILD_COMPILER",
        "OTIS_BUILD_TOOLCHAIN_INSTALLED_SHA256",
        "OTIS_BUILD_INVOCATION_ID",
    ):
        assert token in sketch
    assert 'emit_status("system", "board", OTIS_TARGET_BOARD' in sketch
    assert 'emit_status("system", "board_name", OTIS_TARGET_BOARD_NAME' in sketch
