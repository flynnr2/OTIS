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

CONTRACT_FIELDS = {
    "raw_events_v1": RAW_EVENT_FIELDS,
    "count_observations_v1": COUNT_OBSERVATION_FIELDS,
    "health_v1": HEALTH_FIELDS,
}

CONTRACT_RECORD_TYPES = {
    "raw_events_v1": {"EVT", "REF"},
    "count_observations_v1": {"CNT"},
    "health_v1": {"STS"},
}

SEQUENCE_FIELDS = {
    "raw_events_v1": "event_seq",
    "count_observations_v1": "count_seq",
    "health_v1": "status_seq",
}

TIMESTAMP_FIELDS = {
    "raw_events_v1": ("timestamp_ticks",),
    "count_observations_v1": ("gate_open_ticks", "gate_close_ticks"),
    "health_v1": ("timestamp_ticks",),
}

CHANNEL_FIELDS = {
    "raw_events_v1": "channel_id",
    "count_observations_v1": "channel_id",
}

DOMAIN_FIELDS = {
    "raw_events_v1": ("capture_domain",),
    "count_observations_v1": ("gate_domain",),
    "health_v1": ("status_domain",),
}

FLAG_KNOWN_MASK_V1 = 0xFFFF
VALID_EDGES = {"R", "F", "B"}
VALID_SEVERITIES = {"INFO", "WARN", "ERROR", "FATAL"}


@dataclass(frozen=True)
class CsvValidationContext:
    contract: str
    known_channels: frozenset[int]
    known_domains: frozenset[str]
    template: bool = False


@dataclass(frozen=True)
class CsvValidationResult:
    path: Path
    row_count: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def _parse_non_negative_int(value: str, field_name: str, row_number: int, errors: list[str]) -> int | None:
    try:
        parsed = int(value, 10)
    except (TypeError, ValueError):
        errors.append(f"row {row_number}: {field_name} is not an integer: {value!r}")
        return None
    if parsed < 0:
        errors.append(f"row {row_number}: {field_name} must be non-negative: {parsed}")
        return None
    return parsed


def _check_schema_version(row: dict[str, str], row_number: int, errors: list[str]) -> None:
    version = _parse_non_negative_int(row.get("schema_version", ""), "schema_version", row_number, errors)
    if version is not None and version != 1:
        errors.append(f"row {row_number}: unsupported schema_version {version}; expected 1")


def _check_record_type(contract: str, row: dict[str, str], row_number: int, errors: list[str]) -> None:
    record_type = row.get("record_type", "")
    expected = CONTRACT_RECORD_TYPES[contract]
    if record_type not in expected:
        errors.append(f"row {row_number}: record_type {record_type!r} not valid for {contract}; expected one of {sorted(expected)}")


def _check_sequence(contract: str, row: dict[str, str], row_number: int, previous: int | None, errors: list[str]) -> int | None:
    field_name = SEQUENCE_FIELDS[contract]
    current = _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
    if current is not None and previous is not None and current <= previous:
        errors.append(f"row {row_number}: {field_name} must be strictly increasing; previous={previous}, current={current}")
    return current if current is not None else previous


def _check_timestamps(contract: str, row: dict[str, str], row_number: int, errors: list[str]) -> None:
    parsed: dict[str, int] = {}
    for field_name in TIMESTAMP_FIELDS[contract]:
        value = _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
        if value is not None:
            parsed[field_name] = value
    if contract == "count_observations_v1" and {"gate_open_ticks", "gate_close_ticks"} <= parsed.keys():
        if parsed["gate_close_ticks"] <= parsed["gate_open_ticks"]:
            errors.append(
                f"row {row_number}: gate_close_ticks must be greater than gate_open_ticks; "
                f"open={parsed['gate_open_ticks']}, close={parsed['gate_close_ticks']}"
            )


def _check_timestamp_monotonicity(
    contract: str,
    parsed_timestamps: dict[str, int],
    row_number: int,
    previous_timestamps: dict[str, int],
    errors: list[str],
) -> None:
    for field_name in TIMESTAMP_FIELDS[contract]:
        if field_name not in parsed_timestamps:
            continue
        previous = previous_timestamps.get(field_name)
        current = parsed_timestamps[field_name]
        if previous is not None and current < previous:
            errors.append(f"row {row_number}: {field_name} must be monotonic; previous={previous}, current={current}")
        previous_timestamps[field_name] = current


