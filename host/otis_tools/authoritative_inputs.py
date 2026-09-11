"""Freeze and validate the complete current profile and schema input set."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_PROFILE = "profiles/discipline/adaptive_hybrid_regulation_v1.json"
CONTRACT = "otis_adaptive_hybrid_authoritative_inputs_v2"
PROFILE_SCHEMA_BINDINGS = {
    ROOT_PROFILE: "schemas/adaptive_hybrid_regulation_v1.schema.json",
    "profiles/discipline/response_classification_v1.json": (
        "schemas/response_classification_v1.schema.json"
    ),
    "profiles/estimators/pps_gated_frequency_estimator_v1.json": (
        "schemas/pps_gated_frequency_estimator_v1.schema.json"
    ),
    "profiles/estimators/relative_phase_estimator_v1.json": (
        "schemas/relative_phase_estimator_v1.schema.json"
    ),
    "profiles/plant_models/pps_gated_oscillator_plant_v1.json": (
        "schemas/plant_model_v1.schema.json"
    ),
}
REFERENCE_ACCEPTANCE_POLICY_PATH = "data_contracts/reference_acceptance_policy_v1.json"
CURRENT_CONTRACT_PATHS = frozenset({REFERENCE_ACCEPTANCE_POLICY_PATH})
CURRENT_PROFILE_PATHS = frozenset(PROFILE_SCHEMA_BINDINGS)
CURRENT_SCHEMA_PATHS = frozenset(
    {
        "schemas/adaptive_hybrid_regulation_v1.schema.json",
        "schemas/adaptive_hybrid_setup_authority_v1.schema.json",
        "schemas/plant_model_v1.schema.json",
        "schemas/pps_gated_frequency_estimator_v1.schema.json",
        "schemas/relative_phase_estimator_v1.schema.json",
        "schemas/response_classification_v1.schema.json",
        "schemas/run_evidence_v1.schema.json",
    }
)


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


@lru_cache(maxsize=32)
def _check_schema_bytes(canonical_schema: str) -> None:
    """Reuse only schema syntax validation for identical immutable bytes.

    Content and set hashes, closure, and profile-instance validation still run
    at every authority boundary. A modified schema is a different cache key;
    invalid schemas raise and are not cached. No mutable document is cached.
    """
    Draft202012Validator.check_schema(json.loads(canonical_schema))


def _check_schema(schema: dict[str, Any]) -> None:
    _check_schema_bytes(
        json.dumps(schema, sort_keys=True, separators=(",", ":"), allow_nan=False)
    )


def _safe_repository_path(repo_root: Path, relative: str, prefix: str) -> Path:
    relative_path = Path(relative)
    if (
        relative_path.is_absolute()
        or not relative_path.parts
        or relative_path.parts[0] != prefix
        or any(part in {"", ".", ".."} for part in relative_path.parts)
    ):
        raise ValueError(f"unsafe authoritative input path: {relative!r}")
    path = repo_root / relative_path
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"authoritative input is unavailable: {relative}") from error
    if resolved != path.absolute() or not resolved.is_relative_to(repo_root.resolve()):
        raise ValueError(f"authoritative input traverses a symbolic link: {relative}")
    if not resolved.is_file():
        raise ValueError(f"authoritative input is not a regular file: {relative}")
    return resolved


def _object_bytes(path: Path, relative: str) -> tuple[bytes, dict[str, Any]]:
    data = path.read_bytes()
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"authoritative input is not valid JSON: {relative}") from error
    if not isinstance(value, dict):
        raise ValueError(f"authoritative input root is not an object: {relative}")
    return data, value


def _profile_references(value: object) -> set[str]:
    references: set[str] = set()

    def walk(child: object) -> None:
        if isinstance(child, dict):
            for item in child.values():
                walk(item)
        elif isinstance(child, list):
            for item in child:
                walk(item)
        elif (
            isinstance(child, str)
            and child.startswith("profiles/")
            and child.endswith(".json")
        ):
            references.add(child)

    walk(value)
    return references


def _entry(relative: str, data: bytes) -> dict[str, Any]:
    return {
        "path": relative,
        "sha256": sha256(data).hexdigest(),
        "size_bytes": len(data),
        "content": data.decode("utf-8"),
    }


def collect_authoritative_inputs(
    *, repo_root: Path = REPO_ROOT, root_profile: str = ROOT_PROFILE
) -> dict[str, Any]:
    """Collect the root profile's transitive closure and every current schema."""

    pending = [root_profile]
    profile_entries: dict[str, dict[str, Any]] = {}
    while pending:
        relative = pending.pop(0)
        if relative in profile_entries:
            continue
        path = _safe_repository_path(repo_root, relative, "profiles")
        data, value = _object_bytes(path, relative)
        profile_entries[relative] = _entry(relative, data)
        pending.extend(sorted(_profile_references(value) - profile_entries.keys()))
    repository_profiles = {
        path.relative_to(repo_root).as_posix()
        for path in (repo_root / "profiles").rglob("*.json")
        if path.is_file()
    }
    if set(profile_entries) != repository_profiles:
        raise ValueError(
            "repository profile set is not the exact transitive authoritative closure"
        )

    schemas_root = repo_root / "schemas"
    schema_entries: list[dict[str, Any]] = []
    for path in sorted(schemas_root.glob("*.schema.json")):
        relative = path.relative_to(repo_root).as_posix()
        resolved = _safe_repository_path(repo_root, relative, "schemas")
        data, _ = _object_bytes(resolved, relative)
        schema_entries.append(_entry(relative, data))
    if not schema_entries:
        raise ValueError("authoritative schema set is empty")

    unsigned: dict[str, Any] = {
        "contract": CONTRACT,
        "root_profile": root_profile,
        "profiles": [profile_entries[path] for path in sorted(profile_entries)],
        "schemas": schema_entries,
        "contracts": [_entry(relative, _safe_repository_path(repo_root, relative, "data_contracts").read_bytes())
                      for relative in sorted(CURRENT_CONTRACT_PATHS)],
        "profile_schema_bindings": dict(PROFILE_SCHEMA_BINDINGS),
    }
    return {**unsigned, "set_sha256": _canonical_sha256(unsigned)}


