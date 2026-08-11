from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools import cx319_g1_rehearsal as rehearsal


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
