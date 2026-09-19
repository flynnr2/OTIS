"""Prospective retained-observation frontier; never repairs historical evidence."""
from __future__ import annotations

from collections import deque
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .raw_measurement_replay import (
    SELECTED_ESTIMATOR_ID, _RAW_REFERENCE_DOMAIN, _SNAPSHOT_BACKEND,
    _U32_MODULUS, _raw_count_replay, _u32,
)
from .accepted_span_replay import (
    POLICY_PATH, accepted_window_ref, replay_accepted_spans,
)
from .authoritative_inputs import ValidatedAuthoritativeInputs, validate_authoritative_inputs
from .time_domains import forward_progress

FRONTIER_PATH = "reports/acquisition_frontier_v1.json"
FRONTIER_STATE_PATH = "reports/acquisition_frontier_live_state_v1.json"
FRONTIER_POLICY = {
    "policy_id": "otis_prospective_acquisition_frontier_v1",
    "selection": "first_unique_retained_adjacent_single_owner_SNP_CNT_pair_with_REF_derivatives",
    "prefix": "retained_unqualified",
    "authority": "manual_setup_requires_raw_anchor_feedback_requires_complete_600_accepted_span_source",
    "advancement": "forbidden",
}


class _SourcePending(RuntimeError):
    """A declared evidence source may still be queued on the raw transport."""


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _validate_selected_estimate_source(
    row: dict[str, str], verified: list[dict[str, Any]], manifest: dict[str, Any]
) -> None:
    if len(verified) != 600:
        raise ValueError("selected EST source is not exactly 600 accepted spans")
    session = int(row["capture_session"])
    epoch = int(row["source_acceptance_epoch"])
    opening = int(row["source_opening_accepted_boundary_ordinal"])
    closing = int(row["source_closing_accepted_boundary_ordinal"])
    first, last = verified[0], verified[-1]
    if (
        row.get("time_domain") != _RAW_REFERENCE_DOMAIN
        or (closing - opening) % _U32_MODULUS != 600
        or row.get("source_accepted_spans_ref")
            != accepted_window_ref(session, epoch, opening, closing)
        or int(row.get("source_opening_snapshot_sequence", -1))
            != first["opening_snapshot_sequence"]
        or int(row.get("source_closing_snapshot_sequence", -1))
            != last["closing_snapshot_sequence"]
        or int(row.get("source_opening_reference_sequence", -1))
            != first["opening_reference_sequence"]
        or int(row.get("source_closing_reference_sequence", -1))
            != last["closing_reference_sequence"]
        or row.get("accepted_sample_count") != "600"
        or row.get("config_hash")
            != manifest.get("transaction_identities", {}).get("estimator_sha256")
        or any(
            row.get(field) != "valid"
            for field in ("observation_validity", "reference_validity", "count_validity")
        )
    ):
        raise ValueError("selected EST does not match its accepted source identity")
    from decimal import Decimal
    total = sum(item["counted_edges"] for item in verified)
    frequency = Decimal.from_float(float(total) / 600.0)
    error_hz = Decimal.from_float(float(total) / 600.0 - 10_000_000.0)
    tolerance = Decimal("0.0000000000005")
    reported_frequency = Decimal(row["frequency_estimate_hz"])
    reported_error = Decimal(row["frequency_error_hz"])
    if not reported_frequency.is_finite() or not reported_error.is_finite():
        raise ValueError("selected EST arithmetic is not finite")
    if (
        abs(reported_frequency - frequency) > tolerance
        or abs(reported_error - error_hz) > tolerance
    ):
        raise ValueError("selected EST arithmetic differs from retained raw source")


