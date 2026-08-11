from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import csv
import hashlib
import json

import pytest

from host.otis_tools.contracts import CsvValidationContext, validate_csv
from host.otis_tools.diagnostics import DEFAULT_DIAGNOSTIC_CONFIG_HASH
from host.otis_tools.observe_only_discipline_replay import ReplayConfig, main, replay_observe_only_discipline


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "profiles" / "plant_models" / "cx317_h1_bench_v3.json"
DEFAULT_CONFIG = ROOT / "profiles" / "discipline" / "phase4_host_replay_v2.json"
CONFIG_SCHEMA = ROOT / "schemas" / "phase4_replay_config_v2.schema.json"
SCENARIOS = ROOT / "tests" / "fixtures" / "phase4_replay" / "scenarios_v1.json"
TICK_HZ = 1_000_000
TOPOLOGY = "h1_run_020_g17_reworked_d14_d10_pps_witness"
BACKEND = "OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE"


def _config(**changes: object) -> ReplayConfig:
    values = {
        "startup_inhibit_s": 0.0,
        "clean_window_requirement": 3,
        "recovery_clean_window_requirement": 2,
        "estimator_window": 3,
        "minimum_estimator_samples": 3,
        "reference_max_age_s": 1.1,
        "count_max_age_s": 1.5,
        "maximum_dispersion_hz": 2.0,
    }
    values.update(changes)
    return ReplayConfig.from_mapping(values)


