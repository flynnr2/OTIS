from __future__ import annotations

import csv
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from host.otis_tools import active_hybrid_live_supervisor as live
from host.otis_tools.active_control_supervisor import (
    _next_selected_interval_is_cadence_eligible,
)
from host.otis_tools.bounded_tight_deadband_prewrite_contract import (
    RAW_PPS_QUALIFICATION_DEADLINE_S,
    canonical_prewrite_fixture,
)
from host.otis_tools.prewrite_readiness_contract import PrewriteReadiness
from host.otis_tools.contracts import CONTRACT_FIELDS


def _utc(epoch: float) -> str:
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


ROOT = Path(__file__).resolve().parents[1]


def _manifest(*, wall_origin_epoch: float = 1_800_000_000.0) -> dict:
    policy_path = (
        ROOT / "profiles/discipline/cx320_bounded_active_hybrid_tight_v1.json"
    )
    policy_sha256 = sha256(policy_path.read_bytes()).hexdigest()
    source_sha256 = "a" * 64
    configuration_sha256 = "b" * 64
    return {
        "manifest_sha256": "c" * 64,
        "programme_id": live.PROGRAMME_ID,
        "stage": "CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_LIVE",
        "run_identity": live.RUNTIME_RUN_IDENTITY,
        "profile_identity": live.PROFILE_ID,
        "started_at_utc": _utc(wall_origin_epoch),
        "bundle": {"bundle_sha256": "d" * 64},
        "firmware": {
            "build_identity": f"{source_sha256}:{configuration_sha256}",
            "source_sha256": source_sha256,
            "configuration_sha256": configuration_sha256,
            "uf2": {"sha256": "e" * 64},
        },
        "policy": {
            "path": str(policy_path),
            "sha256": policy_sha256,
            "size_bytes": policy_path.stat().st_size,
            "policy_sha256": policy_sha256,
        },
        "cx320": {
            "run_identity": live.RUNTIME_RUN_IDENTITY,
            "profile_id": live.PROFILE_ID,
            "setup": {"code": live.SETUP_CODE},
            "automatic_control": {
                "maximum_total_applications": live.MAXIMUM_APPLICATIONS,
                "maximum_cumulative_movement_codes": (
                    live.MAXIMUM_CUMULATIVE_MOVEMENT_CODES
                ),
                "maximum_step_codes": live.MAXIMUM_STEP_CODES,
                "minimum_applied_cadence_s": live.DECISION_CADENCE_S,
                "minimum_code": live.MINIMUM_CODE,
                "maximum_code": live.MAXIMUM_CODE,
            },
            "qualification": {
                "qualified_duration_s": live.QUALIFIED_DURATION_S,
                "absolute_wall_clock_limit_s": live.ABSOLUTE_WALL_LIMIT_S,
                "no_extension": True,
            },
        },
    }


def _supervisor(
    tmp_path: Path, *, wall_origin_epoch: float = 1_800_000_000.0
) -> live.ActiveHybridLiveSupervisor:
    run_dir = tmp_path / "run"
    (run_dir / "csv").mkdir(parents=True)
    manifest = _manifest(wall_origin_epoch=wall_origin_epoch)
    spec, identities = live.load_active_hybrid_spec(manifest)
    return live.ActiveHybridLiveSupervisor(
        manifest=manifest,
        manifest_path=run_dir / "run_manifest.json",
        run_dir=run_dir,
        command_fifo=tmp_path / "normal.fifo",
        emergency_command_fifo=tmp_path / "emergency.fifo",
        abort_fifo=tmp_path / "abort.fifo",
        spec=spec,
        identities=identities,
        expected_build_identity=manifest["firmware"]["build_identity"],
        duration_s=None,
    )


