"""Deterministic shared wait tests; no serial device or physical operations."""
from __future__ import annotations

import pytest

from host.otis_tools import adaptive_hybrid_health as health_module
from host.otis_tools import adaptive_hybrid_transport as transport
from host.otis_tools.active_status_live_state import LiveHealthState
from tests.runtime_fixtures import construct_simulated_supervisor


class Clock:
    def __init__(self):
        self.ns = 1_000_000_000
        self.after_sleep = lambda: None
    def advance(self, seconds):
        self.ns += int(seconds * 1_000_000_000)
    def sleep(self, seconds):
        self.advance(seconds)
        self.after_sleep()


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    monkeypatch.setattr(transport.time, "monotonic_ns", lambda: value.ns)
    monkeypatch.setattr(transport.time, "monotonic", lambda: value.ns / 1e9)
    monkeypatch.setattr(transport.time, "sleep", value.sleep)
    return value


def subject(tmp_path):
    value = construct_simulated_supervisor(tmp_path)
    value.state = {
        "host_attach_query_nonce": 40, "active_snapshot_request_nonce": 40,
        "startup_census_process_nonce": 91, "lease_sequence": 1,
        "terminal": None, "terminal_static_code": None,
    }
    value._live_command_ack_required = True
    value._startup_census_admitted = lambda: True
    value._save = lambda: None
    value._programme_event = lambda *_args, **_kwargs: None
    value._event = lambda *_args, **_kwargs: None
    value._record_bench_application_before_acknowledgement = lambda *_args: {}
    return value


def snapshot(generation, phase="application_pending", request=7):
    return {
        ("adaptive_hybrid", "snapshot_generation_complete"): str(generation),
        ("adaptive_hybrid", "evidence_phase"): phase,
        ("adaptive_hybrid", "evidence_request_sequence"): str(request),
    }


def install_snapshots(value, clock, phases, *, query_seconds=1):
    commands = []
    def command(text):
        commands.append(text)
        clock.advance(query_seconds)
    value._command = command
    value._current_health = lambda **_: snapshot(
        len(commands), phases[min(len(commands), len(phases) - 1)])
    return commands


def test_every_causally_behind_response_is_examined_under_one_deadline(tmp_path, clock):
    value = subject(tmp_path)
    commands = install_snapshots(value, clock,
        ["acceptance_pending"] * 6 + ["application_pending"])
    initial = clock.ns
    proof = value._prepare_evidence_acknowledgement({"request_sequence": "7"}, 3)
    assert len(commands) == 6  # The former fifth response/discard boundary is crossed.
    assert proof["pre_submit_snapshot_generation"] == 6
    assert proof["causal_observation_owner_nonce"] == 91
    assert proof["causal_observation_deadline_monotonic_ns"] == initial + 30_000_000_000


def test_unrelated_fresh_snapshots_cannot_reset_the_operation_deadline(tmp_path, clock):
    value = subject(tmp_path)
    commands = install_snapshots(value, clock, ["acceptance_pending"], query_seconds=6)
    initial = clock.ns
    with pytest.raises(TimeoutError, match="causal observation"):
        value._prepare_evidence_acknowledgement({"request_sequence": "7"}, 3)
    assert clock.ns == initial + 30_000_000_000
    assert len(commands) == 5
    assert value.state.get("inflight_evidence_acknowledgement") is None


def acknowledgement(clock):
    return {
        "phase": 3, "request_sequence": 7,
        "pre_submit_snapshot_generation": 1,
        "pre_submit_evidence_phase": "application_pending",
        "host_write_confirmed": True,
        "causal_observation_owner_nonce": 91,
        "causal_observation_deadline_monotonic_ns": clock.ns + 5_000_000_000,
    }


