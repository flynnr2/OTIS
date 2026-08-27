from __future__ import annotations

import ast
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path

import pytest

import host.otis_tools.adaptive_steering_offline_study as study
from host.otis_tools.adaptive_steering_contract import (
    load_analysis_contract,
    validate_output_location,
)
from host.otis_tools.adaptive_steering_offline import IntervalSign
from host.otis_tools.adaptive_steering_offline_study import (
    DEFAULT_CONTRACT,
    Interval,
    SourceData,
    _build_intervals,
    _linear_fit,
    _persistence_observation,
    _raw_component_increments,
    _source_provenance_json,
    _unwrap_domain_ticks,
    _validated_selected_frequency_rows,
    environment_associations,
    phase_windows,
)


def _interval(sequence: int, ticks: int) -> Interval:
    return Interval(
        source_id="fixture",
        package_content_sha256="a" * 64,
        source_file_sha256="b" * 64,
        source_files_sha256_json="{}",
        session=1,
        count_sequence=sequence,
        opening_snapshot_sequence=sequence - 1,
        closing_snapshot_sequence=sequence,
        opening_reference_sequence=sequence - 1,
        closing_reference_sequence=sequence,
        opening_reference_timestamp_ticks=ticks - 1,
        closing_reference_timestamp_ticks=ticks,
        timer_domain="rp2040_timer0",
        capture_backend="pio_wait_cumulative_snapshot_dma_v1",
        counted_edges=10_000_000,
        edge_error_cycles=0,
        fractional_frequency=Fraction(0),
        measurement_qualified=True,
        measurement_exclusion_reason="",
        phase_available=True,
        phase_method="fixture_phase",
        phase_epoch="fixture_epoch",
        relative_phase_cycles=sequence,
        phase_exclusion_reason="",
        dac_epoch=1,
        applied_code=43000,
        settled_same_code=True,
        control_input_eligible=True,
        control_decision_eligible=None,
        control_decision_eligibility_state="unavailable",
        control_decision_eligibility_reason="fixture",
    )


def _source(intervals: list[Interval], environment: list[dict[str, str]]) -> SourceData:
    hashes = {
        name: str(index) * 64
        for index, name in enumerate(
            (
                "csv/raw_events.csv",
                "csv/pps_snapshots.csv",
                "csv/count_observations.csv",
                "csv/active_transactions_v1.csv",
                "csv/estimates_v2.csv",
                "csv/environment.csv",
            ),
            start=1,
        )
    }
    return SourceData(
        binding={
            "source_id": "fixture",
            "consumed_files": hashes,
            "package_identity": {"content_sha256": "a" * 64},
            "historical_identity": {"timer_domain": "rp2040_timer0"},
        },
        root=Path("/fixture"),
        manifest={},
        raw_events=[],
        counts=[],
        snapshots=[],
        estimates=[],
        phase=[],
        phase_outputs=[],
        decisions=[],
        transactions=[],
        environment=environment,
        intervals=intervals,
        applications=[],
    )


def test_frozen_contract_is_self_identifying_and_offline_only() -> None:
    contract = load_analysis_contract(DEFAULT_CONTRACT)

    assert contract["contract_sha256"] == (
        "b7525de381bbd6506978819a46ccdc280993c47aba2d1ab673a9e595b48e325f"
    )
    assert len(contract["sources"]) == 3
    assert contract["authority"]["offline_analysis"] is True
    assert contract["authority"]["completed_evidence_read_only"] is True
    assert all(
        contract["authority"][name] is False
        for name in (
            "serial_access",
            "live_process_access",
            "firmware_build",
            "firmware_edit",
            "firmware_flash",
            "dac_write",
            "control_arm",
            "physical_rehearsal",
            "live_acquisition",
        )
    )
    assert [
        item["candidate_id"]
        for item in contract["controller_comparison"]["candidates"]
    ] == [
        "cx322_unchanged",
        "cx322_tagged_debt_with_bounded_backcalculation",
        "cx322_tagged_debt_backcalculation_plus_same_sign_persistence",
    ]


def test_contract_rejects_semantic_digest_mismatch(tmp_path: Path) -> None:
    value = json.loads(DEFAULT_CONTRACT.read_text(encoding="utf-8"))
    value["normalization_v2"]["control_eligibility"][
        "gnss_metadata_freshness_limit_s"
    ] = 4
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="contract semantic identity differs"):
        load_analysis_contract(path)