def _health(
    supervisor: live.ActiveHybridLiveSupervisor, **values: str
) -> dict[tuple[str, str], str]:
    active = {
        "snapshot_generation_begin": "7",
        "snapshot_contract": "cx317_active_status_snapshot_v1",
        "enabled": "true",
        "run_identity": supervisor.spec.run_identity,
        "build_identity": supervisor.expected_build_identity,
        "profile_identity": supervisor.spec.profile,
        **supervisor.identities,
        "state": "DISARMED",
        "reason": "initialized_disarmed",
        "evidence_pending": "false",
        "evidence_phase": "evidence_clear",
        "capture_lease_live": "true",
        "manual_start_confirmed": "true",
        "arm_eligible": "true",
        "fail_static": "false",
        "setup_gnss_eligible": "true",
        "setup_reference_eligible": "true",
        "setup_partition_healthy": "true",
        "hybrid_state": "FREQUENCY_ACQUIRE",
        "hybrid_reason": "frequency_acquisition",
        "first_phase_checkpoint_passed": "false",
        "phase_nonzero_application_count": "0",
        "phase_material_application_count": "0",
        "frequency_only_application_count": "0",
        "session_id": "1",
        "query_nonce": str(supervisor.state["host_attach_query_nonce"]),
        "uptime_s": "4000",
        "evidence_request_sequence": "0",
        "expected_setup_code": "0xA83C",
        "confirmed_applied_code_known": "true",
        "confirmed_applied_code": str(live.SETUP_CODE),
        "correction_count": "0",
        "cumulative_movement_codes": "0",
        "dac_epoch": "1",
        "selected_interval_count": "0",
        "automatic_retry": "false",
        "automatic_restore": "false",
        "snapshot_generation_complete": "7",
    }
    active.update(values)
    health = {("cx317_active", key): value for key, value in active.items()}
    health.update(
        {
            ("capture", "dropped_count"): "0",
            ("capture", "pps_count_boundary_dropped_count"): "0",
            ("dual_core", "telemetry_dropped"): "0",
            ("dual_core", "service_publish_failures"): "0",
            ("dual_core", "partition_fault"): "none",
            ("dual_core", "fail_static"): "false",
            ("cx317_preview", "telemetry_dropped_frames"): "0",
            ("cx317_preview", "actionable"): "false",
            ("cx317_preview", "actuation_authorized"): "false",
            ("cx318_preview", "actionable"): "false",
            ("cx318_preview", "actuation_authorized"): "false",
            ("cx318_preview", "authorization_consumed"): "false",
        }
    )
    return health


def _ready() -> PrewriteReadiness:
    return PrewriteReadiness(
        contract_id="fixture",
        ready=True,
        missing=(),
        mismatches=(),
        inherited_preview_baseline_code="0xA828",
        inherited_preview_baseline_provenance="fixture",
        planned_live_stimulus_code="0xA83C",
        physical_dac_confirmation="unknown_before_live_stimulus",
    )


def _prewrite_health(
    supervisor: live.ActiveHybridLiveSupervisor,
) -> dict[tuple[str, str], str]:
    expected = {
        "run_identity": supervisor.spec.run_identity,
        "build_identity": supervisor.expected_build_identity,
        "profile_identity": supervisor.spec.profile,
        **supervisor.identities,
    }
    health = canonical_prewrite_fixture(
        expected_identity=expected,
        planned_live_stimulus_code=supervisor.spec.start_code,
    )
    health[("cx317_active", "query_nonce")] = str(
        supervisor.state["host_attach_query_nonce"]
    )
    return health


def _write_control_hold(supervisor: live.ActiveHybridLiveSupervisor) -> None:
    path = supervisor.run_dir / live.CONTROL_CSV
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "decision_id",
                "decision_timestamp_ticks",
                "preview_available",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "decision_id": "control:1",
                "decision_timestamp_ticks": "16000000000",
                "preview_available": "false",
            }
        )