def test_pending_confirmation_across_outer_passes_keeps_same_deadline_and_identity(tmp_path, clock):
    value = subject(tmp_path)
    commands = install_snapshots(value, clock, ["application_pending"], query_seconds=2)
    # Keep the observed generation strictly beyond the retained source frontier.
    value._current_health = lambda **_: snapshot(2 + len(commands))
    ack = acknowledgement(clock)
    deadline = ack["causal_observation_deadline_monotonic_ns"]
    assert value._confirm_evidence_acknowledgement(ack) is False
    clock.advance(3)
    with pytest.raises(TimeoutError):
        value._confirm_evidence_acknowledgement(ack)
    assert len(commands) == 1
    assert ack["causal_observation_deadline_monotonic_ns"] == deadline
    assert ack["host_write_confirmed"] is True
    assert (ack["request_sequence"], ack["phase"]) == (7, 3)


def test_prior_owner_deadline_is_not_compared_or_refreshed(tmp_path, clock):
    value = subject(tmp_path)
    ack = acknowledgement(clock)
    ack["causal_observation_owner_nonce"] = 90
    ack["causal_observation_deadline_monotonic_ns"] = 10**30
    with pytest.raises(ValueError, match="unknown supervisor process"):
        value._confirm_evidence_acknowledgement(ack)
    assert ack["causal_observation_deadline_monotonic_ns"] == 10**30


@pytest.mark.parametrize("owned", [True, False])
def test_snapshot_wait_renews_only_owned_lease_after_exact_command_ack(tmp_path, clock, monkeypatch, owned):
    value = subject(tmp_path)
    start = clock.ns
    value._last_lease_monotonic_ns = start if owned else None
    sent = 0
    pending_at = None
    commands = []
    def submit(_path, command):
        nonlocal pending_at
        assert pending_at is None, "a normal command was inserted before its predecessor ACK"
        commands.append(command)
        pending_at = clock.ns + 40_000_000
    def capture():
        nonlocal sent, pending_at
        if pending_at is not None and clock.ns >= pending_at:
            sent += 1
            pending_at = None
        return {"commands_sent": sent}
    value._check_capture_transport_state = capture
    monkeypatch.setattr(transport, "send_timestamped_command_to_fifo", submit)
    def health(*_args, **_kwargs):
        complete = clock.ns >= start + 6_000_000_000
        return LiveHealthState("complete" if complete else "in_progress",
            snapshot(2) if complete else {}, 2,
            clock.ns if complete else start, "fixture")
    monkeypatch.setattr(health_module, "read_live_health_state", health)
    assert value._fresh_active_snapshot_after(1) == snapshot(2)
    assert commands == ["ACTIVE SNAPSHOT 41"] + (["ACTIVE LEASE 2"] if owned else [])
    assert sent == len(commands)
    assert value._normal_command_ack_pending is False


def test_normal_command_wait_obeys_shorter_enclosing_budget_and_keeps_unresolved_guard(tmp_path, clock, monkeypatch):
    value = subject(tmp_path)
    commands = []
    monkeypatch.setattr(transport, "send_timestamped_command_to_fifo",
                        lambda _path, command: commands.append(command))
    value._check_capture_transport_state = lambda: {"commands_sent": 0}
    start = clock.ns
    with pytest.raises(TimeoutError), value._causal_observation(.2):
        value._command("ACTIVE?")
    assert clock.ns == start + 200_000_000
    assert value._normal_command_ack_pending is True
    with pytest.raises(ValueError, match="unresolved"):
        value._renew_lease()
    assert value.state["lease_sequence"] == 1
    assert commands == ["ACTIVE?"]


