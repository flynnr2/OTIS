"""Fail-closed selected-preview firmware parity over a declared corpus.

The runner is host-only.  It feeds the pure C++ selected-preview harness with
the exact snapshot/count/DAC boundaries used by Stage 3, then compares every
returned engine field to the same selected host phase and hybrid-preview
implementations.  It never opens a serial device or changes a run source.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import argparse
import csv
import json
import math
import shutil
import subprocess
import tempfile
from typing import Any, Iterator

from .phase_frequency_hybrid_preview import HybridCandidateEngine, HybridPreviewDecision, load_profile as load_hybrid_profile
from .reference_relative_phase_estimator import CandidateEstimate, PhaseRecord, RelativePhaseAccumulator, Snapshot, load_profile as load_phase_profile
REPO_ROOT = Path(__file__).resolve().parents[2]


FIRMWARE_ROOT = REPO_ROOT / "firmware/arduino/otis_nano_rp2040_connect"
ENGINE_SOURCE = FIRMWARE_ROOT / "otis_selected_phase_frequency_preview_engine.cpp"
ENGINE_HEADER = FIRMWARE_ROOT / "otis_selected_phase_frequency_preview_engine.h"
HARNESS_SOURCE = REPO_ROOT / "tests/cpp/selected_phase_frequency_preview_engine_harness.cpp"
SELECTED_PHASE_PROFILE = REPO_ROOT / "profiles/estimators/cx318_relative_phase_selected_v1.json"
SELECTED_HYBRID_PROFILE = REPO_ROOT / "profiles/discipline/cx318_hybrid_preview_selected_v1.json"
MAX_MISMATCHES = 32
NUMERIC_ABSOLUTE_FLOOR = 1e-15


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _candidate_file(run_dir: Path, candidates: list[str]) -> Path | None:
    return next(
        (run_dir / relative for relative in candidates if (run_dir / relative).is_file()),
        None,
    )


def _rates(manifest: dict[str, Any], nominal_override: str | None = None) -> tuple[int, int, float]:
    oscillator = manifest.get("oscillator") or {}
    nominal = oscillator.get("nominal_frequency_hz")
    domains = manifest.get("domains") or []
    timer = next(
        (item.get("nominal_hz") for item in domains if item.get("name") == "rp2040_timer0"),
        None,
    )
    if nominal is None and nominal_override is not None:
        nominal = int(nominal_override.split("_", 1)[0])
    if nominal is None or timer is None:
        raise ValueError("run manifest lacks oscillator or timer nominal rate")
    if float(nominal) != round(float(nominal)):
        raise ValueError("non-integer nominal edge rate is unsupported")
    return int(round(float(nominal))), int(round(float(timer))), 1e9 / float(nominal)


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
        if not applied or (requested and requested != applied):
            continue
        code = int(applied)
        if 0xA800 <= code <= 0xAB00:
            result.append((float(row["elapsed_ms"]) / 1000.0, code))
    return sorted(set(result))


def _recursive_codes(value: Any) -> list[tuple[str, int]]:
    keys = {"start_code", "initial_code", "fixed_code", "dac_code", "fail_static_code"}
    result: list[tuple[str, int]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, (int, float)) and float(item).is_integer():
                code = int(item)
                if 0xA800 <= code <= 0xAB00:
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


@dataclass(frozen=True)
class Boundary:
    snapshot: Snapshot
    counted_edges: int | None
    reference_qualified: bool
    dac_epoch: int
    timestamp_s: float
    actual_applied_code: int


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _file_identity(path: Path, root: Path) -> dict[str, str]:
    return {"path": _relative(path, root), "sha256": _sha256_file(path)}


def compile_harness(
    output: Path,
    *,
    compiler: str | None = None,
    engine_source: Path = ENGINE_SOURCE,
    harness_source: Path = HARNESS_SOURCE,
    firmware_root: Path = FIRMWARE_ROOT,
) -> Path:
    """Compile the pure selected-preview harness for a parity invocation."""
    selected_compiler = compiler or shutil.which("c++")
    if not selected_compiler:
        raise RuntimeError("a C++17 compiler is required for CX318 firmware parity")
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            selected_compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(harness_source),
            str(engine_source),
            "-I",
            str(firmware_root),
            "-o",
            str(output),
        ],
        check=True,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )
    return output


def _declared_runs(corpus: dict[str, Any], repo_root: Path) -> list[dict[str, str]]:
    runs = [dict(item) for item in corpus["explicit_runs"]]
    for group in corpus.get("discovered_run_groups", []):
        directory = repo_root / str(group["directory"])
        if not directory.is_dir():
            runs.append(
                {
                    "class": str(group["class"]),
                    "path": str(group["directory"]),
                    "discovery_status": "directory_missing",
                }
            )
            continue
        for child in sorted(directory.glob(str(group["child_directory_glob"]))):
            if child.is_dir():
                runs.append(
                    {
                        "class": str(group["class"]),
                        "path": child.relative_to(repo_root).as_posix(),
                        "discovery_status": "discovered",
                    }
                )
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in runs:
        if item["path"] not in seen:
            unique.append(item)
            seen.add(item["path"])
    return unique


def _boundaries(
    snapshots: list[dict[str, str]],
    counts: list[dict[str, str]],
    *,
    timer_hz: int,
    events: list[tuple[float, int]],
    start_code: int,
) -> Iterator[Boundary]:
    """Yield precisely the Stage 3 replay's selected-engine input boundary."""
    count_by_sequence = {int(row["count_seq"]): row for row in counts}
    event_times = [item[0] for item in events]
    timestamp_modulus = timer_hz * (1 << 32) // 1_000_000
    previous_raw_timestamp: int | None = None
    unwrapped_timestamp = 0
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
        reference_qualified = count is not None and flags & ~16 == 0
        counted_edges = int(count["counted_edges"]) if count is not None else None
        if previous_raw_timestamp is None:
            unwrapped_timestamp = snapshot.reference_timestamp_ticks
        else:
            unwrapped_timestamp += (
                snapshot.reference_timestamp_ticks - previous_raw_timestamp
            ) % timestamp_modulus
        previous_raw_timestamp = snapshot.reference_timestamp_ticks
        timestamp_s = unwrapped_timestamp / timer_hz
        event_index = bisect_right(event_times, timestamp_s) - 1
        actual_code = events[event_index][1] if event_index >= 0 else start_code
        yield Boundary(
            snapshot=snapshot,
            counted_edges=counted_edges,
            reference_qualified=reference_qualified,
            dac_epoch=event_index + 1,
            timestamp_s=timestamp_s,
            actual_applied_code=actual_code,
        )


