from __future__ import annotations

import json
import time
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools import adaptive_hybrid_supervisor as supervisor_module
from host.otis_tools.adaptive_hybrid_contract import ADAPTIVE_HYBRID_PROGRAMME
from host.otis_tools.adaptive_hybrid_supervisor import AdaptiveHybridSupervisor
from host.otis_tools.adaptive_hybrid_transport import ControlSupervisorBase
from tests.runtime_fixtures import construct_simulated_supervisor


def _supervisor(tmp_path: Path) -> AdaptiveHybridSupervisor:
    supervisor = construct_simulated_supervisor(tmp_path)
    supervisor._retained_supervisor_state_at_start = False
    supervisor.state.update(
        {
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
            "initial_session_id": 7,
            "host_verification_hold": None,
            "host_attach_query_nonce": 40,
            "active_snapshot_request_nonce": 40,
            "startup_census": None,
            "startup_census_history": [],
            "startup_census_authority_admitted": False,
            "startup_census_process_nonce": 91,
        }
    )
    supervisor._save = lambda: None
    supervisor._programme_event = lambda *_args, **_kwargs: None
    return supervisor


def _fresh_health(*, generation: int = 12, nonce: int = 41) -> dict[tuple[str, str], str]:
    values = {
        "state": "DISARMED",
        "evidence_pending": "false",
        "evidence_phase": "evidence_clear",
        "capture_lease_live": "false",
        "manual_start_confirmed": "false",
        "arm_eligible": "false",
        "fail_static": "false",
        "hybrid_state": "SETUP_PENDING",
        "first_phase_checkpoint_passed": "false",
        "phase_nonzero_application_count": "0",
        "phase_material_application_count": "0",
        "frequency_only_application_count": "0",
        "evidence_request_sequence": "0",
        "expected_setup_code": f"0x{ADAPTIVE_HYBRID_PROGRAMME.setup_code:04X}",
        "confirmed_applied_code_known": "false",
        "confirmed_applied_code": "unavailable",
        "correction_count": "0",
        "cumulative_movement_codes": "0",
        "dac_epoch": "0",
        "automatic_retry": "false",
        "automatic_restore": "false",
        "snapshot_generation_complete": str(generation),
        "query_nonce": str(nonce),
        "session_id": "7",
    }
    return {("adaptive_hybrid", key): value for key, value in values.items()}


def test_lowest_command_boundary_allows_only_queries_before_census(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path)

    for command in ("CONFIG?", "DUALCORE?", "DAC?", "ACTIVE?", "ACTIVE SNAPSHOT 41"):
        supervisor._assert_command_admitted(command)
    for command in (
        "ACTIVE LEASE 1",
        "ACTIVE SETUP 1 1 1 1 1 0xA84D 1 " + "1" * 64,
        "ACTIVE ARM 1 1 1",
        "ACTIVE EVIDENCE 1 1",
    ):
        with pytest.raises(ValueError, match="startup census"):
            supervisor._assert_command_admitted(command)


def test_fresh_census_precedes_first_lease_and_survives_later_query_nonce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _supervisor(tmp_path)
    health = _fresh_health()
    supervisor._identity_ready = lambda _health: True
    observed_health_calls = 0

    def current_health(*, required_query_nonce: int | None = None):
        nonlocal observed_health_calls
        observed_health_calls += 1
        if required_query_nonce is None:
            return {}
        assert required_query_nonce == 41
        return health

    supervisor._current_health = current_health
    commands: list[str] = []
    monkeypatch.setattr(
        ControlSupervisorBase,
        "_command",
        lambda _self, command: commands.append(command),
    )

    supervisor._establish_startup_census()
    assert supervisor.state["startup_census"]["classification"] == "fresh_disarmed"
    assert supervisor.state["startup_census_authority_admitted"] is True
    supervisor._renew_lease()
    supervisor.state["active_snapshot_request_nonce"] = 42
    supervisor._assert_command_admitted("ACTIVE ARM 1 2 3")

    assert commands == ["ACTIVE SNAPSHOT 41", "ACTIVE LEASE 1"]
    assert observed_health_calls == 2


@pytest.mark.parametrize(
    ("changes", "classification"),
    [
        (
            {
                "manual_start_confirmed": "true",
                "confirmed_applied_code_known": "true",
                "confirmed_applied_code": "0xA84D",
                "dac_epoch": "1",
            },
            "already_setup_or_tracking",
        ),
        (
            {
                "manual_start_confirmed": "true",
                "evidence_pending": "true",
                "evidence_phase": "application_pending",
                "evidence_request_sequence": "3",
                "confirmed_applied_code_known": "true",
                "confirmed_applied_code": "0xA84D",
                "dac_epoch": "1",
            },
            "transaction_inflight",
        ),
        ({"state": "FAULT", "fail_static": "true"}, "terminal_or_fault"),
    ],
)
def test_unowned_active_states_are_discovered_without_authority(
    tmp_path: Path, changes: dict[str, str], classification: str
) -> None:
    supervisor = _supervisor(tmp_path)
    health = _fresh_health()
    health.update(
        {("adaptive_hybrid", key): value for key, value in changes.items()}
    )
    supervisor._identity_ready = lambda _health: True

    observed, admitted, diagnostics = supervisor._classify_startup_snapshot(health)

    assert observed == classification
    assert admitted is False
    assert diagnostics


