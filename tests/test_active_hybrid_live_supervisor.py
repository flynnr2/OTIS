from __future__ import annotations

import csv
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from host.otis_tools import active_hybrid_live_supervisor as live
from host.otis_tools.prewrite_readiness_contract import PrewriteReadiness


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
    health = _health(
        supervisor,
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