def test_output_location_cannot_overlap_a_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(ValueError, match="below immutable source"):
        validate_output_location(source / "derived", [source])


def test_output_location_must_be_new_or_empty(tmp_path: Path) -> None:
    output = tmp_path / "derived"
    output.mkdir()
    (output / "existing").write_text("retained", encoding="utf-8")

    with pytest.raises(ValueError, match="must be new or empty"):
        validate_output_location(output, [])


def test_raw_component_allocation_preserves_full_combined_demand() -> None:
    row = {
        "raw_combined_delta_codes": "-6.009381560192",
        "combined_demand_hz": "-0.002083333607",
        "frequency_term_hz": "-0.001666666940",
    }

    fll, pll = _raw_component_increments(row)

    assert fll + pll == Fraction("-6.009381560192")
    assert fll < 0
    assert pll < 0


def test_persistence_uses_count_quantization_interval_not_display_value() -> None:
    row = {
        "accumulated_edge_error_counts": "0",
        "phase_term_hz": "-0.000416666667",
        "capture_session": "7",
        "phase_epoch": "phase-1",
        "current_applied_code": "43062",
        "dac_epoch": "2",
        "source_first_sequence": "7502",
        "source_last_sequence": "8102",
        "cadence_limited": "false",
    }

    observation = _persistence_observation(
        row,
        gain_minimum=Fraction("0.00016357422282453626"),
        gain_maximum=Fraction("0.00017334010044578463"),
    )

    assert observation.combined_demand.sign is IntervalSign.CONTAINS_ZERO


def test_modular_environment_join_preserves_role_and_wrap() -> None:
    modulus = (1 << 32) * 16
    source = _source(
        [_interval(1, modulus - 10), _interval(2, 10)],
        [
            {
                "env_seq": "1", "timestamp_ticks": str(modulus - 20),
                "observation_domain": "rp2040_timer0", "source": "sht4x",
                "role": "vcocxo_near", "temperature_c": "20",
                "relative_humidity_pct": "40", "pressure_pa": "", "flags": "0",
            },
            {
                "env_seq": "2", "timestamp_ticks": str(modulus - 19),
                "observation_domain": "rp2040_timer0", "source": "bmp280",
                "role": "pressure_reference", "temperature_c": "21",
                "relative_humidity_pct": "", "pressure_pa": "100000", "flags": "0",
            },
            {
                "env_seq": "3", "timestamp_ticks": "4",
                "observation_domain": "rp2040_timer0", "source": "bmp280",
                "role": "wrong_role", "temperature_c": "21",
                "relative_humidity_pct": "", "pressure_pa": "100000", "flags": "0",
            },
            {
                "env_seq": "4", "timestamp_ticks": "5",
                "observation_domain": "rp2040_timer0", "source": "sht4x",
                "role": "vcocxo_near", "temperature_c": "22",
                "relative_humidity_pct": "41", "pressure_pa": "", "flags": "0",
            },
            {
                "env_seq": "5", "timestamp_ticks": "5",
                "observation_domain": "rp2040_timer0", "source": "bmp280",
                "role": "pressure_reference", "temperature_c": "23",
                "relative_humidity_pct": "", "pressure_pa": "100001", "flags": "0",
            },
        ],
    )
    windows = [{
        "window_sequence": 1,
        "source_first_sequence": 1,
        "source_last_sequence": 2,
        "closing_timestamp_ticks": 10,
        "frequency_error_hz": 0.0,
    }]

    rows = environment_associations(source, windows, lags_s=[0], maximum_age_s=5)

    assert rows[0]["temperature_c"] == 22.0
    assert rows[0]["bmp280_role"] == "pressure_reference"
    assert rows[0]["bmp280_pressure_pa"] == 100001.0
    assert _unwrap_domain_ticks([modulus - 10, 10], "rp2040_timer0") == [
        modulus - 10,
        modulus + 10,
    ]


def test_environment_fit_gates_are_not_silently_waived() -> None:
    assert _linear_fit(
        [(1.0, 1.0), (2.0, 2.0)],
        minimum_samples=3,
        minimum_temperature_range_c=0.05,
    )["reason"] == "insufficient_samples"
    assert _linear_fit(
        [(1.0, 1.0), (1.01, 2.0), (1.02, 3.0)],
        minimum_samples=3,
        minimum_temperature_range_c=0.05,
    )["reason"] == "insufficient_temperature_range"


