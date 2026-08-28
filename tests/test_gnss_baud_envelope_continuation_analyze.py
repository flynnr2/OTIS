from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from host.otis_tools.gnss_baud_envelope_analyze import (
    CONTINUATION_ANALYSIS_TYPE,
    CONTINUATION_COMPLETION_TERMINAL,
    analyze_events,
)
from host.otis_tools.gnss_baud_envelope_supervisor import (
    CampaignSupervisor,
    load_contract,
    read_events,
)


CONTINUATION_CONTRACT = Path(
    "profiles/qualification/otis_gnss_baud_envelope_characterization_continuation_v1.json"
)
FULL_CONTRACT = Path(
    "profiles/qualification/otis_gnss_baud_envelope_characterization_v1.json"
)


def _challenge(sequence: int, sent_ticks: int) -> dict[str, int | str]:
    completed = sent_ticks + 1_000_000
    return {
        "challenge_sequence": sequence,
        "sent_ticks": sent_ticks,
        "completed_ticks": completed,
        "host_drained_ticks": completed,
        "timestamp_domain": "host_monotonic_ns",
        "response_bytes": 64,
        "response_duration_ns": 1_000_000,
        "response_start_status_sequence": sequence * 10,
        "response_end_status_sequence": sequence * 10 + 2,
        "response_snapshot_generation": sequence * 2 - 1,
        "completed_peak_snapshot_generation": sequence * 2,
        "completed_peak_end_status_sequence": sequence * 10 + 4,
        "completed_peak_challenge_sequence": sequence,
    }