def test_prior_host_hold_cannot_be_reclassified_as_fresh(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    supervisor.state["host_verification_hold"] = {"source": "retained"}
    supervisor._identity_ready = lambda _health: True

    classification, admitted, diagnostics = supervisor._classify_startup_snapshot(
        _fresh_health()
    )

    assert classification == "incoherent"
    assert admitted is False
    assert "retained host_verification_hold is not pristine" in diagnostics


def _setup_authority_and_retained_inflight_fixture(
    supervisor: AdaptiveHybridSupervisor,
    health: dict[tuple[str, str], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor._retained_supervisor_state_at_start = True
    supervisor.state.update(
        {
            "manual_start_sent": True,
            "setup_authorization_sequence": 1,
            "setup_confirmed_utc": "2026-09-11T00:00:00Z",
            "setup_confirmation": {
                "transaction_record_sequence": 1,
                "event_timestamp_ticks": 1_000_001,
                "time_domain": "rp2040_monotonic_us64",
                "session_id": 7,
                "applied_code": ADAPTIVE_HYBRID_PROGRAMME.setup_code,
                "dac_epoch": 1,
                "setup_authorization_sequence": 1,
                "setup_status_generation": 10,
                "setup_query_nonce": 9,
                "setup_authority_record_sha256": "pending",
            },
            "setup_authority_path": "reports/adaptive_hybrid_setup_authority_v1.json",
            "terminal_static_code": ADAPTIVE_HYBRID_PROGRAMME.setup_code,
            "bench_attempt_causal_state": {"firmware_correction_count": 0},
            "observed_manual_record_sequences": [1],
            "inflight_evidence_acknowledgement": {
                "record_sequence": 2,
                "request_sequence": 1,
                "phase": 1,
                "pre_submit_snapshot_generation": 11,
                "pre_submit_evidence_phase": "request_pending",
                "host_write_confirmed": True,
                "causal_observation_owner_nonce": supervisor.state["startup_census_process_nonce"],
                "causal_observation_deadline_monotonic_ns": time.monotonic_ns() + 30_000_000_000,
            },
        }
    )
    health.update(
        {
            ("adaptive_hybrid", "state"): "DISARMED",
            ("adaptive_hybrid", "hybrid_state"): "FREQUENCY_ACQUIRE",
            ("adaptive_hybrid", "manual_start_confirmed"): "true",
            ("adaptive_hybrid", "evidence_pending"): "true",
            ("adaptive_hybrid", "evidence_phase"): "request_pending",
            ("adaptive_hybrid", "evidence_request_sequence"): "1",
            ("adaptive_hybrid", "confirmed_applied_code_known"): "true",
            ("adaptive_hybrid", "confirmed_applied_code"): "0xA84D",
            ("adaptive_hybrid", "dac_epoch"): "1",
            ("adaptive_hybrid", "acceptance_epoch"): "1",
            ("adaptive_hybrid", "accepted_boundary_ordinal"): "600",
        }
    )
    row = {
        "transaction_record_sequence": "2",
        "request_sequence": "1",
        "event": "request_created",
        "session_id": "7",
        "source_acceptance_epoch": "1",
        "source_closing_accepted_boundary_ordinal": "600",
    }
    manual_row = {
        "transaction_record_sequence": "1",
        "event": "manual_start",
        "session_id": "7",
        "application_timestamp_s": "1",
        "event_timestamp_ticks": "1000001",
        "time_domain": "rp2040_monotonic_us64",
        "authorization_sequence": "0",
        "nonce": "0",
        "request_sequence": "0",
        "decision_sequence": "0",
        "current_applied_code": str(ADAPTIVE_HYBRID_PROGRAMME.setup_code),
        "requested_delta_codes": "0",
        "requested_code": str(ADAPTIVE_HYBRID_PROGRAMME.setup_code),
        "correction_ordinal": "0",
        "cumulative_after_codes": "0",
        "accepted_code": str(ADAPTIVE_HYBRID_PROGRAMME.setup_code),
        "applied_code": str(ADAPTIVE_HYBRID_PROGRAMME.setup_code),
        "application_sequence": "0",
        "i2c_ok": "true",
        "clamped": "false",
        "ambiguous": "false",
        "dac_epoch": "1",
        "estimator_history_reset": "false",
        "correction_count": "0",
        "cumulative_movement_codes": "0",
        "active_state": "DISARMED",
        "response_class": "unavailable",
        "reason": "manual_start_established",
        "evidence_state": "evidence_clear",
    }
    authority_health = {
        ("adaptive_hybrid", "query_nonce"): "9",
        ("adaptive_hybrid", "session_id"): "7",
        ("adaptive_hybrid", "snapshot_generation_complete"): "10",
        ("adaptive_hybrid", "uptime_s"): "100",
    }
    authority = {
        "contract": supervisor_module.SETUP_AUTHORITY_CONTRACT,
        "created_utc": "2026-09-11T00:00:00Z",
        "request": {
            "authorization_sequence": 1,
            "status_generation": 10,
            "query_nonce": 9,
            "expires_s": 130,
            "session_id": 7,
            "requested_code": ADAPTIVE_HYBRID_PROGRAMME.setup_code,
            "one_shot_ordinal": 1,
            "configuration_identity": "1" * 64,
        },
        "health": [
            {"component": component, "key": key, "value": value}
            for (component, key), value in sorted(authority_health.items())
        ],
        "active_row_count": 0,
        "dac_row_count": 0,
        "telemetry_drop_baseline": 0,
    }
    authority["record_sha256"] = sha256(
        json.dumps(authority, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    authority_path = supervisor.run_dir / supervisor_module.SETUP_AUTHORITY_PATH
    authority_path.parent.mkdir(parents=True, exist_ok=True)
    authority_path.write_text(json.dumps(authority) + "\n", encoding="utf-8")
    supervisor.state["setup_confirmation"]["setup_authority_record_sha256"] = authority[
        "record_sha256"
    ]
    monkeypatch.setattr(
        supervisor_module,
        "validate_csv",
        lambda *_args, **_kwargs: SimpleNamespace(errors=[]),
    )
    monkeypatch.setattr(supervisor_module, "_read_csv", lambda _path: [manual_row, row])
    monkeypatch.setattr(
        supervisor_module,
        "evaluate_setup_prewrite_readiness",
        lambda *_args, **_kwargs: SimpleNamespace(ready=True, diagnostic=lambda: "ready"),
    )


def test_nonfresh_retained_transaction_is_observational_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _supervisor(tmp_path)
    health = _fresh_health()
    _setup_authority_and_retained_inflight_fixture(supervisor, health, monkeypatch)
    supervisor._identity_ready = lambda _health: True

    classification, admitted, diagnostics = supervisor._classify_startup_snapshot(
        health
    )

    assert classification == "transaction_inflight"
    assert admitted is False
    assert any("continuation is unsupported" in item for item in diagnostics)
    for command in (
        "ACTIVE LEASE 2",
        "ACTIVE EVIDENCE 1 1",
        "ACTIVE SETUP 1 1 1 1 1 0xA84D 1 " + "1" * 64,
        "ACTIVE ARM 1 1 1",
    ):
        with pytest.raises(ValueError, match="startup census"):
            supervisor._assert_command_admitted(command)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing_manual", False),
        ("unobserved_manual", False),
        ("altered_authority", "raises"),
    ],
)
def test_setup_confirmation_requires_exact_observed_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected: bool | str,
) -> None:
    supervisor = _supervisor(tmp_path)
    health = _fresh_health()
    _setup_authority_and_retained_inflight_fixture(supervisor, health, monkeypatch)
    if mutation == "missing_manual":
        monkeypatch.setattr(supervisor_module, "_read_csv", lambda _path: [])
    elif mutation == "unobserved_manual":
        supervisor.state["observed_manual_record_sequences"] = []
    else:
        path = supervisor.run_dir / supervisor_module.SETUP_AUTHORITY_PATH
        value = json.loads(path.read_text(encoding="utf-8"))
        value["request"]["requested_code"] += 1
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")

    if expected == "raises":
        with pytest.raises(ValueError, match="authority"):
            supervisor._latch_setup_confirmation()
    else:
        assert supervisor._latch_setup_confirmation() is expected


@pytest.mark.parametrize(
    ("key", "value", "classification"),
    [
        ("state", "FAULT", "terminal_or_fault"),
        ("fail_static", "true", "terminal_or_fault"),
        ("acceptance_epoch", "2", "transaction_inflight"),
    ],
)
def test_faulted_or_source_changed_retained_state_never_admits_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    value: str,
    classification: str,
) -> None:
    supervisor = _supervisor(tmp_path)
    health = _fresh_health()
    _setup_authority_and_retained_inflight_fixture(supervisor, health, monkeypatch)
    health[("adaptive_hybrid", key)] = value
    supervisor._identity_ready = lambda _health: True

    observed, admitted, diagnostics = supervisor._classify_startup_snapshot(health)

    assert observed == classification
    assert admitted is False
    assert any("continuation is unsupported" in item for item in diagnostics)


def test_pre_census_transaction_consumer_cannot_prepare_ack(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    supervisor._validate_hybrid_decisions_or_hold = lambda: (_ for _ in ()).throw(
        AssertionError("pre-census transaction evidence was consumed")
    )

    supervisor._process_transactions()

    assert supervisor.state["inflight_evidence_acknowledgement"] is None
