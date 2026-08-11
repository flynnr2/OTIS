"""Replay a frozen bounded hybrid-preview grid without authority."""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import argparse
import csv
import json
import math
from typing import Any

from .phase_frequency_hybrid_preview import (
    HybridCandidateEngine,
    HybridPreviewDecision,
    HybridPreviewSuite,
    load_profile as load_hybrid_profile,
)
from .reference_relative_phase_estimator import (
    CandidateEstimate,
    CandidateSuite,
    PhaseRecord,
    RelativePhaseAccumulator,
    Snapshot,
    load_profile as load_phase_profile,
)
from .relative_phase_candidate_replay import (
    DEFAULT_CORPUS,
    REPO_ROOT,
    _atomic_json,
    _candidate_file,
    _declared_runs,
    _rates,
    _read_csv,
    _sha256_file,
)


DEFAULT_OUTPUT = (
    REPO_ROOT
    / "runs/cx318_relative_phase_hybrid_preview/campaign_20260808T110942Z/"
    "stage3/stage3_hybrid_replay_v1.json"
)
FINAL_CX317_QUALIFICATION = (
    "runs/cx317_bounded_closed_loop_acquisition/campaign_20260803T080615Z/"
    "stage7/part_b_final_20260807T073432Z"
)


def _dac_events(run_dir: Path) -> list[tuple[float, int]]:
    path = _candidate_file(run_dir, ["csv/dac_steps.csv", "csv/dac.csv"])
    if path is None:
        return []
    result: list[tuple[float, int]] = []
    for row in _read_csv(path):
        if not row.get("elapsed_ms") or row.get("flags", "0") not in {"", "0"}:
            continue
        requested = row.get("dac_code_requested")
        applied = row.get("dac_code_applied")
        if not applied or requested and requested != applied:
            continue
        code = int(applied)
        if 43008 <= code <= 43776:
            result.append((float(row["elapsed_ms"]) / 1000.0, code))
    return sorted(set(result))


