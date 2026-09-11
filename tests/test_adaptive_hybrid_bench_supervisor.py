from __future__ import annotations

from copy import deepcopy
import csv
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools import adaptive_hybrid_supervisor as supervisor_module
from host.otis_tools.adaptive_hybrid_contract import (
    CAUSAL_STATE_CONTRACT_ID,
    CAUSAL_STATE_SCHEMA_VERSION,
    CONTINGENT_72_HOUR_HYBRID_CONTROL,
    INHIBITED_ZERO_WRITE,
    envelope_for_purpose,
)
from host.otis_tools.adaptive_hybrid_contract import ADAPTIVE_HYBRID_PROGRAMME
from host.otis_tools.adaptive_hybrid_transactions import (
    ACTIVE_CSV,
    AdaptiveHybridTransactionSupervisor,
)


def _causal_state(purpose: str) -> dict[str, object]:
    envelope = envelope_for_purpose(purpose)
    closed = purpose == INHIBITED_ZERO_WRITE
    return {
        "schema_version": CAUSAL_STATE_SCHEMA_VERSION,
        "contract": CAUSAL_STATE_CONTRACT_ID,
        "durable_ACT_application_count": 0,
        "firmware_correction_count": 0,
        "authority_closed": closed,
        "closure": (
            {
                "trigger": "initial_contract_state",
                "bench_attempt_purpose": purpose,
                "bench_attempt_envelope_sha256": envelope.as_dict()[
                    "envelope_sha256"
                ],
            }
            if closed
            else None
        ),
    }


def _bare_supervisor(purpose: str, run_dir: Path) -> supervisor_module.AdaptiveHybridSupervisor:
    supervisor = object.__new__(supervisor_module.AdaptiveHybridSupervisor)
    envelope = envelope_for_purpose(purpose)
    supervisor.envelope = SimpleNamespace(bench_attempt=envelope)
    supervisor.programme = ADAPTIVE_HYBRID_PROGRAMME
    supervisor.run_dir = run_dir
    supervisor.state = {
        "host_verification_hold": None,
        "bench_attempt_causal_state": _causal_state(purpose),
        "bench_attempt_arm_admission_closed": (
            purpose == INHIBITED_ZERO_WRITE
        ),
        "bench_attempt_arm_admission_closed_utc": None,
        "bench_attempt_arm_admission_endpoint": None,
        "bench_attempt_arm_submission_count": 0,
        "bench_attempt_last_arm_opportunity": None,
        "bench_attempt_arm_admissions": [],
        "response_horizon_closed_utc": None,
        "manual_start_sent": False,
        "arm_pending": False,
        "arm_sent_at_utc": None,
        "authorization_sequence": 0,
    }
    return supervisor


def _application_row() -> dict[str, str]:
    return {
        "event": "application",
        "transaction_record_sequence": "4",
        "request_sequence": "7",
        "decision_sequence": "11",
        "application_sequence": "1",
        "correction_count": "1",
    }


