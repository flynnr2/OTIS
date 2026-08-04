from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from host.otis_tools.cx317_stage7_analyze import (
    _historical_shadow_replays,
    _latest_health_rows,
    _series_metrics,
)
from host.otis_tools.cx317_stage7_manifest import create_stage7_manifest
from host.otis_tools.cx317_stage7_shadow import CONTRACT_SHA256
from host.otis_tools.cx317_stage7_shadow_monitor import (
    AUTHORITATIVE,
    SHADOW,
    refresh,
)
from host.otis_tools.cx317_stage7_supervisor import (
    PART_B_DURATION_S,
    Stage7Supervisor,
    _next_selected_interval_is_cadence_eligible,
    load_stage7_spec,
)
from host.otis_tools.run_loader import CAPTURE_IN_PROGRESS_FLAG


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_stage7_specs_freeze_part_a_and_endurance_budgets() -> None:
    part_a, identities_a = load_stage7_spec("part_a", 0xA82A)
    part_b, identities_b = load_stage7_spec("part_b", 0xA815)

    assert part_a.profile == "cx317_dual_core_active_part_a"
    assert part_a.run_identity == "cx317_stage7_part_a:3170003"
    assert (part_a.correction_limit, part_a.cumulative_limit) == (4, 84)
    assert part_b.profile == "cx317_dual_core_active_endurance_part_b"
    assert part_b.run_identity == "cx317_stage7_part_b:3170004"
    assert part_b.start_code == 0xA815
    assert (part_b.correction_limit, part_b.cumulative_limit) == (32, 672)
    assert identities_a == identities_b
    assert PART_B_DURATION_S == 86400


def test_shadow_monitor_preserves_context_and_exactly_replays(tmp_path: Path) -> None:
    run = tmp_path / "run"
    (run / "csv").mkdir(parents=True)
    (run / "reports").mkdir()
    (run / CAPTURE_IN_PROGRESS_FLAG).write_text("test\n", encoding="utf-8")
    (run / "csv/estimates_v2.csv").write_text(
        "record_type,estimator_version,config_hash,observation_validity,"
        "reference_validity,count_validity,diagnostic_health,preview_eligibility,"
        "frequency_error_hz,estimate_id,estimate_seq,estimator_timestamp_ticks,"
        "source_reference_first_seq,source_reference_last_seq\n"
        "EST,cx317_selected_600s_nonoverlap_v1,"
        "5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c,"
        "valid,valid,valid,healthy,true,-0.005000000820,"
        "est:cx317:selected600:000001,1,9600000000,1,600\n",
        encoding="utf-8",
    )
    (run / "csv/active_transactions_v1.csv").write_text("event\n", encoding="utf-8")
    (run / "csv/environment.csv").write_text(
        "env_seq,temperature_c,relative_humidity_pct,pressure_pa\n"
        "600,30.5,42.0,\n",
        encoding="utf-8",
    )
    (run / "csv/health.csv").write_text(
        "record_type,component,status_key,status_value\n"
        "STS,gnss_receiver,control_eligible,true\n"
        "STS,dual_core,service_to_timing_depth,0\n"
        "STS,dual_core,service_to_timing_high_water,2\n"
        "STS,dual_core,observation_depth,0\n"
        "STS,dual_core,observation_high_water,3\n"
        "STS,dual_core,critical_depth,0\n"
        "STS,dual_core,critical_high_water,2\n"
        "STS,dual_core,evidence_depth,0\n"
        "STS,dual_core,evidence_high_water,1\n"
        "STS,dual_core,telemetry_depth,0\n"
        "STS,dual_core,telemetry_high_water,4\n"
        "STS,dual_core,telemetry_dropped,0\n",
        encoding="utf-8",
    )
    (run / "reports/cx317_active_supervisor_state.json").write_text(
        json.dumps(
            {
                "stage7_part": "part_b",
                "part_b_service_burst_index": None,
            }
        ),
        encoding="utf-8",
    )

    assert refresh(run, part="part_b", start_code=0xA82A) == (1, 5)
    assert refresh(run, part="part_b", start_code=0xA82A) == (1, 5)
    authoritative = _rows(run / AUTHORITATIVE)
    shadow = _rows(run / SHADOW)
    assert len(authoritative) == 1
    assert authoritative[0]["actual_applied_code"] == str(0xA82A)
    assert authoritative[0]["authoritative_deadband_state"] == "inside"
    assert authoritative[0]["gnss_qualification"] == "qualified"
    assert authoritative[0]["shadow_contract_sha256"] == CONTRACT_SHA256
    assert authoritative[0]["preserved_while_capture_active"] == "true"
    assert len(shadow) == 5
    assert {row["estimate_id"] for row in shadow} == {
        "est:cx317:selected600:000001"
    }
    assert all(row["actionable"] == "false" for row in shadow)
    assert all(row["actuation_authorized"] == "false" for row in shadow)
    assert all(row["authorization_consumed"] == "false" for row in shadow)