def _recursive_codes(value: Any) -> list[tuple[str, int]]:
    keys = {"start_code", "initial_code", "fixed_code", "dac_code", "fail_static_code"}
    result: list[tuple[str, int]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, (int, float)) and float(item).is_integer():
                code = int(item)
                if 43008 <= code <= 43776:
                    result.append((key, code))
            result.extend(_recursive_codes(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(_recursive_codes(item))
    return result


def _start_code(
    manifest: dict[str, Any],
    dac_events: list[tuple[float, int]],
    profile: dict[str, Any],
) -> tuple[int, str]:
    active = manifest.get("active_campaign")
    if isinstance(active, dict) and isinstance(active.get("start_code"), int):
        return int(active["start_code"]), "run_manifest.active_campaign.start_code"
    codes = _recursive_codes(manifest)
    if codes:
        return codes[0][1], f"run_manifest_recursive.{codes[0][0]}"
    if dac_events:
        return dac_events[0][1], "first_accepted_dac_event"
    return (
        int(profile["numerical_policy"]["counterfactual_seed_code_when_source_unavailable"]),
        "profile_counterfactual_seed_source_code_unavailable",
    )


class _Metrics:
    def __init__(self) -> None:
        self.output_count = 0
        self.frequency_events = 0
        self.decision_count = 0
        self.correction_count = 0
        self.step_limited_count = 0
        self.range_clamped_count = 0
        self.phase_step_count = 0
        self.reference_loss_count = 0
        self.recovery_count = 0
        self.state_counts: Counter[str] = Counter()
        self.reason_counts: Counter[str] = Counter()
        self.first_timestamp: float | None = None
        self.first_frequency_s: float | None = None
        self.first_hybrid_s: float | None = None
        self.observed_frequency_square_sum = 0.0
        self.modeled_frequency_square_sum = 0.0
        self.frequency_count = 0
        self.residual_square_sum = 0.0
        self.residual_count = 0
        self.residual_min = math.inf
        self.residual_max = -math.inf
        self.frequency_term_square_sum = 0.0
        self.phase_bias_square_sum = 0.0
        self.combined_square_sum = 0.0
        self.contribution_count = 0
        self.phase_cap_count = 0
        self.segments: dict[str, dict[str, float]] = {}
        self.last_state: str | None = None
        self.last_shadow_code = 0
        self.path_codes = 0
        self.alternations = 0
        self.minimum_range_distance = math.inf
        self.terminal_fault = False

    def update(self, value: HybridPreviewDecision, cap_hz: float) -> None:
        self.output_count += 1
        self.first_timestamp = value.timestamp_s if self.first_timestamp is None else self.first_timestamp
        elapsed = value.timestamp_s - self.first_timestamp
        self.state_counts[value.preview_state] += 1
        self.reason_counts[value.decision_reason] += 1
        if value.frequency_observation_event:
            self.frequency_events += 1
            if self.first_frequency_s is None:
                self.first_frequency_s = elapsed
            if value.observed_frequency_error_hz is not None and value.modeled_frequency_error_hz is not None:
                self.frequency_count += 1
                self.observed_frequency_square_sum += value.observed_frequency_error_hz**2
                self.modeled_frequency_square_sum += value.modeled_frequency_error_hz**2
        if value.preview_state == "HYBRID_TRACKING_PREVIEW" and self.first_hybrid_s is None:
            self.first_hybrid_s = elapsed
        if value.counterfactual_decision:
            self.decision_count += 1
            if (
                value.frequency_term_hz is not None
                and value.combined_desired_frequency_change_hz is not None
            ):
                self.contribution_count += 1
                self.frequency_term_square_sum += value.frequency_term_hz**2
                self.phase_bias_square_sum += value.phase_bias_hz**2
                self.combined_square_sum += value.combined_desired_frequency_change_hz**2
                if math.isclose(abs(value.phase_bias_hz), cap_hz, abs_tol=1e-15):
                    self.phase_cap_count += 1
        if value.counterfactual_correction:
            self.correction_count += 1
        self.step_limited_count += int(value.step_limited)
        self.range_clamped_count += int(value.range_clamped)
        self.phase_step_count += int(value.decision_reason == "phase_step_hold_started")
        self.reference_loss_count += int(value.preview_state == "REFERENCE_LOST_PREVIEW" and self.last_state != value.preview_state)
        self.recovery_count += int(value.preview_state == "RECOVER_PREVIEW" and self.last_state == "REFERENCE_LOST_PREVIEW")
        self.last_state = value.preview_state
        residual = value.modeled_relative_phase_cycles - value.raw_relative_phase_cycles
        self.residual_count += 1
        self.residual_square_sum += residual * residual
        self.residual_min = min(self.residual_min, residual)
        self.residual_max = max(self.residual_max, residual)
        key = f"phase_epoch_{value.phase_epoch}:dac_epoch_{value.dac_epoch}"
        segment = self.segments.setdefault(
            key,
            {
                "raw_start": float(value.raw_relative_phase_cycles),
                "raw_end": float(value.raw_relative_phase_cycles),
                "raw_min": float(value.raw_relative_phase_cycles),
                "raw_max": float(value.raw_relative_phase_cycles),
                "model_start": value.modeled_relative_phase_cycles,
                "model_end": value.modeled_relative_phase_cycles,
                "model_min": value.modeled_relative_phase_cycles,
                "model_max": value.modeled_relative_phase_cycles,
            },
        )
        segment["raw_end"] = float(value.raw_relative_phase_cycles)
        segment["raw_min"] = min(segment["raw_min"], value.raw_relative_phase_cycles)
        segment["raw_max"] = max(segment["raw_max"], value.raw_relative_phase_cycles)
        segment["model_end"] = value.modeled_relative_phase_cycles
        segment["model_min"] = min(segment["model_min"], value.modeled_relative_phase_cycles)
        segment["model_max"] = max(segment["model_max"], value.modeled_relative_phase_cycles)
        self.last_shadow_code = value.shadow_code_after
        self.path_codes = value.cumulative_movement_codes
        self.alternations = value.alternating_correction_count
        self.minimum_range_distance = min(
            self.minimum_range_distance,
            value.shadow_code_after - 43008,
            43776 - value.shadow_code_after,
        )
        self.terminal_fault = self.terminal_fault or value.preview_state == "FAULT_PREVIEW"

    def finalize(self) -> dict[str, Any]:
        raw_movement = sum(abs(v["raw_end"] - v["raw_start"]) for v in self.segments.values())
        modeled_movement = sum(abs(v["model_end"] - v["model_start"]) for v in self.segments.values())
        raw_range = sum(v["raw_max"] - v["raw_min"] for v in self.segments.values())
        modeled_range = sum(v["model_max"] - v["model_min"] for v in self.segments.values())
        observed_rms = (
            math.sqrt(self.observed_frequency_square_sum / self.frequency_count)
            if self.frequency_count
            else None
        )
        modeled_rms = (
            math.sqrt(self.modeled_frequency_square_sum / self.frequency_count)
            if self.frequency_count
            else None
        )
        return {
            "output_count": self.output_count,
            "frequency_observation_count": self.frequency_events,
            "counterfactual_decision_count": self.decision_count,
            "counterfactual_correction_count": self.correction_count,
            "cumulative_movement_codes": self.path_codes,
            "alternating_correction_count": self.alternations,
            "step_limited_count": self.step_limited_count,
            "range_clamped_count": self.range_clamped_count,
            "minimum_code_range_distance": None if math.isinf(self.minimum_range_distance) else self.minimum_range_distance,
            "terminal_shadow_code": self.last_shadow_code,
            "terminal_fault_preview": self.terminal_fault,
            "phase_step_count": self.phase_step_count,
            "reference_loss_count": self.reference_loss_count,
            "recovery_count": self.recovery_count,
            "first_frequency_acquired_s": self.first_frequency_s,
            "first_hybrid_tracking_s": self.first_hybrid_s,
            "observed_600s_frequency_rms_hz": observed_rms,
            "modeled_600s_frequency_rms_hz": modeled_rms,
            "frequency_rms_degradation_hz": (
                modeled_rms - observed_rms
                if modeled_rms is not None and observed_rms is not None
                else None
            ),
            "modeled_phase_residual_rms_cycles": (
                math.sqrt(self.residual_square_sum / self.residual_count)
                if self.residual_count
                else None
            ),
            "modeled_phase_residual_range_cycles": (
                self.residual_max - self.residual_min if self.residual_count else None
            ),
            "observed_phase_absolute_segment_movement_cycles": raw_movement,
            "modeled_phase_absolute_segment_movement_cycles": modeled_movement,
            "phase_movement_reduction_cycles": raw_movement - modeled_movement,
            "observed_phase_segment_range_cycles": raw_range,
            "modeled_phase_segment_range_cycles": modeled_range,
            "frequency_term_rms_hz_at_decisions": (
                math.sqrt(self.frequency_term_square_sum / self.contribution_count)
                if self.contribution_count
                else None
            ),
            "phase_bias_rms_hz_at_decisions": (
                math.sqrt(self.phase_bias_square_sum / self.contribution_count)
                if self.contribution_count
                else None
            ),
            "combined_term_rms_hz_at_decisions": (
                math.sqrt(self.combined_square_sum / self.contribution_count)
                if self.contribution_count
                else None
            ),
            "phase_bias_cap_count": self.phase_cap_count,
            "preview_state_counts": dict(sorted(self.state_counts.items())),
            "decision_reason_counts": dict(sorted(self.reason_counts.items())),
            "phase_dac_epoch_metrics": dict(sorted(self.segments.items())),
        }


def _digest_update(digest: Any, value: HybridPreviewDecision) -> None:
    payload = (
        value.candidate_id,
        value.phase_epoch,
        value.observation_sequence,
        value.dac_epoch,
        round(value.modeled_relative_phase_cycles, 12),
        None if value.modeled_frequency_error_hz is None else round(value.modeled_frequency_error_hz, 15),
        round(value.phase_bias_hz, 15),
        value.shadow_code_after,
        value.band_state_after,
        value.preview_state,
        value.decision_reason,
        value.counterfactual_correction,
    )
    digest.update(repr(payload).encode("utf-8"))


def replay_run(
    item: dict[str, str],
    *,
    corpus: dict[str, Any],
    phase_profile: dict[str, Any],
    phase_configuration_sha256: str,
    hybrid_profile: dict[str, Any],
) -> dict[str, Any]:
    run_dir = REPO_ROOT / item["path"]
    adequacy = corpus["adequate_raw_input"]
    manifest_path = run_dir / adequacy["required_run_manifest"]
    snapshot_path = _candidate_file(run_dir, adequacy["snapshot_candidates"])
    count_path = _candidate_file(run_dir, adequacy["count_candidates"])
    missing = [
        name
        for name, path in (
            ("run_manifest", manifest_path if manifest_path.is_file() else None),
            ("snapshots", snapshot_path),
            ("counts", count_path),
        )
        if path is None
    ]
    base = {"class": item["class"], "path": item["path"], "discovery_status": item.get("discovery_status", "explicit")}
    if missing:
        return {**base, "status": "missing_or_inadequate_raw_source", "missing": missing, "preview_records_generated": 0}
    assert snapshot_path is not None and count_path is not None
    source_paths = [manifest_path, snapshot_path, count_path]
    before_hashes = {path.relative_to(run_dir).as_posix(): _sha256_file(path) for path in source_paths}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    nominal_edges, timer_hz, period_ns = _rates(manifest, item.get("nominal_frequency_hz_override"))
    counts = _read_csv(count_path)
    count_by_sequence = {int(row["count_seq"]): row for row in counts}
    snapshots = _read_csv(snapshot_path)
    if len(snapshots) < int(adequacy["minimum_snapshot_rows"]):
        return {**base, "status": "missing_or_inadequate_raw_source", "missing": ["minimum_snapshot_rows"], "preview_records_generated": 0}
    events = _dac_events(run_dir)
    event_times = [item[0] for item in events]
    start_code, start_provenance = _start_code(manifest, events, hybrid_profile)
    raw_engine = RelativePhaseAccumulator(
        nominal_edges=nominal_edges,
        timer_ticks_per_second=timer_hz,
        period_ns_per_cycle=period_ns,
        configuration_sha256=phase_configuration_sha256,
        reference_interval_minimum_s=float(phase_profile["validity"]["reference_interval_minimum_s"]),
        reference_interval_maximum_s=float(phase_profile["validity"]["reference_interval_maximum_s"]),
        reference_timestamp_modulus_ticks=timer_hz * (1 << 32) // 1_000_000,
    )
    phase_candidates = CandidateSuite(phase_profile)
    nominal_suite = HybridPreviewSuite(hybrid_profile, start_code=start_code)
    sensitivity_suites: dict[str, HybridPreviewSuite] = {}
    if item["path"] == FINAL_CX317_QUALIFICATION:
        gains = hybrid_profile["numerical_policy"]["gain_hz_per_code"]
        sensitivity_suites = {
            label: HybridPreviewSuite(hybrid_profile, start_code=start_code, gain_hz_per_code=float(gains[label]))
            for label in ("minimum", "maximum")
        }
    nominal_metrics = {item["candidate_id"]: _Metrics() for item in hybrid_profile["candidates"]}
    sensitivity_metrics = {
        label: {item["candidate_id"]: _Metrics() for item in hybrid_profile["candidates"]}
        for label in sensitivity_suites
    }
    caps = {item["candidate_id"]: float(item["phase_bias_cap_hz"]) for item in hybrid_profile["candidates"]}
    digest = sha256()
    previous_raw_timestamp: int | None = None
    unwrapped_timestamp = 0
    invalid_records = 0
    for row in snapshots:
        snapshot = Snapshot(
            session=int(row["session"]),
            snapshot_sequence=int(row["snapshot_sequence"]),
            cumulative_down_counter=int(row["cumulative_down_counter"]),
            reference_sequence=int(row["reference_sequence"]),
            reference_timestamp_ticks=int(row["reference_timestamp_ticks"]),
            status=int(row["status"]),
            backend=row["backend"],
        )
        count = count_by_sequence.get(snapshot.snapshot_sequence)
        flags = int(count["flags"]) if count is not None else 0
        qualified = count is not None and flags & ~16 == 0
        counted_edges = int(count["counted_edges"]) if count is not None else None
        if previous_raw_timestamp is None:
            unwrapped_timestamp = snapshot.reference_timestamp_ticks
        else:
            unwrapped_timestamp += (snapshot.reference_timestamp_ticks - previous_raw_timestamp) % (timer_hz * (1 << 32) // 1_000_000)
        previous_raw_timestamp = snapshot.reference_timestamp_ticks
        timestamp_s = unwrapped_timestamp / timer_hz
        event_index = bisect_right(event_times, timestamp_s) - 1
        actual_code = events[event_index][1] if event_index >= 0 else start_code
        dac_epoch = event_index + 1
        phase_record = raw_engine.process(
            snapshot,
            counted_edges=counted_edges,
            reference_qualified=qualified,
            dac_epoch=dac_epoch,
        )
        estimates = phase_candidates.process(phase_record)
        raw_estimate = next((value for value in estimates if value.candidate_id == "CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1"), None)
        invalid_records += int(raw_estimate is None)
        nominal_outputs = nominal_suite.process(
            phase_record,
            raw_estimate,
            timestamp_s=timestamp_s,
            actual_applied_code=actual_code,
        )
        for output in nominal_outputs:
            nominal_metrics[output.candidate_id].update(output, caps[output.candidate_id])
            _digest_update(digest, output)
        for label, suite in sensitivity_suites.items():
            for output in suite.process(
                phase_record,
                raw_estimate,
                timestamp_s=timestamp_s,
                actual_applied_code=actual_code,
            ):
                sensitivity_metrics[label][output.candidate_id].update(output, caps[output.candidate_id])
    after_hashes = {path.relative_to(run_dir).as_posix(): _sha256_file(path) for path in source_paths}
    return {
        **base,
        "status": "replayed",
        "source_sha256": before_hashes,
        "sources_unchanged": before_hashes == after_hashes,
        "snapshot_rows": len(snapshots),
        "invalid_phase_input_records": invalid_records,
        "start_code": start_code,
        "start_code_provenance": start_provenance,
        "actual_dac_event_count": len(events),
        "preview_records_generated": len(snapshots) * len(hybrid_profile["candidates"]),
        "nominal_preview_sha256": digest.hexdigest(),
        "candidate_metrics": {key: value.finalize() for key, value in sorted(nominal_metrics.items())},
        "gain_sensitivity": {
            label: {key: value.finalize() for key, value in sorted(metrics.items())}
            for label, metrics in sorted(sensitivity_metrics.items())
        },
    }


def _frequency_only_parity(profile: dict[str, Any]) -> dict[str, Any]:
    run = REPO_ROOT / FINAL_CX317_QUALIFICATION
    with (run / "reports/stage7_authoritative_observations_v1.csv").open(newline="", encoding="utf-8") as handle:
        observations = list(csv.DictReader(handle))
    with (run / "reports/stage7_shadow_decisions_v1.csv").open(newline="", encoding="utf-8") as handle:
        expected = [row for row in csv.DictReader(handle) if row["candidate_id"] == "v2_symmetric_baseline"]
    candidate = next(item for item in profile["candidates"] if item["candidate_id"] == "p3600_cap1_v2")
    engine = HybridCandidateEngine(
        profile,
        candidate,
        start_code=43029,
        gain_hz_per_code=0.00017072602587382669,
        phase_enabled=False,
    )

    def record(sequence: int, dac_epoch: int) -> PhaseRecord:
        return PhaseRecord(
            phase_epoch=1,
            observation_sequence=sequence,
            capture_session=1,
            opening_snapshot_sequence=sequence,
            closing_snapshot_sequence=sequence + 1,
            opening_reference_sequence=sequence,
            closing_reference_sequence=sequence + 1,
            dac_epoch=dac_epoch,
            interval_edges=10_000_000,
            edge_error_cycles=0,
            relative_phase_cycles=0,
            relative_phase_time_ns=0,
            qualification_state="qualified",
            observation_age_s=0,
            discontinuity_reason=None,
            calibrated_uncertainty_status="unavailable",
            source_backend="pio_wait_cumulative_snapshot_dma_v1",
            method_id="CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1",
            configuration_sha256="0" * 64,
            accepted=True,
        )

    opening = record(0, 0)
    opening_estimate = CandidateEstimate("CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1", 1, 0, 0, 0, 0.0, None, "initializing", "unavailable")
    engine.process(opening, opening_estimate, timestamp_s=0, actual_applied_code=43029)
    mismatches = []
    for observed, sealed in zip(observations, expected):
        timestamp = int(observed["timestamp_s"])
        current = record(timestamp, int(observed["actual_dac_epoch"]))
        estimate = CandidateEstimate(
            "CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1",
            1,
            timestamp,
            current.dac_epoch,
            0,
            0.0,
            float(observed["frequency_error_hz"]),
            "qualified",
            "unavailable",
        )
        output = engine.process(
            current,
            estimate,
            timestamp_s=timestamp,
            actual_applied_code=int(observed["actual_applied_code"]),
        )
        if output.shadow_code_after != int(sealed["shadow_code_after"]) or output.counterfactual_correction != (sealed["counterfactual_write"] == "true"):
            mismatches.append(int(observed["observation_sequence"]))
    return {
        "observation_count": len(observations),
        "sealed_decision_count": len(expected),
        "mismatch_count": len(mismatches),
        "mismatch_observation_sequences": mismatches,
        "exact": not mismatches and len(observations) == len(expected),
        "phase_contribution_forced_hz": 0.0,
    }


def _aggregate(runs: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, dict[str, Any]] = {}
    for candidate in profile["candidates"]:
        identifier = candidate["candidate_id"]
        rows = [run["candidate_metrics"][identifier] for run in runs if run["status"] == "replayed"]
        freq_rows = [row for row in rows if row["frequency_observation_count"]]
        observed_ss = sum((row["observed_600s_frequency_rms_hz"] or 0) ** 2 * row["frequency_observation_count"] for row in freq_rows)
        modeled_ss = sum((row["modeled_600s_frequency_rms_hz"] or 0) ** 2 * row["frequency_observation_count"] for row in freq_rows)
        freq_n = sum(row["frequency_observation_count"] for row in freq_rows)
        result[identifier] = {
            "declared_runs": len(rows),
            "runs_with_frequency_support": len(freq_rows),
            "observed_phase_absolute_segment_movement_cycles": sum(row["observed_phase_absolute_segment_movement_cycles"] for row in rows),
            "modeled_phase_absolute_segment_movement_cycles": sum(row["modeled_phase_absolute_segment_movement_cycles"] for row in rows),
            "phase_movement_reduction_cycles": sum(row["phase_movement_reduction_cycles"] for row in rows),
            "observed_600s_frequency_rms_hz": math.sqrt(observed_ss / freq_n) if freq_n else None,
            "modeled_600s_frequency_rms_hz": math.sqrt(modeled_ss / freq_n) if freq_n else None,
            "frequency_rms_degradation_hz": (math.sqrt(modeled_ss / freq_n) - math.sqrt(observed_ss / freq_n)) if freq_n else None,
            "counterfactual_correction_count": sum(row["counterfactual_correction_count"] for row in rows),
            "cumulative_movement_codes": sum(row["cumulative_movement_codes"] for row in rows),
            "alternating_correction_count": sum(row["alternating_correction_count"] for row in rows),
            "range_clamped_count": sum(row["range_clamped_count"] for row in rows),
            "terminal_fault_preview_runs": sum(bool(row["terminal_fault_preview"]) for row in rows),
            "phase_step_count": sum(row["phase_step_count"] for row in rows),
            "reference_loss_count": sum(row["reference_loss_count"] for row in rows),
            "recovery_count": sum(row["recovery_count"] for row in rows),
        }
    return result


def replay_corpus(corpus_path: Path = DEFAULT_CORPUS) -> dict[str, Any]:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    phase_profile, phase_sha = load_phase_profile()
    hybrid_profile, hybrid_sha = load_hybrid_profile()
    runs = [
        replay_run(
            item,
            corpus=corpus,
            phase_profile=phase_profile,
            phase_configuration_sha256=phase_sha,
            hybrid_profile=hybrid_profile,
        )
        for item in _declared_runs(corpus)
    ]
    statuses = Counter(item["status"] for item in runs)
    return {
        "schema_version": 1,
        "tool": "cx318_stage3_hybrid_replay_v1",
        "status": "complete_with_explicit_missing_sources",
        "corpus": {"path": corpus_path.relative_to(REPO_ROOT).as_posix(), "sha256": _sha256_file(corpus_path)},
        "hybrid_profile": {"path": "profiles/discipline/cx318_hybrid_preview_candidates_v1.json", "sha256": hybrid_sha},
        "authority": hybrid_profile["authority"],
        "run_count": len(runs),
        "status_counts": dict(sorted(statuses.items())),
        "frequency_only_forced_zero_parity": _frequency_only_parity(hybrid_profile),
        "aggregate_candidate_metrics": _aggregate(runs, hybrid_profile),
        "runs": runs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    result = replay_corpus(args.corpus.resolve())
    _atomic_json(args.output.resolve(), result)
    print(f"{args.output.resolve()}\nruns={result['run_count']} status_counts={result['status_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