def _write_single_row(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _zero_write_terminal_health(
    supervisor: supervisor_module.AdaptiveHybridSupervisor,
) -> dict[tuple[str, str], str]:
    session_id = 7
    baseline = {
        key: 0
        for key in supervisor_module._authoritative_capture_counters(
            supervisor.programme
        )
    }
    supervisor.state.update(
        {
            "terminal": None,
            "terminal_static_code": None,
            "wall_origin_utc": "2026-09-09T00:00:00Z",
            "qualified_origin_session_id": session_id,
            "qualified_authoritative_capture_baseline": baseline,
            "setup_requested_utc": None,
            "setup_confirmed_utc": None,
            "setup_authorization_sequence": 0,
            "setup_authority_path": None,
            "setup_confirmation": None,
            "later_authority_released": False,
            "first_phase_checkpoint_passed": False,
            "first_phase_observation_checkpoint_exact": False,
            "phase_material_application_count": 0,
        }
    )
    active = {
        "state": "DISARMED",
        "reason": "initialized_disarmed",
        "hybrid_state": "SETUP_PENDING",
        "hybrid_reason": "setup_consumers_pending",
        "capture_lease_live": "true",
        "manual_start_confirmed": "false",
        "arm_eligible": "false",
        "fail_static": "false",
        "evidence_phase": "evidence_clear",
        "evidence_pending": "false",
        "evidence_request_sequence": "0",
        "confirmed_applied_code_known": "false",
        "confirmed_applied_code": "unavailable",
        "correction_count": "0",
        "cumulative_movement_codes": "0",
        "dac_epoch": "0",
        "phase_material_application_count": "0",
        "phase_nonzero_application_count": "0",
        "frequency_only_application_count": "0",
        "first_phase_checkpoint_passed": "false",
        "automatic_retry": "false",
        "automatic_restore": "false",
    }
    health = {
        ("adaptive_hybrid", key): value for key, value in active.items()
    }
    health.update(
        {
            ("pps_gate", key): value
            for key, value in supervisor_module._AUTHORITATIVE_CAPTURE_EXPECTED_HEALTH.items()
        }
    )
    health[("pps_gate", "snapshot_session")] = str(session_id)
    health.update(
        {("pps_gate", key): str(value) for key, value in baseline.items()}
    )
    health[("adaptive_hybrid", "session_id")] = str(session_id)
    for key in ("reference_acceptance_state", "accepted_anchor_current"):
        health[("adaptive_hybrid", key)] = health[("pps_gate", key)]
    return health


def test_zero_write_gate_cannot_reach_identity_setup_or_arm(tmp_path: Path) -> None:
    supervisor = _bare_supervisor(INHIBITED_ZERO_WRITE, tmp_path)
    supervisor._identity_ready = lambda _health: (_ for _ in ()).throw(
        AssertionError("zero-write gate evaluated a setup/ARM prerequisite")
    )

    supervisor._maybe_start_or_arm({})

    assert supervisor.state["manual_start_sent"] is False
    assert supervisor.state["authorization_sequence"] == 0
    assert supervisor.state["bench_attempt_arm_submission_count"] == 0


def test_zero_write_wall_endpoint_is_static_without_a_known_dac_code(
    tmp_path: Path,
) -> None:
    supervisor = _bare_supervisor(INHIBITED_ZERO_WRITE, tmp_path)
    health = _zero_write_terminal_health(supervisor)
    supervisor._identity_ready = lambda _health: True
    supervisor._qualified_d14_apertures = lambda _health: 6720
    supervisor._healthy_terminal_ready = lambda _health: (_ for _ in ()).throw(
        AssertionError("zero-write endpoint required a confirmed DAC code")
    )
    supervisor._save = lambda: None
    supervisor._command = lambda _command: (_ for _ in ()).throw(
        AssertionError("zero-write endpoint submitted a command")
    )
    supervisor._abort = lambda _reason: (_ for _ in ()).throw(
        AssertionError("zero-write endpoint submitted an abort")
    )
    holds: list[tuple[str, str]] = []
    supervisor._enter_host_verification_hold = (
        lambda error, *, source="host_verifier": holds.append((str(error), source))
    )
    wall_s = envelope_for_purpose(INHIBITED_ZERO_WRITE).as_dict()["timing"][
        "absolute_wall_limit_s"
    ]

    assert supervisor._maybe_finish_bench_attempt(
        health,
        supervisor_module._parse_utc_epoch("2026-09-09T00:00:00Z") + wall_s,
    )

    terminal = supervisor.state["terminal"]
    assert terminal["result"] == "healthy_stop"
    assert terminal["reason"] == "inhibited_zero_write_complete"
    assert terminal["preliminary_decision"] == "pending_offline_scientific_analysis"
    assert terminal["last_confirmed_code"] is None
    assert supervisor.state["terminal_static_code"] is None
    assert holds == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confirmed_applied_code_known", "true"),
        ("confirmed_applied_code", "0xA800"),
        ("manual_start_confirmed", "true"),
        ("evidence_pending", "true"),
        ("evidence_request_sequence", "1"),
        ("correction_count", "1"),
        ("cumulative_movement_codes", "1"),
        ("dac_epoch", "1"),
        ("state", "ARMED"),
        ("hybrid_state", "FREQUENCY_ACQUIRE"),
    ],
)
def test_zero_write_wall_endpoint_rejects_nonstatic_firmware_evidence(
    tmp_path: Path, field: str, value: str
) -> None:
    supervisor = _bare_supervisor(INHIBITED_ZERO_WRITE, tmp_path)
    health = _zero_write_terminal_health(supervisor)
    health[("adaptive_hybrid", field)] = value
    supervisor._identity_ready = lambda _health: True
    supervisor._qualified_d14_apertures = lambda _health: 6720
    supervisor._save = lambda: None
    holds: list[tuple[str, str]] = []
    supervisor._enter_host_verification_hold = (
        lambda error, *, source="host_verifier": holds.append((str(error), source))
    )
    wall_s = envelope_for_purpose(INHIBITED_ZERO_WRITE).as_dict()["timing"][
        "absolute_wall_limit_s"
    ]

    supervisor._maybe_finish_bench_attempt(
        health,
        supervisor_module._parse_utc_epoch("2026-09-09T00:00:00Z") + wall_s,
    )

    assert supervisor.state["terminal"] is None
    assert holds == [
        (
            "zero-write wall endpoint lacks a clear static terminal",
            "bench_attempt_wall_endpoint_observer",
        )
    ]


@pytest.mark.parametrize("relative_path", [ACTIVE_CSV, supervisor_module.DAC_CSV])
def test_zero_write_wall_endpoint_rejects_any_control_transaction(
    tmp_path: Path, relative_path: Path
) -> None:
    supervisor = _bare_supervisor(INHIBITED_ZERO_WRITE, tmp_path)
    health = _zero_write_terminal_health(supervisor)
    _write_single_row(tmp_path / relative_path, {"event": "unexpected"})
    supervisor._identity_ready = lambda _health: True

    assert supervisor._inhibited_zero_write_terminal_ready(health) is False
    assert supervisor.state["terminal_static_code"] is None


