from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from host.otis_tools.firmware_bindings import (
    current_forwarded_clock_contract,
    current_profile_sha256,
)
from tools import build_firmware
from tools.build_firmware import firmware_input_report

ROOT = Path(__file__).resolve().parents[1]
BUILD_MANIFEST = ROOT / "firmware/arduino/firmware_build_manifest.json"
BUILDER = ROOT / "tools/build_firmware.py"
CONFIG = ROOT / "firmware/arduino/otis_nano_rp2040_connect/otis_config.h"


def test_repository_declares_exactly_one_fixed_firmware_image() -> None:
    manifest = json.loads(BUILD_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["builder_id"] == "otis_fixed_firmware_builder_v1"
    assert manifest["image"]["id"] == "adaptive_hybrid_regulation"
    assert manifest["image"]["firmware_version"] == (
        "OTIS_AUTONOMOUS_INSTRUMENT_V2"
    )
    assert "profiles" not in manifest
    assert manifest["profile_bindings"] == build_firmware.EXPECTED_PROFILE_BINDINGS
    assert manifest["schema_bindings"] == build_firmware.EXPECTED_SCHEMA_BINDINGS
    assert manifest["contract_bindings"] == (build_firmware.EXPECTED_CONTRACT_BINDINGS)
    assert "negative_compile_cases" not in manifest
    assert not (ROOT / "firmware/arduino/firmware_matrix.json").exists()


def test_fixed_builder_has_no_profile_or_matrix_selection_surface() -> None:
    source = BUILDER.read_text(encoding="utf-8")
    assert "firmware_matrix" not in source.lower()
    for option in ("--profile", "--profiles", "--all", "--tier"):
        assert option not in source
    assert "adaptive_hybrid_regulation" in source
    assert "firmware_build_manifest.json" in source
    assert "--build-session-id" in source


def test_builder_rejects_a_malformed_deterministic_session_before_build(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        build_firmware.BuildError,
        match="16 lowercase hexadecimal digits",
    ):
        build_firmware.build_firmware(
            build_firmware.load_manifest(),
            tmp_path / "output",
            arduino_cli="must-not-be-run",
            build_session_id="NOT-HEX",
        )


def test_git_source_state_is_scoped_to_operational_inputs(tmp_path: Path) -> None:
    def git(*arguments: str) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )

    git("init")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "OTIS test")
    firmware = tmp_path / "firmware.cpp"
    documentation = tmp_path / "notes.md"
    firmware.write_text("int main() { return 0; }\n", encoding="utf-8")
    documentation.write_text("initial notes\n", encoding="utf-8")
    git("add", "firmware.cpp", "notes.md")
    git("commit", "-m", "fixture")

    documentation.write_text("edited notes\n", encoding="utf-8")
    assert (
        build_firmware._git_identity(tmp_path, pathspecs=("firmware.cpp",))[1]
        == "clean"
    )
    assert build_firmware._git_identity(tmp_path)[1] == "dirty"

    firmware.write_text("int main() { return 1; }\n", encoding="utf-8")
    assert (
        build_firmware._git_identity(tmp_path, pathspecs=("firmware.cpp",))[1]
        == "dirty"
    )


def test_source_input_inventory_includes_the_binding_implementation() -> None:
    paths = set(build_firmware.source_input_paths(build_firmware.load_manifest()))
    assert build_firmware.FIRMWARE_HOST_BINDING_HELPER.resolve() in paths
    assert build_firmware.FIRMWARE_BINARY_HELPER.resolve() in paths
    assert not any(path.suffix == ".md" for path in paths)