def _write_state(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    temporary.replace(path)


def _read_frontier(run_dir: Path, manifest_value: dict[str, Any]) -> dict[str, Any]:
    if manifest_value.get("acquisition_frontier") != FRONTIER_POLICY:
        raise ValueError("acquisition frontier policy differs from frozen current policy")
    artifact = json.loads((run_dir / FRONTIER_PATH).read_text())
    if not isinstance(artifact, dict):
        raise ValueError("acquisition frontier artifact is not an object")
    unsigned = {key: value for key, value in artifact.items() if key != "frontier_sha256"}
    if artifact.get("frontier_sha256") != _digest(unsigned):
        raise ValueError("acquisition frontier digest mismatch")
    if artifact.get("source_manifest_sha256") != _digest(manifest_value):
        raise ValueError("acquisition frontier manifest binding mismatch")
    if artifact.get("policy") != FRONTIER_POLICY:
        raise ValueError("acquisition frontier artifact policy mismatch")
    _validate_artifact_body(artifact)
    return artifact


def read_acquisition_readiness(
    run_dir: Path, manifest_value: dict[str, Any], *, source_estimate_id: str | None = None, expected_capture_session: int | None = None,
    validated_inputs: ValidatedAuthoritativeInputs | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = dict(ready=False, anchor_ready=False, source_ready=False, errors=[], frontier_sha256=None, source_proof=None, capture_session=None)
    try:
        if manifest_value.get("acquisition_frontier") != FRONTIER_POLICY:
            raise ValueError("acquisition frontier policy differs from the frozen policy")
        if expected_capture_session is not None and (type(expected_capture_session) is not int or not 0 <= expected_capture_session < 1 << 32):
            raise ValueError("expected capture session is outside its uint32 domain")
        state_path = run_dir / FRONTIER_STATE_PATH
        if not state_path.exists() and not (run_dir / FRONTIER_PATH).exists():
            return result
        state = json.loads(state_path.read_text())
        ids, proofs = _validate_live_state(state, manifest_value)
        result["errors"] = list(state["errors"])
        if not (run_dir / FRONTIER_PATH).exists():
            if state["anchor_ready"] or state.get("frontier_sha256") is not None or ids:
                raise ValueError("live state claims an absent immutable frontier")
            return result
        artifact = _read_frontier(run_dir, manifest_value)
        if not _live_marker_at_offset(run_dir, artifact, state.get("frontier_marker_search_offset")):
            return result  # Recorder may still be finishing its raw marker.
        if state.get("frontier_sha256") != artifact["frontier_sha256"] or state["anchor_ready"] != (not state["errors"] and state.get("current_session_pair_ready") is True):
            raise ValueError("acquisition frontier live state binding or readiness mismatch")
        for name, tag in _SOURCE_TYPES.items():
            _bind_source_at_offset(run_dir, manifest_value, tag, artifact[name])
        result["frontier_sha256"] = artifact["frontier_sha256"]
        result["capture_session"] = state.get("current_capture_session")
        if type(result["capture_session"]) is not int or type(state.get("current_session_pair_ready")) is not bool:
            raise ValueError("acquisition current session readiness is malformed")
        if expected_capture_session is not None and result["capture_session"] != expected_capture_session:
            return result  # Coherent recorder generation may lag current status.
        result["anchor_ready"] = state["anchor_ready"] and not result["errors"]
        if source_estimate_id is not None and source_estimate_id in ids:
            proof = proofs[ids.index(source_estimate_id)]
            estimate = _bind_source_at_offset(run_dir, manifest_value, "EST", proof)
            spans = _bind_accepted_span_window(run_dir, manifest_value, proof)
            snapshots, references, counts = _bind_raw_source_window(
                run_dir, manifest_value, proof
            )
            inputs = validated_inputs
            if inputs is None:
                inputs = validate_authoritative_inputs(manifest_value.get("authoritative_inputs"))
            elif not inputs.matches(manifest_value.get("authoritative_inputs")):
                raise ValueError("acquisition readiness authoritative inputs differ")
            policy = inputs.document(POLICY_PATH)
            policy_sha = inputs.binding(POLICY_PATH)["sha256"]
            exact, report, verified = replay_accepted_spans(
                snapshots, references, counts, spans,
                acceptance_policy=policy,
                acceptance_policy_sha256=str(policy_sha),
            )
            session = int(estimate["capture_session"])
            epoch = int(estimate["source_acceptance_epoch"])
            opening = int(estimate["source_opening_accepted_boundary_ordinal"])
            closing = int(estimate["source_closing_accepted_boundary_ordinal"])
            if (
                not exact
                or len(verified) != 600
                or proof.get("capture_session") != session
                or proof.get("source_acceptance_epoch") != epoch
                or proof.get("source_opening_accepted_boundary_ordinal") != opening
                or proof.get("source_closing_accepted_boundary_ordinal") != closing
                or (closing - opening) % _U32_MODULUS != 600
                or estimate.get("source_accepted_spans_ref")
                    != accepted_window_ref(session, epoch, opening, closing)
                or any(
                    int(row["capture_session"]) != session
                    or int(row["acceptance_epoch"]) != epoch
                    or int(row["accepted_boundary_ordinal"])
                        != (opening + index) % _U32_MODULUS
                    for index, row in enumerate(spans, start=1)
                )
            ):
                raise ValueError(
                    "live selected EST source does not reconstruct from retained APS/raw evidence: "
                    + "; ".join(report["errors"])
                )
            _validate_selected_estimate_source(estimate, verified, manifest_value)
            if proof.get("capture_session") != result["capture_session"]:
                raise ValueError("selected EST proof belongs to a different capture session")
            result["source_proof"] = proof
            result["source_ready"] = result["anchor_ready"]
        result["ready"] = result["anchor_ready"] if source_estimate_id is None else result["source_ready"]
    except (OSError, KeyError, TypeError, ValueError) as error:
        result["ready"] = result["anchor_ready"] = result["source_ready"] = False
        result["errors"].append(str(error))
    return result


class AcquisitionFrontierTracker:
    """Bounded live observer of records already accepted by the CSV splitter.

    This is evidence readiness only. Errors inhibit new host authority; they
    neither abort capture nor modify any canonical record or existing frontier.
    """

    def __init__(self, run_dir: Path, manifest_value: dict[str, Any]) -> None:
        if manifest_value.get("acquisition_frontier") != FRONTIER_POLICY:
            raise ValueError("acquisition frontier requires the frozen current policy")
        self.run_dir = Path(run_dir)
        self.manifest_sha = _digest(manifest_value)
        self.manifest = manifest_value
        inputs = validate_authoritative_inputs(manifest_value.get("authoritative_inputs"))
        self.acceptance_policy = inputs.document(POLICY_PATH)
        self.acceptance_policy_sha256 = str(inputs.binding(POLICY_PATH)["sha256"])
        self.frontier: dict[str, Any] | None = None
        self.errors: list[str] = []
        self.ordinals: dict[str, int] = {}
        # Six hundred admitted spans may each contain eight excluded raw
        # candidates. Retain exactly that bounded worst-case source horizon.
        self.references: deque[dict[str, Any]] = deque(maxlen=5402)
        self.snapshots: deque[dict[str, Any]] = deque(maxlen=5402)
        self.counts: deque[dict[str, Any]] = deque(maxlen=5401)
        self.spans: deque[dict[str, Any]] = deque(maxlen=601)
        self.qualified_estimate_ids: deque[str] = deque(maxlen=2)
        self.qualified_estimates: deque[dict[str, Any]] = deque(maxlen=2)
        self.pending_estimates: dict[str, dict[str, Any]] = {}
        self.seen_selected_ids: set[str] = set()
        self.previous_estimate_sequence: int | None = None
        self.unqualified_estimate_count = 0
        self.last_line = 0
        self.frontier_marker_search_offset: int | None = None
        self.current_capture_session: int | None = None
        self.current_session_pair_ready = False
        self.closed_sessions: set[int] = set()
        if (self.run_dir / FRONTIER_PATH).exists() or (self.run_dir / FRONTIER_STATE_PATH).exists():
            raise ValueError("acquisition tracker cannot restart or replace an existing frontier state")
        self._publish()

    def _publish(self) -> None:
        _write_state(self.run_dir / FRONTIER_STATE_PATH, {
            "schema_version": 1, "source_manifest_sha256": self.manifest_sha,
            "frontier_marker_search_offset": self.frontier_marker_search_offset,
            "frontier_sha256": self.frontier["frontier_sha256"] if self.frontier else None,
            "anchor_ready": self.frontier is not None and self.current_session_pair_ready and not self.errors,
            "current_capture_session": self.current_capture_session,
            "current_session_pair_ready": self.current_session_pair_ready,
            "qualified_estimate_ids": list(self.qualified_estimate_ids),
            "qualified_estimates": list(self.qualified_estimates),
            "pending_estimate_ids": list(self.pending_estimates),
            "unqualified_estimate_count": self.unqualified_estimate_count,
            "last_capture_line_ordinal": self.last_line,
            "errors": list(self.errors),
        })

    def note_marker_search_offset(self, offset: int) -> None:
        if self.frontier is None or self.frontier_marker_search_offset is not None or type(offset) is not int or offset < 0:
            raise ValueError("frontier raw marker search position cannot be replaced or invented")
        self.frontier_marker_search_offset = offset
        self._publish()

    def note_discrepancy(self, reason: str, *, line_number: int | None = None) -> None:
        message = f"line {line_number}: {reason}" if line_number is not None else reason
        if message not in self.errors and len(self.errors) < 20:
            self.errors.append(message)
            self._publish()

    def observe(self, record: dict[str, str], *, line_number: int, csv_byte_offset: int | None = None) -> None:
        tag = record.get("record_type")
        if tag not in {"REF", "SNP", "CNT", "APS", "EST"}:
            return  # D10 is never a source or veto for this frontier.
        try:
            if type(line_number) is not int or line_number <= self.last_line:
                raise ValueError("capture line ordering is not strictly increasing")
            self.last_line = line_number
            self.ordinals[tag] = self.ordinals.get(tag, 0) + 1
            source = {
                "record_type": tag, "csv_row_ordinal": self.ordinals[tag],
                "capture_line_ordinal": line_number, "row_sha256": _digest(record),
                "csv_byte_offset": csv_byte_offset,
                "record": dict(record),
            }
            if tag == "REF":
                self._reference(source)
            elif tag == "SNP":
                self._snapshot(source)
            elif tag == "CNT":
                self._count(source)
            elif tag == "APS":
                self._span(source)
            else:
                self._estimate(source)
        except (KeyError, TypeError, ValueError, ArithmeticError) as error:
            self.note_discrepancy(str(error), line_number=line_number)

    def _reference(self, source: dict[str, Any]) -> None:
        row = source["record"]
        sequence = _u32(row, "event_seq")
        _u32(row, "timestamp_ticks")
        if (row["channel_id"], row["edge"], row["capture_domain"]) != ("1", "R", _RAW_REFERENCE_DOMAIN):
            raise ValueError("REF differs from the declared D14 producer")
        if self.references and sequence <= int(self.references[-1]["record"]["event_seq"]):
            raise ValueError("REF emitted sequence duplicates, reverses, or wraps")
        self.references.append(source)

    def _snapshot(self, source: dict[str, Any]) -> None:
        row = source["record"]
        session, sequence = _u32(row, "session"), _u32(row, "snapshot_sequence")
        reference_sequence = _u32(row, "reference_sequence")
        ticks = _u32(row, "reference_timestamp_ticks")
        uncertainty = _u32(row, "timestamp_uncertainty_ticks")
        _u32(row, "cumulative_down_counter")
        status = _u32(row, "status")
        if row.get("schema_version") != "2" or row["backend"] != _SNAPSHOT_BACKEND:
            raise ValueError("SNP contract or backend is unsupported")
        if reference_sequence != sequence:
            raise ValueError("SNP reference identity differs from its FIFO-word ordinal")
        if status & ~0x1F or (uncertainty == 0xFFFFFFFF) != bool(status & (1 << 1)):
            raise ValueError("SNP transport status or uncertainty is contradictory")
        previous = self.snapshots[-1] if self.snapshots else None
        if previous:
            before = previous["record"]
            if session == int(before["session"]):
                if sequence != (int(before["snapshot_sequence"]) + 1) % _U32_MODULUS or reference_sequence != (int(before["reference_sequence"]) + 1) % _U32_MODULUS:
                    raise ValueError("SNP snapshot/source sequence gap or reordering")
                if not forward_progress(int(before["reference_timestamp_ticks"]), ticks, domain=_RAW_REFERENCE_DOMAIN).valid:
                    raise ValueError("SNP timestamp progression is ambiguous")
            else:
                self.current_session_pair_ready = False
                self.qualified_estimate_ids.clear()
                self.qualified_estimates.clear()
                self.pending_estimates = {
                    identity: item
                    for identity, item in self.pending_estimates.items()
                    if int(item["record"]["capture_session"]) == session
                }
                self.spans = deque(
                    (
                        item for item in self.spans
                        if int(item["record"]["capture_session"]) == session
                    ),
                    maxlen=601,
                )
                self.closed_sessions.add(int(before["session"]))
                if session in self.closed_sessions:
                    raise ValueError("SNP returns to a closed session")
        # REF is the immediately preceding same-owner serial presentation,
        # audited for raw preservation. It never chooses or authorizes a SNP.
        candidate = self.references[-1] if self.references else None
        prior_reference = previous.get("reference") if previous else None
        if (
            candidate is None
            or (prior_reference is not None and candidate["csv_row_ordinal"] <= prior_reference["csv_row_ordinal"])
            or int(candidate["record"]["timestamp_ticks"]) != ticks
            or candidate["capture_line_ordinal"] >= source["capture_line_ordinal"]
        ):
            candidate = None
        source["reference"] = candidate
        if candidate is None and (self.frontier is not None or previous is not None):
            raise ValueError("SNP is missing its same-owner REF derivative")
        if previous and int(previous["record"]["session"]) == session and prior_reference and candidate:
            if candidate["csv_row_ordinal"] != prior_reference["csv_row_ordinal"] + 1:
                raise ValueError("REF derivative stream has an interior gap")
        self.snapshots.append(source)
        self.current_capture_session = session
        if not self.current_session_pair_ready:
            self._publish()

    def _count(self, source: dict[str, Any]) -> None:
        row = source["record"]
        sequence = _u32(row, "count_seq")
        if self.counts:
            before = self.counts[-1]["record"]
            same_session = bool(self.snapshots) and self.counts[-1].get("session") == self.snapshots[-1]["record"]["session"]
            if same_session and sequence != (int(before["count_seq"]) + 1) % _U32_MODULUS:
                raise ValueError("CNT sequence gap or reordering")
        source["session"] = self.snapshots[-1]["record"]["session"] if self.snapshots else None
        self.counts.append(source)
        if len(self.snapshots) < 2 or not all(item.get("reference") for item in list(self.snapshots)[-2:]):
            if self.frontier is not None:
                raise ValueError("required CNT lacks its opening retained SNP/REF")
            return  # Explicit leading incomplete aperture, preserved in full CSV.
        pair = list(self.snapshots)[-2:]
        if pair[0]["record"]["session"] != pair[1]["record"]["session"]:
            raise ValueError("CNT crosses a snapshot session boundary")
        # Include one previous aperture to reconstruct the producer's one-step
        # recovery inhibition. That aperture has already been checked live.
        history = pair
        count_history = [source]
        if self.frontier and len(self.snapshots) >= 3 and len(self.counts) >= 2:
            candidate = list(self.snapshots)[-3:]
            if len({item["record"]["session"] for item in candidate}) == 1:
                history, count_history = candidate, list(self.counts)[-2:]
        _, report, intervals = _raw_count_replay(
            [item["record"] for item in history],
            [item["reference"]["record"] for item in history],
            [item["record"] for item in count_history],
        )
        if (not self.frontier and not report.get("source_exact")) or not intervals or not intervals[-1]["count_exact"]:
            raise ValueError("CNT does not reproduce retained SNP source: " + "; ".join(report["errors"]))
        session_pair_became_ready = not self.current_session_pair_ready
        self.current_session_pair_ready = True
        if self.frontier is None and not self.errors:
            def immutable(item):
                return {key: value for key, value in item.items() if key not in {"reference", "session"}}
            artifact = {
                "schema_version": 1, "policy": FRONTIER_POLICY,
                "source_manifest_sha256": self.manifest_sha,
                "opening_reference": immutable(pair[0]["reference"]),
                "opening_snapshot": immutable(pair[0]),
                "closing_reference": immutable(pair[1]["reference"]),
                "closing_snapshot": immutable(pair[1]),
                "first_count": immutable(source),
                "prefix_disposition": "retained_unqualified",
            }
            artifact["frontier_sha256"] = _digest(artifact)
            path = self.run_dir / FRONTIER_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(artifact, sort_keys=True, indent=2) + "\n")
            self.frontier = artifact
            self._publish()
        self._reconsider_estimates(force_publish=session_pair_became_ready)

    def _span(self, source: dict[str, Any]) -> None:
        row = source["record"]
        session = _u32(row, "capture_session")
        epoch = _u32(row, "acceptance_epoch")
        ordinal = _u32(row, "accepted_boundary_ordinal")
        if not session or not epoch:
            raise ValueError("APS source identity is zero")
        if row.get("acceptance_policy_sha256") != self.acceptance_policy_sha256:
            raise ValueError("APS acceptance policy differs from frozen inputs")
        if session in self.closed_sessions:
            raise ValueError("APS belongs to a closed capture session")
        same_session = [
            item for item in self.spans
            if int(item["record"]["capture_session"]) == session
        ]
        if same_session:
            before = same_session[-1]["record"]
            before_identity = (
                int(before["capture_session"]), int(before["acceptance_epoch"]),
                int(before["accepted_boundary_ordinal"]),
            )
            if (session, epoch) == before_identity[:2]:
                if ordinal != (before_identity[2] + 1) % _U32_MODULUS:
                    raise ValueError("APS accepted boundary ordinal is discontinuous")
            elif session == before_identity[0] and epoch <= before_identity[1]:
                raise ValueError("APS acceptance epoch moved backward")
        self.spans.append(source)
        self._reconsider_estimates(force_publish=False)

    def _estimate(self, source: dict[str, Any]) -> None:
        row = source["record"]
        sequence = _u32(row, "estimate_seq")
        if self.previous_estimate_sequence is not None and sequence != (self.previous_estimate_sequence + 1) % _U32_MODULUS:
            raise ValueError("EST sequence gap or reordering")
        self.previous_estimate_sequence = sequence
        if row.get("estimator_version") != SELECTED_ESTIMATOR_ID:
            return
        if _u32(row, "capture_session") in self.closed_sessions:
            raise ValueError("selected EST belongs to a closed capture session")
        identity = row["estimate_id"]
        if identity in self.seen_selected_ids:
            raise ValueError("selected EST identity is duplicated")
        if len(self.seen_selected_ids) >= 2048:
            raise ValueError("selected EST identities exceed bounded campaign retention")
        self.seen_selected_ids.add(identity)
        if len(self.pending_estimates) >= 2:
            raise ValueError("selected EST source remains pending beyond bounded retention")
        # A newer selected estimator frontier immediately retires earlier ARM
        # proofs, even when its independent raw source queue is still catching up.
        self.qualified_estimate_ids.clear()
        self.qualified_estimates.clear()
        self.pending_estimates[identity] = source
        self._reconsider_estimates(force_publish=True)

    def _reconsider_estimates(self, *, force_publish: bool = False) -> None:
        for identity, source in list(self.pending_estimates.items()):
            disposition = self._evaluate_estimate(source)
            if disposition == "pending":
                continue
            del self.pending_estimates[identity]
            force_publish = True
            if disposition == "unqualified_prefix":
                self.unqualified_estimate_count += 1
            else:
                self.qualified_estimate_ids.append(identity)
                self.qualified_estimates.append({
                    "estimate_id": identity, "row_sha256": source["row_sha256"],
                    "csv_row_ordinal": source["csv_row_ordinal"],
                    "capture_line_ordinal": source["capture_line_ordinal"],
                    "csv_byte_offset": source["csv_byte_offset"],
                    "record": source["record"],
                    "capture_session": self.current_capture_session,
                    "source_acceptance_epoch": int(source["record"]["source_acceptance_epoch"]),
                    "source_opening_accepted_boundary_ordinal": int(source["record"]["source_opening_accepted_boundary_ordinal"]),
                    "source_closing_accepted_boundary_ordinal": int(source["record"]["source_closing_accepted_boundary_ordinal"]),
                    "accepted_span_sources": source["accepted_span_sources"],
                    "raw_reference_sources": source["raw_reference_sources"],
                    "raw_snapshot_sources": source["raw_snapshot_sources"],
                    "raw_count_sources": source["raw_count_sources"],
                })
        if force_publish:
            self._publish()

    def _evaluate_estimate(self, source: dict[str, Any]) -> str:
        row = source["record"]
        if self.frontier is None:
            return "pending"
        try:
            session = _u32(row, "capture_session")
            epoch = _u32(row, "source_acceptance_epoch")
            opening = _u32(row, "source_opening_accepted_boundary_ordinal")
            closing = _u32(row, "source_closing_accepted_boundary_ordinal")
        except (KeyError, TypeError, ValueError):
            raise ValueError("selected EST accepted source identity is malformed")
        available = [item for item in self.spans
                     if int(item["record"]["capture_session"]) == session
                     and int(item["record"]["acceptance_epoch"]) == epoch]
        source_spans = [item for item in available
                        if 0 < (int(item["record"]["accepted_boundary_ordinal"]) - opening) % _U32_MODULUS <= 600]
        source_spans.sort(key=lambda item: (int(item["record"]["accepted_boundary_ordinal"]) - opening) % _U32_MODULUS)
        if len(source_spans) < 600:
            return "pending"
        if len(source_spans) != 600 or (closing - opening) % _U32_MODULUS != 600:
            raise ValueError("selected EST accepted source range is not exactly 600 spans")
        try:
            snapshots, references, counts = self._raw_sources_for_spans(source_spans)
        except _SourcePending:
            return "pending"
        exact, report, verified = replay_accepted_spans(
            [item["record"] for item in snapshots],
            [item["record"] for item in references],
            [item["record"] for item in counts],
            [item["record"] for item in source_spans],
            acceptance_policy=self.acceptance_policy,
            acceptance_policy_sha256=self.acceptance_policy_sha256,
        )
        if not exact or len(verified) != 600:
            raise ValueError("selected EST source is not 600 exact accepted spans: " + "; ".join(report["errors"]))
        first = verified[0]
        opening_snapshot = snapshots[first["source_first_snapshot_position"]]
        frontier_session = int(self.frontier["closing_snapshot"]["record"]["session"])
        if (
            session == frontier_session
            and opening_snapshot["capture_line_ordinal"]
                < self.frontier["opening_snapshot"]["capture_line_ordinal"]
        ):
            return "unqualified_prefix"
        _validate_selected_estimate_source(row, verified, self.manifest)
        source["accepted_span_sources"] = [
            {
                "csv_row_ordinal": item["csv_row_ordinal"],
                "capture_line_ordinal": item["capture_line_ordinal"],
                "csv_byte_offset": item["csv_byte_offset"],
                "row_sha256": item["row_sha256"],
            }
            for item in source_spans
        ]
        source["raw_reference_sources"] = [
            _live_source_pointer(item) for item in references
        ]
        source["raw_snapshot_sources"] = [
            _live_source_pointer(item) for item in snapshots
        ]
        source["raw_count_sources"] = [
            _live_source_pointer(item) for item in counts
        ]
        return "qualified"

    def _raw_sources_for_spans(
        self, source_spans: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        first_row = source_spans[0]["record"]
        last_row = source_spans[-1]["record"]
        session = int(first_row["capture_session"])
        opening_key = (
            session,
            int(first_row["opening_snapshot_sequence"]),
            int(first_row["opening_reference_timestamp_ticks"]),
        )
        closing_key = (
            session,
            int(last_row["closing_snapshot_sequence"]),
            int(last_row["closing_reference_timestamp_ticks"]),
        )
        snapshots = list(self.snapshots)
        opening_positions = [
            index for index, item in enumerate(snapshots)
            if (
                int(item["record"]["session"]),
                int(item["record"]["snapshot_sequence"]),
                int(item["record"]["reference_timestamp_ticks"]),
            ) == opening_key
        ]
        closing_positions = [
            index for index, item in enumerate(snapshots)
            if (
                int(item["record"]["session"]),
                int(item["record"]["snapshot_sequence"]),
                int(item["record"]["reference_timestamp_ticks"]),
            ) == closing_key
        ]
        if len(opening_positions) > 1 or len(closing_positions) > 1:
            raise ValueError("selected EST APS window lacks unique raw SNP endpoints")
        if not opening_positions and any(
            int(item["record"]["session"]) == session
            and int(item["record"]["snapshot_sequence"]) == opening_key[1]
            for item in snapshots
        ):
            raise ValueError("selected EST APS opening SNP identity is contradictory")
        if not closing_positions and any(
            int(item["record"]["session"]) == session
            and int(item["record"]["snapshot_sequence"]) == closing_key[1]
            for item in snapshots
        ):
            raise ValueError("selected EST APS closing SNP identity is contradictory")
        if not opening_positions or not closing_positions:
            raise _SourcePending("selected EST APS raw SNP endpoints are pending")
        opening_position, closing_position = opening_positions[0], closing_positions[0]
        if closing_position <= opening_position:
            raise ValueError("selected EST APS raw SNP window is reversed")
        selected_snapshots = snapshots[opening_position : closing_position + 1]
        if any(item.get("reference") is None for item in selected_snapshots):
            raise ValueError("selected EST APS window lacks retained REF derivatives")
        selected_references = [item["reference"] for item in selected_snapshots]
        count_index: dict[int, list[dict[str, Any]]] = {}
        for item in self.counts:
            if item.get("session") == str(session):
                count_index.setdefault(int(item["record"]["count_seq"]), []).append(item)
        selected_counts: list[dict[str, Any]] = []
        for span in source_spans:
            row = span["record"]
            first_sequence = int(row["source_count_first_sequence"])
            last_sequence = int(row["source_count_last_sequence"])
            record_count = int(row["source_count_record_count"])
            if (
                not 1 <= record_count <= 9
                or (last_sequence - first_sequence) % _U32_MODULUS
                    != record_count - 1
            ):
                raise ValueError("selected APS raw count range is malformed")
            for offset in range(record_count):
                sequence = (first_sequence + offset) % _U32_MODULUS
                candidates = count_index.get(sequence, [])
                if len(candidates) > 1:
                    raise ValueError(
                        "selected APS lacks one exact same-session raw count source"
                    )
                if not candidates:
                    same_session_counts = [
                        int(item["record"]["count_seq"])
                        for item in self.counts
                        if item.get("session") == str(session)
                    ]
                    if same_session_counts and (
                        same_session_counts[-1] - sequence
                    ) % _U32_MODULUS <= 0x7FFFFFFF:
                        raise ValueError(
                            "selected APS raw count frontier passed a missing source"
                        )
                    raise _SourcePending("selected APS raw count source is pending")
                selected_counts.append(candidates[0])
        same_session_counts = [
            item for item in self.counts if item.get("session") == str(session)
        ]
        positions = {
            item["capture_line_ordinal"]: index
            for index, item in enumerate(same_session_counts)
        }
        selected_lines = [item["capture_line_ordinal"] for item in selected_counts]
        if len(set(selected_lines)) != len(selected_lines):
            raise ValueError("selected APS duplicates a raw count occurrence")
        first_position = positions[selected_lines[0]]
        last_position = positions[selected_lines[-1]]
        retained_occurrences = same_session_counts[first_position : last_position + 1]
        if selected_lines != [
            item["capture_line_ordinal"] for item in retained_occurrences
        ]:
            raise ValueError(
                "selected APS count sources omit or duplicate an interior raw count"
            )
        return selected_snapshots, selected_references, selected_counts


_SOURCE_TYPES = {
    "opening_reference": "REF", "opening_snapshot": "SNP",
    "closing_reference": "REF", "closing_snapshot": "SNP", "first_count": "CNT",
}


def _validate_artifact_body(artifact: dict[str, Any]) -> None:
    if artifact.get("schema_version") != 1 or artifact.get("prefix_disposition") != "retained_unqualified":
        raise ValueError("acquisition frontier artifact schema or prefix disposition differs")
    for name, tag in _SOURCE_TYPES.items():
        source = artifact.get(name)
        if not isinstance(source, dict) or source.get("record_type") != tag:
            raise ValueError(f"acquisition frontier {name} is malformed")
        for field in ("csv_row_ordinal", "capture_line_ordinal"):
            if type(source.get(field)) is not int or source[field] < 1:
                raise ValueError(f"acquisition frontier {name} has invalid {field}")
        row = source.get("record")
        if not isinstance(row, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in row.items()) or row.get("record_type") != tag or source.get("row_sha256") != _digest(row):
            raise ValueError(f"acquisition frontier {name} row identity differs")
    opening, closing = artifact["opening_snapshot"], artifact["closing_snapshot"]
    first_count = artifact["first_count"]
    if closing["csv_row_ordinal"] != opening["csv_row_ordinal"] + 1:
        raise ValueError("frontier snapshots are not adjacent retained rows")
    if artifact["closing_reference"]["csv_row_ordinal"] != artifact["opening_reference"]["csv_row_ordinal"] + 1:
        raise ValueError("frontier references are not adjacent retained D14 rows")
    if not opening["capture_line_ordinal"] < closing["capture_line_ordinal"] < first_count["capture_line_ordinal"]:
        raise ValueError("frontier SNP/CNT capture line order differs from producer")
    for name, snapshot in (("opening_reference", opening), ("closing_reference", closing)):
        if artifact[name]["capture_line_ordinal"] >= snapshot["capture_line_ordinal"]:
            raise ValueError("frontier REF does not precede its associated SNP")
    exact, report, _ = _raw_count_replay(
        [opening["record"], closing["record"]],
        [artifact["opening_reference"]["record"], artifact["closing_reference"]["record"]],
        [first_count["record"]],
    )
    if not exact:
        raise ValueError("frontier does not contain an exact complete raw pair: " + "; ".join(report["errors"]))


def _bind_source(source: dict[str, Any], rows: list[dict[str, str]]) -> None:
    position = source["csv_row_ordinal"] - 1
    if position >= len(rows) or _digest(rows[position]) != source["row_sha256"] or rows[position] != source["record"]:
        raise ValueError("acquisition frontier source differs from retained canonical CSV")


def select_required_replay_rows(
    run_dir: Path, manifest_value: dict[str, Any], *,
    snapshots: list[dict[str, str]], references: list[dict[str, str]],
    counts: list[dict[str, str]], estimates: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], set[str], dict[str, Any]]:
    """Verify the live-recorded frontier; never choose one during sealing."""
    artifact = _read_frontier(run_dir, manifest_value)
    if not _verify_live_marker(run_dir, artifact):
        raise ValueError("immutable acquisition frontier lacks its live raw establishment marker")
    state = json.loads((run_dir / FRONTIER_STATE_PATH).read_text())
    _validate_live_state(state, manifest_value)
    if state["errors"] or state.get("frontier_sha256") != artifact["frontier_sha256"]:
        raise ValueError("live acquisition observer retained a discrepancy or mismatched frontier")
    rows_by_type = {"REF": references, "SNP": snapshots, "CNT": counts}
    for name, tag in _SOURCE_TYPES.items():
        _bind_source(artifact[name], rows_by_type[tag])
    opening = artifact["opening_snapshot"]["csv_row_ordinal"] - 1
    reference = artifact["opening_reference"]["csv_row_ordinal"] - 1
    first_count = artifact["first_count"]["csv_row_ordinal"] - 1
    # There must not have been an earlier complete retained pair that the
    # recorder passed over. Prefix classification cannot select healthier data.
    snapshot_keys: dict[tuple[str, str], list[int]] = {}
    reference_keys: dict[str, list[int]] = {}
    for position, row in enumerate(snapshots[:opening + 2]):
        snapshot_keys.setdefault((row["snapshot_sequence"], row["reference_timestamp_ticks"]), []).append(position)
    for position, row in enumerate(references[:artifact["closing_reference"]["csv_row_ordinal"]]):
        reference_keys.setdefault(row["timestamp_ticks"], []).append(position)
    for count in counts[:first_count]:
        positions = snapshot_keys.get((count["count_seq"], count["gate_close_ticks"]), [])
        if len(positions) != 1 or positions[0] == 0:
            continue
        pair = snapshots[positions[0] - 1:positions[0] + 1]
        refs = [reference_keys.get(row["reference_timestamp_ticks"], []) for row in pair]
        if any(len(items) != 1 for items in refs) or refs[1][0] != refs[0][0] + 1:
            continue
        exact, _, _ = _raw_count_replay(pair, [references[items[0]] for items in refs], [count])
        if exact:
            raise ValueError("recorded frontier skipped an earlier complete retained pair")
    required_snapshots = snapshots[opening:]
    # Accepted-span replay, rather than raw elapsed position, now decides
    # whether an EST has a complete retained 600-span source.
    return required_snapshots, references[reference:], counts[first_count:], set(), {
        "exact": True,
        "frontier_sha256": artifact["frontier_sha256"],
        "policy": FRONTIER_POLICY,
        "prefix_disposition": "retained_unqualified",
        "unqualified_prefix_count_count": first_count,
        "unqualified_prefix_snapshot_count": opening,
        "unqualified_prefix_reference_count": reference,
        "unqualified_selected_estimate_ids": [],
        "raw_and_full_csv_preserved": True,
    }


def _verify_live_marker(run_dir: Path, artifact: dict[str, Any]) -> bool:
    """Bind live establishment to raw record order, independent of file mtimes."""
    import csv
    from .contracts import CONTRACT_FIELDS
    prefix = b"# OTIS_HOST "
    source_by_line = {artifact[name]["capture_line_ordinal"]: artifact[name] for name in _SOURCE_TYPES}
    if len(source_by_line) != len(_SOURCE_TYPES):
        raise ValueError("frontier source capture lines are not distinct")
    fields_by_tag = {"REF": CONTRACT_FIELDS["raw_events_v1"], "SNP": CONTRACT_FIELDS["pps_snapshots_v2"], "CNT": CONTRACT_FIELDS["count_observations_v1"]}
    device_line = 0
    matched_sources: set[int] = set()
    markers = 0
    with (run_dir / "raw/serial.log").open("rb") as stream:
        for raw_line in stream:
            if raw_line.startswith(prefix):
                marker = json.loads(raw_line[len(prefix):])
                if not isinstance(marker, dict):
                    raise ValueError("raw host marker is not an object")
                if marker.get("event") == "acquisition_frontier_established":
                    markers += 1
                    if markers != 1 or marker.get("frontier_sha256") != artifact["frontier_sha256"] or marker.get("capture_line_ordinal") != artifact["first_count"]["capture_line_ordinal"] or device_line < artifact["first_count"]["capture_line_ordinal"]:
                        raise ValueError("raw acquisition frontier marker identity or order differs")
                command = str(marker.get("command", "")).split()
                if marker.get("event") in {"host_command_accepted", "host_command_sent"} and command[:2] in (["ACTIVE", "SETUP"], ["ACTIVE", "ARM"]) and markers != 1:
                    raise ValueError("new SETUP/ARM authority precedes the live acquisition frontier marker")
                continue
            device_line += 1
            if device_line in source_by_line:
                source = source_by_line[device_line]
                values = next(csv.reader([raw_line.decode("utf-8").strip()]))
                fields = fields_by_tag[source["record_type"]]
                if len(values) != len(fields) or _digest(dict(zip(fields, values))) != source["row_sha256"]:
                    raise ValueError("frontier source capture line differs from retained raw bytes")
                matched_sources.add(device_line)
    if matched_sources != set(source_by_line):
        raise ValueError("frontier source capture lines are absent from retained raw bytes")
    return markers == 1


def _live_source_pointer(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "csv_row_ordinal": source["csv_row_ordinal"],
        "capture_line_ordinal": source["capture_line_ordinal"],
        "csv_byte_offset": source["csv_byte_offset"],
        "row_sha256": source["row_sha256"],
    }


def _bind_source_at_offset(
    run_dir: Path, manifest: dict[str, Any], tag: str, source: dict[str, Any]
) -> dict[str, str]:
    import csv
    offset = source.get("csv_byte_offset")
    if type(offset) is not int or offset < 0:
        raise ValueError("live source proof lacks an exact canonical CSV byte offset")
    contract = {"REF": "raw_events_v1", "SNP": "pps_snapshots_v2", "CNT": "count_observations_v1", "APS": "accepted_pps_spans_v1", "EST": "estimates_v3"}[tag]
    files = [entry for entry in manifest.get("files", []) if entry.get("contract") == contract
             and (tag != "REF" or entry.get("record_type") == "REF")]
    if len(files) != 1:
        raise ValueError(f"expected one canonical {tag} artifact for live source binding")
    with (run_dir / files[0]["path"]).open("rb") as stream:
        # This is a record-sized read at a recorded position, never a scan of
        # the growing acquisition. The wire parser already bounds line size.
        header = stream.readline(65537)
        if offset < len(header):
            raise ValueError("live source byte offset points inside CSV header")
        stream.seek(offset)
        raw = stream.readline(65537)
    if not header.endswith(b"\n") or not raw.endswith(b"\n") or len(header) > 65536 or len(raw) > 65536:
        raise ValueError("live source header or record is incomplete or exceeds capture bound")
    fields = next(csv.reader([header.decode("utf-8").strip()]))
    values = next(csv.reader([raw.decode("utf-8").strip()]))
    row = dict(zip(fields, values))
    if len(fields) != len(values) or _digest(row) != source["row_sha256"]:
        raise ValueError("live source differs from its retained canonical CSV byte position")
    return row


def _bind_accepted_span_window(
    run_dir: Path, manifest: dict[str, Any], proof: dict[str, Any]
) -> list[dict[str, str]]:
    sources = proof.get("accepted_span_sources")
    if not isinstance(sources, list) or len(sources) != 600:
        raise ValueError("live selected EST lacks its 600-span proof")
    previous_ordinal = 0
    rows: list[dict[str, str]] = []
    for source in sources:
        if (
            not isinstance(source, dict)
            or set(source) != {
                "csv_row_ordinal", "capture_line_ordinal", "csv_byte_offset",
                "row_sha256",
            }
        ):
            raise ValueError("live accepted-span proof entry is malformed")
        rows.append(_bind_source_at_offset(run_dir, manifest, "APS", source))
        ordinal = source["csv_row_ordinal"]
        if type(ordinal) is not int or ordinal != previous_ordinal + 1:
            if previous_ordinal:
                raise ValueError("live accepted-span CSV rows are not contiguous")
        previous_ordinal = ordinal
    return rows


def _bind_raw_source_window(
    run_dir: Path, manifest: dict[str, Any], proof: dict[str, Any]
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    result: list[list[dict[str, str]]] = []
    for field, tag, maximum in (
        ("raw_snapshot_sources", "SNP", 5402),
        ("raw_reference_sources", "REF", 5402),
        ("raw_count_sources", "CNT", 5401),
    ):
        sources = proof.get(field)
        if not isinstance(sources, list) or not sources or len(sources) > maximum:
            raise ValueError(f"live selected EST {field} is malformed or unbounded")
        rows: list[dict[str, str]] = []
        previous_ordinal = 0
        for source in sources:
            if not isinstance(source, dict) or set(source) != {
                "csv_row_ordinal", "capture_line_ordinal", "csv_byte_offset",
                "row_sha256",
            }:
                raise ValueError(f"live selected EST {field} entry is malformed")
            ordinal = source.get("csv_row_ordinal")
            if type(ordinal) is not int or ordinal < 1 or (
                previous_ordinal and ordinal != previous_ordinal + 1
            ):
                raise ValueError(f"live selected EST {field} rows are not contiguous")
            previous_ordinal = ordinal
            rows.append(_bind_source_at_offset(run_dir, manifest, tag, source))
        result.append(rows)
    return result[0], result[1], result[2]


def _live_marker_at_offset(run_dir: Path, artifact: dict[str, Any], offset: int | None) -> bool:
    if offset is None:
        return False  # Observer state may precede the recorder's marker callback.
    if type(offset) is not int or offset < 0:
        raise ValueError("frontier marker search offset is malformed")
    with (run_dir / "raw/serial.log").open("rb") as stream:
        stream.seek(offset)
        # RawEvidenceWriter defers a marker behind at most one partial line.
        # Current capture bounds that line at 65536 bytes with 4096-byte reads;
        # the additional 4096 bytes cover the marker itself and queued markers.
        candidate = stream.read(65536 + 4096 + 4096)
    markers = []
    for line in candidate.splitlines():
        if line.startswith(b"# OTIS_HOST "):
            try:
                marker = json.loads(line[len(b"# OTIS_HOST "):])
            except ValueError:
                continue  # A currently incomplete trailing marker stays pending.
            if not isinstance(marker, dict):
                raise ValueError("live raw host marker is not an object")
            if marker.get("event") == "acquisition_frontier_established":
                markers.append(marker)
    if not markers:
        return False
    if len(markers) != 1 or markers[0].get("frontier_sha256") != artifact["frontier_sha256"] or markers[0].get("capture_line_ordinal") != artifact["first_count"]["capture_line_ordinal"]:
        raise ValueError("live acquisition frontier raw marker identity differs")
    return True


def _validate_live_state(state: Any, manifest_value: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    if not isinstance(state, dict) or state.get("schema_version") != 1 or state.get("source_manifest_sha256") != _digest(manifest_value):
        raise ValueError("acquisition frontier live state schema or manifest binding differs")
    if not isinstance(state.get("errors"), list) or any(not isinstance(item, str) for item in state["errors"]):
        raise ValueError("acquisition frontier live errors field is malformed")
    if type(state.get("anchor_ready")) is not bool or type(state.get("last_capture_line_ordinal")) is not int:
        raise ValueError("acquisition frontier live readiness fields are malformed")
    ids, proofs = state.get("qualified_estimate_ids"), state.get("qualified_estimates")
    if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids) or len(ids) != len(set(ids)) or not isinstance(proofs, list):
        raise ValueError("acquisition frontier live source identities are malformed")
    if any(not isinstance(item, dict) or item.get("estimate_id") not in ids or not isinstance(item.get("record"), dict)
           or item.get("row_sha256") != _digest(item["record"]) for item in proofs) or [item["estimate_id"] for item in proofs] != ids:
        raise ValueError("acquisition frontier live source proof is malformed")
    for field in ("pending_estimate_ids",):
        values = state.get(field)
        if not isinstance(values, list) or len(values) > 2 or any(not isinstance(item, str) for item in values) or len(values) != len(set(values)):
            raise ValueError("acquisition pending source identities are malformed")
    if type(state.get("unqualified_estimate_count")) is not int or state["unqualified_estimate_count"] < 0 or state["last_capture_line_ordinal"] < 0:
        raise ValueError("acquisition live counters are malformed")
    if type(state.get("current_session_pair_ready")) is not bool or (state.get("current_capture_session") is not None and type(state["current_capture_session"]) is not int):
        raise ValueError("acquisition live session fields are malformed")
    for field in ("frontier_sha256", "frontier_marker_search_offset", "current_capture_session"):
        if field not in state:
            raise ValueError("acquisition live state omits a mandatory binding")
    if len(ids) > 2 or any(type(item.get("capture_session")) is not int or type(item.get("csv_row_ordinal")) is not int or item["csv_row_ordinal"] < 1
                          or type(item.get("capture_line_ordinal")) is not int or item["capture_line_ordinal"] < 1
                          or item["record"].get("estimate_id") != item["estimate_id"]
                          or type(item.get("source_acceptance_epoch")) is not int
                          or item["source_acceptance_epoch"] <= 0
                          or any(type(item.get(field)) is not int or not 0 <= item[field] < _U32_MODULUS for field in (
                              "source_opening_accepted_boundary_ordinal",
                              "source_closing_accepted_boundary_ordinal",
                          ))
                          or not isinstance(item.get("accepted_span_sources"), list)
                          or len(item["accepted_span_sources"]) != 600
                          for item in proofs):
        raise ValueError("acquisition selected source proof identity is malformed")
    return ids, proofs