def test_zero_write_wall_endpoint_rejects_a_setup_authority_record(
    tmp_path: Path,
) -> None:
    supervisor = _bare_supervisor(INHIBITED_ZERO_WRITE, tmp_path)
    health = _zero_write_terminal_health(supervisor)
    path = tmp_path / supervisor_module.SETUP_AUTHORITY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    supervisor._identity_ready = lambda _health: True

    assert supervisor._inhibited_zero_write_terminal_ready(health) is False


def test_one_application_setup_is_submitted_once(tmp_path: Path) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    supervisor._identity_ready = lambda _health: True
    supervisor._prewrite_readiness = lambda _health: SimpleNamespace(ready=True)
    supervisor._acquisition_authority_ready = lambda **_kwargs: True
    request = {
        "authorization_sequence": 1,
        "status_generation": 2,
        "query_nonce": 3,
        "expires_s": 40,
        "session_id": 5,
    }
    supervisor._setup_command = lambda _health: ("ACTIVE SETUP exact", request)
    supervisor._retain_setup_authority = lambda _health, _request: None
    commands: list[str] = []
    supervisor._command = commands.append
    supervisor._save = lambda: None
    supervisor._programme_event = lambda _event, **_fields: None
    health = {
        ("adaptive_hybrid", "state"): "DISARMED",
        ("adaptive_hybrid", "manual_start_confirmed"): "false",
        ("adaptive_hybrid", "session_id"): "5",
        ("pps_gate", "snapshot_session"): "5",
    }

    supervisor._maybe_start_or_arm(health)
    supervisor._maybe_start_or_arm(health)

    assert commands == ["ACTIVE SETUP exact"]
    assert supervisor.state["manual_start_sent"] is True


def test_setup_confirmation_accepts_exact_ticks_within_reported_whole_second(
) -> None:
    assert supervisor_module._tick_is_within_reported_whole_second(612071551, 612)
    assert supervisor_module._tick_is_within_reported_whole_second(612999999, 612)
    assert not supervisor_module._tick_is_within_reported_whole_second(
        613000000, 612
    )
    assert not supervisor_module._tick_is_within_reported_whole_second(
        611999999, 612
    )


def test_application_frontier_is_durable_before_phase_three_command(
    tmp_path: Path,
) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    row = _application_row()
    active_path = tmp_path / ACTIVE_CSV
    _write_single_row(active_path, row)
    supervisor.state.update(
        {
            "arm_pending": True,
            "arm_sent_at_utc": "2026-09-09T00:00:00Z",
            "inflight_evidence_acknowledgement": None,
            "acknowledged_record_sequences": [],
        }
    )
    health = {
        ("adaptive_hybrid", "snapshot_generation_complete"): "12",
        ("adaptive_hybrid", "query_nonce"): "91",
        ("adaptive_hybrid", "session_id"): "5",
        ("adaptive_hybrid", "evidence_phase"): "application_pending",
        ("adaptive_hybrid", "evidence_request_sequence"): "7",
        ("adaptive_hybrid", "correction_count"): "1",
    }
    supervisor._current_health = lambda: {
        **health,
        ("adaptive_hybrid", "snapshot_generation_complete"): "11",
    }
    supervisor._fresh_active_snapshot_after = lambda _generation: health
    supervisor._qualified_d14_apertures = lambda _health: 733
    trace: list[tuple[str, object]] = []

    def save() -> None:
        trace.append(
            (
                "save",
                deepcopy(supervisor.state.get("bench_attempt_causal_state")),
            )
        )

    def command(value: str) -> None:
        causal = supervisor.state["bench_attempt_causal_state"]
        assert causal["authority_closed"] is False
        assert causal["durable_ACT_application_count"] == 1
        assert causal["firmware_correction_count"] == 1
        trace.append(("command", value))

    supervisor._save = save
    supervisor._command = command
    supervisor._programme_event = lambda event, **_fields: trace.append(
        ("programme_event", event)
    )
    supervisor._event = lambda event, **_fields: trace.append(("event", event))
    supervisor._confirm_evidence_acknowledgement = lambda _ack: True

    acknowledged = AdaptiveHybridTransactionSupervisor._preserve_and_acknowledge(
        supervisor, row, 3
    )

    assert acknowledged is True
    frontier_event_index = trace.index(
        ("programme_event", "bench_attempt_application_frontier_persisted")
    )
    command_index = trace.index(("command", "ACTIVE EVIDENCE 7 3"))
    assert frontier_event_index < command_index
    causal = supervisor.state["bench_attempt_causal_state"]
    assert causal["closure"] is None
    assert supervisor.state["bench_attempt_arm_admission_closed"] is False
    assert supervisor.state["arm_pending"] is True

    events_before = [item for item in trace if item[0] == "programme_event"]
    supervisor._prepare_evidence_acknowledgement(row, 3)
    assert [item for item in trace if item[0] == "programme_event"] == events_before


