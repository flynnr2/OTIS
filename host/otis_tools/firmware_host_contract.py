"""Current firmware/host protocol authority and deterministic projections.

The JSON document is the sole authority for wire layouts, versions, command
forms, the ACTIVE status vocabulary, bounded frontiers, and named cross-field
relations.  Production implementations may remain explicit, but they must be
mechanically compared with these projections.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping


CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "data_contracts/otis_firmware_host_contract_v1.json"
)
GENERATED_CPP_HEADER_PATH = (
    Path(__file__).resolve().parents[2]
    / "firmware/arduino/otis_nano_rp2040_connect/"
    "otis_firmware_host_contract.generated.h"
)
EXPECTED_CONTRACT_ID = "OTIS_FIRMWARE_HOST_CONTRACT_V1"
RELATION_KINDS = frozenset(
    {
        "integer_projection",
        "wrapped_suffix",
        "monotonic_sequence",
        "absence_semantics",
        "lifetime_counter",
        "latched_until",
        "causal_frontier",
        "stateful_classifier",
    }
)


class FirmwareHostContractError(ValueError):
    """The checked-in current protocol authority is malformed or stale."""


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise FirmwareHostContractError(f"{field} must be a non-empty string")
    return value


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise FirmwareHostContractError(f"{field} must be an object")
    return value


def _strings(value: object, field: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise FirmwareHostContractError(
            f"{field} must be a non-empty list of unique strings"
        )
    return tuple(value)


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FirmwareHostContractError(
            f"cannot load firmware/host contract {path}: {exc}"
        ) from exc
    root = dict(_mapping(value, "contract"))
    if root.get("schema_version") != 1:
        raise FirmwareHostContractError("contract schema_version must be 1")
    if root.get("contract_id") != EXPECTED_CONTRACT_ID:
        raise FirmwareHostContractError(
            f"contract_id must be {EXPECTED_CONTRACT_ID!r}"
        )
    if root.get("compatibility") != "exact_current_only":
        raise FirmwareHostContractError(
            "firmware/host compatibility must be exact_current_only"
        )

    records = _mapping(root.get("records"), "records")
    seen_tags: set[str] = set()
    for name, raw in records.items():
        record = _mapping(raw, f"records.{name}")
        fields = _strings(record.get("fields"), f"records.{name}.fields")
        if fields[:2] != ("record_type", "schema_version"):
            raise FirmwareHostContractError(
                f"records.{name} must begin with record_type,schema_version"
            )
        tags = _strings(
            record.get("record_types"), f"records.{name}.record_types"
        )
        duplicate_tags = seen_tags.intersection(tags)
        if duplicate_tags:
            raise FirmwareHostContractError(
                f"record tags are multiply assigned: {sorted(duplicate_tags)}"
            )
        seen_tags.update(tags)
        version = record.get("schema_version")
        if not isinstance(version, int) or version <= 0:
            raise FirmwareHostContractError(
                f"records.{name}.schema_version must be positive"
            )
        sequence = record.get("sequence_field")
        if sequence not in fields:
            raise FirmwareHostContractError(
                f"records.{name}.sequence_field is not in its fields"
            )
        for category in ("timestamp_fields", "domain_fields"):
            members = record.get(category)
            if not isinstance(members, list) or any(
                member not in fields for member in members
            ):
                raise FirmwareHostContractError(
                    f"records.{name}.{category} contains an unknown field"
                )
        session = record.get("session_field")
        if session is not None and session not in fields:
            raise FirmwareHostContractError(
                f"records.{name}.session_field is not in its fields"
            )
        _string(record.get("first_consumer"), f"records.{name}.first_consumer")

    snapshots = _mapping(root.get("status_snapshots"), "status_snapshots")
    if len(snapshots) != 1:
        raise FirmwareHostContractError(
            "the current image must declare exactly one ACTIVE status contract"
        )
    snapshot_name, raw_snapshot = next(iter(snapshots.items()))
    snapshot = _mapping(raw_snapshot, f"status_snapshots.{snapshot_name}")
    _strings(snapshot.get("keys"), f"status_snapshots.{snapshot_name}.keys")
    envelope = _mapping(
        snapshot.get("envelope"),
        f"status_snapshots.{snapshot_name}.envelope",
    )
    if set(envelope) != {"begin", "contract", "complete"}:
        raise FirmwareHostContractError(
            "ACTIVE status envelope must declare begin, contract, and complete"
        )
    if len(set(envelope.values())) != 3:
        raise FirmwareHostContractError("ACTIVE status envelope keys must differ")

    commands = _mapping(root.get("commands"), "commands")
    _strings(commands.get("simple"), "commands.simple")
    forms = _mapping(commands.get("forms"), "commands.forms")
    prefixes: set[str] = set()
    for name, raw in forms.items():
        form = _mapping(raw, f"commands.forms.{name}")
        prefix = _string(form.get("prefix"), f"commands.forms.{name}.prefix")
        if prefix in prefixes:
            raise FirmwareHostContractError(f"duplicate command prefix {prefix!r}")
        prefixes.add(prefix)
        arguments = form.get("arguments")
        if not isinstance(arguments, list) or not arguments:
            raise FirmwareHostContractError(
                f"commands.forms.{name}.arguments must be non-empty"
            )
        for index, raw_argument in enumerate(arguments):
            argument = _mapping(
                raw_argument, f"commands.forms.{name}.arguments[{index}]"
            )
            _string(argument.get("name"), "command argument name")
            _string(argument.get("wire_type"), "command argument wire_type")

    frontiers = _mapping(root.get("frontiers"), "frontiers")
    evidence = _mapping(
        frontiers.get("adaptive_hybrid_evidence"),
        "frontiers.adaptive_hybrid_evidence",
    )
    expected_request = (
        evidence.get("selected_prefix", 0)
        + evidence.get("request_decision", 0)
        + evidence.get("selected_suffix", 0)
    )
    expected_response = (
        evidence.get("selected_prefix", 0)
        + evidence.get("response_decision", 0)
        + evidence.get("response_completion", 0)
        + evidence.get("selected_suffix", 0)
    )
    expected_fail = (
        evidence.get("selected_prefix", 0)
        + evidence.get("request_decision", 0)
        + evidence.get("fail_transition", 0)
        + evidence.get("selected_suffix", 0)
    )
    if (
        evidence.get("request_frontier") != expected_request
        or evidence.get("response_frontier") != expected_response
        or evidence.get("request_fail_frontier") != expected_fail
        or evidence.get("queue_depth", 0)
        < max(expected_request, expected_response, expected_fail)
    ):
        raise FirmwareHostContractError(
            "adaptive-hybrid evidence frontier arithmetic is inconsistent"
        )
    status = _mapping(
        frontiers.get("adaptive_hybrid_status"),
        "frontiers.adaptive_hybrid_status",
    )
    if (
        status.get("field_count") != len(snapshot["keys"])
        or status.get("envelope_count") != 3
        or status.get("burst_count") != len(snapshot["keys"]) + 3
    ):
        raise FirmwareHostContractError(
            "adaptive-hybrid status frontier differs from its vocabulary"
        )
    relations = root.get("relations")
    if not isinstance(relations, list) or len(relations) < 1:
        raise FirmwareHostContractError("relations must be a non-empty list")
    relation_ids = [_mapping(item, "relation").get("id") for item in relations]
    if any(not isinstance(item, str) or not item for item in relation_ids):
        raise FirmwareHostContractError("every relation must have an id")
    if len(relation_ids) != len(set(relation_ids)):
        raise FirmwareHostContractError("relation ids must be unique")
    unknown_relation_kinds = sorted(
        {
            str(_mapping(item, "relation").get("kind"))
            for item in relations
        }
        - RELATION_KINDS
    )
    if unknown_relation_kinds:
        raise FirmwareHostContractError(
            f"unknown relation kinds: {unknown_relation_kinds}"
        )
    return root


CONTRACT = load_contract()
CONTRACT_ID = str(CONTRACT["contract_id"])
CONTRACT_SHA256 = sha256(canonical_bytes(CONTRACT)).hexdigest()
RECORDS = CONTRACT["records"]
RECORD_FIELDS = {
    name: tuple(record["fields"]) for name, record in RECORDS.items()
}
RECORD_SCHEMA_VERSIONS = {
    name: int(record["schema_version"]) for name, record in RECORDS.items()
}
RECORD_TYPES = {
    name: frozenset(record["record_types"]) for name, record in RECORDS.items()
}
RECORD_TYPE_TO_CONTRACT = {
    record_type: name
    for name, record_types in RECORD_TYPES.items()
    for record_type in record_types
}
ACTIVE_STATUS_CONTRACT_ID, ACTIVE_STATUS = next(
    iter(CONTRACT["status_snapshots"].items())
)
ACTIVE_STATUS_KEYS = tuple(ACTIVE_STATUS["keys"])
ACTIVE_STATUS_COMPONENT = str(ACTIVE_STATUS["component"])
ACTIVE_STATUS_ENVELOPE = dict(ACTIVE_STATUS["envelope"])
SIMPLE_COMMANDS = frozenset(CONTRACT["commands"]["simple"])
COMMAND_FORMS = CONTRACT["commands"]["forms"]
FRONTIERS = CONTRACT["frontiers"]
RELATIONS = {item["id"]: item for item in CONTRACT["relations"]}


def integer_projection_matches(
    relation_id: str, *, source: int, target: int, source_domain: str
) -> bool:
    relation = RELATIONS[relation_id]
    if relation.get("kind") != "integer_projection":
        raise FirmwareHostContractError(
            f"{relation_id} is not an integer_projection relation"
        )
    return (
        source_domain == relation.get("source_domain")
        and relation.get("rounding") == "floor"
        and target == source // int(relation["divisor"])
    )


def wrapped_suffix_matches(
    relation_id: str,
    *,
    source: int,
    source_domain: str,
    target: int,
    target_domain: str,
) -> bool:
    relation = RELATIONS[relation_id]
    if relation.get("kind") != "wrapped_suffix":
        raise FirmwareHostContractError(
            f"{relation_id} is not a wrapped_suffix relation"
        )
    modulus = int(relation["modulus"])
    return (
        source_domain == relation.get("source_domain")
        and target_domain == relation.get("target_domain")
        and 0 <= source < modulus
        and target >= 0
        and target % modulus == source
    )


def binding() -> dict[str, object]:
    return {
        "path": CONTRACT_PATH.relative_to(CONTRACT_PATH.parents[1]).as_posix(),
        "contract_id": CONTRACT_ID,
        "sha256": CONTRACT_SHA256,
        "size_bytes": CONTRACT_PATH.stat().st_size,
    }


def _macro_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")


def render_cpp_header() -> str:
    lines = [
        "// Generated from data_contracts/otis_firmware_host_contract_v1.json.",
        "// Do not edit by hand; run tools/generate_firmware_host_contract.py.",
        "#ifndef OTIS_FIRMWARE_HOST_CONTRACT_GENERATED_H",
        "#define OTIS_FIRMWARE_HOST_CONTRACT_GENERATED_H",
        "",
        f"#define OTIS_FIRMWARE_HOST_CONTRACT_ID {json.dumps(CONTRACT_ID)}",
        f"#define OTIS_FIRMWARE_HOST_CONTRACT_SHA256 {json.dumps(CONTRACT_SHA256)}",
        "",
    ]
    for name in sorted(RECORDS):
        macro = _macro_name(name)
        record = RECORDS[name]
        header = ",".join(record["fields"])
        lines.extend(
            [
                f"#define OTIS_CONTRACT_{macro}_HEADER {json.dumps(header)}",
                f"#define OTIS_CONTRACT_{macro}_SCHEMA_VERSION {record['schema_version']}u",
                f"#define OTIS_CONTRACT_{macro}_FIELD_COUNT {len(record['fields'])}u",
            ]
        )
    status = FRONTIERS["adaptive_hybrid_status"]
    evidence = FRONTIERS["adaptive_hybrid_evidence"]
    telemetry = FRONTIERS["telemetry"]
    lines.extend(
        [
            "",
            f"#define OTIS_ACTIVE_STATUS_CONTRACT_ID {json.dumps(ACTIVE_STATUS_CONTRACT_ID)}",
            f"#define OTIS_ACTIVE_STATUS_COMPONENT {json.dumps(ACTIVE_STATUS_COMPONENT)}",
            f"#define OTIS_ACTIVE_STATUS_FIELD_COUNT {status['field_count']}u",
            f"#define OTIS_ACTIVE_STATUS_ENVELOPE_COUNT {status['envelope_count']}u",
            f"#define OTIS_ACTIVE_STATUS_BURST_COUNT {status['burst_count']}u",
            f"#define OTIS_EVIDENCE_SELECTED_PREFIX_COUNT {evidence['selected_prefix']}u",
            f"#define OTIS_EVIDENCE_SELECTED_SUFFIX_COUNT {evidence['selected_suffix']}u",
            f"#define OTIS_EVIDENCE_REQUEST_DECISION_COUNT {evidence['request_decision']}u",
            f"#define OTIS_EVIDENCE_RESPONSE_DECISION_COUNT {evidence['response_decision']}u",
            f"#define OTIS_EVIDENCE_RESPONSE_COMPLETION_COUNT {evidence['response_completion']}u",
            f"#define OTIS_EVIDENCE_FAIL_TRANSITION_COUNT {evidence['fail_transition']}u",
            f"#define OTIS_EVIDENCE_REQUEST_FRONTIER {evidence['request_frontier']}u",
            f"#define OTIS_EVIDENCE_RESPONSE_FRONTIER {evidence['response_frontier']}u",
            f"#define OTIS_EVIDENCE_REQUEST_FAIL_FRONTIER {evidence['request_fail_frontier']}u",
            f"#define OTIS_EVIDENCE_QUEUE_DEPTH {evidence['queue_depth']}u",
            f"#define OTIS_TELEMETRY_NONACTIVE_TIMING_HEALTH_COUNT {telemetry['nonactive_timing_health']}u",
            f"#define OTIS_TELEMETRY_MAXIMUM_CONCURRENT_COUNT {telemetry['maximum_concurrent']}u",
            f"#define OTIS_TELEMETRY_MAXIMUM_BOOT_COUNT {telemetry['maximum_boot']}u",
            f"#define OTIS_TELEMETRY_QUEUE_DEPTH {telemetry['queue_depth']}u",
        ]
    )
    for name in sorted(COMMAND_FORMS):
        form = COMMAND_FORMS[name]
        macro = _macro_name(name)
        lines.extend(
            [
                f"#define OTIS_COMMAND_{macro}_PREFIX {json.dumps(form['prefix'])}",
                f"#define OTIS_COMMAND_{macro}_PREFIX_LENGTH {len(form['prefix'])}u",
                f"#define OTIS_COMMAND_{macro}_ARGUMENT_COUNT {len(form['arguments'])}u",
            ]
        )
    lines.extend(["", "#endif", ""])
    return "\n".join(lines)


def verify_generated_cpp_header(
    path: Path = GENERATED_CPP_HEADER_PATH,
) -> None:
    expected = render_cpp_header()
    try:
        observed = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FirmwareHostContractError(
            f"generated firmware contract header is unavailable: {path}"
        ) from exc
    if observed != expected:
        raise FirmwareHostContractError(
            "generated firmware contract header is stale; run "
            "tools/generate_firmware_host_contract.py"
        )
