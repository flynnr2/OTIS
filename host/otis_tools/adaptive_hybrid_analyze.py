"""Independent offline replay for one closed adaptive-hybrid run.

The analyzer is read-only with respect to captured evidence.  It validates the
current manifest, exact lifecycle records, D14/D8 measurement reconstruction,
controller transactions, and maintenance-state replay before publishing an
immutable analysis report. Packaging is a separate responsibility.  D10 remains optional external-event evidence and is
never consulted by a control or terminal predicate.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from .adaptive_hybrid_contract import (
    CONTINGENT_72_HOUR_HYBRID_CONTROL,
    INHIBITED_ZERO_WRITE,
    AdaptiveHybridProgramme,
    programme_from_mapping,
    validate_bench_attempt_envelope,
)
from .adaptive_hybrid_evidence import replay_adaptive_hybrid_maintenance_history
from .adaptive_hybrid_policy import AdaptiveHybridPolicy, policy_from_mapping
from .adaptive_hybrid_replay import (
    _measurement_replay,
    _response_replay,
    replay_active_decision_measurement_sources,
    replay_phase_accepted_sources,
    replay_transaction_capsules,
)
from .adaptive_hybrid_transactions import (
    CampaignSpec,
    _read_csv,
    validate_transaction_history,
)
from .authoritative_inputs import (
    ROOT_PROFILE,
    validate_authoritative_inputs,
)
from .contracts import CONTRACT_FIELDS, CsvValidationContext, validate_csv
from .evidence_package import (
    ANALYSIS_CONTRACT,
    ANALYSIS_REPORT,
    ANALYZER_TOOL,
    CAPTURE_RAW,
    PACKAGE_MANIFEST,
    PASSING_ANALYSIS_CHECKS,
    validate_package,
)
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, RunManifest, load_manifest
from .run_spec import (
    current_host_toolset_sha256,
    load_run_spec,
    verify_current_host_toolset,
)

TOOL_ID = ANALYZER_TOOL
SUPERVISOR_STATE = Path("reports/adaptive_hybrid_supervisor_state.json")
SUPERVISOR_EVENTS = Path("reports/adaptive_hybrid_supervisor_events.jsonl")
CAPTURE_CLOSURE = Path("reports/capture_segment_closure_v1.json")
ACTIVE_TRANSACTIONS = Path("csv/active_transactions_v3.csv")
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


def classify_scientific_outcome(
    terminal: object,
    programme: AdaptiveHybridProgramme,
    *,
    bench_attempt: object,
    qualified_d14_accepted_apertures: object,
) -> str:
    """Classify the scientific outcome from the frozen endpoint evidence.

    A passing offline-integrity check is deliberately insufficient here.  The
    finite campaign succeeds only at the exact accepted-D14/D8-aperture
    endpoint declared by the programme and bench-attempt envelope.
    """

    exact, decision, result, _ = _normalize_terminal(
        terminal,
        programme,
        bench_attempt=bench_attempt,
    )
    if not exact:
        return "undetermined"
    try:
        validated_bench_attempt = validate_bench_attempt_envelope(bench_attempt)
    except (TypeError, ValueError):
        return "undetermined"
    if result == "healthy_stop":
        if validated_bench_attempt.purpose == INHIBITED_ZERO_WRITE:
            return "diagnostic_complete"
        if validated_bench_attempt.purpose != CONTINGENT_72_HOUR_HYBRID_CONTROL:
            return "undetermined"
        if (
            type(qualified_d14_accepted_apertures) is int
            and qualified_d14_accepted_apertures
            == programme.qualified_d14_aperture_count
            and decision == programme.qualified_endpoint_reason
        ):
            return "qualified_complete"
        return "undetermined"
    if result == "aborted":
        return "interrupted_incomplete"
    if (
        type(qualified_d14_accepted_apertures) is not int
        or qualified_d14_accepted_apertures < 0
    ):
        return "undetermined"
    if decision == "adaptive_hybrid_right_censored_incomplete":
        return "interrupted_incomplete"
    if result == "nonpass":
        return "bounded_nonpass"
    return "undetermined"


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
        path.relative_to(manifest.root).as_posix(): _sha256_file(path)
        for path in sorted(manifest.root.rglob("*"))
        if path.is_file() and not path.is_symlink() and not path.name.endswith(".lock")
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

    The caller supplies the common projection of the retained run specification.
    This function independently reads the declared artifacts, supervisor
    records; callers cannot supply their verdicts.  It
    intentionally excludes physical measurement replay and physical-seal
    construction, which a PTY rehearsal cannot establish.
    """

    before_hashes = _source_hashes(manifest)
    csv_results = _validate_manifest_csvs(
        manifest, expected_policy_sha256=expected_active_policy_sha256
    )
    lifecycle = {"time_domain": "rp2040_monotonic_us64", "exact": all(
        csv_results.get(contract, {}).get("exact") is True
        for contract in ("active_transactions_v3", "active_hybrid_decisions_v3")
    )}
    transactions = _read_csv(_one_contract(manifest, "active_transactions_v3"))
    decisions = _read_csv(_one_contract(manifest, "active_hybrid_decisions_v3"))
    maintenance = _read_csv(
        _one_contract(manifest, "active_hybrid_maintenance_v2")
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
        response_classification_observational=True,
        response_policy_document=response_policy_document,
    )
    supervisor_state = _read_object(manifest.root / SUPERVISOR_STATE)
    events = _read_jsonl(manifest.root / SUPERVISOR_EVENTS)
    capsules = replay_transaction_capsules(
        manifest.root, transactions, events, supervisor_state
    )

    source_hashes = _source_hashes(manifest)
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
        "transaction_capsules_exact": capsules["exact"],
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
            "source_immutability": "exercised",
            "physical_D14_D8_measurement_replay": "unexercised",
            "physical_terminal_scientific_decision": "unexercised",
            "physical_seal_construction": "unexercised",
        },
        "checks": checks,
        "csv_validation": csv_results,
        "exact_lifecycle_records": lifecycle,
        "record_replay": record_replay,
        "response_replay": responses,
        "transaction_capsule_sha256": capsules["capsule_sha256"],
        "transaction_capsule_errors": capsules["errors"],
        "source_sha256": source_hashes,
    }