@pytest.mark.parametrize("firmware_count", (0, 2))
def test_application_count_mismatch_withholds_phase_three_acknowledgement(
    tmp_path: Path, firmware_count: int
) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    row = _application_row()
    _write_single_row(tmp_path / ACTIVE_CSV, row)
    supervisor._qualified_d14_apertures = lambda _health: 700
    supervisor._save = lambda: None
    supervisor._programme_event = lambda _event, **_fields: None
    health = {
        ("adaptive_hybrid", "snapshot_generation_complete"): "12",
        ("adaptive_hybrid", "query_nonce"): "91",
        ("adaptive_hybrid", "correction_count"): str(firmware_count),
    }

    with pytest.raises(ValueError, match="correction counts differ"):
        supervisor._record_bench_application_before_acknowledgement(
            row, health
        )
    assert supervisor.state["bench_attempt_causal_state"]["authority_closed"] is False


def test_long_run_authority_closes_only_at_automatic_application_limit(
    tmp_path: Path,
) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    limit = supervisor.envelope.bench_attempt.limits.automatic_application_limit
    rows = []
    for sequence in range(1, limit + 1):
        rows.append(
            {
                "event": "application",
                "transaction_record_sequence": str(sequence * 4),
                "request_sequence": str(sequence),
                "decision_sequence": str(sequence),
                "application_sequence": str(sequence),
                "correction_count": str(sequence),
            }
        )
    _write_rows(tmp_path / ACTIVE_CSV, rows)
    supervisor.state["bench_attempt_causal_state"] = {
        "schema_version": CAUSAL_STATE_SCHEMA_VERSION,
        "contract": CAUSAL_STATE_CONTRACT_ID,
        "durable_ACT_application_count": limit - 1,
        "firmware_correction_count": limit - 1,
        "authority_closed": False,
        "closure": None,
    }
    supervisor.state["arm_pending"] = True
    supervisor._qualified_d14_apertures = lambda _health: 200_000
    supervisor._save = lambda: None
    events: list[str] = []
    supervisor._programme_event = lambda event, **_fields: events.append(event)
    health = {
        ("adaptive_hybrid", "snapshot_generation_complete"): "900",
        ("adaptive_hybrid", "query_nonce"): "901",
        ("adaptive_hybrid", "correction_count"): str(limit),
    }

    result = supervisor._record_bench_application_before_acknowledgement(
        rows[-1], health
    )

    causal = supervisor.state["bench_attempt_causal_state"]
    assert result["bench_attempt_authority_closed"] is True
    assert causal["durable_ACT_application_count"] == 144
    assert causal["firmware_correction_count"] == 144
    assert causal["authority_closed"] is True
    assert causal["closure"]["trigger"] == "automatic_application_limit_reached"
    assert supervisor.state["bench_attempt_arm_admission_closed"] is True
    assert supervisor.state["arm_pending"] is False
    assert events == ["bench_attempt_authority_closed"]


def test_long_run_early_hours_and_first_application_are_nonterminal(
    tmp_path: Path,
) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    supervisor.state.update(
        {
            "terminal": None,
            "wall_origin_utc": "2026-09-09T00:00:00Z",
        }
    )
    supervisor._qualified_d14_apertures = lambda _health: 7_200

    delegated = supervisor._maybe_finish_bench_attempt(
        {}, supervisor_module._parse_utc_epoch("2026-09-09T02:00:00Z")
    )

    assert delegated is False
    assert supervisor.state["terminal"] is None


def test_long_run_zero_correction_path_reaches_72_hour_qualified_endpoint(
    tmp_path: Path,
) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    supervisor.state.update(
        {
            "terminal": None,
            "terminal_static_code": ADAPTIVE_HYBRID_PROGRAMME.setup_code,
            "qualification_started_utc": "2026-09-09T01:00:00Z",
            "wall_origin_utc": "2026-09-09T00:00:00Z",
        }
    )
    supervisor._qualified_d14_apertures = lambda _health: (
        ADAPTIVE_HYBRID_PROGRAMME.qualified_d14_aperture_count
    )
    supervisor._healthy_terminal_ready = lambda _health: True
    supervisor._save = lambda: None
    health = {
        ("adaptive_hybrid", "phase_material_application_count"): "0",
        ("adaptive_hybrid", "first_phase_checkpoint_passed"): "false",
    }

    supervisor._maybe_finish(
        health, supervisor_module._parse_utc_epoch("2026-09-12T01:00:00Z")
    )

    assert supervisor.state["terminal"] == {
        "result": "healthy_stop",
        "reason": "adaptive_hybrid_qualified_complete",
        "preliminary_decision": "pending_offline_scientific_analysis",
        "last_confirmed_code": ADAPTIVE_HYBRID_PROGRAMME.setup_code,
        "utc": supervisor.state["terminal"]["utc"],
    }


