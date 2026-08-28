#!/usr/bin/env python3
"""Stitch the retained GNSS baud campaign prefix, continuation, and resume.

This is an offline provenance wrapper.  It preserves both failed source
terminals, never subtracts counters across run baselines, and accepts only the
exact 6 + 13 + 2 logical-phase partition frozen by the campaign contracts.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping


PREFIX_KEYS = (
    ("S01", "ordinary"), ("S02", "ordinary"), ("S03", "ordinary"),
    ("S04", "ordinary"), ("S05", "ordinary"), ("S06", "ordinary_entry"),
)
MIDDLE_KEYS = (
    ("S06", "peak_status"), ("S06", "clean_requalification"),
    ("S07", "ordinary_entry"), ("S07", "peak_status"),
    ("S07", "clean_requalification"), ("S08", "ordinary_entry"),
    ("S08", "peak_status"), ("S08", "clean_requalification"),
    ("S09", "ordinary_entry"), ("S09", "peak_status"),
    ("S09", "clean_requalification"), ("S10", "ordinary_entry"),
    ("S10", "peak_status"),
)
TAIL_KEYS = (("S10", "ordinary_soak"), ("S11", "closing_clean_soak"))
ALL_KEYS = PREFIX_KEYS + MIDDLE_KEYS + TAIL_KEYS
BAUDS = (9600, 19200, 38400, 57600, 115200)
FAULT_COUNTERS = (
    "bytes_dropped_before_retention", "hardware_break_count",
    "hardware_framing_count", "hardware_overrun_count",
    "hardware_parity_count", "link_checksum_failure_count",
    "metadata_checksum_failure_count", "overflow_count", "oversize_count",
    "parser_drop_count", "transport_metadata_hold_count", "truncated_count",
)


def _canonical_sha(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _file_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def _events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _uf2_identity(build: Mapping[str, Any]) -> tuple[str, str, str]:
    provenance = build["provenance"]
    uf2 = [item for item in build["artifacts"] if str(item.get("name", "")).endswith(".uf2")]
    if len(uf2) != 1:
        raise ValueError("build manifest does not bind exactly one UF2")
    return (
        str(uf2[0]["sha256"]), str(provenance["source"]["sha256"]),
        str(provenance["configuration"]["sha256"]),
    )


def _source_for_original(run_dir: Path, continuation_contract_sha: str) -> dict[str, str]:
    contract = run_dir / "reports/activated_contract_v1.json"
    event_path = run_dir / "reports/gnss_baud_envelope_supervisor_events_v1.jsonl"
    uf2, source, config = _uf2_identity(_read(run_dir / "reports/activated_firmware_build_manifest_v1.json"))
    return {
        "source_run_id": run_dir.name,
        "source_artifact_sha256": _file_sha(event_path),
        "source_contract_sha256": _file_sha(contract),
        "source_firmware_uf2_sha256": uf2,
        "source_firmware_source_sha256": source,
        "source_firmware_config_sha256": config,
        "original_contract_sha256": _file_sha(contract),
        "continuation_contract_sha256": continuation_contract_sha,
        "counter_domain": "rp2040_timer0_extended",
        "source_counter_baseline_id": f"{run_dir.name}:capture-baseline:1",
    }


def _scope(source: Mapping[str, str]) -> dict[str, str]:
    return {
        "operation": "within_source_closing_minus_opening",
        "source_run_id": source["source_run_id"],
        "source_artifact_sha256": source["source_artifact_sha256"],
        "source_contract_sha256": source["source_contract_sha256"],
        "source_counter_baseline_id": source["source_counter_baseline_id"],
        "counter_domain": source["counter_domain"],
    }


def _phase_durations(run_dir: Path) -> dict[tuple[str, str], int]:
    contract = _read(run_dir / "reports/activated_contract_v1.json")
    durations: dict[tuple[str, str], int] = {}
    for segment in contract["schedule"]["segments"]:
        logical_segment_id = str(segment.get("logical_segment_id", segment["id"]))
        for phase in segment["phases"]:
            key = (logical_segment_id, str(phase["id"]))
            if key in durations:
                raise ValueError(f"duplicate frozen phase duration: {key}")
            durations[key] = int(phase["duration_s"])
    return durations


def _prefix_phases(events: list[dict[str, Any]], source: Mapping[str, str]) -> list[dict[str, Any]]:
    rows = []
    for event in events:
        if event.get("event") != "phase_completed":
            continue
        rows.append({
            "logical_segment_id": str(event["segment_id"]),
            "phase_id": str(event["phase_id"]), "baud": int(event["baud"]),
            "elapsed_ticks": int(event["elapsed_ticks"]),
            "ticks_per_second": 16_000_000,
            "required_duration_s": int(event["required_duration_s"]),
            "status": "completed", "source": dict(source),
            "counter_delta_scope": _scope(source),
            "counter_deltas": dict(event["counter_deltas"]),
            "metrics": dict(event["metrics"]),
        })
    if tuple((r["logical_segment_id"], r["phase_id"]) for r in rows) != PREFIX_KEYS:
        raise ValueError("historical completed prefix differs from frozen 6-phase prefix")
    return rows


def _bound_phases(
    report: Mapping[str, Any],
    source: Mapping[str, str],
    expected: tuple[tuple[str, str], ...],
    durations: Mapping[tuple[str, str], int],
) -> list[dict[str, Any]]:
    rows = list(report.get("phases", []))
    if tuple((str(r.get("logical_segment_id")), str(r.get("phase_id"))) for r in rows) != expected:
        raise ValueError("source completed logical-phase prefix differs")
    for row in rows:
        if row.get("status") != "completed" or row.get("source") != source or row.get("counter_delta_scope") != _scope(source):
            raise ValueError("phase/source/counter-baseline provenance differs")
    return [
        {**dict(row), "required_duration_s": int(durations[key])}
        for row, key in zip(rows, expected, strict=True)
    ]


def stitch(original_dir: Path, predecessor_dir: Path, resume_dir: Path) -> dict[str, Any]:
    original_analysis_path = original_dir / "reports/gnss_baud_envelope_analysis_v1.json"
    predecessor_analysis_path = predecessor_dir / "reports/gnss_baud_envelope_analysis_v1.json"
    resume_analysis_path = resume_dir / "reports/gnss_baud_envelope_analysis_v1.json"
    original = _read(original_analysis_path)
    predecessor = _read(predecessor_analysis_path)
    resume = _read(resume_analysis_path)
    if original.get("evidence_status") != "failed" or original.get("programme_terminal") != "programme_invalid_due_to_platform_or_evidence_failure":
        raise ValueError("original failed terminal differs")
    if predecessor.get("analysis_type") != "otis_gnss_baud_envelope_continuation_analysis_v1" or predecessor.get("evidence_status") != "failed":
        raise ValueError("predecessor failed continuation differs")
    if resume.get("analysis_type") != "otis_gnss_baud_envelope_resume_analysis_v1" or resume.get("evidence_status") != "passed" or resume.get("completion_terminal") != "resume_capture_complete":
        raise ValueError("resume completion differs")
    predecessor_source = dict(predecessor["source"])
    resume_source = dict(resume["source"])
    original_source = _source_for_original(original_dir, predecessor_source["continuation_contract_sha256"])
    for run_dir, report, source in ((predecessor_dir, predecessor, predecessor_source), (resume_dir, resume, resume_source)):
        events_path = run_dir / "reports/gnss_baud_envelope_supervisor_events_v1.jsonl"
        contract_path = run_dir / "reports/activated_contract_v1.json"
        if source["source_run_id"] != run_dir.name or source["source_artifact_sha256"] != _file_sha(events_path) or source["source_contract_sha256"] != _file_sha(contract_path):
            raise ValueError("retained source artifact identity differs")
    if predecessor["source_gap"].get("historical_run_id") != original_dir.name or resume["source_gap"].get("predecessor_run_id") != predecessor_dir.name:
        raise ValueError("three-artifact source gap lineage differs")
    if resume_source.get("original_contract_sha256") != original_source["original_contract_sha256"] or resume_source.get("continuation_contract_sha256") != predecessor_source["source_contract_sha256"]:
        raise ValueError("three-artifact contract lineage differs")
    original_events = _events(original_dir / "reports/gnss_baud_envelope_supervisor_events_v1.jsonl")
    phases = _prefix_phases(original_events, original_source)
    phases += _bound_phases(
        predecessor, predecessor_source, MIDDLE_KEYS,
        _phase_durations(predecessor_dir),
    )
    phases += _bound_phases(
        resume, resume_source, TAIL_KEYS, _phase_durations(resume_dir),
    )
    if tuple((p["logical_segment_id"], p["phase_id"]) for p in phases) != ALL_KEYS:
        raise ValueError("stitched phase sequence differs")
    source_files = []
    for run_dir, analysis_path, report, source in (
        (original_dir, original_analysis_path, original, original_source),
        (predecessor_dir, predecessor_analysis_path, predecessor, predecessor_source),
        (resume_dir, resume_analysis_path, resume, resume_source),
    ):
        source_files.append({
            "run_id": run_dir.name, "analysis_path": str(analysis_path.resolve()),
            "analysis_file_sha256": _file_sha(analysis_path),
            "analysis_content_sha256": str(report["analysis_sha256"]),
            "supervisor_events_sha256": source["source_artifact_sha256"],
            "source": source,
        })
    per_baud: dict[str, Any] = {}
    for baud in BAUDS:
        selected = [p for p in phases if int(p["baud"]) == baud]
        strata = []
        for source_file in source_files:
            local = [p for p in selected if p["source"]["source_run_id"] == source_file["run_id"]]
            if not local:
                continue
            counters = {name: sum(int(p["counter_deltas"].get(name, 0)) for p in local) for name in FAULT_COUNTERS}
            highs = [int(p["metrics"]["ring_high_water"]) for p in local if p.get("metrics", {}).get("ring_high_water") is not None]
            capacities = [int(p["metrics"]["ring_capacity_entries"]) for p in local if p.get("metrics", {}).get("ring_capacity_entries") is not None]
            strata.append({
                "source_run_id": source_file["run_id"], "phase_count": len(local),
                "confirmed_online_seconds": sum(int(p["required_duration_s"]) for p in local),
                "fault_counter_deltas": counters,
                "maximum_raw_ring_high_water": max(highs) if highs else None,
                "raw_ring_capacity": min(capacities) if capacities else None,
                "factor_of_two_observed_headroom": bool(highs and capacities and max(highs) * 2 <= min(capacities)),
                "counter_deltas_combined_across_sources": False,
            })
        robust = bool(strata) and all(not any(s["fault_counter_deltas"].values()) and s["factor_of_two_observed_headroom"] for s in strata)
        per_baud[str(baud)] = {
            "baud": baud, "phase_count": len(selected),
            "confirmed_online_seconds": sum(s["confirmed_online_seconds"] for s in strata),
            "steady_online_class": "operationally_feasible_observed" if robust else "not_operationally_feasible_observed",
            "transition_class": "transition_reliable_observed" if robust else "transition_not_reliable_observed",
            "source_strata": strata,
            "cross_source_counter_aggregation_performed": False,
        }
    eligible = [b for b in BAUDS if per_baud[str(b)]["steady_online_class"] == "operationally_feasible_observed" and per_baud[str(b)]["transition_class"] == "transition_reliable_observed"]
    selected = max(eligible) if eligible else 9600
    bridge = [dict(e) for e in original_events if e.get("event_sequence") in (26, 27)]
    if [e.get("event") for e in bridge] != ["transition_requested", "transition_confirmed"]:
        raise ValueError("historical S06 bridge differs")
    result: dict[str, Any] = {
        "schema_version": 1,
        "analysis_type": "otis_gnss_baud_envelope_three_artifact_composite_analysis_v1",
        "tool": "gnss_baud_envelope_three_artifact_stitch_v1",
        "evidence_status": "passed",
        "terminal": "composite_three_artifact_characterization_complete",
        "ordinary_programme_completion_terminal_permitted": False,
        "source_terminals": [
            {"run_id": original_dir.name, "evidence_status": "failed", "terminal": original["programme_terminal"], "preservation": "preserved_failed_not_reinterpreted_as_success"},
            {"run_id": predecessor_dir.name, "evidence_status": "failed", "terminal": predecessor.get("source_programme_terminal"), "preservation": "preserved_failed_not_reinterpreted_as_success"},
            {"run_id": resume_dir.name, "evidence_status": "passed", "terminal": resume["completion_terminal"]},
        ],
        "source_artifacts": source_files,
        "source_gaps": [dict(predecessor["source_gap"]), dict(resume["source_gap"])],
        "historical_s06_bridge_events": bridge,
        "counter_delta_policy": {
            "rule": "subtract_only_within_one_source_run_artifact_contract_and_counter_baseline",
            "cross_source_subtraction_permitted": False,
            "counter_deltas_aggregated_across_sources": False,
        },
        "completed_logical_phase_count": len(phases),
        "phases": phases,
        "per_baud": per_baud,
        "recommendation": {
            "selected_operational_baud": selected,
            "decision": f"promote_candidate_{selected}" if selected > 9600 else "retain_9600",
            "rule": "highest baud with observed steady feasibility and reliable transitions; otherwise retain 9600",
            "physical_promotion_authorized": False,
        },
    }
    result["analysis_sha256"] = _canonical_sha(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-run-dir", type=Path, required=True)
    parser.add_argument("--predecessor-run-dir", type=Path, required=True)
    parser.add_argument("--resume-run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = stitch(args.original_run_dir, args.predecessor_run_dir, args.resume_run_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output.resolve()), "analysis_sha256": result["analysis_sha256"],
        "evidence_status": result["evidence_status"], "terminal": result["terminal"],
        "recommendation": result["recommendation"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