def _replay_control_preview_estimate_sources(
    manifest: RunManifest,
    selected_estimates: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Bind each CTL to its exact selected EST and retained wire order."""

    controls = _read_csv(_one_contract(manifest, "control_previews_v1"))
    if not controls:
        return {
            "exact": True,
            "applicability": "not_applicable_no_control_previews",
            "control_count": 0,
            "joins": [],
            "errors": [],
            "error_count": 0,
        }

    needed_estimate_ids = {row.get("est_input_ref", "") for row in controls}
    needed_decision_ids = {row.get("decision_id", "") for row in controls}
    raw_estimates: dict[str, tuple[int, int, dict[str, str]]] = {}
    raw_controls: dict[str, tuple[int, int, dict[str, str]]] = {}
    errors: list[str] = []
    error_count = 0

    def note_error(message: str) -> None:
        nonlocal error_count
        error_count += 1
        if len(errors) < 20:
            errors.append(message)

    with (manifest.root / CAPTURE_RAW).open("rb") as stream:
        for line_ordinal, raw_line in enumerate(stream, 1):
            if not raw_line.startswith((b"EST,", b"CTL,")):
                continue
            try:
                values = next(csv.reader([raw_line.decode("utf-8").strip()]))
            except (UnicodeError, csv.Error):
                continue
            record_type = values[0] if values else ""
            contract = "estimates_v3" if record_type == "EST" else "control_previews_v1"
            fields = CONTRACT_FIELDS[contract]
            if len(values) != len(fields):
                continue
            row = dict(zip(fields, values, strict=True))
            if record_type == "EST" and row["estimate_id"] in needed_estimate_ids:
                previous = raw_estimates.get(row["estimate_id"])
                raw_estimates[row["estimate_id"]] = (
                    1 if previous is None else previous[0] + 1,
                    line_ordinal if previous is None else previous[1],
                    row if previous is None else previous[2],
                )
            elif record_type == "CTL" and row["decision_id"] in needed_decision_ids:
                previous = raw_controls.get(row["decision_id"])
                raw_controls[row["decision_id"]] = (
                    1 if previous is None else previous[0] + 1,
                    line_ordinal if previous is None else previous[1],
                    row if previous is None else previous[2],
                )

    joins: list[dict[str, Any]] = []
    for control in controls:
        decision_id = control.get("decision_id", "")
        estimate_id = control.get("est_input_ref", "")
        estimate = selected_estimates.get(estimate_id)
        estimate_occurrence = raw_estimates.get(estimate_id)
        control_occurrence = raw_controls.get(decision_id)
        timestamp_domain_exact = (
            estimate is not None
            and control.get("decision_timestamp_ticks")
            == estimate.get("estimator_timestamp_ticks")
            and control.get("time_domain") == estimate.get("time_domain")
        )
        raw_estimate_exact = (
            estimate is not None
            and estimate_occurrence is not None
            and estimate_occurrence[0] == 1
            and estimate_occurrence[2] == estimate
        )
        raw_control_exact = (
            control_occurrence is not None
            and control_occurrence[0] == 1
            and control_occurrence[2] == control
        )
        publication_order_exact = (
            raw_estimate_exact
            and raw_control_exact
            and estimate_occurrence[1] < control_occurrence[1]
        )
        exact = (
            estimate is not None
            and timestamp_domain_exact
            and raw_estimate_exact
            and raw_control_exact
            and publication_order_exact
        )
        if not exact:
            note_error(
                f"CTL {decision_id or '?'} does not bind one earlier exact selected "
                f"EST {estimate_id or '?'} with the same timestamp and domain"
            )
        joins.append(
            {
                "decision_id": decision_id,
                "estimate_id": estimate_id,
                "timestamp_domain_exact": timestamp_domain_exact,
                "raw_estimate_exact": raw_estimate_exact,
                "raw_control_exact": raw_control_exact,
                "publication_order_exact": publication_order_exact,
                "exact": exact,
            }
        )
    return {
        "exact": error_count == 0,
        "applicability": "emitted_control_previews",
        "control_count": len(controls),
        "joins": joins,
        "errors": errors,
        "error_count": error_count,
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


def analyze(
    run_dir: Path,
    *,
    output_path: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Replay closed observations and publish an immutable analysis report."""

    run_dir = run_dir.resolve()
    if (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise ValueError("adaptive-hybrid capture is still active")
    manifest = load_manifest(run_dir)
    manifest_value = manifest.data
    run_spec = load_run_spec(run_dir / manifest_value["run_spec"]["path"])
    programme = programme_from_mapping(manifest_value)
    before_hashes = _source_hashes(manifest)
    # A later analysis of sealed evidence is a linked report outside the package.
    sealed_source = (
        validate_package(run_dir) if (run_dir / PACKAGE_MANIFEST).exists() else None
    )
    if sealed_source is None:
        verify_current_host_toolset(run_spec)
    analysis_toolset_sha256 = current_host_toolset_sha256()
    destination = output_path.resolve() if output_path else run_dir / ANALYSIS_REPORT
    if sealed_source is not None and (destination == run_dir or run_dir in destination.parents):
        raise ValueError("sealed evidence is immutable; select an external analysis output")
    closure = _read_object(run_dir / CAPTURE_CLOSURE)
    if (closure.get("logical_segment_closed") is not True
            or closure.get("physical_serial_open") is not False
            or closure.get("run_manifest_sha256") != _sha256_file(manifest.path)):
        raise ValueError("capture closure does not bind this closed acquisition")
    frozen_inputs = validate_authoritative_inputs(manifest_value.get("authoritative_inputs"))
    policy_document = frozen_inputs.document(ROOT_PROFILE)
    policy_binding = frozen_inputs.binding(ROOT_PROFILE)
    policy = policy_from_mapping(
        policy_document, policy_sha256=str(policy_binding["sha256"])
    )
    section = manifest_value[programme.manifest_section]
    control = section["automatic_control"]
    build_identity = str(manifest_value["firmware"]["build_identity"])
    bench_attempt = manifest_value.get("bench_attempt", {})
    inhibited_zero_write = bench_attempt.get("purpose") == "inhibited_zero_write"
    if inhibited_zero_write:
        transactions = _read_csv(_one_contract(manifest, "active_transactions_v3"))
        dac_steps = _read_csv(_one_contract(manifest, "dac_steps_v1"))
        inhibited_authority_exact = (
            section["setup"].get("authorized_after_entry") is False
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
        response_policy_document=frozen_inputs.document(str(policy_document["bindings"]["response_classification"]),
        ),
        programme=programme,
    )
    record_replay = shared_consumers["record_replay"]
    maintenance_replay = _inhibited_zero_write_maintenance_replay(
        record_replay,
        authority_exact=inhibited_zero_write and inhibited_authority_exact,
    )
    transactions = _read_csv(_one_contract(manifest, "active_transactions_v3"))
    _, measurement, selected_estimates = _measurement_replay(
        manifest, manifest_value, validated_inputs=frozen_inputs
    )
    control_estimate_sources = _replay_control_preview_estimate_sources(
        manifest, selected_estimates
    )
    decision_measurement_sources = replay_active_decision_measurement_sources(
        manifest, measurement
    )
    phase_sources = replay_phase_accepted_sources(manifest)
    measurement["active_decision_sources"] = decision_measurement_sources
    measurement["phase_sources"] = phase_sources
    measurement["control_preview_estimate_sources"] = control_estimate_sources
    responses = shared_consumers["response_replay"]
    supervisor_state = _read_object(run_dir / SUPERVISOR_STATE)
    qualification_coordinate_exact = False
    try:
        origin_epoch = supervisor_state["qualified_acceptance_epoch_origin"]
        origin_ordinal = supervisor_state["qualified_acceptance_ordinal_origin"]
        endpoint_ordinal = supervisor_state["qualified_acceptance_ordinal_endpoint"]
        accepted_apertures = supervisor_state["qualified_d14_accepted_apertures"]
        origin_session = supervisor_state["qualified_origin_session_id"]
        qualification_coordinate_exact = (
            type(origin_epoch) is int and origin_epoch > 0
            and type(origin_session) is int and origin_session > 0
            and all(type(value) is int and 0 <= value < 1 << 32 for value in
                    (origin_ordinal, endpoint_ordinal))
            and type(accepted_apertures) is int
            and 0 <= accepted_apertures <= 0x7FFFFFFF
            and (endpoint_ordinal - origin_ordinal) & 0xFFFFFFFF
                == accepted_apertures
        )
    except (KeyError, TypeError):
        accepted_apertures = None
    effective_terminal = supervisor_state.get("terminal")

    d10_isolated = _d10_isolated(section, measurement)
    checks = {
        "manifest_current": True,
        "csv_contracts_exact": (
            shared_consumers["checks"]["authoritative_csvs_exact"]
            and control_estimate_sources.get("exact") is True
        ),
        "exact_lifecycle_records": shared_consumers["checks"][
            "exact_lifecycle_records"
        ],
        "transactions_exact": shared_consumers["checks"][
            "transaction_history_exact"
        ],
        "maintenance_replay_exact": maintenance_replay.get("exact") is True,
        "D14_D8_measurement_replay_exact": measurement.get("raw_measurement_exact") is True,
        "selected_estimates_replay_exact": measurement.get("estimate_replay", {}).get("exact") is True,
        "decision_measurement_sources_exact": (
            decision_measurement_sources.get("exact") is True
        ),
        "phase_accepted_sources_exact": phase_sources.get("exact") is True,
        "response_replay_exact": shared_consumers["checks"][
            "response_replay_exact"
        ],
        "transaction_capsules_exact": shared_consumers["checks"][
            "transaction_capsules_exact"
        ],
        "D10_optional_event_isolated": d10_isolated,
        "inhibited_zero_write_authority_exact": inhibited_authority_exact,
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
    qualification_fields_present = any(
        supervisor_state.get(key) is not None
        for key in (
            "qualified_acceptance_epoch_origin",
            "qualified_acceptance_ordinal_origin",
            "qualified_acceptance_ordinal_endpoint",
            "qualified_d14_accepted_apertures",
        )
    )
    checks["accepted_span_qualification_coordinate_exact"] = (
        qualification_coordinate_exact
        if qualification_fields_present
        else terminal_result != "healthy_stop"
    )
    scientific_outcome = classify_scientific_outcome(
        effective_terminal,
        programme,
        bench_attempt=bench_attempt,
        qualified_d14_accepted_apertures=(
            accepted_apertures if qualification_coordinate_exact else None
        ),
    )
    checks["scientific_outcome_determined"] = (
        scientific_outcome != "undetermined"
    )
    if set(checks) != PASSING_ANALYSIS_CHECKS:
        raise RuntimeError("offline analyzer check contract differs")
    passed = all(checks.values())
    evidence_integrity = "passed" if passed else "review_required"
    if not passed:
        scientific_outcome = "undetermined"
    source_hashes = _source_hashes(manifest)
    if source_hashes != before_hashes:
        raise RuntimeError("source evidence changed during offline analysis")
    tool_hash = _sha256_file(Path(__file__))
    unsigned: dict[str, Any] = {
        "schema_version": 2,
        "contract": ANALYSIS_CONTRACT,
        "tool": TOOL_ID,
        "tool_sha256": tool_hash,
        "host_toolset_sha256": analysis_toolset_sha256,
        "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_id": manifest.run_id,
        "run_identity": spec.run_identity,
        "build_identity": build_identity,
        "image_identity": spec.profile,
        "programme_id": programme.programme_id,
        "policy_id": policy.policy_id,
        "status": evidence_integrity,
        "evidence_integrity": evidence_integrity,
        "scientific_outcome": scientific_outcome,
        "outcome": scientific_outcome,
        "source_package_content_sha256": (sealed_source["package_content_sha256"] if sealed_source else None),
        "primary_decision": (
            scientific_decision
            if passed and isinstance(scientific_decision, str)
            else "operator_review_required"
        ),
        "terminal_result": terminal_result,
        "terminal_reason": terminal_reason,
        "checks": checks,
        "csv_validation": shared_consumers["csv_validation"],
        "exact_lifecycle_records": shared_consumers["exact_lifecycle_records"],
        "maintenance_replay": maintenance_replay,
        "measurement_replay": measurement,
        "response_replay": responses,
        "transaction_capsule_sha256": shared_consumers[
            "transaction_capsule_sha256"
        ],
        "transaction_capsule_errors": shared_consumers["transaction_capsule_errors"],
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
    unsigned["analysis_sha256"] = _canonical_sha256(unsigned)
    _atomic_new_json(destination, unsigned)
    return destination, unsigned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    path, seal = analyze(
        args.run_dir,
        output_path=args.output,
    )
    print(json.dumps({"path": str(path), **seal}, indent=2, sort_keys=True))
    return 0 if seal["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
