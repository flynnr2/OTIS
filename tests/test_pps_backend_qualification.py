from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import csv
import json

import pytest

from host.otis_tools.pps_backend_qualification import (
    QualificationConfig,
    qualify_pps_backend,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    ROOT / "profiles" / "qualification" / "pps_gated_ratio_v1.json"
)
CONFIG_SCHEMA = (
    ROOT / "schemas" / "pps_backend_qualification_config_v1.schema.json"
)
SCENARIOS = (
    ROOT
    / "tests"
    / "fixtures"
    / "pps_backend_qualification"
    / "scenarios_v1.json"
)
TICKS_PER_SECOND = 16_000_000
CANDIDATE_BACKEND = "OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO"
WRAP_TICKS = (1 << 32) * 16


def _write_csv(
    path: Path, fields: list[str], rows: list[list[object]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(fields)
        writer.writerows(rows)


def _metadata(
    *,
    candidate: bool,
    source_domain: str = "h1_ocxo_open_loop",
    uncertainty_complete: bool = True,
) -> dict:
    uncertainty = {
        "count_quantization_standard_uncertainty_hz": (
            0.288675 if uncertainty_complete and candidate else None
        ),
        "counter_aperture_s_1sigma": (
            1e-9 if uncertainty_complete and candidate else None
        ),
        "reference_fractional_1sigma": (
            1e-11 if uncertainty_complete and candidate else None
        ),
        "independent_frequency_hz_1sigma": (
            0.01 if uncertainty_complete and not candidate else None
        ),
    }
    result = {
        "evidence_kind": "synthetic",
        "comparison_interval_id": "fixture-stable-interval",
        "comparison_started_utc": "2026-07-29T12:00:00Z",
        "comparison_ended_utc": "2026-07-29T12:00:06Z",
        "comparison_first_count_seq": 1,
        "comparison_last_count_seq": 6 if candidate else 1,
        "estimator_type": (
            "pps_gated_ratio_count_v1"
            if candidate
            else "pio_long_gate_timer_frequency_v1"
        ),
        "measurement_backend": (
            CANDIDATE_BACKEND
            if candidate
            else "OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE"
        ),
        "source_domain": source_domain,
        "uncertainty": uncertainty,
    }
    if candidate:
        result["service_plane_segments"] = [
            {
                "label": "baseline",
                "mode": "baseline",
                "first_count_seq": 1,
                "last_count_seq": 3,
            },
            {
                "label": "serial_status_load",
                "mode": "load",
                "first_count_seq": 4,
                "last_count_seq": 6,
            },
        ]
    return result


def _manifest(
    run_dir: Path,
    run_id: str,
    *,
    candidate: bool,
    source_domain: str = "h1_ocxo_open_loop",
    uncertainty_complete: bool = True,
) -> None:
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "template": False,
        "h_phase": "H1",
        "stage": "PHASE5_PPS_BACKEND_QUALIFICATION",
        "control_mode": "observe_only",
        "closed_loop_control": False,
        "firmware": {
            "name": "otis_nano_rp2040_connect",
            "version": "SW1",
            "config_id": (
                "phase5_pps_gated_qualification_v1"
                if candidate
                else "phase5_independent_long_gate_v1"
            ),
            "git_commit": "a" * 40,
        },
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": TICKS_PER_SECOND}
        ],
        "channels": [
            {"channel_id": 1, "role": "pps_reference"},
            {"channel_id": 2, "role": "oscillator_count"},
        ],
        "oscillator": {"nominal_frequency_hz": 10_000_000.0},
        "phase5_pps_backend_qualification": _metadata(
            candidate=candidate,
            source_domain=source_domain,
            uncertainty_complete=uncertainty_complete,
        ),
        "files": [
            {"path": "csv/raw_events.csv", "contract": "raw_events_v1"},
            {
                "path": "csv/count_observations.csv",
                "contract": "count_observations_v1",
            },
            {"path": "csv/health.csv", "contract": "health_v1"},
        ],
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _health_rows() -> list[list[object]]:
    reasons = [
        "reference_missing_pps",
        "reference_pps_duplicate",
        "reference_pps_short_interval",
        "reference_pps_long_interval",
        "count_zero",
        "count_saturated",
    ]
    rows: list[list[object]] = []
    seq = 1
    for component, key, value in (
        ("firmware", "name", "otis_nano_rp2040_connect"),
        ("firmware", "version", "SW1"),
        ("firmware", "config_id", "phase5_pps_gated_qualification_v1"),
        ("firmware", "git_commit", "a" * 40),
        ("capture", "tcxo_counter_backend", "pps_gated_ratio"),
        ("capture", "pps_gated_ratio_init", "ok"),
        ("build", "enable_dac_ad5693r", "0"),
        ("build", "enable_h1_dac_sweep", "0"),
        ("build", "enable_phase4_observe_preview", "0"),
        ("phase4_preview", "actuation_authorized", "false"),
        ("pps_gate", "backend", "pps_gated_ratio"),
        ("pps_gate", "duplicate_max_interval_us", "100000"),
        ("pps_gate", "min_interval_us", "800000"),
        ("pps_gate", "max_interval_us", "1200000"),
        ("pps_gate", "missing_timeout_us", "2500000"),
        ("pps_gate", "count_resolution_edges", "1"),
    ):
        rows.append(
            [
                "STS",
                1,
                seq,
                seq * 100,
                "rp2040_timer0",
                component,
                key,
                value,
                "INFO",
                0,
            ]
        )
        seq += 1
    for reason in reasons:
        key = (
            "count_reason" if reason.startswith("count_") else "reference_reason"
        )
        rows.append(
            [
                "STS",
                1,
                seq,
                seq * 100,
                "rp2040_timer0",
                "pps_gate",
                key,
                reason,
                "WARN",
                0,
            ]
        )
        seq += 1
        rows.append(
            [
                "STS",
                1,
                seq,
                seq * 100,
                "rp2040_timer0",
                "pps_gate",
                "control_eligible",
                "false",
                "WARN",
                0,
            ]
        )
        seq += 1
    for key, value in (
        ("startup_inhibit_active", "true"),
        ("startup_inhibit_active", "false"),
        ("reference_validity", "invalid"),
        ("reference_validity", "valid"),
        ("count_validity", "invalid"),
        ("count_validity", "valid"),
        ("control_eligible", "true"),
        ("dropped_count", "0"),
    ):
        component = "capture" if key == "dropped_count" else "pps_gate"
        rows.append(
            [
                "STS",
                1,
                seq,
                seq * 100,
                "rp2040_timer0",
                component,
                key,
                value,
                "INFO",
                0,
            ]
        )
        seq += 1
    return rows


def _make_candidate(
    root: Path,
    *,
    source_domain: str = "h1_ocxo_open_loop",
    uncertainty_complete: bool = True,
    rollover: bool = False,
) -> Path:
    run_dir = root / "candidate"
    run_dir.mkdir(parents=True)
    _manifest(
        run_dir,
        "phase5_candidate_fixture",
        candidate=True,
        source_domain=source_domain,
        uncertainty_complete=uncertainty_complete,
    )
    if rollover:
        reference_ticks = [
            WRAP_TICKS - 2 * TICKS_PER_SECOND,
            WRAP_TICKS - TICKS_PER_SECOND,
            0,
            TICKS_PER_SECOND,
            2 * TICKS_PER_SECOND,
            3 * TICKS_PER_SECOND,
            4 * TICKS_PER_SECOND,
        ]
    else:
        reference_ticks = [
            second * TICKS_PER_SECOND for second in range(7)
        ]
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
            [
                "REF",
                1,
                seq,
                1,
                "R",
                ticks,
                "rp2040_timer0",
                16,
            ]
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
            [
                "CNT",
                1,
                seq,
                2,
                reference_ticks[seq - 1],
                reference_ticks[seq],
                "rp2040_timer0",
                10_000_001,
                "R",
                source_domain,
                16,
            ]
            for seq in range(1, 7)
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
        _health_rows(),
    )
    return run_dir