def _write_continuously_available_control_previews(
    supervisor: live.ActiveHybridLiveSupervisor,
) -> None:
    path = supervisor.run_dir / live.CONTROL_CSV
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "decision_id",
                "decision_timestamp_ticks",
                "preview_available",
            ),
        )
        writer.writeheader()
        for sequence, timestamp_s in enumerate((3001, 3601, 4201), start=2):
            writer.writerow(
                {
                    "decision_id": f"control:{sequence}",
                    "decision_timestamp_ticks": str(timestamp_s * 16_000_000),
                    "preview_available": "true",
                }
            )


def _append_selected_estimate(
    supervisor: live.ActiveHybridLiveSupervisor,
    *,
    estimate_seq: int,
    source_dac_ref: str,
    timestamp_s: int | None = None,
    timestamp_ticks: int | None = None,
) -> None:
    path = supervisor.run_dir / live.ESTIMATES_CSV
    fields = CONTRACT_FIELDS["estimates_v2"]
    row = {field: "" for field in fields}
    row.update(
        {
            "record_type": "EST",
            "schema_version": "2",
            "estimate_seq": str(estimate_seq),
            "estimate_id": f"est:cx317:selected600:{estimate_seq:06d}",
            "estimator_timestamp_ticks": str(
                timestamp_ticks
                if timestamp_ticks is not None
                else (
                    timestamp_s
                    if timestamp_s is not None
                    else estimate_seq * 600
                )
                * live.RP2040_TIMER0_TICKS_PER_SECOND
            ),
            "time_domain": "rp2040_timer0",
            "estimator_version": "cx317_selected_600s_nonoverlap_v1",
            "source_count_ref": f"live:CNT:{estimate_seq * 600}",
            "source_dac_ref": source_dac_ref,
            "observation_validity": "valid",
            "reference_validity": "valid",
            "reference_continuity": "true",
            "count_validity": "valid",
            "count_continuity": "true",
            "diagnostic_health": "healthy",
            "accepted_sample_count": "600",
            "preview_eligibility": "true",
        }
    )
    write_header = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def test_exact_runtime_identity_and_frozen_envelope() -> None:
    manifest = _manifest()
    spec, identities = live.load_active_hybrid_spec(manifest)

    assert spec.run_identity == "cx320_active_hybrid:3200001"
    assert spec.profile == "cx320_active_hybrid"
    assert (
        spec.start_code,
        spec.correction_limit,
        spec.cumulative_limit,
        spec.maximum_step,
        spec.minimum_code,
        spec.maximum_code,
    ) == (0xA83C, 4, 84, 21, 0xA800, 0xAB00)
    assert identities["active_policy_sha256"] == manifest["policy"][
        "policy_sha256"
    ]
    assert identities["numerical_policy_sha256"] == manifest["policy"][
        "policy_sha256"
    ]
    assert live._runtime_envelope(manifest).wall_origin_utc == manifest[
        "started_at_utc"
    ]
    assert live.QUALIFIED_DURATION_S == 12 * 60 * 60
    assert live.ABSOLUTE_WALL_LIMIT_S == 16 * 60 * 60


def test_cx320_uses_observed_raw_pps_qualification_deadline(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path)

    assert supervisor.prewrite_contract_startup_grace_s == (
        RAW_PPS_QUALIFICATION_DEADLINE_S
    )


def test_cx320_prewrite_waits_for_exact_firmware_setup_authority(
    tmp_path: Path, monkeypatch
) -> None:
    supervisor = _supervisor(tmp_path)
    commands: list[str] = []
    monkeypatch.setattr(supervisor, "_command", commands.append)
    health = _prewrite_health(supervisor)
    health[("cx317_active", "setup_reference_eligible")] = "false"

    readiness = supervisor._prewrite_readiness(health)
    supervisor._maybe_start_or_arm(health)

    assert readiness.ready is False
    assert readiness.contract_id == (
        "cx320_active_hybrid_prewrite_runtime_contract_v1"
    )
    assert readiness.mismatches == (
        "cx317_active.setup_reference_eligible='false', expected 'true' "
        "before setup",
    )
    assert commands == []
    assert supervisor.state["manual_start_sent"] is False
    assert not (
        supervisor.run_dir / "reports/setup_authority_input_v1.json"
    ).exists()


