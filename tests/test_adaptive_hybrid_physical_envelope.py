from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools import adaptive_hybrid_activation as activation_module
from host.otis_tools import adaptive_hybrid_run as run_module
from host.otis_tools.adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    INHIBITED_ZERO_WRITE,
    SINGLE_AUTOMATIC_APPLICATION,
    envelope_for_purpose,
)


def _board_listing(*, product: str = "Nano RP2040 Connect") -> dict[str, object]:
    return {
        "detected_ports": [
            {
                "port": {
                    "address": "/dev/cu.usbmodem-test",
                    "hardware_id": "503533748A919118",
                    "properties": {
                        "serialNumber": "503533748A919118",
                        "vid": "0x2341",
                        "pid": "0x005e",
                        "product": product,
                    },
                },
                "matching_boards": [
                    {
                        "name": "Arduino Nano RP2040 Connect",
                        "fqbn": "rp2040:rp2040:arduino_nano_connect",
                    }
                ],
            }
        ]
    }


@pytest.mark.parametrize(
    ("purpose", "setup", "automatic", "arms", "writes"),
    (
        (INHIBITED_ZERO_WRITE, 0, 0, 0, 0),
        (SINGLE_AUTOMATIC_APPLICATION, 1, 1, 4, 2),
    ),
)
def test_activation_and_run_fields_derive_from_exact_bench_envelope(
    purpose: str, setup: int, automatic: int, arms: int, writes: int
) -> None:
    bench = envelope_for_purpose(purpose)
    authority = activation_module._authority(ADAPTIVE_HYBRID_PROGRAMME, bench)
    section = activation_module._run_section(
        ADAPTIVE_HYBRID_PROGRAMME, authority, bench
    )

    assert authority["firmware_flash_limit"] == 1
    assert authority["setup_write_limit"] == setup
    assert authority["maximum_total_automatic_applications"] == automatic
    assert authority["arm_submission_limit"] == arms
    assert authority["total_dac_value_write_limit"] == writes
    assert authority["absolute_wall_clock_limit_s"] == 7200
    assert section["purpose"] == purpose
    assert section["automatic_control"]["maximum_total_applications"] == automatic
    assert section["qualification"]["progress_domain"] == (
        "accepted_D14_D8_apertures"
    )


def test_board_identity_checks_every_envelope_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = SimpleNamespace(stdout=json.dumps(_board_listing()))
    monkeypatch.setattr(run_module.subprocess, "run", lambda *_args, **_kwargs: completed)
    bench = envelope_for_purpose(INHIBITED_ZERO_WRITE)

    identity = run_module.read_board_identity(
        "/dev/cu.usbmodem-test", bench_attempt=bench
    )
    assert identity["product"] == "Nano RP2040 Connect"

    completed.stdout = json.dumps(_board_listing(product="lookalike"))
    with pytest.raises(ValueError, match="accepted OTIS bench board"):
        run_module.read_board_identity(
            "/dev/cu.usbmodem-test", bench_attempt=bench
        )


@pytest.mark.parametrize(
    "purpose", (INHIBITED_ZERO_WRITE, SINGLE_AUTOMATIC_APPLICATION)
)
def test_single_upload_record_binds_envelope_and_compile_identity(
    purpose: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench = envelope_for_purpose(purpose)
    identity = bench.as_dict()["device_identity"]
    board = {
        "address": "/dev/cu.usbmodem-test",
        "serial_number": identity["expected_board_serial"],
        "hardware_id": identity["expected_hardware_id"],
        "vid": identity["expected_usb_vid"],
        "pid": identity["expected_usb_pid"],
        "product": identity["expected_usb_product"],
        "board_name": identity["expected_board_name"],
        "board_fqbn": identity["expected_base_fqbn"],
    }
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="uploaded", stderr="")

    monkeypatch.setattr(run_module.subprocess, "run", run)
    monkeypatch.setattr(run_module, "_fresh_auto_detect_device", lambda: board["address"])
    monkeypatch.setattr(run_module, "read_board_identity", lambda *_args, **_kwargs: board)
    activation = {
        "bench_attempt": bench.as_dict(),
        "authority": {"firmware_flash_limit": 1},
        "firmware": {
            "fqbn": identity["expected_compile_fqbn"],
            "uf2": {"path": "/tmp/frozen.uf2", "sha256": "a" * 64},
            "build_identity": "source:config",
            "image_id": ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        },
        "bundle": {"bundle_sha256": "b" * 64},
    }

    _, _, record = run_module._upload_exact_firmware(
        run_dir=tmp_path,
        activation=activation,
        device=str(board["address"]),
        board_before=board,
        arduino_cli="arduino-cli",
    )

    assert len(calls) == 1
    assert record["firmware_flash_count"] == 1
    assert record["bench_attempt"] == bench.as_dict()
    assert record["compile_fqbn"] == identity["expected_compile_fqbn"]
    assert record["dac_value_write_attempts"] == 0


def test_runner_durations_and_terminals_are_envelope_derived(tmp_path: Path) -> None:
    zero = envelope_for_purpose(INHIBITED_ZERO_WRITE)
    one = envelope_for_purpose(SINGLE_AUTOMATIC_APPLICATION)
    capture = run_module._capture_command(
        device="/dev/cu.usbmodem-test", run_dir=tmp_path, bench_attempt=zero
    )
    supervisor = run_module._supervisor_command(
        run_dir=tmp_path, build_identity="source:config", bench_attempt=one
    )
    assert capture[capture.index("--duration-s") + 1] == "7380"
    assert supervisor[supervisor.index("--duration-s") + 1] == "7320"
    assert run_module._terminal_expected(
        {
            "result": "healthy_stop",
            "reason": "inhibited_zero_write_complete",
            "preliminary_decision": "pending_offline_scientific_analysis",
            "last_confirmed_code": 43000,
        },
        zero,
    )
    assert run_module._terminal_expected(
        {
            "result": "nonpass",
            "primary_decision": "bounded_no_natural_correction",
            "last_confirmed_code": 43000,
        },
        one,
    )
