from __future__ import annotations

import json
from pathlib import Path
import pytest

from host.otis_tools import adaptive_hybrid_operational_rehearsal as rehearsal
from host.otis_tools.evidence_finalization import journal_path_for


def _hashed(value: dict[str, object], field: str) -> dict[str, object]:
    return {**value, field: rehearsal._canonical_sha256(value)}


def test_supervisor_worker_retains_exact_startup_phase_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bundle_path = tmp_path / "bundle.json"
    proposal_path = tmp_path / "proposal.json"
    bundle_path.write_text(
        json.dumps(_hashed({}, "bundle_sha256")) + "\n", encoding="utf-8"
    )
    proposal_path.write_text(
        json.dumps(_hashed({}, "proposal_sha256")) + "\n", encoding="utf-8"
    )
    manifest_path = run_dir / "run_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "bundle": {"path": str(bundle_path)},
                "proposal": {"path": str(proposal_path)},
                "host": {
                    "fifos": {
                        "normal_command": "control/normal_commands.fifo",
                        "emergency_abort": "control/emergency_abort.fifo",
                        "host_abort": "control/host_abort.fifo",
                    }
                },
                "firmware": {"build_identity": "source:configuration"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        rehearsal,
        "_validate_manifest_value",
        lambda _path, value, **_kwargs: value,
    )

    monkeypatch.setattr(rehearsal, "prepare_validated_nonphysical_rehearsal_context", lambda _manifest, **_kwargs: object())

    monkeypatch.setattr(rehearsal, "_load_worker_manifest", lambda path: (json.loads(path.read_text()), object()))

    class FakeSupervisor:
        def run(self) -> int:
            value = json.loads(
                (run_dir / rehearsal.SUPERVISOR_STARTUP_PATH).read_text()
            )
            assert value["current_phase"] == "ready_to_run"
            return 17

    monkeypatch.setattr(
        rehearsal,
        "create_validated_nonphysical_rehearsal_supervisor",
        lambda **_kwargs: FakeSupervisor(),
    )

    assert rehearsal._supervisor_worker(manifest_path, run_dir) == 17
    value = json.loads((run_dir / rehearsal.SUPERVISOR_STARTUP_PATH).read_text())
    assert value["contract"] == rehearsal.SUPERVISOR_STARTUP_CONTRACT
    assert value["run_directory"] == str(run_dir.resolve())
    assert value["manifest"] == rehearsal._binding(manifest_path)
    assert [item["phase"] for item in value["phases"]] == [
        "worker_started",
        "manifest_validation_started",
        "manifest_validated",
        "supervisor_construction_started",
        "supervisor_constructed",
        "ready_to_run",
    ]


def _run_topology_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, TimeoutError]:
    run_dir = tmp_path / "run"
    index_path = tmp_path / "evidence_index_v1.json"
    bundle = {
        "firmware": {
            "source_revision": "a" * 40,
            "build_identity": "b" * 64 + ":" + "c" * 64,
        }
    }

    def create_manifest(**kwargs: object) -> Path:
        path = Path(kwargs["run_dir"]) / "run_manifest.json"
        path.write_text("{}\n", encoding="utf-8")
        return path

    monkeypatch.setattr(rehearsal, "create_rehearsal_run_manifest", create_manifest)
    monkeypatch.setattr(
        rehearsal, "validate_rehearsal_run_manifest", lambda *_args, **_kwargs: {}
    )
    monkeypatch.setattr(rehearsal.pty, "openpty", lambda: (-1, -1))
    monkeypatch.setattr(rehearsal.os, "ttyname", lambda _descriptor: "/dev/ttys999")
    monkeypatch.setattr(
        rehearsal,
        "_run_process_topology",
        lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("startup stalled")),
    )

    with pytest.raises(TimeoutError, match="startup stalled") as caught:
        rehearsal._run_validated(
            bundle_path=tmp_path / "bundle.json",
            bundle=bundle,
            proposal_path=tmp_path / "proposal.json",
            proposal={},
            run_dir=run_dir,
            evidence_index_path=index_path,
        )
    return run_dir, index_path, caught.value


def test_topology_failure_is_journalled_and_registered_as_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, index_path, _ = _run_topology_failure(tmp_path, monkeypatch)

    journal = json.loads(journal_path_for(run_dir).read_text())
    assert journal["primary_failure"] == {
        "phase": "process_topology",
        "error_type": "TimeoutError",
        "error": "startup stalled",
        "observed_utc": journal["primary_failure"]["observed_utc"],
    }
    assert all(value is None for value in journal["phases"].values())
    index = json.loads(index_path.read_text())
    assert len(index["packages"]) == 1
    record = next(iter(index["packages"].values()))
    assert record["attempt_classification"] == "diagnostic"
    assert record["result_or_failure_reason"] == (
        "adaptive-hybrid operational rehearsal process topology failed: "
        "TimeoutError: startup stalled"
    )
    assert not (run_dir / "COMPLETE").exists()
    assert not (run_dir / "evidence_manifest.json").exists()
    assert not (run_dir / rehearsal.SEAL_PATH).exists()


def test_diagnostic_registration_failure_is_secondary_to_topology_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        rehearsal,
        "register_package",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("index unavailable")),
    )

    _, _, error = _run_topology_failure(tmp_path, monkeypatch)

    assert "diagnostic registration also failed" in str(error)
    journal = json.loads(journal_path_for(tmp_path / "run").read_text())
    assert journal["primary_failure"]["phase"] == "process_topology"
    assert journal["secondary_failures"][0]["phase"] == "diagnostic_registration"


def test_cli_surfaces_primary_and_supplementary_topology_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        rehearsal,
        "run_operational_rehearsal",
        lambda **_kwargs: (_ for _ in ()).throw(
            TimeoutError(
                "startup stalled; process-topology diagnostic registration "
                "also failed: OSError: index unavailable"
            )
        ),
    )

    with pytest.raises(SystemExit) as stopped:
        rehearsal.main(
            [
                "run",
                "--bundle",
                str(tmp_path / "bundle.json"),
                "--proposal",
                str(tmp_path / "proposal.json"),
                "--run-dir",
                str(tmp_path / "run"),
                "--evidence-index",
                str(tmp_path / "index.json"),
            ]
        )

    assert stopped.value.code == 2
    stderr = capsys.readouterr().err
    assert "startup stalled" in stderr
    assert "diagnostic registration also failed" in stderr
