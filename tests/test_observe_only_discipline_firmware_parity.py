from __future__ import annotations

from pathlib import Path
import copy
import csv
import hashlib
import io
import json
import re
import subprocess
import sys

import pytest

from host.otis_tools.contracts import (
    CONTROL_PREVIEW_V1_FIELDS,
    DIAGNOSTICS_V1_FIELDS,
    ESTIMATE_V2_FIELDS,
    REFERENCE_OBSERVATION_V1_FIELDS,
    CsvValidationContext,
    validate_csv,
)
from host.otis_tools.diagnostics import DEFAULT_DIAGNOSTIC_CONFIG_HASH
from host.otis_tools.reference_quality import ReferenceQualityConfig
from host.otis_tools.observe_only_discipline_replay import ReplayConfig, replay_observe_only_discipline
from host.otis_tools.plant_model import (
    estimator_contract_definition_hash,
    load_plant_model,
    validate_plant_model_semantics,
)
from tools.generate_plant_model_binding import render_binding


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "profiles" / "plant_models" / "cx317_h1_bench_v3.json"
ENGINE = (
    ROOT
    / "firmware"
    / "arduino"
    / "otis_nano_rp2040_connect"
    / "otis_observe_only_discipline_engine.cpp"
)
HARNESS = ROOT / "tests" / "cpp" / "observe_only_discipline_engine_harness.cpp"
LIVE_HARNESS = ROOT / "tests" / "cpp" / "observe_only_discipline_live_harness.cpp"
LIVE_ADAPTER = ENGINE.parent / "otis_observe_only_discipline_live.cpp"
DIAGNOSTIC_ENGINE = ENGINE.parent / "otis_diagnostic_engine.cpp"
DIAGNOSTIC_CATALOG = ENGINE.parent / "otis_diagnostic_catalog.cpp"
REFERENCE_QUALITY = ENGINE.parent / "otis_reference_quality.cpp"
BOUNDARY_ESTIMATOR = ENGINE.parent / "otis_pps_boundary_frequency_estimator.cpp"
MODEL_BINDING = ENGINE.parent / "otis_plant_model_v4_generated.h"
MODEL_BINDING_GENERATOR = ROOT / "tools" / "generate_plant_model_binding.py"
TICK_HZ = 1_000_000
TOPOLOGY = "h1_run_020_g17_reworked_d14_d10_pps_witness"
BACKEND = "OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE"

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
    "plant_model_estimator_method_mismatch": 1 << 27,
    "boundary_pps_support_unavailable": 1 << 28,
    "reference_sequence_nonmonotonic": 1 << 29,
    "boundary_pps_support_overwritten": 1 << 30,
    "pending_count_overwritten": 1 << 31,
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
                "fixture_ticks", edges, "R", "h1_cx317_ocxo_10mhz",
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
            ["STS", 1, 3, 1, "fixture_ticks", "reference_receiver",
             "authority_state", "qualified", "INFO", 0],
            ["STS", 1, 4, 1, "fixture_ticks", "reference_receiver",
             "utc_traceability_state", "valid", "INFO", 0],
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


