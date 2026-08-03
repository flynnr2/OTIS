"""Produce the evidence-gated CX317 Stage 7 final-readiness decision.

The review is offline and non-actuating.  It validates sealed run identities,
binds every selected model/policy artifact, consumes the final software/build
verification record, and carries the earlier tolerance tables into one tracked
report.  A green software suite cannot override failed or missing bench
evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import argparse
import json
import tempfile
from typing import Any, Iterable

from .cx317_pps_plant_characterize import _markdown_table
from .evidence import validate_evidence_snapshot
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, COMPLETE_MARKER, load_manifest


TOOL_VERSION = "cx317_final_readiness_v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
DECISIONS = (
    "not_ready",
    "ready_for_more_observe_only_testing",
    "ready_for_separate_single_step_actuation_review",
)
PROVENANCE_HEADINGS = (
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


@dataclass(frozen=True)
class Check:
    identifier: str
    passed: bool
    evidence: str


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
        suffix=".tmp", delete=False,
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def _write_json(path: Path, value: Any) -> None:
    _write_atomic(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _unique_completed_run(campaign: Path, prefix: str) -> Path:
    matches = sorted(
        item for item in campaign.glob(f"{prefix}*")
        if item.is_dir() and (item / COMPLETE_MARKER).is_file()
    )
    if len(matches) != 1:
        raise ValueError(
            f"expected one completed {prefix} run under {campaign}, got {len(matches)}"
        )
    return matches[0]


def _seal_check(identifier: str, run_dir: Path) -> tuple[Check, dict[str, Any]]:
    manifest = load_manifest(run_dir)
    failures, warnings = validate_evidence_snapshot(run_dir, manifest)
    snapshot_path = run_dir / "evidence_manifest.json"
    snapshot = _read_json(snapshot_path) if snapshot_path.is_file() else {}
    passed = (
        (run_dir / COMPLETE_MARKER).is_file()
        and not failures
        and snapshot.get("run_state") == "complete"
    )
    evidence = {
        "run_id": manifest.run_id,
        "run_directory": str(run_dir),
        "evidence_manifest_sha256": (
            _sha256_file(snapshot_path) if snapshot_path.is_file() else None
        ),
        "snapshot_digest": snapshot.get("snapshot_digest"),
        "failures": failures,
        "warnings": warnings,
    }
    return Check(
        identifier,
        passed,
        f"run={manifest.run_id}; seal failures={len(failures)}; warnings={len(warnings)}",
    ), evidence


def _section(markdown: str, heading: str) -> str:
    marker = f"## {heading}"
    start = markdown.find(marker)
    if start < 0:
        raise ValueError(f"missing report section {heading!r}")
    following = markdown.find("\n## ", start + len(marker))
    end = len(markdown) if following < 0 else following
    return markdown[start:end].strip()


def _section_body(markdown: str, heading: str) -> str:
    section = _section(markdown, heading)
    return "\n".join(section.splitlines()[1:]).strip()


def _span(
    baseline: dict[str, Any], span_s: int, mode: str
) -> dict[str, Any]:
    matches = [
        item for item in baseline["span_statistics"]
        if item["span_seconds"] == span_s and item["mode"] == mode
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one {span_s} s {mode} baseline statistic")
    return matches[0]


def _drift(
    baseline: dict[str, Any], span_s: int, mode: str
) -> dict[str, Any]:
    matches = [
        item for item in baseline["linear_drift"]["by_estimator_span"]
        if item["span_seconds"] == span_s and item["mode"] == mode
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one {span_s} s {mode} drift result")
    return matches[0]


def _verification_checks(value: dict[str, Any]) -> list[Check]:
    if value.get("schema_version") != 1:
        raise ValueError("final verification schema_version must be 1")
    pytest_result = value["pytest"]
    matrix = value["firmware_matrix"]
    no_hardware = value["no_hardware_validation"]
    return [
        Check(
            "final_software_suite",
            pytest_result.get("result") == "pass"
            and int(pytest_result.get("failed", -1)) == 0
            and int(pytest_result.get("errors", -1)) == 0
            and int(pytest_result.get("passed", 0)) > 0,
            f"{pytest_result.get('passed')} passed, {pytest_result.get('skipped')} skipped, "
            f"{pytest_result.get('failed')} failed, {pytest_result.get('errors')} errors",
        ),
        Check(
            "final_firmware_matrix",
            matrix.get("result") == "pass"
            and int(matrix.get("expected_pass_profiles", -1))
            == int(matrix.get("passed_profiles", -2))
            and int(matrix.get("expected_fail_profiles", -1))
            == int(matrix.get("guarded_failures_observed", -2)),
            f"{matrix.get('passed_profiles')}/{matrix.get('expected_pass_profiles')} pass profiles; "
            f"{matrix.get('guarded_failures_observed')}/{matrix.get('expected_fail_profiles')} guarded failures",
        ),
        Check(
            "final_no_hardware_validation",
            no_hardware.get("result") == "pass",
            str(no_hardware.get("evidence", "unavailable")),
        ),
    ]


def _decision(checks: Iterable[Check], blockers: list[dict[str, str]]) -> str:
    if not all(item.passed for item in checks):
        return "not_ready"
    if any(item["status"] != "resolved" for item in blockers):
        return "ready_for_more_observe_only_testing"
    return "ready_for_separate_single_step_actuation_review"


def _future_experiment(decision: str) -> dict[str, Any]:
    """Describe the next evidence-gathering experiment without granting authority."""
    if decision == "not_ready":
        eligibility = (
            "not eligible: repair and revalidate every failed mandatory gate before "
            "proposing another hardware run"
        )
    elif decision == "ready_for_more_observe_only_testing":
        eligibility = (
            "eligible only for a new, separately authorized observe-only evidence-closure run"
        )
    else:
        eligibility = (
            "eligible only for a separately authored and approved single-step review; "
            "this report supplies no actuation authority"
        )
    return {
        "name": "CX317_OBSERVE_ONLY_EVIDENCE_CLOSURE",
        "authorization_status": "not_authorized_by_this_programme",
        "eligibility": eligibility,
        "feedback_derived_dac_commands": False,
        "automatic_actuation": False,
        "phase_1_static_metrology": {
            "starting_code": 43344,
            "starting_code_hex": "0xA950",
            "source": (
                "operator-selected and Stage 5/6 digitally verified fail-static state"
            ),
            "measurements": [
                "fresh connected Vc measurements at exact predeclared low, centre and high codes with documented calibration/uncertainty",
                "D8 duty cycle, rise/fall time and phase-margin evidence with a suitable oscilloscope",
                "GPS UART fix/lock/UTC/satellite/antenna state correlated with PPS evidence",
            ],
        },
        "phase_2_conditional_open_loop_settling": {
            "mode": "manual predetermined open loop only",
            "existing_reviewed_code_range": [43008, 43776],
            "existing_reviewed_code_range_hex": ["0xA800", "0xAB00"],
            "range_source": (
                "sealed Stage 5 characterization and carried physical/model provenance; "
                "this is not an actuation target"
            ),
            "exact_step_codes": "unavailable_pending_phase_1_and_separate_runbook",
            "sample_cadence": "unavailable_pending_noise_and_instrument_evidence",
            "dwell_duration": "unavailable_pending_measured_settling_design",
            "objective": (
                "measure settling t95 and quantify noise/uncertainty on the same "
                "topology, backend and selected estimator without feedback-derived writes"
            ),
        },
        "completion_gate": (
            "rerun the evidence-gated readiness review; do not request a single-step "
            "actuation review until combined uncertainty, settling, connected Vc, D8 "
            "waveform and GNSS-quality blockers are resolved"
        ),
    }


def _stage7_provenance(
    checks: list[Check], decision: str, verification: dict[str, Any],
    stage6: dict[str, Any], blockers: list[dict[str, str]],
) -> list[str]:
    check_map = {item.identifier: item for item in checks}
    pytest_result = verification["pytest"]
    matrix = verification["firmware_matrix"]
    rows = [
        (
            "sealed mandatory run evidence, run count",
            "exactly four completed and valid evidence seals: Stages 1, 3, 5 and replacement Stage 6",
            "architecture screen", "3, 4",
            "00_MASTER_UNATTENDED_PROMPT.md programme completion; each run evidence_manifest.json",
            "same campaign and exact declared hardware/backend evidence; diagnostic/unsealed attempts excluded",
            "validate each snapshot digest, file hash, evidence scope and emitted build provenance",
            "cryptographic identity only; physical measurement uncertainty remains in the underlying reports",
            f"{sum(check_map[name].passed for name in ('stage1_seal','stage3_seal','stage5_seal','stage6_seal'))}/4 valid",
            "pass" if all(check_map[name].passed for name in ('stage1_seal','stage3_seal','stage5_seal','stage6_seal')) else "fail",
            "Decision is not_ready; do not treat unsealed evidence as authoritative",
        ),
        (
            "final software regression, tests",
            "complete discovered suite must have zero failures and zero errors; skips must be individually explained",
            "architecture screen", "4",
            "07_FINAL_READINESS_REVIEW_PROMPT.md Audit; final verification JSON",
            "exact final source state in the isolated execution worktree",
            "pytest collection/execution totals recorded by the final verification step",
            "software test coverage is not physical bench evidence and cannot override a failed run",
            f"{pytest_result.get('passed')} passed; {pytest_result.get('skipped')} skipped; {pytest_result.get('failed')} failed; {pytest_result.get('errors')} errors",
            "pass" if check_map["final_software_suite"].passed else "fail",
            "Decision is not_ready until the regression is clean and skips are explained",
        ),
        (
            "final firmware matrix, profile count",
            "all declared expected-pass profiles compile/verify and every expected-fail guard fails for its declared reason",
            "architecture screen", "4",
            "07_FINAL_READINESS_REVIEW_PROMPT.md Audit; firmware/arduino/firmware_matrix.json; final matrix_summary.json",
            "exact final firmware source/toolchain/core provenance",
            "compare passed and guarded-failure totals with the declared matrix inventory",
            "build result is digital evidence; it does not prove the flashed physical waveform",
            f"{matrix.get('passed_profiles')}/{matrix.get('expected_pass_profiles')} pass; {matrix.get('guarded_failures_observed')}/{matrix.get('expected_fail_profiles')} guards",
            "pass" if check_map["final_firmware_matrix"].passed else "fail",
            "Decision is not_ready; do not flash or actuate an unverified profile",
        ),
        (
            "final static DAC state, code",
            "replacement Stage 6 must end with exactly one manually established 0xA950 / 43344 state and zero active/live updates",
            "hard safety limit", "2, 3, 4",
            "sealed replacement Stage 6 result static_dac/authority; operator-selected fail-static code",
            "actual assembled rig, exact AD5693R/CX317 topology, observe-only artifact",
            "exact digital requested/applied code and authority-field comparison",
            "connected Vc calibration remains unavailable; manufacturer/topology maximum screen is carried below",
            f"code {stage6.get('static_dac', {}).get('code')}; active update {stage6.get('authority', {}).get('active_live_update_codes')}",
            "pass" if check_map["final_static_no_authority"].passed else "fail",
            "Decision is not_ready; leave the last verified state static and request physical intervention if identity is lost",
        ),
        (
            "separate single-step review blockers, unresolved count",
            "zero unresolved physical/metrology/model blockers before the decision may reach separate_single_step_actuation_review",
            "architecture screen", "2, 3, 4, 5",
            "user source-hierarchy/fail-closed requirement; Stage 5/6 limitations; Stage 7 required decision",
            "the threshold is an explicitly conservative engineering assumption for review eligibility, not actuation permission",
            "count blocker rows whose status is not resolved",
            "unknown uncertainty cannot be converted into margin; no probabilistic coverage claim",
            f"{sum(item['status'] != 'resolved' for item in blockers)} unresolved; decision {decision}",
            "pass" if not any(item["status"] != "resolved" for item in blockers) else "unavailable",
            "Remain ready only for more observe-only testing; a later review needs new evidence and separate approval",
        ),
    ]
    return _markdown_table(
        PROVENANCE_HEADINGS,
        rows,
        alignments=("left",) * len(PROVENANCE_HEADINGS),
    )


def review(
    campaign_dir: Path,
    stage6_run: Path,
    verification_path: Path,
    *,
    output_json: Path,
    output_report: Path,
) -> tuple[Path, dict[str, Any]]:
    campaign = campaign_dir.resolve()
    stage6_run = stage6_run.resolve()
    if (stage6_run / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise RuntimeError("replacement Stage 6 capture is still active")

    stage1_run = _unique_completed_run(campaign, "stage1_smoke_")
    stage3_run = _unique_completed_run(campaign, "stage3_fixed_code_")
    stage5_run = _unique_completed_run(campaign, "stage5_fresh_session_smoke_")
    runs = {
        "stage1": stage1_run,
        "stage3": stage3_run,
        "stage5": stage5_run,
        "stage6": stage6_run,
    }
    checks: list[Check] = []
    seals: dict[str, Any] = {}
    for name, run_dir in runs.items():
        check, evidence = _seal_check(f"{name}_seal", run_dir)
        checks.append(check)
        seals[name] = evidence

    baseline_path = stage3_run / "derived/pps_cumulative_snapshot_span_v1/fixed_code_baseline_analysis_v1.json"
    selection_path = campaign / "stage4_estimator_selection/estimator_candidate_evaluation_v1.json"
    plant_path = stage5_run / "derived/cx317_pps_plant_characterization_v1/plant_characterization_v1.json"
    replay_path = campaign / "stage6_preparation/controller_replay_v1/controller_replay_v1.json"
    stage6_path = stage6_run / "derived/cx317_stage6_live_preview_v1/stage6_live_preview_v1.json"
    estimator_path = REPO_ROOT / "profiles/estimators/cx317_pps_gated_selected_v1.json"
    model_path = REPO_ROOT / "profiles/plant_models/cx317_pps_gated_v1.json"
    policy_path = REPO_ROOT / "profiles/discipline/cx317_pps_gated_i_only_preview_v1.json"
    verification_path = verification_path.resolve()
    stage4_report = campaign / "stage4_estimator_selection/STAGE_4_ESTIMATOR_SELECTION_REPORT.md"
    stage5_report = stage5_run / "reports/PLANT_CHARACTERIZATION.md"
    replay_report = campaign / "stage6_preparation/controller_replay_v1/CONTROLLER_REPLAY.md"
    stage6_report = stage6_run / "reports/STAGE6_LIVE_PREVIEW.md"
    json_sources = {
        "baseline": baseline_path,
        "selection": selection_path,
        "plant": plant_path,
        "controller_replay": replay_path,
        "stage6": stage6_path,
        "estimator": estimator_path,
        "plant_model": model_path,
        "policy": policy_path,
        "verification": verification_path,
    }
    report_sources = {
        "stage4_report": stage4_report,
        "stage5_report": stage5_report,
        "controller_replay_report": replay_report,
        "stage6_report": stage6_report,
    }
    sources = {**json_sources, **report_sources}
    values = {name: _read_json(path) for name, path in json_sources.items()}
    baseline = values["baseline"]
    selection = values["selection"]
    plant = values["plant"]
    replay = values["controller_replay"]
    stage6 = values["stage6"]
    estimator = values["estimator"]
    model = values["plant_model"]
    policy = values["policy"]
    verification = values["verification"]

    checks.extend([
        Check(
            "selected_estimator_identity",
            estimator.get("status") == "selected_observe_only"
            and stage6["identities"]["selected_estimator_sha256"]
            == _sha256_file(estimator_path),
            f"{estimator.get('profile_id')} / {_sha256_file(estimator_path)}",
        ),
        Check(
            "plant_model_identity",
            model.get("status", {}).get("control_ready") is False
            and model.get("status", {}).get("actuation_enabled") is False
            and stage6["identities"]["plant_model_sha256"]
            == _sha256_file(model_path),
            f"{model.get('model_id')} v{model.get('model_version')} / {_sha256_file(model_path)}",
        ),
        Check(
            "preview_policy_identity",
            policy.get("authority", {}).get("actionable") is False
            and policy["parameters"]["active_live_update_codes"] == 0
            and stage6["identities"]["policy_sha256"] == _sha256_file(policy_path),
            f"{policy.get('policy_id')} / {_sha256_file(policy_path)}",
        ),
        Check(
            "stage3_fixed_code_gate",
            baseline.get("source_immutability_verified") is True
            and baseline.get("invalid_interval_count") == 0
            and baseline.get("valid_adjacent_interval_count", 0) >= 21600,
            f"{baseline.get('valid_adjacent_interval_count')} valid / {baseline.get('invalid_interval_count')} invalid",
        ),
        Check(
            "stage4_selection_gate",
            selection.get("observed_stable_intervals", 0) >= 21600
            and selection.get("actuation_authority") is False,
            f"{selection.get('observed_stable_intervals')} stable intervals; selection tool authority={selection.get('actuation_authority')}",
        ),
        Check(
            "stage5_plant_gate",
            plant.get("exit_gate") == "pass_observe_only"
            and plant.get("source_immutability_verified") is True,
            f"{plant.get('exit_gate')}; gain samples={plant.get('plant_gain', {}).get('sample_count')}",
        ),
        Check(
            "controller_replay_gate",
            replay.get("exit_gate") == "pass_observe_only"
            and replay.get("passed_scenarios") == replay.get("scenario_count"),
            f"{replay.get('passed_scenarios')}/{replay.get('scenario_count')} scenarios",
        ),
        Check(
            "stage6_live_gate",
            stage6.get("exit_gate") == "pass_observe_only"
            and all(item.get("passed") for item in stage6.get("checks", [])),
            f"{stage6.get('exit_gate')}; {len(stage6.get('checks', []))} checks",
        ),
        Check(
            "final_static_no_authority",
            stage6.get("static_dac", {}).get("code") == 43344
            and stage6.get("static_dac", {}).get("feedback_derived_commands") is False
            and stage6.get("authority") == {
                "control_ready": False,
                "actuation_enabled": False,
                "actuation_authorized": False,
                "actionable": False,
                "active_live_update_codes": 0,
            },
            f"static={stage6.get('static_dac', {}).get('hex_code')}; authority={stage6.get('authority')}",
        ),
    ])
    checks.extend(_verification_checks(verification))

    blockers = [
        {
            "blocker": "calibrated combined frequency uncertainty",
            "status": "unavailable",
            "evidence": "; ".join(baseline.get("uncertainty_reason_codes", [])),
            "consequence": "no calibrated accuracy or uncertainty-qualified correction claim",
        },
        {
            "blocker": "measured CX317 settling t95 bounds",
            "status": "unavailable" if plant["settling"].get("t95_s_max") is None else "resolved",
            "evidence": plant["settling"]["interpretation"],
            "consequence": "900 s remains a model-use screen at 600 s resolution, not a measured time constant",
        },
        {
            "blocker": "fresh connected low/centre/high Vc characterization and calibrated voltage uncertainty",
            "status": "unavailable",
            "evidence": "Stage 5 limitations and plant-model unresolved_fields",
            "consequence": "retain code-domain observe-only model; no voltage-calibrated control claim",
        },
        {
            "blocker": "D8 physical duty/rise/fall/phase margin",
            "status": "not tested",
            "evidence": "no scope available; Stage 5 physical/electrical provenance",
            "consequence": "no physical waveform qualification or separate actuation review",
        },
        {
            "blocker": "GNSS fix/lock/UTC/PPS-quality qualification",
            "status": "unavailable",
            "evidence": "GPS UART physically wired but unused; PPS presence only",
            "consequence": "no reference-accuracy or holdover claim",
        },
    ]
    decision = _decision(checks, blockers)
    if decision not in DECISIONS:
        raise RuntimeError("internal invalid Stage 7 decision")

    span600 = _span(baseline, 600, "non_overlapping")
    drift600 = _drift(baseline, 600, "non_overlapping")
    source_evidence = {
        name: {"path": str(path), "sha256": _sha256_file(path)}
        for name, path in sources.items()
    }
    proposed_future_experiment = _future_experiment(decision)
    result = {
        "schema_version": 1,
        "tool_version": TOOL_VERSION,
        "decision": decision,
        "checks": [asdict(item) for item in checks],
        "seals": seals,
        "source_evidence": source_evidence,
        "identities": {
            "estimator_profile_sha256": _sha256_file(estimator_path),
            "plant_model_sha256": _sha256_file(model_path),
            "preview_policy_sha256": _sha256_file(policy_path),
            "stage6_firmware": stage6["identities"],
        },
        "estimator": estimator,
        "fixed_code_600_s": span600,
        "fixed_code_600_s_drift": drift600,
        "plant": {
            "gain": plant["plant_gain"],
            "crossing": plant["crossing"],
            "settling": plant["settling"],
            "hysteresis": plant["bidirectional_hysteresis"],
        },
        "policy": policy,
        "stage6": {
            "run_id": stage6.get("run_id"),
            "capture": stage6.get("capture"),
            "static_dac": stage6.get("static_dac"),
            "service_load": stage6.get("service_load"),
            "estimator_parity": stage6.get("estimator_parity"),
            "controller_parity": stage6.get("controller_parity"),
            "authority": stage6.get("authority"),
        },
        "verification": verification,
        "actuation_review_blockers": blockers,
        "proposed_future_experiment": proposed_future_experiment,
        "claims_not_made": [
            "calibrated_absolute_accuracy",
            "isolated_firmware_jitter",
            "physical_phase_or_duty_qualification",
            "connected_vc_calibration",
            "combined_uncertainty",
            "actuation_authority",
        ],
    }
    report = render_report(
        result,
        stage4_report=stage4_report,
        stage5_report=stage5_report,
        replay_report=replay_report,
        stage6_report=stage6_report,
    )
    _write_json(output_json, result)
    _write_atomic(output_report, report)
    source_evidence_after = {
        name: {"path": str(path), "sha256": _sha256_file(path)}
        for name, path in sources.items()
    }
    if source_evidence_after != source_evidence:
        output_json.unlink(missing_ok=True)
        output_report.unlink(missing_ok=True)
        raise RuntimeError("Stage 7 source evidence changed during review")
    return output_report, result


def render_report(
    result: dict[str, Any], *, stage4_report: Path, stage5_report: Path,
    replay_report: Path, stage6_report: Path,
) -> str:
    decision = result["decision"]
    checks = result["checks"]
    identities = result["identities"]
    fixed = result["fixed_code_600_s"]
    drift = result["fixed_code_600_s_drift"]
    plant = result["plant"]
    parameters = result["policy"]["parameters"]
    rules = result["policy"]["rules"]
    verification = result["verification"]
    experiment = result["proposed_future_experiment"]
    lines = [
        "# CX317 PPS-Gated Estimator/Control Programme Final Readiness",
        "",
        f"Decision: `{decision}`.",
        "",
        "This decision grants no DAC actuation authority. The rig remains at the exact verified fail-static code `0xA950` / `43344`; control readiness, actuation enablement, authorization and actionability remain false.",
        "",
        "## Rationale",
        "",
    ]
    if decision == "not_ready":
        lines.append("One or more mandatory evidence, parity, seal, build or verification gates failed. Failed software or bench evidence is not overridden by other passing checks.")
    elif decision == "ready_for_more_observe_only_testing":
        lines.append("All mandatory observe-only gates pass, but calibrated combined uncertainty, measured t95, fresh connected voltage characterization, physical D8 waveform qualification and GNSS quality qualification remain unavailable or untested. The evidence supports further observe-only work only.")
    else:
        lines.append("All mandatory observe-only gates and every separately enumerated review blocker are resolved. This permits only a new, separately approved single-step actuation review; it is not actuation permission.")
    lines.extend([
        "",
        "## Exit-gate audit",
        "",
        *_markdown_table(
            ("Check", "Result", "Evidence"),
            ((item["identifier"], "pass" if item["passed"] else "fail", item["evidence"]) for item in checks),
            alignments=("left", "left", "left"),
        ),
        "",
        "## Exact identities",
        "",
        *_markdown_table(
            ("Artifact", "SHA-256 / identity"),
            (
                ("selected estimator", identities["estimator_profile_sha256"]),
                ("PPS-gated CX317 plant model", identities["plant_model_sha256"]),
                ("I-only preview policy", identities["preview_policy_sha256"]),
                ("Stage 6 firmware source", identities["stage6_firmware"]["firmware_source_sha256"]),
                ("Stage 6 firmware configuration", identities["stage6_firmware"]["firmware_configuration_sha256"]),
                ("Stage 6 UF2", identities["stage6_firmware"]["firmware_uf2_sha256"]),
            ),
            alignments=("left", "left"),
        ),
        "",
        "## Estimator and fixed-code evidence",
        "",
        f"- authoritative estimator: `PPS_CUMULATIVE_SNAPSHOT_SPAN_V1`, `{parameters['estimator_span_s']} s` non-overlapping; count increment `{fixed['count_increment_hz']:.12g} Hz`; `{fixed['eligible_estimate_count']}` independent outputs",
        f"- fixed-code 600 s population standard deviation `{fixed['population_stddev_hz']:.12g} Hz`; range `{fixed['range_hz']:.12g} Hz`; empirical detection floor `{parameters['empirical_detection_floor_hz']:.12g} Hz`",
        f"- 600 s fitted drift `{drift['slope_hz_per_hour']:.12g} Hz/h`, characterization only; no causal or isolated-firmware attribution",
        f"- diagnostic estimator: `60 s` overlapping at one accepted interval cadence; it has no decision authority",
        "",
        "## Plant characterization",
        "",
        f"- measured local gain `{plant['gain']['minimum_hz_per_code']:.15g}..{plant['gain']['maximum_hz_per_code']:.15g} Hz/code`; median `{plant['gain']['median_hz_per_code']:.15g}` from `{plant['gain']['sample_count']}` finite-run samples",
        f"- crossing `{plant['crossing']['nominal_code_float']:.6f}`, rounded `0x{plant['crossing']['nominal_code_rounded']:04X}`; policy replay envelope `0x{parameters['crossing_envelope_min_code']:04X}..0x{parameters['crossing_envelope_max_code']:04X}`",
        f"- settling screen `{plant['settling']['declared_exclusion_s']} s` plus `{plant['settling']['fresh_selected_support_s']} s` fresh history = `{plant['settling']['conservative_history_reset_s']} s`; measured t95 remains unavailable",
        f"- observed interior hysteresis `{plant['hysteresis'][0]['absolute_equivalent_codes']:.6g}` and `{plant['hysteresis'][1]['absolute_equivalent_codes']:.6g}` equivalent codes; no population or endpoint bound",
        "",
        "## Proposed observe-only control policy",
        "",
        f"- I-only preview; deadband `{parameters['error_deadband_hz']:.15g} Hz`; integrator gain `{parameters['integrator_gain_codes_per_hz_per_decision']:.15g} codes/Hz/decision`",
        f"- proposed future maximum update and integrator limit `{parameters['proposed_future_maximum_update_codes']}` codes; active live update exactly `{parameters['active_live_update_codes']}` codes",
        f"- preview cadence `{parameters['preview_decision_cadence_s']} s`; proposed future minimum actuation cadence `{parameters['future_minimum_actuation_cadence_s']} s`; neither is actuation permission",
        f"- hard code clamp `0x{parameters['dac_min_code']:04X}..0x{parameters['dac_max_code']:04X}`; fail-static `0x{parameters['fail_static_code']:04X}`",
        f"- startup `{parameters['startup_warmup_s']} s`; DAC-epoch reset `{parameters['settling_exclusion_s']}+{parameters['fresh_support_after_settling_s']}={parameters['full_history_reset_s']} s`; recovery requires `{parameters['recovery_fresh_support_s']} s` fresh support",
        f"- anti-windup: {rules['anti_windup']}; fault recovery: {rules['fault_recovery']}; abort: {rules['abort']}",
        "",
        "## Remaining blockers and untested limitations",
        "",
        *_markdown_table(
            ("Blocker", "Status", "Evidence", "Consequence"),
            ((item["blocker"], item["status"], item["evidence"], item["consequence"]) for item in result["actuation_review_blockers"]),
            alignments=("left", "left", "left", "left"),
        ),
        "",
        "No calibrated absolute accuracy, isolated firmware jitter, physical phase/duty qualification, connected-Vc calibration, complete uncertainty budget or actuation authority is claimed.",
        "",
        "## Proposed future experiment",
        "",
        f"Proposal: `{experiment['name']}`. Authorization: `{experiment['authorization_status']}`; {experiment['eligibility']}.",
        "",
        f"1. Static metrology begins and remains at the independently verified fail-static state `{experiment['phase_1_static_metrology']['starting_code_hex']}` / `{experiment['phase_1_static_metrology']['starting_code']}`. Obtain fresh connected-Vc uncertainty, D8 waveform/phase-margin evidence and GPS-UART quality evidence. The exact measurement points and instrument procedures must be predeclared in a separate runbook.",
        f"2. Only after the static evidence passes, a separately authorized manual predetermined open-loop settling subcampaign may use the already reviewed `0xA800..0xAB00` characterization range. Exact step codes, sampling cadence and dwell duration remain explicitly unavailable until derived from Phase 1, measured noise and instrument capability; no convenient placeholder is proposed.",
        "3. The subcampaign may not calculate any DAC command from PPS/count/estimate/error/controller state, and it grants no automatic actuation. Its objective is to measure t95 and close the uncertainty/model-applicability gaps on the same topology, backend and selected estimator.",
        f"4. Completion gate: {experiment['completion_gate']}.",
        "",
        "## Final software and firmware verification",
        "",
        f"- pytest: `{verification['pytest']['passed']} passed`, `{verification['pytest']['skipped']} skipped`, `{verification['pytest']['failed']} failed`, `{verification['pytest']['errors']} errors`; skips: {verification['pytest'].get('skip_reasons', [])}",
        f"- firmware matrix: `{verification['firmware_matrix']['passed_profiles']}/{verification['firmware_matrix']['expected_pass_profiles']}` expected-pass profiles and `{verification['firmware_matrix']['guarded_failures_observed']}/{verification['firmware_matrix']['expected_fail_profiles']}` expected guard failures",
        f"- integrated no-hardware validation: `{verification['no_hardware_validation']['result']}` — {verification['no_hardware_validation'].get('evidence')}",
        "",
        "## Final-readiness tolerance provenance",
        "",
        *_stage7_provenance(
            [Check(item["identifier"], item["passed"], item["evidence"]) for item in checks],
            decision,
            verification,
            result["stage6"],
            result["actuation_review_blockers"],
        ),
        "",
        "## Carried-forward estimator-selection provenance",
        "",
        _section_body(stage4_report.read_text(encoding="utf-8"), "Tolerance provenance"),
        "",
        "## Carried-forward physical/electrical provenance",
        "",
        _section_body(stage5_report.read_text(encoding="utf-8"), "Pre-command physical and electrical tolerance provenance"),
        "",
        "## Carried-forward plant-characterization provenance",
        "",
        _section_body(stage5_report.read_text(encoding="utf-8"), "Plant-campaign tolerance provenance"),
        "",
        "## Carried-forward controller-policy provenance",
        "",
        _section_body(replay_report.read_text(encoding="utf-8"), "Tolerance provenance"),
        "",
        "## Carried-forward live-preview provenance",
        "",
        _section_body(stage6_report.read_text(encoding="utf-8"), "Tolerance provenance"),
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Produce the evidence-gated CX317 Stage 7 final-readiness review."
    )
    parser.add_argument("campaign_dir", type=Path)
    parser.add_argument("--stage6-run", type=Path, required=True)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report, result = review(
            args.campaign_dir,
            args.stage6_run,
            args.verification,
            output_json=args.output_json,
            output_report=args.output_report,
        )
    except (
        FileNotFoundError, KeyError, IndexError, TypeError, ValueError,
        RuntimeError, json.JSONDecodeError,
    ) as exc:
        parser.error(str(exc))
    print(report)
    return 0 if result["decision"] != "not_ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
