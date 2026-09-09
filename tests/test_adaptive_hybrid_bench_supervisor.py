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
    INHIBITED_ZERO_WRITE,
    SINGLE_AUTOMATIC_APPLICATION,
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


def test_zero_write_gate_cannot_reach_identity_setup_or_arm(tmp_path: Path) -> None:
    supervisor = _bare_supervisor(INHIBITED_ZERO_WRITE, tmp_path)
    supervisor._identity_ready = lambda _health: (_ for _ in ()).throw(
        AssertionError("zero-write gate evaluated a setup/ARM prerequisite")
    )

    supervisor._maybe_start_or_arm({})

    assert supervisor.state["manual_start_sent"] is False
    assert supervisor.state["authorization_sequence"] == 0
    assert supervisor.state["bench_attempt_arm_submission_count"] == 0


def test_one_application_setup_is_submitted_once(tmp_path: Path) -> None:
    supervisor = _bare_supervisor(SINGLE_AUTOMATIC_APPLICATION, tmp_path)
    supervisor._identity_ready = lambda _health: True
    supervisor._prewrite_readiness = lambda _health: SimpleNamespace(ready=True)
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
    }

    supervisor._maybe_start_or_arm(health)
    supervisor._maybe_start_or_arm(health)

    assert commands == ["ACTIVE SETUP exact"]
    assert supervisor.state["manual_start_sent"] is True


def test_application_closure_is_durable_before_phase_three_command(
    tmp_path: Path,
) -> None:
    supervisor = _bare_supervisor(SINGLE_AUTOMATIC_APPLICATION, tmp_path)
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
        assert causal["authority_closed"] is True
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
    closure_event_index = trace.index(
        ("programme_event", "bench_attempt_authority_closed")
    )
    command_index = trace.index(("command", "ACTIVE EVIDENCE 7 3"))
    assert closure_event_index < command_index
    causal = supervisor.state["bench_attempt_causal_state"]
    assert causal["closure"]["accepted_D14_D8_apertures_at_application"] == 733
    assert supervisor.state["bench_attempt_arm_admission_closed"] is True
    assert supervisor.state["arm_pending"] is False

    events_before = [item for item in trace if item[0] == "programme_event"]
    supervisor._prepare_evidence_acknowledgement(row, 3)
    assert [item for item in trace if item[0] == "programme_event"] == events_before


@pytest.mark.parametrize("firmware_count", (0, 2))
def test_application_count_mismatch_withholds_phase_three_acknowledgement(
    tmp_path: Path, firmware_count: int
) -> None:
    supervisor = _bare_supervisor(SINGLE_AUTOMATIC_APPLICATION, tmp_path)
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
        supervisor._close_bench_authority_before_application_acknowledgement(
            row, health
        )
    assert supervisor.state["bench_attempt_causal_state"]["authority_closed"] is False


def test_transaction_validation_error_enters_review_hold_without_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _bare_supervisor(SINGLE_AUTOMATIC_APPLICATION, tmp_path)
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
    supervisor = _bare_supervisor(SINGLE_AUTOMATIC_APPLICATION, tmp_path)
    supervisor.state.update(
        {
            "qualified_d14_segment_accepted_window_origin": 100,
            "qualified_d14_segment_reference_sequence_origin": 200,
            "qualified_d14_completed_apertures_before_segment": 0,
        }
    )
    supervisor._save = lambda: None
    events: list[dict[str, object]] = []
    supervisor._programme_event = lambda _event, **fields: events.append(fields)

    before = {
        ("pps_gate", "accepted_window_count"): "1899",
        ("pps_gate", "boundary_reference_sequence"): "1999",
    }
    endpoint = {
        ("pps_gate", "accepted_window_count"): "1900",
        ("pps_gate", "boundary_reference_sequence"): "2000",
    }

    assert supervisor._close_bench_arm_admission_if_required(before) is False
    assert supervisor._close_bench_arm_admission_if_required(endpoint) is True
    assert supervisor.state["bench_attempt_arm_admission_closed"] is True
    assert supervisor.state["bench_attempt_arm_admission_endpoint"] == 1800
    assert events[-1]["progress_domain"] == "accepted_D14_D8_apertures"


def test_one_application_arm_is_durable_and_not_reused_for_same_opportunity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _bare_supervisor(SINGLE_AUTOMATIC_APPLICATION, tmp_path)
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
            "qualified_d14_segment_accepted_window_origin": 100,
            "qualified_d14_segment_reference_sequence_origin": 200,
            "qualified_d14_completed_apertures_before_segment": 0,
        }
    )
    supervisor._identity_ready = lambda _health: True
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
        lambda _path: [{"decision_id": "natural-opportunity-1"}],
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
        ("adaptive_hybrid", "snapshot_generation_complete"): "12",
        ("adaptive_hybrid", "query_nonce"): "91",
        ("pps_gate", "accepted_window_count"): "700",
        ("pps_gate", "boundary_reference_sequence"): "800",
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


def test_retained_arm_admission_rejects_restart_tampering(tmp_path: Path) -> None:
    supervisor = _bare_supervisor(SINGLE_AUTOMATIC_APPLICATION, tmp_path)
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
                    "admission_deadline_delta": 1800,
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
    supervisor = _bare_supervisor(SINGLE_AUTOMATIC_APPLICATION, tmp_path)
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
