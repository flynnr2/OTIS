from __future__ import annotations

from copy import deepcopy

import pytest

from host.otis_tools.gnss_baud_envelope_composite_analyze import (
    COMPOSITE_TERMINAL,
    CONTINUATION_PHASE_KEYS,
    HISTORICAL_PHASE_KEYS,
    analyze_composite,
)


ORIGINAL_CONTRACT = "1" * 64
CONTINUATION_CONTRACT = "2" * 64


def _source(
    *,
    run_id: str,
    artifact: str,
    contract: str,
    uf2: str,
    source: str,
    config: str,
    baseline: str,
) -> dict[str, str]:
    return {
        "source_run_id": run_id,
        "source_artifact_sha256": artifact,
        "source_contract_sha256": contract,
        "source_firmware_uf2_sha256": uf2,
        "source_firmware_source_sha256": source,
        "source_firmware_config_sha256": config,
        "original_contract_sha256": ORIGINAL_CONTRACT,
        "continuation_contract_sha256": CONTINUATION_CONTRACT,
        "counter_domain": "rp2040_timer0_extended",
        "source_counter_baseline_id": baseline,
    }


def _phase(segment_id: str, phase_id: str, source: dict[str, str]) -> dict:
    return {
        "logical_segment_id": segment_id,
        "phase_id": phase_id,
        "status": "completed",
        "source": deepcopy(source),
        "counter_delta_scope": {
            "operation": "within_source_closing_minus_opening",
            "source_run_id": source["source_run_id"],
            "source_artifact_sha256": source["source_artifact_sha256"],
            "source_contract_sha256": source["source_contract_sha256"],
            "source_counter_baseline_id": source[
                "source_counter_baseline_id"
            ],
            "counter_domain": source["counter_domain"],
        },
        "counter_deltas": {
            "bytes_observed": 400,
            "metadata_checksum_valid_count": 40,
            "hardware_overrun_count": 0,
        },
    }


def _reports() -> tuple[dict, dict]:
    historical_source = _source(
        run_id="live_historical",
        artifact="3" * 64,
        contract=ORIGINAL_CONTRACT,
        uf2="4" * 64,
        source="5" * 64,
        config="6" * 64,
        baseline="historical-capture-baseline-1",
    )
    continuation_source = _source(
        run_id="live_continuation",
        artifact="7" * 64,
        contract=CONTINUATION_CONTRACT,
        uf2="8" * 64,
        source="9" * 64,
        config="a" * 64,
        baseline="continuation-capture-baseline-1",
    )
    historical = {
        "report_type": (
            "otis_gnss_baud_envelope_validated_historical_prefix_v1"
        ),
        "validation_status": "validated_against_original_manifest_and_contract",
        "cross_run_counter_delta_attempted": False,
        "source": historical_source,
        "historical_terminal": {
            "evidence_status": "failed",
            "programme_terminal": "programme_invalid_due_to_platform_or_evidence_failure",
            "failure_reason": "retained_original_platform_failure",
        },
        "phases": [
            _phase(segment_id, phase_id, historical_source)
            for segment_id, phase_id in HISTORICAL_PHASE_KEYS
        ],
        "bridge": {
            "events": [
                {
                    "event_sequence": 26,
                    "event": "transition_requested",
                    "logical_segment_id": "S06",
                    "request_sequence": 6,
                    "source": deepcopy(historical_source),
                },
                {
                    "event_sequence": 27,
                    "event": "transition_confirmed",
                    "logical_segment_id": "S06",
                    "request_sequence": 6,
                    "confirmed_baud": 57600,
                    "identity_confirmed": True,
                    "configuration_confirmed": True,
                    "first_dependent_snapshot_bound": True,
                    "source": deepcopy(historical_source),
                },
            ]
        },
    }
    continuation = {
        "analysis_type": "otis_gnss_baud_envelope_continuation_analysis_v1",
        "evidence_status": "passed",
        "completion_terminal": "continuation_capture_complete",
        "programme_terminal": None,
        "cross_run_counter_delta_attempted": False,
        "source": continuation_source,
        "phases": [
            _phase(segment_id, phase_id, continuation_source)
            for segment_id, phase_id in CONTINUATION_PHASE_KEYS
        ],
        "source_gap": {
            "historical_run_id": historical_source["source_run_id"],
            "continuation_run_id": continuation_source["source_run_id"],
            "capture_continuity": False,
            "firmware_continuity": False,
            "counter_baseline_continuity": False,
            "cross_run_counter_delta_permitted": False,
        },
    }
    return historical, continuation