def test_cx320_prewrite_accepts_the_complete_setup_authority_snapshot(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path)

    readiness = supervisor._prewrite_readiness(_prewrite_health(supervisor))

    assert readiness.ready is True
    assert readiness.missing == ()
    assert readiness.mismatches == ()


def test_qualified_clock_requires_fresh_selected_estimate_from_setup_epoch(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path)
    supervisor.state["setup_confirmed_utc"] = _utc(1_800_000_611.0)
    supervisor._save()
    health = _health(supervisor, dac_epoch="1")

    _append_selected_estimate(
        supervisor,
        estimate_seq=1,
        source_dac_ref="live:DAC:0",
    )
    supervisor._maybe_qualify(health)

    assert supervisor.state["qualification_started_utc"] is None
    assert supervisor.state["qualified_origin_estimate_id"] is None

    _append_selected_estimate(
        supervisor,
        estimate_seq=2,
        source_dac_ref="live:DAC:1",
    )
    supervisor._maybe_qualify(health)

    assert supervisor.state["qualification_started_utc"] is not None
    assert supervisor.state["qualified_origin_estimate_id"] == (
        "est:cx317:selected600:000002"
    )
    assert supervisor.state["qualified_origin_timestamp_ticks"] == (
        1200 * live.RP2040_TIMER0_TICKS_PER_SECOND
    )
    assert supervisor.state["qualified_origin_session_id"] == 1
    assert '"source_dac_ref": "live:DAC:1"' in (
        supervisor.events_path.read_text(encoding="utf-8")
    )


def test_qualified_clock_defers_fractional_origin_until_uptime_lower_bound(
    tmp_path: Path,
) -> None:
    """Regress the exact host-side escape observed by physical attempt 8."""

    supervisor = _supervisor(tmp_path)
    supervisor.state["setup_confirmed_utc"] = _utc(1_800_000_611.0)
    supervisor._save()
    attempt8_origin_ticks = 38_429_602_864  # 2401.850179 s
    _append_selected_estimate(
        supervisor,
        estimate_seq=541,
        source_dac_ref="live:DAC:1",
        timestamp_ticks=attempt8_origin_ticks,
    )

    # A complete snapshot with integer uptime=2401 only proves that the exact
    # device clock is at least 2401 s.  The estimator timestamp is 0.850179 s
    # beyond that lower bound, so qualification must wait rather than abort.
    supervisor._maybe_qualify(_health(supervisor, uptime_s="2401"))
    assert supervisor.state["qualification_started_utc"] is None
    assert supervisor.state["qualified_origin_estimate_id"] is None

    supervisor._maybe_qualify(_health(supervisor, uptime_s="2402"))
    assert supervisor.state["qualified_origin_estimate_id"] == (
        "est:cx317:selected600:000541"
    )
    assert supervisor.state["qualified_origin_timestamp_ticks"] == (
        attempt8_origin_ticks
    )

    # All later boundaries remain conservative relative to the exact origin:
    # the integer lower bound cannot close one until it has crossed the exact
    # fractional timestamp plus the frozen duration.
    endpoint_floor_s = 2401 + live.QUALIFIED_DURATION_S
    before = _health(supervisor, uptime_s=str(endpoint_floor_s))
    assert supervisor._qualified_elapsed_ticks(before) < (
        live.QUALIFIED_DURATION_S * live.RP2040_TIMER0_TICKS_PER_SECOND
    )
    after = _health(supervisor, uptime_s=str(endpoint_floor_s + 1))
    assert supervisor._qualified_elapsed_ticks(after) >= (
        live.QUALIFIED_DURATION_S * live.RP2040_TIMER0_TICKS_PER_SECOND
    )