def test_phase_insufficient_segment_origin_is_explicit_unavailable() -> None:
    source = _source([_interval(1, 1), _interval(2, 2)], [])

    rows = phase_windows(source, [5])

    assert len(rows) == 1
    assert rows[0]["availability"] == "unavailable"
    assert "insufficient_complete_unjoined" in rows[0]["exclusion_reason"]


def test_material_source_provenance_is_complete_and_canonical() -> None:
    binding = {
        "source_id": "fixture",
        "consumed_files": {"b": "2" * 64, "a": "1" * 64},
    }

    assert _source_provenance_json(binding, "b", "a") == (
        '{"a":"' + "1" * 64 + '","b":"' + "2" * 64 + '"}'
    )


def test_strict_interval_join_rejects_gate_endpoint_mismatch() -> None:
    binding = _source([], []).binding
    binding["count_source_domain"] = "fixture_oscillator"
    raw = [
        {"record_type": "REF", "schema_version": "1", "event_seq": "1",
         "channel_id": "1", "edge": "R", "timestamp_ticks": "100",
         "capture_domain": "rp2040_timer0", "flags": "16"},
        {"record_type": "REF", "schema_version": "1", "event_seq": "2",
         "channel_id": "1", "edge": "R", "timestamp_ticks": "16000100",
         "capture_domain": "rp2040_timer0", "flags": "16"},
    ]
    snapshots = [
        {"record_type": "SNP", "schema_version": "1", "session": "1",
         "snapshot_sequence": "0", "cumulative_down_counter": "10000000",
         "reference_sequence": "0", "reference_timestamp_ticks": "100",
         "status": "0", "backend": "pio_wait_cumulative_snapshot_dma_v1"},
        {"record_type": "SNP", "schema_version": "1", "session": "1",
         "snapshot_sequence": "1", "cumulative_down_counter": "0",
         "reference_sequence": "1", "reference_timestamp_ticks": "16000100",
         "status": "0", "backend": "pio_wait_cumulative_snapshot_dma_v1"},
    ]
    count = {"record_type": "CNT", "schema_version": "1", "count_seq": "1",
             "channel_id": "2", "gate_open_ticks": "100",
             "gate_close_ticks": "16000100", "gate_domain": "rp2040_timer0",
             "counted_edges": "10000000", "source_edge": "R",
             "source_domain": "fixture_oscillator", "flags": "16"}
    transactions = [{"event": "manual_start", "applied_code": "43000", "dac_epoch": "0"}]

    rows = _build_intervals(
        "fixture", binding, raw, [count], snapshots, [], [], transactions
    )
    assert len(rows) == 1 and rows[0].measurement_qualified
    assert rows[0].opening_d14_event_sequence == 1
    assert rows[0].closing_d14_event_sequence == 2
    assert rows[0].opening_d14_flags == 16
    assert rows[0].closing_d14_flags == 16
    assert rows[0].count_flags == 16
    assert rows[0].count_gate_domain == "rp2040_timer0"
    assert rows[0].count_source_domain == "fixture_oscillator"
    assert rows[0].opening_snapshot_status == 0
    assert rows[0].closing_snapshot_status == 0

    broken = {**count, "gate_open_ticks": "101"}
    rows = _build_intervals(
        "fixture", binding, raw, [broken], snapshots, [], [], transactions
    )
    assert not rows[0].measurement_qualified
    assert "count_gate_open_snapshot_mismatch" in rows[0].measurement_exclusion_reason