def _write_harness_input(path: Path, start_code: int, boundaries: Iterator[Boundary]) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"{start_code}\n")
        for item in boundaries:
            snapshot = item.snapshot
            handle.write(
                " ".join(
                    (
                        str(snapshot.session),
                        str(snapshot.snapshot_sequence),
                        str(snapshot.cumulative_down_counter),
                        str(snapshot.reference_sequence),
                        str(snapshot.reference_timestamp_ticks),
                        str(snapshot.status),
                        str(item.counted_edges or 0),
                        str(item.dac_epoch),
                        format(item.timestamp_s, ".17g"),
                        str(item.actual_applied_code),
                        str(int(item.counted_edges is not None)),
                        str(int(item.reference_qualified)),
                        "0",  # Stage 3 replay does not synthesize reset inputs.
                        "0",  # Stage 3 replay does not synthesize phase-step inputs.
                    )
                )
                + "\n"
            )
            count += 1
    return count


def _host_outputs(
    boundaries: Iterator[Boundary],
    *,
    nominal_edges: int,
    timer_hz: int,
    period_ns: float,
    phase_profile: dict[str, Any],
    phase_configuration_sha256: str,
    hybrid_profile: dict[str, Any],
    selected_candidate: dict[str, Any],
    start_code: int,
    reset_first: bool = False,
) -> Iterator[tuple[PhaseRecord, CandidateEstimate | None, HybridPreviewDecision]]:
    phase_engine = RelativePhaseAccumulator(
        nominal_edges=nominal_edges,
        timer_ticks_per_second=timer_hz,
        period_ns_per_cycle=period_ns,
        configuration_sha256=phase_configuration_sha256,
        reference_interval_minimum_s=float(phase_profile["validity"]["reference_interval_minimum_s"]),
        reference_interval_maximum_s=float(phase_profile["validity"]["reference_interval_maximum_s"]),
        reference_timestamp_modulus_ticks=timer_hz * (1 << 32) // 1_000_000,
    )
    from .reference_relative_phase_estimator import CandidateSuite

    candidates = CandidateSuite(phase_profile)
    hybrid = HybridCandidateEngine(hybrid_profile, selected_candidate, start_code=start_code)
    for boundary_index, item in enumerate(boundaries):
        record = phase_engine.process(
            item.snapshot,
            counted_edges=item.counted_edges,
            reference_qualified=item.reference_qualified,
            dac_epoch=item.dac_epoch,
            reset=reset_first and boundary_index == 0,
        )
        estimates = candidates.process(record)
        raw_estimate = next(
            (
                estimate
                for estimate in estimates
                if estimate.candidate_id == "CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1"
            ),
            None,
        )
        if raw_estimate is None or record.qualification_state == "invalid":
            decision = hybrid.invalidate(
                record,
                timestamp_s=item.timestamp_s,
                actual_applied_code=item.actual_applied_code,
                reason=record.discontinuity_reason or "invalid_phase_input",
            )
        else:
            decision = hybrid.process(
                record,
                raw_estimate,
                timestamp_s=item.timestamp_s,
                actual_applied_code=item.actual_applied_code,
            )
        yield record, raw_estimate, decision


