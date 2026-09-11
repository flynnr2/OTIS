"""Runner discrepancy reaches the existing supervisor authority boundary."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from host.otis_tools import adaptive_hybrid_run as runner
from host.otis_tools.adaptive_hybrid_supervisor import AdaptiveHybridSupervisor
from host.otis_tools.adaptive_hybrid_contract import HOST_REVIEW_HOLD, ORCHESTRATION_FAILURE


class CaptureOwner:
    pid = 123
    closed_by_operator = False

    def poll(self):
        return 0 if self.closed_by_operator else None

    def terminate(self):
        raise AssertionError("a verifier discrepancy cannot terminate capture")

    kill = terminate


def _supervisor(root):
    supervisor = object.__new__(AdaptiveHybridSupervisor)
    supervisor.run_dir = root
    supervisor.runtime_context = SimpleNamespace(bundle_sha256="b" * 64, bench_attempt=None)
    supervisor.state = {"host_verification_hold": None, "terminal": None,
                        "arm_pending": False, "arm_sent_at_utc": None,
                        "inflight_evidence_acknowledgement": {
                            "record_sequence": 4, "request_sequence": 1,
                            "phase": 3, "host_write_confirmed": False,
                            "pre_submit_snapshot_generation": 20,
                            "pre_submit_evidence_phase": "application_pending",
                        }}
    supervisor.state.update(
        initial_session_id=1,
        startup_census_process_nonce=17,
        startup_census_authority_admitted=True,
        startup_census={
            "contract": "adaptive_hybrid_startup_census_v1",
            "authority_admitted": True, "process_nonce": 17, "session_id": 1,
        },
    )
    supervisor.state_path = root / runner.SUPERVISOR_STATE
    supervisor._programme_event = lambda *args, **kwargs: None
    supervisor._identity_ready = lambda health: pytest.fail(
        "authority progressed beyond the retained orchestration hold"
    )
    return supervisor


@pytest.mark.parametrize("mutation", ["none", "partial", "wrong_bundle", "wrong_run", "old_schema", "fallback"])
def test_runner_hold_reaches_first_supervisor_authority_consumer(tmp_path, monkeypatch, mutation):
    supervisor = _supervisor(tmp_path)
    owner = CaptureOwner()
    activation = {"activation_sha256": "a" * 64,
                  "bundle": {"bundle_sha256": "b" * 64}}
    if mutation == "fallback":
        original = runner._atomic_new_json

        def fail_primary(path, value):
            if path == tmp_path / HOST_REVIEW_HOLD:
                raise OSError("injected primary marker failure")
            return original(path, value)

        monkeypatch.setattr(runner, "_atomic_new_json", fail_primary)

    def independent_supervisor_cycle(_seconds):
        assert owner.poll() is None
        marker = tmp_path / HOST_REVIEW_HOLD
        if mutation == "partial":
            marker.write_text('{"schema_version":')
        elif mutation in {"wrong_bundle", "wrong_run", "old_schema"}:
            value = json.loads(marker.read_text())
            if mutation == "wrong_bundle":
                value["bundle_sha256"] = "c" * 64
            elif mutation == "wrong_run":
                value["run_directory"] = "/different/run"
            else:
                value["schema_version"] = 0
            marker.write_text(json.dumps(value))
        assert supervisor._consume_orchestration_review_hold()
        supervisor._maybe_start_or_arm({})
        with pytest.raises(ValueError, match="hold inhibits"):
            supervisor._command("ACTIVE ARM 1 2 9999")
        # Census has already established this owner's authority. The hold
        # keeps the existing lease/pending-ACK policy; those commands still
        # require their ordinary transport and exact phase checks downstream.
        supervisor._assert_command_admitted("ACTIVE LEASE 2")
        supervisor._assert_command_admitted("ACTIVE EVIDENCE 1 3")
        retained = json.loads(supervisor.state_path.read_text())
        assert retained["host_verification_hold"]["new_authority"] is False
        assert retained["terminal"] is None
        assert owner.poll() is None
        # Only simulated operator closure allows the real runner wait to end.
        owner.closed_by_operator = True

    monkeypatch.setattr(runner.time, "sleep", independent_supervisor_cycle)
    result = runner._retain_live_capture_for_host_review(
        run_dir=tmp_path, activation=activation, error=ValueError("runner discrepancy"),
        capture=owner, supervisor=None,
    )
    assert result["capture_alive_at_entry"]
    assert result["authority_hold_marker_published"]
    # Every malformed/foreign replacement still inhibits authority, but its
    # receipt cannot acknowledge the different bytes originally published.
    assert result["supervisor_hold_confirmed"] is (mutation in {"none", "fallback"})
    assert (tmp_path / (ORCHESTRATION_FAILURE if mutation == "fallback" else HOST_REVIEW_HOLD)).exists()


def test_failed_primary_and_fallback_publication_does_not_claim_propagation(tmp_path, monkeypatch, capsys):
    owner = CaptureOwner()
    monkeypatch.setattr(runner, "_atomic_new_json", lambda *args: (_ for _ in ()).throw(OSError("disk unavailable")))
    monkeypatch.setattr(runner.time, "sleep", lambda _: setattr(owner, "closed_by_operator", True))
    result = runner._retain_live_capture_for_host_review(
        run_dir=tmp_path,
        activation={"activation_sha256": "a" * 64, "bundle": {"bundle_sha256": "b" * 64}},
        error=ValueError("runner discrepancy"), capture=owner, supervisor=None,
    )
    assert not result["authority_hold_marker_published"]
    assert not result["supervisor_hold_confirmed"]
    assert "authority-hold propagation is unconfirmed" in capsys.readouterr().err


def test_consumed_hold_remains_latched_if_marker_is_removed(tmp_path):
    supervisor = _supervisor(tmp_path)
    marker = tmp_path / HOST_REVIEW_HOLD
    marker.parent.mkdir()
    marker.write_text("{}")
    assert supervisor._consume_orchestration_review_hold()
    marker.unlink()
    assert not supervisor._consume_orchestration_review_hold()
    supervisor._maybe_start_or_arm({})
    assert supervisor.state["host_verification_hold"] is not None


def test_published_marker_without_supervisor_receipt_is_unconfirmed(tmp_path, monkeypatch):
    owner = CaptureOwner()
    monkeypatch.setattr(runner.time, "sleep", lambda _: setattr(owner, "closed_by_operator", True))
    result = runner._retain_live_capture_for_host_review(
        run_dir=tmp_path,
        activation={"activation_sha256": "a" * 64, "bundle": {"bundle_sha256": "b" * 64}},
        error=ValueError("runner discrepancy"), capture=owner, supervisor=None,
    )
    assert result["authority_hold_marker_published"]
    assert not result["supervisor_hold_confirmed"]