def test_selected_frequency_support_is_independent_of_phase_availability() -> None:
    binding = _source([], []).binding
    intervals = [
        replace(
            _interval(sequence, sequence * 16_000_000),
            phase_available=False,
            relative_phase_cycles=None,
            phase_exclusion_reason="fixture_phase_unavailable",
        )
        for sequence in range(1, 601)
    ]
    estimate = {
        "record_type": "EST", "schema_version": "2", "estimate_seq": "0",
        "estimate_id": "fixture-selected", "estimator_version":
        "cx317_selected_600s_nonoverlap_v1", "time_domain": "rp2040_timer0",
        "config_hash": "5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c",
        "accepted_sample_count": "600", "source_reference_first_seq": "0",
        "source_reference_last_seq": "600", "source_count_seq": "600",
        "source_count_ref": "live:CNT:600", "observation_validity": "valid",
        "reference_validity": "valid", "reference_age_s": "0",
        "reference_continuity": "true", "count_validity": "valid",
        "count_age_s": "0", "count_continuity": "true",
        "diagnostic_health": "healthy", "preview_eligibility": "true",
        "frequency_error_hz": "0.000000000000",
    }

    rows, support = _validated_selected_frequency_rows(
        source_id="fixture", binding=binding, estimates=[estimate],
        intervals=intervals, decisions=[]
    )

    assert rows[0]["availability"] == "available"
    assert rows[0]["frequency_summary_eligible"] is True
    assert len(support) == 600


def test_invalid_model_emits_complete_unavailable_continuation_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = load_analysis_contract(DEFAULT_CONTRACT)
    cx322 = _source([], [])
    cx322.binding["source_id"] = "cx322_coherent"
    attempt4 = _source([], [])
    attempt4.binding["source_id"] = "attempt4_sustained"
    cx317 = _source([], [])
    cx317.binding["source_id"] = "cx317_fll_baseline"
    monkeypatch.setattr(
        study,
        "_changed_candidate_trace",
        lambda source, **_: {
            "source_id": source.binding["source_id"],
            "first_divergence": {"candidate_delta_codes": 1, "historical_delta_codes": 0},
        },
    )
    monkeypatch.setattr(
        study,
        "_first_divergence_sensitivity",
        lambda *_: {"available": True, "decision_bearing": False},
    )
    monkeypatch.setattr(
        study,
        "unchanged_cx322_on_attempt4",
        lambda *_: {"first_divergence_decision_sequence": 1},
    )

    result = study.candidate_comparison(
        sources=[cx317, cx322, attempt4],
        contract=contract,
        model_validation={"valid_for_decision_bearing_continuation": False},
        own_law_exact=True,
        generation_utc="fixture",
        tool_sha256="f" * 64,
        tool_files_sha256={"fixture.py": "f" * 64},
        tool_bundle_sha256="e" * 64,
    )

    for candidate in result["candidates"][1:]:
        continuation = candidate["all_case_continuation"]
        assert continuation["execution_state"] == "not_executed"
        assert continuation["required_case_count"] == 18
        assert continuation["generated_continuation_row_count"] == 0
        assert {row["source_id"] for row in continuation["cases"]} == {
            "cx322_coherent",
            "attempt4_sustained",
        }
        assert all(row["frequency_metrics"] is None for row in continuation["cases"])
        assert candidate["selection_gates"]["frequency_no_worse"] == "not_evaluated"
        assert set(candidate["traces"]) == {"cx322_coherent", "attempt4_sustained"}
    assert set(result["source_files_sha256"]) == {
        "cx317_fll_baseline",
        "cx322_coherent",
        "attempt4_sustained",
    }
    assert result["analysis_tool_files_sha256"] == {"fixture.py": "f" * 64}
    assert result["analysis_tool_bundle_sha256"] == "e" * 64


def test_unchanged_cx322_counterfactual_rows_carry_source_provenance() -> None:
    source = _source([], [])
    source.binding["source_id"] = "attempt4_sustained"
    source.binding["consumed_files"]["csv/active_hybrid_decisions_v1.csv"] = (
        "7" * 64
    )
    source.decisions = [
        {
            "decision_sequence": "1",
            "requested_delta_codes": "0",
            "raw_combined_delta_codes": "0.0",
        }
    ]

    result = study.unchanged_cx322_on_attempt4(source)

    provenance = json.loads(result["source_files_sha256_json"])
    assert "csv/active_hybrid_decisions_v1.csv" in provenance
    assert result["comparisons_through_first_divergence"][0][
        "source_files_sha256_json"
    ] == result["source_files_sha256_json"]


def test_study_module_has_no_device_or_process_control_imports() -> None:
    path = Path(__file__).parents[1] / "host/otis_tools/adaptive_steering_offline_study.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )

    forbidden = {"serial", "subprocess", "socket", "requests"}
    assert forbidden.isdisjoint(imported)
