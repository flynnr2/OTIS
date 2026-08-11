from __future__ import annotations

from dataclasses import dataclass
import json
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools import tight_deadband_rehearsal_analyze as analyzer
from host.otis_tools.active_status_contract import (
    ACTIVE_STATUS_KEYS,
    ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    SNAPSHOT_BEGIN_KEY,
    SNAPSHOT_COMPLETE_KEY,
    SNAPSHOT_CONTRACT_KEY,
)


@dataclass(frozen=True)
class _Replay:
    exact: bool = True
    row_count: int = 1

    def as_dict(self) -> dict[str, object]:
        return {
            "exact": self.exact,
            "ok": self.exact,
            "row_count": self.row_count,
            "errors": [] if self.exact else ["fixture mismatch"],
        }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    duration_s: int = 2700,
    authority: bool = False,
    evidence_failures: list[str] | None = None,
    active_rows: bool = False,
) -> Path:
    """Build a minimal isolated run while mocking only unrelated parsers.

    The analyzer's own file lifecycle, marker parsing, final check assembly,
    source hashing, and atomic publication remain real in these tests.
    """
    run_dir = tmp_path / "rehearsal"
    (run_dir / "raw").mkdir(parents=True)
    (run_dir / "csv").mkdir()
    (run_dir / "reports").mkdir()
    (run_dir / "COMPLETE").touch()
    (run_dir / "run_manifest.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "raw/serial.log").write_text(
        "# OTIS_HOST {\"event\": \"capture_started\", \"utc\": \"2026-08-10T00:00:00Z\", \"owner_pid\": 42, \"transport_generation\": 1}\n"
        f"# OTIS_HOST {{\"event\": \"capture_stopped\", \"utc\": \"2026-08-10T00:{duration_s // 60:02d}:{duration_s % 60:02d}Z\", \"owner_pid\": 42, \"transport_generation\": 1, \"logical_rotation\": false, \"next_run\": null}}\n",
        encoding="utf-8",
    )

    # Include every evidence stream in the manifest inventory so the emitted
    # seal has a real hash for all no-write inputs, not merely a synthetic one.
    relative_paths = (
        analyzer.ACTIVE_CSV,
        analyzer.DAC_CSV,
        analyzer.ENVIRONMENT_CSV,
        analyzer.ESTIMATES_CSV,
        analyzer.CONTROL_CSV,
        analyzer.RPH_CSV,
        analyzer.PHE_CSV,
        analyzer.HPR_CSV,
        analyzer.TDB_CSV,
        analyzer.HEALTH_CSV,
    )
    files = []
    contracts: dict[str, int] = {}
    for index, relative in enumerate(relative_paths):
        contract = f"fixture_contract_{index}"
        target = run_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture\n", encoding="utf-8")
        files.append({"path": str(relative), "contract": contract})
        contracts[contract] = 1
    association_relative = Path("csv/association_loss_decisions_v1.csv")
    (run_dir / association_relative).write_text("fixture\n", encoding="utf-8")
    files.append(
        {
            "path": str(association_relative),
            "contract": "association_loss_decisions_v1",
        }
    )
    contracts["association_loss_decisions_v1"] = 1

    _write_json(
        run_dir / analyzer.CAPTURE_STATE,
        {
            "pid": 42,
            "capture_active": False,
            "serial_open": False,
            "logical_segment_closed": True,
            "physical_serial_open": False,
            "transport_generation": 1,
            "reconnect_count": 0,
            "parser_errors": 0,
            "malformed_utf8": 0,
            "commands_rejected": 0,
            "emergency_aborts_sent": 0,
        },
    )
    _write_json(
        run_dir / analyzer.SEGMENT_CLOSURE,
        {
            "schema_version": 1,
            "protocol": analyzer.SEGMENT_PROTOCOL_ID,
            "run": str(run_dir.resolve()),
            "run_manifest_sha256": sha256(
                (run_dir / "run_manifest.json").read_bytes()
            ).hexdigest(),
            "owner_pid": 42,
            "transport_generation": 1,
            "closure_mode": "physical_serial_close",
            "logical_segment_closed": True,
            "physical_serial_open": False,
            "serial_reopened": False,
            "next_run": None,
            "request_id": None,
            "serial_owner_check": None,
            "counters": {
                "reconnect_count": 0,
                "parser_errors": 0,
                "malformed_utf8": 0,
                "commands_rejected": 0,
                "emergency_aborts_sent": 0,
            },
        },
    )
    _write_json(
        run_dir / analyzer.SUPERVISOR_STATE,
        {
            "stage5_mode": "rehearsal",
            "stage5_leg": "A",
            "manual_start_sent": False,
            "authorization_sequence": 0,
            "terminal": {"result": "healthy_stop"},
        },
    )
    (run_dir / analyzer.SUPERVISOR_EVENTS).write_text("\n", encoding="utf-8")
    _write_json(
        run_dir / analyzer.EVIDENCE_MANIFEST,
        {"run_state": "complete", "snapshot_digest": "e" * 64},
    )

    manifest_value = {
        "stage": analyzer.REHEARSAL_STAGE,
        "stage5": {"leg": "A"},
        "contracts": contracts,
        "firmware": {
            "source_sha256": "source",
            "configuration_sha256": "configuration",
            "sha256": "build",
            "uf2": {"sha256": "uf2"},
        },
    }
    manifest = SimpleNamespace(
        root=run_dir,
        files=files,
        known_channels=frozenset(),
        known_domains=frozenset(),
    )
    identities = {"firmware_identity": "fixture-firmware"}
    spec = SimpleNamespace(
        run_identity="fixture-run", profile="fixture-profile", start_code=0xA808
    )
    health = {
        **{
            ("cx317_active", key): "present"
            for key in ACTIVE_STATUS_KEYS
        },
        ("cx317_active", "run_identity"): spec.run_identity,
        ("cx317_active", "build_identity"): "source:configuration",
        ("cx317_active", "profile_identity"): spec.profile,
        ("cx317_active", "firmware_identity"): identities["firmware_identity"],
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "enabled"): "true",
        ("cx317_active", "reason"): "initialized_disarmed",
        ("cx317_active", "evidence_pending"): "false",
        ("cx317_active", "evidence_phase"): "evidence_clear",
        ("cx317_active", "capture_lease_live"): "true",
        ("cx317_active", "manual_start_confirmed"): "false",
        ("cx317_active", "arm_eligible"): "false",
        ("cx317_active", "session_id"): "1",
        ("cx317_active", "uptime_s"): "2700",
        ("cx317_active", "evidence_request_sequence"): "0",
        ("cx317_active", "expected_setup_code"): "0xA808",
        ("cx317_active", "confirmed_applied_code_known"): "false",
        ("cx317_active", "confirmed_applied_code"): "unavailable",
        ("cx317_active", "correction_count"): "0",
        ("cx317_active", "cumulative_movement_codes"): "0",
        ("cx317_active", "dac_epoch"): "0",
        ("cx317_active", "selected_interval_count"): "1",
        ("cx317_active", "automatic_retry"): "false",
        ("cx317_active", "automatic_restore"): "false",
        ("cx318_preview", "static_code"): "0xA828",
        ("cx318_preview", "applied_code"): "0xA828",
        ("cx318_preview", "dac_epoch"): "0",
        ("cx317_preview", "actionable"): "false",
        ("cx317_preview", "actuation_authorized"): "false",
        ("cx318_preview", "actionable"): "false",
        ("cx318_preview", "actuation_authorized"): "false",
        ("cx318_preview", "authorization_consumed"): "false",
        ("dac", "applied_code_known"): "false",
        ("dac", "last_write_ok"): "false",
        ("dac", "last_applied_code"): "unavailable",
        ("capture", "dropped_count"): "0",
        ("capture", "pps_count_boundary_dropped_count"): "0",
        ("dual_core", "telemetry_dropped"): "0",
        ("dual_core", "service_publish_failures"): "0",
        ("dual_core", "partition_fault"): "none",
        ("dual_core", "fail_static"): "false",
        ("cx317_active", "fail_static"): "false",
        ("cx317_preview", "telemetry_dropped_frames"): "0",
        ("cx317_active", SNAPSHOT_BEGIN_KEY): "1",
        ("cx317_active", SNAPSHOT_CONTRACT_KEY): ACTIVE_STATUS_SNAPSHOT_CONTRACT,
        ("cx317_active", SNAPSHOT_COMPLETE_KEY): "1",
    }
    authority_row = {
        "actionable": "true" if authority else "false",
        "actuation_authorized": "false",
        "authorization_consumed": "false",
    }

    def read_csv(path: Path) -> list[dict[str, str]]:
        path = Path(path)
        if path == run_dir / analyzer.ACTIVE_CSV:
            return [{"event": "automatic"}] if active_rows else []
        if path == run_dir / analyzer.DAC_CSV:
            return []
        if path == run_dir / analyzer.ESTIMATES_CSV:
            return [{"estimator_version": "cx317_selected_600s_nonoverlap_v1"}]
        if path == run_dir / analyzer.ENVIRONMENT_CSV:
            return [{"source": "sht4x"}, {"source": "bmp280"}]
        return [authority_row]

    monkeypatch.setattr(analyzer, "validate_manifest", lambda _: manifest_value)
    monkeypatch.setattr(analyzer, "load_manifest", lambda _: manifest)
    monkeypatch.setattr(
        analyzer,
        "load_tight_deadband_spec",
        lambda leg: (spec, identities, object()),
    )
    def validate_csv(*args, **kwargs):
        context = args[1]
        rows = 0 if context.contract == "association_loss_decisions_v1" else 1
        return SimpleNamespace(ok=True, row_count=rows, errors=[])

    monkeypatch.setattr(analyzer, "validate_csv", validate_csv)
    monkeypatch.setattr(analyzer, "_read_csv", read_csv)
    monkeypatch.setattr(analyzer, "latest_complete_health", lambda _: health)
    monkeypatch.setattr(analyzer, "replay_tight_deadband", lambda _: _Replay())
    monkeypatch.setattr(
        analyzer,
        "validate_evidence_snapshot",
        lambda *_: (evidence_failures or [], []),
    )
    return run_dir