def _write_csv(path: Path, fields: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(fields)
        writer.writerows(rows)


def _make_run(
    root: Path,
    *,
    reference_seconds: list[int] | None = None,
    counts: list[tuple[int, int, int]] | None = None,
    dac_rows: list[tuple[int, int, int]] | None = None,
    topology: str = TOPOLOGY,
    backend: str = BACKEND,
    run_id: str = "phase4_fixture",
) -> Path:
    run_dir = root / "run"
    run_dir.mkdir(parents=True)
    reference_seconds = reference_seconds if reference_seconds is not None else list(range(0, 7))
    counts = counts if counts is not None else [
        (seq, seq, 10_000_001) for seq in range(1, 7)
    ]
    dac_rows = dac_rows if dac_rows is not None else [(1, 0, 0xA950)]

    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "template": False,
        "h_phase": "H1",
        "stage": "SW2_PHASE4_HOST_REPLAY",
        "domains": [{"name": "fixture_ticks", "nominal_hz": TICK_HZ}],
        "channels": [
            {"channel_id": 1, "role": "pps_reference"},
            {"channel_id": 2, "role": "oscillator_count"},
        ],
        "oscillator": {"nominal_frequency_hz": 10_000_000.0},
        "phase4_replay": {
            "hardware_topology_id": topology,
            "measurement_backend": backend,
        },
        "files": [
            {"path": "csv/raw_events.csv", "contract": "raw_events_v1"},
            {"path": "csv/count_observations.csv", "contract": "count_observations_v1"},
            {"path": "csv/health.csv", "contract": "health_v1"},
            {"path": "csv/dac_steps.csv", "contract": "dac_steps_v1"},
        ],
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_csv(
        run_dir / "csv" / "raw_events.csv",
        [
            "record_type",
            "schema_version",
            "event_seq",
            "channel_id",
            "edge",
            "timestamp_ticks",
            "capture_domain",
            "flags",
        ],
        [
            ["REF", 1, index + 1, 1, "R", second * TICK_HZ, "fixture_ticks", 16]
            for index, second in enumerate(reference_seconds)
        ],
    )
    _write_csv(
        run_dir / "csv" / "count_observations.csv",
        [
            "record_type",
            "schema_version",
            "count_seq",
            "channel_id",
            "gate_open_ticks",
            "gate_close_ticks",
            "gate_domain",
            "counted_edges",
            "source_edge",
            "source_domain",
            "flags",
        ],
        _count_csv_rows(counts),
    )
    _write_csv(
        run_dir / "csv" / "health.csv",
        [
            "record_type",
            "schema_version",
            "status_seq",
            "timestamp_ticks",
            "status_domain",
            "component",
            "status_key",
            "status_value",
            "severity",
            "flags",
        ],
        [
            ["STS", 1, 1, 0, "fixture_ticks", "reference", "reference_valid_for_control", "true", "INFO", 0],
            ["STS", 1, 2, 1, "fixture_ticks", "count", "count_valid_for_control", "true", "INFO", 0],
            ["STS", 1, 3, 1, "fixture_ticks", "reference_receiver", "authority_state", "qualified", "INFO", 0],
            ["STS", 1, 4, 1, "fixture_ticks", "reference_receiver", "utc_traceability_state", "valid", "INFO", 0],
        ],
    )
    _write_csv(
        run_dir / "csv" / "dac_steps.csv",
        [
            "record_type",
            "schema_version",
            "seq",
            "elapsed_ms",
            "step_index",
            "dac_code_requested",
            "dac_code_applied",
            "dac_code_clamped",
            "dac_voltage_measured_v",
            "ocxo_tune_voltage_measured_v",
            "dwell_ms",
            "event",
            "flags",
        ],
        [
            ["DAC", 1, seq, elapsed_ms, -1, code, code, 0, "", "", 0, "step_apply", 0]
            for seq, elapsed_ms, code in dac_rows
        ],
    )
    return run_dir


def _count_csv_rows(counts: list[tuple[int, ...]]) -> list[list[object]]:
    result: list[list[object]] = []
    previous_close_second = 0
    for seq, close_second, counted_edges, *row_flags in counts:
        result.append(
            [
                "CNT",
                1,
                seq,
                2,
                previous_close_second * TICK_HZ,
                close_second * TICK_HZ,
                "fixture_ticks",
                counted_edges,
                "R",
                "h1_cx317_ocxo_10mhz",
                row_flags[0] if row_flags else 16,
            ]
        )
        previous_close_second = close_second
    return result


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _source_hashes(run_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(run_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(run_dir.rglob("*"))
        if path.is_file() and path.relative_to(run_dir).parts[0] != "derived"
    }


def test_fixture_matrix_names_every_required_replay_case() -> None:
    fixture = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    assert fixture["schema_version"] == 1
    assert len(fixture["cases"]) == 12
    assert {case["id"] for case in fixture["cases"]} >= {
        "free_running_constant_frequency_offset",
        "known_dac_step_h1_plant_response",
        "startup_inhibit_then_clean_window_qualification",
        "pps_outlier",
        "missing_and_stale_pps",
        "zero_saturated_missing_and_stale_count",
        "post_qualification_measurement_fault",
        "unavailable_or_invalid_plant_model",
        "input_outside_model_applicability",
        "correction_beyond_range_and_maximum_preview_step",
        "reference_loss_and_return",
        "byte_identical_repeated_execution",
    }


def test_versioned_default_configuration_keeps_drift_disabled() -> None:
    config_data = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    schema = json.loads(CONFIG_SCHEMA.read_text(encoding="utf-8"))
    config = ReplayConfig.from_mapping(config_data)
    assert config.drift_estimation_enabled is False
    assert schema["properties"]["drift_estimation_enabled"]["const"] is False
    assert schema["additionalProperties"] is False


def test_replay_cli_uses_explicit_model_and_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = _make_run(tmp_path)
    config_path = tmp_path / "fast_fixture_config.json"
    config_path.write_text(
        json.dumps(asdict_for_test(_config()), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert main(
        [
            str(run_dir),
            "--plant-model",
            str(MODEL),
            "--config",
            str(config_path),
        ]
    ) == 0
    assert "source evidence unchanged" in capsys.readouterr().out


def test_nominal_replay_is_strict_deterministic_and_preserves_sources(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path)
    before = _source_hashes(run_dir)
    raw_reference_before = (
        run_dir / "csv" / "raw_events.csv"
    ).read_bytes()
    result = replay_observe_only_discipline(run_dir, plant_model_path=MODEL, config=_config())
    first_bytes = {
        path.name: path.read_bytes()
        for path in (
            result.estimates_path,
            result.reference_observations_path,
            result.diagnostics_path,
            result.previews_path,
            result.report_path,
        )
    }
    repeated = replay_observe_only_discipline(run_dir, plant_model_path=MODEL, config=_config())

    assert before == _source_hashes(run_dir)
    assert (
        run_dir / "csv" / "raw_events.csv"
    ).read_bytes() == raw_reference_before
    assert first_bytes == {
        path.name: path.read_bytes()
        for path in (
            repeated.estimates_path,
            repeated.reference_observations_path,
            repeated.diagnostics_path,
            repeated.previews_path,
            repeated.report_path,
        )
    }

    estimate_validation = validate_csv(
        result.estimates_path,
        CsvValidationContext("estimates_v2", frozenset(), frozenset({"fixture_ticks"})),
    )
    preview_validation = validate_csv(
        result.previews_path,
        CsvValidationContext("control_previews_v1", frozenset(), frozenset({"fixture_ticks"})),
    )
    assert estimate_validation.errors == ()
    assert preview_validation.errors == ()

    estimates = _rows(result.estimates_path)
    diagnostics = _rows(result.diagnostics_path)
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    previews = _rows(result.previews_path)
    assert "frequency_uncertainty_hz" not in estimates[-1]
    assert estimates[-1]["uncertainty_status"] == "incomplete"
    assert estimates[-1]["combined_standard_uncertainty_hz"] == ""
    assert estimates[-1]["preview_eligibility"] == "true"
    assert previews[-1]["preview_available"] == "true"
    assert previews[-1]["preview_only"] == "true"
    assert previews[-1]["actuation_authorized"] == "false"
    assert previews[-1]["actionable"] == "false"
    assert previews[-1]["est_input_ref"] == estimates[-1]["estimate_id"]
    assert previews[-1]["plant_model_version"] == "4"
    assert previews[-1]["policy_version"]
    assert previews[-1]["config_hash"] == estimates[-1]["config_hash"]
    assert diagnostics
    assert {
        row["config_hash"] for row in diagnostics
    } == {DEFAULT_DIAGNOSTIC_CONFIG_HASH}
    assert all(
        "phase4_replay" not in row["config_hash"] for row in diagnostics
    )
    assert all(
        ":REF:" in row["first_evidence_refs"]
        or "unavailable:" in row["first_evidence_refs"]
        for row in diagnostics
    )
    assert any(
        row["diagnostic_id"] == "diag.aperture.unqualified"
        for row in diagnostics
    )
    assert (
        report["diagnostics"]["configuration_hash"]
        == DEFAULT_DIAGNOSTIC_CONFIG_HASH
    )
    assert report["uncertainty"]["available_record_count"] == 0


def test_reference_receiver_identity_change_creates_a_new_replay_epoch(
    tmp_path: Path,
) -> None:
    run_dir = _make_run(tmp_path)
    _write_csv(
        run_dir / "csv" / "health.csv",
        [
            "record_type",
            "schema_version",
            "status_seq",
            "timestamp_ticks",
            "status_domain",
            "component",
            "status_key",
            "status_value",
            "severity",
            "flags",
        ],
        [
            ["STS", 1, 1, 0, "fixture_ticks", "reference_receiver",
             "authority_state", "qualified", "INFO", 0],
            ["STS", 1, 2, 0, "fixture_ticks", "reference_receiver",
             "utc_traceability_state", "valid", "INFO", 0],
            ["STS", 1, 3, 0, "fixture_ticks", "reference_receiver",
             "identity", "module-A", "INFO", 0],
            ["STS", 1, 4, 0, "fixture_ticks", "reference_receiver",
             "firmware", "1.0", "INFO", 0],
            ["STS", 1, 5, 4 * TICK_HZ, "fixture_ticks",
             "reference_receiver", "identity", "module-B", "INFO", 0],
            ["STS", 1, 6, 4 * TICK_HZ, "fixture_ticks",
             "reference_receiver", "firmware", "2.0", "INFO", 0],
        ],
    )
    result = replay_observe_only_discipline(run_dir, plant_model_path=MODEL, config=_config())
    rows = _rows(result.reference_observations_path)
    module_a = next(row for row in rows if row["receiver_identity"] == "module-A")
    module_b = next(row for row in rows if row["receiver_identity"] == "module-B")
    assert module_a["source_identity_epoch"] == "reference_source_epoch:1"
    assert module_b["source_identity_epoch"] == "reference_source_epoch:2"
    assert module_a["source_identity_epoch"] != module_b["source_identity_epoch"]


def test_nominal_cadence_without_receiver_metadata_inhibits_eligibility(
    tmp_path: Path,
) -> None:
    run_dir = _make_run(tmp_path)
    _write_csv(
        run_dir / "csv" / "health.csv",
        [
            "record_type",
            "schema_version",
            "status_seq",
            "timestamp_ticks",
            "status_domain",
            "component",
            "status_key",
            "status_value",
            "severity",
            "flags",
        ],
        [
            ["STS", 1, 1, 0, "fixture_ticks", "reference",
             "reference_valid_for_control", "true", "INFO", 0],
            ["STS", 1, 2, 1, "fixture_ticks", "count",
             "count_valid_for_control", "true", "INFO", 0],
        ],
    )
    result = replay_observe_only_discipline(
        run_dir, plant_model_path=MODEL, config=_config()
    )
    references = _rows(result.reference_observations_path)
    estimates = _rows(result.estimates_path)
    assert any(row["cadence_state"] == "valid" for row in references)
    assert all(row["qualification_state"] != "qualified" for row in references)
    assert all(row["preview_eligibility"] == "false" for row in estimates)
    assert all(
        "reference_authority_unqualified" in row["eligibility_reason_codes"]
        for row in estimates
    )


def test_replay_output_loss_and_resource_failure_raise_then_clear(
    tmp_path: Path,
) -> None:
    run_dir = _make_run(tmp_path)
    health = run_dir / "csv" / "health.csv"
    with health.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            ["STS", 1, 5, 2 * TICK_HZ, "fixture_ticks", "capture",
             "drop_count", "1", "ERROR", 0]
        )
        writer.writerow(
            ["STS", 1, 6, 3 * TICK_HZ, "fixture_ticks", "capture",
             "drop_count", "0", "INFO", 0]
        )
    result = replay_observe_only_discipline(
        run_dir, plant_model_path=MODEL, config=_config()
    )
    diagnostics = _rows(result.diagnostics_path)
    for diagnostic_id in ("diag.output.loss", "diag.resource.failure"):
        transitions = [
            row["transition"]
            for row in diagnostics
            if row["diagnostic_id"] == diagnostic_id
        ]
        assert transitions == ["raised", "cleared"]


def test_replay_refuses_to_replace_a_different_existing_derived_product(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path)
    before = _source_hashes(run_dir)
    result = replay_observe_only_discipline(run_dir, plant_model_path=MODEL, config=_config())
    result.previews_path.write_text("sealed-or-different\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="refusing to replace"):
        replay_observe_only_discipline(run_dir, plant_model_path=MODEL, config=_config())
    assert _source_hashes(run_dir) == before


def test_startup_clean_qualification_and_h1_preview_limits(tmp_path: Path) -> None:
    run_dir = _make_run(
        tmp_path,
        counts=[(seq, seq, 10_000_100) for seq in range(1, 7)],
        dac_rows=[(1, 0, 0xA800)],
    )
    result = replay_observe_only_discipline(
        run_dir,
        plant_model_path=MODEL,
        config=_config(startup_inhibit_s=1.5),
    )
    previews = _rows(result.previews_path)

    assert previews[0]["control_state"] == "WARMUP_INHIBIT"
    assert any(row["control_state"] == "QUALIFYING" for row in previews)
    available = [row for row in previews if row["preview_available"] == "true"]
    assert available
    assert available[-1]["step_limited"] == "true"
    assert available[-1]["range_clamped"] == "true"
    assert available[-1]["proposed_dac_code"] == str(0xA800)
    assert available[-1]["limited_delta_codes"] == "0"


@pytest.mark.parametrize(
    ("references", "counts", "expected_reason"),
    [
        ([0, 1, 2, 4, 5, 6], None, "reference_interval_outlier"),
        ([0, 1, 2], None, "reference_stale"),
        (None, [(1, 1, 10_000_000), (2, 2, 10_000_000), (3, 3, 10_000_000), (4, 4, 0)], "count_zero"),
        (
            None,
            [(1, 1, 10_000_000), (2, 2, 10_000_000), (3, 3, 10_000_000), (4, 4, 10_000_000, 1 << 13)],
            "count_saturated",
        ),
        (
            None,
            [(1, 1, 10_000_000), (2, 2, 10_000_000), (3, 3, 10_000_000), (5, 4, 10_000_000)],
            "count_sequence_discontinuity",
        ),
    ],
)
def test_fault_inputs_are_ineligible_and_never_propose(
    tmp_path: Path,
    references: list[int] | None,
    counts: list[tuple[int, ...]] | None,
    expected_reason: str,
) -> None:
    run_dir = _make_run(tmp_path, reference_seconds=references, counts=counts)
    result = replay_observe_only_discipline(run_dir, plant_model_path=MODEL, config=_config())
    estimates = _rows(result.estimates_path)
    previews = _rows(result.previews_path)

    matching = [row for row in estimates if expected_reason in row["observation_reason_codes"]]
    assert matching
    matching_ids = {row["estimate_id"] for row in matching}
    decisions = [row for row in previews if row["est_input_ref"] in matching_ids]
    assert decisions
    assert all(row["preview_eligibility"] == "false" for row in decisions)
    assert all(row["preview_available"] == "false" for row in decisions)
    assert all(row["proposed_dac_code"] == "" for row in decisions)
    if expected_reason in {"count_zero", "count_saturated", "count_sequence_discontinuity"}:
        assert decisions[-1]["control_state"] == "FAULT"
        assert any(
            row["transition_reason_code"] == "post_qualification_measurement_fault"
            for row in decisions
        )


def test_stale_count_snapshot_faults_after_qualification(tmp_path: Path) -> None:
    run_dir = _make_run(
        tmp_path,
        reference_seconds=list(range(0, 7)),
        counts=[(seq, seq, 10_000_000) for seq in range(1, 4)],
    )
    result = replay_observe_only_discipline(run_dir, plant_model_path=MODEL, config=_config())
    estimates = _rows(result.estimates_path)
    previews = _rows(result.previews_path)
    assert "count_stale" in estimates[-1]["observation_reason_codes"]
    assert previews[-1]["control_state"] == "FAULT"
    assert previews[-1]["preview_available"] == "false"


def test_pps_reference_flag_on_count_does_not_collapse_count_validity(
    tmp_path: Path,
) -> None:
    counts = [
        (seq, seq, 10_000_000)
        for seq in range(1, 4)
    ]
    counts.append(
        (4, 4, 10_000_000, (1 << 3) | (1 << 12))
    )
    run_dir = _make_run(tmp_path, counts=counts)
    result = replay_observe_only_discipline(
        run_dir, plant_model_path=MODEL, config=_config()
    )
    estimates = _rows(result.estimates_path)
    affected = [
        row for row in estimates if row["source_count_seq"] == "4"
    ][0]
    assert affected["reference_validity"] == "invalid"
    assert affected["count_validity"] == "valid"
    assert (
        "reference_flagged_invalid"
        in affected["observation_reason_codes"]
    )
    assert "count_flagged_invalid" not in affected[
        "observation_reason_codes"
    ]


def test_replay_unwraps_rp2040_reference_and_count_gate_rollover(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["domains"] = [{"name": "rp2040_timer0", "nominal_hz": 16_000_000}]
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    wrap = (1 << 32) * 16
    reference_ticks = [wrap - 32_000_000, wrap - 16_000_000, 0, 16_000_000, 32_000_000]
    _write_csv(
        run_dir / "csv" / "raw_events.csv",
        [
            "record_type",
            "schema_version",
            "event_seq",
            "channel_id",
            "edge",
            "timestamp_ticks",
            "capture_domain",
            "flags",
        ],
        [
            ["REF", 1, seq, 1, "R", ticks, "rp2040_timer0", 16]
            for seq, ticks in enumerate(reference_ticks, start=1)
        ],
    )
    _write_csv(
        run_dir / "csv" / "count_observations.csv",
        [
            "record_type",
            "schema_version",
            "count_seq",
            "channel_id",
            "gate_open_ticks",
            "gate_close_ticks",
            "gate_domain",
            "counted_edges",
            "source_edge",
            "source_domain",
            "flags",
        ],
        [
            ["CNT", 1, 1, 2, wrap - 32_000_000, wrap - 16_000_000, "rp2040_timer0", 10_000_000, "R", "h1_cx317_ocxo_10mhz", 16],
            ["CNT", 1, 2, 2, wrap - 16_000_000, 0, "rp2040_timer0", 10_000_000, "R", "h1_cx317_ocxo_10mhz", 16],
            ["CNT", 1, 3, 2, 0, 16_000_000, "rp2040_timer0", 10_000_000, "R", "h1_cx317_ocxo_10mhz", 16],
            ["CNT", 1, 4, 2, 16_000_000, 32_000_000, "rp2040_timer0", 10_000_000, "R", "h1_cx317_ocxo_10mhz", 16],
        ],
    )
    _write_csv(
        run_dir / "csv" / "health.csv",
        [
            "record_type",
            "schema_version",
            "status_seq",
            "timestamp_ticks",
            "status_domain",
            "component",
            "status_key",
            "status_value",
            "severity",
            "flags",
        ],
            [
                ["STS", 1, 1, wrap - 32_000_000, "rp2040_timer0", "reference", "reference_valid_for_control", "true", "INFO", 0],
                ["STS", 1, 2, wrap - 32_000_000, "rp2040_timer0", "count", "count_valid_for_control", "true", "INFO", 0],
                ["STS", 1, 3, wrap - 32_000_000, "rp2040_timer0", "reference_receiver", "authority_state", "qualified", "INFO", 0],
                ["STS", 1, 4, wrap - 32_000_000, "rp2040_timer0", "reference_receiver", "utc_traceability_state", "valid", "INFO", 0],
            ],
    )
    result = replay_observe_only_discipline(run_dir, plant_model_path=MODEL, config=_config())
    estimates = _rows(result.estimates_path)
    preview = _rows(result.previews_path)[-1]
    timestamps = [int(row["estimator_timestamp_ticks"]) for row in estimates]
    assert timestamps == sorted(timestamps)
    assert all(float(row["frequency_observation_hz"]) == 10_000_000 for row in estimates)
    assert preview["control_state"] == "ACQUIRE_PREVIEW"
    assert preview["preview_available"] == "true"


def test_reference_loss_and_return_uses_holdover_then_recovery(tmp_path: Path) -> None:
    run_dir = _make_run(
        tmp_path,
        reference_seconds=[0, 1, 2, 3, 6, 7, 8, 9],
        counts=[(seq, seq, 10_000_000) for seq in range(1, 10)],
    )
    result = replay_observe_only_discipline(run_dir, plant_model_path=MODEL, config=_config())
    previews = _rows(result.previews_path)
    states = [row["control_state"] for row in previews]
    assert "HOLDOVER_PREVIEW" in states
    assert "RECOVER_PREVIEW" in states
    assert states[-1] == "ACQUIRE_PREVIEW"
    assert any(row["transition_reason_code"] == "reference_return_requalification" for row in previews)


@pytest.mark.parametrize(("model_kind", "expected"), [("missing", "plant_model_unavailable"), ("invalid", "plant_model_invalid")])
def test_unavailable_or_invalid_model_inhibits_preview(
    tmp_path: Path, model_kind: str, expected: str
) -> None:
    run_dir = _make_run(tmp_path)
    model_path = tmp_path / "model.json"
    if model_kind == "invalid":
        model_path.write_text("{not-json}\n", encoding="utf-8")
    result = replay_observe_only_discipline(run_dir, plant_model_path=model_path, config=_config())
    previews = _rows(result.previews_path)
    assert expected in previews[-1]["model_reason_codes"]
    assert previews[-1]["preview_available"] == "false"
    assert previews[-1]["proposed_dac_code"] == ""


def test_model_identity_applicability_and_excluded_sequence_are_enforced(tmp_path: Path) -> None:
    outside = _make_run(tmp_path / "outside", dac_rows=[(1, 0, 0x9000)])
    outside_result = replay_observe_only_discipline(outside, plant_model_path=MODEL, config=_config())
    assert "input_outside_model_applicability" in _rows(outside_result.previews_path)[-1]["model_reason_codes"]

    mismatch = _make_run(tmp_path / "mismatch", topology="other_topology")
    mismatch_result = replay_observe_only_discipline(mismatch, plant_model_path=MODEL, config=_config())
    assert "plant_model_topology_mismatch" in _rows(mismatch_result.previews_path)[-1]["model_reason_codes"]

    excluded = _make_run(
        tmp_path / "excluded",
        reference_seconds=list(range(0, 79)),
        counts=[(seq, seq, 10_000_000) for seq in range(72, 78)],
        run_id="run_020",
    )
    excluded_result = replay_observe_only_discipline(excluded, plant_model_path=MODEL, config=_config())
    assert "plant_model_excluded_count_sequence" in _rows(excluded_result.previews_path)[-1]["model_reason_codes"]


def test_known_dac_step_uses_h1_model_gain_and_latest_dac_evidence(tmp_path: Path) -> None:
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    slope = model["plant_response"]["local_slope"]["hz_per_code"]
    step_codes = 0x0300
    gate_s = 1000
    expected_step_hz = slope * step_codes
    stepped_count = round((10_000_000.0 + expected_step_hz) * gate_s)
    run_dir = _make_run(
        tmp_path,
        reference_seconds=list(range(0, 6001)),
        counts=[
            (1, 1000, 10_000_000 * gate_s),
            (2, 2000, 10_000_000 * gate_s),
            (3, 3000, 10_000_000 * gate_s),
            (4, 4000, stepped_count),
            (5, 5000, stepped_count),
            (6, 6000, stepped_count),
        ],
        dac_rows=[(1, 0, 0xA950), (2, 3_000_000, 0xAC50)],
    )
    result = replay_observe_only_discipline(
        run_dir,
        plant_model_path=MODEL,
        config=_config(count_max_age_s=1500.0),
    )
    estimates = _rows(result.estimates_path)
    previews = _rows(result.previews_path)
    before = previews[1]
    after = previews[-1]
    assert float(after["hz_per_code"]) == pytest.approx(
        slope
    )
    assert before["current_dac_code"] == str(0xA950)
    assert after["current_dac_code"] == str(0xAC50)
    assert after["plant_model_version"] == "4"
    assert float(estimates[3]["frequency_observation_hz"]) - 10_000_000.0 == pytest.approx(
        expected_step_hz, abs=0.0006
    )


def test_phase4_configuration_rejects_drift_estimation() -> None:
    value = deepcopy(asdict_for_test(_config()))
    value["drift_estimation_enabled"] = True
    with pytest.raises(ValueError, match="must remain false"):
        ReplayConfig.from_mapping(value)


def asdict_for_test(config: ReplayConfig) -> dict[str, object]:
    return {field: getattr(config, field) for field in config.__dataclass_fields__}
