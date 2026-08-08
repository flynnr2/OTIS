"""Replay the frozen Stage 2 relative-phase candidates over the declared corpus."""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import argparse
import csv
import json
import os
import tempfile
from typing import Any

from .cx318_relative_phase import (
    CandidateSuite,
    RelativePhaseAccumulator,
    Snapshot,
    load_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = (
    REPO_ROOT / "profiles/replay/cx318_stage2_replay_corpus_v1.json"
)


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def _candidate_file(run_dir: Path, candidates: list[str]) -> Path | None:
    return next(
        (run_dir / relative for relative in candidates if (run_dir / relative).is_file()),
        None,
    )


def _declared_runs(corpus: dict[str, Any]) -> list[dict[str, str]]:
    runs = [dict(item) for item in corpus["explicit_runs"]]
    for group in corpus["discovered_run_groups"]:
        root = REPO_ROOT / group["directory"]
        if not root.is_dir():
            runs.append(
                {
                    "class": group["class"],
                    "path": group["directory"],
                    "discovery_status": "directory_missing",
                }
            )
            continue
        for child in sorted(root.glob(group["child_directory_glob"])):
            if child.is_dir():
                runs.append(
                    {
                        "class": group["class"],
                        "path": child.relative_to(REPO_ROOT).as_posix(),
                        "discovery_status": "discovered",
                    }
                )
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for item in runs:
        if item["path"] not in seen:
            unique.append(item)
            seen.add(item["path"])
    return unique


def _rates(
    manifest: dict[str, Any], nominal_override: str | None = None
) -> tuple[int, int, float]:
    oscillator = manifest.get("oscillator") or {}
    nominal = oscillator.get("nominal_frequency_hz")
    domains = manifest.get("domains") or []
    timer = next(
        (
            item.get("nominal_hz")
            for item in domains
            if item.get("name") == "rp2040_timer0"
        ),
        None,
    )
    if nominal is None and nominal_override is not None:
        nominal = int(nominal_override.split("_", 1)[0])
    if nominal is None:
        nominal = next(
            (
                item.get("nominal_hz")
                for item in domains
                if item.get("name") != "rp2040_timer0"
            ),
            None,
        )
    if nominal is None or timer is None:
        raise ValueError("run manifest lacks oscillator or timer nominal rate")
    if float(nominal) != round(float(nominal)):
        raise ValueError("non-integer nominal edge rate is unsupported")
    return int(round(float(nominal))), int(round(float(timer))), 1e9 / float(nominal)


def _dac_transition_times(run_dir: Path) -> list[float]:
    path = _candidate_file(run_dir, ["csv/dac_steps.csv", "csv/dac.csv"])
    if path is None:
        return []
    times: list[float] = []
    for row in _read_csv(path):
        if "elapsed_ms" not in row or not row["elapsed_ms"]:
            continue
        if row.get("flags", "0") not in {"", "0"}:
            continue
        requested = row.get("dac_code_requested")
        applied = row.get("dac_code_applied")
        if requested and applied and requested != applied:
            continue
        times.append(float(row["elapsed_ms"]) / 1000.0)
    return sorted(set(times))


def _authoritative_frequency(run_dir: Path) -> dict[int, float]:
    path = run_dir / "csv/estimates_v2.csv"
    if not path.is_file():
        return {}
    result: dict[int, float] = {}
    for row in _read_csv(path):
        if row.get("accepted_sample_count") != "600":
            continue
        if "selected_600s" not in row.get("estimator_version", ""):
            continue
        if row.get("observation_validity") != "valid":
            continue
        result[int(row["source_reference_last_seq"])] = float(
            row["frequency_error_hz"]
        )
    return result


def _metric_finalize(value: dict[str, Any]) -> dict[str, Any]:
    output = dict(value)
    residual_count = output.pop("_residual_count", 0)
    residual_square_sum = output.pop("_residual_square_sum", 0.0)
    output["residual_rms_cycles"] = (
        (residual_square_sum / residual_count) ** 0.5
        if residual_count
        else None
    )
    if residual_count:
        output["residual_range_cycles"] = (
            output["residual_max_cycles"] - output["residual_min_cycles"]
        )
    else:
        output["residual_min_cycles"] = None
        output["residual_max_cycles"] = None
        output["residual_range_cycles"] = None
    for prefix in ("raw_600", "existing_600"):
        count = output.pop(f"_{prefix}_count", 0)
        square_sum = output.pop(f"_{prefix}_square_sum", 0.0)
        output[f"frequency_difference_vs_{prefix}_count"] = count
        output[f"frequency_difference_vs_{prefix}_rms_hz"] = (
            (square_sum / count) ** 0.5 if count else None
        )
    _finalize_lag_one(output)
    return output


def _finalize_lag_one(output: dict[str, Any]) -> None:
    count = int(output.pop("_lag_count", 0))
    sum_x = output.pop("_lag_sum_x", 0.0)
    sum_y = output.pop("_lag_sum_y", 0.0)
    sum_xx = output.pop("_lag_sum_xx", 0.0)
    sum_yy = output.pop("_lag_sum_yy", 0.0)
    sum_xy = output.pop("_lag_sum_xy", 0.0)
    denominator = (
        (count * sum_xx - sum_x * sum_x)
        * (count * sum_yy - sum_y * sum_y)
    )
    output["residual_lag1_pair_count"] = count
    output["residual_lag1_correlation"] = (
        (count * sum_xy - sum_x * sum_y) / denominator**0.5
        if count >= 2 and denominator > 0
        else None
    )


def _residual_epoch_finalize(value: dict[str, Any]) -> dict[str, Any]:
    output = dict(value)
    count = int(output.pop("_residual_count", 0))
    square_sum = output.pop("_residual_square_sum", 0.0)
    output["residual_count"] = count
    output["residual_rms_cycles"] = (
        (square_sum / count) ** 0.5 if count else None
    )
    output["residual_range_cycles"] = (
        output["residual_max_cycles"] - output["residual_min_cycles"]
        if count
        else None
    )
    _finalize_lag_one(output)
    return output


def replay_run(
    item: dict[str, str],
    *,
    corpus: dict[str, Any],
    candidate_profile: dict[str, Any],
    configuration_sha256: str,
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
    base = {
        "class": item["class"],
        "path": item["path"],
        "discovery_status": item.get("discovery_status", "explicit"),
    }
    if missing:
        return {
            **base,
            "status": "missing_or_inadequate_raw_source",
            "missing": missing,
            "phase_records_generated": 0,
        }

    assert snapshot_path is not None and count_path is not None
    source_paths = [manifest_path, snapshot_path, count_path]
    source_hashes_before = {
        path.relative_to(run_dir).as_posix(): _sha256_file(path)
        for path in source_paths
    }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    nominal_edges, timer_hz, period_ns = _rates(
        manifest, item.get("nominal_frequency_hz_override")
    )
    count_rows = _read_csv(count_path)
    count_by_sequence: dict[int, dict[str, str]] = {}
    duplicate_count_sequences = 0
    for row in count_rows:
        sequence = int(row["count_seq"])
        if sequence in count_by_sequence:
            duplicate_count_sequences += 1
        count_by_sequence[sequence] = row
    snapshot_rows = _read_csv(snapshot_path)
    if len(snapshot_rows) < int(adequacy["minimum_snapshot_rows"]):
        return {
            **base,
            "status": "missing_or_inadequate_raw_source",
            "missing": ["minimum_snapshot_rows"],
            "snapshot_rows": len(snapshot_rows),
            "phase_records_generated": 0,
        }

    engine = RelativePhaseAccumulator(
        nominal_edges=nominal_edges,
        timer_ticks_per_second=timer_hz,
        period_ns_per_cycle=period_ns,
        configuration_sha256=configuration_sha256,
        reference_interval_minimum_s=float(
            candidate_profile["validity"]["reference_interval_minimum_s"]
        ),
        reference_interval_maximum_s=float(
            candidate_profile["validity"]["reference_interval_maximum_s"]
        ),
        reference_timestamp_modulus_ticks=(
            timer_hz * (1 << 32) // 1_000_000
        ),
    )
    candidates = CandidateSuite(candidate_profile)
    dac_times = _dac_transition_times(run_dir)
    authoritative = _authoritative_frequency(run_dir)
    record_digest = sha256()
    estimate_digest = sha256()
    reasons: Counter[str] = Counter()
    states: Counter[str] = Counter()
    metrics: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "output_count": 0,
            "qualified_frequency_count": 0,
            "_residual_count": 0,
            "_residual_square_sum": 0.0,
            "residual_min_cycles": float("inf"),
            "residual_max_cycles": float("-inf"),
            "_raw_600_count": 0,
            "_raw_600_square_sum": 0.0,
            "_existing_600_count": 0,
            "_existing_600_square_sum": 0.0,
            "_lag_count": 0,
            "_lag_sum_x": 0.0,
            "_lag_sum_y": 0.0,
            "_lag_sum_xx": 0.0,
            "_lag_sum_yy": 0.0,
            "_lag_sum_xy": 0.0,
        }
    )
    epoch_metrics: dict[str, dict[str, dict[str, Any]]] = defaultdict(
        lambda: defaultdict(
            lambda: {
                "_residual_count": 0,
                "_residual_square_sum": 0.0,
                "residual_min_cycles": float("inf"),
                "residual_max_cycles": float("-inf"),
                "_lag_count": 0,
                "_lag_sum_x": 0.0,
                "_lag_sum_y": 0.0,
                "_lag_sum_xx": 0.0,
                "_lag_sum_yy": 0.0,
                "_lag_sum_xy": 0.0,
            }
        )
    )
    previous_residual: dict[str, tuple[str, float]] = {}
    accepted = 0
    false_continuity = 0
    false_recovery = 0
    last_state = ""
    last_epoch = 0
    latest_raw_frequency: float | None = None
    terminal_phase = 0
    timestamp_modulus_ticks = timer_hz * (1 << 32) // 1_000_000
    previous_raw_timestamp: int | None = None
    unwrapped_timestamp = 0

    for row in snapshot_rows:
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
        reference_qualified = count is not None and flags & ~16 == 0
        counted_edges = int(count["counted_edges"]) if count is not None else None
        if previous_raw_timestamp is None:
            unwrapped_timestamp = snapshot.reference_timestamp_ticks
        else:
            timestamp_delta = (
                snapshot.reference_timestamp_ticks - previous_raw_timestamp
            ) % timestamp_modulus_ticks
            unwrapped_timestamp += timestamp_delta
        previous_raw_timestamp = snapshot.reference_timestamp_ticks
        elapsed_s = unwrapped_timestamp / timer_hz
        dac_epoch = bisect_right(dac_times, elapsed_s)
        record = engine.process(
            snapshot,
            counted_edges=counted_edges,
            reference_qualified=reference_qualified,
            dac_epoch=dac_epoch,
        )
        states[record.qualification_state] += 1
        if record.discontinuity_reason:
            reasons[record.discontinuity_reason] += 1
        if record.accepted:
            accepted += 1
        if last_state == "invalid" and record.accepted:
            false_recovery += 1
        if record.phase_epoch < last_epoch:
            false_continuity += 1
        last_state = record.qualification_state
        last_epoch = record.phase_epoch
        terminal_phase = record.relative_phase_cycles
        record_digest.update(
            json.dumps(
                asdict(record), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        )
        estimates = candidates.process(record)
        raw_frequency = next(
            (
                value.estimated_frequency_error_hz
                for value in estimates
                if value.candidate_id
                == "CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1"
            ),
            None,
        )
        latest_raw_frequency = raw_frequency
        existing_frequency = authoritative.get(snapshot.reference_sequence)
        for estimate in estimates:
            value = metrics[estimate.candidate_id]
            value["output_count"] += 1
            residual = (
                estimate.raw_relative_phase_cycles
                - estimate.filtered_relative_phase_cycles
            )
            value["_residual_count"] += 1
            value["_residual_square_sum"] += residual * residual
            value["residual_min_cycles"] = min(
                value["residual_min_cycles"], residual
            )
            value["residual_max_cycles"] = max(
                value["residual_max_cycles"], residual
            )
            epoch_key = f"phase_epoch_{record.phase_epoch}:dac_epoch_{record.dac_epoch}"
            epoch_value = epoch_metrics[estimate.candidate_id][epoch_key]
            epoch_value["_residual_count"] += 1
            epoch_value["_residual_square_sum"] += residual * residual
            epoch_value["residual_min_cycles"] = min(
                epoch_value["residual_min_cycles"], residual
            )
            epoch_value["residual_max_cycles"] = max(
                epoch_value["residual_max_cycles"], residual
            )
            previous = previous_residual.get(estimate.candidate_id)
            if previous is not None and previous[0] == epoch_key:
                prior = previous[1]
                for destination in (value, epoch_value):
                    destination["_lag_count"] += 1
                    destination["_lag_sum_x"] += prior
                    destination["_lag_sum_y"] += residual
                    destination["_lag_sum_xx"] += prior * prior
                    destination["_lag_sum_yy"] += residual * residual
                    destination["_lag_sum_xy"] += prior * residual
            previous_residual[estimate.candidate_id] = (epoch_key, residual)
            frequency = estimate.estimated_frequency_error_hz
            if frequency is not None:
                value["qualified_frequency_count"] += 1
                if raw_frequency is not None:
                    difference = frequency - raw_frequency
                    value["_raw_600_count"] += 1
                    value["_raw_600_square_sum"] += difference * difference
                if existing_frequency is not None:
                    difference = frequency - existing_frequency
                    value["_existing_600_count"] += 1
                    value["_existing_600_square_sum"] += difference * difference
            estimate_digest.update(
                json.dumps(
                    asdict(estimate), sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            )

    source_hashes_after = {
        path.relative_to(run_dir).as_posix(): _sha256_file(path)
        for path in source_paths
    }
    return {
        **base,
        "status": "replayed",
        "source_sha256": source_hashes_before,
        "sources_unchanged": source_hashes_before == source_hashes_after,
        "nominal_frequency_hz": nominal_edges,
        "timer_ticks_per_second": timer_hz,
        "snapshot_rows": len(snapshot_rows),
        "count_rows": len(count_rows),
        "duplicate_count_sequences": duplicate_count_sequences,
        "phase_records_generated": len(snapshot_rows),
        "accepted_interval_records": accepted,
        "phase_epoch_count": engine.phase_epoch,
        "qualification_state_counts": dict(sorted(states.items())),
        "discontinuity_reason_counts": dict(sorted(reasons.items())),
        "false_continuity_count": false_continuity,
        "false_recovery_count": false_recovery,
        "dac_transition_count": len(dac_times),
        "terminal_relative_phase_cycles": terminal_phase,
        "terminal_raw_600_frequency_error_hz": latest_raw_frequency,
        "raw_phase_records_sha256": record_digest.hexdigest(),
        "candidate_estimates_sha256": estimate_digest.hexdigest(),
        "existing_authoritative_600_observation_count": len(authoritative),
        "candidate_metrics": {
            key: {
                **_metric_finalize(value),
                "phase_epoch_residual_metrics": {
                    epoch: _residual_epoch_finalize(epoch_value)
                    for epoch, epoch_value in sorted(epoch_metrics[key].items())
                },
            }
            for key, value in sorted(metrics.items())
        },
    }


def replay_corpus(
    corpus_path: Path = DEFAULT_CORPUS,
) -> dict[str, Any]:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    if corpus.get("corpus_id") != "cx318_stage2_replay_corpus_v1":
        raise ValueError("unsupported Stage 2 replay corpus")
    if any(corpus["authority"].values()):
        raise ValueError("replay corpus authority must remain false")
    candidate_profile, candidate_sha256 = load_profile()
    runs = [
        replay_run(
            item,
            corpus=corpus,
            candidate_profile=candidate_profile,
            configuration_sha256=candidate_sha256,
        )
        for item in _declared_runs(corpus)
    ]
    status_counts = Counter(item["status"] for item in runs)
    return {
        "schema_version": 1,
        "tool": "cx318_stage2_replay_v1",
        "status": "complete_with_explicit_missing_sources",
        "corpus": {
            "path": corpus_path.relative_to(REPO_ROOT).as_posix(),
            "sha256": _sha256_file(corpus_path),
        },
        "candidate_profile": {
            "path": "profiles/estimators/cx318_relative_phase_candidates_v1.json",
            "sha256": candidate_sha256,
        },
        "authority": corpus["authority"],
        "run_count": len(runs),
        "status_counts": dict(sorted(status_counts.items())),
        "runs": runs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = replay_corpus(args.corpus.resolve())
    _atomic_json(args.output.resolve(), result)
    print(
        f"{args.output.resolve()}\n"
        f"runs={result['run_count']} status_counts={result['status_counts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