def test_two_source_composite_preserves_provenance_failure_and_gap() -> None:
    historical, continuation = _reports()

    result = analyze_composite(
        historical_prefix=historical,
        continuation_analysis=continuation,
    )

    assert result["evidence_status"] == "passed"
    assert result["terminal"] == COMPOSITE_TERMINAL
    assert result["ordinary_programme_completion_terminal_permitted"] is False
    assert result["historical_terminal"] == {
        **historical["historical_terminal"],
        "preservation": "preserved_failed_not_reinterpreted_as_success",
        "source_run_id": "live_historical",
    }
    assert [event["event_sequence"] for event in result["bridge"]["historical_events"]] == [
        26,
        27,
    ]
    assert result["bridge"]["capture_and_firmware_gap"] == continuation[
        "source_gap"
    ]
    assert result["counter_delta_policy"] == {
        "rule": "subtract_only_within_one_source_run_artifact_contract_and_counter_baseline",
        "cross_source_subtraction_permitted": False,
        "counter_deltas_aggregated_across_sources": False,
    }
    assert len(result["phases"]) == 21
    assert len(result["segments"]) == 11
    assert result["phase_analysis_mode"] == "stratified_by_firmware_identity"
    assert len(result["firmware_strata"]) == 2
    assert result["firmware_compatibility_proof"] == {
        "provided": False,
        "passed": False,
        "cross_firmware_join_permitted": False,
    }

    required_source_fields = {
        "source_run_id",
        "source_artifact_sha256",
        "source_contract_sha256",
        "source_firmware_uf2_sha256",
        "source_firmware_source_sha256",
        "source_firmware_config_sha256",
        "original_contract_sha256",
        "continuation_contract_sha256",
        "counter_domain",
        "source_counter_baseline_id",
    }
    assert all(required_source_fields == set(phase["source"]) for phase in result["phases"])
    assert all(
        required_source_fields == set(source)
        for segment in result["segments"]
        for source in segment["source_provenance"]
    )
    s06 = next(
        segment
        for segment in result["segments"]
        if segment["logical_segment_id"] == "S06"
    )
    assert [source["source_run_id"] for source in s06["source_provenance"]] == [
        "live_historical",
        "live_continuation",
    ]
    assert all(
        segment["counter_deltas_combined_across_sources"] is False
        for segment in result["segments"]
    )
    assert len(result["analysis_sha256"]) == 64


def test_missing_logical_phase_is_rejected() -> None:
    historical, continuation = _reports()
    continuation["phases"].pop()
    with pytest.raises(ValueError, match="logical phase set differs"):
        analyze_composite(
            historical_prefix=historical,
            continuation_analysis=continuation,
        )


def test_duplicate_logical_phase_is_rejected() -> None:
    historical, continuation = _reports()
    continuation["phases"].append(deepcopy(continuation["phases"][0]))
    with pytest.raises(ValueError, match="duplicate logical phase"):
        analyze_composite(
            historical_prefix=historical,
            continuation_analysis=continuation,
        )


@pytest.mark.parametrize("tamper", ["contract", "phase_source"])
def test_mixed_or_tampered_contract_and_source_are_rejected(tamper: str) -> None:
    historical, continuation = _reports()
    if tamper == "contract":
        continuation["source"]["original_contract_sha256"] = "b" * 64
    else:
        continuation["phases"][0]["source"]["source_run_id"] = "other-run"
    with pytest.raises(ValueError, match="contract lineage differs|source tag differs"):
        analyze_composite(
            historical_prefix=historical,
            continuation_analysis=continuation,
        )


def test_absent_bridge_event_is_rejected() -> None:
    historical, continuation = _reports()
    historical["bridge"]["events"].pop()
    with pytest.raises(ValueError, match="exact events 26 and 27"):
        analyze_composite(
            historical_prefix=historical,
            continuation_analysis=continuation,
        )


@pytest.mark.parametrize("location", ["report", "phase"])
def test_cross_run_delta_attempt_is_rejected(location: str) -> None:
    historical, continuation = _reports()
    if location == "report":
        continuation["cross_run_counter_delta_attempted"] = True
        match = "cross-run counter delta attempt"
    else:
        continuation["phases"][0]["counter_delta_scope"][
            "source_run_id"
        ] = "live_historical"
        match = "cross-source counter delta"
    with pytest.raises(ValueError, match=match):
        analyze_composite(
            historical_prefix=historical,
            continuation_analysis=continuation,
        )


def test_ordinary_programme_completion_terminal_is_rejected() -> None:
    historical, continuation = _reports()
    continuation["programme_terminal"] = "multi_baud_characterization_complete"
    with pytest.raises(ValueError, match="ordinary programme completion terminal"):
        analyze_composite(
            historical_prefix=historical,
            continuation_analysis=continuation,
        )