def test_qualified_clock_status_lead_and_lower_bound_edges(
    tmp_path: Path,
) -> None:
    at_lower = _supervisor(tmp_path / "lower")
    at_lower.state["setup_confirmed_utc"] = _utc(1_800_000_611.0)
    at_lower._save()
    _append_selected_estimate(
        at_lower,
        estimate_seq=9,
        source_dac_ref="live:DAC:1",
        timestamp_ticks=2401 * live.RP2040_TIMER0_TICKS_PER_SECOND,
    )
    at_lower._maybe_qualify(_health(at_lower, uptime_s="2401"))
    assert at_lower.state["qualified_origin_estimate_id"] == (
        "est:cx317:selected600:000009"
    )

    at_lead_limit = _supervisor(tmp_path / "lead_limit")
    at_lead_limit.state["setup_confirmed_utc"] = _utc(1_800_000_611.0)
    at_lead_limit._save()
    maximum_coherent = (
        2401 + live.QUALIFIED_ORIGIN_MAXIMUM_STATUS_LEAD_S
    ) * live.RP2040_TIMER0_TICKS_PER_SECOND
    _append_selected_estimate(
        at_lead_limit,
        estimate_seq=10,
        source_dac_ref="live:DAC:1",
        timestamp_ticks=maximum_coherent,
    )
    at_lead_limit._maybe_qualify(
        _health(at_lead_limit, uptime_s="2401")
    )
    assert at_lead_limit.state["qualified_origin_estimate_id"] is None

    beyond_lead = _supervisor(tmp_path / "beyond_lead")
    beyond_lead.state["setup_confirmed_utc"] = _utc(1_800_000_611.0)
    beyond_lead._save()
    _append_selected_estimate(
        beyond_lead,
        estimate_seq=11,
        source_dac_ref="live:DAC:1",
        timestamp_ticks=maximum_coherent + 1,
    )
    with pytest.raises(ValueError, match="device clock is incoherent"):
        beyond_lead._maybe_qualify(
            _health(beyond_lead, uptime_s="2401")
        )


def test_production_factory_validates_the_run_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    manifest = _manifest()
    manifest_path = tmp_path / "run_manifest.json"
    observed: list[Path] = []

    def validate(path: Path) -> dict:
        observed.append(path)
        return manifest

    monkeypatch.setattr(
        "host.otis_tools.active_hybrid_activation.validate_run_manifest",
        validate,
    )
    supervisor = live.create_supervisor(
        manifest_path=manifest_path,
        run_dir=tmp_path,
        command_fifo=tmp_path / "normal.fifo",
        emergency_command_fifo=tmp_path / "emergency.fifo",
        abort_fifo=tmp_path / "abort.fifo",
        expected_build_identity=manifest["firmware"]["build_identity"],
    )

    assert observed == [manifest_path]
    assert supervisor.envelope.bundle_sha256 == manifest["bundle"][
        "bundle_sha256"
    ]
    assert supervisor.state["wall_origin_utc"] == manifest["started_at_utc"]


def test_retained_state_rejects_manifest_identity_or_wall_origin_drift(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path)
    changed = _manifest(wall_origin_epoch=1_800_000_001.0)
    changed["bundle"]["bundle_sha256"] = "f" * 64
    spec, identities = live.load_active_hybrid_spec(changed)

    with pytest.raises(
        ValueError, match="retained supervisor (bundle_sha256|wall_origin_utc)"
    ):
        live.ActiveHybridLiveSupervisor(
            manifest=changed,
            manifest_path=supervisor.manifest_path,
            run_dir=supervisor.run_dir,
            command_fifo=supervisor.command_fifo,
            emergency_command_fifo=supervisor.emergency_command_fifo,
            abort_fifo=supervisor.abort_fifo,
            spec=spec,
            identities=identities,
            expected_build_identity=changed["firmware"]["build_identity"],
            duration_s=None,
        )