def _live_harness_rows(
    executable: Path,
    scenario: str = "nominal",
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    completed = subprocess.run(
        [str(executable), scenario],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        cwd=ROOT,
    )
    lines = [line for line in completed.stdout.splitlines() if line]
    estimate_lines = [
        lines[0],
        *[line for line in lines[2:] if line.startswith("EST,")],
    ]
    preview_lines = [
        lines[1],
        *[line for line in lines[2:] if line.startswith("CTL,")],
    ]
    return (
        list(csv.DictReader(estimate_lines)),
        list(csv.DictReader(preview_lines)),
    )


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
            "-DOTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW=1",
            "-DOTIS_ENABLE_DAC_AD5693R=1",
            "-DOTIS_TCXO_COUNTER_BACKEND="
            "OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE",
            "-DOTIS_FC0_STARTUP_INHIBIT_MS=0",
            str(LIVE_HARNESS), str(LIVE_ADAPTER), str(BOUNDARY_ESTIMATOR),
            str(ENGINE), str(DIAGNOSTIC_ENGINE), str(DIAGNOSTIC_CATALOG),
            str(REFERENCE_QUALITY),
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
        version = "plant_model_version_not_4" not in model_reasons
        topology = "plant_model_topology_mismatch" not in model_reasons
        backend = "plant_model_backend_mismatch" not in model_reasons
        method = "plant_model_estimator_method_mismatch" not in model_reasons
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
            str(int(topology)), str(int(backend)), str(int(method)),
            str(int(in_range)),
            str(int(excluded)), str(int(gain)),
            preview["hz_per_code"] or "0",
            str(int(bool(dac))), dac or "0",
            str(
                int(
                    "reference_authority_unqualified"
                    not in estimate["eligibility_reason_codes"].split(";")
                )
            ),
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
    result = replay_observe_only_discipline(run, plant_model_path=model_path, config=config)
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
        / "otis_observe_only_discipline_live.cpp"
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


def test_firmware_preview_constants_are_bound_to_plant_model_v4() -> None:
    source = LIVE_ADAPTER.read_text(encoding="utf-8")
    binding = MODEL_BINDING.read_text(encoding="utf-8")
    model_bytes = MODEL.read_bytes()
    model = json.loads(model_bytes)
    subprocess.run(
        [sys.executable, str(MODEL_BINDING_GENERATOR), "--check"],
        check=True,
        cwd=ROOT,
    )
    assert '#include "otis_plant_model_v4_generated.h"' in source
    assert hashlib.sha256(model_bytes).hexdigest() in binding
    assert model["model_version"] == 4
    assert model["status"]["control_ready"] is False
    assert model["status"]["actuation_enabled"] is False
    method = model["plant_response"]["applicability"][
        "estimator_method_contract"
    ]
    applicability_contract = model["plant_response"]["applicability"]
    assert method["estimator_method_id"] in binding
    assert method["method_definition_hash"] in binding
    assert model["hardware_topology"]["topology_id"] in binding
    assert applicability_contract["mode"] in binding
    assert applicability_contract["measurement_backend"] in binding
    assert str(applicability_contract["gate_duration_s"]) in binding
    assert str(applicability_contract["settling_exclusion_s"]) in binding
    assert str(applicability_contract["temperature_range_c"]["min_c"]) in binding
    assert str(applicability_contract["temperature_range_c"]["max_c"]) in binding
    assert all(
        f"{sequence}u" in binding
        for sequence in applicability_contract["excluded_count_sequences"]
    )
    assert str(model["plant_response"]["local_slope"]["hz_per_code"]) in binding
    applicability = model["plant_response"]["applicability"]["dac_code_range"]
    candidate = model["dac"]["automatic_control_range_codes"]
    assert f"0x{applicability['min']:04X}u" in binding
    assert f"0x{applicability['max']:04X}u" in binding
    assert f"0x{candidate['min']:04X}u" in binding
    assert f"0x{candidate['max']:04X}u" in binding
    assert re.search(
        rf"kMaximumPreviewStep = 0x{model['dac']['manual_preview_max_step_codes']:04X}u",
        binding,
    )
    profile = json.loads(
        (ROOT / "profiles" / "discipline" / "phase4_host_replay_v2.json").read_text(
            encoding="utf-8"
        )
    )
    assert ReplayConfig.from_mapping(profile).config_hash in source


def test_mutated_artifact_applicability_values_change_generated_binding(
    tmp_path: Path,
) -> None:
    changed = copy.deepcopy(load_plant_model(MODEL).data)
    changed["hardware_topology"]["topology_id"] = "mutated_topology"
    applicability = changed["plant_response"]["applicability"]
    applicability["gate_duration_s"] = 301
    applicability["settling_exclusion_s"] = 901
    applicability["temperature_range_c"] = {
        "min_c": 10.0,
        "max_c": 20.0,
    }
    applicability["excluded_count_sequences"] = [11, 12]
    path = tmp_path / "mutated_model.json"
    path.write_text(json.dumps(changed), encoding="utf-8")

    assert validate_plant_model_semantics(changed).valid
    rendered = render_binding(
        path,
        model_ref_override="profiles/plant_models/mutated_model.json",
    )

    assert '"mutated_topology"' in rendered
    assert "kPlantModelGateDurationS = 301" in rendered
    assert "kPlantModelSettlingExclusionS =\n    901" in rendered
    assert "kPlantModelTemperatureMinC =\n    10.0" in rendered
    assert "kPlantModelTemperatureMaxC =\n    20.0" in rendered
    assert "kPlantModelExcludedCountSequences[] = {11u, 12u}" in rendered


def test_binding_generator_rejects_valid_but_incompatible_estimator(
    tmp_path: Path,
) -> None:
    changed = copy.deepcopy(load_plant_model(MODEL).data)
    method = changed["plant_response"]["applicability"][
        "estimator_method_contract"
    ]
    method["reference_time_mapping"] = "future_mapping"
    method["method_definition_hash"] = estimator_contract_definition_hash(
        method
    )
    path = tmp_path / "future_estimator_model.json"
    path.write_text(json.dumps(changed), encoding="utf-8")

    assert validate_plant_model_semantics(changed).valid
    with pytest.raises(ValueError, match="incompatible with the current"):
        render_binding(
            path,
            model_ref_override=(
                "profiles/plant_models/future_estimator_model.json"
            ),
        )


def test_live_preview_compares_generated_applicability_to_runtime_context() -> None:
    source = LIVE_ADAPTER.read_text(encoding="utf-8")
    sketch = (
        ENGINE.parent / "otis_nano_rp2040_connect.ino"
    ).read_text(encoding="utf-8")

    assert "strcmp(kPlantModelTopologyId, kRuntimeTopologyId)" in source
    assert (
        "strcmp(kPlantModelMeasurementBackend,"
        "\n             kRuntimeMeasurementBackend)"
        in source
    )
    assert "observed_gate_duration_acceptable" in source
    assert "OTIS_OBSERVE_ONLY_DISCIPLINE_OBSERVED_GATE_TOLERANCE_US" in source
    assert (
        "fabs(observed_s - kRuntimeConfiguredGateDurationS)"
        in source
    )
    assert "kPlantModelTemperatureMinC" in source
    assert "kPlantModelTemperatureMaxC" in source
    assert "OTIS_OBSERVE_ONLY_DISCIPLINE_TEMPERATURE_MAX_AGE_MS" in source
    assert '"temperature_not_observed"' in source
    assert "kPlantModelSettlingExclusionS" in source
    assert "count_sequence_is_excluded" in source
    assert "replaying_model_source_evidence" in source
    assert sketch.count("otis_observe_only_discipline_live_on_dac_applied(") == 3
    assert (
        "otis_observe_only_discipline_live_on_dac_applied(\n"
        "        request.requested_code, otis_capture_ticks_now())"
        in sketch
    )
    assert (
        "otis_observe_only_discipline_live_on_temperature(\n"
        "        false, 0.0f, otis_capture_ticks_now())"
        in sketch
    )


@pytest.mark.parametrize(
    "scenario",
    [
        "gate_plus_1us",
        "gate_minus_1us",
        "gate_plus_1ms",
        "gate_minus_1ms",
    ],
)
def test_live_gate_aperture_tolerance_accepts_normal_service_latency(
    phase4_live_adapter_harness: Path,
    scenario: str,
) -> None:
    estimates, previews = _live_harness_rows(
        phase4_live_adapter_harness, scenario
    )

    assert estimates[-1]["observation_validity"] == "valid"
    assert "count_flagged_invalid" not in estimates[-1][
        "observation_reason_codes"
    ]
    assert previews[-1]["model_applicability"] == "applicable"
    assert previews[-1]["preview_available"] == "false"
    assert "reference_authority_unqualified" in previews[-1][
        "eligibility_reason_codes"
    ]


def test_egregious_live_gate_aperture_is_observation_quality_failure(
    phase4_live_adapter_harness: Path,
) -> None:
    estimates, previews = _live_harness_rows(
        phase4_live_adapter_harness, "gate_egregious"
    )

    assert estimates[-1]["observation_validity"] == "invalid"
    assert "count_flagged_invalid" in estimates[-1][
        "observation_reason_codes"
    ]
    assert previews[-1]["model_applicability"] == "applicable"
    assert previews[-1]["preview_available"] == "false"


@pytest.mark.parametrize(
    ("scenario", "applicable"),
    [
        ("settling_boundary", True),
        ("settling_straddling", False),
    ],
)
def test_dac_settling_requires_the_entire_count_window_after_cutoff(
    phase4_live_adapter_harness: Path,
    scenario: str,
    applicable: bool,
) -> None:
    _, previews = _live_harness_rows(
        phase4_live_adapter_harness, scenario
    )

    assert (
        previews[-1]["model_applicability"] == "applicable"
    ) is applicable
    assert (
        "count_window_inside_model_settling_exclusion"
        in previews[-1]["model_reason_codes"]
    ) is (not applicable)
    assert previews[-1]["preview_available"] == "false"
    assert "reference_authority_unqualified" in previews[-1][
        "eligibility_reason_codes"
    ]


@pytest.mark.parametrize(
    ("scenario", "extra_reason"),
    [
        ("temperature_missing", None),
        ("temperature_loss", None),
        ("temperature_stale", "temperature_observation_stale"),
    ],
)
def test_temperature_unavailable_loss_and_staleness_block_applicability(
    phase4_live_adapter_harness: Path,
    scenario: str,
    extra_reason: str | None,
) -> None:
    _, previews = _live_harness_rows(
        phase4_live_adapter_harness, scenario
    )
    reasons = previews[-1]["model_reason_codes"].split(";")

    assert previews[-1]["model_applicability"] == "not_applicable"
    assert "temperature_not_observed" in reasons
    if extra_reason is not None:
        assert extra_reason in reasons
    assert previews[-1]["preview_available"] == "false"


def test_out_of_range_temperature_has_specific_model_reason(
    phase4_live_adapter_harness: Path,
) -> None:
    _, previews = _live_harness_rows(
        phase4_live_adapter_harness, "temperature_outside"
    )

    assert previews[-1]["model_applicability"] == "not_applicable"
    assert "input_outside_model_temperature_range" in previews[-1][
        "model_reason_codes"
    ]
    assert previews[-1]["preview_available"] == "false"


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
    assert next(csv.reader([lines[0]])) == ESTIMATE_V2_FIELDS
    assert next(csv.reader([lines[1]])) == CONTROL_PREVIEW_V1_FIELDS
    assert next(csv.reader([lines[2]])) == REFERENCE_OBSERVATION_V1_FIELDS
    assert next(csv.reader([lines[3]])) == DIAGNOSTICS_V1_FIELDS
    estimate_lines = [lines[0], *[line for line in lines[2:] if line.startswith("EST,")]]
    preview_lines = [lines[1], *[line for line in lines[2:] if line.startswith("CTL,")]]
    reference_lines = [
        lines[2], *[line for line in lines[4:] if line.startswith("RFO,")]
    ]
    diagnostic_lines = [
        lines[3], *[line for line in lines[4:] if line.startswith("DIAG,")]
    ]
    assert len(estimate_lines) == 9
    assert len(preview_lines) == 9
    estimate_path = tmp_path / "estimates.csv"
    preview_path = tmp_path / "previews.csv"
    reference_path = tmp_path / "reference_observations.csv"
    diagnostic_path = tmp_path / "diagnostics.csv"
    estimate_path.write_text("\n".join(estimate_lines) + "\n", encoding="utf-8")
    preview_path.write_text("\n".join(preview_lines) + "\n", encoding="utf-8")
    reference_path.write_text("\n".join(reference_lines) + "\n", encoding="utf-8")
    diagnostic_path.write_text("\n".join(diagnostic_lines) + "\n", encoding="utf-8")
    context = CsvValidationContext(
        contract="estimates_v2",
        known_channels=frozenset(),
        known_domains=frozenset({"rp2040_timer0"}),
    )
    assert validate_csv(estimate_path, context).errors == ()
    reference_context = CsvValidationContext(
        contract="reference_observations_v1",
        known_channels=frozenset(),
        known_domains=frozenset({"rp2040_timer0"}),
    )
    assert validate_csv(reference_path, reference_context).errors == ()
    diagnostic_context = CsvValidationContext(
        contract="diagnostics_v1",
        known_channels=frozenset(),
        known_domains=frozenset({"rp2040_timer0"}),
    )
    assert validate_csv(diagnostic_path, diagnostic_context).errors == ()
    preview_context = CsvValidationContext(
        contract="control_previews_v1",
        known_channels=frozenset(),
        known_domains=frozenset({"rp2040_timer0"}),
    )
    assert validate_csv(preview_path, preview_context).errors == ()
    previews = _rows(preview_path)
    estimates = _rows(estimate_path)
    references = _rows(reference_path)
    diagnostics = _rows(diagnostic_path)
    assert estimates[0]["source_count_seq"] == ""
    assert estimates[0]["frequency_observation_hz"] == ""
    assert previews[0]["current_dac_code"] == str(0xA950)
    assert previews[0]["proposed_dac_code"] == ""
    assert all(row["preview_only"] == "true" for row in previews)
    assert all(row["actuation_authorized"] == "false" for row in previews)
    assert all(row["actionable"] == "false" for row in previews)
    assert all(
        "boundary_pps_support_overwritten"
        not in row["observation_reason_codes"]
        for row in estimates
    )
    assert previews[-1]["preview_available"] == "false"
    assert "reference_authority_unqualified" in previews[-1][
        "eligibility_reason_codes"
    ]
    assert estimates[-1]["estimator_timestamp_ticks"] == str(
        1803 * 16_000_000
    )
    assert float(estimates[-1]["frequency_observation_hz"]) == pytest.approx(
        10_000_001.333333334
    )
    assert {row["config_hash"] for row in diagnostics} == {
        DEFAULT_DIAGNOSTIC_CONFIG_HASH
    }
    assert all(
        not row["first_evidence_refs"].startswith("live:evidence_at:")
        and row["latest_evidence_refs"]
        for row in diagnostics
    )
    assert {row["config_hash"] for row in references} == {
        ReferenceQualityConfig().config_hash
    }


def test_live_and_replay_est2_uncertainty_semantics_match(
    tmp_path: Path, phase4_live_adapter_harness: Path
) -> None:
    run = _make_run(tmp_path / "host")
    replay = replay_observe_only_discipline(
        run, plant_model_path=MODEL, config=_config()
    )
    unavailable_run = _make_run(
        tmp_path / "host_unavailable", counts=[]
    )
    unavailable_replay = replay_observe_only_discipline(
        unavailable_run, plant_model_path=MODEL, config=_config()
    )
    host_rows = [
        *_rows(replay.estimates_path),
        *_rows(unavailable_replay.estimates_path),
    ]
    live_rows, _ = _live_harness_rows(phase4_live_adapter_harness)
    fields = (
        "uncertainty_status",
        "uncertainty_reason_codes",
        "count_quantization_standard_uncertainty_hz",
        "counter_aperture_standard_uncertainty_hz",
        "reference_standard_uncertainty_hz",
        "calibration_standard_uncertainty_hz",
        "model_standard_uncertainty_hz",
        "combined_standard_uncertainty_hz",
        "coverage_factor",
        "expanded_uncertainty_hz",
        "correlation_policy",
        "uncertainty_model_ref",
    )
    for status in ("unavailable", "incomplete"):
        host = next(row for row in host_rows if row["uncertainty_status"] == status)
        live = next(row for row in live_rows if row["uncertainty_status"] == status)
        assert {field: host[field] for field in fields} == {
            field: live[field] for field in fields
        }
def test_preview_queue_is_bounded_and_drop_is_telemetry_only() -> None:
    source = (
        ROOT
        / "firmware"
        / "arduino"
        / "otis_nano_rp2040_connect"
        / "otis_observe_only_discipline_live.cpp"
    ).read_text(encoding="utf-8")
    assert "queue[OTIS_OBSERVE_ONLY_DISCIPLINE_PREVIEW_QUEUE_DEPTH]" in source
    assert "dropped_telemetry_pair_count" in source
    assert "last_diagnosed_drop_count" in source
    assert "dropped_pairs > last_diagnosed_drop_count" in source
    assert "otis_observe_only_discipline_engine_evaluate" in source
    # State evaluation happens before enqueue; an output drop cannot feed back.
    assert source.index("otis_observe_only_discipline_engine_evaluate") < source.index(
        "format_and_enqueue(estimate_seq"
    )


def test_output_backpressure_diagnostic_is_eventually_raised_and_cleared(
    phase4_live_adapter_harness: Path,
) -> None:
    completed = subprocess.run(
        [str(phase4_live_adapter_harness), "output_backpressure"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        cwd=ROOT,
    )
    lines = [line for line in completed.stdout.splitlines() if line]
    diagnostic_lines = [
        lines[3], *[line for line in lines[4:] if line.startswith("DIAG,")]
    ]
    diagnostics = list(csv.DictReader(diagnostic_lines))
    output_loss = [
        row
        for row in diagnostics
        if row["diagnostic_id"] == "diag.output.loss"
    ]
    assert [row["transition"] for row in output_loss] == ["raised", "cleared"]
    assert output_loss[0]["control_effect"] == "none"
    assert output_loss[0]["first_evidence_refs"].startswith("live:REF:")
    assert not output_loss[0]["first_evidence_refs"].startswith(
        "live:evidence_at:"
    )


def test_live_resource_registry_failure_raises_and_clears(
    phase4_live_adapter_harness: Path,
) -> None:
    completed = subprocess.run(
        [str(phase4_live_adapter_harness), "resource_failure"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        cwd=ROOT,
    )
    lines = [line for line in completed.stdout.splitlines() if line]
    diagnostics = list(
        csv.DictReader(
            [
                lines[3],
                *[line for line in lines[4:] if line.startswith("DIAG,")],
            ]
        )
    )
    transitions = [
        row["transition"]
        for row in diagnostics
        if row["diagnostic_id"] == "diag.resource.failure"
    ]
    assert transitions == ["raised", "cleared"]


def test_boundary_support_and_pending_count_are_fixed_capacity() -> None:
    header = (
        ENGINE.parent / "otis_pps_boundary_frequency_estimator.h"
    ).read_text(encoding="utf-8")
    source = BOUNDARY_ESTIMATOR.read_text(encoding="utf-8")
    adapter = LIVE_ADAPTER.read_text(encoding="utf-8")
    assert "#define OTIS_PPS_BOUNDARY_SUPPORT_CAPACITY 384u" in header
    assert "points[OTIS_PPS_BOUNDARY_SUPPORT_CAPACITY]" in header
    assert "PendingCount pending_count" in adapter
    assert "pending_count_overwrite_count" in adapter
    forbidden = ("malloc(", "calloc(", "realloc(", "new ", "std::vector")
    assert all(token not in source for token in forbidden)
    assert all(token not in adapter for token in forbidden)


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
                    "1", "1", "1", "1", "1", "1", "1", "0", "1",
                    "0.0001673035127775317", "1", str(0xA950),
                    "1",
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


def test_firmware_engine_inhibits_estimator_method_mismatch(
    phase4_engine_harness: Path,
) -> None:
    lines = ["CONFIG,0,1,1,1,1,0.25,10000000"]
    lines.append(
        ",".join(
            [
                "OBS", str(TICK_HZ), "1", "1",
                "1", "1", "1", "1", "1", "0", "1", "10000000",
                "1", "1", "1", "1", "1", "0", "1", "0", "1",
                "0.0001673035127775317", "1", str(0xA950),
                "1",
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
    row = list(csv.DictReader(io.StringIO(completed.stdout)))[0]
    assert row["estimate_eligible"] == "true"
    assert row["preview_eligible"] == "false"
    assert row["preview_available"] == "false"
    assert int(row["model_mask"]) & (1 << 27)