def _validate_entries(
    value: object, *, prefix: str
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"frozen {prefix} input set is empty or malformed")
    entries: dict[str, dict[str, Any]] = {}
    documents: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "path", "sha256", "size_bytes", "content"
        }:
            raise ValueError(f"frozen {prefix} input entry is malformed")
        relative = item.get("path")
        content = item.get("content")
        if not isinstance(relative, str) or not isinstance(content, str):
            raise ValueError(f"frozen {prefix} input identity is malformed")
        relative_path = Path(relative)
        if (
            relative_path.is_absolute()
            or not relative_path.parts
            or relative_path.parts[0] != prefix
            or any(part in {"", ".", ".."} for part in relative_path.parts)
            or relative in entries
        ):
            raise ValueError(f"frozen {prefix} input path is unsafe or duplicated")
        data = content.encode("utf-8")
        if len(data) != item.get("size_bytes") or sha256(data).hexdigest() != item.get(
            "sha256"
        ):
            raise ValueError(f"frozen authoritative input bytes differ: {relative}")
        try:
            document = json.loads(content)
        except json.JSONDecodeError as error:
            raise ValueError(f"frozen authoritative input is invalid JSON: {relative}") from error
        if not isinstance(document, dict):
            raise ValueError(f"frozen authoritative input is not an object: {relative}")
        entries[relative] = item
        documents[relative] = document
    if list(entries) != sorted(entries):
        raise ValueError(f"frozen {prefix} input entries are not canonically ordered")
    return entries, documents


def _validate_input_set(value: object) -> dict[str, dict[str, Any]]:
    """Validate embedded bytes, transitive closure, schemas, and their set hash."""

    if not isinstance(value, dict):
        raise ValueError("frozen authoritative inputs are malformed")
    claimed = value.get("set_sha256")
    unsigned = {key: item for key, item in value.items() if key != "set_sha256"}
    if (
        set(value)
        != {
            "contract", "root_profile", "profiles", "schemas", "contracts",
            "profile_schema_bindings", "set_sha256",
        }
        or value.get("contract") != CONTRACT
        or value.get("root_profile") != ROOT_PROFILE
        or claimed != _canonical_sha256(unsigned)
    ):
        raise ValueError("frozen authoritative input-set identity differs")

    profile_entries, profile_documents = _validate_entries(
        value.get("profiles"), prefix="profiles"
    )
    if set(profile_entries) != CURRENT_PROFILE_PATHS:
        raise ValueError("frozen profile set is not the exact current profile set")
    schema_entries, schema_documents = _validate_entries(
        value.get("schemas"), prefix="schemas"
    )
    if set(schema_entries) != CURRENT_SCHEMA_PATHS:
        raise ValueError("frozen schema set is not the exact current schema set")
    contract_entries, contract_documents = _validate_entries(
        value.get("contracts"), prefix="data_contracts"
    )
    if set(contract_entries) != CURRENT_CONTRACT_PATHS:
        raise ValueError("frozen contract set differs from the current instrument")
    policy_entry = contract_entries[REFERENCE_ACCEPTANCE_POLICY_PATH]
    for path in ("profiles/estimators/pps_gated_frequency_estimator_v1.json",
                 "profiles/estimators/relative_phase_estimator_v1.json"):
        if (profile_documents[path].get("reference_acceptance_policy_ref") != REFERENCE_ACCEPTANCE_POLICY_PATH
            or profile_documents[path].get("reference_acceptance_policy_sha256") != policy_entry["sha256"]):
            raise ValueError("estimator acceptance policy binding differs from retained policy bytes")
    discovered = {ROOT_PROFILE}
    pending = [ROOT_PROFILE]
    while pending:
        relative = pending.pop(0)
        document = profile_documents.get(relative)
        if document is None:
            raise ValueError(f"frozen profile closure omits {relative}")
        for reference in sorted(_profile_references(document)):
            if reference not in discovered:
                discovered.add(reference)
                pending.append(reference)
    if discovered != set(profile_entries):
        raise ValueError("frozen profile set is not the exact transitive closure")

    bindings = value.get("profile_schema_bindings")
    if bindings != PROFILE_SCHEMA_BINDINGS:
        raise ValueError("frozen profile/schema bindings differ")
    for profile_path, schema_path in PROFILE_SCHEMA_BINDINGS.items():
        if profile_path not in profile_documents or schema_path not in schema_documents:
            raise ValueError("frozen profile/schema binding is unavailable")
        schema = schema_documents[schema_path]
        _check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(profile_documents[profile_path]),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            raise ValueError(
                f"frozen profile fails {schema_path}: {errors[0].message}"
            )
    for schema in schema_documents.values():
        _check_schema(schema)
    return {**profile_documents, **schema_documents, **contract_documents}