def _make_independent(root: Path) -> Path:
    run_dir = root / "independent"
    run_dir.mkdir(parents=True)
    _manifest(run_dir, "phase5_independent_fixture", candidate=False)
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
            [
                "REF",
                1,
                seq + 1,
                1,
                "R",
                seq * TICKS_PER_SECOND,
                "rp2040_timer0",
                16,
            ]
            for seq in range(7)
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
            [
                "CNT",
                1,
                1,
                2,
                0,
                6 * TICKS_PER_SECOND,
                "rp2040_timer0",
                60_000_006,
                "R",
                "h1_ocxo_open_loop",
                16,
            ]
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
            [
                "STS",
                1,
                1,
                0,
                "rp2040_timer0",
                "capture",
                "pio_long_gate_init",
                "ok",
                "INFO",
                0,
            ]
        ],
    )
    return run_dir


def _fast_config(tmp_path: Path) -> Path:
    value = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    value["minimum_eligible_windows"] = 6
    value["minimum_stable_duration_s"] = 6.0
    value["minimum_service_plane_windows_per_segment"] = 3
    path = tmp_path / "qualification_config.json"
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_scenario_fixture_names_the_required_repository_and_bench_cases() -> None:
    fixture = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    assert fixture["schema_version"] == 1
    assert {case["id"] for case in fixture["cases"]} >= {
        "nominal_traceable_pps_windows",
        "timer_rollover",
        "duplicate_and_short_pps",
        "long_and_missing_pps",
        "zero_and_saturated_count",
        "startup_inhibit_and_recovery",
        "stale_timeout_and_count_unavailability",
        "source_typing_mismatch",
        "independent_metrology_bias",
        "service_plane_load",
        "unavailable_uncertainty",
    }