def _expected_boolean(actual: str, expected: bool, field: str) -> str | None:
    expected_text = "1" if expected else "0"
    return None if actual == expected_text else f"{field}: expected {expected_text}, got {actual!r}"


def _expected_integer(actual: str, expected: int, field: str) -> str | None:
    try:
        observed = int(actual, 10)
    except ValueError:
        return f"{field}: expected integer {expected}, got {actual!r}"
    return None if observed == expected else f"{field}: expected {expected}, got {observed}"


def _expected_float(actual: str, expected: float | None, field: str) -> str | None:
    try:
        observed = float(actual)
    except ValueError:
        return f"{field}: expected numeric value, got {actual!r}"
    if expected is None:
        return None if observed == 0.0 else f"{field}: unavailable expected 0.0, got {observed!r}"
    tolerance = max(math.ulp(float(expected)), NUMERIC_ABSOLUTE_FLOOR)
    return (
        None
        if math.isfinite(observed) and abs(observed - float(expected)) <= tolerance
        else f"{field}: expected {float(expected)!r} +/- {tolerance!r}, got {observed!r}"
    )


def compare_engine_output(
    actual: dict[str, str],
    expected: tuple[PhaseRecord, CandidateEstimate | None, HybridPreviewDecision],
) -> list[str]:
    """Compare one harness row using the frozen Stage 4 field contract."""
    record, raw_estimate, decision = expected
    errors: list[str] = []
    integer_fields = {
        "phase_epoch": record.phase_epoch,
        "observation_sequence": record.observation_sequence,
        "dac_epoch": record.dac_epoch,
        "capture_session": record.capture_session,
        "opening_snapshot_sequence": record.opening_snapshot_sequence,
        "closing_snapshot_sequence": record.closing_snapshot_sequence,
        "opening_reference_sequence": record.opening_reference_sequence,
        "closing_reference_sequence": record.closing_reference_sequence,
        "interval_edges": record.interval_edges or 0,
        "edge_error_cycles": record.edge_error_cycles or 0,
        "relative_phase_cycles": record.relative_phase_cycles,
        "relative_phase_time_ns": int(record.relative_phase_time_ns),
        "shadow_code_before": decision.shadow_code_before,
        "shadow_code_after": decision.shadow_code_after,
        "actual_applied_code": decision.actual_applied_code,
        "limited_delta_codes": decision.limited_delta_codes or 0,
        "correction_count": decision.correction_count,
        "cumulative_movement_codes": decision.cumulative_movement_codes,
        "alternating_correction_count": decision.alternating_correction_count,
    }
    exact_fields = {
        "phase_state": record.qualification_state,
        "phase_reason": record.discontinuity_reason or "",
        "band_state_before": decision.band_state_before,
        "band_state_after": decision.band_state_after,
        "preview_state": decision.preview_state,
        "decision_reason": decision.decision_reason,
    }
    boolean_fields = {
        "phase_accepted": record.accepted,
        "interval_available": record.interval_edges is not None,
        "frequency_available": decision.modeled_frequency_error_hz is not None,
        "raw_frequency_available": raw_estimate is not None and raw_estimate.estimated_frequency_error_hz is not None,
        "frequency_observation_event": decision.frequency_observation_event,
        "counterfactual_decision": decision.counterfactual_decision,
        "counterfactual_correction": decision.counterfactual_correction,
        "raw_delta_available": decision.raw_delta_codes is not None,
        "step_limited": decision.step_limited,
        "range_clamped": decision.range_clamped,
        "modeled_not_observed_after_divergence": decision.modeled_not_observed_after_divergence,
    }
    float_fields = {
        "raw_frequency_error_hz": None if raw_estimate is None else raw_estimate.estimated_frequency_error_hz,
        "observed_frequency_error_hz": decision.observed_frequency_error_hz,
        "modeled_relative_phase_cycles": decision.modeled_relative_phase_cycles,
        "modeled_frequency_error_hz": decision.modeled_frequency_error_hz,
        "frequency_term_hz": decision.frequency_term_hz,
        "phase_bias_hz": decision.phase_bias_hz,
        "combined_desired_frequency_change_hz": decision.combined_desired_frequency_change_hz,
        "raw_delta_codes": decision.raw_delta_codes,
    }
    for field, value in integer_fields.items():
        if error := _expected_integer(actual.get(field, ""), value, field):
            errors.append(error)
    for field, value in exact_fields.items():
        if actual.get(field, "") != value:
            errors.append(f"{field}: expected {value!r}, got {actual.get(field, '')!r}")
    for field, value in boolean_fields.items():
        if error := _expected_boolean(actual.get(field, ""), value, field):
            errors.append(error)
    for field, value in float_fields.items():
        if error := _expected_float(actual.get(field, ""), value, field):
            errors.append(error)
    return errors


