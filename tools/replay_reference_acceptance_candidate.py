#!/usr/bin/env python3
"""Assess the unwired native PPS policy against retained raw observations.

This is a counterfactual design check, never a historical seal, qualification,
capture owner or source of control authority. Outputs must be outside the
source package and in a new directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from host.otis_tools.raw_measurement_replay import (  # noqa: E402
    _ordered_reference_association,
    _raw_count_replay,
)

POLICY = ROOT / "data_contracts/reference_acceptance_policy_v1.json"
HEADER = ROOT / "firmware/arduino/otis_nano_rp2040_connect/otis_reference_acceptance.h"
HARNESS = ROOT / "tests/cpp/reference_acceptance_harness.cpp"
POLICY_ARGUMENTS = (
    "nominal_interval_ticks", "tolerance_ticks", "acquisition_intervals",
    "maximum_edge_rate_hz", "allowed_reference_flags",
    "maximum_excluded_candidates_per_span", "maximum_count_span_ticks",
)


def binding(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": sha256(data).hexdigest(), "size_bytes": len(data)}


def assess(source: Path, output: Path) -> dict[str, object]:
    source, output = source.resolve(), output.resolve()
    if output == source or source in output.parents:
        raise ValueError("assessment output must be outside the source package")
    paths = {name: source / "csv" / filename for name, filename in (
        ("REF", "reference_events.csv"), ("SNP", "pps_snapshots.csv"),
        ("CNT", "count_observations.csv"),
    )}
    inputs = {name: binding(path) for name, path in paths.items()}
    rows = {}
    for name, path in paths.items():
        with path.open(encoding="utf-8", newline="") as stream:
            rows[name] = list(csv.DictReader(stream))
    snapshots, references, counts = rows["SNP"], rows["REF"], rows["CNT"]
    if len(snapshots) < 2 or len({row["session"] for row in snapshots}) != 1:
        raise ValueError("assessment requires a retained single-session SNP sequence")
    # The first received CNT may have closed at the first retained snapshot.
    # It is retained but unproved; this design exercise does not repair it.
    prefix_count = int(bool(counts) and (
        counts[0]["count_seq"], counts[0]["gate_close_ticks"]
    ) == (snapshots[0]["snapshot_sequence"], snapshots[0]["reference_timestamp_ticks"]))
    exact, raw_report, intervals = _raw_count_replay(
        snapshots, references, counts[prefix_count:],
    )
    if not exact or len(intervals) != len(snapshots) - 1:
        raise ValueError("retained adjacent raw pairs do not reconstruct: " + "; ".join(raw_report["errors"]))
    associations = _ordered_reference_association(snapshots, references)
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if policy.get("control_authority") is not False or policy.get("implementation_stage") != "native_candidate":
        raise ValueError("this tool is only for the unwired candidate policy")
    compiler = shutil.which("c++")
    if compiler is None:
        raise ValueError("a native C++ compiler is required")
    implementation = {name: binding(path) for name, path in (
        ("policy", POLICY), ("header", HEADER), ("harness", HARNESS),
        ("assessment_tool", Path(__file__)),
        ("raw_reconstruction", ROOT / "host/otis_tools/raw_measurement_replay.py"),
    )}
    output.mkdir(parents=True, exist_ok=False)
    executable = output / "reference_acceptance_trace"
    compile_command = [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic",
                       str(HARNESS), "-I", str(HEADER.parent), "-o", str(executable)]
    with (output / "compile.log").open("w") as log:
        subprocess.run(compile_command, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=60)
    trace_input = output / "native_input.txt"
    with trace_input.open("w", encoding="utf-8") as stream:
        for snapshot, ref_index in zip(snapshots, associations):
            values = [snapshot[name] for name in (
                "session", "snapshot_sequence", "reference_sequence",
                "reference_timestamp_ticks", "cumulative_down_counter", "status",
            )]
            stream.write("O " + " ".join([*values, references[ref_index]["flags"]]) + "\n")
    trace_output = output / "native_outcomes.jsonl"
    command = [str(executable), *(str(policy[key]) for key in POLICY_ARGUMENTS)]
    with trace_input.open("r") as inputs_stream, trace_output.open("w") as outcomes_stream:
        subprocess.run(command, stdin=inputs_stream, stdout=outcomes_stream, check=True, timeout=60)
    dispositions: Counter[str] = Counter()
    epochs: set[int] = set()
    bridged, losses = [], []
    accepted_count = accepted_edges = 0
    with trace_output.open() as stream:
        for line in stream:
            result = json.loads(line)
            dispositions[result["disposition"]] += 1
            if result["has_span"]:
                accepted_count += 1
                accepted_edges += result["counted_edges"]
                epochs.add(result["acceptance_epoch"])
                if result["excluded_candidate_count"]:
                    bridged.append(result)
            if result["disposition"] in {"qualification_lost", "invalid_policy", "frontier_rejected"}:
                losses.append(result)
    if sum(dispositions.values()) != len(snapshots):
        raise ValueError("native trace omitted or duplicated observation outcomes")
    for name, path in paths.items():
        if binding(path) != inputs[name]:
            raise ValueError("source CSV changed during assessment")
    for value in implementation.values():
        if binding(Path(str(value["path"]))) != value:
            raise ValueError("candidate implementation changed during assessment")
    summary = {
        "classification": "counterfactual_reference_policy_assessment",
        "historical_qualification_or_seal": False,
        "control_authority": False, "physical_actions_performed": 0,
        "source_package": str(source), "source_files": inputs,
        "unproved_leading_count_rows": prefix_count,
        "paired_observations": len(snapshots), "exact_retained_raw_pairs": len(intervals),
        "implementation": implementation, "native_binary": binding(executable),
        "compile_command": compile_command, "native_command": command,
        "native_input": binding(trace_input), "native_outcomes": binding(trace_output),
        "dispositions": dict(dispositions), "accepted_spans": accepted_count,
        "accepted_span_edges": accepted_edges, "acceptance_epochs": sorted(epochs),
        "bridged_spans": bridged, "qualification_losses": losses,
        "expiry_frontier_path_exercised": False,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = assess(args.source, args.output)
    print(json.dumps({key: result[key] for key in (
        "classification", "paired_observations", "unproved_leading_count_rows",
        "accepted_spans", "acceptance_epochs", "dispositions",
    )}, indent=2))


if __name__ == "__main__":
    main()