def test_default_config_and_schema_are_closed_and_versioned() -> None:
    value = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    schema = json.loads(CONFIG_SCHEMA.read_text(encoding="utf-8"))
    config = QualificationConfig.from_mapping(value)
    assert config.candidate_estimator_type == "pps_gated_ratio_count_v1"
    assert config.allowed_independent_paths[0] == (
        "pio_long_gate_timer_frequency_v1",
        "OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE",
    )
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(value)


def test_synthetic_candidate_and_independent_report_is_deterministic_but_not_qualified(
    tmp_path: Path,
) -> None:
    candidate = _make_candidate(tmp_path)
    independent = _make_independent(tmp_path)
    config = _fast_config(tmp_path)
    before = {
        path.relative_to(candidate).as_posix(): path.read_bytes()
        for path in candidate.rglob("*")
        if path.is_file()
    }

    result = qualify_pps_backend(
        candidate, independent_run=independent, config_path=config
    )
    first = result.report_path.read_bytes()
    repeated = qualify_pps_backend(
        candidate, independent_run=independent, config_path=config
    )
    report = _report(repeated.report_path)

    assert first == repeated.report_path.read_bytes()
    assert result.qualification_state == "repository_validation_only"
    assert report["candidate"]["traceable_window_count"] == 6
    assert report["candidate"]["reference_valid_window_count"] == 6
    assert report["candidate"]["count_valid_window_count"] == 6
    assert report["candidate"]["eligible_window_count"] == 6
    assert report["comparison"]["bias_hz"] == pytest.approx(0.0)
    assert report["service_plane"]["maximum_absolute_mean_shift_hz"] == 0.0
    assert (
        report["acceptance_checks"][
            "runtime_backend_identity_and_config_match"
        ]
        is True
    )
    assert report["uncertainty"]["unavailable_components"] == []
    assert all(
        item["detected"] and item["inhibition_observed"]
        for item in report["diagnostics"].values()
    )
    assert report["phase_boundary"] == {
        "observe_only": True,
        "control_ready": False,
        "actuation_enabled": False,
        "dac_write_authorized": False,
    }
    after = {
        path.relative_to(candidate).as_posix(): path.read_bytes()
        for path in candidate.rglob("*")
        if path.is_file() and path.relative_to(candidate).parts[0] != "derived"
    }
    assert before == after