def _static_firmware_eligibility(nominal_edges: int, timer_hz: int, period_ns: float) -> str | None:
    if nominal_edges != 10_000_000 or timer_hz != 16_000_000 or period_ns != 100.0:
        return (
            "selected firmware engine has a fixed CX317 10 MHz / RP2040 "
            "16 MHz / 100 ns contract"
        )
    return None


def _run_one(
    item: dict[str, str],
    *,
    corpus: dict[str, Any],
    repo_root: Path,
    harness: Path,
    phase_profile: dict[str, Any],
    phase_hash: str,
    hybrid_profile: dict[str, Any],
    selected_candidate: dict[str, Any],
    max_mismatches: int,
    expected_stage2_status: str | None,
) -> dict[str, Any]:
    run_dir = repo_root / item["path"]
    adequacy = corpus["adequate_raw_input"]
    manifest_path = run_dir / str(adequacy["required_run_manifest"])
    snapshot_path = _candidate_file(run_dir, list(adequacy["snapshot_candidates"]))
    count_path = _candidate_file(run_dir, list(adequacy["count_candidates"]))
    base = {
        "class": item["class"],
        "path": item["path"],
        "discovery_status": item.get("discovery_status", "explicit"),
    }
    missing = [
        name
        for name, path in (
            ("run_manifest", manifest_path if manifest_path.is_file() else None),
            ("snapshots", snapshot_path),
            ("counts", count_path),
        )
        if path is None
    ]
    if missing:
        expected_missing = (
            expected_stage2_status == "missing_or_inadequate_raw_source"
        )
        return {
            **base,
            "status": (
                "expected_missing_or_inadequate_raw_source"
                if expected_missing
                else "failed"
            ),
            "missing": missing,
            "boundary_count": 0,
            "error": (
                None if expected_missing else "a Stage 2 replay source is now missing"
            ),
        }
    assert snapshot_path is not None and count_path is not None
    source_paths = [manifest_path, snapshot_path, count_path]
    dac_path = _candidate_file(run_dir, ["csv/dac_steps.csv", "csv/dac.csv"])
    if dac_path is not None:
        source_paths.append(dac_path)
    source_before = {_relative(path, run_dir): _sha256_file(path) for path in source_paths}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        nominal_edges, timer_hz, period_ns = _rates(manifest, item.get("nominal_frequency_hz_override"))
        snapshots = _read_csv(snapshot_path)
        counts = _read_csv(count_path)
        if len(snapshots) < int(adequacy["minimum_snapshot_rows"]):
            expected_missing = (
                expected_stage2_status == "missing_or_inadequate_raw_source"
            )
            return {
                **base,
                "status": (
                    "expected_missing_or_inadequate_raw_source"
                    if expected_missing
                    else "failed"
                ),
                "missing": ["minimum_snapshot_rows"],
                "boundary_count": len(snapshots),
                "error": (
                    None
                    if expected_missing
                    else "a Stage 2 replay source is now inadequate"
                ),
            }
        if expected_stage2_status == "missing_or_inadequate_raw_source":
            return {
                **base,
                "status": "failed",
                "boundary_count": len(snapshots),
                "error": "a source excluded by sealed Stage 2 is now populated",
            }
        if reason := _static_firmware_eligibility(nominal_edges, timer_hz, period_ns):
            return {**base, "status": "ineligible_firmware_static_contract", "reason": reason, "boundary_count": len(snapshots)}
        events = _dac_events(run_dir)
        start_code, start_provenance = _start_code(manifest, events, hybrid_profile)
        boundaries_kwargs = {
            "snapshots": snapshots,
            "counts": counts,
            "timer_hz": timer_hz,
            "events": events,
            "start_code": start_code,
        }
        with tempfile.TemporaryDirectory(prefix="cx318-parity-") as temporary_directory:
            temporary = Path(temporary_directory)
            input_path = temporary / "input.txt"
            output_path = temporary / "output.csv"
            boundary_count = _write_harness_input(input_path, start_code, _boundaries(**boundaries_kwargs))
            with input_path.open("r", encoding="utf-8") as input_handle, output_path.open("w", encoding="utf-8") as output_handle:
                subprocess.run([str(harness)], stdin=input_handle, stdout=output_handle, stderr=subprocess.PIPE, text=True, check=True, cwd=repo_root)
            mismatches: list[dict[str, Any]] = []
            mismatch_count = 0
            with output_path.open("r", encoding="utf-8", newline="") as output_handle:
                actual_rows = csv.DictReader(output_handle)
                expected_rows = _host_outputs(
                    _boundaries(**boundaries_kwargs),
                    nominal_edges=nominal_edges,
                    timer_hz=timer_hz,
                    period_ns=period_ns,
                    phase_profile=phase_profile,
                    phase_configuration_sha256=phase_hash,
                    hybrid_profile=hybrid_profile,
                    selected_candidate=selected_candidate,
                    start_code=start_code,
                )
                actual_count = 0
                for record_index, expected in enumerate(expected_rows, start=1):
                    actual = next(actual_rows, None)
                    if actual is None:
                        mismatch_count += 1
                        if len(mismatches) < max_mismatches:
                            record, _, decision = expected
                            mismatches.append(
                                {
                                    "record_index": record_index,
                                    "snapshot_sequence": record.closing_snapshot_sequence,
                                    "phase_epoch": record.phase_epoch,
                                    "preview_state": decision.preview_state,
                                    "fields": ["harness output ended before expected record"],
                                }
                            )
                        break
                    actual_count += 1
                    errors = compare_engine_output(actual, expected)
                    if errors:
                        mismatch_count += 1
                        if len(mismatches) < max_mismatches:
                            record, _, decision = expected
                            mismatches.append(
                                {
                                    "record_index": record_index,
                                    "snapshot_sequence": record.closing_snapshot_sequence,
                                    "phase_epoch": record.phase_epoch,
                                    "preview_state": decision.preview_state,
                                    "fields": errors[:8],
                                }
                            )
                extra_rows = sum(1 for _ in actual_rows)
                if extra_rows:
                    mismatch_count += extra_rows
                    if len(mismatches) < max_mismatches:
                        mismatches.append(
                            {
                                "record_index": actual_count + 1,
                                "fields": [
                                    f"harness emitted {extra_rows} unexpected extra record(s)"
                                ],
                            }
                        )
                    actual_count += extra_rows
        source_after = {_relative(path, run_dir): _sha256_file(path) for path in source_paths}
        source_unchanged = source_before == source_after
        return {
            **base,
            "status": "passed" if not mismatch_count and source_unchanged else "failed",
            "boundary_count": boundary_count,
            "compared_record_count": actual_count,
            "mismatch_count": mismatch_count,
            "first_mismatches": mismatches,
            "source_sha256": source_before,
            "sources_unchanged": source_unchanged,
            "start_code": start_code,
            "start_code_provenance": start_provenance,
            "actual_dac_event_count": len(events),
        }
    except (KeyError, TypeError, ValueError, subprocess.CalledProcessError) as exc:
        return {**base, "status": "failed", "boundary_count": 0, "error": str(exc)}