def test_long_run_host_discrepancy_at_endpoint_remains_review_hold(
    tmp_path: Path,
) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    hold = {
        "source": "host_verifier",
        "review_status": "operator_review_required",
        "new_authority": False,
    }
    supervisor.state.update(
        {
            "terminal": None,
            "host_verification_hold": hold,
            "qualification_started_utc": "2026-09-09T01:00:00Z",
            "wall_origin_utc": "2026-09-09T00:00:00Z",
        }
    )
    supervisor._qualified_d14_apertures = lambda _health: (
        ADAPTIVE_HYBRID_PROGRAMME.qualified_d14_aperture_count
    )
    supervisor._healthy_terminal_ready = lambda _health: (_ for _ in ()).throw(
        AssertionError("review hold attempted to decide the terminal")
    )
    supervisor._save = lambda: None
    events: list[tuple[str, dict[str, object]]] = []
    supervisor._programme_event = lambda event, **fields: events.append(
        (event, fields)
    )

    supervisor._maybe_finish(
        {}, supervisor_module._parse_utc_epoch("2026-09-12T01:00:00Z")
    )

    assert supervisor.state["terminal"] is None
    assert hold["qualified_endpoint_review_required"] is True
    assert events[-1][0] == "host_verification_hold_qualified_endpoint_observed"
    assert events[-1][1]["capture_continues"] is True


def test_transaction_validation_error_enters_review_hold_without_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    supervisor.state["terminal"] = None
    supervisor._validate_hybrid_decisions_or_hold = lambda: True
    holds: list[tuple[Exception, str]] = []
    supervisor._enter_host_verification_hold = (
        lambda error, *, source="host_verifier": holds.append((error, source))
    )
    monkeypatch.setattr(
        supervisor_module.AdaptiveHybridSupervisorBase,
        "_process_transactions",
        lambda _self: (_ for _ in ()).throw(ValueError("causal mismatch")),
    )

    supervisor._process_transactions()

    assert len(holds) == 1
    assert str(holds[0][0]) == "causal mismatch"
    assert holds[0][1] == "transaction_evidence_validation"
    assert supervisor.state["terminal"] is None


def test_arm_admission_closes_at_exact_accepted_aperture_boundary(
    tmp_path: Path,
) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    supervisor.state.update(
        {
            "qualified_acceptance_ordinal_origin": 100,
            "qualified_acceptance_epoch_origin": 1,
            "qualified_origin_session_id": 5,

        }
    )
    supervisor._save = lambda: None
    events: list[dict[str, object]] = []
    supervisor._programme_event = lambda _event, **fields: events.append(fields)
    limits = supervisor.envelope.bench_attempt.limits
    deadline = limits.automatic_application_admission_deadline_apertures

    before = {
        ("pps_gate", "accepted_boundary_ordinal"): str(100 + deadline - 1),
        ("pps_gate", "reference_acceptance_epoch"): "1",
        ("pps_gate", "snapshot_session"): "5",
        ("pps_gate", "boundary_reference_sequence"): str(200 + deadline - 1),
    }
    endpoint = {
        ("pps_gate", "accepted_boundary_ordinal"): str(100 + deadline),
        ("pps_gate", "reference_acceptance_epoch"): "1",
        ("pps_gate", "snapshot_session"): "5",
        ("pps_gate", "boundary_reference_sequence"): str(200 + deadline),
    }

    assert supervisor._close_bench_arm_admission_if_required(before) is False
    assert supervisor._close_bench_arm_admission_if_required(endpoint) is True
    assert supervisor.state["bench_attempt_arm_admission_closed"] is True
    assert supervisor.state["bench_attempt_arm_admission_endpoint"] == deadline
    assert supervisor.state["response_horizon_closed_utc"] is not None
    assert events[-1]["progress_domain"] == "accepted_D14_D8_apertures"


def test_one_application_arm_is_durable_and_not_reused_for_same_opportunity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    supervisor.state.update(
        {
            "manual_start_sent": True,
            "setup_confirmed_utc": "2026-09-09T00:00:00Z",
            "setup_confirmation": {
                "session_id": 5,
                "applied_code": ADAPTIVE_HYBRID_PROGRAMME.setup_code,
                "dac_epoch": 1,
            },
            "initial_session_id": 5,
            "qualified_acceptance_ordinal_origin": 100,
            "qualified_acceptance_epoch_origin": 1,
            "qualified_origin_session_id": 5,

        }
    )
    supervisor._identity_ready = lambda _health: True
    supervisor._acquisition_authority_ready = lambda **_kwargs: True
    supervisor._close_bench_arm_admission_if_required = lambda _health: False
    supervisor._arm_progress_epoch_ready = lambda _preview, _progress: True
    supervisor._save = lambda: None
    supervisor._programme_event = lambda _event, **_fields: None
    commands: list[str] = []

    def command(value: str) -> None:
        assert supervisor.state["bench_attempt_arm_submission_count"] == 1
        assert supervisor.state["arm_pending"] is True
        commands.append(value)

    supervisor._command = command
    monkeypatch.setattr(
        supervisor_module,
        "_read_csv",
        lambda _path: [
                {
                    "decision_id": "natural-opportunity-1",
                    "est_input_ref": "est:fixture:1",
                    "preview_available": "true",
                "preview_eligibility": "true",
            }
        ],
    )
    health = {
        ("adaptive_hybrid", "state"): "DISARMED",
        ("adaptive_hybrid", "manual_start_confirmed"): "true",
        ("adaptive_hybrid", "hybrid_state"): "FREQUENCY_ACQUIRE",
        ("adaptive_hybrid", "first_phase_checkpoint_passed"): "false",
        ("adaptive_hybrid", "correction_count"): "0",
        ("adaptive_hybrid", "selected_interval_count"): "600",
        ("adaptive_hybrid", "arm_eligible"): "true",
        ("adaptive_hybrid", "evidence_phase"): "evidence_clear",
        ("adaptive_hybrid", "evidence_pending"): "false",
        ("adaptive_hybrid", "uptime_s"): "700",
        ("adaptive_hybrid", "session_id"): "5",
        ("adaptive_hybrid", "snapshot_generation_complete"): "12",
        ("adaptive_hybrid", "query_nonce"): "91",
            ("pps_gate", "accepted_boundary_ordinal"): "700",
            ("pps_gate", "reference_acceptance_epoch"): "1",
            ("pps_gate", "boundary_reference_sequence"): "800",
            ("pps_gate", "snapshot_session"): "5",
    }

    supervisor._maybe_start_or_arm(health)
    assert len(commands) == 1
    assert commands[0].startswith("ACTIVE ARM ")
    admission = supervisor.state["bench_attempt_arm_admissions"][0]
    assert admission["authorizing_snapshot_generation"] == 12
    assert admission["authorizing_query_nonce"] == 91
    assert admission["accepted_D14_D8_apertures"] == 600
    assert admission["natural_opportunity"] == "natural-opportunity-1"

    supervisor.state["arm_pending"] = False
    supervisor.state["arm_sent_at_utc"] = None
    supervisor._maybe_start_or_arm(health)
    assert len(commands) == 1
    assert supervisor.state["bench_attempt_arm_submission_count"] == 1


