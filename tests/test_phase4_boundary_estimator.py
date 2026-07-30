from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import io
import json
import subprocess

import pytest

from host.otis_tools.phase4_boundary_estimator import (
    BoundaryPpsTimeMapper,
    ESTIMATOR_METHOD_DEFINITION_HASH,
    ESTIMATOR_METHOD_ID,
)
from host.otis_tools.phase4_replay import ReplayConfig, replay_phase4


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware" / "arduino" / "otis_nano_rp2040_connect"
HARNESS = ROOT / "tests" / "cpp" / "phase4_boundary_estimator_harness.cpp"
MODEL = ROOT / "profiles" / "plant_models" / "cx317_h1_bench_v3.json"


@dataclass(frozen=True)
class Ref:
    seq: int
    ticks: int
    flags: int = 16


def _mapper(
    ticks: list[int],
    *,
    seqs: list[int] | None = None,
    flags: list[int] | None = None,
) -> BoundaryPpsTimeMapper:
    seqs = seqs or list(range(1, len(ticks) + 1))
    flags = flags or [16] * len(ticks)
    return BoundaryPpsTimeMapper.from_references(
        [
            Ref(seq=seq, ticks=tick, flags=flag)
            for seq, tick, flag in zip(seqs, ticks, flags)
        ],
        domain_hz=1_000_000.0,
        nominal_interval_s=1.0,
        interval_tolerance_s=0.2,
    )


@pytest.mark.parametrize(
    ("ticks", "gate", "edges", "expected_seconds"),
    [
        ([0, 1_000_000, 2_000_000], (0, 2_000_000), 20_000_000, 2.0),
        (
            [0, 1_000_000, 2_200_000, 3_000_000],
            (500_000, 2_600_000),
            20_000_000,
            2.0,
        ),
        (
            [0, 999_900, 2_000_100, 3_000_000],
            (400_000, 2_700_000),
            23_000_000,
            pytest.approx(2.3, abs=3e-4),
        ),
        (
            [index * 1_000_000 for index in range(351)],
            (250_000, 349_750_000),
            3_495_000_000,
            349.5,
        ),
    ],
)
def test_boundary_interpolation_valid_cases(
    ticks: list[int],
    gate: tuple[int, int],
    edges: int,
    expected_seconds: object,
) -> None:
    result = _mapper(ticks).estimate_gate(*gate, edges)
    assert result.valid
    assert result.gate_seconds == expected_seconds
    assert result.frequency_hz == pytest.approx(edges / result.gate_seconds)


def test_boundary_interpolation_handles_unwrapped_rollover() -> None:
    wrap = (1 << 32) * 16
    ticks = [wrap - 1_000_000, wrap, wrap + 1_000_000, wrap + 2_000_000]
    result = _mapper(ticks).estimate_gate(
        wrap - 500_000,
        wrap + 1_500_000,
        20_000_000,
    )
    assert result.valid
    assert result.gate_seconds == pytest.approx(2.0)
    assert result.frequency_hz == pytest.approx(10_000_000.0)


@pytest.mark.parametrize(
    ("mapper", "gate", "edges", "reason"),
    [
        (
            _mapper([1_000_000, 2_000_000, 3_000_000]),
            (500_000, 2_500_000),
            20_000_000,
            "missing_pps_before_or_after_count_window_start",
        ),
        (
            _mapper([0, 1_000_000, 2_000_000]),
            (500_000, 2_500_000),
            20_000_000,
            "missing_pps_before_or_after_count_window_end",
        ),
        (
            _mapper([0, 1_000_000, 2_500_000, 3_500_000]),
            (500_000, 3_000_000),
            25_000_000,
            "count_window_crosses_invalid_pps_segment",
        ),
        (
            _mapper(
                [0, 1_000_000, 2_000_000, 3_000_000],
                flags=[16, 16, 1, 16],
            ),
            (500_000, 2_500_000),
            20_000_000,
            "missing_pps_before_or_after_count_window_end",
        ),
        (
            _mapper(
                [0, 1_000_000, 2_000_000, 3_000_000],
                seqs=[1, 2, 1, 2],
            ),
            (500_000, 2_500_000),
            20_000_000,
            "count_window_crosses_invalid_pps_segment",
        ),
        (
            _mapper([0, 1_000_000, 2_000_000]),
            (1_500_000, 1_500_000),
            1,
            "invalid_count_window",
        ),
        (
            _mapper([0, 1_000_000, 2_000_000]),
            (500_000, 1_500_000),
            0,
            "count_zero",
        ),
    ],
)
def test_boundary_interpolation_rejects_invalid_support(
    mapper: BoundaryPpsTimeMapper,
    gate: tuple[int, int],
    edges: int,
    reason: str,
) -> None:
    result = mapper.estimate_gate(*gate, edges)
    assert not result.valid
    assert reason in result.reason_codes