@dataclass(frozen=True, slots=True)
class _ValidatedEntry:
    group: str
    path: str
    sha256: str
    size_bytes: int
    content: str


@dataclass(frozen=True, slots=True, init=False)
class ValidatedAuthoritativeInputs:
    """One validated immutable input snapshot, independent of caller mutation.

    Construction is the raw-data boundary. Consumers read detached documents
    and bindings from these exact bytes without repeating validation or
    consulting the checkout. A new raw payload requires a new instance.
    """

    _encoded: str
    _entries: tuple[_ValidatedEntry, ...]
    set_sha256: str

    def __init__(self, value: object) -> None:
        if not isinstance(value, dict):
            raise ValueError("frozen authoritative inputs are malformed")
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        snapshot = json.loads(encoded)
        _validate_input_set(snapshot)
        object.__setattr__(self, "_encoded", encoded)
        object.__setattr__(self, "set_sha256", snapshot["set_sha256"])
        object.__setattr__(self, "_entries", tuple(
            _ValidatedEntry(group=group, **entry)
            for group in ("profiles", "schemas", "contracts")
            for entry in snapshot[group]
        ))

    def _entry(self, relative: str) -> _ValidatedEntry:
        for entry in self._entries:
            if entry.path == relative:
                return entry
        raise ValueError(f"frozen authoritative input is unavailable: {relative}")

    def document(self, relative: str) -> dict[str, Any]:
        return json.loads(self._entry(relative).content)

    def binding(self, relative: str) -> dict[str, Any]:
        entry = self._entry(relative)
        return {"path": entry.path, "sha256": entry.sha256, "size_bytes": entry.size_bytes}

    def as_dict(self) -> dict[str, Any]:
        return json.loads(self._encoded)

    def matches(self, value: object) -> bool:
        try:
            return self._encoded == json.dumps(
                value, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        except (TypeError, ValueError):
            return False

    def summary(self) -> dict[str, Any]:
        value = self.as_dict()
        return {
            "contract": value["contract"],
            "root_profile": value["root_profile"],
            **{group: [self.binding(entry.path) for entry in self._entries if entry.group == group]
               for group in ("profiles", "schemas", "contracts")},
            "profile_schema_bindings": value["profile_schema_bindings"],
            "set_sha256": self.set_sha256,
        }


def validate_authoritative_inputs(value: object) -> ValidatedAuthoritativeInputs:
    return ValidatedAuthoritativeInputs(value)


def transaction_identities_from_bundle(
    bundle: dict[str, Any], *, inputs: ValidatedAuthoritativeInputs | None = None,
) -> dict[str, str]:
    if inputs is None:
        inputs = validate_authoritative_inputs(bundle.get("authoritative_inputs"))
    elif not inputs.matches(bundle.get("authoritative_inputs")):
        raise ValueError("transaction input context differs from bundle bytes")
    policy = inputs.document(ROOT_PROFILE)
    policy_sha256 = str(inputs.binding(ROOT_PROFILE)["sha256"])
    bundle_policy = bundle.get("policy")
    if not isinstance(bundle_policy, dict) or bundle_policy.get("policy_sha256") != policy_sha256:
        raise ValueError("transaction policy identity differs from frozen root policy")
    bindings = policy.get("bindings", {})
    if not isinstance(bindings, dict):
        raise ValueError("adaptive-hybrid policy bindings are unavailable")

    def digest(name: str) -> str:
        relative = bindings.get(name)
        if not isinstance(relative, str):
            raise ValueError(f"policy binding {name!r} is unavailable")
        return str(inputs.binding(relative)["sha256"])

    return {
        "estimator_sha256": digest("frequency_estimator"),
        "model_sha256": digest("plant_model"),
        "active_policy_sha256": policy_sha256,
        "response_policy_sha256": digest("response_classification"),
        "numerical_policy_sha256": policy_sha256,
    }
