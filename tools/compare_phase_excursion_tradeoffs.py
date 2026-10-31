"""Finite offline source-shape comparison and explicitly synthetic plant study."""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/50_SOFTWARE/phase_excursion_tradeoff_v1.json"
FW = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
HARNESS = ROOT / "tests/cpp/phase_excursion_tradeoff_harness.cpp"


def cases(contract):
    m = contract["synthetic_model"]
    out = []

    def add(family, gain, fraction, position, drift=0, pulse=0, width=1, noise=0):
        out.append(
            {
                "id": f"case_{len(out):05d}",
                "family": family,
                "gain": gain,
                "fraction": fraction,
                "position": position,
                "drift": drift,
                "pulse": pulse,
                "width": width,
                "noise": noise,
            }
        )

    gains = m["gains_hz_per_code"]
    fractions = m["fractional_count_phases"]
    positions = m["onset_positions_spans"]
    signs = m["signs"]
    nominal = gains[1]
    for g, f, pos, sign, size in itertools.product(
        gains, fractions, positions, signs, m["frequency_step_counts_per_600"]
    ):
        add(1, g, f, pos, sign * size)
    for g, f, pos, sign, size in itertools.product(
        gains, fractions, positions, signs, m["frequency_ramp_target_counts_per_600"]
    ):
        add(2, g, f, pos, sign * size)
    for g, f, pos, sign, size, width in itertools.product(
        gains,
        fractions,
        positions,
        signs,
        m["localized_cycle_changes"],
        m["localized_durations_s"],
    ):
        add(3, g, f, pos, pulse=sign * size, width=width)
    for f, pos, sign, size, pulse_sign, width in itertools.product(
        fractions, positions, signs, (1, 3, 6), signs, m["localized_durations_s"]
    ):
        add(4, nominal, f, pos, sign * size, pulse_sign * 4, width)
    for family, f, pos, sign, size in itertools.product(
        (5, 6), fractions, positions, signs, m["localized_cycle_changes"]
    ):
        add(family, nominal, f, pos, pulse=sign * size)
    for f, pos, sign, noise in itertools.product(
        (0, 0.5), (1, 300, 600), signs, (0.4, 1.5)
    ):
        add(1, nominal, f, pos, sign * 4, noise=noise)
        add(2, nominal, f, pos, sign * 6, noise=noise)
        add(3, nominal, f, pos, pulse=sign * 4, width=1, noise=noise)
        add(3, nominal, f, pos, pulse=sign * 4, width=30, noise=noise)
        add(4, nominal, f, pos, sign * 3, sign * 4, 1, noise)
        add(5, nominal, f, pos, pulse=sign * 4, noise=noise)
    for g, f, noise in itertools.product(
        gains, fractions, m["bounded_reference_phase_jitter_cycles"]
    ):
        add(0, g, f, 1, noise=noise)
    return out


