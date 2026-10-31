"""Retrospective source audit; proposals are checkpoints, never plant replays."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import subprocess
from pathlib import Path

from tools.compare_phase_excursion_tradeoffs import CONTRACT, compile_native

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/adaptive_hybrid/large_steering_steps_20261031.json"


def audit(output):
    output.mkdir(parents=True, exist_ok=True)
    contract = json.loads(CONTRACT.read_bytes())
    fixture = json.loads(FIXTURE.read_bytes())
    assert fixture["schema"] == "OTIS_LARGE_STEERING_STEP_SOURCE_FIXTURE_V1"
    assert fixture["source_zip_sha256"] == contract["source_zip_sha256"]
    assert fixture["absolute_step_selection"] == 10
    executable = compile_native(output)
    records = []
    lines = []
    for case in fixture["applications"]:
        a = case["application"]
        d = case["decision"]
        prior = case["prior_application"]
        e = case["estimate"]
        counts = case["residual_counts"]
        assert len(counts) == 600 and sum(counts) == int(d["edge_error_counts"])
        assert abs(int(a["delta_codes"])) >= 10
        assert e["source_dac_ref"] == "live:DAC:" + d["dac_epoch"]
        assert e["source_acceptance_epoch"] == d["acceptance_epoch"]
        assert (
            e["source_opening_accepted_boundary_ordinal"]
            == d["opening_accepted_boundary"]
        )
        assert (
            e["source_closing_accepted_boundary_ordinal"]
            == d["closing_accepted_boundary"]
        )
        assert int(e["accepted_sample_count"]) == 600
        impulse = [(i + 1, v) for i, v in enumerate(counts) if abs(v) >= 2]
        r = {
            "dac_epoch": int(a["dac_epoch"]),
            "elapsed_days": float(a["elapsed_days"]),
            "recorded_delta_codes": int(a["delta_codes"]),
            "recorded_reason": d["reason"],
            "source_error_counts": sum(counts),
            "nonzero_spans": sum(v != 0 for v in counts),
            "maximum_absolute_span_residual": max(map(abs, counts)),
            "multicycle_spans": impulse,
            "following_applications": case["following_applications"],
        }
        if "ordinary_request_ready" in d["reason"]:
            values = [
                a["dac_epoch"],
                d["timestamp_ticks"],
                prior["timestamp_ticks"],
                d["acceptance_epoch"],
                d["opening_accepted_boundary"],
                d["closing_accepted_boundary"],
                d["dac_epoch"],
                d["applied_code"],
                d["phase_epoch"],
                d["relative_phase_cycles"],
                d["tight_inside"],
                *counts,
            ]
            lines.append(" ".join(map(str, values)) + "\n")
            r["checkpoint_scope"] = (
                "Recorded ordinary-path code/epoch, prior application and raw decision gates; not earlier engine history."
            )
        else:
            r["checkpoint_scope"] = (
                "Maintenance checkpoint needs prior persistence/debt state; no incomplete per-window projection is attributed to it."
            )
        records.append(r)
    result = subprocess.run(
        [str(executable), "project"],
        input="".join(lines),
        capture_output=True,
        text=True,
        check=True,
    )
    names = [
        "dac_epoch",
        "candidate",
        "projected_FLL_counts",
        "projected_delta_codes",
        "confirmation_pending",
        "step_model_selected",
    ]
    projections = [
        dict(zip(names, map(int, row)))
        for row in csv.reader(io.StringIO(result.stdout))
    ]
    for case in records:
        case["projections"] = [
            {
                "candidate": contract["candidates"][r["candidate"]],
                "FLL_counts": r["projected_FLL_counts"],
                "delta_codes": r["projected_delta_codes"],
                "confirmation_pending": bool(r["confirmation_pending"]),
                "step_model_selected": bool(r["step_model_selected"]),
            }
            for r in projections
            if r["dac_epoch"] == case["dac_epoch"]
        ]
        if case["projections"]:
            assert case["projections"][0]["delta_codes"] == case["recorded_delta_codes"]
    summary = {
        "schema": "OTIS_LARGE_STEERING_STEP_AUDIT_V1",
        "authority": "offline_only",
        "fixture_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        "contract_sha256": hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),
        "applications": records,
        "source_zip_sha256": fixture["source_zip_sha256"],
        "source_attribution": "No event is assigned to oscillator or reference by this audit.",
        "counterfactual_scope": "Recorded later counts followed the actual commands; they are not responses to these unissued projections.",
    }
    (output / "large_step_audit.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = audit(a.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