def test_stage7_supervisor_declares_four_host_evidence_releases() -> None:
    source = Path(
        "host/otis_tools/cx317_stage7_supervisor.py"
    ).read_text(encoding="utf-8")
    assert '"request_created": 1' in source
    assert '"core0_accepted": 2' in source
    assert '"application": 3' in source
    assert '"response": 4' in source
    assert "PART_A_SERVICE_LOAD_QUERIES = 60" in source
    assert "PART_B_DURATION_S = 24 * 60 * 60" in source
    assert 'self.state["response_count"] >= 1' in source
    assert '"part_a_post_service_eligible_control_seq"' in source
    assert "inside_deadband" not in source[source.index("def _process_transactions") : source.index("def _maybe_qualify")]


def test_stage7_manifest_binds_clean_part_a_artifact(tmp_path: Path) -> None:
    build = {
        "provenance": {
            "source": {
                "git_commit": "1" * 40,
                "sha256": "2" * 64,
                "state": "clean",
            },
            "configuration": {
                "profile_id": "cx317_dual_core_active_part_a",
                "sha256": "3" * 64,
                "defines": {
                    "OTIS_CX317_ACTIVE_START_CODE": "0xA82Au",
                    "OTIS_CX317_ACTIVE_CORRECTION_LIMIT": "4u",
                    "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES": "84u",
                    "OTIS_ENABLE_DUAL_CORE_PARTITION": "1",
                    "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "1",
                    "OTIS_GNSS_UART_TX_ENABLED": "0",
                },
            },
        },
        "artifacts": [
            {
                "name": "otis_nano_rp2040_connect.ino.uf2",
                "sha256": "4" * 64,
                "size_bytes": 123456,
            }
        ],
    }
    build_manifest = tmp_path / "firmware_build_manifest.json"
    build_manifest.write_text(
        json.dumps(build, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    run = tmp_path / "stage7_part_a"
    manifest_path = create_stage7_manifest(
        part="part_a",
        start_code=0xA82A,
        run_dir=run,
        build_manifest_path=build_manifest,
        serial_device="/dev/cu.test",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["stage"] == "CX317_DUAL_CORE_ACTIVE_PART_A"
    assert manifest["firmware"]["profile_id"] == "cx317_dual_core_active_part_a"
    assert manifest["active_campaign"]["authoritative_deadband_hz"] == (
        0.006249995628992717
    )
    assert manifest["shadow_contract"]["sha256"] == CONTRACT_SHA256
    assert manifest["host"]["shadow_has_serial_or_command_authority"] is False


def test_stage7_time_series_metrics_do_not_assume_independence() -> None:
    rows = [
        {"frequency_error_hz": str(value), "timestamp_s": str(index * 600)}
        for index, value in enumerate(
            (-0.005, -0.004, -0.003, 0.007, 0.006, 0.005), 1
        )
    ]
    metrics = _series_metrics(rows)
    assert metrics["count"] == 6
    assert metrics["newey_west_lag"] == 3
    assert metrics["successive_estimates_assumed_independent"] is False
    assert 0 < metrics["effective_sample_size_initial_positive_acf"] <= 6
    assert metrics["authoritative_boundary_crossings"] == 2


def test_stage7_analyzer_uses_run_manifest_validation_sets() -> None:
    source = Path("host/otis_tools/cx317_stage7_analyze.py").read_text(
        encoding="utf-8"
    )
    assert "manifest.known_channels" in source
    assert "manifest.known_domains" in source
    assert '"rp2040_timer0" in manifest.known_domains' in source
    assert "manifest.channels" not in source
    assert "manifest.domains" not in source


def test_stage7_analyzer_reduces_loaded_health_rows() -> None:
    latest = _latest_health_rows(
        [
            {
                "record_type": "STS",
                "component": "dual_core",
                "status_key": "telemetry_dropped",
                "status_value": "0",
            },
            {
                "record_type": "STS",
                "component": "dual_core",
                "status_key": "telemetry_dropped",
                "status_value": "7",
            },
        ]
    )
    assert latest[("dual_core", "telemetry_dropped")] == "7"


def _supervisor(tmp_path: Path) -> Stage7Supervisor:
    run = tmp_path / "run"
    (run / "csv").mkdir(parents=True)
    spec, identities = load_stage7_spec("part_a", 0xA82A)
    return Stage7Supervisor(
        part="part_a",
        run_dir=run,
        command_fifo=tmp_path / "command.fifo",
        abort_fifo=tmp_path / "abort.fifo",
        spec=spec,
        identities=identities,
        expected_build_identity="a" * 64 + ":" + "b" * 64,
        allow_manual_start=True,
        allow_arm=True,
        duration_s=None,
    )


def test_part_a_waits_for_eligible_decision_after_service_interval(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path)
    supervisor.state.update(
        {
            "response_count": 1,
            "part_a_service_load_complete": True,
            "part_a_service_load_completed_control_seq": 10,
            "part_a_post_service_eligible_control_seq": None,
            "arm_pending": False,
        }
    )
    controls = supervisor.run_dir / "csv/control_previews_v1.csv"
    controls.write_text(
        "control_seq,preview_available,model_applicability,diagnostic_health,"
        "limited_delta_codes\n"
        "10,true,applicable,healthy,0\n",
        encoding="utf-8",
    )
    health = {
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "evidence_phase"): "evidence_clear",
    }
    supervisor._maybe_finish(health, 0.0)
    assert supervisor.state["terminal"] is None

    with controls.open("a", encoding="utf-8") as handle:
        handle.write("11,true,applicable,healthy,0\n")
    supervisor._maybe_finish(health, 0.0)
    assert supervisor.state["terminal"]["result"] == "healthy_stop"
    assert supervisor.state["part_a_post_service_eligible_control_seq"] == 11


def test_stage7_supervisor_stops_on_partition_or_transport_loss(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path)
    with pytest.raises(ValueError, match="partition fault"):
        supervisor._check_fail_static_health(
            {("dual_core", "partition_fault"): "evidence_queue_exhausted"}
        )
    with pytest.raises(ValueError, match="telemetry_dropped"):
        supervisor._check_fail_static_health(
            {
                ("dual_core", "partition_fault"): "none",
                ("dual_core", "telemetry_dropped"): "1",
            }
        )


def test_stage7_arms_only_for_the_next_cadence_eligible_interval(
    tmp_path: Path,
) -> None:
    controls = tmp_path / "control_previews_v1.csv"
    estimates = tmp_path / "estimates_v2.csv"
    header = (
        "decision_timestamp_ticks,preview_available,decision_reason_code,"
        "est_input_ref\n"
    )
    controls.write_text(header, encoding="utf-8")
    estimates.write_text(
        "estimate_id,source_count_seq\n"
        "est:0,1799\n"
        "est:1,2399\n"
        "est:2,2999\n"
        "est:3,3599\n",
        encoding="utf-8",
    )
    assert not _next_selected_interval_is_cadence_eligible(
        controls, estimates
    )

    with controls.open("a", encoding="utf-8") as handle:
        handle.write("28827892112,false,fresh_estimator_support,est:0\n")
    assert _next_selected_interval_is_cadence_eligible(controls, estimates)

    with controls.open("a", encoding="utf-8") as handle:
        handle.write("38427843600,true,inside_evidence_deadband,est:1\n")
    assert not _next_selected_interval_is_cadence_eligible(
        controls, estimates
    )

    with controls.open("a", encoding="utf-8") as handle:
        handle.write("48027796864,false,decision_cadence_hold,est:2\n")
    assert not _next_selected_interval_is_cadence_eligible(
        controls, estimates
    )

    with controls.open("a", encoding="utf-8") as handle:
        handle.write("57627748416,false,decision_cadence_hold,est:3\n")
    assert _next_selected_interval_is_cadence_eligible(controls, estimates)


def test_stage7_does_not_rearm_from_stale_high_progress_after_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor = _supervisor(tmp_path)
    controls = supervisor.run_dir / "csv/control_previews_v1.csv"
    estimates = supervisor.run_dir / "csv/estimates_v2.csv"
    controls.write_text(
        "decision_timestamp_ticks,preview_available,decision_reason_code,"
        "est_input_ref,decision_id,limited_delta_codes\n"
        "38427843600,true,inside_evidence_deadband,est:1,ctl:1,0\n"
        "48027796864,false,decision_cadence_hold,est:2,ctl:2,\n"
        "57627748416,false,decision_cadence_hold,est:3,ctl:3,\n",
        encoding="utf-8",
    )
    estimates.write_text(
        "estimate_id,source_count_seq\n"
        "est:1,2399\n"
        "est:2,2999\n"
        "est:3,3599\n",
        encoding="utf-8",
    )
    supervisor.state.update(
        {
            "arm_pending": False,
            "duration_elapsed": False,
            "manual_start_sent": True,
            "authorization_sequence": 1,
        }
    )
    commands: list[str] = []
    monkeypatch.setattr(supervisor, "_identity_ready", lambda health: True)
    monkeypatch.setattr(supervisor, "_command", commands.append)

    health = {
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "manual_start_confirmed"): "true",
        ("cx317_active", "correction_count"): "0",
        ("cx317_active", "arm_eligible"): "true",
        ("cx317_active", "evidence_phase"): "evidence_clear",
        ("cx317_active", "selected_interval_count"): "598",
        ("cx317_active", "uptime_s"): "3600",
    }

    # This is the exact V5 race: CTL3 is new but ACTIVE? still reports the
    # previous estimator epoch's high-water progress.  It must not arm.
    supervisor._maybe_start_or_arm(health)
    assert commands == []
    assert supervisor.state["authorization_sequence"] == 1

    # Observe the reset for the epoch after CTL3, then arm only once genuine
    # progress reaches the frozen threshold near CTL4.
    health[("cx317_active", "selected_interval_count")] = "0"
    supervisor._maybe_start_or_arm(health)
    assert commands == []
    health[("cx317_active", "selected_interval_count")] = "519"
    supervisor._maybe_start_or_arm(health)
    assert commands == []
    health[("cx317_active", "selected_interval_count")] = "520"
    health[("cx317_active", "uptime_s")] = "4120"
    supervisor._maybe_start_or_arm(health)
    assert len(commands) == 1
    assert commands[0].startswith("ACTIVE ARM 2 ")
    assert supervisor.state["arm_pending"] is True


def test_frozen_shadow_exactly_replays_sealed_campaign_a_and_b() -> None:
    check, replays = _historical_shadow_replays()
    assert check.passed
    assert set(replays) == {"campaign_a_v3", "campaign_b"}
    assert replays["campaign_a_v3"][
        "v2_baseline_exact_application_replay"
    ]
    assert replays["campaign_b"][
        "v2_baseline_exact_application_replay"
    ]
    for replay in replays.values():
        assert replay["authoritative_stage_exit_passed"]
        assert replay["v2_baseline_within_original_campaign_budget"]
        assert replay["every_counterfactual_decision_has_reason"]
        baseline = replay["candidate_metrics"]["v2_symmetric_baseline"]
        assert baseline["newey_west_lag"] == min(
            3, baseline["observations"] - 1
        )
        assert baseline["successive_estimates_assumed_independent"] is False
