from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools.active_status_live_state import read_live_health_state
from host.otis_tools.adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    INHIBITED_ZERO_WRITE,
)
from host.otis_tools.adaptive_hybrid_supervisor import AdaptiveHybridSupervisor
from host.otis_tools.capture_device import ActiveStatusLivePublisher

FIXTURE = (
    Path(__file__).parent / "fixtures" / "startup_census_539ff6a"
    / "health_records.csv"
)
ACTIVE_COMPONENT = "adaptive_hybrid"
FIRST_ACTIVE_END = 411
PPS_AND_SECOND_ACTIVE_END = 699
QUERY_NONCE = 1_312_243_200


def _fixture_lines() -> list[tuple[int, str]]:
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    header = next(csv.reader([lines[0]]))
    sequence_index = header.index("status_seq")
    return [
        (int(next(csv.reader([line]))[sequence_index]), line)
        for line in lines[1:]
    ]


def _publish(
    publisher: ActiveStatusLivePublisher,
    records: list[tuple[int, str]],
    *,
    through_sequence: int,
    after_sequence: int = 0,
) -> None:
    for sequence, line in records:
        if after_sequence < sequence <= through_sequence:
            publisher.process_line(line, transport_generation=1)


def _health(publisher: ActiveStatusLivePublisher) -> dict[tuple[str, str], str]:
    selection = read_live_health_state(
        publisher.path, required_query_nonce=QUERY_NONCE
    )
    assert selection.state == "complete", selection.diagnostic
    return selection.health


def _first_and_second_health(
    tmp_path: Path,
) -> tuple[
    dict[tuple[str, str], str],
    dict[tuple[str, str], str],
]:
    records = _fixture_lines()
    publisher = ActiveStatusLivePublisher(tmp_path)
    _publish(publisher, records, through_sequence=FIRST_ACTIVE_END)
    first = _health(publisher)
    _publish(
        publisher,
        records,
        through_sequence=PPS_AND_SECOND_ACTIVE_END,
        after_sequence=FIRST_ACTIVE_END,
    )
    return first, _health(publisher)


def _supervisor(
    tmp_path: Path,
    health: dict[tuple[str, str], str],
    *,
    zero_write: bool = True,
) -> AdaptiveHybridSupervisor:
    supervisor = object.__new__(AdaptiveHybridSupervisor)
    supervisor.run_dir = tmp_path
    supervisor.programme = ADAPTIVE_HYBRID_PROGRAMME
    supervisor.runtime_context = SimpleNamespace(
        bench_attempt=(
            SimpleNamespace(purpose=INHIBITED_ZERO_WRITE)
            if zero_write
            else None
        )
    )
    supervisor.spec = SimpleNamespace(
        campaign="adaptive_hybrid_regulation",
        run_identity=health[(ACTIVE_COMPONENT, "run_identity")],
        profile=health[(ACTIVE_COMPONENT, "image_identity")],
        start_code=ADAPTIVE_HYBRID_PROGRAMME.setup_code,
        correction_limit=0,
        cumulative_limit=0,
    )
    supervisor.identities = {
        key: health[(ACTIVE_COMPONENT, key)]
        for key in (
            "estimator_sha256",
            "model_sha256",
            "active_policy_sha256",
            "response_policy_sha256",
            "numerical_policy_sha256",
        )
    }
    supervisor.expected_build_identity = health[(ACTIVE_COMPONENT, "build_identity")]
    supervisor.reference_acceptance_policy_sha256 = health[
        (ACTIVE_COMPONENT, "reference_acceptance_policy_sha256")
    ]
    supervisor._retained_supervisor_state_at_start = False
    supervisor._explicit_abort_submission = False
    supervisor.state = {
        "manual_start_sent": False,
        "arm_pending": False,
        "authorization_sequence": 0,
        "lease_sequence": 0,
        "setup_confirmed_utc": None,
        "setup_confirmation": None,
        "setup_authority_path": None,
        "setup_requested_utc": None,
        "terminal": None,
        "terminal_static_code": None,
        "inflight_evidence_acknowledgement": None,
        "acknowledged_record_sequences": [],
        "observed_manual_record_sequences": [],
        "initial_session_id": None,
        "host_verification_hold": None,
        "host_attach_query_nonce": QUERY_NONCE - 1,
        "active_snapshot_request_nonce": QUERY_NONCE - 1,
        "startup_census": None,
        "startup_census_history": [],
        "startup_census_authority_admitted": False,
        "startup_census_process_nonce": 539,
        "qualification_started_utc": None,
        "qualified_origin_estimate_id": None,
        "qualified_origin_session_id": None,
        "qualified_acceptance_epoch_origin": None,
        "qualified_acceptance_ordinal_origin": None,
        "qualified_authoritative_capture_baseline": None,
    }
    supervisor._save = lambda: None
    supervisor._programme_event = lambda *_args, **_kwargs: None
    supervisor._consume_orchestration_review_hold = lambda: False
    return supervisor