def run_corpus(
    corpus_path: Path,
    *,
    harness: Path | None = None,
    compiler: str | None = None,
    repo_root: Path = REPO_ROOT,
    max_mismatches: int = MAX_MISMATCHES,
) -> dict[str, Any]:
    """Run selected-engine parity for every declared corpus run, fail-closed."""
    if max_mismatches <= 0:
        raise ValueError("max_mismatches must be positive")
    corpus_path = corpus_path.resolve()
    repo_root = repo_root.resolve()
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    phase_profile, phase_hash = load_phase_profile()
    hybrid_profile, hybrid_hash = load_hybrid_profile()
    selected_hybrid = json.loads(SELECTED_HYBRID_PROFILE.read_text(encoding="utf-8"))
    selected_candidate_id = str(selected_hybrid["selection"]["selected_candidate_id"])
    selected_candidate = next(
        (item for item in hybrid_profile["candidates"] if item["candidate_id"] == selected_candidate_id),
        None,
    )
    if selected_candidate is None:
        raise ValueError("selected CX318 hybrid candidate is absent from its frozen profile")
    if harness is None:
        with tempfile.TemporaryDirectory(prefix="cx318-parity-build-") as temporary_directory:
            executable = compile_harness(Path(temporary_directory) / "selected_preview", compiler=compiler)
            return _run_corpus_with_harness(
                corpus_path, corpus, repo_root, executable, phase_profile, phase_hash,
                hybrid_profile, hybrid_hash, selected_candidate, max_mismatches,
            )
    return _run_corpus_with_harness(
        corpus_path, corpus, repo_root, harness.resolve(), phase_profile, phase_hash,
        hybrid_profile, hybrid_hash, selected_candidate, max_mismatches,
    )