def test_exact_setup_then_frequency_acquisition_arm(
    tmp_path: Path, monkeypatch
) -> None:
    supervisor = _supervisor(tmp_path)
    commands: list[str] = []
    monkeypatch.setattr(supervisor, "_prewrite_readiness", lambda health: _ready())
    monkeypatch.setattr(
        supervisor,
        "_setup_command",
        lambda health: ("ACTIVE SETUP exact", {"authorization_sequence": 1,
                                                "status_generation": 7,
                                                "query_nonce": 9,
                                                "expires_s": 4100,
                                                "session_id": 1}),
    )
    monkeypatch.setattr(supervisor, "_retain_setup_authority", lambda health, request: None)
    monkeypatch.setattr(supervisor, "_command", commands.append)
    before_setup = _health(
        supervisor,
        manual_start_confirmed="false",
        confirmed_applied_code_known="false",
        confirmed_applied_code="unavailable",
        dac_epoch="0",
        arm_eligible="false",
        hybrid_state="SETUP_PENDING",
    )

    supervisor._maybe_start_or_arm(before_setup)

    assert commands == ["ACTIVE SETUP exact"]
    assert supervisor.state["manual_start_sent"] is True

    _write_control_hold(supervisor)
    acquiring = _health(supervisor, selected_interval_count="0")
    supervisor._maybe_start_or_arm(acquiring)
    acquiring[("cx317_active", "selected_interval_count")] = str(
        live.ARM_PROGRESS_THRESHOLD
    )
    supervisor._maybe_start_or_arm(acquiring)

    assert len(commands) == 2
    assert commands[1].startswith("ACTIVE ARM 1 ")
    assert commands[1].split()[-1] == str(4000 + live.ARM_LIFETIME_S)
    assert supervisor.state["arm_pending"] is True


def test_phase_qualify_rearms_despite_continuous_frequency_preview(
    tmp_path: Path, monkeypatch
) -> None:
    supervisor = _supervisor(tmp_path)
    commands: list[str] = []
    monkeypatch.setattr(supervisor, "_command", commands.append)
    supervisor.state["manual_start_sent"] = True
    supervisor.state["qualification_started_utc"] = _utc(1_800_000_000.0)
    supervisor._save()
    _write_continuously_available_control_previews(supervisor)

    # This is the exact attempt-6 escape: the CX319 predictor remains false
    # when every 600-second predecessor preview is marked available.
    assert not _next_selected_interval_is_cadence_eligible(
        supervisor.run_dir / live.CONTROL_CSV,
        supervisor.run_dir / live.ESTIMATES_CSV,
        selected_interval_s=live.SELECTED_INTERVAL_S,
        decision_cadence_s=live.DECISION_CADENCE_S,
    )

    phase_qualify = _health(
        supervisor,
        hybrid_state="PHASE_QUALIFY",
        hybrid_reason="phase_qualified_first_transaction_eligible",
        selected_interval_count="0",
    )
    supervisor._maybe_start_or_arm(phase_qualify)
    phase_qualify[("cx317_active", "selected_interval_count")] = str(
        live.ARM_PROGRESS_THRESHOLD
    )
    supervisor._maybe_start_or_arm(phase_qualify)

    assert len(commands) == 1
    assert commands[0].startswith("ACTIVE ARM 1 ")
    assert supervisor.state["arm_pending"] is True


def test_checkpoint_release_is_observed_only_from_firmware_state(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path)
    supervisor.state["manual_start_sent"] = True
    released = _health(
        supervisor,
        hybrid_state="HYBRID_TRACKING",
        hybrid_reason="first_phase_checkpoint_passed_and_tight_reacquired",
        first_phase_checkpoint_passed="true",
        phase_nonzero_application_count="1",
        phase_material_application_count="1",
        correction_count="1",
        cumulative_movement_codes="4",
    )

    supervisor._check_fail_static_health(released)

    assert supervisor.state["first_phase_checkpoint_passed"] is True
    assert supervisor.state["later_authority_released"] is True
    assert "cx320_first_phase_checkpoint_release_observed" in (
        supervisor.events_path.read_text(encoding="utf-8")
    )


