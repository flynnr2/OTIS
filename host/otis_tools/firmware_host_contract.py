"""Current firmware/host protocol authority and deterministic projections.

The JSON document is the sole authority for wire layouts, versions, command
forms, the ACTIVE status vocabulary, bounded frontiers, and named cross-field
relations.  Production implementations may remain explicit, but they must be
mechanically compared with these projections.
"""

from __future__ import annotations

from hashlib import sha256
import json
import math
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
        "bounded_modular_lag",
        "monotonic_sequence",
        "absence_semantics",
        "lifetime_counter",
        "latched_until",
        "causal_frontier",
        "stateful_classifier",
    }
)
WIRE_TYPE_KINDS = frozenset(
    {
        "enum",
        "escaped_atom",
        "finite_decimal",
        "hex_integer",
        "integer",
        "literal_or",
        "lower_hex",
        "lower_hex_or_literal",
        "optional",
        "record_type",
        "schema_version",
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

    wire_types = _mapping(root.get("wire_types"), "wire_types")
    for name, raw in wire_types.items():
        wire_type = _mapping(raw, f"wire_types.{name}")
        kind = wire_type.get("kind")
        if kind not in WIRE_TYPE_KINDS:
            raise FirmwareHostContractError(
                f"wire_types.{name}.kind {kind!r} is unknown"
            )
        if kind == "integer":
            minimum = wire_type.get("minimum")
            maximum = wire_type.get("maximum")
            if (
                not isinstance(minimum, int)
                or isinstance(minimum, bool)
                or not isinstance(maximum, int)
                or isinstance(maximum, bool)
                or minimum > maximum
            ):
                raise FirmwareHostContractError(
                    f"wire_types.{name} has an invalid integer range"
                )
            if wire_type.get("signed") is not (minimum < 0):
                raise FirmwareHostContractError(
                    f"wire_types.{name}.signed contradicts its range"
                )
        elif kind in {"literal_or", "optional"}:
            base = wire_type.get("base")
            if base not in wire_types or base == name:
                raise FirmwareHostContractError(
                    f"wire_types.{name}.base is unknown or recursive"
                )
            if kind == "literal_or":
                _string(wire_type.get("literal"), f"wire_types.{name}.literal")
        elif kind == "enum":
            _strings(wire_type.get("values"), f"wire_types.{name}.values")
        elif kind in {"lower_hex", "lower_hex_or_literal"}:
            length = wire_type.get("length")
            if not isinstance(length, int) or length <= 0:
                raise FirmwareHostContractError(
                    f"wire_types.{name}.length must be positive"
                )
            if kind == "lower_hex_or_literal":
                _string(wire_type.get("literal"), f"wire_types.{name}.literal")
        elif kind == "hex_integer":
            digits = wire_type.get("digits")
            prefix = wire_type.get("prefix")
            minimum = wire_type.get("minimum")
            maximum = wire_type.get("maximum")
            if (
                not isinstance(digits, int)
                or digits <= 0
                or not isinstance(prefix, str)
                or not isinstance(minimum, int)
                or not isinstance(maximum, int)
                or minimum < 0
                or minimum > maximum
            ):
                raise FirmwareHostContractError(
                    f"wire_types.{name} has an invalid hexadecimal range"
                )
            if (
                maximum >= 16**digits
                or not isinstance(wire_type.get("uppercase"), bool)
            ):
                raise FirmwareHostContractError(
                    f"wire_types.{name} exceeds its hexadecimal encoding"
                )

    raw_diagnostics = _mapping(
        root.get("raw_only_diagnostics"), "raw_only_diagnostics"
    )
    if raw_diagnostics.get("disposition") != (
        "raw_evidence_only_never_control_or_terminal"
    ):
        raise FirmwareHostContractError(
            "raw-only diagnostics must remain zero-authority raw evidence"
        )
    _string(
        raw_diagnostics.get("first_consumer"),
        "raw_only_diagnostics.first_consumer",
    )
    late_fragment = _mapping(
        raw_diagnostics.get("late_attach_fragment"),
        "raw_only_diagnostics.late_attach_fragment",
    )
    maximum_fragment_bytes = late_fragment.get("maximum_bytes")
    if (
        late_fragment.get(
            "admissible_before_first_recognized_protocol_line_only"
        )
        is not True
        or not isinstance(maximum_fragment_bytes, int)
        or maximum_fragment_bytes <= 0
        or late_fragment.get("content")
        != "bounded_uninterpreted_carrier_fragment"
    ):
        raise FirmwareHostContractError(
            "raw-only late-attach fragment contract is malformed"
        )
    diagnostic_records = _mapping(
        raw_diagnostics.get("record_types"),
        "raw_only_diagnostics.record_types",
    )
    if not diagnostic_records:
        raise FirmwareHostContractError(
            "raw-only diagnostics must declare at least one record type"
        )
    for record_type, raw_diagnostic in diagnostic_records.items():
        _string(record_type, "raw-only diagnostic record type")
        diagnostic = _mapping(
            raw_diagnostic,
            f"raw_only_diagnostics.record_types.{record_type}",
        )
        forms = diagnostic.get("forms")
        if not isinstance(forms, list) or not forms:
            raise FirmwareHostContractError(
                f"raw-only diagnostic {record_type} must declare forms"
            )
        seen_forms: set[tuple[str, ...]] = set()
        for index, raw_form in enumerate(forms):
            label = (
                f"raw_only_diagnostics.record_types.{record_type}.forms[{index}]"
            )
            form = _mapping(raw_form, label)
            fields = _strings(form.get("fields"), f"{label}.fields")
            if fields[0] != "v" or fields in seen_forms:
                raise FirmwareHostContractError(
                    f"{label} must begin with v and have a unique layout"
                )
            seen_forms.add(fields)
            groups = _mapping(
                form.get("field_wire_types"),
                f"{label}.field_wire_types",
            )
            unknown_types = set(groups) - set(wire_types)
            if unknown_types:
                raise FirmwareHostContractError(
                    f"{label} uses unknown wire types: {sorted(unknown_types)}"
                )
            typed_fields = [
                field
                for wire_type, raw_fields in groups.items()
                for field in _strings(raw_fields, f"{label}.{wire_type}")
            ]
            duplicates = sorted(
                {
                    field
                    for field in typed_fields
                    if typed_fields.count(field) > 1
                }
            )
            if duplicates or set(typed_fields) != set(fields):
                raise FirmwareHostContractError(
                    f"{label} wire types must cover its fields exactly; "
                    f"duplicates={duplicates}, "
                    f"missing={sorted(set(fields) - set(typed_fields))}, "
                    f"extra={sorted(set(typed_fields) - set(fields))}"
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

    field_groups = _mapping(
        root.get("record_field_wire_types"), "record_field_wire_types"
    )
    if set(field_groups) != set(records):
        raise FirmwareHostContractError(
            "record_field_wire_types must cover every current record exactly"
        )
    for name, raw_groups in field_groups.items():
        fields = tuple(records[name]["fields"])
        groups = _mapping(raw_groups, f"record_field_wire_types.{name}")
        unknown_types = set(groups) - set(wire_types)
        if unknown_types:
            raise FirmwareHostContractError(
                f"record_field_wire_types.{name} uses unknown wire types: "
                f"{sorted(unknown_types)}"
            )
        seen_fields: list[str] = []
        for wire_type, raw_fields in groups.items():
            typed_fields = _strings(
                raw_fields, f"record_field_wire_types.{name}.{wire_type}"
            )
            seen_fields.extend(typed_fields)
        duplicates = sorted(
            {field for field in seen_fields if seen_fields.count(field) > 1}
        )
        if duplicates:
            raise FirmwareHostContractError(
                f"record_field_wire_types.{name} duplicates fields: {duplicates}"
            )
        if set(seen_fields) != set(fields):
            missing = sorted(set(fields) - set(seen_fields))
            extra = sorted(set(seen_fields) - set(fields))
            raise FirmwareHostContractError(
                f"record_field_wire_types.{name} differs from its layout; "
                f"missing={missing}, extra={extra}"
            )
        field_to_type = {
            field: wire_type
            for wire_type, typed_fields in groups.items()
            for field in typed_fields
        }
        if field_to_type["record_type"] != "record_type":
            raise FirmwareHostContractError(
                f"record_field_wire_types.{name}.record_type must use record_type"
            )
        if field_to_type["schema_version"] != "schema_version":
            raise FirmwareHostContractError(
                f"record_field_wire_types.{name}.schema_version must use schema_version"
            )

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
    envelope_value_types = _mapping(
        snapshot.get("envelope_value_wire_types"),
        f"status_snapshots.{snapshot_name}.envelope_value_wire_types",
    )
    if set(envelope_value_types) != set(envelope):
        raise FirmwareHostContractError(
            f"status_snapshots.{snapshot_name}.envelope_value_wire_types must "
            "cover begin, contract, and complete exactly"
        )
    if any(value not in wire_types for value in envelope_value_types.values()):
        raise FirmwareHostContractError(
            f"status_snapshots.{snapshot_name}.envelope_value_wire_types uses "
            "an unknown wire type"
        )
    value_groups = _mapping(
        snapshot.get("value_wire_types"),
        f"status_snapshots.{snapshot_name}.value_wire_types",
    )
    unknown_types = set(value_groups) - set(wire_types)
    if unknown_types:
        raise FirmwareHostContractError(
            f"status_snapshots.{snapshot_name}.value_wire_types uses unknown "
            f"wire types: {sorted(unknown_types)}"
        )
    value_fields: list[str] = []
    for wire_type, raw_fields in value_groups.items():
        value_fields.extend(
            _strings(
                raw_fields,
                f"status_snapshots.{snapshot_name}.value_wire_types.{wire_type}",
            )
        )
    duplicates = sorted(
        {field for field in value_fields if value_fields.count(field) > 1}
    )
    if duplicates or set(value_fields) != set(snapshot["keys"]):
        raise FirmwareHostContractError(
            f"status_snapshots.{snapshot_name}.value_wire_types must cover "
            f"every key exactly; duplicates={duplicates}, "
            f"missing={sorted(set(snapshot['keys']) - set(value_fields))}, "
            f"extra={sorted(set(value_fields) - set(snapshot['keys']))}"
        )

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
    metadata_transition = evidence.get("metadata_transition")
    queue_depth = evidence.get("queue_depth")
    if type(metadata_transition) is not int or metadata_transition != 1:
        raise FirmwareHostContractError("metadata transition frontier must be one frame")
    if type(queue_depth) is not int or queue_depth < 1 or queue_depth & (queue_depth - 1):
        raise FirmwareHostContractError("evidence queue depth must be a power of two")
    expected_metadata_response = metadata_transition + expected_response
    if (
        evidence.get("request_frontier") != expected_request
        or evidence.get("response_frontier") != expected_response
        or evidence.get("request_fail_frontier") != expected_fail
        or evidence.get("metadata_response_frontier") != expected_metadata_response
        or queue_depth
        < max(expected_request, expected_response, expected_fail, expected_metadata_response)
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
    for relation in relations:
        if relation["kind"] == "bounded_modular_lag":
            modulus = relation.get("modulus")
            maximum = relation.get("maximum_lag_ticks")
            if (
                type(modulus) is not int or modulus != 1 << 32
                or type(maximum) is not int or not 0 <= maximum < modulus // 2
                or relation.get("source_domain") != "rp2040_monotonic_us32"
                or relation.get("target_domain") != "rp2040_monotonic_us64"
            ):
                raise FirmwareHostContractError(
                    "bounded modular lag must declare an unambiguous native-to-extended domain"
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
WIRE_TYPES = CONTRACT["wire_types"]
RAW_ONLY_DIAGNOSTICS = CONTRACT["raw_only_diagnostics"]
RAW_ONLY_DIAGNOSTIC_RECORD_TYPES = frozenset(
    RAW_ONLY_DIAGNOSTICS["record_types"]
)
RAW_ONLY_DIAGNOSTIC_FORMS = {
    record_type: tuple(
        (
            tuple(form["fields"]),
            {
                field: wire_type
                for wire_type, fields in form["field_wire_types"].items()
                for field in fields
            },
        )
        for form in diagnostic["forms"]
    )
    for record_type, diagnostic in RAW_ONLY_DIAGNOSTICS[
        "record_types"
    ].items()
}
RECORD_FIELD_WIRE_TYPES = {
    name: {
        field: wire_type
        for wire_type, fields in CONTRACT["record_field_wire_types"][name].items()
        for field in fields
    }
    for name in RECORDS
}
ACTIVE_STATUS_CONTRACT_ID, ACTIVE_STATUS = next(
    iter(CONTRACT["status_snapshots"].items())
)
ACTIVE_STATUS_KEYS = tuple(ACTIVE_STATUS["keys"])
ACTIVE_STATUS_COMPONENT = str(ACTIVE_STATUS["component"])
ACTIVE_STATUS_ENVELOPE = dict(ACTIVE_STATUS["envelope"])
ACTIVE_STATUS_VALUE_WIRE_TYPES = {
    field: wire_type
    for wire_type, fields in ACTIVE_STATUS["value_wire_types"].items()
    for field in fields
}
ACTIVE_STATUS_VALUE_WIRE_TYPES.update(
    {
        ACTIVE_STATUS_ENVELOPE[role]: wire_type
        for role, wire_type in ACTIVE_STATUS["envelope_value_wire_types"].items()
    }
)
SIMPLE_COMMANDS = frozenset(CONTRACT["commands"]["simple"])
COMMAND_FORMS = CONTRACT["commands"]["forms"]
FRONTIERS = CONTRACT["frontiers"]
RELATIONS = {item["id"]: item for item in CONTRACT["relations"]}


_UNSIGNED_INTEGER = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_SIGNED_INTEGER = re.compile(r"(?:0|-?[1-9][0-9]*)\Z")
_FIXED_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_LOWER_HEX = re.compile(r"[0-9a-f]+\Z")
_ESCAPED_BYTES = frozenset({"25", "2C", "22", "0D", "0A"})


def _atom_error(value: str, *, optional: bool) -> str | None:
    if not value:
        return None if optional else "must be a non-empty escaped atom"
    if any(ord(character) > 0x7F for character in value):
        return "must contain only ASCII wire bytes"
    if any(character in ',"\r\n' for character in value):
        return "must use unquoted CSV percent escaping"
    index = 0
    while index < len(value):
        if value[index] != "%":
            index += 1
            continue
        escape = value[index + 1 : index + 3]
        if len(escape) != 2 or escape not in _ESCAPED_BYTES:
            return "contains an invalid or non-canonical percent escape"
        index += 3
    return None


def _wire_type_value_error(
    type_name: str, value: str, *, contract_name: str | None = None
) -> str | None:
    wire_type = WIRE_TYPES[type_name]
    kind = wire_type["kind"]
    if kind == "optional":
        if value == "":
            return None
        wire_type = WIRE_TYPES[str(wire_type["base"])]
        kind = wire_type["kind"]
    if kind == "literal_or":
        if value == wire_type["literal"]:
            return None
        return _wire_type_value_error(str(wire_type["base"]), value)

    if kind == "record_type":
        if contract_name is None:
            raise FirmwareHostContractError(
                "record_type validation requires a record contract"
            )
        if value not in RECORD_TYPES[contract_name]:
            return f"must be one of {sorted(RECORD_TYPES[contract_name])}"
        return None
    if kind == "schema_version":
        if contract_name is None:
            raise FirmwareHostContractError(
                "schema_version validation requires a record contract"
            )
        expected = str(RECORD_SCHEMA_VERSIONS[contract_name])
        return None if value == expected else f"must equal {expected}"
    if kind == "integer":
        signed = bool(wire_type["signed"])
        pattern = _SIGNED_INTEGER if signed else _UNSIGNED_INTEGER
        if pattern.fullmatch(value) is None:
            return "must use canonical decimal integer encoding"
        parsed = int(value, 10)
        if not int(wire_type["minimum"]) <= parsed <= int(wire_type["maximum"]):
            return (
                f"must be in {wire_type['minimum']}..{wire_type['maximum']}"
            )
        return None
    if kind == "finite_decimal":
        optional = bool(wire_type.get("optional", False))
        if value == "":
            return None if optional else "must not be empty"
        if _FIXED_DECIMAL.fullmatch(value) is None:
            return "must use finite fixed-decimal encoding"
        try:
            parsed = float(value)
        except ValueError:
            return "must be an IEEE-754 binary64 decimal"
        return None if math.isfinite(parsed) else "must fit finite IEEE-754 binary64"
    if kind == "hex_integer":
        prefix = str(wire_type["prefix"])
        digits = int(wire_type["digits"])
        alphabet = "[0-9A-F]" if wire_type.get("uppercase") is True else "[0-9a-f]"
        if re.fullmatch(re.escape(prefix) + alphabet + f"{{{digits}}}", value) is None:
            return (
                f"must use {prefix} followed by exactly {digits} "
                f"{'uppercase' if wire_type.get('uppercase') is True else 'lowercase'} "
                "hexadecimal digits"
            )
        parsed = int(value[len(prefix) :], 16)
        if not int(wire_type["minimum"]) <= parsed <= int(wire_type["maximum"]):
            return (
                f"must be in {wire_type['minimum']}..{wire_type['maximum']}"
            )
        return None
    if kind == "enum":
        values = tuple(str(item) for item in wire_type["values"])
        return None if value in values else f"must be one of {list(values)}"
    if kind == "escaped_atom":
        return _atom_error(value, optional=bool(wire_type.get("optional", False)))
    if kind == "lower_hex":
        length = int(wire_type["length"])
        if len(value) != length or _LOWER_HEX.fullmatch(value) is None:
            return f"must be exactly {length} lowercase hexadecimal characters"
        return None
    if kind == "lower_hex_or_literal":
        if value == wire_type["literal"]:
            return None
        length = int(wire_type["length"])
        if len(value) != length or _LOWER_HEX.fullmatch(value) is None:
            return (
                f"must be {wire_type['literal']!r} or exactly {length} "
                "lowercase hexadecimal characters"
            )
        return None
    raise FirmwareHostContractError(f"wire type {type_name!r} is not executable")


def wire_value_error(
    contract_name: str, field_name: str, value: str
) -> str | None:
    """Return the exact current-wire error for one already-split CSV field."""

    try:
        type_name = RECORD_FIELD_WIRE_TYPES[contract_name][field_name]
    except KeyError as exc:
        raise FirmwareHostContractError(
            f"unknown current record field {contract_name}.{field_name}"
        ) from exc
    return _wire_type_value_error(
        type_name, value, contract_name=contract_name
    )


def active_status_value_error(key: str, value: str) -> str | None:
    """Validate one value inside the exact current ACTIVE snapshot vocabulary."""

    try:
        type_name = ACTIVE_STATUS_VALUE_WIRE_TYPES[key]
    except KeyError as exc:
        raise FirmwareHostContractError(
            f"unknown current ACTIVE status key {key!r}"
        ) from exc
    return _wire_type_value_error(type_name, value)


def validate_record_wire_values(
    contract_name: str, values: tuple[str, ...] | list[str]
) -> tuple[str, ...]:
    """Validate field count, canonical encodings, widths, and signedness."""

    fields = RECORD_FIELDS[contract_name]
    if len(values) != len(fields):
        return (f"column count {len(values)} does not match {len(fields)}",)
    errors: list[str] = []
    for field_name, value in zip(fields, values, strict=True):
        error = wire_value_error(contract_name, field_name, value)
        if error is not None:
            errors.append(f"{contract_name}.{field_name} {error}; got {value!r}")
    return tuple(errors)


def validate_raw_only_diagnostic(values: list[str]) -> tuple[str, ...]:
    """Validate one documented zero-authority boot diagnostic line."""

    if not values or values[0] not in RAW_ONLY_DIAGNOSTIC_RECORD_TYPES:
        return ("unknown raw-only diagnostic record type",)
    parsed_fields: list[tuple[str, str]] = []
    for token in values[1:]:
        field_name, separator, value = token.partition("=")
        if not separator or not field_name or value == "":
            return (
                f"{values[0]} fields must use non-empty name=value tokens",
            )
        parsed_fields.append((field_name, value))
    field_names = tuple(field for field, _ in parsed_fields)
    matching = [
        field_types
        for fields, field_types in RAW_ONLY_DIAGNOSTIC_FORMS[values[0]]
        if fields == field_names
    ]
    if not matching:
        return (f"{values[0]} field layout is not declared",)
    field_types = matching[0]
    errors: list[str] = []
    for field_name, value in parsed_fields:
        error = _wire_type_value_error(field_types[field_name], value)
        if error is not None:
            errors.append(
                f"{values[0]}.{field_name} {error}; got {value!r}"
            )
    return tuple(errors)


def is_admissible_late_attach_fragment(
    value: str,
    *,
    recognized_protocol_line_seen: bool,
    prior_fragment_seen: bool,
) -> bool:
    """Admit one bounded uninterpreted line fragment at carrier attachment."""

    if recognized_protocol_line_seen or prior_fragment_seen:
        return False
    contract = RAW_ONLY_DIAGNOSTICS["late_attach_fragment"]
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        return False
    return bool(encoded) and len(encoded) <= int(contract["maximum_bytes"])


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


def bounded_modular_lag_matches(
    relation_id: str,
    *,
    source: int,
    source_domain: str,
    target: int,
    target_domain: str,
) -> bool:
    relation = RELATIONS[relation_id]
    if relation.get("kind") != "bounded_modular_lag":
        raise FirmwareHostContractError(
            f"{relation_id} is not a bounded_modular_lag relation"
        )
    modulus = int(relation["modulus"])
    lag = (target % modulus - source) % modulus
    return (
        source_domain == relation.get("source_domain")
        and target_domain == relation.get("target_domain")
        and 0 <= source < modulus
        and 0 <= target < 1 << 64
        and lag <= int(relation["maximum_lag_ticks"])
        and target >= lag
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
            f"#define OTIS_EVIDENCE_METADATA_TRANSITION_COUNT {evidence['metadata_transition']}u",
            f"#define OTIS_EVIDENCE_METADATA_RESPONSE_FRONTIER {evidence['metadata_response_frontier']}u",
            f"#define OTIS_EVIDENCE_REQUEST_FAIL_FRONTIER {evidence['request_fail_frontier']}u",
            f"#define OTIS_EVIDENCE_QUEUE_DEPTH {evidence['queue_depth']}u",
            f"#define OTIS_ESTIMATE_TO_DECISION_MAXIMUM_LAG_TICKS {RELATIONS['estimate_capture_precedes_operational_decision']['maximum_lag_ticks']}ull",
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