def test_contingent_arm_waits_for_first_natural_opportunity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    supervisor.state.update(
        {
            "manual_start_sent": True,
            "setup_confirmed_utc": "2026-09-09T00:00:00Z",
            "setup_confirmation": {
                "session_id": 5,
                "applied_code": ADAPTIVE_HYBRID_PROGRAMME.setup_code,
                "dac_epoch": 1,
            },
            "initial_session_id": 5,
        }
    )
    supervisor._identity_ready = lambda _health: True
    supervisor._acquisition_authority_ready = lambda **_kwargs: True
    supervisor._acquisition_authority_ready = lambda **_kwargs: True
    supervisor._close_bench_arm_admission_if_required = lambda _health: False
    supervisor._arm_progress_epoch_ready = lambda *_args: (_ for _ in ()).throw(
        AssertionError("ARM progress evaluated without a natural opportunity")
    )
    supervisor._command = lambda _command: (_ for _ in ()).throw(
        AssertionError("ARM submitted without a natural opportunity")
    )
    monkeypatch.setattr(supervisor_module, "_read_csv", lambda _path: [])
    health = {
        ("adaptive_hybrid", "state"): "DISARMED",
        ("adaptive_hybrid", "manual_start_confirmed"): "true",
        ("adaptive_hybrid", "hybrid_state"): "PHASE_QUALIFY",
        ("adaptive_hybrid", "first_phase_checkpoint_passed"): "false",
        ("adaptive_hybrid", "correction_count"): "0",
        ("adaptive_hybrid", "selected_interval_count"): "600",
    }

    supervisor._maybe_start_or_arm(health)

    assert supervisor.state["authorization_sequence"] == 0
    assert supervisor.state["bench_attempt_arm_submission_count"] == 0
    assert supervisor.state["bench_attempt_arm_admissions"] == []


def test_contingent_arm_rejects_durable_nonpreview_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    supervisor.state.update(
        {
            "manual_start_sent": True,
            "setup_confirmed_utc": "2026-09-09T00:00:00Z",
            "setup_confirmation": {
                "session_id": 5,
                "applied_code": ADAPTIVE_HYBRID_PROGRAMME.setup_code,
                "dac_epoch": 1,
            },
            "initial_session_id": 5,
        }
    )
    supervisor._identity_ready = lambda _health: True
    supervisor._close_bench_arm_admission_if_required = lambda _health: False
    supervisor._arm_progress_epoch_ready = lambda *_args: (_ for _ in ()).throw(
        AssertionError("ARM progress evaluated for a non-preview decision")
    )
    supervisor._command = lambda _command: (_ for _ in ()).throw(
        AssertionError("ARM submitted for a non-preview decision")
    )
    monkeypatch.setattr(
        supervisor_module,
        "_read_csv",
        lambda _path: [
            {
                "decision_id": "ctl:frequency_regulation:000000",
                "control_seq": "0",
                "preview_available": "false",
                "preview_eligibility": "false",
            }
        ],
    )
    health = {
        ("adaptive_hybrid", "state"): "DISARMED",
        ("adaptive_hybrid", "manual_start_confirmed"): "true",
        ("adaptive_hybrid", "hybrid_state"): "PHASE_QUALIFY",
        ("adaptive_hybrid", "first_phase_checkpoint_passed"): "false",
        ("adaptive_hybrid", "correction_count"): "0",
        ("adaptive_hybrid", "selected_interval_count"): "600",
    }

    supervisor._maybe_start_or_arm(health)

    assert supervisor.state["authorization_sequence"] == 0
    assert supervisor.state["arm_pending"] is False
    assert supervisor.state["bench_attempt_arm_submission_count"] == 0


