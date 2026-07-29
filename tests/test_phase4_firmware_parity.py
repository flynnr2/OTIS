from __future__ import annotations

from pathlib import Path
import csv
import hashlib
import io
import json
import re
import subprocess

import pytest

from host.otis_tools.contracts import (
    CONTROL_PREVIEW_V1_FIELDS,
    ESTIMATE_V1_FIELDS,
    CsvValidationContext,
    validate_csv,
)
from host.otis_tools.phase4_replay import ReplayConfig, replay_phase4


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "profiles" / "plant_models" / "cx317_h1_bench_v2.json"
ENGINE = (
    ROOT
    / "firmware"
    / "arduino"
    / "otis_nano_rp2040_connect"
    / "otis_phase4_engine.cpp"
)
HARNESS = ROOT / "tests" / "cpp" / "phase4_engine_harness.cpp"
LIVE_HARNESS = ROOT / "tests" / "cpp" / "phase4_live_adapter_harness.cpp"
LIVE_ADAPTER = ENGINE.parent / "otis_phase4_observe_preview.cpp"
TICK_HZ = 1_000_000
TOPOLOGY = "h1_run_020_g17_reworked_d14_d10_pps_witness"
BACKEND = (
    "OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE with LOCAL_PPS_INTERPOLATED "
    "host estimator"
)

VALIDITY = {"unavailable": 0, "valid": 1, "invalid": 2, "stale": 3}
DIAGNOSTIC = {"unknown": 0, "healthy": 1, "degraded": 2, "fault": 3}
OBSERVATION_REASON_BITS = {
    "reference_unavailable": 1 << 0,
    "reference_stale": 1 << 1,
    "reference_interval_outlier": 1 << 2,
    "reference_flagged_invalid": 1 << 3,
    "count_unavailable": 1 << 4,
    "count_stale": 1 << 5,
    "count_zero": 1 << 6,
    "count_saturated": 1 << 7,
    "count_sequence_discontinuity": 1 << 8,
    "count_flagged_invalid": 1 << 9,
    "reference_continuity_unavailable": 1 << 26,
}


def _config(**changes: object) -> ReplayConfig:
    values: dict[str, object] = {
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
    references: list[int] | None = None,
    counts: list[tuple[int, ...]] | None = None,
    dac_code: int = 0xA950,
    topology: str = TOPOLOGY,
) -> Path:
    run = root / "run"
    run.mkdir(parents=True)
    references = references if references is not None else list(range(7))
    counts = counts if counts is not None else [
        (seq, seq, 10_000_001) for seq in range(1, 7)
    ]
    manifest = {
        "schema_version": 1,
        "run_id": "phase4_firmware_parity_fixture",
        "template": False,
        "h_phase": "H1",
        "domains": [{"name": "fixture_ticks", "nominal_hz": TICK_HZ}],
        "channels": [
            {"channel_id": 1, "role": "pps_reference"},
            {"channel_id": 2, "role": "oscillator_count"},
        ],
        "oscillator": {"nominal_frequency_hz": 10_000_000.0},
        "phase4_replay": {
            "hardware_topology_id": topology,
            "measurement_backend": BACKEND,
        },
        "files": [
            {"path": "csv/raw_events.csv", "contract": "raw_events_v1"},
            {"path": "csv/count_observations.csv", "contract": "count_observations_v1"},
            {"path": "csv/health.csv", "contract": "health_v1"},
            {"path": "csv/dac_steps.csv", "contract": "dac_steps_v1"},
        ],
    }
    (run / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_csv(
        run / "csv" / "raw_events.csv",
        [
            "record_type", "schema_version", "event_seq", "channel_id", "edge",
            "timestamp_ticks", "capture_domain", "flags",
        ],
        [
            ["REF", 1, seq, 1, "R", second * TICK_HZ, "fixture_ticks", 16]
            for seq, second in enumerate(references, start=1)
        ],
    )
    previous = 0
    count_rows: list[list[object]] = []
    for seq, close, edges, *flags in counts:
        count_rows.append(
            [
                "CNT", 1, seq, 2, previous * TICK_HZ, close * TICK_HZ,
                "fixture_ticks", edges, "R", "h1_ocxo_open_loop",
                flags[0] if flags else 16,
            ]
        )
        previous = close
    _write_csv(
        run / "csv" / "count_observations.csv",
        [
            "record_type", "schema_version", "count_seq", "channel_id",
            "gate_open_ticks", "gate_close_ticks", "gate_domain",
            "counted_edges", "source_edge", "source_domain", "flags",
        ],
        count_rows,
    )
    _write_csv(
        run / "csv" / "health.csv",
        [
            "record_type", "schema_version", "status_seq", "timestamp_ticks",
            "status_domain", "component", "status_key", "status_value",
            "severity", "flags",
        ],
        [
            ["STS", 1, 1, 0, "fixture_ticks", "reference",
             "reference_valid_for_control", "true", "INFO", 0],
            ["STS", 1, 2, 1, "fixture_ticks", "count",
             "count_valid_for_control", "true", "INFO", 0],
        ],
    )
    _write_csv(
        run / "csv" / "dac_steps.csv",
        [
            "record_type", "schema_version", "seq", "elapsed_ms", "step_index",
            "dac_code_requested", "dac_code_applied", "dac_code_clamped",
            "dac_voltage_measured_v", "ocxo_tune_voltage_measured_v",
            "dwell_ms", "event", "flags",
        ],
        [["DAC", 1, 1, 0, -1, dac_code, dac_code, 0, "", "", 0,
          "step_apply", 0]],
    )
    return run


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="session")
def phase4_engine_harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("phase4_engine") / "phase4_engine_harness"
    subprocess.run(
        [
            "c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
            str(HARNESS), str(ENGINE),
            "-I", str(ENGINE.parent), "-o", str(output),
        ],
        check=True,
        cwd=ROOT,
    )
    return output