def _check_channel(context: CsvValidationContext, row: dict[str, str], row_number: int, errors: list[str]) -> None:
    field_name = CHANNEL_FIELDS.get(context.contract)
    if not field_name:
        return
    channel = _parse_non_negative_int(row.get(field_name, ""), field_name, row_number, errors)
    if channel is not None and context.known_channels and channel not in context.known_channels:
        errors.append(f"row {row_number}: {field_name} {channel} is not declared in manifest channels")


def _check_domains(context: CsvValidationContext, row: dict[str, str], row_number: int, errors: list[str]) -> None:
    for field_name in DOMAIN_FIELDS[context.contract]:
        domain = row.get(field_name, "")
        if context.known_domains and domain not in context.known_domains:
            errors.append(f"row {row_number}: {field_name} {domain!r} is not declared in manifest domains")


def _check_flags(row: dict[str, str], row_number: int, errors: list[str]) -> None:
    flags = _parse_non_negative_int(row.get("flags", ""), "flags", row_number, errors)
    if flags is not None and flags & ~FLAG_KNOWN_MASK_V1:
        errors.append(f"row {row_number}: flags uses reserved v1 bits: {flags}")


def _check_edges(contract: str, row: dict[str, str], row_number: int, errors: list[str]) -> None:
    if contract == "raw_events_v1" and row.get("edge") not in VALID_EDGES:
        errors.append(f"row {row_number}: edge must be one of {sorted(VALID_EDGES)}")
    if contract == "count_observations_v1" and row.get("source_edge") not in VALID_EDGES:
        errors.append(f"row {row_number}: source_edge must be one of {sorted(VALID_EDGES)}")


def _check_count_observation(row: dict[str, str], row_number: int, errors: list[str]) -> None:
    if "counted_edges" in row:
        _parse_non_negative_int(row.get("counted_edges", ""), "counted_edges", row_number, errors)


def _check_health(row: dict[str, str], row_number: int, errors: list[str]) -> None:
    if row.get("severity") not in VALID_SEVERITIES:
        errors.append(f"row {row_number}: severity must be one of {sorted(VALID_SEVERITIES)}")
    for field_name in ("component", "status_key", "status_value"):
        if not row.get(field_name):
            errors.append(f"row {row_number}: {field_name} must not be empty")


def validate_csv(path: Path, context: CsvValidationContext) -> CsvValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    row_count = 0
    previous_seq: int | None = None
    previous_timestamps: dict[str, int] = {}

    if context.contract not in CONTRACT_FIELDS:
        return CsvValidationResult(path=path, row_count=0, errors=(f"unsupported contract {context.contract!r}",))
    if not path.exists():
        return CsvValidationResult(path=path, row_count=0, errors=("file listed in manifest does not exist",))

    expected_fields = CONTRACT_FIELDS[context.contract]
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        actual = reader.fieldnames or []
        if actual != expected_fields:
            errors.append(f"header mismatch: expected {expected_fields}, got {actual}")

        for row_count, row in enumerate(reader, start=1):
            if None in row:
                errors.append(f"row {row_count}: malformed row has too many columns")
            for field_name in expected_fields:
                if row.get(field_name) is None:
                    errors.append(f"row {row_count}: malformed row missing field {field_name}")
            _check_schema_version(row, row_count, errors)
            _check_record_type(context.contract, row, row_count, errors)
            previous_seq = _check_sequence(context.contract, row, row_count, previous_seq, errors)
            _check_timestamps(context.contract, row, row_count, errors)
            parsed_timestamps: dict[str, int] = {}
            for field_name in TIMESTAMP_FIELDS[context.contract]:
                try:
                    parsed_timestamps[field_name] = int(row.get(field_name, ""), 10)
                except (TypeError, ValueError):
                    continue
            _check_timestamp_monotonicity(context.contract, parsed_timestamps, row_count, previous_timestamps, errors)
            _check_channel(context, row, row_count, errors)
            _check_domains(context, row, row_count, errors)
            _check_flags(row, row_count, errors)
            _check_edges(context.contract, row, row_count, errors)
            if context.contract == "count_observations_v1":
                _check_count_observation(row, row_count, errors)
            if context.contract == "health_v1":
                _check_health(row, row_count, errors)

    if row_count == 0:
        warnings.append("CSV has headers but no data rows")

    return CsvValidationResult(path=path, row_count=row_count, errors=tuple(errors), warnings=tuple(warnings))


def validate_csv_header(path: Path, expected_fields: list[str]) -> CsvValidationResult:
    """Compatibility wrapper for older callers; prefer validate_csv()."""
    contract = next((name for name, fields in CONTRACT_FIELDS.items() if fields == expected_fields), "unknown")
    return validate_csv(
        path,
        CsvValidationContext(contract=contract, known_channels=frozenset(), known_domains=frozenset()),
    )
