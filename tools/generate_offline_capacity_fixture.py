"""Create a synthetic, nonqualification D14/D8 offline-capacity artifact.

The generator copies only a retained simulated rehearsal's metadata/lifecycle
prefix into a disposable destination, then extends canonical REF/SNP/CNT/APS
and raw serial evidence with exact nominal one-second apertures.  It never
writes to the source package and does not open a serial device.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections.abc import Iterable
from copy import deepcopy
from hashlib import sha256
from pathlib import Path, PurePosixPath

from host.otis_tools.acquisition_frontier import _digest
from host.otis_tools.authoritative_inputs import (
    ROOT_PROFILE,
    validate_authoritative_inputs,
)
from host.otis_tools.contracts import CONTRACT_FIELDS
from host.otis_tools.evidence_package import ANALYSIS_REPORT
from host.otis_tools.run_loader import load_manifest
from host.otis_tools.run_spec import build_run_spec, create_run_record

U32 = 1 << 32
NOMINAL_EDGES = 10_000_000
ESTIMATE_WINDOW = 600


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_finite_json(path: Path) -> dict[str, object]:
    def reject(value: str) -> None:
        raise ValueError(f"non-finite JSON value in {path}: {value}")

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected retained regular file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _package_identity(value: dict[str, object]) -> str:
    unsigned = {
        key: item for key, item in value.items() if key != "package_content_sha256"
    }
    encoded = (
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _safe_member(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if (
        not relative
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != relative
    ):
        raise ValueError(f"unsafe donor inventory path: {relative!r}")
    member = root.joinpath(*path.parts)
    resolved_root = root.resolve()
    resolved_parent = member.parent.resolve()
    if resolved_root not in (resolved_parent, *resolved_parent.parents):
        raise ValueError(f"donor inventory escapes root: {relative!r}")
    return member


def _validate_simulated_donor(
    path: Path, *, role: str
) -> tuple[str, list[dict[str, object]]]:
    """Verify a sealed simulated donor without recertifying it as current."""

    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"{role} donor must be a real directory")
    package = _read_finite_json(path / "evidence_package_v1.json")
    identity = package.get("package_content_sha256")
    if (
        package.get("contract") != "otis_portable_evidence_package_v1"
        or not isinstance(identity, str)
        or identity != _package_identity(package)
    ):
        raise ValueError(f"{role} donor package seal identity differs")
    inventory = package.get("inventory")
    if not isinstance(inventory, list):
        raise TypeError(f"{role} donor package inventory is malformed")
    expected_keys = {"path", "sha256", "size_bytes"}
    verified: list[dict[str, object]] = []
    for entry in inventory:
        if not isinstance(entry, dict) or set(entry) != expected_keys:
            raise ValueError(f"{role} donor inventory member is malformed")
        relative = entry.get("path")
        size = entry.get("size_bytes")
        digest = entry.get("sha256")
        if (
            not isinstance(relative, str)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or not isinstance(digest, str)
        ):
            raise TypeError(f"{role} donor inventory member types are malformed")
        member = _safe_member(path, relative)
        if member.is_symlink() or not member.is_file():
            raise ValueError(f"{role} donor member is not a retained regular file")
        if member.stat().st_size != size or _sha256_file(member) != digest:
            raise ValueError(f"{role} donor member differs from package inventory")
        verified.append(entry)
    bindings = [entry for entry in verified if entry["path"] == "run_manifest.json"]
    if len(bindings) != 1:
        raise ValueError(f"{role} donor package lacks one run-manifest binding")
    record_path = _safe_member(path, "run_manifest.json")
    record = _read_finite_json(record_path)
    if (
        record.get("execution_kind") != "simulated"
        or record.get("entry_authorization") is not None
    ):
        raise ValueError(f"{role} donor must be an un-authorized simulated run")
    return identity, verified


def _copy_source(
    source: Path, destination: Path, inventory: list[dict[str, object]]
) -> None:
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    destination.mkdir()
    for entry in inventory:
        relative = entry["path"]
        if not isinstance(relative, str):
            raise TypeError("verified donor inventory path is not text")
        origin = _safe_member(source, relative)
        copied = _safe_member(destination, relative)
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, copied)
        if (
            copied.stat().st_size != entry["size_bytes"]
            or _sha256_file(copied) != entry["sha256"]
        ):
            raise ValueError("copied donor member differs from its verified inventory")
    excluded = {
        "run_spec.json",
        "run_manifest.json",
        "evidence_package_v1.json",
        "reports/offline_analysis_v1.json",
        "reports/offline_analysis_v2.json",
        ANALYSIS_REPORT.as_posix(),
        "reports/rehearsal_boundaries_v1.json",
    }
    for relative in excluded:
        (destination / relative).unlink(missing_ok=True)


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or ()), list(reader)


def _append_rows(path: Path, fields: list[str], rows: Iterable[dict[str, str]]) -> None:
    with path.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writerows(rows)


def _device_line(contract: str, row: dict[str, str]) -> bytes:
    return (
        ",".join(row[field] for field in CONTRACT_FIELDS[contract]).encode("utf-8")
        + b"\n"
    )


def _append_measurements(destination: Path, apertures: int) -> list[bytes]:
    csv_root = destination / "csv"
    ref_fields, references = _read_rows(csv_root / "reference_events.csv")
    snp_fields, snapshots = _read_rows(csv_root / "pps_snapshots.csv")
    cnt_fields, counts = _read_rows(csv_root / "count_observations.csv")
    aps_fields, spans = _read_rows(csv_root / "accepted_pps_spans_v1.csv")
    if not (len(references) == len(snapshots) == len(counts) + 1 == len(spans) + 1):
        raise ValueError("source rehearsal measurement prefix is not contiguous")
    if apertures < len(counts):
        raise ValueError("requested aperture count is smaller than retained prefix")
    last_snapshot = snapshots[-1]
    last_reference = references[-1]
    last_span = spans[-1]
    sequence = int(last_snapshot["snapshot_sequence"])
    reference_event = int(last_reference["event_seq"])
    counter = int(last_snapshot["cumulative_down_counter"])
    timestamp = int(last_snapshot["reference_timestamp_ticks"])
    ordinal = int(last_span["accepted_boundary_ordinal"])
    policy = last_span["acceptance_policy_sha256"]
    generated_ref: list[dict[str, str]] = []
    generated_snp: list[dict[str, str]] = []
    generated_cnt: list[dict[str, str]] = []
    generated_aps: list[dict[str, str]] = []
    raw: list[bytes] = []
    for _ in range(len(counts) + 1, apertures + 1):
        opening_sequence = sequence
        opening_ticks = timestamp
        sequence += 1
        reference_event += 1
        timestamp = (timestamp + 1_000_000) % U32
        counter = (counter - NOMINAL_EDGES) % U32
        ordinal += 1
        reference = {
            "record_type": "REF",
            "schema_version": "1",
            "event_seq": str(reference_event),
            "channel_id": "1",
            "edge": "R",
            "timestamp_ticks": str(timestamp),
            "capture_domain": "rp2040_monotonic_us32",
            "flags": "16",
        }
        snapshot = {
            "record_type": "SNP",
            "schema_version": "2",
            "session": "1",
            "snapshot_sequence": str(sequence),
            "cumulative_down_counter": str(counter),
            "reference_sequence": str(sequence),
            "reference_timestamp_ticks": str(timestamp),
            "timestamp_uncertainty_ticks": "1",
            "status": "0",
            "backend": "pio_wait_cumulative_snapshot_fifo_irq_v2",
        }
        count = {
            "record_type": "CNT",
            "schema_version": "1",
            "count_seq": str(sequence),
            "channel_id": "2",
            "gate_open_ticks": str(opening_ticks),
            "gate_close_ticks": str(timestamp),
            "gate_domain": "rp2040_monotonic_us32",
            "counted_edges": str(NOMINAL_EDGES),
            "source_edge": "R",
            "source_domain": "h1_oscillator_10mhz",
            "flags": "16",
        }
        span = {
            "record_type": "APS",
            "schema_version": "1",
            "capture_session": "1",
            "acceptance_epoch": "1",
            "accepted_boundary_ordinal": str(ordinal),
            "opening_snapshot_sequence": str(opening_sequence),
            "closing_snapshot_sequence": str(sequence),
            "opening_reference_sequence": str(opening_sequence),
            "closing_reference_sequence": str(sequence),
            "opening_reference_timestamp_ticks": str(opening_ticks),
            "closing_reference_timestamp_ticks": str(timestamp),
            "time_domain": "rp2040_monotonic_us32",
            "source_count_first_sequence": str(sequence),
            "source_count_last_sequence": str(sequence),
            "source_count_record_count": "1",
            "counted_edges": str(NOMINAL_EDGES),
            "excluded_candidate_count": "0",
            "nominal_interval_count": "1",
            "acceptance_policy_sha256": policy,
        }
        generated_ref.append(reference)
        generated_snp.append(snapshot)
        generated_cnt.append(count)
        generated_aps.append(span)
        raw.extend(
            (
                _device_line("raw_events_v1", reference),
                _device_line("pps_snapshots_v2", snapshot),
                _device_line("count_observations_v1", count),
                _device_line("accepted_pps_spans_v1", span),
            )
        )
    _append_rows(csv_root / "reference_events.csv", ref_fields, generated_ref)
    _append_rows(csv_root / "pps_snapshots.csv", snp_fields, generated_snp)
    _append_rows(csv_root / "count_observations.csv", cnt_fields, generated_cnt)
    _append_rows(csv_root / "accepted_pps_spans_v1.csv", aps_fields, generated_aps)
    return raw


def _append_estimates(
    destination: Path, estimate_source: Path, apertures: int
) -> list[bytes]:
    path = destination / "csv/estimates_v3.csv"
    fields, existing = _read_rows(path)
    if existing:
        raise ValueError("synthetic source must have no pre-existing EST rows")
    template_fields, template_rows = _read_rows(
        estimate_source / "csv/estimates_v3.csv"
    )
    if fields != template_fields or not template_rows:
        raise ValueError("current fixed-image EST template is unavailable")
    template = template_rows[0]
    estimates: list[dict[str, str]] = []
    raw: list[bytes] = []
    for sequence, closing in enumerate(
        range(ESTIMATE_WINDOW, apertures + 1, ESTIMATE_WINDOW), 1
    ):
        opening = closing - ESTIMATE_WINDOW
        row = deepcopy(template)
        row.update(
            estimate_seq=str(sequence),
            estimate_id=f"offline-capacity-estimate-{sequence}",
            estimator_timestamp_ticks=str((closing * 1_000_000) % U32),
            capture_session="1",
            source_acceptance_epoch="1",
            source_opening_accepted_boundary_ordinal=str(opening),
            source_closing_accepted_boundary_ordinal=str(closing),
            source_opening_snapshot_sequence=str(opening),
            source_closing_snapshot_sequence=str(closing),
            source_opening_reference_sequence=str(opening),
            source_closing_reference_sequence=str(closing),
            source_accepted_spans_ref=f"live:APS:1:1:{opening}:{closing}",
            accepted_sample_count=str(ESTIMATE_WINDOW),
            frequency_observation_hz="10000000.000000000000",
            frequency_estimate_hz="10000000.000000000000",
            frequency_error_hz="0.000000000000",
        )
        estimates.append(row)
        raw.append(_device_line("estimates_v3", row))
    _append_rows(path, fields, estimates)
    return raw


def _append_dense_phase(destination: Path) -> tuple[list[bytes], int]:
    """Generate ideal, source-bound phase observations without control evidence."""

    manifest = load_manifest(destination).data
    inputs = validate_authoritative_inputs(manifest["authoritative_inputs"])
    phase_hash = inputs.binding(
        inputs.document(ROOT_PROFILE)["bindings"]["phase_estimator"]
    )["sha256"]
    span_path = destination / "csv/accepted_pps_spans_v1.csv"
    rph_path = destination / "csv/relative_phase_observations_v2.csv"
    phe_path = destination / "csv/phase_estimator_outputs_v2.csv"
    raw: list[bytes] = []
    with (
        span_path.open(newline="", encoding="utf-8") as span_stream,
        rph_path.open("w", newline="", encoding="utf-8") as rph_stream,
        phe_path.open("w", newline="", encoding="utf-8") as phe_stream,
    ):
        rph_writer = csv.DictWriter(
            rph_stream, fieldnames=CONTRACT_FIELDS["relative_phase_observations_v2"]
        )
        phe_writer = csv.DictWriter(
            phe_stream, fieldnames=CONTRACT_FIELDS["phase_estimator_outputs_v2"]
        )
        rph_writer.writeheader()
        phe_writer.writeheader()
        count = 0
        for count, span in enumerate(csv.DictReader(span_stream), 1):
            if int(span["counted_edges"]) != NOMINAL_EDGES:
                raise ValueError(
                    "dense phase input requires ideal nominal D8 intervals"
                )
            identity = {
                key: span[key]
                for key in (
                    "capture_session",
                    "acceptance_epoch",
                    "accepted_boundary_ordinal",
                )
            }
            ordinal = int(identity["accepted_boundary_ordinal"])
            rph = {
                "record_type": "RPH",
                "schema_version": "2",
                "phase_epoch": "1",
                "observation_sequence": str(count),
                **identity,
                "source_accepted_span_ref": (
                    f"live:APS:{identity['capture_session']}:"
                    f"{identity['acceptance_epoch']}:{ordinal}"
                ),
                **{
                    key: span[key]
                    for key in (
                        "opening_snapshot_sequence",
                        "closing_snapshot_sequence",
                        "opening_reference_sequence",
                        "closing_reference_sequence",
                    )
                },
                "dac_epoch": "1",
                "source_backend": "pio_wait_cumulative_snapshot_fifo_irq_v2",
                "source_file_sha256": "live_stream_unsealed",
                "method_id": "D14_ACCEPTED_SPAN_RELATIVE_PHASE_ACCUMULATOR_V1",
                "configuration_sha256": phase_hash,
                "interval_edges": str(NOMINAL_EDGES),
                "edge_error_cycles": "0",
                "relative_phase_cycles": "0",
                "relative_phase_time_ns": "0",
                "qualification_state": "qualified",
                "observation_age_s": "0",
                "discontinuity_reason": "",
                "calibrated_uncertainty_status": "unavailable",
            }
            warm = count >= ESTIMATE_WINDOW
            phe = {
                "record_type": "PHE",
                "schema_version": "2",
                "phase_epoch": "1",
                "observation_sequence": str(count),
                **identity,
                "source_relative_phase_observation": f"RPH:1:{count}",
                "raw_relative_phase_cycles": "0",
                "raw_relative_phase_time_ns": "0",
                "filtered_relative_phase_cycles": "0",
                "estimated_frequency_error_hz": "0.000000000000" if warm else "",
                "estimator_id": "OTIS_RELATIVE_PHASE_ESTIMATOR_V1",
                "configuration_sha256": phase_hash,
                "estimate_age_s": str(count % ESTIMATE_WINDOW) if warm else "",
                "qualification_state": "qualified" if warm else "initializing",
                "uncertainty_status": "unavailable",
                "reason_codes": (
                    "frequency_estimate_fresh"
                    if warm and count % ESTIMATE_WINDOW == 0
                    else "frequency_estimate_retained"
                    if warm
                    else "frequency_estimate_initializing"
                ),
            }
            rph_writer.writerow(rph)
            phe_writer.writerow(phe)
            raw.extend(
                (
                    _device_line("relative_phase_observations_v2", rph),
                    _device_line("phase_estimator_outputs_v2", phe),
                )
            )
    return raw, count


def _rewrite_frontier(destination: Path, manifest: dict[str, object]) -> None:
    report = destination / "reports/acquisition_frontier_v1.json"
    value = json.loads(report.read_text(encoding="utf-8"))
    value["source_manifest_sha256"] = _digest(manifest)
    unsigned = {key: item for key, item in value.items() if key != "frontier_sha256"}
    value["frontier_sha256"] = _digest(unsigned)
    report.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    state_path = destination / "reports/acquisition_frontier_live_state_v1.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["source_manifest_sha256"] = value["source_manifest_sha256"]
    state["frontier_sha256"] = value["frontier_sha256"]
    state_path.write_text(
        json.dumps(state, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def _rewrite_raw_and_closure(
    destination: Path, generated: list[bytes], run_manifest: Path
) -> None:
    raw_path = destination / "raw/serial.log"
    original = raw_path.read_bytes().splitlines(keepends=True)
    inserted = False
    rewritten: list[bytes] = []
    for line in original:
        if line.startswith(b"# OTIS_HOST "):
            marker = json.loads(line[len(b"# OTIS_HOST ") :])
            if marker.get("event") == "acquisition_frontier_established":
                marker["frontier_sha256"] = json.loads(
                    (destination / "reports/acquisition_frontier_v1.json").read_text()
                )["frontier_sha256"]
                line = (
                    b"# OTIS_HOST "
                    + json.dumps(marker, sort_keys=True).encode()
                    + b"\n"
                )
            if marker.get("event") == "emergency_abort_sent" and not inserted:
                rewritten.extend(generated)
                inserted = True
            if marker.get("event") == "capture_stopped":
                continue
        rewritten.append(line)
    if not inserted:
        raise ValueError("source raw capture has no emergency-abort boundary")
    device = [line for line in rewritten if not line.startswith(b"# OTIS_HOST ")]
    source_closure = json.loads(
        (destination / "reports/capture_segment_closure_v1.json").read_text()
    )
    counters = dict(source_closure["counters"])
    counters.update(
        bytes_written=sum(len(line) for line in device),
        lines_seen=len(device),
        lines_parsed=len(device),
        malformed_utf8=0,
        parser_errors=0,
        reconnect_count=0,
    )
    owner_pid = 1
    marker = {
        "event": "capture_stopped",
        "utc": "2026-09-12T12:00:00Z",
        **counters,
        "normal_command_buffered_bytes_discarded": 0,
        "emergency_abort_latched": True,
        "owner_pid": owner_pid,
        "transport_generation": 1,
    }
    rewritten.append(
        b"# OTIS_HOST " + json.dumps(marker, sort_keys=True).encode() + b"\n"
    )
    raw_path.write_bytes(b"".join(rewritten))
    closure = {
        "schema_version": 1,
        "protocol": "otis_capture_closure_v1",
        "closed_utc": "2026-09-12T12:00:00Z",
        "run": str(destination),
        "run_manifest_sha256": sha256(run_manifest.read_bytes()).hexdigest(),
        "device": "/dev/ttys999",
        "baud": 115200,
        "owner_pid": owner_pid,
        "transport_generation": 1,
        "closure_mode": "physical_serial_close",
        "logical_segment_closed": True,
        "physical_serial_open": False,
        "serial_reopened": False,
        "counters": counters,
    }
    (destination / "reports/capture_segment_closure_v1.json").write_text(
        json.dumps(closure, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def generate(
    *,
    source: Path,
    estimate_source: Path,
    destination: Path,
    firmware_manifest: Path,
    apertures: int,
    dense_phase: bool,
) -> None:
    if apertures % ESTIMATE_WINDOW:
        raise ValueError("apertures must be an exact multiple of 600")
    source_package_sha256, source_inventory = _validate_simulated_donor(
        source, role="measurement"
    )
    estimate_package_sha256, _ = _validate_simulated_donor(
        estimate_source, role="estimate"
    )
    _copy_source(source, destination, source_inventory)
    spec = build_run_spec(
        firmware_manifest_path=firmware_manifest,
        purpose="inhibited_zero_write",
        output_path=destination / "run_spec.json",
        created_utc="2026-09-12T12:00:00Z",
    )
    record = create_run_record(
        spec,
        execution_kind="simulated",
        run_id=destination.name,
        started_at_utc="2026-09-12T12:00:00Z",
        serial_device="/dev/ttys999",
        output_path=destination / "run_manifest.json",
    )
    manifest = spec.runtime_manifest(record)
    _rewrite_frontier(destination, manifest)
    raw = _append_measurements(destination, apertures)
    raw.extend(_append_estimates(destination, estimate_source, apertures))
    phase_pairs = 0
    if dense_phase:
        phase_raw, phase_pairs = _append_dense_phase(destination)
        raw.extend(phase_raw)
    _rewrite_raw_and_closure(destination, raw, destination / "run_manifest.json")
    metadata = {
        "schema_version": 1,
        "contract": "otis_offline_capacity_fixture_v1",
        "kind": "synthetic_nonqualification",
        "measurement_source": {
            "path": str(source),
            "package_content_sha256": source_package_sha256,
        },
        "estimate_source": {
            "path": str(estimate_source),
            "package_content_sha256": estimate_package_sha256,
        },
        "generator": {
            "path": Path(__file__).name,
            "sha256": _sha256_file(Path(__file__)),
        },
        "target_apertures": apertures,
        "selected_estimate_count": apertures // ESTIMATE_WINDOW,
        "control_or_dac_records_generated": False,
        "phase_history_generated": dense_phase,
        "phase_pair_count": phase_pairs,
        "phase_history_model": (
            "ideal stationary oscillator; exact APS/RPH/PHE joins; "
            "no firmware initialization or controller execution claim"
            if dense_phase
            else "not generated"
        ),
        "raw_extension_precedes_priority_abort_and_capture_stopped": True,
    }
    (destination / "reports/offline_capacity_fixture_v1.json").write_text(
        json.dumps(metadata, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--estimate-source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--firmware-manifest", type=Path, required=True)
    parser.add_argument("--apertures", type=int, default=259_200)
    parser.add_argument("--dense-phase", action="store_true")
    args = parser.parse_args(argv)
    generate(
        source=args.source,
        estimate_source=args.estimate_source,
        destination=args.destination,
        firmware_manifest=args.firmware_manifest,
        apertures=args.apertures,
        dense_phase=args.dense_phase,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