def test_analyzer_seals_exact_2700_second_no_write_rehearsal_and_never_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _fixture_run(tmp_path, monkeypatch)

    output, result = analyzer.analyze(run_dir)

    assert result["status"] == "passed"
    assert result["checks"]["finite_capture_at_least_2700s"] is True
    assert result["checks"]["stage5_prewrite_runtime_contract_exact"] is True
    assert result["checks"]["phase_hybrid_and_tdb_zero_authority"] is True
    assert result["checks"]["sealed_evidence_snapshot_valid"] is True
    assert result["source_artifacts_sha256"]["raw/serial.log"]
    original = output.read_bytes()

    # A later source modification cannot silently replace the published seal.
    (run_dir / "raw/serial.log").write_text(
        (run_dir / "raw/serial.log").read_text(encoding="utf-8") + "tampered\n",
        encoding="utf-8",
    )
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        analyzer.analyze(run_dir)
    assert output.read_bytes() == original


def test_capture_closure_accepts_only_proven_same_owner_logical_rotation(
    tmp_path: Path,
) -> None:
    run_dir = (tmp_path / "rehearsal").resolve()
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text("{}\n", encoding="utf-8")
    state = {
        "pid": 42,
        "capture_active": False,
        "serial_open": True,
        "logical_segment_closed": True,
        "physical_serial_open": True,
        "transport_generation": 1,
        "reconnect_count": 0,
        "parser_errors": 0,
        "malformed_utf8": 0,
        "commands_rejected": 0,
        "emergency_aborts_sent": 0,
    }
    markers = [
        {
            "event": "capture_started",
            "owner_pid": 42,
            "transport_generation": 1,
        },
        {
            "event": "capture_stopped",
            "owner_pid": 42,
            "transport_generation": 1,
            "logical_rotation": True,
            "next_run": str(tmp_path / "transition"),
        },
    ]
    closure = {
        "schema_version": 1,
        "protocol": analyzer.SEGMENT_PROTOCOL_ID,
        "run": str(run_dir),
        "run_manifest_sha256": sha256(
            (run_dir / "run_manifest.json").read_bytes()
        ).hexdigest(),
        "owner_pid": 42,
        "transport_generation": 1,
        "closure_mode": "same_owner_logical_rotation",
        "logical_segment_closed": True,
        "physical_serial_open": True,
        "serial_reopened": False,
        "next_run": str(tmp_path / "transition"),
        "request_id": "0" * 32,
        "serial_owner_check": {"performed": True, "owner_pids": [42]},
        "counters": {
            "reconnect_count": 0,
            "parser_errors": 0,
            "malformed_utf8": 0,
            "commands_rejected": 0,
            "emergency_aborts_sent": 0,
        },
    }
    _write_json(run_dir / analyzer.SEGMENT_CLOSURE, closure)

    result = analyzer._capture_closure(run_dir, state, markers)
    assert result["ok"] is True
    assert result["mode"] == "same_owner_logical_rotation"

    closure["serial_owner_check"]["owner_pids"] = [99]
    _write_json(run_dir / analyzer.SEGMENT_CLOSURE, closure)
    result = analyzer._capture_closure(run_dir, state, markers)
    assert result["ok"] is False