@pytest.fixture(scope="session")
def firmware_boundary_harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("phase4_boundary") / "harness"
    subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(HARNESS),
            str(FIRMWARE / "otis_phase4_boundary_estimator.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(output),
        ],
        check=True,
        cwd=ROOT,
    )
    return output


@pytest.mark.parametrize(
    ("ticks", "gate", "edges"),
    [
        ([0, 1_000_000, 2_000_000], (0, 2_000_000), 20_000_000),
        (
            [0, 1_000_000, 2_200_000, 3_000_000],
            (500_000, 2_600_000),
            20_000_000,
        ),
        ([0, 1_000_000, 2_500_000, 3_500_000], (500_000, 3_000_000), 1),
        ([0, 1_000_000, 2_000_000], (500_000, 2_500_000), 1),
        ([0, 1_000_000, 2_000_000], (1_500_000, 1_500_000), 1),
    ],
)
def test_exact_firmware_estimator_matches_host(
    firmware_boundary_harness: Path,
    ticks: list[int],
    gate: tuple[int, int],
    edges: int,
) -> None:
    refs = [Ref(seq=index, ticks=tick) for index, tick in enumerate(ticks, 1)]
    host = _mapper(ticks).estimate_gate(*gate, edges)
    lines = [
        f"REF,{ref.seq},{ref.ticks},{ref.flags},1" for ref in refs
    ]
    lines.append(f"GATE,{gate[0]},{gate[1]},{edges}")
    completed = subprocess.run(
        [str(firmware_boundary_harness)],
        input="\n".join(lines) + "\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        cwd=ROOT,
    )
    row = next(csv.reader(io.StringIO(completed.stdout)))
    assert (row[0] == "true") is host.valid
    if host.valid:
        assert float(row[3]) == pytest.approx(host.gate_seconds, abs=1e-12)
        assert float(row[4]) == pytest.approx(host.frequency_hz, abs=1e-9)
        assert [int(value) for value in row[5:9]] == [
            host.pps_before_open_seq,
            host.pps_after_open_seq,
            host.pps_before_close_seq,
            host.pps_after_close_seq,
        ]
    else:
        assert row[1] in host.reason_codes