@pytest.mark.parametrize("compiler_host", ["arm64-apple-darwin", "x86_64-apple-darwin"])
def test_builder_generates_every_current_semantic_identity_from_bound_bytes(compiler_host: str) -> None:
    manifest = build_firmware.load_manifest()
    source = build_firmware.capture_source_state(manifest)
    environment = {
        "arduino_cli_version": str(manifest["arduino_cli_version"]),
        "board_id": "test_board",
        "board_name": "test board",
        "core_installed_sha256": manifest["target"]["core_installed_sha256"],
        "toolchain_installed_sha256": manifest["toolchain"]["installed_sha256_by_host"][compiler_host],
        "core_path": "/test/core",
        "toolchain_path": "/test/toolchain",
        "compiler_identity": "test_compiler",
    }
    provenance = build_firmware.build_provenance(
        manifest, environment, source, "0123456789abcdef"
    )
    assert provenance["toolchain"]["host"] == compiler_host
    assert provenance["toolchain"]["installed_sha256"] == environment["toolchain_installed_sha256"]
    header = build_firmware.provenance_header(provenance)
    generated_values = build_firmware.generated_provenance_values(provenance)

    for macro, value in generated_values.items():
        assert f"#define {macro} {json.dumps(value)}" in header

    assert provenance["configuration"]["profile_bindings"] == (
        build_firmware.profile_binding_report(manifest)
    )
    assert "schema_bindings" not in provenance["configuration"]
    assert provenance["firmware_inputs"] == build_firmware.firmware_input_report(
        manifest
    )
    assert (
        generated_values["OTIS_BUILD_GIT_COMMIT"] == source["firmware_audit_revision"]
    )
    assert (
        generated_values["OTIS_BUILD_AUTHORITATIVE_INPUT_SET_SHA256"]
        == source["firmware_inputs"]["set_sha256"]
    )
    assert provenance["configuration"]["contract_bindings"] == (
        build_firmware.contract_binding_report(manifest)
    )
    for name, macro in build_firmware.PROFILE_BINDING_MACROS.items():
        digest = current_profile_sha256(name)
        assert f'#define {macro} "{digest}"' in header
        assert provenance["configuration"]["profile_bindings"][name]["sha256"] == digest
    frequency_tag = current_profile_sha256("frequency_estimator")[:16]
    assert (
        f"#define OTIS_BUILD_FREQUENCY_ESTIMATOR_TAG_U64 0x{frequency_tag}ULL"
    ) in header
    phase_profile = json.loads(
        (ROOT / build_firmware.EXPECTED_PROFILE_BINDINGS["phase_estimator"]).read_text(
            encoding="utf-8"
        )
    )
    assert (
        "#define OTIS_BUILD_PHASE_ESTIMATOR_ID "
        f"{json.dumps(phase_profile['profile_id'])}"
    ) in header
    assert (
        "#define OTIS_BUILD_PHASE_RAW_METHOD_ID "
        f"{json.dumps(phase_profile['selection']['raw_phase_method'])}"
    ) in header
    contract, contract_sha256 = current_forwarded_clock_contract()
    assert provenance["configuration"]["forwarded_clock_contract"] == contract
    assert (
        f'#define OTIS_BUILD_FORWARDED_CLOCK_CONTRACT_SHA256 "{contract_sha256}"'
    ) in header


def test_production_code_has_no_unmanaged_literal_semantic_sha256() -> None:
    literal_sha256 = re.compile(r"[0-9a-f]{64}")
    production_files = [
        *(ROOT / "firmware/arduino/otis_nano_rp2040_connect").glob("*"),
        *(ROOT / "host/otis_tools").glob("*.py"),
    ]
    offenders = {
        path.relative_to(ROOT).as_posix(): literal_sha256.findall(
            path.read_text(encoding="utf-8", errors="replace")
        )
        for path in production_files
        if path.is_file()
        and not path.name.endswith(".generated.h")
        and literal_sha256.search(path.read_text(encoding="utf-8", errors="replace"))
    }
    assert offenders == {}


def test_obsolete_hybrid_counterfactual_wire_surface_is_absent() -> None:
    firmware = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
    source = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in firmware.iterdir()
        if path.is_file() and path.suffix in {".cpp", ".h", ".ino"}
    )
    host_source = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (ROOT / "host/otis_tools").glob("*.py")
    )
    assert '"H' + "PR" not in source
    assert "hybrid_preview_decisions_v1" not in host_source