def _run_corpus_with_harness(
    corpus_path: Path,
    corpus: dict[str, Any],
    repo_root: Path,
    harness: Path,
    phase_profile: dict[str, Any],
    phase_hash: str,
    hybrid_profile: dict[str, Any],
    hybrid_hash: str,
    selected_candidate: dict[str, Any],
    max_mismatches: int,
) -> dict[str, Any]:
    declared = _declared_runs(corpus, repo_root)
    runs = [
        _run_one(
            item,
            corpus=corpus,
            repo_root=repo_root,
            harness=harness,
            phase_profile=phase_profile,
            phase_hash=phase_hash,
            hybrid_profile=hybrid_profile,
            selected_candidate=selected_candidate,
            max_mismatches=max_mismatches,
            expected_stage2_status=None,
        )
        for item in declared
    ]
    statuses = Counter(str(item["status"]) for item in runs)
    failures = [item for item in runs if item["status"] == "failed"]
    return {
        "schema_version": 1,
        "tool": "cx318_stage4_firmware_parity_v1",
        "status": "passed" if not failures else "failed",
        "corpus": _file_identity(corpus_path, repo_root),
        "profiles": {
            "phase_candidates": _file_identity(REPO_ROOT / "profiles/estimators/cx318_relative_phase_candidates_v1.json", REPO_ROOT),
            "phase_selected": _file_identity(SELECTED_PHASE_PROFILE, REPO_ROOT),
            "hybrid_candidates": _file_identity(REPO_ROOT / "profiles/discipline/cx318_hybrid_preview_candidates_v1.json", REPO_ROOT),
            "hybrid_selected": _file_identity(SELECTED_HYBRID_PROFILE, REPO_ROOT),
            "phase_candidate_configuration_sha256": phase_hash,
            "hybrid_candidate_configuration_sha256": hybrid_hash,
            "selected_candidate_id": selected_candidate["candidate_id"],
        },
        "firmware_sources": {
            "engine": _file_identity(ENGINE_SOURCE, REPO_ROOT),
            "header": _file_identity(ENGINE_HEADER, REPO_ROOT),
            "harness": _file_identity(HARNESS_SOURCE, REPO_ROOT),
        },
        "numerical_contract": {
            "maximum_error": "max(one_ulp_at_expected, 1e-15)",
            "absolute_floor": NUMERIC_ABSOLUTE_FLOOR,
        },
        "declared_run_count": len(runs),
        "eligible_run_count": statuses["passed"] + statuses["failed"],
        "passed_run_count": statuses["passed"],
        "failed_run_count": statuses["failed"],
        "expected_missing_or_inadequate_run_count": statuses[
            "expected_missing_or_inadequate_raw_source"
        ],
        "ineligible_firmware_static_contract_run_count": statuses["ineligible_firmware_static_contract"],
        "boundary_count": sum(int(item.get("boundary_count", 0)) for item in runs if item["status"] in {"passed", "failed"}),
        "compared_record_count": sum(int(item.get("compared_record_count", 0)) for item in runs),
        "mismatch_count": sum(int(item.get("mismatch_count", 0)) for item in runs),
        "status_counts": dict(sorted(statuses.items())),
        "runs": runs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--harness", type=Path)
    parser.add_argument("--compiler")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--max-mismatches", type=int, default=MAX_MISMATCHES)
    args = parser.parse_args(argv)
    report = run_corpus(
        args.corpus,
        harness=args.harness,
        compiler=args.compiler,
        repo_root=args.repo_root,
        max_mismatches=args.max_mismatches,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{args.output.resolve()} status={report['status']} runs={report['declared_run_count']} mismatches={report['mismatch_count']}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