def test_semantic_mismatch_changes_result_and_model_contract_rejects_it(
    tmp_path: Path,
) -> None:
    ticks = [0, 1_000_000, 2_200_000, 3_000_000]
    gate_open = 500_000
    gate_close = 2_600_000
    edges = 20_000_000
    corrected = _mapper(ticks).estimate_gate(gate_open, gate_close, edges)
    latest_interval_tick_rate = ticks[2] - ticks[1]
    previous_frequency = edges / (
        (gate_close - gate_open) / latest_interval_tick_rate
    )
    assert corrected.valid
    assert corrected.frequency_hz == pytest.approx(10_000_000.0)
    assert previous_frequency == pytest.approx(11_428_571.42857143)
    assert corrected.frequency_hz != pytest.approx(previous_frequency)

    run = _write_replay_fixture(
        tmp_path / "run",
        ticks=ticks,
        gate=(gate_open, gate_close),
        edges=edges,
    )
    config = ReplayConfig.from_mapping(
        {
            "startup_inhibit_s": 0,
            "clean_window_requirement": 1,
            "minimum_estimator_samples": 1,
            "estimator_window": 1,
            "count_max_age_s": 5,
        }
    )
    corrected_result = replay_phase4(
        run,
        plant_model_path=MODEL,
        config=config,
    )
    estimate = _read_rows(corrected_result.estimates_path)[0]
    preview = _read_rows(corrected_result.previews_path)[0]
    assert float(estimate["frequency_observation_hz"]) == pytest.approx(
        corrected.frequency_hz
    )
    assert preview["model_applicability"] == "applicable"

    mismatched_model = json.loads(MODEL.read_text(encoding="utf-8"))
    mismatched_model["plant_response"]["applicability"][
        "estimator_method_contract"
    ]["boundary_interpolation"] = "one_recent_pps_interval_full_gate_scaling"
    mismatch_path = tmp_path / "mismatched_model.json"
    mismatch_path.write_text(
        json.dumps(mismatched_model, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    mismatch_run = _write_replay_fixture(
        tmp_path / "mismatch_run",
        ticks=ticks,
        gate=(gate_open, gate_close),
        edges=edges,
    )
    mismatch_result = replay_phase4(
        mismatch_run,
        plant_model_path=mismatch_path,
        config=config,
    )
    mismatch_preview = _read_rows(mismatch_result.previews_path)[0]
    assert mismatch_preview["model_applicability"] == "not_applicable"
    assert (
        "plant_model_estimator_method_mismatch"
        in mismatch_preview["model_reason_codes"]
    )
    assert mismatch_preview["preview_available"] == "false"


def test_method_identity_and_hash_are_stable() -> None:
    assert ESTIMATOR_METHOD_ID == "LOCAL_PPS_BOUNDARY_INTERPOLATED_V1"
    assert (
        ESTIMATOR_METHOD_DEFINITION_HASH
        == "af4afcb01f9f22b2f1102d278cf17a80d15f37f72da4016666d4278e4fb37e3b"
    )


def test_historical_outputs_and_model_are_not_reinterpreted(
    tmp_path: Path,
) -> None:
    ticks = [0, 1_000_000, 2_000_000]
    run = _write_replay_fixture(
        tmp_path / "historical",
        ticks=ticks,
        gate=(0, 2_000_000),
        edges=20_000_000,
    )
    historical = run / "derived" / "phase4_replay_v1" / "estimates_v1.csv"
    historical.parent.mkdir(parents=True)
    historical.write_text(
        "estimator_version\nphase4_frequency_mean_v1\n",
        encoding="utf-8",
    )
    historical_bytes = historical.read_bytes()
    config = ReplayConfig.from_mapping(
        {
            "startup_inhibit_s": 0,
            "clean_window_requirement": 1,
            "minimum_estimator_samples": 1,
            "estimator_window": 1,
        }
    )
    result = replay_phase4(run, plant_model_path=MODEL, config=config)
    assert result.output_dir.name == "phase4_replay_v2"
    assert historical.read_bytes() == historical_bytes
    assert _read_rows(result.estimates_path)[0]["estimator_version"] == (
        "LOCAL_PPS_BOUNDARY_INTERPOLATED_V1"
    )

    old_model_run = _write_replay_fixture(
        tmp_path / "old_model",
        ticks=ticks,
        gate=(0, 2_000_000),
        edges=20_000_000,
    )
    old_model = (
        ROOT / "profiles" / "plant_models" / "cx317_h1_bench_v2.json"
    )
    old_result = replay_phase4(
        old_model_run,
        plant_model_path=old_model,
        config=config,
    )
    preview = _read_rows(old_result.previews_path)[0]
    assert preview["model_applicability"] == "not_applicable"
    assert "plant_model_version_not_4" in preview["model_reason_codes"]
    assert (
        "plant_model_estimator_method_mismatch"
        in preview["model_reason_codes"]
    )
    assert preview["preview_available"] == "false"


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, fields: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(fields)
        writer.writerows(rows)


def _write_replay_fixture(
    root: Path,
    *,
    ticks: list[int],
    gate: tuple[int, int],
    edges: int,
) -> Path:
    root.mkdir()
    manifest = {
        "schema_version": 1,
        "run_id": root.name,
        "template": False,
        "h_phase": "H1",
        "stage": "SW2_PHASE4_HOST_REPLAY",
        "domains": [{"name": "fixture_ticks", "nominal_hz": 1_000_000}],
        "channels": [
            {"channel_id": 1, "role": "pps_reference"},
            {"channel_id": 2, "role": "oscillator_count"},
        ],
        "oscillator": {"nominal_frequency_hz": 10_000_000.0},
        "phase4_replay": {
            "hardware_topology_id": "h1_run_020_g17_reworked_d14_d10_pps_witness",
            "measurement_backend": "OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE",
        },
        "files": [
            {"path": "csv/ref.csv", "contract": "raw_events_v1"},
            {"path": "csv/cnt.csv", "contract": "count_observations_v1"},
            {"path": "csv/sts.csv", "contract": "health_v1"},
            {"path": "csv/dac.csv", "contract": "dac_steps_v1"},
        ],
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(
        root / "csv" / "ref.csv",
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
            ["REF", 1, seq, 1, "R", tick, "fixture_ticks", 16]
            for seq, tick in enumerate(ticks, 1)
        ],
    )
    _write_csv(
        root / "csv" / "cnt.csv",
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
        [["CNT", 1, 1, 2, gate[0], gate[1], "fixture_ticks", edges, "R", "h1_ocxo_open_loop", 16]],
    )
    evaluation_tick = ticks[-1]
    _write_csv(
        root / "csv" / "sts.csv",
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
            ["STS", 1, 1, evaluation_tick, "fixture_ticks", "reference", "reference_valid_for_control", "true", "INFO", 0],
            ["STS", 1, 2, evaluation_tick, "fixture_ticks", "count", "count_valid_for_control", "true", "INFO", 0],
        ],
    )
    _write_csv(
        root / "csv" / "dac.csv",
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
        [["DAC", 1, 1, 0, -1, 43344, 43344, 0, "", "", 0, "step_apply", 0]],
    )
    return root
