from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools import active_hybrid_activation as activation
from host.otis_tools import active_hybrid_live_rehearsal as rehearsal
from host.otis_tools.contracts import ACTIVE_HYBRID_DECISION_V1_FIELDS


def _binding(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def _fixture(tmp_path: Path) -> tuple[Path, dict, Path, dict]:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text("{}\n", encoding="utf-8")
    tool_path = tmp_path / "tool.py"
    tool_path.write_text("# tool\n", encoding="utf-8")
    bundle_path = tmp_path / "bundle.json"
    proposal_path = tmp_path / "proposal.json"
    firmware = {
        "build_identity": "a" * 64 + ":" + "b" * 64,
        "source_sha256": "a" * 64,
        "configuration_sha256": "b" * 64,
        "uf2": {"sha256": "c" * 64},
    }
    bundle = {
        "bundle_sha256": "d" * 64,
        "firmware": firmware,
        "policy": {
            **_binding(policy_path),
            "policy_sha256": "e" * 64,
        },
        "host_tools": {"fixture": _binding(tool_path)},
    }
    proposal = {
        "proposal_sha256": "f" * 64,
        "exact_bundle": {"bundle_sha256": bundle["bundle_sha256"]},
    }
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    return bundle_path, bundle, proposal_path, proposal


def test_rehearsal_manifest_is_strictly_non_authorizing_and_pty_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal = _fixture(tmp_path)
    monkeypatch.setattr(rehearsal, "validate_bundle", lambda path: bundle)
    monkeypatch.setattr(rehearsal, "validate_proposal", lambda path: proposal)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    path = rehearsal._create_rehearsal_run_manifest(
        run_dir=run_dir,
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
        device="/dev/pts/99",
    )

    observed = rehearsal.validate_rehearsal_run_manifest(path)

    assert observed["qualification_evidence"] is False
    assert observed["physical_actions_performed"] == 0
    assert observed["actionable"] is False
    assert observed["actuation_authorized"] is False


def test_rehearsal_manifest_rejects_non_pty_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal = _fixture(tmp_path)
    monkeypatch.setattr(rehearsal, "validate_bundle", lambda path: bundle)
    monkeypatch.setattr(rehearsal, "validate_proposal", lambda path: proposal)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    path = rehearsal._create_rehearsal_run_manifest(
        run_dir=run_dir,
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
        device="/dev/cu.usbmodem-real",
    )

    with pytest.raises(ValueError, match="no-I/O boundary"):
        rehearsal.validate_rehearsal_run_manifest(path)


def test_rehearsal_manifest_accepts_macos_pty_slave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal = _fixture(tmp_path)
    monkeypatch.setattr(rehearsal, "validate_bundle", lambda path: bundle)
    monkeypatch.setattr(rehearsal, "validate_proposal", lambda path: proposal)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    path = rehearsal._create_rehearsal_run_manifest(
        run_dir=run_dir,
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
        device="/dev/ttys001",
    )

    observed = rehearsal.validate_rehearsal_run_manifest(path)

    assert observed["host"]["serial_device"] == "/dev/ttys001"


def test_activation_and_rehearsal_require_the_same_complete_coverage() -> None:
    assert set(rehearsal.REHEARSAL_COVERAGE) == set(
        activation.REHEARSAL_COVERAGE
    )


def test_wire_fixture_uses_frozen_supervisor_identities() -> None:
    policy_path = (
        Path(__file__).resolve().parents[1]
        / "profiles/discipline/cx320_bounded_active_hybrid_tight_v1.json"
    )
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    bundle = {
        "firmware": {"build_identity": "a" * 64 + ":" + "b" * 64},
        "policy": {
            "path": str(policy_path),
            "policy_sha256": sha256(policy_path.read_bytes()).hexdigest(),
        },
    }

    values = rehearsal._active_hybrid_wire_fixture(bundle).decode().strip().split(",")
    row = dict(zip(ACTIVE_HYBRID_DECISION_V1_FIELDS, values, strict=True))

    assert len(values) == 56
    assert row["frequency_estimator_sha256"] == policy["bindings"][
        "frequency_estimator"
    ]["sha256"]
    assert row["phase_estimator_sha256"] == policy["bindings"]["phase_estimator"][
        "sha256"
    ]
    assert row["active_policy_sha256"] == bundle["policy"]["policy_sha256"]
    assert row["response_policy_sha256"] == policy["bindings"]["response_policy"][
        "sha256"
    ]
    assert row["actionable"] == "false"


def test_obstruction_queues_abort_before_resuming_the_supervisor() -> None:
    source = Path(rehearsal.__file__).read_text(encoding="utf-8")
    supervisor_stop = source.index(
        "os.kill(supervisor.pid, signal.SIGSTOP)"
    )
    capture_stop = source.index(
        "os.kill(capture.pid, signal.SIGSTOP)", supervisor_stop
    )
    saturate = source.index("for _ in range(100_000):", capture_stop)
    abort = source.index("send_abort(host_abort)", saturate)
    supervisor_continue = source.index(
        "os.kill(supervisor.pid, signal.SIGCONT)", abort
    )
    capture_continue = source.index(
        "os.kill(capture.pid, signal.SIGCONT)", supervisor_continue
    )

    assert (
        supervisor_stop
        < capture_stop
        < saturate
        < abort
        < supervisor_continue
        < capture_continue
    )


def test_accelerated_prewrite_boundary_uses_physical_evidence_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal = _fixture(tmp_path)
    policy_path = (
        Path(__file__).resolve().parents[1]
        / "profiles/discipline/cx320_bounded_active_hybrid_tight_v1.json"
    )
    policy_sha256 = sha256(policy_path.read_bytes()).hexdigest()
    bundle["policy"] = {
        **_binding(policy_path),
        "policy_sha256": policy_sha256,
    }
    bundle["firmware"] = {
        **bundle["firmware"],
        "source_sha256": "a" * 64,
        "configuration_sha256": "b" * 64,
    }
    monkeypatch.setattr(rehearsal, "validate_bundle", lambda path: bundle)
    monkeypatch.setattr(rehearsal, "validate_proposal", lambda path: proposal)

    result = rehearsal._exercise_prewrite_qualification_boundary(
        output_dir=tmp_path / "boundary",
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
    )

    assert result == {
        "startup_inhibit_s": 600,
        "observed_historical_qualification_s": 612,
        "qualification_deadline_s": 660,
        "waits_while_unqualified_at_30s": True,
        "ready_at_observed_612s": True,
        "atomic_handoff_hybrid_state": "SETUP_PENDING",
        "first_post_setup_consumer_passed": True,
        "missing_authority_at_660s_is_terminal": True,
        "setup_commands_issued": 0,
        "physical_actions_performed": 0,
    }


def test_accelerated_qualified_boundaries_use_device_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path, bundle, proposal_path, proposal = _fixture(tmp_path)
    policy_path = (
        Path(__file__).resolve().parents[1]
        / "profiles/discipline/cx320_bounded_active_hybrid_tight_v1.json"
    )
    bundle["policy"] = {
        **_binding(policy_path),
        "policy_sha256": sha256(policy_path.read_bytes()).hexdigest(),
    }
    monkeypatch.setattr(rehearsal, "validate_bundle", lambda path: bundle)
    monkeypatch.setattr(rehearsal, "validate_proposal", lambda path: proposal)

    result = rehearsal._exercise_qualified_device_time_boundaries(
        output_dir=tmp_path / "qualified_time",
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
    )

    assert result == {
        "time_domain": "rp2040_timer0",
        "capture_session": 1,
        "correction_admission_close_elapsed_s": 41_400,
        "qualified_endpoint_elapsed_s": 43_200,
        "admission_open_one_second_before": True,
        "admission_closed_at_exact_boundary": True,
        "forward_host_utc_step_did_not_close_early": True,
        "backward_host_utc_step_did_not_delay_endpoint": True,
        "physical_actions_performed": 0,
    }