def test_fixed_configuration_has_no_retired_feature_selectors() -> None:
    source = CONFIG.read_text(encoding="utf-8")
    forbidden_fragments = (
        "BRINGUP_MODE",
        "PSEUDO_PPS",
        "Q2_TRANSACTION",
        "STAGE4",
        "STAGE5",
        "RANGE_MAP",
        "PLANT_SIGN",
        "DIRECT_HYBRID",
        "BAUD_CHARACTERIZATION",
    )
    for fragment in forbidden_fragments:
        assert fragment not in source
    assert "OTIS_ENABLE_" not in source


def test_fixed_firmware_flags_do_not_reintroduce_profile_semantics() -> None:
    firmware = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
    source = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in firmware.iterdir()
        if path.is_file() and path.suffix in {".cpp", ".h", ".ino"}
    )
    retired_name = "OTIS_FLAG_" + "PROFILE_ASSUMPTION"
    assert retired_name not in source
    assert "OTIS_FLAG_CONFIGURATION_ASSUMPTION" in source


def test_retired_fixed_image_wrappers_and_estimators_are_absent() -> None:
    firmware = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
    retired_files = {
        "otis_modes.cpp",
        "otis_modes.h",
        "otis_status_led.h",
        "otis_records.h",
        "otis_pps_boundary_frequency_estimator.cpp",
        "otis_pps_boundary_frequency_estimator.h",
        "otis_forwarded_clock_monitor_interval.h",
    }
    assert not {path.name for path in firmware.iterdir()} & retired_files


def test_firmware_input_set_excludes_runtime_only_schemas() -> None:
    report = firmware_input_report(build_firmware.load_manifest())
    paths = {item["path"] for item in report["entries"]}
    assert report["contract"] == "otis_firmware_input_set_v1"
    assert set(build_firmware.EXPECTED_PROFILE_BINDINGS.values()).issubset(paths)
    assert set(build_firmware.EXPECTED_CONTRACT_BINDINGS.values()).issubset(paths)
    assert not any(path.startswith("schemas/") for path in paths)
    assert "host/otis_tools/adaptive_hybrid_supervisor.py" not in paths


def test_firmware_audit_revision_ignores_a_later_host_only_commit(
    tmp_path: Path,
) -> None:
    def git(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "OTIS test")
    (tmp_path / "firmware.cpp").write_text("firmware-v1\n")
    (tmp_path / "host.py").write_text("host-v1\n")
    git("add", ".")
    git("commit", "-m", "firmware")
    firmware_revision = git("rev-parse", "HEAD")
    (tmp_path / "host.py").write_text("host-v2\n")
    git("add", "host.py")
    git("commit", "-m", "host only")

    assert (
        build_firmware._git_firmware_audit_revision(
            ("firmware.cpp",), repo_root=tmp_path
        )
        == firmware_revision
    )
    assert git("rev-parse", "HEAD") != firmware_revision


def test_build_provenance_excludes_repository_head_context() -> None:
    manifest = build_firmware.load_manifest()
    source = build_firmware.capture_source_state(manifest)
    environment = {
        "arduino_cli_version": str(manifest["arduino_cli_version"]),
        "board_id": "test_board",
        "board_name": "test board",
        "core_installed_sha256": manifest["target"]["core_installed_sha256"],
        "toolchain_installed_sha256": manifest["toolchain"]["installed_sha256_by_host"]["x86_64-apple-darwin"],
        "core_path": "/test/core",
        "toolchain_path": "/test/toolchain",
        "compiler_identity": "test_compiler",
    }
    provenance = build_firmware.build_provenance(
        manifest, environment, source, "0123456789abcdef"
    )
    assert "repository_context" not in provenance
    assert (
        provenance["source"]["firmware_audit_revision"]
        == source["firmware_audit_revision"]
    )
    assert provenance["source"]["sha256"] == provenance["firmware_inputs"]["set_sha256"]


def test_unreviewed_compiler_package_is_rejected():
    toolchain = build_firmware.load_manifest()["toolchain"]
    with pytest.raises(build_firmware.BuildError, match="no approved host package"):
        build_firmware.compiler_package_host(toolchain, "0" * 64)
