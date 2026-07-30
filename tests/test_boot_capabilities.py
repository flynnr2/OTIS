from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


FIRMWARE = Path("firmware/arduino/otis_nano_rp2040_connect")


def test_boot_capability_policy_and_phase_ordering(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is not available")

    executable = tmp_path / "boot_capabilities_harness"
    subprocess.run(
        [
            compiler,
            "-std=c++11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(FIRMWARE),
            str(Path("tests/cpp/boot_capabilities_harness.cpp")),
            str(FIRMWARE / "otis_boot_capabilities.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
    )
    subprocess.run([str(executable)], check=True)


def test_named_phases_directly_bracket_selected_initializers() -> None:
    source = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )

    expected_work = {
        "boot_phase_early_init": "otis_resource_registry_begin()",
        "boot_phase_clocks_init": "otis_timebase_begin()",
        "boot_phase_ring_buffers_init": "otis_capture_ring_reset()",
        "boot_phase_serial_init": "otis_transport_begin(",
        "boot_phase_timer_init": "otis_count_observation_begin(",
        "boot_phase_pps_input_init": "begin_edge_capture_backend(",
        "boot_phase_peripherals_init": "otis_dac_ad5693r_begin()",
        "boot_phase_preview_init": "otis_phase4_observe_preview_begin(",
        "boot_phase_capability_audit": "otis_resource_registry_complete()",
    }
    for function, work in expected_work.items():
        start = source.index(f"void {function}(void)")
        end = source.index("\nvoid ", start + 1)
        body = source[start:end]
        begin = body.index("begin_boot_phase(")
        actual_work = body.index(work)
        complete = body.index("complete_boot_phase(")
        assert begin < actual_work < complete

    run_start = source.index("void boot_phase_run_mode(void)")
    run_end = source.index("\nvoid service_loopback_output", run_start)
    run_body = source[run_start:run_end]
    gate = run_body.index("otis_boot_capability_mark_run_mode(")
    enter = run_body.index("enter_boot_phase(BootPhase::RunMode)")
    breadcrumb = run_body.index("otisBootBreadcrumbMarkRunMode()")
    assert gate < enter < breadcrumb
    assert "setup_mode();" not in run_body


def test_profile_policy_is_explicit_in_firmware() -> None:
    source = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    policy_start = source.index("void configure_selected_capabilities(void)")
    policy_end = source.index(
        "void emit_selected_capability_status();", policy_start
    )
    policy = source[policy_start:policy_end]

    for capability in (
        "ResourceRegistry",
        "SparseCapture",
        "PpsCapture",
        "CountBackend",
        "Dac",
        "Sensors",
        "Phase4Preview",
        "Transport",
    ):
        assert f"OtisBootCapability::{capability}" in policy
    assert "OtisBootCapabilityRequirement::Required" in policy
    assert "OtisBootCapabilityRequirement::Optional" in policy


def test_blocked_boot_reports_outcomes_after_late_host_attachment() -> None:
    source = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    start = source.index("void halt_boot(")
    end = source.index("\nvoid enter_safe_mode", start)
    body = source[start:end]

    late_host = body[body.index("while (true)") :]
    assert late_host.index("emit_protocol_banner_if_serial_ready()") < (
        late_host.index("emit_selected_capability_status()")
    )
    assert late_host.index("emit_selected_capability_status()") < (
        late_host.index("emit_resource_ownership_status()")
    )
    assert late_host.index("emit_resource_ownership_status()") < (
        late_host.index("emitOtisBootFatal(")
    )
    assert "fatal_emitted = true" in late_host