def test_evidence_acknowledgement_requires_a_later_firmware_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    supervisor = _supervisor(tmp_path)
    acknowledgement = {
        "record_sequence": 2,
        "request_sequence": 1,
        "phase": 1,
        "host_write_confirmed": True,
        "pre_submit_snapshot_generation": 7,
        "pre_submit_evidence_phase": "request_pending",
    }
    pending = _health(
        supervisor,
        snapshot_generation_begin="8",
        snapshot_generation_complete="8",
        evidence_phase="request_pending",
        evidence_request_sequence="1",
    )
    monkeypatch.setattr(
        supervisor, "_fresh_active_snapshot_after", lambda _generation: pending
    )
    assert supervisor._confirm_evidence_acknowledgement(acknowledgement) is False

    advanced = _health(
        supervisor,
        snapshot_generation_begin="9",
        snapshot_generation_complete="9",
        evidence_phase="acceptance_pending",
        evidence_request_sequence="1",
    )
    monkeypatch.setattr(
        supervisor, "_fresh_active_snapshot_after", lambda _generation: advanced
    )
    assert supervisor._confirm_evidence_acknowledgement(acknowledgement) is True

    contradictory = dict(advanced)
    contradictory[("cx317_active", "evidence_request_sequence")] = "2"
    monkeypatch.setattr(
        supervisor,
        "_fresh_active_snapshot_after",
        lambda _generation: contradictory,
    )
    with pytest.raises(ValueError, match="contradictory request identity"):
        supervisor._confirm_evidence_acknowledgement(acknowledgement)


def test_phase_degradation_stops_as_active_hybrid_nonpass(
    tmp_path: Path, monkeypatch
) -> None:
    supervisor = _supervisor(tmp_path)
    commands: list[str] = []
    supervisor.emergency_command_fifo = None
    monkeypatch.setattr(supervisor, "_command", commands.append)
    health = _health(
        supervisor,
        hybrid_state="PHASE_DEGRADED_FREQUENCY_ONLY",
        hybrid_reason="phase_step_detected",
    )

    supervisor._maybe_finish(health, 1_800_000_000.0, 0.0)

    assert commands == ["ACTIVE ABORT"]
    assert supervisor.state["terminal"]["primary_decision"] == (
        "phase_channel_degraded_frequency_control_retained"
    )