def test_contingent_arm_coordinate_failure_does_not_publish_ghost_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    supervisor.state.update(
        {
            "manual_start_sent": True,
            "setup_confirmed_utc": "2026-09-09T00:00:00Z",
            "setup_confirmation": {
                "session_id": 5,
                "applied_code": ADAPTIVE_HYBRID_PROGRAMME.setup_code,
                "dac_epoch": 1,
            },
            "initial_session_id": 5,
        }
    )
    supervisor._identity_ready = lambda _health: True
    supervisor._acquisition_authority_ready = lambda **_kwargs: True
    supervisor._close_bench_arm_admission_if_required = lambda _health: False
    supervisor._arm_progress_epoch_ready = lambda _preview, _progress: True
    supervisor._qualified_d14_apertures = lambda _health: None
    supervisor._command = lambda _command: (_ for _ in ()).throw(
        AssertionError("ARM submitted without an aperture coordinate")
    )
    monkeypatch.setattr(
        supervisor_module,
        "_read_csv",
        lambda _path: [
                {
                    "decision_id": "natural-opportunity-1",
                    "est_input_ref": "est:fixture:1",
                    "preview_available": "true",
                "preview_eligibility": "true",
            }
        ],
    )
    health = {
        ("adaptive_hybrid", "state"): "DISARMED",
        ("adaptive_hybrid", "manual_start_confirmed"): "true",
        ("adaptive_hybrid", "hybrid_state"): "FREQUENCY_ACQUIRE",
        ("adaptive_hybrid", "first_phase_checkpoint_passed"): "false",
        ("adaptive_hybrid", "correction_count"): "0",
        ("adaptive_hybrid", "selected_interval_count"): "600",
        ("adaptive_hybrid", "arm_eligible"): "true",
        ("adaptive_hybrid", "evidence_phase"): "evidence_clear",
        ("adaptive_hybrid", "evidence_pending"): "false",
        ("adaptive_hybrid", "uptime_s"): "700",
        ("adaptive_hybrid", "session_id"): "5",
        ("pps_gate", "snapshot_session"): "5",
    }

    with pytest.raises(ValueError, match="lacks an accepted-aperture coordinate"):
        supervisor._maybe_start_or_arm(health)

    assert supervisor.state["authorization_sequence"] == 0
    assert supervisor.state["arm_pending"] is False
    assert supervisor.state["arm_sent_at_utc"] is None
    assert supervisor.state["bench_attempt_arm_submission_count"] == 0
    assert supervisor.state["bench_attempt_arm_admissions"] == []


def test_qualification_selector_uses_frozen_policy_estimator_identity(
    tmp_path: Path,
) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    supervisor.natural_policy = SimpleNamespace(
        frequency_estimator_id="OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1"
    )
    row = {
        "estimator_version": "OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1",
        "observation_validity": "valid",
        "reference_validity": "valid",
        "reference_continuity": "true",
        "count_validity": "valid",
        "count_continuity": "true",
        "diagnostic_health": "healthy",
        "preview_eligibility": "true",
        "source_dac_ref": "live:DAC:1",
        "accepted_sample_count": "600",
        "source_accepted_spans_ref": "live:APS:1:1:0:600",
    }

    assert supervisor._fresh_authoritative_selected_estimate(
        [row], dac_epoch=1
    ) is row


@pytest.mark.parametrize("session,epoch,exact", [(5, 1, True), (5, 2, False), (6, 1, False)])
def test_metadata_requalification_is_epoch_bound_and_accepts_ordinal_wrap(
    tmp_path: Path, session: int, epoch: int, exact: bool,
) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    supervisor._save = lambda: None
    supervisor._programme_event = lambda *args, **kwargs: None
    values = {
        "session_id": "5", "acceptance_epoch": "1",
        "confirmed_applied_code_known": "true", "confirmed_applied_code": "0xA84D",
        "dac_epoch": "1", "correction_count": "0", "cumulative_movement_codes": "0",
        "gnss_metadata_hold_entry_sequence": "10", "gnss_metadata_hold_transaction_pending": "false",
    }
    health = {("adaptive_hybrid", key): value for key, value in values.items()}
    supervisor._update_gnss_metadata_hold(health, True)
    for key, value in {
        "session_id": str(session), "acceptance_epoch": str(epoch),
        "state": "DISARMED", "gnss_metadata_requalification_sequence": "11",
        "gnss_qualified_accepted_ordinal": str((1 << 32) - 1), "accepted_boundary_ordinal": "0",
    }.items():
        health[("adaptive_hybrid", key)] = value
    if exact:
        supervisor._update_gnss_metadata_hold(health, False)
        assert supervisor.state["gnss_metadata_hold"] is None
    else:
        with pytest.raises(ValueError, match="fresh causal requalification"):
            supervisor._update_gnss_metadata_hold(health, False)
        assert supervisor.state["gnss_metadata_hold"] is not None