@pytest.fixture(scope="session")
def phase4_live_adapter_harness(
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    output = tmp_path_factory.mktemp("phase4_live") / "phase4_live_harness"
    subprocess.run(
        [
            "c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-DOTIS_ENABLE_PHASE4_OBSERVE_PREVIEW=1",
            "-DOTIS_FC0_STARTUP_INHIBIT_MS=0",
            str(LIVE_HARNESS), str(LIVE_ADAPTER), str(ENGINE),
            "-I", str(ROOT / "tests" / "cpp" / "stubs"),
            "-I", str(ENGINE.parent), "-o", str(output),
        ],
        check=True,
        cwd=ROOT,
    )
    return output


def _reason_mask(text: str) -> int:
    return sum(
        OBSERVATION_REASON_BITS.get(reason, 0)
        for reason in text.split(";")
        if reason
    )


def _harness_input(
    estimates: list[dict[str, str]],
    previews: list[dict[str, str]],
    config: ReplayConfig,
) -> str:
    lines = [
        ",".join(
            [
                "CONFIG", str(config.startup_inhibit_s),
                str(config.clean_window_requirement),
                str(config.recovery_clean_window_requirement),
                str(config.estimator_window),
                str(config.minimum_estimator_samples),
                str(config.maximum_dispersion_hz), "10000000",
            ]
        )
    ]
    # Fixture REF evidence begins at tick zero; host and live firmware both
    # measure startup qualification from that evidence origin.
    first_ticks = 0
    previous_count = ""
    assert len(estimates) == len(previews)
    for estimate, preview in zip(estimates, previews):
        count_seq = estimate["source_count_seq"]
        new_count = bool(count_seq) and count_seq != previous_count
        previous_count = count_seq
        model_reasons = set(preview["model_reason_codes"].split(";"))
        available = "plant_model_unavailable" not in model_reasons
        valid = "plant_model_invalid" not in model_reasons
        version = "plant_model_version_not_3" not in model_reasons
        topology = "plant_model_topology_mismatch" not in model_reasons
        backend = "plant_model_backend_mismatch" not in model_reasons
        in_range = "input_outside_model_applicability" not in model_reasons
        excluded = "plant_model_excluded_count_sequence" in model_reasons
        gain = "plant_model_unknown_gain" not in model_reasons
        dac = preview["current_dac_code"]
        fields = [
            "OBS",
            estimate["estimator_timestamp_ticks"],
            str(
                (int(estimate["estimator_timestamp_ticks"]) - first_ticks)
                / TICK_HZ
            ),
            str(int(new_count)),
            str(VALIDITY[estimate["reference_validity"]]),
            str(VALIDITY[estimate["count_validity"]]),
            str(int(estimate["reference_continuity"] == "true")),
            str(int(estimate["count_continuity"] == "true")),
            str(DIAGNOSTIC[estimate["diagnostic_health"]]),
            str(_reason_mask(estimate["observation_reason_codes"])),
            str(int(bool(estimate["frequency_observation_hz"]))),
            estimate["frequency_observation_hz"] or "0",
            str(int(available)), str(int(valid)), str(int(version)),
            str(int(topology)), str(int(backend)), str(int(in_range)),
            str(int(excluded)), str(int(gain)),
            preview["hz_per_code"] or "0",
            str(int(bool(dac))), dac or "0",
        ]
        lines.append(",".join(fields))
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize(
    ("case", "run_kwargs", "config"),
    [
        ("nominal", {}, _config()),
        ("startup", {}, _config(startup_inhibit_s=1.5)),
        (
            "post_qualification_zero",
            {"counts": [
                (1, 1, 10_000_000), (2, 2, 10_000_000),
                (3, 3, 10_000_000), (4, 4, 0),
            ]},
            _config(),
        ),
        (
            "post_qualification_saturated",
            {"counts": [
                (1, 1, 10_000_000), (2, 2, 10_000_000),
                (3, 3, 10_000_000), (4, 4, 10_000_000, 1 << 13),
            ]},
            _config(),
        ),
        (
            "missing_count",
            {"counts": []},
            _config(),
        ),
        (
            "stale_count",
            {"counts": [
                (1, 1, 10_000_000), (2, 2, 10_000_000),
                (3, 3, 10_000_000),
            ]},
            _config(),
        ),
        (
            "pps_outlier",
            {"references": [0, 1, 2, 4, 5, 6]},
            _config(),
        ),
        (
            "stale_reference",
            {"references": [0, 1, 2]},
            _config(),
        ),
        (
            "reference_loss_return",
            {
                "references": [0, 1, 2, 3, 6, 7, 8, 9],
                "counts": [
                    (seq, seq, 10_000_000) for seq in range(1, 10)
                ],
            },
            _config(),
        ),
        ("model_input_outside", {"dac_code": 0x9000}, _config()),
        (
            "step_and_range_clamp",
            {
                "dac_code": 0xA800,
                "counts": [
                    (seq, seq, 10_000_100) for seq in range(1, 7)
                ],
            },
            _config(),
        ),
        ("model_identity_mismatch", {"topology": "other"}, _config()),
    ],
)
def test_firmware_engine_matches_host_replay_decisions(
    tmp_path: Path,
    phase4_engine_harness: Path,
    case: str,
    run_kwargs: dict[str, object],
    config: ReplayConfig,
) -> None:
    run = _make_run(tmp_path / case, **run_kwargs)
    _assert_host_firmware_parity(run, MODEL, config, phase4_engine_harness)


def _assert_host_firmware_parity(
    run: Path,
    model_path: Path,
    config: ReplayConfig,
    phase4_engine_harness: Path,
) -> None:
    result = replay_phase4(run, plant_model_path=model_path, config=config)
    estimates = _rows(result.estimates_path)
    previews = _rows(result.previews_path)
    completed = subprocess.run(
        [str(phase4_engine_harness)],
        input=_harness_input(estimates, previews, config),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        cwd=ROOT,
    )
    firmware = list(csv.DictReader(io.StringIO(completed.stdout)))
    assert len(firmware) == len(estimates)
    for estimate, preview, live in zip(estimates, previews, firmware):
        assert live["state"] == preview["control_state"]
        assert live["previous"] == preview["previous_control_state"]
        assert live["transition"] == preview["transition_reason_code"]
        assert live["confidence"] == estimate["estimator_confidence"]
        assert live["samples"] == estimate["accepted_sample_count"]
        assert live["estimate_eligible"] == estimate["preview_eligibility"]
        assert live["preview_eligible"] == preview["preview_eligibility"]
        assert live["preview_available"] == preview["preview_available"]
        assert live["proposed"] == preview["proposed_dac_code"]
        assert live["limited"] == preview["limited_delta_codes"]
        assert live["step_limited"] == preview["step_limited"]
        assert live["range_clamped"] == preview["range_clamped"]
        if estimate["frequency_error_hz"]:
            assert float(live["error_hz"]) == pytest.approx(
                float(estimate["frequency_error_hz"]), abs=1e-9
            )
            assert float(live["dispersion_hz"]) == pytest.approx(
                float(estimate["dispersion_hz"]), abs=1e-9
            )


@pytest.mark.parametrize("kind", ["unavailable", "invalid"])
def test_firmware_engine_matches_host_model_failure_inhibition(
    tmp_path: Path, phase4_engine_harness: Path, kind: str
) -> None:
    run = _make_run(tmp_path / kind)
    model_path = tmp_path / f"{kind}.json"
    if kind == "invalid":
        model_path.write_text("{not-json}\n", encoding="utf-8")
    _assert_host_firmware_parity(
        run, model_path, _config(), phase4_engine_harness
    )


def test_preview_translation_unit_has_no_dac_write_route() -> None:
    source = (
        ROOT
        / "firmware"
        / "arduino"
        / "otis_nano_rp2040_connect"
        / "otis_phase4_observe_preview.cpp"
    ).read_text(encoding="utf-8")
    engine = ENGINE.read_text(encoding="utf-8")
    forbidden = (
        "otis_dac_ad5693r.h",
        "otis_dac_ad5693r_set_raw",
        "Wire.",
        "write-and-update",
    )
    assert all(token not in source for token in forbidden)
    assert all(token not in engine for token in forbidden)
    assert "actuation_authorized = false" in engine
    assert "actionable = false" in engine


def test_firmware_preview_constants_are_bound_to_plant_model_v3() -> None:
    source = LIVE_ADAPTER.read_text(encoding="utf-8")
    model_bytes = MODEL.read_bytes()
    model = json.loads(model_bytes)
    assert hashlib.sha256(model_bytes).hexdigest() in source
    assert model["model_version"] == 3
    assert model["status"]["control_ready"] is False
    assert model["status"]["actuation_enabled"] is False
    assert str(model["plant_response"]["local_slope"]["hz_per_code"]) in source
    applicability = model["plant_response"]["applicability"]["dac_code_range"]
    candidate = model["dac"]["automatic_control_range_codes"]
    assert f"0x{applicability['min']:04X}u" in source
    assert f"0x{applicability['max']:04X}u" in source
    assert f"0x{candidate['min']:04X}u" in source
    assert f"0x{candidate['max']:04X}u" in source
    assert re.search(
        rf"kMaximumPreviewStep = 0x{model['dac']['manual_preview_max_step_codes']:04X}u",
        source,
    )
    profile = json.loads(
        (ROOT / "profiles" / "discipline" / "phase4_host_replay_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert ReplayConfig.from_mapping(profile).config_hash in source


def test_live_est_ctl_rows_match_normative_contracts(
    tmp_path: Path, phase4_live_adapter_harness: Path
) -> None:
    completed = subprocess.run(
        [str(phase4_live_adapter_harness)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        cwd=ROOT,
    )
    lines = [line for line in completed.stdout.splitlines() if line]
    assert next(csv.reader([lines[0]])) == ESTIMATE_V1_FIELDS
    assert next(csv.reader([lines[1]])) == CONTROL_PREVIEW_V1_FIELDS
    estimate_lines = [lines[0], *[line for line in lines[2:] if line.startswith("EST,")]]
    preview_lines = [lines[1], *[line for line in lines[2:] if line.startswith("CTL,")]]
    assert len(estimate_lines) == 8
    assert len(preview_lines) == 8
    estimate_path = tmp_path / "estimates.csv"
    preview_path = tmp_path / "previews.csv"
    estimate_path.write_text("\n".join(estimate_lines) + "\n", encoding="utf-8")
    preview_path.write_text("\n".join(preview_lines) + "\n", encoding="utf-8")
    context = CsvValidationContext(
        contract="estimates_v1",
        known_channels=frozenset(),
        known_domains=frozenset({"rp2040_timer0"}),
    )
    assert validate_csv(estimate_path, context).errors == ()
    preview_context = CsvValidationContext(
        contract="control_previews_v1",
        known_channels=frozenset(),
        known_domains=frozenset({"rp2040_timer0"}),
    )
    assert validate_csv(preview_path, preview_context).errors == ()
    previews = _rows(preview_path)
    estimates = _rows(estimate_path)
    assert estimates[0]["source_count_seq"] == ""
    assert estimates[0]["frequency_observation_hz"] == ""
    assert previews[0]["current_dac_code"] == str(0xA950)
    assert previews[0]["proposed_dac_code"] == ""
    assert all(row["preview_only"] == "true" for row in previews)
    assert all(row["actuation_authorized"] == "false" for row in previews)
    assert all(row["actionable"] == "false" for row in previews)
    assert previews[-1]["preview_available"] == "true"


def test_preview_queue_is_bounded_and_drop_is_telemetry_only() -> None:
    source = (
        ROOT
        / "firmware"
        / "arduino"
        / "otis_nano_rp2040_connect"
        / "otis_phase4_observe_preview.cpp"
    ).read_text(encoding="utf-8")
    assert "queue[OTIS_PHASE4_PREVIEW_QUEUE_DEPTH]" in source
    assert "dropped_telemetry_pair_count" in source
    assert "otis_phase4_engine_evaluate" in source
    # State evaluation happens before enqueue; an output drop cannot feed back.
    assert source.index("otis_phase4_engine_evaluate") < source.index(
        "format_and_enqueue(estimate_seq"
    )


def test_long_clean_engine_run_does_not_wrap_qualification_counter(
    phase4_engine_harness: Path,
) -> None:
    lines = ["CONFIG,0,3,2,5,3,0.25,10000000"]
    for seq in range(1, 301):
        lines.append(
            ",".join(
                [
                    "OBS", str(seq * TICK_HZ), str(seq), "1",
                    "1", "1", "1", "1", "1", "0", "1", "10000000.1",
                    "1", "1", "1", "1", "1", "1", "0", "1",
                    "0.0001673035127775317", "1", str(0xA950),
                ]
            )
        )
    completed = subprocess.run(
        [str(phase4_engine_harness)],
        input="\n".join(lines) + "\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        cwd=ROOT,
    )
    rows = list(csv.DictReader(io.StringIO(completed.stdout)))
    assert len(rows) == 300
    assert rows[-1]["state"] == "ACQUIRE_PREVIEW"
    assert rows[-1]["estimate_eligible"] == "true"
    assert rows[-1]["preview_available"] == "true"