def test_qualified_endpoint_requires_clear_static_terminal(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    origin = 1_800_000_000.0
    supervisor.state["qualification_started_utc"] = _utc(origin)
    supervisor.state["qualified_origin_timestamp_ticks"] = (
        4000 * live.RP2040_TIMER0_TICKS_PER_SECOND
    )
    supervisor.state["qualified_origin_session_id"] = 1
    health = _health(
        supervisor,
        uptime_s=str(4000 + live.QUALIFIED_DURATION_S),
        hybrid_state="HYBRID_TRACKING",
        first_phase_checkpoint_passed="true",
        phase_nonzero_application_count="2",
        phase_material_application_count="2",
        correction_count="2",
        cumulative_movement_codes="8",
    )

    supervisor._maybe_finish(health, origin + live.QUALIFIED_DURATION_S, 0.0)

    assert supervisor.state["terminal"] == {
        "result": "healthy_stop",
        "reason": "cx320_12h_qualified_endpoint_complete",
        "preliminary_decision": "pending_offline_scientific_analysis",
        "last_confirmed_code": live.SETUP_CODE,
        "utc": supervisor.state["terminal"]["utc"],
    }


def test_qualified_boundaries_use_device_time_despite_host_utc_steps(
    tmp_path: Path,
) -> None:
    origin_utc = 1_800_000_000.0
    origin_uptime_s = 4_000
    supervisor = _supervisor(tmp_path, wall_origin_epoch=origin_utc)
    supervisor.state["qualification_started_utc"] = _utc(origin_utc)
    supervisor.state["qualified_origin_timestamp_ticks"] = (
        origin_uptime_s * live.RP2040_TIMER0_TICKS_PER_SECOND
    )
    supervisor.state["qualified_origin_session_id"] = 1
    supervisor._save()

    before_admission_close = _health(
        supervisor,
        uptime_s=str(
            origin_uptime_s
            + live.QUALIFIED_DURATION_S
            - live.CORRECTION_RESPONSE_RESERVE_S
            - 1
        ),
    )
    assert not supervisor._close_response_horizon_if_required(
        before_admission_close
    )
    at_admission_close = _health(
        supervisor,
        uptime_s=str(
            origin_uptime_s
            + live.QUALIFIED_DURATION_S
            - live.CORRECTION_RESPONSE_RESERVE_S
        ),
    )
    assert supervisor._close_response_horizon_if_required(at_admission_close)

    before_endpoint = _health(
        supervisor,
        uptime_s=str(origin_uptime_s + live.QUALIFIED_DURATION_S - 1),
        hybrid_state="HYBRID_TRACKING",
        first_phase_checkpoint_passed="true",
        phase_nonzero_application_count="2",
        phase_material_application_count="2",
        correction_count="2",
        cumulative_movement_codes="8",
    )
    # A 50,000-second forward UTC step is still inside the independent 16-hour
    # wall endpoint but must not complete 43,200 seconds of device support.
    supervisor._maybe_finish(before_endpoint, origin_utc + 50_000, 0.0)
    assert supervisor.state["terminal"] is None

    at_endpoint = dict(before_endpoint)
    at_endpoint[("cx317_active", "uptime_s")] = str(
        origin_uptime_s + live.QUALIFIED_DURATION_S
    )
    # A backward UTC step must likewise not delay the device-domain endpoint.
    supervisor._maybe_finish(at_endpoint, origin_utc - 1_000, 0.0)
    assert supervisor.state["terminal"]["reason"] == (
        "cx320_12h_qualified_endpoint_complete"
    )


def test_qualified_clock_rejects_capture_session_change(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    supervisor.state["qualified_origin_timestamp_ticks"] = (
        4000 * live.RP2040_TIMER0_TICKS_PER_SECOND
    )
    supervisor.state["qualified_origin_session_id"] = 1

    with pytest.raises(ValueError, match="capture session changed"):
        supervisor._qualified_elapsed_ticks(
            _health(supervisor, session_id="2", uptime_s="5000")
        )


def test_wall_endpoint_is_right_censored_nonpass_when_static(tmp_path: Path) -> None:
    origin = 1_800_000_000.0
    supervisor = _supervisor(tmp_path, wall_origin_epoch=origin)

    supervisor._maybe_finish(
        _health(supervisor), origin + live.ABSOLUTE_WALL_LIMIT_S, 0.0
    )

    assert supervisor.state["terminal"]["result"] == "nonpass"
    assert supervisor.state["terminal"]["primary_decision"] == (
        "right_censored_incomplete"
    )
    assert supervisor.state["terminal"]["last_confirmed_code"] == live.SETUP_CODE


def test_independent_abort_uses_emergency_path_and_classifies_operator_abort(
    tmp_path: Path, monkeypatch
) -> None:
    supervisor = _supervisor(tmp_path)
    submitted: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        live,
        "send_command_to_fifo",
        lambda path, command: submitted.append((path, command)),
        raising=False,
    )
    # ActiveTransactionSupervisor resolves the sender in its defining module.
    monkeypatch.setattr(
        "host.otis_tools.active_transactions.send_command_to_fifo",
        lambda path, command: submitted.append((path, command)),
    )

    supervisor._abort("independent_host_abort_fifo")

    assert submitted == [(supervisor.emergency_command_fifo, "ACTIVE ABORT")]
    assert supervisor.state["terminal"]["result"] == "aborted"
    assert supervisor.state["terminal"]["primary_decision"] == "operator_abort"
