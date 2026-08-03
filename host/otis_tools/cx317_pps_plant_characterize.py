"""Characterize the predetermined CX317 PPS-gated Stage 5 plant campaign.

The analyser is deliberately offline.  It refuses an active capture, derives
every control epoch from the actual acknowledged DAC records, and uses the
selected cumulative-snapshot estimator without assigning any command
authority.  Reported spreads and ranges are finite-run characterization, not
calibrated uncertainty.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import argparse
import csv
from datetime import datetime
import json
import math
import statistics
import tempfile
from typing import Any, Iterable

from .pps_cumulative_span_estimator import (
    DEFAULT_CONFIG,
    IntervalEvidence,
    SpanEstimate,
    estimate_spans,
    load_config,
    load_run_inputs,
)
from .cx317_open_loop_scheduler import load_plan
from .run_loader import load_manifest
from .timebase import RP2040_TIMER0_MICROS_WRAP_TICKS, unwrap_ticks


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN = REPO_ROOT / "profiles/plant_campaigns/cx317_pps_gated_open_loop_v1.json"
DEFAULT_SELECTED_PROFILE = (
    REPO_ROOT / "profiles/estimators/cx317_pps_gated_selected_v1.json"
)
OUTPUT_DIR = Path("derived/cx317_pps_plant_characterization_v1")
OUTPUT_NAME = "plant_characterization_v1.json"
REPORT_NAME = "PLANT_CHARACTERIZATION.md"
POLICY_NAME = "interval_policy_v1.json"
TOOL_VERSION = "cx317_pps_plant_characterize_v1"
TICKS_PER_SECOND = 16_000_000
TICKS_PER_MILLISECOND = 16_000


@dataclass(frozen=True)
class AcknowledgedDwell:
    index: int
    label: str
    code: int
    dac_sequence: int
    elapsed_ms: int
    accepted_raw_ticks: int
    accepted_unwrapped_ticks: int

    @property
    def epoch(self) -> str:
        return f"dwell_{self.index + 1:02d}_{self.label}_0x{self.code:04X}"


@dataclass(frozen=True)
class DwellSummary:
    index: int
    label: str
    epoch: str
    code: int
    acknowledged_ticks: int
    settled_interval_count: int
    selected_estimate_count: int
    selected_count_increment_hz: float | None
    selected_frequency_values_hz: tuple[float, ...]
    representative_frequency_hz: float | None
    representative_ticks: float | None
    selected_population_stddev_hz: float | None
    selected_range_hz: float | None
    diagnostic_estimate_count: int
    diagnostic_frequency_min_hz: float | None
    diagnostic_frequency_max_hz: float | None


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(value)
        temporary = Path(handle.name)
    temporary.replace(path)


def _markdown_value(value: Any) -> str:
    if value is None:
        text = "unavailable"
    elif isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, sort_keys=True, separators=(",", ":"))
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _markdown_table(
    headers: tuple[str, ...],
    rows: Iterable[tuple[Any, ...]],
    *,
    alignments: tuple[str, ...] | None = None,
) -> list[str]:
    rendered_rows = [
        tuple(_markdown_value(value) for value in row) for row in rows
    ]
    if any(len(row) != len(headers) for row in rendered_rows):
        raise ValueError("Markdown table row width differs from header width")
    alignment = alignments or tuple("left" for _ in headers)
    if len(alignment) != len(headers) or set(alignment) - {"left", "right", "center"}:
        raise ValueError("Markdown table alignment is malformed")
    widths = [
        max(
            3,
            len(header),
            *(len(row[index]) for row in rendered_rows),
        )
        for index, header in enumerate(headers)
    ]

    def formatted(row: tuple[str, ...]) -> str:
        cells = []
        for index, value in enumerate(row):
            if alignment[index] == "right":
                cells.append(value.rjust(widths[index]))
            elif alignment[index] == "center":
                cells.append(value.center(widths[index]))
            else:
                cells.append(value.ljust(widths[index]))
        return "| " + " | ".join(cells) + " |"

    separators = []
    for width, item in zip(widths, alignment, strict=True):
        if item == "right":
            separators.append("-" * (width - 1) + ":")
        elif item == "center":
            separators.append(":" + "-" * (width - 2) + ":")
        else:
            separators.append(":" + "-" * (width - 1))
    return [formatted(tuple(headers)), formatted(tuple(separators)), *map(formatted, rendered_rows)]


PROVENANCE_FIELDS = (
    "parameter_and_units",
    "acceptance_rejection_threshold",
    "disposition",
    "source_document_and_location",
    "source_conditions_and_applicability",
    "calculation_or_conversion",
    "measurement_uncertainty_and_safety_margin",
    "measured_result",
    "status",
    "consequences_of_failure",
)


def load_markdown_provenance_table(path: Path) -> list[dict[str, str]]:
    """Load the completed physical-gate provenance table without weakening it."""

    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        heading_index = lines.index("## Tolerance provenance")
    except ValueError as exc:
        raise ValueError(f"{path}: missing tolerance-provenance heading") from exc
    table_lines: list[str] = []
    for line in lines[heading_index + 1 :]:
        if line.startswith("|"):
            table_lines.append(line)
        elif table_lines and line.strip():
            break
    if len(table_lines) < 3:
        raise ValueError(f"{path}: tolerance-provenance table is empty")
    header_cells = [cell.strip() for cell in table_lines[0].strip("|").split("|")]
    if len(header_cells) != len(PROVENANCE_FIELDS):
        raise ValueError(f"{path}: tolerance-provenance table width is not ten columns")
    rows: list[dict[str, str]] = []
    for line in table_lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != len(PROVENANCE_FIELDS):
            raise ValueError(f"{path}: malformed tolerance-provenance row")
        rows.append(dict(zip(PROVENANCE_FIELDS, cells, strict=True)))
    if not rows:
        raise ValueError(f"{path}: tolerance-provenance table has no data rows")
    return rows


def render_markdown_report(report: dict[str, Any]) -> str:
    gain = report["plant_gain"]
    crossing = report["crossing"]
    repeatability = report["centre_repeatability"]
    settling = report["settling"]
    health = report["capture_health"]
    temperature = report["temperature_context"]
    lines = [
        "# CX317 PPS-Gated Stage 5 Plant Characterization",
        "",
        f"- run_id: `{report['run_id']}`",
        f"- exit_gate: `{report['exit_gate']}`",
        "- authority: observe-only; `control_ready=false`, `actuation_enabled=false`, `actuation_authorized=false`, `actionable=false`",
        "",
        "## Execution and capture integrity",
        "",
        f"- executor status: `{report['executor']['status']}`",
        f"- exact acknowledgements: {report['executor']['acknowledgement_count']}",
        f"- last verified code: `0x{int(report['executor']['last_verified_code']):04X}`",
        f"- source-valid adjacent intervals: {health['source_valid_adjacent_interval_count']}",
        f"- source-invalid adjacent intervals: {health['source_invalid_adjacent_interval_count']}",
        f"- policy-excluded intervals: {health['policy_excluded_interval_count']}",
        f"- global reason codes: `{_markdown_value(health['global_reason_codes'])}`",
        "",
        "## Plant result",
        "",
        f"- drift-cancelled gain, Hz/code: minimum `{gain['minimum_hz_per_code']:.12g}`, median `{gain['median_hz_per_code']:.12g}`, maximum `{gain['maximum_hz_per_code']:.12g}` ({gain['sample_count']} samples)",
        f"- crossing code: `{crossing['nominal_code_float']:.6f}`; rounded `0x{int(crossing['nominal_code_rounded']):04X}`",
        f"- between-visit crossing range, codes: `{crossing['between_visit_code_min']:.6f}..{crossing['between_visit_code_max']:.6f}`",
        f"- centre raw visit span, Hz: `{repeatability['raw_visit_span_hz']:.12g}`",
        f"- centre drift-fit residual span, Hz: `{repeatability['drift_fit_residual_span_hz']:.12g}`",
        f"- declared settling exclusion, s: `{settling['declared_exclusion_s']}`",
        f"- fresh selected support after exclusion, s: `{settling['fresh_selected_support_s']}`",
        f"- conservative full-history reset, s: `{settling['conservative_history_reset_s']}`",
        f"- measured t95: `unavailable`",
        f"- SHT41 nearby-air context, C: `{_markdown_value(temperature['temperature_min_c'])}..{_markdown_value(temperature['temperature_max_c'])}`",
        "",
        "The crossing, gain, repeatability, hysteresis and settling results are finite-run characterization. They are not calibrated uncertainty, a CX317 specification or actuation authority.",
        "",
        "## Dwell results",
        "",
    ]
    lines.extend(
        _markdown_table(
            (
                "Visit",
                "Code",
                "Settled intervals",
                "600 s outputs",
                "Representative frequency, Hz",
                "Within-visit range, Hz",
            ),
            (
                (
                    visit["label"],
                    f"0x{int(visit['code']):04X}",
                    visit["settled_interval_count"],
                    visit["selected_estimate_count"],
                    visit["representative_frequency_hz"],
                    visit["selected_range_hz"],
                )
                for visit in report["dwell_visits"]
            ),
            alignments=("left", "right", "right", "right", "right", "right"),
        )
    )
    lines.extend(
        [
            "",
            "## Bidirectional hysteresis",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            (
                "Interior",
                "Code",
                "Return minus outbound, Hz",
                "Absolute equivalent codes",
                "Disposition",
            ),
            (
                (
                    item["location"],
                    f"0x{int(item['code']):04X}",
                    item["return_minus_outbound_hz"],
                    item["absolute_equivalent_codes"],
                    "characterization-only",
                )
                for item in report["bidirectional_hysteresis"]
            ),
            alignments=("left", "right", "right", "right", "left"),
        )
    )
    lines.extend(
        [
            "",
            "## Pre-command physical and electrical tolerance provenance",
            "",
            "The completed pre-command gate is reproduced without retroactive alteration. Rows that describe future runtime checks retain that historical pre-command disposition; the measured execution results are in the plant-campaign table below.",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            (
                "Parameter and units",
                "Acceptance/rejection threshold",
                "Disposition",
                "Source document and location",
                "Source conditions and applicability",
                "Calculation or conversion",
                "Measurement uncertainty and safety margin",
                "Measured result",
                "Status",
                "Consequences of failure",
            ),
            (
                tuple(item[key] for key in PROVENANCE_FIELDS)
                for item in report["physical_electrical_tolerance_provenance"]
            ),
            alignments=tuple("left" for _ in PROVENANCE_FIELDS),
        )
    )
    lines.extend(["", "## Plant-campaign tolerance provenance", ""])
    lines.extend(
        _markdown_table(
            (
                "Parameter and units",
                "Acceptance/rejection threshold",
                "Disposition",
                "Source document and location",
                "Source conditions and applicability",
                "Calculation or conversion",
                "Measurement uncertainty and safety margin",
                "Measured result",
                "Status",
                "Consequences of failure",
            ),
            (
                tuple(item[key] for key in PROVENANCE_FIELDS)
                for item in report["tolerance_provenance"]
            ),
            alignments=tuple("left" for _ in PROVENANCE_FIELDS),
        )
    )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def _contract_path(manifest: Any, contract: str) -> Path:
    matches = [
        manifest.root / str(item["path"])
        for item in manifest.files
        if item.get("contract") == contract
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {contract} path, got {len(matches)}")
    return matches[0]


def _parse_code(value: Any) -> int:
    if isinstance(value, int):
        return value
    return int(str(value), 0)


def _plan_steps(plan: dict[str, Any]) -> list[tuple[str, int]]:
    sequence = plan.get("sequence")
    if not isinstance(sequence, list) or not sequence:
        raise ValueError("plant campaign has no sequence")
    output: list[tuple[str, int]] = []
    for item in sequence:
        if not isinstance(item, dict) or set(item) != {"label", "code"}:
            raise ValueError("plant campaign sequence item is malformed")
        output.append((str(item["label"]), _parse_code(item["code"])))
    return output


def align_acknowledged_dwells(
    plan: dict[str, Any],
    executor_result: dict[str, Any],
    dac_rows: list[dict[str, str]],
    health_rows: list[dict[str, str]],
) -> tuple[AcknowledgedDwell, ...]:
    """Bind plan, executor, DAC acknowledgement and accepted-code evidence.

    ``elapsed_ms`` and health timestamps are emitted immediately around the
    same successful write.  The elapsed millisecond value selects the unique
    32-bit-microsecond wrap epoch nearest to the accepted-code timestamp.  The
    observed residual is retained in the report; it is not converted into a
    timing-accuracy claim.
    """

    steps = _plan_steps(plan)
    if executor_result.get("status") != "complete_fail_static":
        raise ValueError("executor result is not complete_fail_static")
    acknowledgements = executor_result.get("acknowledgements")
    if not isinstance(acknowledgements, list) or len(acknowledgements) != len(steps):
        raise ValueError("executor acknowledgement count differs from plan")
    manual_rows = [row for row in dac_rows if row.get("event") == "manual_apply"]
    if len(manual_rows) != len(steps):
        raise ValueError("actual manual DAC acknowledgement count differs from plan")
    accepted_rows = [
        row
        for row in health_rows
        if row.get("component") == "dac" and row.get("status_key") == "accepted_code"
    ]
    if len(accepted_rows) != len(steps):
        raise ValueError("accepted-code timestamp count differs from plan")

    output: list[AcknowledgedDwell] = []
    previous_tick: int | None = None
    for index, ((label, code), result, dac, accepted) in enumerate(
        zip(steps, acknowledgements, manual_rows, accepted_rows, strict=True)
    ):
        evidence_codes = (
            _parse_code(result["requested_code"]),
            _parse_code(result["applied_code"]),
            _parse_code(dac["dac_code_requested"]),
            _parse_code(dac["dac_code_applied"]),
            _parse_code(accepted["status_value"]),
        )
        if any(item != code for item in evidence_codes):
            raise ValueError(f"dwell {index}: acknowledged code differs from plan")
        if bool(result.get("clamped")) or _parse_code(dac["dac_code_clamped"]) != 0:
            raise ValueError(f"dwell {index}: acknowledgement reports clamping")
        if _parse_code(result.get("flags", 0)) != 0 or _parse_code(dac["flags"]) != 0:
            raise ValueError(f"dwell {index}: acknowledgement carries non-zero flags")
        if result.get("event") != "manual_apply":
            raise ValueError(f"dwell {index}: executor acknowledgement event differs")
        if _parse_code(result["seq"]) != _parse_code(dac["seq"]):
            raise ValueError(f"dwell {index}: acknowledgement sequence differs")
        elapsed_ms = _parse_code(dac["elapsed_ms"])
        raw_ticks = _parse_code(accepted["timestamp_ticks"])
        approximate_ticks = elapsed_ms * TICKS_PER_MILLISECOND
        wrap_index = round(
            (approximate_ticks - raw_ticks) / RP2040_TIMER0_MICROS_WRAP_TICKS
        )
        unwrapped_ticks = raw_ticks + wrap_index * RP2040_TIMER0_MICROS_WRAP_TICKS
        if previous_tick is not None and unwrapped_ticks <= previous_tick:
            raise ValueError("accepted-code timestamps are not strictly increasing")
        previous_tick = unwrapped_ticks
        output.append(
            AcknowledgedDwell(
                index=index,
                label=label,
                code=code,
                dac_sequence=_parse_code(dac["seq"]),
                elapsed_ms=elapsed_ms,
                accepted_raw_ticks=raw_ticks,
                accepted_unwrapped_ticks=unwrapped_ticks,
            )
        )
    if output[-1].code != _parse_code(plan["final_safe_code"]):
        raise ValueError("last acknowledged code is not the final safe code")
    if _parse_code(executor_result.get("last_verified_code")) != output[-1].code:
        raise ValueError("executor last verified code differs from the final acknowledgement")
    return tuple(output)


def _provisional_policy(intervals: Iterable[IntervalEvidence]) -> dict[str, Any]:
    sequences = [item.closing_snapshot_sequence for item in intervals]
    if not sequences:
        raise ValueError("no PPS intervals are available")
    return {
        "schema_version": 1,
        "ranges": [
            {
                "first_closing_snapshot_sequence": min(sequences),
                "last_closing_snapshot_sequence": max(sequences),
                "control_epoch": "provisional_unmapped",
                "settling_excluded": True,
            }
        ],
    }


def build_interval_policy(
    intervals: tuple[IntervalEvidence, ...],
    dwells: tuple[AcknowledgedDwell, ...],
    *,
    settling_exclusion_s: int,
) -> tuple[dict[str, Any], dict[int, tuple[int, int]]]:
    """Assign each complete PPS interval to the latest acknowledged dwell."""

    if settling_exclusion_s < 0:
        raise ValueError("settling exclusion must be non-negative")
    if not intervals:
        raise ValueError("no PPS intervals are available")
    raw_ticks = [intervals[0].opening_reference_timestamp_ticks]
    raw_ticks.extend(item.closing_reference_timestamp_ticks for item in intervals)
    unwrapped, _ = unwrap_ticks(raw_ticks)
    interval_ticks = {
        item.closing_snapshot_sequence: (unwrapped[index], unwrapped[index + 1])
        for index, item in enumerate(intervals)
    }
    assignments: list[tuple[int, str, bool]] = []
    active_index = -1
    exclusion_ticks = settling_exclusion_s * TICKS_PER_SECOND
    for interval in intervals:
        opening, closing = interval_ticks[interval.closing_snapshot_sequence]
        while (
            active_index + 1 < len(dwells)
            and dwells[active_index + 1].accepted_unwrapped_ticks <= closing
        ):
            active_index += 1
        if active_index < 0:
            epoch = "pre_campaign_uncommanded"
            excluded = True
        else:
            dwell = dwells[active_index]
            epoch = dwell.epoch
            excluded = (
                opening < dwell.accepted_unwrapped_ticks
                or opening < dwell.accepted_unwrapped_ticks + exclusion_ticks
            )
        assignments.append((interval.closing_snapshot_sequence, epoch, excluded))

    ranges: list[dict[str, Any]] = []
    for sequence, epoch, excluded in assignments:
        if (
            ranges
            and ranges[-1]["last_closing_snapshot_sequence"] + 1 == sequence
            and ranges[-1]["control_epoch"] == epoch
            and ranges[-1]["settling_excluded"] == excluded
        ):
            ranges[-1]["last_closing_snapshot_sequence"] = sequence
        else:
            ranges.append(
                {
                    "first_closing_snapshot_sequence": sequence,
                    "last_closing_snapshot_sequence": sequence,
                    "control_epoch": epoch,
                    "settling_excluded": excluded,
                }
            )
    return {"schema_version": 1, "ranges": ranges}, interval_ticks


def _estimate_midpoint_ticks(
    estimate: SpanEstimate, interval_ticks: dict[int, tuple[int, int]]
) -> float:
    opening = interval_ticks[estimate.first_snapshot_sequence + 1][0]
    closing = interval_ticks[estimate.last_snapshot_sequence][1]
    return (opening + closing) / 2.0


def summarize_dwells(
    dwells: tuple[AcknowledgedDwell, ...],
    intervals: tuple[IntervalEvidence, ...],
    estimates: tuple[SpanEstimate, ...],
    interval_ticks: dict[int, tuple[int, int]],
    *,
    selected_span_s: int,
    diagnostic_span_s: int,
) -> tuple[DwellSummary, ...]:
    by_epoch: dict[str, list[SpanEstimate]] = defaultdict(list)
    for estimate in estimates:
        by_epoch[estimate.control_epoch].append(estimate)
    settled_counts: dict[str, int] = defaultdict(int)
    for interval in intervals:
        if interval.effective_valid:
            settled_counts[interval.control_epoch] += 1

    output: list[DwellSummary] = []
    for dwell in dwells:
        selected = [
            item
            for item in by_epoch[dwell.epoch]
            if item.mode == "non_overlapping" and item.span_seconds == selected_span_s
        ]
        diagnostic = [
            item
            for item in by_epoch[dwell.epoch]
            if item.mode == "overlapping" and item.span_seconds == diagnostic_span_s
        ]
        values = tuple(item.authoritative_frequency_hz for item in selected)
        diagnostic_values = [item.authoritative_frequency_hz for item in diagnostic]
        output.append(
            DwellSummary(
                index=dwell.index,
                label=dwell.label,
                epoch=dwell.epoch,
                code=dwell.code,
                acknowledged_ticks=dwell.accepted_unwrapped_ticks,
                settled_interval_count=settled_counts[dwell.epoch],
                selected_estimate_count=len(selected),
                selected_count_increment_hz=(selected[0].count_increment_hz if selected else None),
                selected_frequency_values_hz=values,
                representative_frequency_hz=(statistics.median(values) if values else None),
                representative_ticks=(
                    statistics.fmean(
                        _estimate_midpoint_ticks(item, interval_ticks) for item in selected
                    )
                    if selected
                    else None
                ),
                selected_population_stddev_hz=(
                    statistics.pstdev(values) if len(values) > 1 else (0.0 if values else None)
                ),
                selected_range_hz=(max(values) - min(values) if values else None),
                diagnostic_estimate_count=len(diagnostic),
                diagnostic_frequency_min_hz=(min(diagnostic_values) if diagnostic_values else None),
                diagnostic_frequency_max_hz=(max(diagnostic_values) if diagnostic_values else None),
            )
        )
    return tuple(output)


def _require_complete_visits(visits: tuple[DwellSummary, ...]) -> None:
    for visit in visits:
        if visit.representative_frequency_hz is None or visit.representative_ticks is None:
            raise ValueError(f"{visit.label}: selected estimator output is unavailable")


def _interpolate_visit(
    target: DwellSummary, left: DwellSummary, right: DwellSummary
) -> float:
    assert target.representative_ticks is not None
    assert left.representative_ticks is not None
    assert right.representative_ticks is not None
    assert left.representative_frequency_hz is not None
    assert right.representative_frequency_hz is not None
    if not left.representative_ticks < target.representative_ticks < right.representative_ticks:
        raise ValueError("drift-cancelling bracket does not contain target visit")
    fraction = (target.representative_ticks - left.representative_ticks) / (
        right.representative_ticks - left.representative_ticks
    )
    return left.representative_frequency_hz + fraction * (
        right.representative_frequency_hz - left.representative_frequency_hz
    )


def drift_cancelled_gain_samples(
    visits: tuple[DwellSummary, ...]
) -> list[dict[str, Any]]:
    """Return six same-code-bracketed/local centre-bracket gain estimates."""

    _require_complete_visits(visits)
    by_label = {item.label: item for item in visits}
    definitions = (
        ("lower_interior_outbound", "lower_interior_1", "centre_1", "centre_2"),
        ("lower_endpoint", "lower_endpoint", "lower_interior_1", "lower_interior_2"),
        ("lower_interior_return", "lower_interior_2", "centre_1", "centre_2"),
        ("upper_interior_outbound", "upper_interior_1", "centre_2", "final_safe_centre"),
        ("upper_endpoint", "upper_endpoint", "upper_interior_1", "upper_interior_2"),
        ("upper_interior_return", "upper_interior_2", "centre_2", "final_safe_centre"),
    )
    output: list[dict[str, Any]] = []
    for name, target_name, left_name, right_name in definitions:
        target = by_label[target_name]
        left = by_label[left_name]
        right = by_label[right_name]
        interpolated = _interpolate_visit(target, left, right)
        target_frequency = float(target.representative_frequency_hz)
        if target.code < left.code:
            numerator = interpolated - target_frequency
            denominator = left.code - target.code
        elif target.code > left.code:
            numerator = target_frequency - interpolated
            denominator = target.code - left.code
        else:
            raise ValueError("gain bracket has no code difference")
        output.append(
            {
                "sample": name,
                "target_label": target_name,
                "bracket_labels": [left_name, right_name],
                "code_difference": denominator,
                "drift_interpolated_bracket_frequency_hz": interpolated,
                "target_frequency_hz": target_frequency,
                "hz_per_code": numerator / denominator,
                "authority": "finite-run drift-cancelled characterization; not calibrated uncertainty",
            }
        )
    return output


def _linear_fit(x: list[float], y: list[float]) -> tuple[float, float]:
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("linear fit requires at least two paired values")
    mean_x = statistics.fmean(x)
    mean_y = statistics.fmean(y)
    denominator = sum((value - mean_x) ** 2 for value in x)
    if denominator == 0:
        raise ValueError("linear fit x values have no span")
    slope = sum(
        (a - mean_x) * (b - mean_y) for a, b in zip(x, y, strict=True)
    ) / denominator
    return mean_y - slope * mean_x, slope


def crossing_and_repeatability(
    visits: tuple[DwellSummary, ...], gain_samples: list[dict[str, Any]], target_hz: float
) -> tuple[dict[str, Any], dict[str, Any], float]:
    _require_complete_visits(visits)
    by_label = {item.label: item for item in visits}
    centres = [by_label[name] for name in ("centre_1", "centre_2", "final_safe_centre")]
    centre_times = [float(item.representative_ticks) for item in centres]
    centre_values = [float(item.representative_frequency_hz) for item in centres]
    intercept, drift_hz_per_tick = _linear_fit(centre_times, centre_values)
    campaign_mid = statistics.median(centre_times)
    predicted_centre = intercept + drift_hz_per_tick * campaign_mid
    gain_values = [float(item["hz_per_code"]) for item in gain_samples]
    nominal_gain = statistics.median(gain_values)
    if nominal_gain == 0:
        raise ValueError("nominal drift-cancelled gain is zero")
    centre_code = centres[0].code
    crossing_float = centre_code + (target_hz - predicted_centre) / nominal_gain
    adjusted_centres = [
        frequency - drift_hz_per_tick * (ticks - campaign_mid)
        for frequency, ticks in zip(centre_values, centre_times, strict=True)
    ]
    crossing_visits = [
        centre_code + (target_hz - frequency) / nominal_gain
        for frequency in adjusted_centres
    ]

    adjusted_by_code: dict[int, list[float]] = defaultdict(list)
    for visit in visits:
        adjusted_by_code[visit.code].append(
            float(visit.representative_frequency_hz)
            - drift_hz_per_tick * (float(visit.representative_ticks) - campaign_mid)
        )
    code_points = sorted(
        (code, statistics.median(values)) for code, values in adjusted_by_code.items()
    )
    below = [item for item in code_points if item[1] <= target_hz]
    above = [item for item in code_points if item[1] >= target_hz]
    bracket = None
    if below and above:
        bracket = {
            "below_code": max(below, key=lambda item: item[0])[0],
            "below_frequency_hz": max(below, key=lambda item: item[0])[1],
            "above_code": min(above, key=lambda item: item[0])[0],
            "above_frequency_hz": min(above, key=lambda item: item[0])[1],
        }
    residuals = [
        frequency - (intercept + drift_hz_per_tick * ticks)
        for frequency, ticks in zip(centre_values, centre_times, strict=True)
    ]
    crossing = {
        "target_frequency_hz": target_hz,
        "nominal_code_float": crossing_float,
        "nominal_code_rounded": int(math.floor(crossing_float + 0.5)),
        "between_visit_code_values": crossing_visits,
        "between_visit_code_min": min(crossing_visits),
        "between_visit_code_max": max(crossing_visits),
        "between_visit_code_span": max(crossing_visits) - min(crossing_visits),
        "observed_drift_adjusted_bracket": bracket,
        "method": "median of six drift-cancelled local gains plus three-visit centre linear drift fit at the campaign midpoint",
        "uncertainty_status": "unavailable",
        "uncertainty_scope": "between-visit finite-run range only; excludes calibrated electrical, reference, aperture and model uncertainty",
    }
    repeatability = {
        "centre_code": centre_code,
        "visit_count": len(centres),
        "raw_visit_frequencies_hz": centre_values,
        "raw_visit_min_hz": min(centre_values),
        "raw_visit_max_hz": max(centre_values),
        "raw_visit_span_hz": max(centre_values) - min(centre_values),
        "linear_drift_hz_per_hour": drift_hz_per_tick * TICKS_PER_SECOND * 3600.0,
        "drift_fit_residuals_hz": residuals,
        "drift_fit_residual_span_hz": max(residuals) - min(residuals),
        "authority": "finite-run repeatability/time-confounding characterization only",
    }
    return crossing, repeatability, nominal_gain


def bidirectional_hysteresis(
    visits: tuple[DwellSummary, ...], nominal_gain_hz_per_code: float
) -> list[dict[str, Any]]:
    _require_complete_visits(visits)
    by_label = {item.label: item for item in visits}
    output: list[dict[str, Any]] = []
    for side, first_name, second_name, left_name, right_name in (
        ("lower_interior", "lower_interior_1", "lower_interior_2", "centre_1", "centre_2"),
        ("upper_interior", "upper_interior_1", "upper_interior_2", "centre_2", "final_safe_centre"),
    ):
        first = by_label[first_name]
        second = by_label[second_name]
        left = by_label[left_name]
        right = by_label[right_name]
        first_residual = float(first.representative_frequency_hz) - _interpolate_visit(first, left, right)
        second_residual = float(second.representative_frequency_hz) - _interpolate_visit(second, left, right)
        delta = second_residual - first_residual
        output.append(
            {
                "code": first.code,
                "location": side,
                "outbound_label": first_name,
                "return_label": second_name,
                "outbound_drift_adjusted_residual_hz": first_residual,
                "return_drift_adjusted_residual_hz": second_residual,
                "return_minus_outbound_hz": delta,
                "absolute_equivalent_codes": (
                    abs(delta / nominal_gain_hz_per_code)
                    if nominal_gain_hz_per_code != 0
                    else None
                ),
                "authority": "observed bidirectional finite-run characterization; no rejection threshold or population bound",
            }
        )
    return output


def _temperature_context(
    path: Path, first_ack_ticks: int, last_ack_ticks: int, dwell_s: int
) -> dict[str, Any]:
    rows = [
        row
        for row in _read_rows(path)
        if row.get("source") == "sht4x" and row.get("temperature_c")
    ]
    raw = [_parse_code(row["timestamp_ticks"]) for row in rows]
    ticks, wraps = unwrap_ticks(raw)
    end_ticks = last_ack_ticks + dwell_s * TICKS_PER_SECOND
    selected = [
        float(row["temperature_c"])
        for row, tick in zip(rows, ticks, strict=True)
        if first_ack_ticks <= tick <= end_ticks
    ]
    return {
        "source": "SHT41 approximately 1 cm from CX317; near-air proxy only",
        "sample_count": len(selected),
        "temperature_min_c": min(selected) if selected else None,
        "temperature_max_c": max(selected) if selected else None,
        "timestamp_wrap_count": wraps,
        "sensor_uncertainty_status": "unavailable",
        "applicability": "observed environmental context, not a demonstrated CX317 internal-temperature sensitivity bound",
    }


def _provenance_row(
    parameter: str,
    threshold: str,
    disposition: str,
    source: str,
    applicability: str,
    calculation: str,
    uncertainty: str,
    measured: Any,
    status: str,
    consequences: str,
) -> dict[str, Any]:
    return {
        "parameter_and_units": parameter,
        "acceptance_rejection_threshold": threshold,
        "disposition": disposition,
        "source_document_and_location": source,
        "source_conditions_and_applicability": applicability,
        "calculation_or_conversion": calculation,
        "measurement_uncertainty_and_safety_margin": uncertainty,
        "measured_result": measured,
        "status": status,
        "consequences_of_failure": consequences,
    }


def characterize_run(
    run_dir: Path,
    *,
    plan_path: Path = DEFAULT_PLAN,
    selected_profile_path: Path = DEFAULT_SELECTED_PROFILE,
    estimator_config_path: Path = DEFAULT_CONFIG,
    executor_result_path: Path | None = None,
    physical_provenance_path: Path | None = None,
) -> Path:
    if (run_dir / "capture_in_progress.flag").exists():
        raise ValueError("capture is still in progress; offline plant analysis refused")
    manifest = load_manifest(run_dir)
    if manifest.data.get("ended_at_utc") in {None, ""}:
        raise ValueError("run manifest has no ended_at_utc")
    plan = _read_json(plan_path)
    plan_contract = load_plan(plan_path)
    selected_profile = _read_json(selected_profile_path)
    executor_path = executor_result_path or run_dir / "control/open_loop_executor_result.json"
    executor = _read_json(executor_path)
    physical_path = physical_provenance_path or (
        run_dir.parent / "stage5_preparation/PHYSICAL_SAFETY_GATE_WORKING.md"
    )
    physical_provenance = load_markdown_provenance_table(physical_path)
    if (
        manifest.data.get("plant_campaign", {}).get("config_sha256")
        != plan_contract.config_hash
    ):
        raise ValueError("run manifest campaign hash binding differs from plan")
    if manifest.data.get("selected_estimator", {}).get("profile_sha256") != _sha256_file(selected_profile_path):
        raise ValueError("run manifest selected-estimator profile hash differs")
    selected_span_s = int(selected_profile["authoritative_policy"]["span_s"])
    diagnostics = selected_profile["diagnostic_policy"]["spans_s"]
    if not isinstance(diagnostics, list) or len(diagnostics) != 1:
        raise ValueError("exactly one diagnostic span is required for Stage 5")
    diagnostic_span_s = int(diagnostics[0])
    config = load_config(estimator_config_path)
    if config.method_id != plan.get("estimator_method_id"):
        raise ValueError("estimator method differs from plant plan")

    dac_path = _contract_path(manifest, "dac_steps_v1")
    health_path = _contract_path(manifest, "health_v1")
    environment_path = _contract_path(manifest, "environment_v1")
    dwells = align_acknowledged_dwells(
        plan,
        executor,
        _read_rows(dac_path),
        _read_rows(health_path),
    )

    output_dir = run_dir / OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    provisional_path = output_dir / ".provisional_interval_policy.json"
    first_snapshot_rows = _read_rows(_contract_path(manifest, "pps_snapshots_v1"))
    sequences = [_parse_code(row["snapshot_sequence"]) for row in first_snapshot_rows]
    if len(sequences) < 2:
        raise ValueError("fewer than two PPS snapshots")
    _write_json_atomic(
        provisional_path,
        {
            "schema_version": 1,
            "ranges": [
                {
                    "first_closing_snapshot_sequence": min(sequences) + 1,
                    "last_closing_snapshot_sequence": max(sequences),
                    "control_epoch": "provisional_unmapped",
                    "settling_excluded": True,
                }
            ],
        },
    )
    try:
        provisional_inputs = load_run_inputs(
            run_dir, config, interval_policy_path=provisional_path
        )
    finally:
        provisional_path.unlink(missing_ok=True)
    policy, interval_ticks = build_interval_policy(
        provisional_inputs.intervals,
        dwells,
        settling_exclusion_s=int(plan["settling_exclusion_s"]),
    )
    policy_path = output_dir / POLICY_NAME
    _write_json_atomic(policy_path, policy)
    inputs = load_run_inputs(run_dir, config, interval_policy_path=policy_path)
    estimates = estimate_spans(inputs.intervals, config)
    visits = summarize_dwells(
        dwells,
        inputs.intervals,
        estimates,
        interval_ticks,
        selected_span_s=selected_span_s,
        diagnostic_span_s=diagnostic_span_s,
    )
    gain_samples = drift_cancelled_gain_samples(visits)
    target_hz = float(manifest.data["oscillator"]["nominal_frequency_hz"])
    crossing, repeatability, nominal_gain = crossing_and_repeatability(
        visits, gain_samples, target_hz
    )
    hysteresis = bidirectional_hysteresis(visits, nominal_gain)
    gain_values = [float(item["hz_per_code"]) for item in gain_samples]
    noise_floor = float(
        selected_profile["authoritative_policy"]["empirical_detection_floor_hz"]
    )
    expected_outputs_per_dwell = math.floor(
        (int(plan["dwell_s"]) - int(plan["settling_exclusion_s"])) / selected_span_s
    )
    min_selected_outputs = min(item.selected_estimate_count for item in visits)
    max_post_exclusion_range = max(float(item.selected_range_hz) for item in visits)
    clamp_min = _parse_code(plan["dac_clamp"]["min_code"])
    clamp_max = _parse_code(plan["dac_clamp"]["max_code"])
    crossing_resolved = crossing["observed_drift_adjusted_bracket"] is not None
    source_invalid_interval_count = sum(
        not item.valid or bool(item.reasons) for item in inputs.intervals
    )
    policy_excluded_interval_count = sum(
        item.settling_excluded for item in inputs.intervals
    )
    events = executor.get("events")
    if not isinstance(events, list):
        raise ValueError("executor result has no event list")
    event_names = [str(item.get("event")) for item in events if isinstance(item, dict)]
    warmup_starts = [
        item for item in events
        if isinstance(item, dict) and item.get("event") == "warmup_start"
    ]
    transition_requests = [
        item for item in events
        if isinstance(item, dict) and item.get("event") == "transition_request"
    ]
    if len(warmup_starts) != 1 or not transition_requests:
        raise ValueError("executor timing events are incomplete")
    executor_started = datetime.fromisoformat(
        str(executor["started_at_utc"]).replace("Z", "+00:00")
    )
    first_transition = datetime.fromisoformat(
        str(transition_requests[0]["utc"]).replace("Z", "+00:00")
    )
    observed_warmup_s = (first_transition - executor_started).total_seconds()
    inter_acknowledgement_s = [
        (later.accepted_unwrapped_ticks - earlier.accepted_unwrapped_ticks)
        / TICKS_PER_SECOND
        for earlier, later in zip(dwells, dwells[1:])
    ]
    acknowledgement_rows = executor.get("acknowledgements")
    if not isinstance(acknowledgement_rows, list):
        raise ValueError("executor result has no acknowledgement list")
    acknowledgement_latencies_s = [float(item["latency_s"]) for item in acknowledgement_rows]
    acknowledgement_slack_s = [float(item["slack_s"]) for item in acknowledgement_rows]
    acknowledgement_deadline_s = float(plan["ack_deadline_s"])
    timing_evidence_complete = (
        float(warmup_starts[0].get("duration_s", -1)) == float(plan["initial_warmup_s"])
        and observed_warmup_s >= float(plan["initial_warmup_s"])
        and event_names.count("warmup_complete") == 1
        and event_names.count("settling_exclusion_complete") == len(dwells)
        and event_names.count("dwell_complete") == len(dwells)
        and all(value >= float(plan["dwell_s"]) for value in inter_acknowledgement_s)
    )
    acknowledgement_timing_clean = (
        len(acknowledgement_latencies_s) == len(dwells)
        and all(math.isfinite(value) and 0 <= value <= acknowledgement_deadline_s for value in acknowledgement_latencies_s)
        and all(math.isfinite(value) and value > 0 for value in acknowledgement_slack_s)
    )
    gate_checks = {
        "executor_complete": (
            executor.get("status") == "complete_fail_static"
            and executor.get("reason") == "planned_sequence_complete"
        ),
        "predetermined_nonfeedback_fail_static_policy": (
            executor.get("feedback_derived_commands") is False
            and executor.get("automatic_restore") is False
        ),
        "exact_acknowledgement_count": len(dwells) == len(_plan_steps(plan)),
        "acknowledgement_timing_clean": acknowledgement_timing_clean,
        "planned_timing_evidence_complete": timing_evidence_complete,
        "final_safe_code_verified": dwells[-1].code == _parse_code(plan["final_safe_code"]),
        "capture_health_clean": not inputs.global_reason_codes
        and source_invalid_interval_count == 0,
        "selected_outputs_per_dwell": min_selected_outputs >= expected_outputs_per_dwell,
        "gain_positive_and_finite": all(math.isfinite(value) and value > 0 for value in gain_values),
        "crossing_resolved_inside_characterized_range": crossing_resolved
        and clamp_min <= crossing["nominal_code_float"] <= clamp_max,
        "settled_selected_spread_not_above_measured_floor": max_post_exclusion_range <= noise_floor,
        "bidirectional_hysteresis_measured": len(hysteresis) == 2
        and all(item["absolute_equivalent_codes"] is not None for item in hysteresis),
    }
    exit_gate = "pass_observe_only" if all(gate_checks.values()) else "fail_closed"
    ack_residuals_ms = [
        (
            item.accepted_unwrapped_ticks
            - item.elapsed_ms * TICKS_PER_MILLISECOND
        )
        / TICKS_PER_MILLISECOND
        for item in dwells
    ]
    temperature = _temperature_context(
        environment_path,
        dwells[0].accepted_unwrapped_ticks,
        dwells[-1].accepted_unwrapped_ticks,
        int(plan["dwell_s"]),
    )
    minimum_gain = min(gain_values)
    maximum_hysteresis_codes = max(
        float(item["absolute_equivalent_codes"]) for item in hysteresis
    )
    crossing_replay_components = {
        "stage3_empirical_floor_equivalent_codes": noise_floor / minimum_gain,
        "maximum_observed_hysteresis_codes": maximum_hysteresis_codes,
        "centre_raw_visit_span_equivalent_codes": float(
            repeatability["raw_visit_span_hz"]
        )
        / minimum_gain,
    }
    crossing_replay_margin_codes = math.ceil(sum(crossing_replay_components.values()))
    crossing_replay_min_code = math.floor(
        float(crossing["nominal_code_float"]) - crossing_replay_margin_codes
    )
    crossing_replay_max_code = math.ceil(
        float(crossing["nominal_code_float"]) + crossing_replay_margin_codes
    )
    crossing["conservative_observe_only_replay_envelope"] = {
        "minimum_code": crossing_replay_min_code,
        "maximum_code": crossing_replay_max_code,
        "outward_margin_codes": crossing_replay_margin_codes,
        "components": crossing_replay_components,
        "authority": "conservative finite-run replay envelope; not calibrated uncertainty or actuation authority",
    }
    tolerance_provenance = [
        _provenance_row(
            "executor completion state",
            "status complete_fail_static with reason planned_sequence_complete",
            "hard safety limit",
            "05_OPEN_LOOP_PLANT_CAMPAIGN_PROMPT.md, firmware/run-control requirements; bound executor result",
            "Exact predetermined Stage 5 run only; completion means the final dwell ended without a universal stop condition.",
            "exact structured status/reason comparison",
            "digital state identity; no analogue or calibrated-frequency inference",
            {"status": executor.get("status"), "reason": executor.get("reason")},
            "pass" if gate_checks["executor_complete"] else "fail",
            "Reject the run, leave the last verified code static and create no plant model.",
        ),
        _provenance_row(
            "feedback-derived commands and automatic restore, count/Boolean",
            "zero feedback-derived commands and automatic_restore=false",
            "hard safety limit",
            "00_MASTER_UNATTENDED_PROMPT.md, Prohibited actions; 05_OPEN_LOOP_PLANT_CAMPAIGN_PROMPT.md",
            "Every live Stage 5 command must come only from the immutable nine-code plan; no automatic 0x8000 restore.",
            "exact executor policy/result identity",
            "digital source/result check; no measurement uncertainty",
            {"feedback_derived_commands": executor.get("feedback_derived_commands"), "automatic_restore": executor.get("automatic_restore")},
            "pass" if gate_checks["predetermined_nonfeedback_fail_static_policy"] else "fail",
            "Universal safety failure; reject the run and do not proceed.",
        ),
        _provenance_row(
            "initial warmup, dwell and exclusion, s",
            f"at least {plan['initial_warmup_s']} s before the first command; {plan['dwell_s']} s per acknowledged code including {plan['settling_exclusion_s']} s exclusion",
            "characterization reference",
            "CX317 datasheet p. 2 warm-up <=5 min; Stage 5 prompt Initial campaign design; bound plan and executor monotonic scheduler",
            "The 1,800 s warmup is six times the datasheet warm-up statement and follows the programme design; it is not a thermal-equilibrium or cold-start qualification. Dwell/exclusion are characterization timing, not controller cadence.",
            f"observed first-request offset from executor start={observed_warmup_s:.0f} s; minimum adjacent accepted-code spacing={min(inter_acknowledgement_s):.6f} s; all nine settling/dwell-complete events required",
            "UTC event stamps are one-second resolution; acknowledged-code spacing uses the RP2040 timer; combined clock uncertainty unavailable",
            {"observed_warmup_s": observed_warmup_s, "minimum_inter_acknowledgement_s": min(inter_acknowledgement_s), "settling_complete_event_count": event_names.count("settling_exclusion_complete"), "dwell_complete_event_count": event_names.count("dwell_complete")},
            "pass" if gate_checks["planned_timing_evidence_complete"] else "fail",
            "Reject the plant run because its prescribed timing evidence is incomplete.",
        ),
        _provenance_row(
            "acknowledged predetermined DAC writes, count",
            f"exactly {len(_plan_steps(plan))}, in the bound order",
            "hard safety limit",
            "05_OPEN_LOOP_PLANT_CAMPAIGN_PROMPT.md, Initial campaign design; bound plan and executor result",
            "This exact run only; no adaptive or feedback-derived command is permitted.",
            "one exact successful, unclamped, zero-flag acknowledgement per planned code",
            "digital identity check; analogue voltage uncertainty remains unavailable",
            len(dwells),
            "pass" if gate_checks["exact_acknowledgement_count"] else "fail",
            "Reject the plant run; create no model and do not proceed to controller replay.",
        ),
        _provenance_row(
            "DAC acknowledgement latency/deadline slack, s",
            f"latency <= {acknowledgement_deadline_s:.12g} s and slack > 0 s for every write",
            "architecture screen",
            "actual-rig Stage 5 no-write service probe; bound plan ack_deadline_s; exact executor acknowledgements",
            "Same capture-owned FIFO and flashed artifact; the pre-run read-only sample supplied the deadline, while these nine write acknowledgements supply the direct live result.",
            "deadline minus measured monotonic acknowledgement latency; minimum slack must remain positive",
            "host clocks are not calibrated; deadline is a service-path safety screen, not a controller cadence or plant-settling value",
            {"minimum_latency_s": min(acknowledgement_latencies_s), "maximum_latency_s": max(acknowledgement_latencies_s), "minimum_slack_s": min(acknowledgement_slack_s), "deadline_s": acknowledgement_deadline_s},
            "pass" if gate_checks["acknowledgement_timing_clean"] else "fail",
            "Stop the sequence fail-static and reject the plant run.",
        ),
        _provenance_row(
            "capture/reference/transport invalid evidence, count",
            "zero global reason codes and zero source-invalid adjacent intervals",
            "hard safety limit",
            "00_MASTER_UNATTENDED_PROMPT.md, Universal hardware stop conditions; selected estimator invalidation contract",
            "Exact captured raw source evidence, run-specific D10 same-PPS declaration and PPS-gated backend.",
            "count interval validity/reason codes after excluding only the declared policy-settling intervals",
            "digital continuity and health screen; reference, aperture and calibrated-frequency uncertainty remain unavailable",
            {"global_reason_codes": list(inputs.global_reason_codes), "source_invalid_adjacent_interval_count": source_invalid_interval_count},
            "pass" if gate_checks["capture_health_clean"] else "fail",
            "Reject the run; do not use its plant estimates or proceed to replay.",
        ),
        _provenance_row(
            "final fail-static DAC code, 16-bit code",
            f"exactly 0x{_parse_code(plan['final_safe_code']):04X}",
            "hard safety limit",
            "operator confirmation recorded 2026-08-02; Stage 5 physical gate; bound plant plan",
            "Provisional safe static state for this topology and campaign only; not feedback authority.",
            "compare final exact successful acknowledgement and executor last_verified_code",
            "applied-code digital acknowledgement exact; connected Vc calibrated uncertainty unavailable",
            f"0x{dwells[-1].code:04X}",
            "pass" if gate_checks["final_safe_code_verified"] else "fail",
            "Fail static at the last verified code, reject the run and request physical review.",
        ),
        _provenance_row(
            "DAC characterization code range, 16-bit code",
            f"0x{clamp_min:04X}..0x{clamp_max:04X}, inclusive",
            "hard safety limit",
            "AD5693R Rev. E pp. 4,19; CX317 datasheet p. 2; Stage 5 physical-gate calculation and exact plan",
            "AD5693R internal reference/gain 1 and unchanged passive connected topology; not a general AD5693R range.",
            "manufacturer worst-case gain-1 output bounds were shown inside CX317 0..3.3 V recommended Vc range before first write",
            "accepted calibrated Vc uncertainty unavailable; manufacturer/topology maximum bound supplies the safety margin",
            [f"0x{item.code:04X}" for item in dwells],
            "pass" if all(clamp_min <= item.code <= clamp_max for item in dwells) else "fail",
            "Reject the run and do not issue any further command.",
        ),
        _provenance_row(
            "authoritative estimator span, s; outputs per settled dwell, count",
            f"{selected_span_s} s and at least {expected_outputs_per_dwell} complete non-overlapping outputs per dwell",
            "architecture screen",
            "Stage 4 selected-estimator profile; Stage 5 plan selected-span-fit calculation",
            "Exact PPS_CUMULATIVE_SNAPSHOT_SPAN_V1 method and 2,400-900=1,500 s settled support.",
            f"floor(({plan['dwell_s']}-{plan['settling_exclusion_s']})/{selected_span_s})={expected_outputs_per_dwell}",
            "count, aperture, reference and calibration uncertainty unavailable",
            {"span_s": selected_span_s, "minimum_outputs_observed": min_selected_outputs},
            "pass" if gate_checks["selected_outputs_per_dwell"] else "fail",
            "Characterization evidence is insufficient; do not fit a PPS-gated model.",
        ),
        _provenance_row(
            "diagnostic estimator span and output cadence, s",
            f"{diagnostic_span_s} s span at one-second output cadence; diagnostic only and never command-authoritative",
            "characterization reference",
            "Stage 4 selected-estimator profile, diagnostic_policy",
            "Same PPS_CUMULATIVE_SNAPSHOT_SPAN_V1 source intervals; retained only to inspect within-dwell response and settling context.",
            "exact profile binding and diagnostic-span estimator execution",
            "finite-run count quantization only; calibrated/reference/combined uncertainty unavailable",
            {"span_s": diagnostic_span_s, "minimum_outputs_observed": min(item.diagnostic_estimate_count for item in visits)},
            "characterization-only",
            "Loss of diagnostics limits response description but cannot be bypassed to create control authority.",
        ),
        _provenance_row(
            "settling exclusion, fresh history and post-exclusion selected-estimate spread, s/Hz",
            f"exclude {plan['settling_exclusion_s']} s, then require fresh {selected_span_s} s support; within-dwell spread <= {noise_floor:.12g} Hz measured Stage 3 empirical detection floor",
            "model-applicability bound",
            "Stage 5 prompt Initial campaign design; sealed Stage 3 fixed-code evidence bound by cx317_pps_gated_selected_v1.json, authoritative_policy.empirical_detection_floor_hz",
            "Same topology/backend/selected method; finite-run two-increment conservative detection rule, not calibrated resolution or t95.",
            f"history reset={plan['settling_exclusion_s']}+{selected_span_s}={int(plan['settling_exclusion_s']) + selected_span_s} s; maximum of each dwell's settled 600 s output ranges compared with the sealed fixed-code empirical floor",
            "combined uncertainty unavailable; margin is empirical_floor minus observed maximum range",
            {"maximum_range_hz": max_post_exclusion_range, "margin_hz": noise_floor - max_post_exclusion_range},
            "pass" if gate_checks["settled_selected_spread_not_above_measured_floor"] else "fail",
            "The 900 s exclusion is not adequate at selected-estimator resolution; fail Stage 5 closed.",
        ),
        _provenance_row(
            "local CX317 gain sign, Hz/code",
            "> 0 for every drift-cancelled sample",
            "architecture screen",
            "sealed Run 020 positive-gain characterization plus the six direct Stage 5 same-code/centre brackets",
            "Run 020 supplies sign expectation only; Stage 5 PPS-gated evidence supplies current magnitude and observed range.",
            "(higher-code frequency minus lower-code frequency) / code difference after linear same-code drift interpolation",
            "finite-run observed range only; calibrated/model uncertainty unavailable",
            {"minimum": min(gain_values), "median": nominal_gain, "maximum": max(gain_values)},
            "pass" if gate_checks["gain_positive_and_finite"] else "fail",
            "Reject the new plant model and do not perform controller replay.",
        ),
        _provenance_row(
            "crossing estimate, 16-bit code",
            f"resolved and inside characterized 0x{clamp_min:04X}..0x{clamp_max:04X}",
            "model-applicability bound",
            "direct Stage 5 drift-adjusted dwell measurements; hard characterization range above",
            "Current run, topology, backend, estimator and observed temperature context only.",
            "campaign-midpoint centre prediction plus median measured gain; direct below/above bracket also required",
            "between-visit range reported; calibrated electrical/reference/model uncertainty unavailable",
            crossing,
            "pass" if gate_checks["crossing_resolved_inside_characterized_range"] else "fail",
            "Crossing is unresolved or extrapolated; do not create a controller-replay model.",
        ),
        _provenance_row(
            "conservative crossing envelope for observe-only replay, 16-bit code",
            f"0x{crossing_replay_min_code:04X}..0x{crossing_replay_max_code:04X}; no extrapolation outside the characterized 0x{clamp_min:04X}..0x{clamp_max:04X} range",
            "model-applicability bound",
            "sealed Stage 3 empirical floor plus direct Stage 5 minimum gain, centre repeatability and maximum observed interior hysteresis",
            "Current topology/backend/estimator and finite-run evidence only; an additive full-span budget is deliberately conservative and has no statistical coverage claim.",
            f"ceil(({noise_floor:.12g}/{minimum_gain:.12g})+{maximum_hysteresis_codes:.12g}+({repeatability['raw_visit_span_hz']:.12g}/{minimum_gain:.12g}))={crossing_replay_margin_codes} codes; apply outward around {crossing['nominal_code_float']:.12g}",
            "combined calibrated uncertainty unavailable; this is an explicit source-hierarchy-4 calculation from sealed/direct evidence",
            crossing["conservative_observe_only_replay_envelope"],
            "characterization-only",
            "Outside this envelope, preview must report model mismatch; it still cannot command the DAC inside the envelope.",
        ),
        _provenance_row(
            "interior bidirectional hysteresis, Hz and equivalent codes",
            "two direction-paired interior results available; no invented magnitude threshold",
            "characterization reference",
            "direct Stage 5 repeated 0xA850 and 0xAA50 visits from opposite directions",
            "Finite-run observed path dependence with centre-drift removal; not a guaranteed bound.",
            "return residual minus outbound residual; divide absolute result by measured median Hz/code for descriptive equivalent codes",
            "population bound and combined uncertainty unavailable",
            hysteresis,
            "pass" if gate_checks["bidirectional_hysteresis_measured"] else "unavailable",
            "If unavailable, plant uncertainty is incomplete and Stage 5 fails closed.",
        ),
        _provenance_row(
            "combined plant/estimator measurement uncertainty, Hz or codes",
            "available before any actuation-authority claim",
            "proposed control-policy value",
            "user acceptance requirement and Stage 4/5 evidence limitations",
            "No traceable aperture, reference, calibration or combined uncertainty has been established.",
            "not calculable from current evidence",
            "unavailable",
            "unavailable",
            "unavailable",
            "No calibrated-accuracy or actuation-authority claim; any later policy remains observe-only.",
        ),
        _provenance_row(
            "near-CX317 temperature context/applicability, degrees C",
            f"observed SHT41 nearby-air range {temperature['temperature_min_c']}..{temperature['temperature_max_c']} C; no extrapolation for the new model without fresh evidence",
            "model-applicability bound",
            "direct Stage 5 SHT41 evidence; sensor/placement provenance in the completed physical gate",
            "SHT41 was approximately 1 cm from the CX317 under the cardboard draft shield; it is not case, oven or internal temperature and no causal sensitivity is claimed.",
            "minimum and maximum valid nearby-air samples during the acknowledged campaign",
            "sensor, spatial and case-to-air uncertainty unavailable; no extra safety margin is invented",
            temperature,
            "characterization-only",
            "Observe-only preview reports model-temperature mismatch outside the observed context; obtain new evidence before widening.",
        ),
        _provenance_row(
            "active estimator/controller-derived DAC update size, codes",
            "exactly 0 in every live build and Stage 5/6 model",
            "hard safety limit",
            "00_MASTER_UNATTENDED_PROMPT.md prohibited actions; Stage 6 firmware structural-safety requirements",
            "All live Stage 5 evidence and any following observe-only replay/preview; a future proposed nonzero value is descriptive only.",
            "structural Boolean/source dependency checks plus zero configured manual_preview_max_step_codes in the new observe-only model",
            "digital invariant; no measurement uncertainty",
            0,
            "pass",
            "Any estimator/controller-derived write or nonzero live update setting is a universal stop and invalidates readiness.",
        ),
    ]
    report = {
        "schema_version": 1,
        "tool_version": TOOL_VERSION,
        "run_id": manifest.run_id,
        "exit_gate": exit_gate,
        "gate_checks": gate_checks,
        "authority": {
            "control_ready": False,
            "actuation_enabled": False,
            "actuation_authorized": False,
            "actionable": False,
        },
        "bindings": {
            "run_manifest_sha256": _sha256_file(manifest.path),
            "plan_path": str(plan_path.relative_to(REPO_ROOT)),
            "plan_sha256": _sha256_file(plan_path),
            "plan_config_sha256": plan_contract.config_hash,
            "selected_profile_path": str(selected_profile_path.relative_to(REPO_ROOT)),
            "selected_profile_sha256": _sha256_file(selected_profile_path),
            "estimator_config_path": str(estimator_config_path.relative_to(REPO_ROOT)),
            "estimator_config_hash": config.config_hash,
            "executor_result_path": str(executor_path.relative_to(run_dir)),
            "executor_result_sha256": _sha256_file(executor_path),
            "physical_provenance_path": str(physical_path.relative_to(run_dir.parent)),
            "physical_provenance_sha256": _sha256_file(physical_path),
            "interval_policy_path": str(policy_path.relative_to(run_dir)),
            "interval_policy_sha256": _sha256_file(policy_path),
        },
        "source_evidence": {
            name: {"path": str(path.relative_to(run_dir)), "sha256": digest}
            for name, path, digest in (
                (key, path, inputs.source_hashes[key])
                for key, path in inputs.source_paths.items()
            )
        },
        "source_immutability_verified": True,
        "executor": {
            "status": executor["status"],
            "reason": executor["reason"],
            "acknowledgement_count": len(dwells),
            "ack_elapsed_to_status_residual_ms": ack_residuals_ms,
            "last_verified_code": executor["last_verified_code"],
            "automatic_restore": executor["automatic_restore"],
            "feedback_derived_commands": executor["feedback_derived_commands"],
        },
        "capture_health": {
            "raw_snapshot_count": inputs.raw_snapshot_count,
            "source_valid_adjacent_interval_count": len(inputs.intervals)
            - source_invalid_interval_count,
            "source_invalid_adjacent_interval_count": source_invalid_interval_count,
            "policy_excluded_interval_count": policy_excluded_interval_count,
            "settled_effective_interval_count": inputs.valid_adjacent_interval_count,
            "global_reason_codes": list(inputs.global_reason_codes),
        },
        "estimator": {
            "method_id": config.method_id,
            "authoritative_span_s": selected_span_s,
            "diagnostic_span_s": diagnostic_span_s,
            "authoritative_count_increment_hz": 1.0 / selected_span_s,
            "stage3_empirical_detection_floor_hz": noise_floor,
            "uncertainty_status": "unavailable",
        },
        "dwell_visits": [asdict(item) for item in visits],
        "plant_gain": {
            "samples": gain_samples,
            "sample_count": len(gain_values),
            "minimum_hz_per_code": min(gain_values),
            "median_hz_per_code": nominal_gain,
            "maximum_hz_per_code": max(gain_values),
            "population_stddev_hz_per_code": statistics.pstdev(gain_values),
            "uncertainty_status": "unavailable; observed finite-run range only",
        },
        "crossing": crossing,
        "centre_repeatability": repeatability,
        "bidirectional_hysteresis": hysteresis,
        "settling": {
            "declared_exclusion_s": int(plan["settling_exclusion_s"]),
            "fresh_selected_support_s": selected_span_s,
            "conservative_history_reset_s": int(plan["settling_exclusion_s"]) + selected_span_s,
            "maximum_post_exclusion_selected_range_hz": max_post_exclusion_range,
            "comparison_floor_hz": noise_floor,
            "comparison_pass": gate_checks["settled_selected_spread_not_above_measured_floor"],
            "t95_s_min": None,
            "t95_s_max": None,
            "interpretation": "900 s exclusion is tested only at 600 s selected-estimator resolution; no sub-resolution t95 is claimed",
        },
        "temperature_context": temperature,
        "physical_electrical_tolerance_provenance": physical_provenance,
        "tolerance_provenance": tolerance_provenance,
        "limitations": [
            "No calibrated absolute frequency, voltage, reference, aperture or combined uncertainty is claimed.",
            "No isolated firmware jitter, physical phase/duty, D8 waveform or scope qualification is claimed.",
            "SHT41 is a nearby-air proxy, not CX317 internal or case temperature.",
            "The observed temperature range is context, not a demonstrated sensitivity limit.",
            "Run 020 is comparison evidence only and is not used as a CX317 specification.",
            "The 900 s exclusion is a validated model-use screen at selected-estimator resolution, not a measured t95 or controller cadence.",
            "This report authorizes only possible observe-only controller replay when exit_gate passes; it authorizes no hardware feedback actuation.",
        ],
    }
    destination = output_dir / OUTPUT_NAME
    source_hashes_before = {name: item["sha256"] for name, item in report["source_evidence"].items()}
    _write_json_atomic(destination, report)
    source_hashes_after = {
        name: _sha256_file(inputs.source_paths[name]) for name in source_hashes_before
    }
    if source_hashes_before != source_hashes_after:
        destination.unlink(missing_ok=True)
        raise RuntimeError("source evidence changed while writing plant characterization")
    markdown_path = run_dir / "reports" / REPORT_NAME
    _write_text_atomic(markdown_path, render_markdown_report(report))
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline characterization of the predetermined CX317 PPS-gated Stage 5 run."
    )
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--selected-profile", type=Path, default=DEFAULT_SELECTED_PROFILE)
    parser.add_argument("--estimator-config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--executor-result", type=Path)
    args = parser.parse_args(argv)
    try:
        output = characterize_run(
            args.run_dir,
            plan_path=args.plan,
            selected_profile_path=args.selected_profile,
            estimator_config_path=args.estimator_config,
            executor_result_path=args.executor_result,
        )
    except (FileNotFoundError, ValueError, RuntimeError, OverflowError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