def compile_native(output):
    executable = output / "native_tradeoff"
    subprocess.run(
        [
            shutil.which("c++") or "c++",
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(FW),
            str(HARNESS),
            *(
                str(FW / n)
                for n in (
                    "otis_adaptive_hybrid_regulation.cpp",
                    "otis_adaptive_hybrid_wide.cpp",
                    "otis_integer_count_tight_deadband.cpp",
                )
            ),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return executable


def describe(values):
    v = sorted(values)
    if not v:
        return {"n": 0}
    return {
        "n": len(v),
        "min": v[0],
        "median": v[len(v) // 2],
        "mean": sum(v) / len(v),
        "max": v[-1],
    }


def run(output, quick=False):
    entry_source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    raw_contract = CONTRACT.read_bytes()
    contract = json.loads(raw_contract)
    assert contract["schema"] == "OTIS_PHASE_EXCURSION_TRADEOFF_STUDY_V1"
    assert (
        hashlib.sha256(
            (
                ROOT / "profiles/discipline/adaptive_hybrid_regulation_v1.json"
            ).read_bytes()
        ).hexdigest()
        == contract["baseline_policy_sha256"]
    )
    (output / "FROZEN_CONTRACT.json").write_bytes(raw_contract)
    executable = compile_native(output)
    matrix = cases(contract)
    if quick:
        matrix = matrix[:1] + [
            x
            for x in matrix
            if x["family"] == 3
            and x["gain"] == contract["synthetic_model"]["gains_hz_per_code"][1]
            and x["fraction"] == 0.25
            and x["position"] == 300
            and x["pulse"] == 4
            and x["width"] == 1
        ]
    (output / "cases.json").write_text(json.dumps(matrix, indent=2) + "\n")
    case_file = output / "cases.input"
    case_file.write_text(
        "".join(
            " ".join(
                str(c[k])
                for k in (
                    "id",
                    "family",
                    "gain",
                    "fraction",
                    "position",
                    "drift",
                    "pulse",
                    "width",
                    "noise",
                )
            )
            + "\n"
            for c in matrix
        )
    )
    native_csv = output / "model_results.csv"
    header = [
        "case_id",
        "candidate",
        "first_application_delay_s",
        "first_correctly_directed_application_delay_s",
        "maximum_step_codes",
        "large_applications",
        "applications",
        "absolute_movement_codes",
        "direction_reversals",
        "integrated_absolute_frequency_error_cycles",
        "peak_frequency_error_ppb",
        "time_to_25_percent_reduction_s",
        "model_selections",
        "final_code",
    ]
    with case_file.open() as inp, native_csv.open("w") as out:
        out.write(",".join(header) + "\n")
        out.flush()
        subprocess.run([str(executable), "simulate"], stdin=inp, stdout=out, check=True)
    with native_csv.open() as f:
        rows = [
            {
                k: (
                    row[k]
                    if k == "case_id"
                    else float(row[k])
                    if k
                    in (
                        "integrated_absolute_frequency_error_cycles",
                        "peak_frequency_error_ppb",
                    )
                    else int(row[k])
                )
                for k in header
            }
            for row in csv.DictReader(f)
        ]
    assert len(rows) == len(matrix) * len(contract["candidates"])
    metadata = {c["id"]: c for c in matrix}
    baseline = {r["case_id"]: r for r in rows if r["candidate"] == 0}
    family_names = {
        0: "quiet",
        1: "frequency_step",
        2: "frequency_ramp",
        3: "localized_reference_phase",
        4: "mixed_frequency_and_phase",
        5: "snapshot_offset_and_rebound",
        6: "persistent_counter_offset",
    }
    summary = []
    for family in range(7):
        for policy, name in enumerate(contract["candidates"]):
            selected = [
                r
                for r in rows
                if r["candidate"] == policy
                and metadata[r["case_id"]]["family"] == family
            ]
            if not selected:
                continue
            delays = []
            censored = []
            iae_ratio = []
            for r in selected:
                b = baseline[r["case_id"]]
                key = "first_correctly_directed_application_delay_s"
                if b[key] >= 0 and r[key] >= 0:
                    delays.append(r[key] - b[key])
                elif b[key] >= 0:
                    censored.append(r["case_id"])
                if b["integrated_absolute_frequency_error_cycles"] > 1e-9:
                    iae_ratio.append(
                        r["integrated_absolute_frequency_error_cycles"]
                        / b["integrated_absolute_frequency_error_cycles"]
                    )
            summary.append(
                {
                    "family": family_names[family],
                    "candidate": name,
                    "cases": len(selected),
                    "maximum_step": describe(
                        [r["maximum_step_codes"] for r in selected]
                    ),
                    "cases_with_large_applications": sum(
                        r["large_applications"] > 0 for r in selected
                    ),
                    "movement": describe(
                        [r["absolute_movement_codes"] for r in selected]
                    ),
                    "additional_first_correct_application_delay_s": describe(delays),
                    "no_correct_application_when_baseline_has_one": censored,
                    "integrated_error_ratio_to_baseline": describe(iae_ratio),
                    "model_selection_count": sum(
                        r["model_selections"] for r in selected
                    ),
                }
            )
    result = {
        "schema": "OTIS_PHASE_EXCURSION_TRADEOFF_RESULT_V1",
        "authority": "offline_only",
        "quick_matrix": quick,
        "contract_sha256": hashlib.sha256(raw_contract).hexdigest(),
        "case_count": len(matrix),
        "model_rows": len(rows),
        "methods": contract["candidates"],
        "summary": summary,
        "physical_source_attribution": "not_established",
        "source_hashes": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                Path(__file__),
                HARNESS,
                FW / "otis_adaptive_hybrid_regulation.cpp",
                FW / "otis_adaptive_hybrid_wide.cpp",
                FW / "otis_integer_count_tight_deadband.cpp",
            ]
        },
        "limits": contract["synthetic_model"]["counterfactual_limit"],
    }
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == entry_source_hash
    result["native_input_sha256"] = hashlib.sha256(case_file.read_bytes()).hexdigest()
    result["native_binary_sha256"] = hashlib.sha256(executable.read_bytes()).hexdigest()
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "case_count": len(matrix),
                "rows": len(rows),
                "summary": str(output / "summary.json"),
            },
            indent=2,
        ),
        flush=True,
    )
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()
    run(args.output, args.quick)


if __name__ == "__main__":
    main()
