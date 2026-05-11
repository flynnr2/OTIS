from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv


RAW_EVENT_FIELDS = [
    "record_type",
    "schema_version",
    "event_seq",
    "channel_id",
    "edge",
    "timestamp_ticks",
    "capture_domain",
    "flags",
]

COUNT_OBSERVATION_FIELDS = [
    "record_type",
    "schema_version",
    "count_seq",
    "channel_id",
    "gate_open_ticks",
    "gate_close_ticks",
    "gate_domain",
    "counted_edges",
    "source_edge",
    "source_domain",
    "flags",
]

HEALTH_FIELDS = [
    "record_type",
    "schema_version",
    "status_seq",
    "timestamp_ticks",
    "status_domain",
    "component",
    "status_key",
    "status_value",
    "severity",
    "flags",
]


@dataclass(frozen=True)
class CsvValidationResult:
    path: Path
    row_count: int
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_csv_header(path: Path, expected_fields: list[str]) -> CsvValidationResult:
    errors: list[str] = []
    row_count = 0

    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        actual = reader.fieldnames or []
        if actual != expected_fields:
            errors.append(f"header mismatch: expected {expected_fields}, got {actual}")
        for row_count, _row in enumerate(reader, start=1):
            pass

    return CsvValidationResult(path=path, row_count=row_count, errors=tuple(errors))