def test_startup_census_replays_first_active_before_pps_and_qualifies_later(
    tmp_path: Path,
) -> None:
    records = _fixture_lines()
    publisher = ActiveStatusLivePublisher(tmp_path)
    _publish(publisher, records, through_sequence=FIRST_ACTIVE_END)
    first = _health(publisher)

    # Generation 1 was the first complete ACTIVE view in the captured stream.
    # It is sufficient to identify a pristine instrument, even though the
    # later PPS-gate publication has not arrived.
    assert ("pps_gate", "reference_acceptance_policy_sha256") not in first
    supervisor = _supervisor(tmp_path, first)
    classification, admitted, diagnostics = supervisor._classify_startup_snapshot(
        first
    )
    assert (classification, admitted, diagnostics) == ("fresh_disarmed", True, [])

    _publish(
        publisher,
        records,
        through_sequence=PPS_AND_SECOND_ACTIVE_END,
        after_sequence=FIRST_ACTIVE_END,
    )
    second = _health(publisher)
    assert second[("adaptive_hybrid", "snapshot_generation_complete")] == "2"
    assert second[("pps_gate", "reference_acceptance_state")] == "tracking"
    assert second[("pps_gate", "fifo_continuity")] == "continuous"

    # The actual census starts against an empty live reader. Its solicited
    # ACTIVE query publishes generation 1; no PPS record is available yet.
    census_dir = tmp_path / "census"
    census_publisher = ActiveStatusLivePublisher(census_dir)
    census_supervisor = _supervisor(census_dir, first)
    published_first = False

    def command(command_text: str) -> None:
        nonlocal published_first
        assert command_text == f"ACTIVE SNAPSHOT {QUERY_NONCE}"
        assert not published_first
        published_first = True
        _publish(
            census_publisher,
            records,
            through_sequence=FIRST_ACTIVE_END,
        )

    census_supervisor._command = command
    census_health = census_supervisor._establish_startup_census()
    assert published_first is True
    assert ("pps_gate", "reference_acceptance_policy_sha256") not in census_health
    assert census_supervisor.state["startup_census_authority_admitted"] is True
    assert census_supervisor.state["startup_census"]["classification"] == "fresh_disarmed"
    with pytest.raises(ValueError, match="already established"):
        census_supervisor._establish_startup_census()

    # Census admission is observational. Missing/acquiring PPS evidence and a
    # firmware REFERENCE_HOLD all stop the actual setup/ARM consumer before it
    # can evaluate prewrite readiness or submit an ACTIVE command.
    census_supervisor.runtime_context = SimpleNamespace(bench_attempt=None)
    census_supervisor._prewrite_readiness = (
        lambda _health: pytest.fail("PPS-gated state reached prewrite")
    )
    census_supervisor._command = (
        lambda _command: pytest.fail("PPS-gated state submitted a command")
    )
    census_supervisor._maybe_start_or_arm(census_health)
    acquiring = dict(second)
    acquiring[("pps_gate", "reference_acceptance_state")] = "acquiring"
    census_supervisor._maybe_start_or_arm(acquiring)
    active_hold = dict(second)
    active_hold[(ACTIVE_COMPONENT, "state")] = "REFERENCE_HOLD"
    census_supervisor._maybe_start_or_arm(active_hold)

    # PPS arrives after census. The first qualification consumer can now
    # establish the zero-write aperture origin without adding setup authority.
    census_supervisor.runtime_context = SimpleNamespace(
        bench_attempt=SimpleNamespace(purpose=INHIBITED_ZERO_WRITE)
    )
    _publish(
        census_publisher,
        records,
        through_sequence=PPS_AND_SECOND_ACTIVE_END,
        after_sequence=FIRST_ACTIVE_END,
    )
    census_second = _health(census_publisher)
    census_supervisor._maybe_qualify(census_second)
    assert (
        census_supervisor.state["qualified_origin_estimate_id"]
        == "bench_attempt:no_setup_accepted_D14_D8_aperture_origin"
    )
    assert census_supervisor.state["qualified_origin_session_id"] == 1