def test_runtime_backend_configuration_must_corroborate_manifest_typing(
    tmp_path: Path,
) -> None:
    candidate = _make_candidate(tmp_path)
    status_path = candidate / "csv" / "health.csv"
    rows = list(csv.reader(status_path.open(newline="", encoding="utf-8")))
    for row in rows[1:]:
        if row[5:7] == ["pps_gate", "min_interval_us"]:
            row[7] = "700000"
    with status_path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)

    result = qualify_pps_backend(
        candidate,
        independent_run=_make_independent(tmp_path),
        config_path=_fast_config(tmp_path),
    )
    report = _report(result.report_path)
    runtime = report["runtime_backend_identity"]
    assert runtime["all_required_fields_match"] is False
    assert (
        runtime["fields"]["pps_gate.min_interval_us"]["observed"]
        == "700000"
    )
    assert (
        report["acceptance_checks"][
            "runtime_backend_identity_and_config_match"
        ]
        is False
    )


def test_rollover_uses_raw_authoritative_ref_boundaries(tmp_path: Path) -> None:
    candidate = _make_candidate(tmp_path, rollover=True)
    independent = _make_independent(tmp_path)
    result = qualify_pps_backend(
        candidate,
        independent_run=independent,
        config_path=_fast_config(tmp_path),
    )
    report = _report(result.report_path)
    assert report["candidate"]["traceable_window_count"] == 6
    assert report["candidate"]["eligible_window_count"] == 6


def test_reference_only_fault_keeps_count_validity_independent(
    tmp_path: Path,
) -> None:
    candidate = _make_candidate(tmp_path)
    path = candidate / "csv" / "count_observations.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    rows[1][-1] = str(16 | (1 << 3) | (1 << 12))
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)

    result = qualify_pps_backend(
        candidate,
        independent_run=_make_independent(tmp_path),
        config_path=_fast_config(tmp_path),
    )
    report = _report(result.report_path)
    assert report["candidate"]["reference_valid_window_count"] == 5
    assert report["candidate"]["count_valid_window_count"] == 6
    assert report["candidate"]["eligible_window_count"] == 5
    assert report["candidate"]["ineligible_reason_counts"] == {
        "reference_flagged_invalid": 1
    }


def test_count_only_fault_keeps_reference_validity_independent(
    tmp_path: Path,
) -> None:
    candidate = _make_candidate(tmp_path)
    path = candidate / "csv" / "count_observations.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    rows[1][7] = "0"
    rows[1][-1] = str(16 | (1 << 5) | (1 << 9))
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)

    result = qualify_pps_backend(
        candidate,
        independent_run=_make_independent(tmp_path),
        config_path=_fast_config(tmp_path),
    )
    report = _report(result.report_path)
    assert report["candidate"]["reference_valid_window_count"] == 6
    assert report["candidate"]["count_valid_window_count"] == 5
    assert report["candidate"]["eligible_window_count"] == 5
    assert report["candidate"]["ineligible_reason_counts"] == {
        "count_zero": 1
    }


def test_untraceable_boundary_is_preserved_but_ineligible(
    tmp_path: Path,
) -> None:
    candidate = _make_candidate(tmp_path)
    path = candidate / "csv" / "count_observations.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    rows[1][5] = str(TICKS_PER_SECOND + 16)
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)

    result = qualify_pps_backend(
        candidate,
        independent_run=_make_independent(tmp_path),
        config_path=_fast_config(tmp_path),
    )
    report = _report(result.report_path)
    assert report["candidate"]["window_count"] == 6
    assert report["candidate"]["traceable_window_count"] == 5
    assert report["candidate"]["eligible_window_count"] == 5
    assert (
        report["acceptance_checks"]["all_candidate_windows_traceable"]
        is False
    )