def test_capture_closure_accepts_a_clean_physical_serial_close(
    tmp_path: Path,
) -> None:
    run_dir = (tmp_path / "live").resolve()
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text("{}\n", encoding="utf-8")
    state = {
        "pid": 42,
        "capture_active": False,
        "serial_open": False,
        "logical_segment_closed": True,
        "physical_serial_open": False,
        "transport_generation": 1,
        "reconnect_count": 0,
        "parser_errors": 0,
        "malformed_utf8": 0,
        "commands_rejected": 0,
        "emergency_aborts_sent": 0,
    }
    markers = [
        {
            "event": "capture_started",
            "owner_pid": 42,
            "transport_generation": 1,
        },
        {
            "event": "capture_stopped",
            "owner_pid": 42,
            "transport_generation": 1,
            "logical_rotation": False,
            "next_run": None,
        },
    ]
    closure = {
        "schema_version": 1,
        "protocol": analyzer.SEGMENT_PROTOCOL_ID,
        "run": str(run_dir),
        "run_manifest_sha256": sha256(
            (run_dir / "run_manifest.json").read_bytes()
        ).hexdigest(),
        "owner_pid": 42,
        "transport_generation": 1,
        "closure_mode": "physical_serial_close",
        "logical_segment_closed": True,
        "physical_serial_open": False,
        "serial_reopened": False,
        "next_run": None,
        "request_id": None,
        "serial_owner_check": None,
        "counters": {
            "reconnect_count": 0,
            "parser_errors": 0,
            "malformed_utf8": 0,
            "commands_rejected": 0,
            "emergency_aborts_sent": 0,
        },
    }
    _write_json(run_dir / analyzer.SEGMENT_CLOSURE, closure)

    result = analyzer._capture_closure(run_dir, state, markers)

    assert result["ok"] is True
    assert result["mode"] == "physical_serial_close"