def test_evidence_command_inherits_its_retained_phase_budget(tmp_path, clock, monkeypatch):
    value = subject(tmp_path)
    ack = acknowledgement(clock)
    ack["host_write_confirmed"] = False
    ack["causal_observation_deadline_monotonic_ns"] = clock.ns + 120_000_000
    value.state["inflight_evidence_acknowledgement"] = ack
    commands = []
    monkeypatch.setattr(transport, "send_timestamped_command_to_fifo",
                        lambda _path, command: commands.append(command))
    value._check_capture_transport_state = lambda: {"commands_sent": 0}
    with pytest.raises(TimeoutError):
        value._command("ACTIVE EVIDENCE 7 3")
    assert clock.ns == ack["causal_observation_deadline_monotonic_ns"]
    assert commands == ["ACTIVE EVIDENCE 7 3"]
    assert value.state["inflight_evidence_acknowledgement"] is ack
    assert ack["host_write_confirmed"] is False


def test_new_incomplete_generations_do_not_extend_hidden_health_wait(tmp_path, clock, monkeypatch):
    value = subject(tmp_path)
    generations = []
    def read(*_args, **_kwargs):
        generations.append(len(generations) + 1)
        return LiveHealthState("in_progress", {}, generations[-1], clock.ns, "")
    monkeypatch.setattr(health_module, "read_live_health_state", read)
    initial = clock.ns
    with pytest.raises(TimeoutError, match="causal observation"):
        value._current_health()
    assert clock.ns == initial + 30_000_000_000
    assert len(generations) > 100


@pytest.mark.parametrize("operation", ["health", "snapshot", "normal_command"])
def test_periodic_wait_uses_current_pending_phase_budget(tmp_path, clock, monkeypatch, operation):
    value = subject(tmp_path)
    ack = acknowledgement(clock)
    ack["causal_observation_deadline_monotonic_ns"] = clock.ns + 100_000_000
    value.state["inflight_evidence_acknowledgement"] = ack
    value._check_capture_transport_state = lambda: {"commands_sent": 0}
    monkeypatch.setattr(transport, "send_timestamped_command_to_fifo", lambda *_: None)
    monkeypatch.setattr(health_module, "read_live_health_state", lambda *_args, **_kwargs:
        LiveHealthState("in_progress", {}, 2, clock.ns, "pending"))
    with pytest.raises(TimeoutError):
        if operation == "health":
            value._current_health()
        elif operation == "snapshot":
            value._fresh_active_snapshot_after(1)
        else:
            value._command("CONFIG?")
    assert clock.ns == ack["causal_observation_deadline_monotonic_ns"]
    assert value.state["inflight_evidence_acknowledgement"] is ack
    assert ack["host_write_confirmed"] is True


def test_cleared_phase_does_not_constrain_successor_budget(tmp_path, clock):
    value = subject(tmp_path)
    ack = acknowledgement(clock)
    value.state["inflight_evidence_acknowledgement"] = ack
    assert value._pending_ack_deadline() == ack["causal_observation_deadline_monotonic_ns"]
    clock.advance(6)
    value.state["inflight_evidence_acknowledgement"] = None
    assert value._pending_ack_deadline() is None
    install_snapshots(value, clock, ["application_pending"])
    start = clock.ns
    result = value._prepare_evidence_acknowledgement({"request_sequence": "7"}, 3)
    assert result["causal_observation_deadline_monotonic_ns"] == start + 30_000_000_000


def test_expired_phase_cannot_advance_durable_lease_sequence(tmp_path, clock):
    value = subject(tmp_path)
    ack = acknowledgement(clock)
    value.state["inflight_evidence_acknowledgement"] = ack
    clock.advance(5)
    with pytest.raises(TimeoutError):
        value._renew_lease()
    assert value.state["lease_sequence"] == 1


def test_default_health_observation_uses_current_query_not_attachment_nonce(tmp_path, clock, monkeypatch):
    value = subject(tmp_path)
    value.state["active_snapshot_request_nonce"] = 45
    observed = []
    def read_health(_self, *, required_query_nonce=None):
        observed.append(required_query_nonce)
        return {}
    monkeypatch.setattr(health_module.AdaptiveHybridSupervisorBase, "_current_health", read_health)
    value._current_health()
    value._current_health(required_query_nonce=46)
    assert observed == [45, 46]
