"""Finite, zero-authority epoch305 source-shape and baseline-sensitivity study."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import shutil
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "docs/50_SOFTWARE/phase_excursion_comparison_v1.json"
DEFAULT_FIXTURE = (
    ROOT / "tests/fixtures/adaptive_hybrid/epoch305_count_excursion_20261031.json"
)
FW = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def shape(counts):
    return {
        "signed_count_total": sum(counts),
        "nonzero_span_count": sum(v != 0 for v in counts),
        "maximum_absolute_single_span_count": max(map(abs, counts)),
        "first_half_count_total": sum(counts[:300]),
        "second_half_count_total": sum(counts[300:]),
    }


def reconstruct(window):
    rows = window["raw_snp"]
    estimate = window["estimate"]
    assert len(rows) == 601 and int(estimate["accepted_sample_count"]) == 600
    assert rows[0][0] == int(estimate["source_opening_snapshot_sequence"])
    assert rows[-1][0] == int(estimate["source_closing_snapshot_sequence"])
    residual = []
    for opening, closing in itertools.pairwise(rows):
        assert closing[0] == opening[0] + 1
        dt = (closing[2] - opening[2]) & 0xFFFFFFFF
        assert 998750 <= dt - closing[3] and dt + opening[3] <= 1001250
        residual.append(((opening[1] - closing[1]) & 0xFFFFFFFF) - 10000000)
    assert abs(float(estimate["frequency_error_hz"]) * 600 - sum(residual)) < 0.0001
    return residual


def analyze(contract_path=DEFAULT_CONTRACT, fixture_path=DEFAULT_FIXTURE):
    contract = json.loads(contract_path.read_bytes())
    fixture = json.loads(fixture_path.read_bytes())
    before = deepcopy(fixture)
    assert contract["schema"] == "OTIS_PHASE_EXCURSION_OFFLINE_COMPARISON_V1"
    assert fixture["schema"] == "OTIS_EPOCH305_SOURCE_FIXTURE_V1"
    assert fixture["source_clock_domain"] == "rp2040_monotonic_us32"
    assert fixture["raw_downcounter_domain"] == "pio_cumulative_d8_downcounter_u32"
    assert fixture["source_zip_sha256"] == contract["source_zip_sha256"]
    assert fixture["instrument_session"] == contract["instrument_session"]
    policy = ROOT / "profiles/discipline/adaptive_hybrid_regulation_v1.json"
    assert (
        hashlib.sha256(policy.read_bytes()).hexdigest()
        == contract["baseline_policy_sha256"]
    )
    windows = {w["name"]: reconstruct(w) for w in fixture["windows"]}
    synthetic = []
    for case in contract["synthetic_traces"]:
        stages = []
        for key in ("first", "next"):
            counts = [0] * 600
            for pos, value in case[key]:
                assert type(pos) is int and 1 <= pos <= 600 and type(value) is int
                counts[pos - 1] += value
            stages.append(shape(counts))
        synthetic.append({"name": case["name"], "first": stages[0], "next": stages[1]})
    decision = fixture["decision"]
    response = fixture["response"]
    application = fixture["application"]
    assert application["dac_epoch"] == response["dac_epoch"] == "305"
    assert (
        application["session"] == response["session"] == fixture["instrument_session"]
    )
    assert response["delta_codes"] == decision["delta_codes"] == "-20"
    assert int(response["opening_accepted_boundary"]) == int(
        next(
            w["estimate"]["source_opening_accepted_boundary_ordinal"]
            for w in fixture["windows"]
            if w["name"] == "response_post"
        )
    )
    with tempfile.TemporaryDirectory(prefix="otis-excursion-") as tmp:
        exe = Path(tmp) / "native"
        subprocess.run(
            [
                shutil.which("c++") or "c++",
                "-std=c++17",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                str(FW),
                str(ROOT / "tests/cpp/phase_excursion_comparison_harness.cpp"),
                *(
                    str(FW / n)
                    for n in (
                        "otis_adaptive_hybrid_regulation.cpp",
                        "otis_adaptive_hybrid_wide.cpp",
                        "otis_regulation_transaction.cpp",
                    )
                ),
                "-o",
                str(exe),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        def native(args):
            return json.loads(
                subprocess.run(
                    [str(exe), *map(str, args)],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
            )

        args = [
            "decision",
            decision["timestamp_ticks"],
            decision["capture_session"],
            decision["acceptance_epoch"],
            decision["opening_accepted_boundary"],
            decision["closing_accepted_boundary"],
            decision["dac_epoch"],
            decision["applied_code"],
            decision["edge_error_counts"],
            decision["phase_epoch"],
            decision["relative_phase_cycles"],
            decision["tight_inside"],
            fixture["prior_application"]["timestamp_ticks"],
            1,
        ]
        aggregate = native(args)
        assert (
            aggregate["delta_codes"] == int(decision["delta_codes"])
            and aggregate["reason"] == decision["reason"]
        )
        for case in synthetic:
            projected = list(args)
            projected[8] = case["first"]["signed_count_total"]
            case["recorded_phase_arithmetic_projection"] = native(projected)
        conditional = list(args)
        conditional[8] = 0
        conditional_projection = native(conditional)
        comparisons = []
        post = sum(windows["response_post"]) / 600
        baselines = [
            sum(windows["selected_pre"]) / 600,
            sum(windows["pre_minus_1"]) / 600,
            (sum(windows["pre_minus_2"]) + sum(windows["pre_minus_1"])) / 1200,
        ]
        for name, pre in zip(contract["response_comparisons"], baselines):
            comparisons.append(
                {
                    "pre_baseline": name,
                    "pre_error_hz": pre,
                    "post_error_hz": post,
                    "observed_difference_hz": post - pre,
                    "fresh_state_local_classifier": native(
                        ["response", pre, post, -20]
                    ),
                }
            )
    assert before == fixture
    return {
        "schema": "OTIS_PHASE_EXCURSION_COMPARISON_RESULT_V1",
        "authority": "offline_diagnostic_only",
        "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "source_zip_sha256": fixture["source_zip_sha256"],
        "source_windows": {name: shape(counts) for name, counts in windows.items()},
        "synthetic_shapes": synthetic,
        "recorded_native_aggregate_projection": aggregate,
        "conditional_zero_FLL_retained_phase_projection": conditional_projection,
        "native_projection_scope": "Initialized arithmetic checkpoint at recorded code/epoch and preceding application; ordinary request resets maintenance debt. Not full historical engine/response-state replay and no counterfactual plant response.",
        "response_comparisons": comparisons,
        "frozen_response_classification": 5,
        "source_identity": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in (
                "tools/analyze_phase_excursion_case.py",
                "tests/cpp/phase_excursion_comparison_harness.cpp",
                "firmware/arduino/otis_nano_rp2040_connect/otis_adaptive_hybrid_regulation.cpp",
                "firmware/arduino/otis_nano_rp2040_connect/otis_adaptive_hybrid_wide.cpp",
                "firmware/arduino/otis_nano_rp2040_connect/otis_regulation_transaction.cpp",
            )
        },
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = analyze()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
