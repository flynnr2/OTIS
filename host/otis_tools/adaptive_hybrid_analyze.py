"""Strict offline replay and seal for one adaptive-hybrid run.

The analyzer is read-only with respect to captured evidence.  It validates the
current manifest, exact lifecycle records, D14/D8 measurement reconstruction,
controller transactions, and maintenance-state replay before publishing a
content-addressed seal.  D10 remains optional external-event evidence and is
never consulted by a control or terminal predicate.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .adaptive_hybrid_activation import validate_frozen_run_manifest
from .active_status_live_state import LIVE_STATE_PATH
from .adaptive_hybrid_contract import (
    INHIBITED_ZERO_WRITE,
    AdaptiveHybridProgramme,
    programme_from_mapping,
    validate_bench_attempt_envelope,
)
from .adaptive_hybrid_evidence import replay_adaptive_hybrid_maintenance_history
from .adaptive_hybrid_policy import AdaptiveHybridPolicy, policy_from_mapping
from .adaptive_hybrid_replay import _capsules_exact, _measurement_replay, _response_replay
from .adaptive_hybrid_transactions import CampaignSpec, _read_csv, validate_transaction_history
from .contracts import CsvValidationContext, validate_csv
from .authoritative_inputs import (
    ROOT_PROFILE,
    authoritative_binding,
    authoritative_document,
    validate_authoritative_inputs,
)
from .evidence import EVIDENCE_MANIFEST, validate_evidence_snapshot
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, COMPLETE_MARKER, RunManifest


TOOL_ID = "adaptive_hybrid_analyze_v1"
SEAL_TYPE = "adaptive_hybrid_physical_seal_v1"
DEFAULT_SEAL = Path("reports/adaptive_hybrid_physical_seal_v1.json")
SUPERVISOR_STATE = Path("reports/adaptive_hybrid_supervisor_state.json")
SUPERVISOR_EVENTS = Path("reports/adaptive_hybrid_supervisor_events.jsonl")
HOST_REVIEW_RESOLUTION = Path(
    "reports/adaptive_hybrid_hybrid_host_review_resolution_v1.json"
)
CAPTURE_STATE = Path("reports/capture_device_state.json")
CAPTURE_CLOSURE = Path("reports/capture_segment_closure_v1.json")
ACTIVE_TRANSACTIONS = Path("csv/active_transactions_v2.csv")
DAC_STEPS = Path("csv/dac_steps.csv")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain an object")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path} contains a non-object record")
            rows.append(value)
    return rows


def _explicit_utc(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _sha256_text(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _normalize_terminal(
    terminal: object,
    programme: AdaptiveHybridProgramme,
    *,
    bench_attempt: object = None,
) -> tuple[bool, str | None, str | None, str | None]:
    """Return exactness, scientific decision, result, and detailed reason."""

    if not isinstance(terminal, dict):
        return False, None, None, None
    result = terminal.get("result")
    reason = terminal.get("reason")
    primary = terminal.get("primary_decision")
    if not isinstance(reason, str) or not reason:
        return False, None, result if isinstance(result, str) else None, None
    validated_bench_attempt = None
    if bench_attempt is not None:
        if not isinstance(bench_attempt, dict):
            return False, None, result if isinstance(result, str) else None, reason
        try:
            validated_bench_attempt = validate_bench_attempt_envelope(
                bench_attempt
            )
        except ValueError:
            return False, None, result if isinstance(result, str) else None, reason
    if result == "healthy_stop":
        if validated_bench_attempt is not None:
            bench_success = validated_bench_attempt.as_dict()[
                "terminal_semantics"
            ]["success_terminal"]
            static_code = terminal.get("last_confirmed_code")
            static_code_exact = (
                static_code is None
                if validated_bench_attempt.purpose == INHIBITED_ZERO_WRITE
                else type(static_code) is int
                and programme.minimum_code <= static_code <= programme.maximum_code
            )
            exact = (
                reason == bench_success
                and terminal.get("preliminary_decision")
                in programme.healthy_preliminary_decisions
                and primary is None
                and static_code_exact
            )
            return exact, bench_success if exact else None, result, reason
        exact = (
            reason == programme.qualified_endpoint_reason
            and terminal.get("preliminary_decision")
            in programme.healthy_preliminary_decisions
            and primary is None
        )
        return exact, programme.qualified_endpoint_reason if exact else None, result, reason
    if result in {"nonpass", "aborted"}:
        exact = (
            isinstance(primary, str)
            and primary in programme.terminal_decisions
            and primary != programme.qualified_endpoint_reason
        )
        return exact, primary if exact else None, result, reason
    return False, None, result if isinstance(result, str) else None, reason


def _validated_host_review_resolution(
    *,
    run_dir: Path,
    manifest: dict[str, Any],
    bench_attempt: object,
    supervisor_state: dict[str, Any],
    prior_review_seal: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, bool, dict[str, Any] | None]:
    """Consume only the immutable resolution of the exact zero-write hold."""

    retained_terminal = supervisor_state.get("terminal")
    resolution_path = run_dir / HOST_REVIEW_RESOLUTION
    if retained_terminal is not None:
        if resolution_path.exists():
            raise ValueError(
                "host-review resolution contradicts an existing supervisor terminal"
            )
        return retained_terminal if isinstance(retained_terminal, dict) else None, True, None
    if not resolution_path.is_file():
        return None, False, None
    if not isinstance(bench_attempt, dict):
        raise ValueError("host-review resolution lacks an exact bench attempt")
    try:
        validated_bench_attempt = validate_bench_attempt_envelope(bench_attempt)
    except ValueError as exc:
        raise ValueError("host-review resolution bench attempt is not exact") from exc
    if validated_bench_attempt.purpose != INHIBITED_ZERO_WRITE:
        raise ValueError("host-review resolution is limited to inhibited zero-write")

    hold = supervisor_state.get("host_verification_hold")
    if not (
        isinstance(hold, dict)
        and hold.get("source") == "bench_attempt_wall_endpoint_observer"
        and hold.get("error")
        == "zero-write wall endpoint lacks a clear static terminal"
        and hold.get("review_status") == "operator_review_required"
        and hold.get("new_authority") is False
    ):
        raise ValueError("host-review resolution does not preserve the exact original hold")

    resolution = _read_object(resolution_path)
    expected_fields = {
        "schema_version",
        "report_type",
        "recorded_utc",
        "resolution",
        "original_hold_preserved",
        "physical_rerun",
        "device_or_actuator_io",
        "new_authority",
        "absent_artifacts",
        "source_sha256",
        "original_tool_sha256",
        "review_tool_sha256",
        "terminal",
        "resolution_sha256",
    }
    unsigned = {
        key: value
        for key, value in resolution.items()
        if key != "resolution_sha256"
    }
    if (
        set(resolution) != expected_fields
        or resolution.get("schema_version") != 1
        or resolution.get("report_type")
        != "adaptive_hybrid_hybrid_host_review_resolution_v1"
        or resolution.get("resolution")
        != "deterministic_host_endpoint_mismatch_superseded"
        or not _explicit_utc(resolution.get("recorded_utc"))
        or resolution.get("original_hold_preserved") is not True
        or resolution.get("physical_rerun") is not False
        or resolution.get("device_or_actuator_io") is not False
        or resolution.get("new_authority") is not False
        or resolution.get("absent_artifacts")
        != ["reports/adaptive_hybrid_setup_authority_v1.json"]
        or (run_dir / "reports/adaptive_hybrid_setup_authority_v1.json").exists()
        or resolution.get("resolution_sha256") != _canonical_sha256(unsigned)
    ):
        raise ValueError("host-review resolution contract or identity differs")

    source_paths = {
        "supervisor_state": run_dir / SUPERVISOR_STATE,
        "live_status": run_dir / LIVE_STATE_PATH,
        "capture_state": run_dir / CAPTURE_STATE,
        "capture_closure": run_dir / CAPTURE_CLOSURE,
        "active_transactions": run_dir / ACTIVE_TRANSACTIONS,
        "dac_steps": run_dir / DAC_STEPS,
        "completion": run_dir / COMPLETE_MARKER,
    }
    try:
        expected_source_sha256 = {
            key: _sha256_file(path) for key, path in source_paths.items()
        }
    except OSError as exc:
        raise ValueError("host-review resolution source evidence is unavailable") from exc
    if resolution.get("source_sha256") != expected_source_sha256:
        raise ValueError("host-review resolution source evidence changed")

    tool_names = (
        "adaptive_hybrid_supervisor",
        "adaptive_hybrid_run",
        "adaptive_hybrid_analyze",
    )
    tool_bindings = manifest.get("host", {}).get("tool_bindings", {})
    expected_original_tools = {
        name: tool_bindings.get(name, {}).get("sha256") for name in tool_names
    }
    module_root = Path(__file__).resolve().parent
    expected_review_tools = {
        name: _sha256_file(module_root / f"{name}.py") for name in tool_names
    }
    if prior_review_seal is not None:
        retained_review_tools = resolution.get("review_tool_sha256")
        if (
            not isinstance(retained_review_tools, dict)
            or set(retained_review_tools) != set(tool_names)
            or not all(_sha256_text(value) for value in retained_review_tools.values())
            or retained_review_tools.get("adaptive_hybrid_analyze")
            != prior_review_seal.get("tool_sha256")
        ):
            raise ValueError("prior analyzer seal review-tool identity differs")
        expected_review_tools = retained_review_tools
    if (
        any(not isinstance(value, str) for value in expected_original_tools.values())
        or resolution.get("original_tool_sha256") != expected_original_tools
        or resolution.get("review_tool_sha256") != expected_review_tools
    ):
        raise ValueError("host-review resolution tool identity differs")

    resolved_terminal = resolution.get("terminal")
    if not isinstance(resolved_terminal, dict) or set(resolved_terminal) != {
        "result",
        "reason",
        "preliminary_decision",
        "last_confirmed_code",
        "utc",
    }:
        raise ValueError("host-review resolution terminal is malformed")
    if not _explicit_utc(resolved_terminal.get("utc")):
        raise ValueError("host-review resolution terminal time is malformed")
    terminal_exact, _, _, _ = _normalize_terminal(
        resolved_terminal,
        programme_from_mapping(manifest),
        bench_attempt=bench_attempt,
    )
    if not terminal_exact:
        raise ValueError("host-review resolution terminal is not exact")
    identity = {
        "path": str(HOST_REVIEW_RESOLUTION),
        "resolution_sha256": resolution["resolution_sha256"],
        "source_sha256": expected_source_sha256,
    }
    if (
        prior_review_seal is not None
        and prior_review_seal.get("host_review_resolution") != identity
    ):
        raise ValueError("prior analyzer seal review-resolution identity differs")
    return resolved_terminal, True, identity


def _d10_isolated(
    section: dict[str, Any], measurement: dict[str, Any]
) -> bool:
    d10 = section.get("external_event_input", {})
    return (
        d10.get("pin") == "D10"
        and d10.get("authority") == "evidence_only"
        and d10.get("control_eligible") is False
        and d10.get("terminal_eligible") is False
        and measurement.get("D10", {}).get("enters_D14_D8_replay") is not True
    )


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
        suffix=".tmp", delete=False,
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _contract_paths(manifest: RunManifest, contract: str) -> list[Path]:
    return [
        manifest.root / str(item["path"])
        for item in manifest.files
        if item.get("contract") == contract
    ]


def _one_contract(manifest: RunManifest, contract: str) -> Path:
    paths = _contract_paths(manifest, contract)
    if len(paths) != 1:
        raise ValueError(f"expected one {contract} artifact, got {len(paths)}")
    return paths[0]


def require_exact_lifecycle_records(manifest: RunManifest) -> dict[str, Any]:
    """Require the sole complete exact ACT and AHY schema-2 products."""

    results: dict[str, Any] = {
        "time_domain": "rp2040_monotonic_us64",
        "exact": True,
    }
    for label, contract in (
        ("transactions", "active_transactions_v2"),
        ("decisions", "active_hybrid_decisions_v2"),
    ):
        path = _one_contract(manifest, contract)
        validation = validate_csv(
            path,
            CsvValidationContext(
                contract, manifest.known_channels, manifest.known_domains
            ),
        )
        if not validation.ok:
            raise ValueError(
                f"{contract} validation failed: {'; '.join(validation.errors)}"
            )
        results[label] = {
            "contract": contract,
            "path": str(path.relative_to(manifest.root)),
            "row_count": validation.row_count,
            "exact": True,
        }
    return results


def _validate_manifest_csvs(
    manifest: RunManifest, *, expected_policy_sha256: str | None = None
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for item in manifest.files:
        contract = item.get("contract")
        path = manifest.root / str(item.get("path", ""))
        if not isinstance(contract, str) or path.suffix.lower() != ".csv":
            continue
        if not path.is_file() and item.get("optional") is True:
            continue
        record_type = item.get("record_type")
        label = (
            f"{contract}:{record_type}"
            if isinstance(record_type, str)
            else contract
        )
        fail_local = contract == "raw_events_v1" and record_type == "EVT"
        try:
            validation = validate_csv(
                path,
                CsvValidationContext(
                    contract,
                    manifest.known_channels,
                    manifest.known_domains,
                    expected_policy_sha256=expected_policy_sha256,
                ),
            )
            row_count = validation.row_count
            errors = list(validation.errors)
            warnings = list(validation.warnings)
            exact = validation.ok
        except (OSError, UnicodeError, csv.Error) as error:
            if not fail_local:
                raise
            row_count = 0
            errors = [f"fail-local D10 validation error: {type(error).__name__}: {error}"]
            warnings = []
            exact = False
        results[label] = {
            "contract": contract,
            "record_type": record_type,
            "path": str(path.relative_to(manifest.root)),
            "row_count": row_count,
            "errors": errors,
            "warnings": warnings,
            "exact": exact,
            "authority": "fail_local" if fail_local else "authoritative",
        }
    return results


def _authoritative_csvs_exact(results: dict[str, Any]) -> bool:
    authoritative = [
        item for item in results.values() if item.get("authority") == "authoritative"
    ]
    return bool(authoritative) and all(item.get("exact") is True for item in authoritative)


def _source_hashes(manifest: RunManifest) -> dict[str, str]:
    return {
        str(item["path"]): _sha256_file(manifest.root / str(item["path"]))
        for item in manifest.files
        if (manifest.root / str(item.get("path", ""))).is_file()
    }


def replay_current_adaptive_hybrid_records(
    *,
    transactions: list[dict[str, str]],
    decisions: list[dict[str, str]],
    maintenance: list[dict[str, str]],
    spec: CampaignSpec,
    identities: dict[str, str],
    expected_build_identity: str,
    policy: AdaptiveHybridPolicy,
    policy_document: dict[str, Any],
    expected_active_policy_sha256: str,
    estimator_sha256: str,
) -> dict[str, Any]:
    """Replay the current deterministic record consumers without authority.

    This seam deliberately accepts no path, manifest, seal, status Boolean, or
    hardware-authority input.  Callers must establish their own manifest and
    artifact boundary first.  The physical analyzer remains responsible for
    validating the live manifest before it calls this shared replay.
    """

    validate_transaction_history(
        transactions,
        spec,
        identities,
        expected_build_identity,
        dual_core=True,
    )
    replay = replay_adaptive_hybrid_maintenance_history(
        decisions,
        transactions,
        maintenance,
        expected_run_identity=spec.run_identity,
        expected_build_identity=expected_build_identity,
        expected_image_identity=spec.profile,
        expected_active_policy_sha256=expected_active_policy_sha256,
        policy=policy,
        policy_document=policy_document,
        estimator_sha256=estimator_sha256,
    )
    return {
        "transaction_history_exact": True,
        "transaction_row_count": len(transactions),
        "decision_row_count": len(decisions),
        "maintenance_row_count": len(maintenance),
        "maintenance_replay": replay,
    }


def replay_current_adaptive_hybrid_host_consumers(
    manifest: RunManifest,
    *,
    spec: CampaignSpec,
    identities: dict[str, str],
    expected_build_identity: str,
    policy: AdaptiveHybridPolicy,
    policy_document: dict[str, Any],
    expected_active_policy_sha256: str,
    estimator_sha256: str,
    response_policy_document: dict[str, Any],
    programme: AdaptiveHybridProgramme,
) -> dict[str, Any]:
    """Run the current deterministic host-analysis consumers without authority.

    The caller must establish the manifest's stage and activation authority.
    This function independently reads the declared artifacts, supervisor
    records, and evidence snapshot; callers cannot supply their verdicts.  It
    intentionally excludes physical measurement replay and physical-seal
    construction, which a PTY rehearsal cannot establish.
    """

    before_hashes = _source_hashes(manifest)
    snapshot_path = manifest.root / EVIDENCE_MANIFEST
    before_snapshot_sha256 = _sha256_file(snapshot_path)
    csv_results = _validate_manifest_csvs(
        manifest, expected_policy_sha256=expected_active_policy_sha256
    )
    lifecycle = require_exact_lifecycle_records(manifest)
    transactions = _read_csv(_one_contract(manifest, "active_transactions_v2"))
    decisions = _read_csv(_one_contract(manifest, "active_hybrid_decisions_v2"))
    maintenance = _read_csv(
        _one_contract(manifest, "active_hybrid_maintenance_v1")
    )
    record_replay = replay_current_adaptive_hybrid_records(
        transactions=transactions,
        decisions=decisions,
        maintenance=maintenance,
        spec=spec,
        identities=identities,
        expected_build_identity=expected_build_identity,
        policy=policy,
        policy_document=policy_document,
        expected_active_policy_sha256=expected_active_policy_sha256,
        estimator_sha256=estimator_sha256,
    )
    response_exact, responses = _response_replay(
        transactions,
        spec.minimum_code,
        spec.maximum_code,
        response_classification_observational=(
            programme.response_checkpoint_observational
        ),
        response_policy_document=response_policy_document,
    )
    supervisor_state = _read_object(manifest.root / SUPERVISOR_STATE)
    events = _read_jsonl(manifest.root / SUPERVISOR_EVENTS)
    capsules_exact, capsule_hashes = _capsules_exact(
        manifest.root, transactions, events, supervisor_state
    )

    source_hashes = _source_hashes(manifest)
    snapshot_failures, snapshot_warnings = validate_evidence_snapshot(
        manifest.root, manifest
    )
    snapshot_sha256 = _sha256_file(snapshot_path)
    checks = {
        "authoritative_csvs_exact": _authoritative_csvs_exact(csv_results),
        "exact_lifecycle_records": lifecycle.get("exact") is True,
        "transaction_history_exact": (
            record_replay.get("transaction_history_exact") is True
        ),
        "maintenance_replay_exact": (
            record_replay.get("maintenance_replay", {}).get("exact") is True
        ),
        "response_replay_exact": response_exact,
        "transaction_capsules_exact": capsules_exact,
        "evidence_snapshot_exact": (
            not snapshot_failures
            and snapshot_sha256 == before_snapshot_sha256
        ),
        "source_evidence_immutable_during_replay": source_hashes == before_hashes,
    }
    return {
        "exact": all(checks.values()),
        "consumer_scope": {
            "csv_contract_validation": "exercised",
            "D10_optional_event_csv": "fail_local",
            "lifecycle_validation": "exercised",
            "transaction_and_maintenance_replay": "exercised",
            "response_replay": "exercised",
            "transaction_capsule_validation": "exercised",
            "evidence_snapshot_and_source_immutability": "exercised",
            "physical_D14_D8_measurement_replay": "unexercised",
            "physical_terminal_scientific_decision": "unexercised",
            "physical_seal_construction": "unexercised",
        },
        "checks": checks,
        "csv_validation": csv_results,
        "exact_lifecycle_records": lifecycle,
        "record_replay": record_replay,
        "response_replay": responses,
        "transaction_capsule_sha256": capsule_hashes,
        "evidence_snapshot": {
            "path": EVIDENCE_MANIFEST,
            "sha256": snapshot_sha256,
            "failures": snapshot_failures,
            "warnings": snapshot_warnings,
        },
        "source_sha256": source_hashes,
    }


def _inhibited_zero_write_maintenance_replay(
    record_replay: dict[str, Any], *, authority_exact: bool
) -> dict[str, Any]:
    """Make an empty controller history exact only when authority forbids one."""

    replay = record_replay["maintenance_replay"]
    if not authority_exact:
        return replay
    if any(
        record_replay.get(field) != 0
        for field in (
            "transaction_row_count",
            "decision_row_count",
            "maintenance_row_count",
        )
    ):
        return replay
    return {
        **replay,
        "exact": True,
        "applicability": "not_applicable",
        "reason": "inhibited_zero_write_frozen_authority_forbids_controller_records",
        "replay_mode": "not_applicable_no_controller_authority",
        "controller_state_authority": "none",
    }


def _validated_prior_review_seal(
    *,
    run_dir: Path,
    path: Path,
    manifest: dict[str, Any],
    source_sha256: dict[str, str],
) -> dict[str, Any]:
    """Validate the immutable diagnostic seal that authorizes offline replay."""

    prior = _read_object(path)
    claimed = prior.get("seal_sha256")
    unsigned = {key: value for key, value in prior.items() if key != "seal_sha256"}
    checks = prior.get("checks")
    false_checks = (
        sorted(key for key, value in checks.items() if value is not True)
        if isinstance(checks, dict)
        else []
    )
    expected_false_checks = [
        "D14_D8_measurement_replay_exact",
        "maintenance_replay_exact",
    ]
    if (
        prior.get("schema_version") != 1
        or prior.get("seal_type") != SEAL_TYPE
        or prior.get("tool") != TOOL_ID
        or not isinstance(claimed, str)
        or claimed != _canonical_sha256(unsigned)
        or prior.get("status") != "review_required"
        or prior.get("primary_decision") != "operator_review_required"
        or false_checks != expected_false_checks
        or prior.get("source_sha256") != source_sha256
        or prior.get("run_id") != manifest.get("run_id")
        or prior.get("run_identity") != manifest.get("run_identity")
        or prior.get("build_identity")
        != manifest.get("firmware", {}).get("build_identity")
        or prior.get("image_identity") != manifest.get("image_identity")
        or not isinstance(prior.get("host_review_resolution"), dict)
    ):
        raise ValueError(
            "offline analysis supersession requires the exact two-check diagnostic seal"
        )
    if path.resolve() != (run_dir / DEFAULT_SEAL).resolve():
        raise ValueError("prior analyzer seal must be the canonical source-run seal")
    return prior


def analyze(
    run_dir: Path,
    *,
    output_path: Path | None = None,
    prior_review_seal_path: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Replay unchanged current evidence and publish one immutable seal."""

    run_dir = run_dir.resolve()
    if (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise ValueError("adaptive-hybrid capture is still active")
    if not (run_dir / COMPLETE_MARKER).is_file():
        raise ValueError("adaptive-hybrid run is not marked complete")
    manifest_value = validate_frozen_run_manifest(run_dir / "run_manifest.json")
    programme = programme_from_mapping(manifest_value)
    manifest = RunManifest(run_dir, run_dir / "run_manifest.json", manifest_value)
    before_hashes = _source_hashes(manifest)
    prior_review_seal = (
        _validated_prior_review_seal(
            run_dir=run_dir,
            path=prior_review_seal_path.resolve(),
            manifest=manifest_value,
            source_sha256=before_hashes,
        )
        if prior_review_seal_path is not None
        else None
    )

    frozen_inputs = manifest_value.get("authoritative_inputs")
    validate_authoritative_inputs(frozen_inputs)
    policy_document = authoritative_document(frozen_inputs, ROOT_PROFILE)
    policy_binding = authoritative_binding(frozen_inputs, ROOT_PROFILE)
    policy = policy_from_mapping(
        policy_document, policy_sha256=str(policy_binding["sha256"])
    )
    section = manifest_value[programme.manifest_section]
    control = section["automatic_control"]
    build_identity = str(manifest_value["firmware"]["build_identity"])
    bench_attempt = manifest_value.get("bench_attempt", {})
    inhibited_zero_write = bench_attempt.get("purpose") == "inhibited_zero_write"
    if inhibited_zero_write:
        transactions = _read_csv(_one_contract(manifest, "active_transactions_v2"))
        dac_steps = _read_csv(_one_contract(manifest, "dac_steps_v1"))
        inhibited_authority_exact = (
            section["setup"].get("authorized") is False
            and section["setup"].get("code") is None
            and control.get("authorized") is False
            and control.get("maximum_total_applications") == 0
            and bench_attempt.get("authority", {}).get(
                "total_dac_value_write_limit"
            )
            == 0
            and not transactions
            and not dac_steps
        )
        if not inhibited_authority_exact:
            raise ValueError(
                "inhibited zero-write evidence contains authority or a DAC transaction"
            )
        # Replay still needs numerical bounds. Here these are validation-only
        # programme constants: the zero limits and empty records above prevent
        # them from asserting or authorizing an applied code.
        start_code = programme.setup_code
        minimum_code = programme.minimum_code
        maximum_code = programme.maximum_code
        maximum_step = programme.maximum_step_codes
    else:
        inhibited_authority_exact = True
        start_code = int(section["setup"]["code"])
        minimum_code = int(control["minimum_code"])
        maximum_code = int(control["maximum_code"])
        maximum_step = int(control["maximum_step_codes"])
    spec = CampaignSpec(
        campaign=programme.campaign_name,
        profile=str(manifest_value["image_identity"]),
        run_identity=str(manifest_value["run_identity"]),
        start_code=start_code,
        correction_limit=int(control["maximum_total_applications"]),
        cumulative_limit=int(control["maximum_cumulative_movement_codes"]),
        minimum_code=minimum_code,
        maximum_code=maximum_code,
        maximum_step=maximum_step,
    )
    shared_consumers = replay_current_adaptive_hybrid_host_consumers(
        manifest,
        spec=spec,
        identities=manifest_value["transaction_identities"],
        expected_build_identity=build_identity,
        policy=policy,
        policy_document=policy_document,
        expected_active_policy_sha256=policy.policy_sha256,
        estimator_sha256=str(manifest_value["transaction_identities"]["estimator_sha256"]),
        response_policy_document=authoritative_document(
            frozen_inputs,
            str(policy_document["bindings"]["response_classification"]),
        ),
        programme=programme,
    )
    record_replay = shared_consumers["record_replay"]
    maintenance_replay = _inhibited_zero_write_maintenance_replay(
        record_replay,
        authority_exact=inhibited_zero_write and inhibited_authority_exact,
    )
    transactions = _read_csv(_one_contract(manifest, "active_transactions_v2"))
    measurement_exact, measurement, _ = _measurement_replay(manifest, manifest_value)
    responses = shared_consumers["response_replay"]
    supervisor_state = _read_object(run_dir / SUPERVISOR_STATE)
    (
        effective_terminal,
        review_resolution_exact,
        review_resolution_identity,
    ) = _validated_host_review_resolution(
        run_dir=run_dir,
        manifest=manifest_value,
        bench_attempt=bench_attempt,
        supervisor_state=supervisor_state,
        prior_review_seal=prior_review_seal,
    )

    d10_isolated = _d10_isolated(section, measurement)
    checks = {
        "manifest_current": True,
        "csv_contracts_exact": shared_consumers["checks"][
            "authoritative_csvs_exact"
        ],
        "evidence_snapshot_exact": shared_consumers["checks"][
            "evidence_snapshot_exact"
        ],
        "exact_lifecycle_records": shared_consumers["checks"][
            "exact_lifecycle_records"
        ],
        "transactions_exact": shared_consumers["checks"][
            "transaction_history_exact"
        ],
        "maintenance_replay_exact": maintenance_replay.get("exact") is True,
        "D14_D8_measurement_replay_exact": measurement_exact,
        "response_replay_exact": shared_consumers["checks"][
            "response_replay_exact"
        ],
        "transaction_capsules_exact": shared_consumers["checks"][
            "transaction_capsules_exact"
        ],
        "D10_optional_event_isolated": d10_isolated,
        "inhibited_zero_write_authority_exact": inhibited_authority_exact,
        "host_review_resolution_exact": review_resolution_exact,
    }
    (
        terminal_exact,
        scientific_decision,
        terminal_result,
        terminal_reason,
    ) = _normalize_terminal(
        effective_terminal,
        programme,
        bench_attempt=bench_attempt,
    )
    checks["supervisor_terminal_exact"] = terminal_exact
    passed = all(checks.values())
    source_hashes = _source_hashes(manifest)
    if source_hashes != before_hashes:
        raise RuntimeError("source evidence changed during offline analysis")
    tool_hash = _sha256_file(Path(__file__))
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "seal_type": SEAL_TYPE,
        "tool": TOOL_ID,
        "tool_sha256": tool_hash,
        "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_id": manifest.run_id,
        "run_identity": spec.run_identity,
        "build_identity": build_identity,
        "image_identity": spec.profile,
        "programme_id": programme.programme_id,
        "policy_id": policy.policy_id,
        "status": "passed" if passed else "review_required",
        "primary_decision": (
            scientific_decision
            if passed and isinstance(scientific_decision, str)
            else "operator_review_required"
        ),
        "terminal_result": terminal_result,
        "terminal_reason": terminal_reason,
        "host_review_resolution": review_resolution_identity,
        "checks": checks,
        "csv_validation": shared_consumers["csv_validation"],
        "exact_lifecycle_records": shared_consumers["exact_lifecycle_records"],
        "maintenance_replay": maintenance_replay,
        "measurement_replay": measurement,
        "response_replay": responses,
        "transaction_capsule_sha256": shared_consumers[
            "transaction_capsule_sha256"
        ],
        "evidence_snapshot": shared_consumers["evidence_snapshot"],
        "source_sha256": source_hashes,
        "D10_semantics": {
            "pin": "D10", "record_type": "EVT", "authority": "evidence_only",
            "absence_noise_invalidity_or_overflow_cannot_change_control_or_terminal": True,
        },
        "host_discrepancy_authority": {
            "review_required": not passed,
            "new_setup": False,
            "new_arm": False,
            "automatic_abort": False,
            "automatic_teardown": False,
            "failed_campaign": False,
            "raw_evidence_preserved": True,
        },
        "limitations": [
            "D14 is the sole PPS/reference input and D8 is the oscillator/count input.",
            "D10 is optional external-event evidence and never timing or control authority.",
            "GNSS metadata qualifies the D14 receiver but cannot replace D14 timing authority.",
        ],
    }
    unsigned["seal_sha256"] = _canonical_sha256(unsigned)
    destination = output_path.resolve() if output_path else run_dir / programme.physical_seal_path
    _atomic_new_json(destination, unsigned)
    return destination, unsigned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--prior-review-seal", type=Path)
    args = parser.parse_args(argv)
    path, seal = analyze(
        args.run_dir,
        output_path=args.output,
        prior_review_seal_path=args.prior_review_seal,
    )
    print(json.dumps({"path": str(path), **seal}, indent=2, sort_keys=True))
    return 0 if seal["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