def _continuation_fixture(tmp_path: Path) -> tuple[dict, list[dict], dict, dict]:
    contract = load_contract(CONTINUATION_CONTRACT)
    events_path = tmp_path / "continuation_events.jsonl"
    run_id = "live_continuation_fixture"
    supervisor = CampaignSupervisor(
        contract,
        run_id=run_id,
        initial_state={
            "programme_id": "OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1",
            "profile_id": contract["firmware_profile"]["profile_id"],
            "confirmed_baud": 57600,
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
    challenge_sequence = 1
    while supervisor.current_segment is not None:
        request = supervisor.next_transition_request(timestamp_ticks=host_ticks)
        same_target = request["transition_mode"] == "same_target_session_bind"
        target_epoch = (
            supervisor.baud_epoch if same_target else supervisor.baud_epoch + 1
        )
        supervisor.accept_transition(
            {
                **request,
                "status": "confirmed",
                "confirmed_baud": request["target_baud"],
                "baud_epoch": target_epoch,
                "identity_confirmed": True,
                "configuration_confirmed": True,
                "fresh_rmc": True,
                "fresh_gga": True,
                "fresh_two_gsa": True,
                "first_dependent_snapshot_bound": True,
                "completed_within_deadline": True,
                "transition_milestones": {
                    "acceptance": {
                        "within_deadline": True,
                        "observed_host_elapsed_ns": 0,
                    },
                    "physical_transmit": (
                        {
                            "complete": False,
                            "not_applicable_reason": (
                                "same_target_session_binding_no_pmtk251"
                            ),
                            "firmware_elapsed_ms": 0,
                        }
                        if same_target
                        else {"complete": True, "firmware_elapsed_ms": 1}
                    ),
                    "target_confirmation": {
                        "identity_confirmed": True,
                        "output_confirmed": True,
                        "identity_elapsed_ms": 1,
                        "output_elapsed_ms": 1,
                    },
                    "terminal": {
                        "state": "complete",
                        "transition_complete_elapsed_ms": 2,
                    },
                },
            },
            timestamp_ticks=host_ticks + 1,
        )
        active_segment_id = request["segment_id"]
        while (
            supervisor.current_segment is not None
            and supervisor.current_segment.segment_id == active_segment_id
            and supervisor.current_phase is not None
        ):
            phase = supervisor.current_phase
            assert phase is not None
            phase_start_host_ticks = host_ticks + 2
            supervisor.start_phase(
                timestamp_ticks=phase_start_host_ticks,
                online_counter_ticks=online_ticks,
                online_counter_domain="rp2040_timer0_extended",
                counters={"bytes_observed": counter},
                metrics={"identity_exact": True},
            )
            required_online_ticks = phase.duration_s * 16_000_000
            phase_end_host_ticks = (
                phase_start_host_ticks + phase.duration_s * 1_000_000_000
            )
            challenges = []
            if phase.kind == "peak_status":
                challenges = [
                    _challenge(
                        challenge_sequence + offset,
                        phase_start_host_ticks + offset * 1_000_000_000,
                    )
                    for offset in range(phase.duration_s)
                ]
                challenge_sequence += phase.duration_s
            counter += 100
            supervisor.complete_phase(
                timestamp_ticks=phase_end_host_ticks,
                online_counter_ticks=online_ticks + required_online_ticks,
                counters={"bytes_observed": counter},
                metrics={
                    "identity_exact": True,
                    "configuration_exact": True,
                    "uart_isr_drain_complete_observed": True,
                    "ring_capacity_entries": 1024,
                    "ring_high_water": 8,
                },
                status_challenges=challenges,
            )
            online_ticks += required_online_ticks
            host_ticks = phase_end_host_ticks
    supervisor.finish(
        timestamp_ticks=host_ticks + 1,
        final_state_evidence={
            "confirmed_baud": 9600,
            "identity_confirmed": True,
            "configuration_confirmed": True,
            "fresh_rmc": True,
            "fresh_gga": True,
            "fresh_two_gsa": True,
            "snapshot_generation": 100,
            "metadata_frontier": 1000,
        },
    )
    events = read_events(events_path)
    contract_file_sha256 = sha256(CONTINUATION_CONTRACT.read_bytes()).hexdigest()
    source = {
        "source_run_id": run_id,
        "source_artifact_sha256": sha256(events_path.read_bytes()).hexdigest(),
        "source_contract_sha256": contract_file_sha256,
        "source_firmware_uf2_sha256": "3" * 64,
        "source_firmware_source_sha256": "4" * 64,
        "source_firmware_config_sha256": "5" * 64,
        "original_contract_sha256": contract["prefix_validation"][
            "original_contract_file_sha256"
        ],
        "continuation_contract_sha256": contract_file_sha256,
        "counter_domain": "rp2040_timer0_extended",
        "source_counter_baseline_id": f"{run_id}:capture-baseline:1",
    }
    source["counter_baseline_provenance"] = {
        key: source[key]
        for key in (
            "source_run_id",
            "source_artifact_sha256",
            "source_contract_sha256",
            "counter_domain",
            "source_counter_baseline_id",
        )
    }
    gap = {
        "historical_run_id": contract["prefix_validation"]["source_run_id"],
        "continuation_run_id": run_id,
        "capture_continuity": False,
        "firmware_continuity": False,
        "counter_baseline_continuity": False,
        "cross_run_counter_delta_permitted": False,
    }
    return contract, events, source, gap


def test_continuation_analysis_is_distinct_source_local_and_composite_ready(
    tmp_path: Path,
) -> None:
    contract, events, source, gap = _continuation_fixture(tmp_path)

    result = analyze_events(
        contract=contract,
        events=events,
        source_provenance=source,
        source_gap=gap,
    )

    assert result["analysis_type"] == CONTINUATION_ANALYSIS_TYPE
    assert result["completion_terminal"] == CONTINUATION_COMPLETION_TERMINAL
    assert result["source_programme_terminal"] == (
        "multi_baud_characterization_continuation_complete"
    )
    assert result["programme_terminal"] is None
    assert result["evidence_status"] == "passed"
    assert result["cross_run_counter_delta_attempted"] is False
    assert result["final_confirmed_9600"] is True
    assert result["source_gap"] == gap
    assert result["source"] == {
        key: value for key, value in source.items() if key != "counter_baseline_provenance"
    }
    assert result["continuation_schedule"] == {
        "local_segment_count": 6,
        "logical_segment_range": ["S06", "S11"],
        "completed_phase_count": 15,
        "required_confirmed_online_seconds": 35_700,
        "observed_confirmed_online_seconds": 35_700,
    }
    assert len(result["segments"]) == 6
    assert len(result["phases"]) == 15
    assert [phase["logical_segment_id"] for phase in result["phases"][:2]] == [
        "S06",
        "S06",
    ]
    assert result["phases"][-1]["logical_segment_id"] == "S11"
    assert all(phase["source"] == result["source"] for phase in result["phases"])
    assert all(segment["source"] == result["source"] for segment in result["segments"])
    assert all(
        phase["counter_delta_scope"]["source_run_id"]
        == result["source"]["source_run_id"]
        and phase["counter_delta_scope"]["source_counter_baseline_id"]
        == result["source"]["source_counter_baseline_id"]
        for phase in result["phases"]
    )


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_continuation_mapping_must_be_exact(
    tmp_path: Path, mutation: str
) -> None:
    contract, events, source, gap = _continuation_fixture(tmp_path)
    mapping = contract["continuation"]["local_to_logical_segment_map"]
    if mutation == "missing":
        mapping.pop()
    else:
        mapping[-1] = deepcopy(mapping[-2])
    with pytest.raises(ValueError, match="local-to-logical mapping differs"):
        analyze_events(
            contract=contract,
            events=events,
            source_provenance=source,
            source_gap=gap,
        )


def test_wrong_logical_phase_identity_fails_analysis(tmp_path: Path) -> None:
    contract, events, source, gap = _continuation_fixture(tmp_path)
    phase = next(event for event in events if event["event"] == "phase_completed")
    phase["logical_segment_id"] = "S11"
    result = analyze_events(
        contract=contract,
        events=events,
        source_provenance=source,
        source_gap=gap,
    )
    assert result["evidence_status"] == "failed"
    assert result["completion_terminal"] is None
    assert any(
        "continuation phase completion mapping differs" in failure
        for failure in result["validation_failures"]
    )


def test_counter_baseline_source_mismatch_is_rejected(tmp_path: Path) -> None:
    contract, events, source, gap = _continuation_fixture(tmp_path)
    source["counter_baseline_provenance"]["source_run_id"] = "another-run"
    with pytest.raises(ValueError, match="counter baseline/source provenance"):
        analyze_events(
            contract=contract,
            events=events,
            source_provenance=source,
            source_gap=gap,
        )


def test_non9600_continuation_final_state_fails_analysis(tmp_path: Path) -> None:
    contract, events, source, gap = _continuation_fixture(tmp_path)
    terminal = events[-1]
    assert terminal["event"] == "programme_terminal"
    terminal["last_confirmed_baud"] = 57600
    result = analyze_events(
        contract=contract,
        events=events,
        source_provenance=source,
        source_gap=gap,
    )
    assert result["evidence_status"] == "failed"
    assert result["final_confirmed_9600"] is False
    assert result["completion_terminal"] is None


def test_full_programme_public_analysis_api_remains_source_argument_free() -> None:
    result = analyze_events(contract=load_contract(FULL_CONTRACT), events=[])
    assert result["analysis_type"] == "otis_gnss_baud_envelope_analysis_v1"
    assert result["evidence_status"] == "failed"
    assert "completion_terminal" not in result