def test_comparison_range_excludes_other_valid_windows(
    tmp_path: Path,
) -> None:
    candidate = _make_candidate(tmp_path)
    manifest_path = candidate / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = manifest["phase5_pps_backend_qualification"]
    metadata["comparison_first_count_seq"] = 2
    metadata["comparison_last_count_seq"] = 5
    metadata["service_plane_segments"] = [
        {
            "label": "baseline",
            "mode": "baseline",
            "first_count_seq": 2,
            "last_count_seq": 3,
        },
        {
            "label": "load",
            "mode": "load",
            "first_count_seq": 4,
            "last_count_seq": 5,
        },
    ]
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    count_path = candidate / "csv" / "count_observations.csv"
    rows = list(csv.reader(count_path.open(newline="", encoding="utf-8")))
    rows[1][7] = "20000000"
    rows[6][7] = "20000000"
    with count_path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)
    config_value = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    config_value["minimum_eligible_windows"] = 4
    config_value["minimum_stable_duration_s"] = 4.0
    config_value["minimum_service_plane_windows_per_segment"] = 2
    config_path = tmp_path / "range_config.json"
    config_path.write_text(
        json.dumps(config_value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = qualify_pps_backend(
        candidate,
        independent_run=_make_independent(tmp_path),
        config_path=config_path,
    )
    report = _report(result.report_path)
    assert report["candidate"]["window_count"] == 6
    assert report["candidate"]["comparison_window_count"] == 4
    assert report["candidate"]["eligible_window_count"] == 4
    assert report["candidate"]["frequency"]["mean_hz"] == 10_000_001
    assert report["candidate"]["stable_duration_s"] == 4.0


def test_explicit_source_typing_rejects_mixed_candidate_rows(
    tmp_path: Path,
) -> None:
    candidate = _make_candidate(tmp_path)
    path = candidate / "csv" / "count_observations.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    rows[-1][-2] = "h0_tcxo_16mhz"
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)
    with pytest.raises(ValueError, match="source_domain differs"):
        qualify_pps_backend(
            candidate,
            independent_run=_make_independent(tmp_path),
            config_path=_fast_config(tmp_path),
        )


def test_independent_typing_requires_an_authorised_estimator_backend_pair(
    tmp_path: Path,
) -> None:
    candidate = _make_candidate(tmp_path)
    independent = _make_independent(tmp_path)
    manifest_path = independent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["phase5_pps_backend_qualification"][
        "measurement_backend"
    ] = "OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="estimator/backend path"):
        qualify_pps_backend(
            candidate,
            independent_run=independent,
            config_path=_fast_config(tmp_path),
        )


def test_different_independent_source_domain_is_rejected(
    tmp_path: Path,
) -> None:
    candidate = _make_candidate(tmp_path)
    independent = _make_independent(tmp_path)
    manifest_path = independent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["phase5_pps_backend_qualification"][
        "source_domain"
    ] = "different_oscillator"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    count_path = independent / "csv" / "count_observations.csv"
    rows = list(csv.reader(count_path.open(newline="", encoding="utf-8")))
    rows[1][-2] = "different_oscillator"
    with count_path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)
    with pytest.raises(ValueError, match="source_domain differ"):
        qualify_pps_backend(
            candidate,
            independent_run=independent,
            config_path=_fast_config(tmp_path),
        )


def test_non_observe_only_manifest_cannot_pass_acceptance(
    tmp_path: Path,
) -> None:
    candidate = _make_candidate(tmp_path)
    manifest_path = candidate / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["closed_loop_control"] = True
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result = qualify_pps_backend(
        candidate,
        independent_run=_make_independent(tmp_path),
        config_path=_fast_config(tmp_path),
    )
    report = _report(result.report_path)
    assert (
        report["acceptance_checks"]["candidate_manifest_is_observe_only"]
        is False
    )
    assert report["acceptance_passed"] is False


def test_unavailable_uncertainty_remains_null_and_blocks_acceptance(
    tmp_path: Path,
) -> None:
    candidate = _make_candidate(tmp_path, uncertainty_complete=False)
    independent = _make_independent(tmp_path)
    independent_manifest = independent / "manifest.json"
    value = json.loads(independent_manifest.read_text(encoding="utf-8"))
    value["phase5_pps_backend_qualification"]["uncertainty"][
        "independent_frequency_hz_1sigma"
    ] = None
    independent_manifest.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result = qualify_pps_backend(
        candidate,
        independent_run=independent,
        config_path=_fast_config(tmp_path),
    )
    report = _report(result.report_path)
    assert report["acceptance_checks"]["uncertainty_complete"] is False
    assert report["uncertainty"]["combined_standard_uncertainty_hz"] is None
    assert len(report["uncertainty"]["unavailable_components"]) == 4
    assert report["qualification_state"] == "repository_validation_only"


def test_config_rejects_unknown_fields() -> None:
    value = deepcopy(json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8")))
    value["actuation_enabled"] = True
    with pytest.raises(ValueError, match="fields differ"):
        QualificationConfig.from_mapping(value)
