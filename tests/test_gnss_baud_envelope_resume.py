from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from host.otis_tools.gnss_baud_envelope_analyze import (
    RESUME_ANALYSIS_TYPE,
    RESUME_COMPLETION_TERMINAL,
    analyze_events,
)
from host.otis_tools.gnss_baud_envelope_supervisor import CampaignSupervisor, load_contract, read_events


CONTRACT = Path(
    "profiles/qualification/otis_gnss_baud_envelope_characterization_resume_v1.json"
)


def test_resume_runs_only_full_s10_soak_and_s11(tmp_path: Path) -> None:
    contract = load_contract(CONTRACT)
    events_path = tmp_path / "events.jsonl"
    run_id = "live_resume_fixture"
    supervisor = CampaignSupervisor(
        contract,
        run_id=run_id,
        initial_state={
            "programme_id": contract["programme_id"],
            "profile_id": contract["firmware_profile"]["profile_id"],
            "confirmed_baud": 115200,
            "baud_epoch": 1,
            "identity_confirmed": True,
            "configuration_confirmed": True,
            "fresh_rmc": True,
            "fresh_gga": True,
            "fresh_two_gsa": True,
            "snapshot_generation": 1,
            "startup_discovery": {"outcome": "hint_confirmed"},
        },
        event_path=events_path,
    )
    host_ticks = 0
    online_ticks = 0
    counter = 100
    while supervisor.current_segment is not None:
        request = supervisor.next_transition_request(timestamp_ticks=host_ticks)
        same_target = request["transition_mode"] == "same_target_session_bind"
        supervisor.accept_transition(
            {
                **request,
                "status": "confirmed",
                "confirmed_baud": request["target_baud"],
                "baud_epoch": supervisor.baud_epoch if same_target else supervisor.baud_epoch + 1,
                "identity_confirmed": True,
                "configuration_confirmed": True,
                "fresh_rmc": True,
                "fresh_gga": True,
                "fresh_two_gsa": True,
                "first_dependent_snapshot_bound": True,
                "completed_within_deadline": True,
                "transition_milestones": {
                    "acceptance": {"within_deadline": True, "observed_host_elapsed_ns": 0},
                    "physical_transmit": (
                        {"complete": False, "not_applicable_reason": "same_target_session_binding_no_pmtk251", "firmware_elapsed_ms": 0}
                        if same_target else {"complete": True, "firmware_elapsed_ms": 1}
                    ),
                    "target_confirmation": {"identity_confirmed": True, "output_confirmed": True, "identity_elapsed_ms": 1, "output_elapsed_ms": 1},
                    "terminal": {"state": "complete", "transition_complete_elapsed_ms": 2},
                },
            },
            timestamp_ticks=host_ticks + 1,
        )
        phase = supervisor.current_phase
        assert phase is not None
        supervisor.start_phase(
            timestamp_ticks=host_ticks + 2,
            online_counter_ticks=online_ticks,
            online_counter_domain="rp2040_timer0_extended",
            counters={"bytes_observed": counter},
            metrics={"identity_exact": True},
        )
        duration_ticks = phase.duration_s * 16_000_000
        counter += 100
        host_ticks += phase.duration_s * 1_000_000_000
        supervisor.complete_phase(
            timestamp_ticks=host_ticks,
            online_counter_ticks=online_ticks + duration_ticks,
            counters={"bytes_observed": counter},
            metrics={"identity_exact": True, "configuration_exact": True, "uart_isr_drain_complete_observed": True, "ring_capacity_entries": 1024, "ring_high_water": 8},
        )
        online_ticks += duration_ticks
    supervisor.finish(
        timestamp_ticks=host_ticks + 1,
        final_state_evidence={
            "confirmed_baud": 9600,
            "identity_confirmed": True,
            "configuration_confirmed": True,
            "fresh_rmc": True,
            "fresh_gga": True,
            "fresh_two_gsa": True,
            "snapshot_generation": 10,
            "metadata_frontier": 10,
        },
    )
    events = read_events(events_path)
    contract_hash = sha256(CONTRACT.read_bytes()).hexdigest()
    source = {
        "source_run_id": run_id,
        "source_artifact_sha256": sha256(events_path.read_bytes()).hexdigest(),
        "source_contract_sha256": contract_hash,
        "source_firmware_uf2_sha256": "1" * 64,
        "source_firmware_source_sha256": "2" * 64,
        "source_firmware_config_sha256": "3" * 64,
        "original_contract_sha256": contract["prefix_validation"]["root_original_contract_file_sha256"],
        "continuation_contract_sha256": contract["prefix_validation"]["continuation_contract_file_sha256"],
        "resume_contract_sha256": contract_hash,
        "counter_domain": "rp2040_timer0_extended",
        "source_counter_baseline_id": f"{run_id}:capture-baseline:1",
    }
    source["counter_baseline_provenance"] = {
        key: source[key]
        for key in ("source_run_id", "source_artifact_sha256", "source_contract_sha256", "counter_domain", "source_counter_baseline_id")
    }
    gap = {
        "predecessor_run_id": "live_20260827T092556Z",
        "resume_run_id": run_id,
        "capture_continuity": False,
        "firmware_continuity": False,
        "counter_baseline_continuity": False,
        "cross_run_counter_delta_permitted": False,
    }
    result = analyze_events(contract=contract, events=events, source_provenance=source, source_gap=gap)
    assert result["analysis_type"] == RESUME_ANALYSIS_TYPE
    assert result["completion_terminal"] == RESUME_COMPLETION_TERMINAL
    assert result["evidence_status"] == "passed"
    assert [(row["logical_segment_id"], row["phase_id"]) for row in result["phases"]] == [
        ("S10", "ordinary_soak"),
        ("S11", "closing_clean_soak"),
    ]
    assert result["resume_schedule"]["required_confirmed_online_seconds"] == 24600