@pytest.mark.parametrize(
    ("kwargs", "failed_check"),
    [
        ({"duration_s": 2699}, "finite_capture_at_least_2700s"),
        ({"authority": True}, "phase_hybrid_and_tdb_zero_authority"),
        ({"evidence_failures": ["tampered evidence"]}, "sealed_evidence_snapshot_valid"),
        ({"active_rows": True}, "stage5_prewrite_runtime_contract_exact"),
    ],
)
def test_analyzer_emits_failed_nonseal_when_no_write_guards_do_not_hold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, object],
    failed_check: str,
) -> None:
    run_dir = _fixture_run(tmp_path, monkeypatch, **kwargs)

    output, result = analyzer.analyze(run_dir)

    assert output.is_file()
    assert result["status"] == "failed"
    assert result["checks"][failed_check] is False
    assert result["seal_sha256"]


def test_analyzer_refuses_an_active_or_incomplete_capture_before_reading_evidence(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "still-running"
    run_dir.mkdir()
    (run_dir / "capture_in_progress.flag").touch()

    with pytest.raises(ValueError, match="still active"):
        analyzer.analyze(run_dir)

    (run_dir / "capture_in_progress.flag").unlink()
    with pytest.raises(ValueError, match="not marked complete"):
        analyzer.analyze(run_dir)
