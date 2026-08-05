"""Produce the final evidence-gated CX317 acquisition-programme review.

This tool is deliberately offline.  It never opens a serial device, command
FIFO or abort FIFO, and it grants no actuation authority.  Every successful
gate is supplied explicitly so a diagnostic run cannot be selected merely by
directory ordering.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import argparse
import csv
import json
import os
import tempfile
from typing import Any, Iterable

from .evidence import validate_evidence_snapshot
from .cx317_stage7_gate_validation import (
    PART_A_COMPOSITE_TEST,
    part_a2_progression_gate_valid,
)
from .run_loader import load_manifest


TOOL_VERSION = "cx317_stage8_final_review_v2"
DECISIONS = (
    "blocked_before_active_control",
    "bounded_control_needs_revision",
    "bounded_frequency_acquisition_passed",
    "dual_core_frequency_control_endurance_passed",
)
NEXT_GOALS = (
    "frequency_acquisition_refinement_and_wider_environmental_applicability",
    "phase_estimator_definition_and_bounded_hybrid_phase_frequency_preview",
    "reference_loss_holdover_and_controlled_recovery",
    "gnss_receiver_provisioning_or_timing_grade_gnss_upgrade",
    "physical_waveform_voltage_metrology_qualification",
    "product_platform_interfaces_after_timing_core_stability",
)


@dataclass(frozen=True)
class Check:
    identifier: str
    passed: bool
    evidence: str


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def _checks_pass(value: dict[str, Any]) -> bool:
    checks = value.get("checks")
    return isinstance(checks, list) and bool(checks) and all(
        isinstance(item, dict) and item.get("passed") is True
        for item in checks
    )


def _gate_passed(value: dict[str, Any], gate_kind: str) -> bool:
    if gate_kind in {"campaign_a", "campaign_b"}:
        return value.get("stage_exit_passed") is True
    if gate_kind == "stage6":
        return value.get("status") == "pass" and _checks_pass(value)
    if gate_kind == "stage7_a2":
        return part_a2_progression_gate_valid(value)
    if gate_kind == "stage7_a1":
        criteria = value.get("criteria", {})
        return (
            value.get("status") == "pass"
            and value.get("test") == "part_a_fixed_code_stability"
            and value.get("applicable") is True
            and isinstance(criteria, dict)
            and bool(criteria)
            and all(item is True for item in criteria.values())
        )
    if gate_kind == "stage7_b":
        return value.get("status") == "pass" and _checks_pass(value)
    if gate_kind == "verification":
        pytest = value.get("pytest", {})
        matrix = value.get("firmware_matrix", {})
        no_hardware = value.get("no_hardware_validation", {})
        return (
            value.get("schema_version") == 1
            and pytest.get("result") == "pass"
            and int(pytest.get("failed", -1)) == 0
            and int(pytest.get("errors", -1)) == 0
            and int(pytest.get("passed", 0)) > 0
            and matrix.get("result") == "pass"
            and int(matrix.get("passed_profiles", -1))
            == int(matrix.get("expected_pass_profiles", -2))
            and int(matrix.get("guarded_failures_observed", -1))
            == int(matrix.get("expected_fail_profiles", -2))
            and no_hardware.get("result") == "pass"
        )
    raise ValueError(f"unknown gate kind {gate_kind!r}")


def _sealed_run_check(
    identifier: str,
    gate_path: Path,
    *,
    allow_partial_subtest: bool = False,
) -> tuple[Check, dict[str, Any]]:
    """Require the run containing a supplied gate to be closed and sealed."""
    resolved = gate_path.resolve()
    run_dir = resolved.parent.parent
    evidence_path = run_dir / "evidence_manifest.json"
    complete = (run_dir / "COMPLETE").is_file()
    capture_active = (run_dir / "capture_in_progress.flag").exists()
    snapshot: dict[str, Any] = {}
    failures: list[str] = []
    warnings: list[str] = []
    try:
        manifest = load_manifest(run_dir)
        failures, warnings = validate_evidence_snapshot(run_dir, manifest)
        if evidence_path.is_file():
            snapshot = _read_json(evidence_path)
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        failures = [str(exc)]
    gate_in_snapshot = False
    if snapshot:
        gate_relative = str(resolved.relative_to(run_dir))
        artifacts = snapshot.get("artifacts", [])
        gate_in_snapshot = any(
            item.get("path") == gate_relative
            for item in artifacts
            if isinstance(item, dict)
        )
    complete_seal = (
        complete
        and not capture_active
        and snapshot.get("run_state") == "complete"
        and isinstance(snapshot.get("snapshot_digest"), str)
        and len(snapshot["snapshot_digest"]) == 64
        and not failures
    )
    partial_subtest_seal = (
        allow_partial_subtest
        and not complete
        and not capture_active
        and snapshot.get("run_state") == "partial"
        and isinstance(snapshot.get("snapshot_digest"), str)
        and len(snapshot["snapshot_digest"]) == 64
        and not failures
    )
    passed = complete_seal or partial_subtest_seal
    details = {
        "run_directory": str(run_dir),
        "gate_path": str(resolved),
        "complete_marker": complete,
        "capture_active": capture_active,
        "evidence_run_state": snapshot.get("run_state", "missing"),
        "evidence_snapshot_digest": snapshot.get("snapshot_digest"),
        "gate_in_snapshot": gate_in_snapshot,
        "allow_partial_subtest": allow_partial_subtest,
        "seal_class": (
            "complete_run"
            if complete_seal
            else "validated_partial_source_for_transitively_sealed_subtest"
            if partial_subtest_seal
            else "unsealed"
        ),
        "validation_failures": failures,
        "validation_warnings": warnings,
    }
    return (
        Check(
            f"{identifier}_sealed_run",
            passed,
            (
                f"run {run_dir.name}; COMPLETE={complete}; "
                f"capture_active={capture_active}; snapshot "
                f"{snapshot.get('snapshot_digest', 'missing')}; "
                f"gate_in_snapshot={gate_in_snapshot}; gate SHA-256 "
                f"{_sha256_file(resolved)}; failures={len(failures)}"
            ),
        ),
        details,
    )


def _composite_part_a_seal_check(
    composite_gate_path: Path,
    part_b_gate_path: Path,
) -> tuple[Check, dict[str, Any]]:
    """Revalidate a composite A gate and its transitive Part B binding.

    Composite A intentionally preserves two partial source runs and one
    complete repair rehearsal; it is not a relabelled single-run pass.  The
    exact composite document becomes progression authority only when the
    immutable Part B manifest embeds its path, hash and document verbatim.
    """
    composite_path = composite_gate_path.resolve()
    composite = _read_json(composite_path)
    failures: list[str] = []
    component_audit: dict[str, dict[str, Any]] = {}
    components = (
        (
            "part_a1_fixed_code_stability",
            composite.get("part_a1_stability", {}).get("binding", {}),
            "gate_path",
            "gate_sha256",
            True,
        ),
        (
            "source_a2_failed_diagnostic",
            composite.get("source_a2_disposition", {}).get("binding", {}),
            "source_exit_gate_path",
            "source_exit_gate_sha256",
            True,
        ),
        (
            "targeted_repair_rehearsal",
            composite.get("repair_rehearsal", {}).get("binding", {}),
            "gate_path",
            "gate_sha256",
            False,
        ),
    )
    for name, binding, path_key, hash_key, allow_partial in components:
        try:
            gate_path = Path(binding[path_key]).resolve()
            check, details = _sealed_run_check(
                name,
                gate_path,
                allow_partial_subtest=allow_partial,
            )
            evidence_manifest = Path(details["run_directory"]) / (
                "evidence_manifest.json"
            )
            exact = (
                check.passed
                and str(gate_path) == str(Path(binding[path_key]).resolve())
                and _sha256_file(gate_path) == binding[hash_key]
                and str(Path(binding["run_dir"]).resolve())
                == details["run_directory"]
                and binding["run_state"] == details["evidence_run_state"]
                and binding["snapshot_digest"]
                == details["evidence_snapshot_digest"]
                and evidence_manifest.is_file()
                and _sha256_file(evidence_manifest)
                == binding["evidence_manifest_sha256"]
                and not binding.get("evidence_snapshot_failures", [])
                and not binding.get("evidence_snapshot_warnings", [])
                and not details["validation_failures"]
                and not details["validation_warnings"]
            )
            component_audit[name] = {**details, "binding_exact": exact}
            if not exact:
                failures.append(f"{name}: component seal binding differs")
        except (FileNotFoundError, KeyError, OSError, TypeError, ValueError) as exc:
            failures.append(f"{name}: {exc}")

    transitive_binding = False
    try:
        part_b_run = part_b_gate_path.resolve().parent.parent
        part_b_manifest = _read_json(part_b_run / "run_manifest.json")
        entry = part_b_manifest["prerequisite_gates"][
            "part_a2_cross_core_transaction"
        ]
        transitive_binding = (
            str(Path(entry["path"]).resolve()) == str(composite_path)
            and entry["sha256"] == _sha256_file(composite_path)
            and entry["document"] == composite
        )
        if not transitive_binding:
            failures.append("Part B manifest composite-A binding differs")
    except (FileNotFoundError, KeyError, OSError, TypeError, ValueError) as exc:
        failures.append(f"Part B manifest composite-A binding: {exc}")

    passed = (
        part_a2_progression_gate_valid(composite)
        and transitive_binding
        and not failures
    )
    details = {
        "run_directory": "composite_transitive_evidence",
        "gate_path": str(composite_path),
        "complete_marker": None,
        "capture_active": False,
        "evidence_run_state": "composite",
        "evidence_snapshot_digest": "transitive_component_seals",
        "gate_in_snapshot": False,
        "allow_partial_subtest": True,
        "seal_class": (
            "part_b_manifest_bound_composite_of_validated_source_seals"
            if passed
            else "unsealed"
        ),
        "transitively_bound_by_part_b_manifest": transitive_binding,
        "component_audit": component_audit,
        "validation_failures": failures,
        "validation_warnings": [],
    }
    return (
        Check(
            "stage7_a2_composite_sealed_evidence",
            passed,
            f"composite SHA-256 {_sha256_file(composite_path)}; "
            f"components={len(component_audit)}/3; "
            f"Part B binding={transitive_binding}; failures={len(failures)}",
        ),
        details,
    )


def _part_a1_transitive_seal_check(
    part_a1_gate_path: Path,
    part_b_gate_path: Path,
) -> tuple[Check, dict[str, Any]]:
    """Accept partial A1 only when Part B binds its exact passed subtest."""
    gate_path = part_a1_gate_path.resolve()
    gate = _read_json(gate_path)
    source_check, details = _sealed_run_check(
        "stage7_a1",
        gate_path,
        allow_partial_subtest=True,
    )
    failures = list(details["validation_failures"])
    transitive_binding = False
    try:
        part_b_run = part_b_gate_path.resolve().parent.parent
        part_b_manifest = _read_json(part_b_run / "run_manifest.json")
        entry = part_b_manifest["prerequisite_gates"][
            "part_a1_fixed_code_stability"
        ]
        transitive_binding = (
            str(Path(entry["path"]).resolve()) == str(gate_path)
            and entry["sha256"] == _sha256_file(gate_path)
            and entry["document"] == gate
        )
        if not transitive_binding:
            failures.append("Part B manifest A1 subtest binding differs")
    except (FileNotFoundError, KeyError, OSError, TypeError, ValueError) as exc:
        failures.append(f"Part B manifest A1 subtest binding: {exc}")
    passed = (
        _gate_passed(gate, "stage7_a1")
        and source_check.passed
        and transitive_binding
        and not failures
    )
    details = {
        **details,
        "seal_class": (
            "part_b_manifest_bound_validated_partial_a1_subtest"
            if passed
            else "unsealed"
        ),
        "transitively_bound_by_part_b_manifest": transitive_binding,
        "validation_failures": failures,
    }
    return (
        Check(
            "stage7_a1_transitively_sealed_subtest",
            passed,
            f"A1 SHA-256 {_sha256_file(gate_path)}; "
            f"Part B binding={transitive_binding}; failures={len(failures)}",
        ),
        details,
    )


def _decision(gates: dict[str, bool]) -> str:
    if not gates.get("campaign_a", False):
        return "blocked_before_active_control"
    if not gates.get("campaign_b", False):
        return "bounded_control_needs_revision"
    stage7 = (
        gates.get("stage6", False),
        gates.get("stage7_a1", False),
        gates.get("stage7_a2", False),
        gates.get("stage7_b", False),
        gates.get("verification", False),
    )
    if all(stage7):
        return "dual_core_frequency_control_endurance_passed"
    if gates.get("stage7_b_attempted", False):
        return "bounded_control_needs_revision"
    return "bounded_frequency_acquisition_passed"


def _terminal(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "reports/cx317_active_supervisor_state.json"
    if not path.is_file():
        return None
    return _read_json(path).get("terminal")


def _run_summary(run_dir: Path, campaign_root: Path) -> dict[str, Any]:
    manifest_path = run_dir / "run_manifest.json"
    manifest = _read_json(manifest_path)
    transactions = _read_csv(run_dir / "csv/active_transactions_v1.csv")
    applications = [row for row in transactions if row.get("event") == "application"]
    manual = [row for row in transactions if row.get("event") == "manual_start"]
    final_code: int | None = None
    if applications:
        final_code = int(applications[-1]["applied_code"])
    elif manual:
        final_code = int(manual[-1]["applied_code"])
    else:
        dac = _read_csv(run_dir / "csv/dac_steps.csv")
        applied = [row for row in dac if row.get("dac_code_applied") not in {None, ""}]
        if applied:
            final_code = int(applied[-1]["dac_code_applied"])
    corrections = [
        {
            "request_sequence": int(row["request_sequence"]),
            "requested_delta_codes": int(row["requested_delta_codes"]),
            "requested_code": int(row["requested_code"]),
            "applied_code": int(row["applied_code"]),
            "pre_error_hz": float(row["pre_error_hz"]),
        }
        for row in applications
    ]
    responses = [
        {
            "request_sequence": int(row["request_sequence"]),
            "post_error_hz": float(row["post_error_hz"]),
            "observed_response_hz": float(row["observed_response_hz"]),
            "response_class": row["response_class"],
        }
        for row in transactions
        if row.get("event") == "response"
    ]
    snapshot_path = run_dir / "evidence_manifest.json"
    snapshot = _read_json(snapshot_path) if snapshot_path.is_file() else {}
    exit_path = run_dir / "reports/stage7_exit_gate.json"
    exit_gate = _read_json(exit_path) if exit_path.is_file() else {}
    firmware = manifest.get("firmware", {})
    active_campaign = manifest.get("active_campaign", {})
    shadow_contract = manifest.get("shadow_contract", {})
    return {
        "run_id": manifest.get("run_id", run_dir.name),
        "run_directory": str(run_dir.relative_to(campaign_root)),
        "stage": manifest.get("stage"),
        "complete_marker": (run_dir / "COMPLETE").is_file(),
        "capture_active": (run_dir / "capture_in_progress.flag").exists(),
        "evidence_run_state": snapshot.get("run_state", "missing"),
        "evidence_snapshot_digest": snapshot.get("snapshot_digest"),
        "stage7_exit_status": exit_gate.get("status"),
        "terminal": _terminal(run_dir),
        "manual_start_code": int(manual[-1]["applied_code"]) if manual else None,
        "automatic_correction_count": len(applications),
        "cumulative_movement_codes": (
            int(applications[-1]["cumulative_movement_codes"])
            if applications
            else 0
        ),
        "final_confirmed_code": final_code,
        "transaction_record_count": len(transactions),
        "transaction_event_sequence": [row.get("event") for row in transactions],
        "corrections": corrections,
        "responses": responses,
        "identities": {
            "firmware_source_sha256": firmware.get("source_sha256"),
            "firmware_configuration_sha256": firmware.get(
                "configuration_sha256"
            ),
            "firmware_uf2_sha256": firmware.get("uf2_sha256"),
            "build_identity": firmware.get("build_identity"),
            "profile_id": firmware.get("profile_id"),
            "estimator_sha256": active_campaign.get("estimator_sha256"),
            "model_sha256": active_campaign.get("model_sha256"),
            "active_policy_sha256": active_campaign.get(
                "active_policy_sha256"
            ),
            "response_policy_sha256": active_campaign.get(
                "response_policy_sha256"
            ),
            "numerical_policy_sha256": active_campaign.get(
                "numerical_policy_sha256"
            ),
            "shadow_contract_sha256": shadow_contract.get("sha256"),
        },
    }


def _active_run_history(campaign: Path) -> list[dict[str, Any]]:
    roots = (campaign / "stage4", campaign / "stage5", campaign / "stage7")
    manifests = sorted(
        path
        for root in roots
        if root.is_dir()
        for path in root.glob("*/run_manifest.json")
    )
    return [_run_summary(path.parent, campaign) for path in manifests]


def _next_goal(decision: str) -> tuple[str, str]:
    if decision == "dual_core_frequency_control_endurance_passed":
        return (
            "phase_estimator_definition_and_bounded_hybrid_phase_frequency_preview",
            "Frequency acquisition and dual-core endurance are established; the largest remaining control-function gap is a replayable phase estimator and a non-actionable bounded hybrid preview.",
        )
    return (
        "frequency_acquisition_refinement_and_wider_environmental_applicability",
        "The bounded frequency-control evidence is not yet sufficient for progression to phase control; close the failed or incomplete acquisition/endurance gates first.",
    )


def _markdown_table(headings: tuple[str, ...], rows: Iterable[Iterable[Any]]) -> list[str]:
    lines = [
        "| " + " | ".join(headings) + " |",
        "| " + " | ".join("---" for _ in headings) + " |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(str(value).replace("\n", " ") for value in row)
            + " |"
        )
    return lines


def _render(result: dict[str, Any]) -> str:
    decision = result["decision"]
    history = result["active_run_history"]
    next_goal = result["recommended_next_goal"]
    stage7 = result["stage7_endurance"]
    authoritative = stage7.get("authoritative_time_series", {})
    context = stage7.get("authoritative_context_analysis", {})
    transactions = stage7.get("transactions", {})
    verification = result["final_verification"]
    correction_rows: list[tuple[Any, ...]] = []
    response_rows: list[tuple[Any, ...]] = []
    for item in history:
        if item["corrections"]:
            correction_rows.extend(
                (
                    item["run_id"],
                    correction["request_sequence"],
                    correction["requested_delta_codes"],
                    f"0x{correction['requested_code']:04X}",
                    f"0x{correction['applied_code']:04X}",
                    f"{correction['pre_error_hz']:.12g}",
                )
                for correction in item["corrections"]
            )
        else:
            correction_rows.append((item["run_id"], "none", 0, "—", "—", "—"))
        response_rows.extend(
            (
                item["run_id"],
                response["request_sequence"],
                f"{response['post_error_hz']:.12g}",
                f"{response['observed_response_hz']:.12g}",
                response["response_class"],
            )
            for response in item["responses"]
        )
    if not response_rows:
        response_rows.append(("none", "—", "—", "—", "—"))
    pytest_result = verification.get("pytest", {})
    matrix_result = verification.get("firmware_matrix", {})
    no_hardware_result = verification.get("no_hardware_validation", {})
    lines = [
        "# CX317 Bounded Closed-Loop Acquisition Programme Final Review",
        "",
        f"Decision: `{decision}`.",
        "",
        "## Rationale",
        "",
        result["rationale"],
        "",
        "## Exit-gate audit",
        "",
        *_markdown_table(
            ("Gate", "Result", "Evidence / SHA-256"),
            (
                (
                    item["identifier"],
                    "pass" if item["passed"] else "fail",
                    item["evidence"],
                )
                for item in result["checks"]
            ),
        ),
        "",
        "## Immutable run seals",
        "",
        *_markdown_table(
            ("Gate", "Seal class", "Snapshot digest", "Gate in snapshot"),
            (
                (
                    name,
                    details["seal_class"],
                    details["evidence_snapshot_digest"],
                    details["gate_in_snapshot"],
                )
                for name, details in result["sealed_run_audit"].items()
            ),
        ),
        "",
        "## Active-run correction history",
        "",
        *_markdown_table(
            (
                "Run",
                "Stage",
                "Terminal",
                "Automatic corrections",
                "Movement (codes)",
                "Final code",
                "Evidence state",
            ),
            (
                (
                    item["run_id"],
                    item["stage"],
                    (item["terminal"] or {}).get("result", "unavailable"),
                    item["automatic_correction_count"],
                    item["cumulative_movement_codes"],
                    (
                        f"0x{item['final_confirmed_code']:04X}"
                        if item["final_confirmed_code"] is not None
                        else "unavailable"
                    ),
                    item["evidence_run_state"],
                )
                for item in history
            ),
        ),
        "",
        "### Exact automatic applications",
        "",
        *_markdown_table(
            ("Run", "Request", "Delta", "Requested", "Applied", "Pre-error (Hz)"),
            correction_rows,
        ),
        "",
        "### Response classifications",
        "",
        *_markdown_table(
            ("Run", "Request", "Post-error (Hz)", "Observed response (Hz)", "Class"),
            response_rows,
        ),
        "",
        "### Complete transaction record sequences",
        "",
        *_markdown_table(
            ("Run", "Records", "Ordered events"),
            (
                (
                    item["run_id"],
                    item["transaction_record_count"],
                    " → ".join(item["transaction_event_sequence"]) or "none",
                )
                for item in history
            ),
        ),
        "",
        "## Exact active identities",
        "",
        *_markdown_table(
            (
                "Run",
                "Firmware source",
                "Config",
                "UF2",
                "Estimator",
                "Model",
                "Active policy",
                "Response policy",
                "Numerical policy",
                "Shadow contract",
            ),
            (
                (
                    item["run_id"],
                    item["identities"]["firmware_source_sha256"],
                    item["identities"]["firmware_configuration_sha256"],
                    item["identities"]["firmware_uf2_sha256"],
                    item["identities"]["estimator_sha256"],
                    item["identities"]["model_sha256"],
                    item["identities"]["active_policy_sha256"],
                    item["identities"]["response_policy_sha256"],
                    item["identities"]["numerical_policy_sha256"],
                    item["identities"]["shadow_contract_sha256"],
                )
                for item in history
            ),
        ),
        "",
        "## Frequency-control and deadband evidence",
        "",
        "The authoritative Stage 7 policy retained the V2 deadband of `abs(error) <= 0.006249995628992717 Hz`; shadow candidates had zero authority.",
        "",
        *_markdown_table(
            ("Metric", "Measured value"),
            (
                ("qualified 600 s observations", authoritative.get("count", "unavailable")),
                ("minimum error (Hz)", authoritative.get("minimum_hz", "unavailable")),
                ("maximum error (Hz)", authoritative.get("maximum_hz", "unavailable")),
                ("mean error (Hz)", authoritative.get("mean_hz", "unavailable")),
                ("median error (Hz)", authoritative.get("median_hz", "unavailable")),
                ("inside-deadband fraction", authoritative.get("authoritative_inside_fraction", "unavailable")),
                ("boundary crossings", authoritative.get("authoritative_boundary_crossings", "unavailable")),
                ("longest continuous inside residence (s)", authoritative.get("longest_inside_continuous_residence_s", "unavailable")),
                ("linear drift (Hz/s)", authoritative.get("linear_drift_hz_per_s", "unavailable")),
                ("effective sample size", authoritative.get("effective_sample_size_initial_positive_acf", "unavailable")),
                ("automatic applications", transactions.get("application_count", "unavailable")),
                ("absolute path (codes)", transactions.get("path_codes", "unavailable")),
                ("net movement (codes)", transactions.get("net_movement_codes", "unavailable")),
                ("direction-paired hysteresis", context.get("hysteresis_claim", "unavailable")),
            ),
        ),
        "",
        "Full fixed-code distributions, residence segments, autocorrelation, Newey–West uncertainty, service/environment associations, candidate replay, dither and hysteresis records remain verbatim in the immutable Stage 7B gate listed above.",
        "",
        "## GNSS validity and availability",
        "",
        f"Stage 7B qualified {context.get('gnss_qualification', {}).get('qualified_count', 'unavailable')} of {context.get('gnss_qualification', {}).get('observation_count', 'unavailable')} authoritative observations; its longest unqualified run was {context.get('gnss_qualification', {}).get('longest_unqualified_run_estimates', 'unavailable')} selected estimates.",
        "Receiver metadata qualifies but does not timestamp the hardware PPS. Fix quality, GSA-3D, checksum, identity, controlled Stage 6 invalidation/recovery and any natural outage evidence remain bounded to eligibility; none supplies UTC traceability.",
        "",
        "## Cross-core architecture and isolation",
        "",
        "Core 1 owns timing, observation, estimation and request generation; Core 0 owns USB, GNSS/environment service and physical I2C application. Stage 6 and Stage 7 evidence must both pass before the endurance decision can be selected.",
        "",
        f"Stage 7B recorded {len(transactions.get('latencies', []))} complete cross-core transaction latency sets, {transactions.get('complete_request_group_count', 'unavailable')}/{transactions.get('request_group_count', 'unavailable')} complete four-phase request groups, and exact response replay={transactions.get('all_response_classifications_replay_exactly', 'unavailable')}.",
        "",
        "## Faults, stops, recovery and preservation",
        "",
        "Every manifest-bearing active attempt appears in the correction-history table, including diagnostic and stopped runs. Passing runs cannot erase a failed prefix; diagnostic evidence remains explicitly non-passing.",
        "",
        "## Final software/build verification",
        "",
        *_markdown_table(
            ("Gate", "Result", "Exact outcome"),
            (
                (
                    "pytest",
                    pytest_result.get("result", "unavailable"),
                    f"passed={pytest_result.get('passed')} skipped={pytest_result.get('skipped')} failed={pytest_result.get('failed')} errors={pytest_result.get('errors')}",
                ),
                (
                    "firmware matrix",
                    matrix_result.get("result", "unavailable"),
                    f"supported={matrix_result.get('passed_profiles')}/{matrix_result.get('expected_pass_profiles')} guarded={matrix_result.get('guarded_failures_observed')}/{matrix_result.get('expected_fail_profiles')}",
                ),
                (
                    "no-hardware validation",
                    no_hardware_result.get("result", "unavailable"),
                    no_hardware_result.get("evidence", "see bound verification artifact"),
                ),
            ),
        ),
        "",
        "## Remaining blockers and unsupported claims",
        "",
        "- no calibrated absolute-frequency accuracy or combined uncertainty claim",
        "- no UTC traceability, phase lock or holdover claim",
        "- no oscilloscope-based D8 waveform, rise/fall or phase-margin qualification",
        "- nearby-air SHT41 data remains a covariate, not a demonstrated CX317 case-temperature model",
        "- the GNSS receiver is read-only and not a timing-grade provisioned receiver",
        "",
        "## Recommended next programme",
        "",
        f"Recommend exactly one goal: `{next_goal['goal']}`.",
        "",
        next_goal["rationale"],
        "",
        "This recommendation grants no actuation authority. A new programme must freeze its estimator, replay, limits and hardware gates separately.",
        "",
        "## Final static state",
        "",
        f"Last confirmed applied code: `{result['last_confirmed_code_hex']}`. Leave it static; Stage 8 performs no DAC write.",
        "",
    ]
    return "\n".join(lines)


def review(
    campaign_dir: Path,
    gate_paths: dict[str, Path],
    *,
    output_json: Path,
    output_report: Path,
) -> tuple[Path, dict[str, Any]]:
    campaign = campaign_dir.resolve()
    values = {name: _read_json(path.resolve()) for name, path in gate_paths.items()}
    kinds = {
        "campaign_a": "campaign_a",
        "campaign_b": "campaign_b",
        "stage6": "stage6",
        "stage7_a1": "stage7_a1",
        "stage7_a2": "stage7_a2",
        "stage7_b": "stage7_b",
        "verification": "verification",
    }
    gates = {
        name: _gate_passed(values[name], kind) for name, kind in kinds.items()
    }
    seal_checks: list[Check] = []
    sealed_runs: dict[str, dict[str, Any]] = {}
    for name in kinds:
        if name == "verification":
            continue
        if name == "stage7_a1":
            check, details = _part_a1_transitive_seal_check(
                gate_paths[name], gate_paths["stage7_b"]
            )
        elif (
            name == "stage7_a2"
            and values[name].get("test") == PART_A_COMPOSITE_TEST
        ):
            check, details = _composite_part_a_seal_check(
                gate_paths[name], gate_paths["stage7_b"]
            )
        else:
            check, details = _sealed_run_check(
                name,
                gate_paths[name],
                allow_partial_subtest=name == "stage7_a1",
            )
        seal_checks.append(check)
        sealed_runs[name] = details
        gates[name] = gates[name] and check.passed
    gates["stage7_b_attempted"] = values["stage7_b"].get("status") in {
        "pass",
        "fail",
    }
    checks = [
        Check(name, gates[name], _sha256_file(gate_paths[name].resolve()))
        for name in kinds
    ] + seal_checks
    decision = _decision(gates)
    if decision not in DECISIONS:
        raise RuntimeError(f"invalid decision {decision!r}")
    history = _active_run_history(campaign)
    if any(item["capture_active"] for item in history):
        raise RuntimeError("an active capture remains; Stage 8 is offline only")
    stage7_b = values["stage7_b"]
    final_code = stage7_b.get("transactions", {}).get("final_code")
    if decision == "dual_core_frequency_control_endurance_passed" and not isinstance(
        final_code, int
    ):
        raise ValueError("passed Stage 7B gate has no integer final code")
    if final_code is None:
        confirmed = [
            item["final_confirmed_code"]
            for item in history
            if item["final_confirmed_code"] is not None
        ]
        final_code = confirmed[-1] if confirmed else None
    goal, goal_rationale = _next_goal(decision)
    source_evidence = {
        name: {
            "path": str(path.resolve()),
            "sha256": _sha256_file(path.resolve()),
        }
        for name, path in gate_paths.items()
    }
    rationale = {
        "blocked_before_active_control": "The first active campaign is not a verified pass.",
        "bounded_control_needs_revision": "Active control was attempted but at least one mandatory bounded campaign or endurance gate failed.",
        "bounded_frequency_acquisition_passed": "Both single-core acquisition campaigns pass, but the complete dual-core endurance gate is not established.",
        "dual_core_frequency_control_endurance_passed": "Both single-core acquisition campaigns, dual-core isolation, composite active confirmation and the bounded 24-hour endurance gate pass with exact replay.",
    }[decision]
    result = {
        "schema_version": 1,
        "tool": TOOL_VERSION,
        "decision": decision,
        "rationale": rationale,
        "checks": [asdict(item) for item in checks],
        "source_evidence": source_evidence,
        "sealed_run_audit": sealed_runs,
        "active_run_history": history,
        "stage7_endurance": stage7_b,
        "final_verification": values["verification"],
        "recommended_next_goal": {
            "goal": goal,
            "rationale": goal_rationale,
        },
        "claims_not_made": [
            "calibrated_absolute_frequency_accuracy",
            "utc_traceability",
            "phase_lock",
            "holdover",
            "oscilloscope_waveform_margin",
        ],
        "last_confirmed_code": final_code,
        "last_confirmed_code_hex": (
            f"0x{final_code:04X}" if isinstance(final_code, int) else "unavailable"
        ),
        "stage8_hardware_actuation": False,
    }
    before = dict(source_evidence)
    _atomic_write(output_json, json.dumps(result, indent=2, sort_keys=True) + "\n")
    _atomic_write(output_report, _render(result))
    after = {
        name: {
            "path": str(path.resolve()),
            "sha256": _sha256_file(path.resolve()),
        }
        for name, path in gate_paths.items()
    }
    if before != after:
        output_json.unlink(missing_ok=True)
        output_report.unlink(missing_ok=True)
        raise RuntimeError("source evidence changed during Stage 8 review")
    return output_report, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign_dir", type=Path)
    for name in (
        "campaign-a",
        "campaign-b",
        "stage6",
        "stage7-a1",
        "stage7-a2",
        "stage7-b",
        "verification",
    ):
        parser.add_argument(f"--{name}-gate", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args(argv)
    gate_paths = {
        "campaign_a": args.campaign_a_gate,
        "campaign_b": args.campaign_b_gate,
        "stage6": args.stage6_gate,
        "stage7_a1": args.stage7_a1_gate,
        "stage7_a2": args.stage7_a2_gate,
        "stage7_b": args.stage7_b_gate,
        "verification": args.verification_gate,
    }
    try:
        report, result = review(
            args.campaign_dir,
            gate_paths,
            output_json=args.output_json,
            output_report=args.output_report,
        )
    except (
        FileNotFoundError,
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as exc:
        parser.error(str(exc))
    print(report)
    return 0 if result["decision"] in {
        "bounded_frequency_acquisition_passed",
        "dual_core_frequency_control_endurance_passed",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
