"""Validate and render numerical tolerance provenance without adding authority.

The contract mirrors the CX317 programme's user-specified evidence hierarchy
and report columns.  It validates provenance records but never decides whether
a proposed threshold is physically adequate.
"""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import tempfile
from typing import Any, Iterable


CONTRACT_ID = "CX317_TOLERANCE_PROVENANCE_TABLE_V1"
DISPOSITIONS = {
    "hard safety limit",
    "architecture screen",
    "characterization reference",
    "model-applicability bound",
    "proposed control-policy value",
}
RESULTS = {
    "pass",
    "fail",
    "characterization-only",
    "unavailable",
    "not tested",
}
ROW_FIELDS = (
    "parameter_and_units",
    "acceptance_rejection_threshold",
    "disposition",
    "source_hierarchy",
    "source_document_and_location",
    "source_conditions_and_applicability",
    "calculation_or_conversion",
    "measurement_uncertainty_and_safety_margin",
    "measured_result",
    "result",
    "consequences_of_failure",
)


def _nonempty_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value.strip()


def _source_hierarchy(value: Any, row_index: int) -> tuple[int, ...]:
    items = value if isinstance(value, list) else [value]
    if not items:
        raise ValueError(f"row {row_index} source_hierarchy must not be empty")
    levels: list[int] = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, int) or item not in range(1, 6):
            raise ValueError(
                f"row {row_index} source_hierarchy values must be integers 1..5"
            )
        if item not in levels:
            levels.append(item)
    return tuple(levels)


def validate_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("tolerance provenance rows must be a non-empty list")
    validated: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or set(row) != set(ROW_FIELDS):
            observed = set(row) if isinstance(row, dict) else set()
            raise ValueError(
                f"row {index} fields differ; "
                f"missing={sorted(set(ROW_FIELDS) - observed)}, "
                f"extra={sorted(observed - set(ROW_FIELDS))}"
            )
        normalized = {
            field: _nonempty_text(row[field], f"row {index} {field}")
            for field in ROW_FIELDS
            if field != "source_hierarchy"
        }
        hierarchy = _source_hierarchy(row["source_hierarchy"], index)
        disposition = normalized["disposition"]
        result = normalized["result"]
        if disposition not in DISPOSITIONS:
            raise ValueError(f"row {index} disposition is not permitted")
        if result not in RESULTS:
            raise ValueError(f"row {index} result is not permitted")
        provenance_text = " ".join(
            normalized[field]
            for field in (
                "acceptance_rejection_threshold",
                "source_document_and_location",
                "source_conditions_and_applicability",
                "calculation_or_conversion",
            )
        ).lower()
        if 5 in hierarchy and "conservative engineering assumption" not in provenance_text:
            raise ValueError(
                f"row {index} hierarchy 5 must be explicitly labelled "
                "conservative engineering assumption"
            )
        if result in {"pass", "fail"} and normalized["measured_result"].lower() in {
            "unavailable",
            "not tested",
        }:
            raise ValueError(f"row {index} {result} requires a measured or calculated result")
        validated.append(
            {
                **normalized,
                "source_hierarchy": list(hierarchy),
            }
        )
    return validated


def validate_table(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "contract_id",
        "report_id",
        "rows",
    }:
        raise ValueError("tolerance provenance table fields differ")
    if value["schema_version"] != 1 or value["contract_id"] != CONTRACT_ID:
        raise ValueError("unsupported tolerance provenance table schema/id")
    report_id = _nonempty_text(value["report_id"], "report_id")
    return {
        "schema_version": 1,
        "contract_id": CONTRACT_ID,
        "report_id": report_id,
        "rows": validate_rows(value["rows"]),
    }


def _markdown_cell(value: Any) -> str:
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value)
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def render_markdown_rows(rows: Iterable[dict[str, Any]]) -> str:
    headings = (
        "Parameter and units",
        "Acceptance/rejection threshold",
        "Disposition",
        "Source hierarchy",
        "Source document and exact page/table/section",
        "Source conditions and applicability to this rig",
        "Calculation or conversion",
        "Measurement uncertainty and safety margin",
        "Measured result",
        "Result",
        "Consequences of failure",
    )
    lines = [
        "| " + " | ".join(headings) + " |",
        "|" + "|".join("---" for _ in headings) + "|",
    ]
    for row in rows:
        lines.append(
            "| " + " | ".join(_markdown_cell(row[field]) for field in ROW_FIELDS) + " |"
        )
    return "\n".join(lines) + "\n"


def render_table(value: Any) -> str:
    return render_markdown_rows(validate_table(value)["rows"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and render a CX317 tolerance-provenance table."
    )
    parser.add_argument("table", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args(argv)
    try:
        value = json.loads(args.table.read_text(encoding="utf-8"))
        markdown = render_table(value)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if args.markdown_output is None:
        print(markdown, end="")
        return 0
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=args.markdown_output.parent,
        prefix=f".{args.markdown_output.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(markdown)
        temporary = Path(handle.name)
    temporary.replace(args.markdown_output)
    print(args.markdown_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
