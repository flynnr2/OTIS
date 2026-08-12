from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools import no_write_qualification_run as rehearsal


def test_same_owner_rotation_preserves_cumulative_reconnect_count() -> None:
    response = {
        "status": "completed",
        "pid": 5436,
        "serial_reopened": False,
        "reconnect_count": 3,
    }

    assert rehearsal._same_owner_rotation_completed(
        response,
        capture_pid=5436,
        reconnect_count_before_rotation=3,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("status", "failed"),
        ("pid", 9999),
        ("serial_reopened", True),
        ("reconnect_count", 4),
    ),
)
def test_same_owner_rotation_rejects_changed_transport_state(
    field: str, value: object
) -> None:
    response = {
        "status": "completed",
        "pid": 5436,
        "serial_reopened": False,
        "reconnect_count": 3,
    }
    response[field] = value

    assert not rehearsal._same_owner_rotation_completed(
        response,
        capture_pid=5436,
        reconnect_count_before_rotation=3,
    )


def test_supervisor_terminal_requires_explicit_healthy_stop(
    tmp_path: Path,
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    state_path = reports / "cx317_active_supervisor_state.json"
    base = {
        "cx319_gate": "G1",
        "manual_start_sent": False,
        "authorization_sequence": 0,
    }
    state_path.write_text(
        json.dumps(
            {
                **base,
                "terminal": {"result": "aborted", "reason": "fault"},
            }
        ),
        encoding="utf-8",
    )
    assert rehearsal._supervisor_terminal(tmp_path) is False

    state_path.write_text(
        json.dumps(
            {
                **base,
                "terminal": {
                    "result": "healthy_stop",
                    "reason": "finite_endpoint_complete",
                },
            }
        ),
        encoding="utf-8",
    )
    assert rehearsal._supervisor_terminal(tmp_path) is True


def test_preanalysis_failure_is_recorded_and_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered: dict[str, object] = {}

    def fake_register_package(**kwargs: object) -> dict[str, str]:
        registered.update(kwargs)
        return {"content_sha256": "f" * 64}

    monkeypatch.setattr(
        rehearsal, "register_package", fake_register_package
    )
    bundle = {
        "bundle_sha256": "b" * 64,
        "leg": {"leg": "A"},
        "firmware": {
            "git_commit": "1" * 40,
            "profile_id": "cx319_tight_lower",
            "build_manifest": {"sha256": "2" * 64},
        },
    }

    result = rehearsal._retain_orchestration_failure(
        run_dir=tmp_path,
        bundle=bundle,
        evidence_index_path=tmp_path.parent / "index.json",
        error=RuntimeError("synthetic cross-surface failure"),
    )

    report = json.loads(
        (tmp_path / rehearsal.ORCHESTRATION_FAILURE_PATH).read_text(
            encoding="utf-8"
        )
    )
    assert result["content_sha256"] == "f" * 64
    assert report["failure_class"] == "platform_defect_caught_in_rehearsal"
    assert report["error"] == "synthetic cross-surface failure"
    assert registered["attempt_classification"] == "failed_rehearsal"
    assert registered["package_path"] == tmp_path


def test_confirmed_firmware_reuse_performs_no_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = {
        "address": "/dev/cu.test-otis",
        "serial_number": "503533748A919118",
    }
    source_record = tmp_path / "source-flash.json"
    source_record.write_text("{}", encoding="utf-8")
    source_bundle = tmp_path / "source-bundle.json"
    source_bundle.write_text("{}", encoding="utf-8")
    entry = {
        "mode": "reuse_confirmed_installed_firmware",
        "firmware_flashes_allowed": 0,
        "source_flash_record": {
            "path": str(source_record),
            "sha256": "1" * 64,
            "size_bytes": 2,
        },
        "source_bundle": {
            "path": str(source_bundle),
            "sha256": "2" * 64,
            "size_bytes": 2,
        },
        "source_bundle_sha256": "3" * 64,
        "source_build_manifest_sha256": "4" * 64,
        "installed_uf2_sha256": "5" * 64,
        "installed_board": board,
    }
    bundle = {
        "bundle_sha256": "6" * 64,
        "device": {"path": "/dev/cu.test-otis"},
        "firmware": {
            "profile_id": "cx319_tight_lower",
            "build_manifest": {"sha256": "7" * 64},
            "uf2": {"sha256": "5" * 64},
        },
        "firmware_entry": entry,
    }
    monkeypatch.setattr(
        rehearsal,
        "validate_confirmed_installed_firmware",
        lambda **_kwargs: entry,
    )
    monkeypatch.setattr(rehearsal, "_serial_owner_pids", lambda _device: set())
    monkeypatch.setattr(
        rehearsal, "read_board_identity", lambda *_args, **_kwargs: board
    )
    monkeypatch.setattr(
        rehearsal.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("upload path must not execute"),
    )

    record = rehearsal.confirm_installed_bundle(
        bundle=bundle,
        output_path=tmp_path / "reuse-record.json",
        arduino_cli="arduino-cli",
    )

    assert record["status"] == "pass"
    assert record["attempt_count"] == 0
    assert record["firmware_flashes"] == 0
    assert record["ordinary_restart_count"] == 0
    assert record["attachment_mode"] == "running_instrument"


def test_run_rejects_repo_local_evidence_index_before_run_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "must-not-be-created"
    monkeypatch.setattr(
        rehearsal, "require_programme_operation_allowed", lambda *_args: None
    )
    monkeypatch.setattr(
        rehearsal,
        "validate_bundle",
        lambda _path: {
            "firmware": {
                "git_commit": "1" * 40,
                "build_manifest": {"sha256": "2" * 64},
                "profile_id": "cx319_tight_lower",
            }
        },
    )

    with pytest.raises(
        ValueError, match="evidence index must be stored outside"
    ):
        rehearsal.run_no_write_qualification(
            bundle_path=tmp_path / "bundle.json",
            run_dir=run_dir,
            evidence_index_path=Path(__file__).resolve().parents[1]
            / "build"
            / "invalid-index.json",
            arduino_cli="arduino-cli",
        )

    assert not run_dir.exists()


def test_q1_confirmed_reuse_observes_restart_without_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = {
        "address": "/dev/cu.test-otis",
        "serial_number": "503533748A919118",
    }
    source_record = tmp_path / "source-flash.json"
    source_record.write_text("{}", encoding="utf-8")
    source_bundle = tmp_path / "source-bundle.json"
    source_bundle.write_text("{}", encoding="utf-8")
    entry = {
        "mode": "reuse_confirmed_installed_firmware",
        "firmware_flashes_allowed": 0,
        "source_flash_record": {
            "path": str(source_record),
            "sha256": "1" * 64,
            "size_bytes": 2,
        },
        "source_bundle": {
            "path": str(source_bundle),
            "sha256": "2" * 64,
            "size_bytes": 2,
        },
        "source_bundle_sha256": "3" * 64,
        "source_build_manifest_sha256": "4" * 64,
        "installed_uf2_sha256": "5" * 64,
        "installed_board": board,
    }
    bundle = {
        "bundle_sha256": "6" * 64,
        "device": {"path": "/dev/cu.test-otis"},
        "firmware": {
            "profile_id": "cx319_tight_lower",
            "build_manifest": {"sha256": "7" * 64},
            "uf2": {"sha256": "5" * 64},
        },
        "firmware_entry": entry,
    }
    existence = iter((True, False, False, True, True))
    monkeypatch.setattr(
        rehearsal,
        "validate_confirmed_installed_firmware",
        lambda **_kwargs: entry,
    )
    monkeypatch.setattr(rehearsal, "_serial_owner_pids", lambda _device: set())
    identity_calls: list[str] = []

    def read_identity(*_args: object, **_kwargs: object) -> dict[str, str]:
        identity_calls.append("board_list")
        return board

    monkeypatch.setattr(rehearsal, "read_board_identity", read_identity)
    monkeypatch.setattr(rehearsal.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        rehearsal.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("upload path must not execute"),
    )

    record = rehearsal.restart_confirmed_installed_bundle(
        bundle=bundle,
        arduino_cli="arduino-cli",
        timeout_s=1.0,
        device_exists=lambda _path: next(existence),
    )

    assert record["status"] == "pending_carrier_identity"
    assert record["ordinary_restart_count"] == 1
    assert record["firmware_flashes"] == 0
    assert identity_calls == ["board_list"]
    assert record["restart_reappeared_monotonic_ns"] >= record[
        "restart_disappeared_monotonic_ns"
    ]

    carrier_ready = record["restart_reappeared_monotonic_ns"] + 1
    completed = rehearsal.confirm_firmware_entry_after_carrier_attach(
        pending_record=record,
        output_path=tmp_path / "restart-record.json",
        arduino_cli="arduino-cli",
        carrier_ready_monotonic_ns=carrier_ready,
    )

    assert completed["status"] == "pass"
    assert completed["post_reset_identity_order"] == (
        "carrier_then_board_enumeration"
    )
    assert completed["post_reset_identity_started_monotonic_ns"] >= (
        carrier_ready
    )
    assert identity_calls == ["board_list", "board_list"]