def test_capture_replay_rejects_wrong_active_identity_and_session(
    tmp_path: Path,
) -> None:
    publisher = ActiveStatusLivePublisher(tmp_path)
    _publish(publisher, _fixture_lines(), through_sequence=FIRST_ACTIVE_END)
    health = _health(publisher)

    supervisor = _supervisor(tmp_path, health)
    wrong_build = dict(health)
    wrong_build[(ACTIVE_COMPONENT, "build_identity")] = "source:" + "0" * 64
    with pytest.raises(ValueError, match="build_identity mismatch"):
        supervisor._classify_startup_snapshot(wrong_build)

    supervisor = _supervisor(tmp_path, health)
    assert supervisor._identity_ready(health) is True
    wrong_session = dict(health)
    wrong_session[(ACTIVE_COMPONENT, "session_id")] = "2"
    with pytest.raises(ValueError, match="session changed"):
        supervisor._classify_startup_snapshot(wrong_session)


def test_capture_replay_keeps_pps_qualification_separate_from_active_identity(
    tmp_path: Path,
) -> None:
    first, second = _first_and_second_health(tmp_path)

    wrong_active_policy = dict(second)
    wrong_active_policy[
        (ACTIVE_COMPONENT, "reference_acceptance_policy_sha256")
    ] = "0" * 64
    with pytest.raises(ValueError, match="reference acceptance policy"):
        _supervisor(tmp_path / "wrong-active-policy", first)._identity_ready(
            wrong_active_policy
        )

    wrong_pps_policy = dict(second)
    wrong_pps_policy[
        ("pps_gate", "reference_acceptance_policy_sha256")
    ] = "0" * 64
    pps_policy_supervisor = _supervisor(tmp_path / "wrong-pps-policy", first)
    pps_policy_supervisor._maybe_qualify(wrong_pps_policy)
    assert pps_policy_supervisor.state["qualification_started_utc"] is None

    # The independently published ACTIVE and PPS ordinals may differ while
    # their session, policy, and individual health predicates remain sound.
    ordinal_skew = dict(second)
    ordinal_skew[("pps_gate", "accepted_boundary_ordinal")] = "2"
    ordinal_supervisor = _supervisor(tmp_path / "ordinal-skew", first)
    ordinal_supervisor._maybe_qualify(ordinal_skew)
    assert ordinal_supervisor.state["qualified_acceptance_ordinal_origin"] == 2
    ordinal_progress = dict(ordinal_skew)
    ordinal_progress[("pps_gate", "accepted_boundary_ordinal")] = "3"
    assert ordinal_supervisor._qualified_d14_apertures(ordinal_progress) == 1

    # An epoch disagreement is not a fresh qualification coordinate. It must
    # wait for a coherent publication rather than invent an aperture origin.
    pre_origin_epoch_skew = dict(second)
    pre_origin_epoch_skew[("pps_gate", "reference_acceptance_epoch")] = "2"
    delayed_origin = _supervisor(tmp_path / "epoch-skew", first)
    delayed_origin._maybe_qualify(pre_origin_epoch_skew)
    assert delayed_origin.state["qualification_started_utc"] is None

    post_origin = _supervisor(tmp_path / "post-origin", first)
    post_origin._maybe_qualify(second)
    holds: list[tuple[str, str]] = []
    post_origin._recover_adaptive_hybrid_aperture_extension = (
        lambda **_kwargs: False
    )
    post_origin._enter_host_verification_hold = (
        lambda error, *, source="host_verifier": holds.append((str(error), source))
    )
    post_origin_epoch_skew = dict(second)
    post_origin_epoch_skew[("pps_gate", "reference_acceptance_epoch")] = "2"
    assert (
        post_origin._abort_on_authoritative_capture_discontinuity(
            post_origin_epoch_skew
        )
        is True
    )
    assert post_origin.state["terminal"] is None
    assert holds and holds[0][1] == "authoritative_capture_observer"
