from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools import cx318_stage5_rehearsal_analyze as analyzer


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
        "# OTIS_HOST {\"event\": \"capture_started\", \"utc\": \"2026-08-10T00:00:00Z\"}\n"
        f"# OTIS_HOST {{\"event\": \"capture_stopped\", \"utc\": \"2026-08-10T00:{duration_s // 60:02d}:{duration_s % 60:02d}Z\"}}\n",
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

    _write_json(
        run_dir / analyzer.CAPTURE_STATE,
        {
            "capture_active": False,
            "serial_open": False,
            "reconnect_count": 0,
            "parser_errors": 0,
            "malformed_utf8": 0,
            "commands_rejected": 0,
            "emergency_aborts_sent": 0,
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
    spec = SimpleNamespace(run_identity="fixture-run", profile="fixture-profile")
    health = {
        ("cx317_active", "run_identity"): spec.run_identity,
        ("cx317_active", "build_identity"): "source:configuration",
        ("cx317_active", "profile_identity"): spec.profile,
        ("cx317_active", "firmware_identity"): identities["firmware_identity"],
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "manual_start_confirmed"): "false",
        ("cx317_active", "arm_eligible"): "false",
        ("cx317_active", "dac_epoch"): "0",
        ("cx318_preview", "static_code"): "0xA828",
        ("cx318_preview", "applied_code"): "0xA828",
        ("cx318_preview", "dac_epoch"): "0",
        ("capture", "dropped_count"): "0",
        ("capture", "pps_count_boundary_dropped_count"): "0",
        ("dual_core", "telemetry_dropped"): "0",
        ("dual_core", "partition_fault"): "none",
        ("dual_core", "fail_static"): "false",
        ("cx317_active", "fail_static"): "false",
        ("cx318_preview", "telemetry_dropped_frames"): "0",
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
        "load_stage5_spec",
        lambda leg: (spec, identities, object()),
    )
    monkeypatch.setattr(
        analyzer,
        "validate_csv",
        lambda *args, **kwargs: SimpleNamespace(ok=True, row_count=1, errors=[]),
    )
    monkeypatch.setattr(analyzer, "_read_csv", read_csv)
    monkeypatch.setattr(analyzer, "_latest_health", lambda _: health)
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
    assert result["checks"]["zero_dac_or_active_rows"] is True
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


@pytest.mark.parametrize(
    ("kwargs", "failed_check"),
    [
        ({"duration_s": 2699}, "finite_capture_at_least_2700s"),
        ({"authority": True}, "phase_hybrid_and_tdb_zero_authority"),
        ({"evidence_failures": ["tampered evidence"]}, "sealed_evidence_snapshot_valid"),
        ({"active_rows": True}, "zero_dac_or_active_rows"),
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