def test_qualified_apertures_allow_zero_wrap_but_never_add_epochs(tmp_path: Path) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    supervisor.state.update(qualified_origin_session_id=5, qualified_acceptance_epoch_origin=1,
                            qualified_acceptance_ordinal_origin=(1 << 32) - 600)
    health = {("pps_gate", "snapshot_session"): "5", ("pps_gate", "reference_acceptance_epoch"): "1",
              ("pps_gate", "accepted_boundary_ordinal"): "0"}
    assert supervisor._qualified_d14_apertures(health) == 600
    health[("pps_gate", "reference_acceptance_epoch")] = "2"
    with pytest.raises(ValueError, match="epoch changed"):
        supervisor._qualified_d14_apertures(health)


def test_retained_arm_admission_rejects_restart_tampering(tmp_path: Path) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    limits = supervisor.envelope.bench_attempt.limits
    deadline = limits.automatic_application_admission_deadline_apertures
    supervisor.state.update(
        {
            "authorization_sequence": 2,
            "bench_attempt_arm_submission_count": 1,
            "bench_attempt_last_arm_opportunity": "natural-opportunity-1",
            "bench_attempt_arm_admissions": [
                {
                    "authorization_sequence": 2,
                    "arm_nonce": 9,
                    "expiry_s": 730,
                    "authorizing_snapshot_generation": 12,
                    "authorizing_query_nonce": 91,
                    "accepted_D14_D8_apertures": 600,
                    "admission_deadline_delta": deadline,
                    "natural_opportunity": "natural-opportunity-1",
                    "admitted_utc": "2026-09-09T00:00:00Z",
                }
            ],
        }
    )
    supervisor._validate_bench_attempt_arm_admissions()
    supervisor.state["bench_attempt_arm_admissions"][0][
        "authorizing_snapshot_generation"
    ] = 0
    with pytest.raises(ValueError, match="ARM admission differs"):
        supervisor._validate_bench_attempt_arm_admissions()


def test_setup_timeout_becomes_review_hold_not_abort(tmp_path: Path) -> None:
    supervisor = _bare_supervisor(CONTINGENT_72_HOUR_HYBRID_CONTROL, tmp_path)
    supervisor.state.update(
        {
            "manual_start_sent": True,
            "setup_requested_utc": "2026-09-09T00:00:00Z",
        }
    )
    holds: list[tuple[str, str]] = []
    supervisor._enter_host_verification_hold = (
        lambda error, *, source="host_verifier": holds.append(
            (str(error), source)
        )
    )
    supervisor._abort = lambda _reason: (_ for _ in ()).throw(
        AssertionError("host setup discrepancy attempted an abort")
    )

    supervisor._check_setup_transaction_timeout(
        {}, supervisor_module._parse_utc_epoch("2026-09-09T00:01:00Z")
    )

    assert holds == [
        (
            "setup transaction expired without an observed result",
            "setup_transaction_observer",
        )
    ]


def test_physical_factory_exposes_no_private_rehearsal_capability() -> None:
    assert "private_rehearsal_capability" not in inspect.signature(
        supervisor_module.create_supervisor
    ).parameters
    with pytest.raises(ValueError, match="lacks an exact bench-attempt envelope"):
        supervisor_module._runtime_envelope(
            {"programme_id": ADAPTIVE_HYBRID_PROGRAMME.programme_id}
        )


def test_validated_nonphysical_spec_helper_accepts_only_exact_private_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = {
        "programme_id": ADAPTIVE_HYBRID_PROGRAMME.programme_id,
        "stage": "OTIS_ADAPTIVE_HYBRID_OPERATIONAL_REHEARSAL_PTY",
        "closed_loop_control": False,
        "actuation_authorized": False,
        "authority_effective": False,
        "actionable": False,
        "qualification_evidence": False,
        "physical_actions_performed": 0,
        "board": "deterministic_pty_no_physical_hardware",
        "capture_mode": "real_capture_device_process_over_pty",
        "mode": "adaptive_hybrid_deterministic_process_topology_rehearsal_pty_v1",
        "scenario": (
            "adaptive_hybrid_two_transaction_metadata_hold_abort_rotation_v1"
        ),
        "activation": {
            "activation_sha256": "0" * 64,
            "status": "rehearsal_no_physical_authority",
        },
    }
    observed: list[tuple[dict[str, object], object]] = []

    def load(
        manifest: dict[str, object], *, private_rehearsal_capability: object
    ) -> tuple[str, str]:
        observed.append((manifest, private_rehearsal_capability))
        return "spec", "identities"

    monkeypatch.setattr(supervisor_module, "load_active_hybrid_spec", load)

    assert supervisor_module.load_validated_nonphysical_rehearsal_spec(private) == (
        "spec",
        "identities",
    )
    assert observed[0][0]["stage"] == ADAPTIVE_HYBRID_PROGRAMME.live_stage
    assert observed[0][1] is not None

    near_miss = {**private, "physical_actions_performed": 1}
    with pytest.raises(ValueError, match="zero-authority boundary"):
        supervisor_module.load_validated_nonphysical_rehearsal_spec(near_miss)
    assert len(observed) == 1
