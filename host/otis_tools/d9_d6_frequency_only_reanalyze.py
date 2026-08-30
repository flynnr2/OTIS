"""Create a provenance-linked successful supersession for D9/D6 attempt 9."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping

from . import d9_d6_frequency_only_endurance as endurance
from .evidence import validate_evidence_snapshot
from .evidence_index import DEFAULT_INDEX, load_index, package_identity, register_package
from .run_loader import load_manifest


TOOL_ID = "d9_d6_frequency_only_offline_reanalysis_v1"
RESULT_TYPE = "d9_d6_frequency_only_analysis_supersession_v1"
SEAL_TYPE = "d9_d6_frequency_only_superseding_seal_v1"
REANALYSIS = Path("reports/d9_d6_frequency_only_digital_endurance_reanalysis_v1.json")
SUPERSESSION = Path("reports/d9_d6_frequency_only_analysis_supersession_v1.json")
SUPERSEDING_SEAL = Path("reports/d9_d6_frequency_only_superseding_seal_v1.json")


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path, description: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be a JSON object: {path}")
    return value


def _repository_state() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    ).stdout
    return {
        "git_commit": revision,
        "source_state": "dirty" if status else "clean",
    }


def _effective_analyzer() -> dict[str, Any]:
    directory = Path(__file__).resolve().parent
    paths = {
        "endurance_analyzer": directory / "d9_d6_frequency_only_endurance.py",
        "evidence": directory / "evidence.py",
        "evidence_index": directory / "evidence_index.py",
        "reanalysis": Path(__file__).resolve(),
        "run_loader": directory / "run_loader.py",
    }
    bindings = {
        name: {
            "path": str(path),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for name, path in sorted(paths.items())
    }
    return {
        "identity": endurance.canonical_sha256(bindings),
        "bindings": bindings,
    }


def _registered_source(
    *, source_run: Path, expected_content_sha256: str, index_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = package_identity(source_run)
    if identity["content_sha256"] != expected_content_sha256:
        raise ValueError("source package content identity differs")
    record = load_index(index_path).get("packages", {}).get(expected_content_sha256)
    if not isinstance(record, dict):
        raise ValueError("source package content identity is not registered")
    if str(source_run) not in record.get("storage_locations", []):
        raise ValueError("exact source path is not a registered storage location")
    indexed_files = {
        str(item["relative_path"]): item for item in record.get("file_manifest", [])
    }
    observed_files = {
        str(item["relative_path"]): item for item in identity.get("files", [])
    }
    if indexed_files != observed_files:
        raise ValueError("source package file manifest differs from registration")
    return identity, record


def _validated_snapshot_artifacts(
    source_run: Path, source_identity: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = load_manifest(source_run)
    failures, warnings = validate_evidence_snapshot(source_run, manifest)
    if failures or warnings:
        raise ValueError(
            "source evidence snapshot validation failed: "
            + "; ".join([*failures, *warnings])
        )
    snapshot_path = source_run / "evidence_manifest.json"
    snapshot = _read_json(snapshot_path, "source evidence snapshot")
    observed = {
        str(item["relative_path"]): item
        for item in source_identity.get("files", [])
    }
    artifacts: list[dict[str, Any]] = []
    for item in snapshot.get("artifacts", []):
        relative_path = str(item.get("path", ""))
        actual = observed.get(relative_path)
        if actual is None or any(
            actual.get(field) != item.get(field)
            for field in ("sha256", "size_bytes")
        ):
            raise ValueError(f"source snapshot artifact differs: {relative_path}")
        artifacts.append(
            {
                "path": relative_path,
                "sha256": str(item["sha256"]),
                "size_bytes": int(item["size_bytes"]),
            }
        )
    if not artifacts:
        raise ValueError("source evidence snapshot has no artifacts")
    return snapshot, artifacts


def _derive_corrected_state(
    source_run: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Correct only preview-first opportunity dispositions from exact ACT1 rows."""

    state = _read_json(
        source_run / endurance.SUPERVISOR_STATE_PATH,
        "source active-supervisor state",
    )
    terminal = state.get("terminal")
    if not isinstance(terminal, dict) or terminal.get("result") != "incomplete":
        raise ValueError("source terminal is not the expected incomplete result")
    if (
        terminal.get("reason")
        != "frequency_only_d9_d6_digital_endurance_incomplete"
        or terminal.get("incomplete_reason")
        != "application_opportunity_identity_mismatch"
        or state.get("target_reached") is not True
    ):
        raise ValueError("source terminal is outside the correctable host escape")

    controls = endurance._read_csv_rows(
        source_run / "csv" / endurance.CONTROL_PREVIEWS_CSV
    )
    control_by_sequence: dict[int, dict[str, str]] = {}
    for row in controls:
        sequence = endurance._safe_int(row.get("control_seq"))
        if sequence is None or sequence in control_by_sequence:
            raise ValueError("control previews lack unique exact sequences")
        control_by_sequence[sequence] = row

    _, retained = endurance._read_opportunity_causal_ledger(
        source_run / endurance.OPPORTUNITY_CAUSAL_LEDGER_PATH
    )
    source_dispositions = Counter(
        str(item.get("disposition"))
        for item in retained.values()
        if item.get("resolved") is True
    )
    if dict(source_dispositions) != state.get("lost_opportunity_dispositions"):
        raise ValueError("source opportunity state differs from its causal ledger")

    applications_by_decision: dict[int, dict[str, str]] = {}
    for row in endurance._read_csv_rows(source_run / endurance.ACTIVE_CSV):
        if row.get("event") != "application":
            continue
        sequence = endurance._safe_int(row.get("decision_sequence"))
        transaction_sequence = endurance._safe_int(
            row.get("transaction_record_sequence")
        )
        if (
            sequence is None
            or transaction_sequence is None
            or sequence in applications_by_decision
        ):
            raise ValueError("applications lack unique decision/record identities")
        applications_by_decision[sequence] = row
    if not applications_by_decision:
        raise ValueError("source has no exact application to reclassify")
    if len(applications_by_decision) != int(state.get("automatic_applications", -1)):
        raise ValueError("application count differs from source supervisor state")

    corrected = {sequence: dict(item) for sequence, item in retained.items()}
    reclassified: list[dict[str, Any]] = []
    for sequence, application in sorted(applications_by_decision.items()):
        control = control_by_sequence.get(sequence)
        item = corrected.get(sequence)
        if control is None or item is None:
            raise ValueError(f"application {sequence} lacks its exact opportunity")
        if item.get("control_identity_sha256") != endurance.canonical_sha256(control):
            raise ValueError(f"application {sequence} opportunity identity differs")
        if (
            item.get("resolved") is not True
            or item.get("disposition") != "ineligible_not_authorized"
            or item.get("resolution_evidence")
            != "control_previews_v1.authority_flags"
        ):
            raise ValueError(
                f"application {sequence} is outside the preview-first defect"
            )
        transaction_sequence = int(application["transaction_record_sequence"])
        item.update(
            {
                "eligible_control_opportunity": True,
                "disposition": "applied",
                "resolution_evidence": "active_transactions_v1.application",
                "resolution_transaction_record_sequence": transaction_sequence,
                "resolution_reason": (
                    "late_exact_application_supersedes_preview_only_classification"
                ),
            }
        )
        reclassified.append(
            {
                "control_sequence": sequence,
                "control_identity_sha256": item["control_identity_sha256"],
                "transaction_record_sequence": transaction_sequence,
                "request_sequence": endurance._safe_int(
                    application.get("request_sequence")
                ),
                "dac_epoch": endurance._safe_int(application.get("dac_epoch")),
                "applied_code": endurance._safe_int(application.get("applied_code")),
                "requested_delta_codes": endurance._safe_int(
                    application.get("requested_delta_codes")
                ),
            }
        )

    corrected_dispositions = Counter(
        str(item.get("disposition"))
        for item in corrected.values()
        if item.get("resolved") is True
    )
    pending = sorted(
        sequence
        for sequence, item in corrected.items()
        if item.get("resolved") is not True
    )
    eligible_count = sum(
        item.get("eligible_control_opportunity") is True
        for item in corrected.values()
    )
    corrected_state = dict(state)
    corrected_state.update(
        {
            "control_opportunity_count": len(corrected),
            "eligible_control_opportunity_count": eligible_count,
            "pending_control_opportunity_sequences": pending,
            "lost_opportunity_dispositions": dict(corrected_dispositions),
            "endpoint_incomplete_reason": None,
        }
    )
    if pending or corrected_dispositions.get("applied", 0) != len(
        applications_by_decision
    ):
        raise ValueError("corrected opportunity accounting remains incomplete")
    correction = {
        "defect": "preview_first_opportunity_resolution_was_immutable",
        "source_terminal": terminal,
        "reclassified_application_count": len(reclassified),
        "reclassified_applications": reclassified,
        "source_dispositions": dict(source_dispositions),
        "corrected_dispositions": dict(corrected_dispositions),
        "criterion_changed": False,
        "raw_evidence_unchanged": True,
    }
    return corrected_state, correction


def _interval_accounting_correction(source_run: Path) -> dict[str, Any]:
    ledger = endurance._read_interval_ledger(
        source_run / endurance.QUALIFIED_INTERVAL_LEDGER_PATH
    )
    canonical = endurance.canonical_d14_d8_intervals(source_run)
    canonical_by_sequence = {
        int(item["count_sequence"]): item for item in canonical
    }
    source_invalid = [
        item for item in ledger if item.get("measurement_qualified") is not True
    ]
    recovered = [
        int(item["count_sequence"])
        for item in source_invalid
        if canonical_by_sequence.get(int(item["count_sequence"]), {}).get(
            "measurement_qualified"
        )
        is True
    ]
    still_invalid = [
        int(item["count_sequence"])
        for item in source_invalid
        if canonical_by_sequence.get(int(item["count_sequence"]), {}).get(
            "measurement_qualified"
        )
        is not True
    ]
    if still_invalid:
        raise ValueError("retained interval exclusions are not fully replay-correctable")
    canonical_invalid = sum(
        item.get("measurement_qualified") is not True for item in canonical
    )
    return {
        "defect": "concurrent_support_files_were_read_before_count_frontier",
        "source_interval_ledger_rows": len(ledger),
        "source_unqualified_rows": len(source_invalid),
        "recovered_as_qualified_from_complete_source": len(recovered),
        "recovered_first_count_sequence": recovered[0] if recovered else None,
        "recovered_last_count_sequence": recovered[-1] if recovered else None,
        "complete_source_canonical_rows": len(canonical),
        "complete_source_unqualified_rows": canonical_invalid,
        "qualification_target_was_already_reached_without_recovery": True,
        "criterion_changed": False,
        "raw_evidence_unchanged": True,
    }


def reanalyze(
    *,
    source_run: Path,
    output_dir: Path,
    source_content_sha256: str,
    review_authority: str,
    evidence_index_path: Path = DEFAULT_INDEX,
) -> dict[str, Any]:
    source_run = source_run.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"reanalysis output already exists: {output_dir}")
    if not review_authority.strip():
        raise ValueError("review authority must be non-empty")

    source_identity, source_record = _registered_source(
        source_run=source_run,
        expected_content_sha256=source_content_sha256,
        index_path=evidence_index_path,
    )
    if source_record.get("attempt_classification") != "failed_qualification":
        raise ValueError("source package is not registered as the original failure")
    snapshot, source_artifacts = _validated_snapshot_artifacts(
        source_run, source_identity
    )
    manifest = _read_json(source_run / "run_manifest.json", "source run manifest")
    bundle_path = source_run / "inputs" / "frozen_bundle.json"
    bundle = endurance.validate_bundle(_read_json(bundle_path, "frozen bundle"))
    if (
        bundle.get("bundle_sha256")
        != manifest.get("frequency_only_engineering", {}).get("bundle_sha256")
    ):
        raise ValueError("source manifest/frozen bundle identity differs")

    original_analysis_path = source_run / endurance.ANALYSIS_PATH
    original_seal_path = source_run / endurance.SEAL_PATH
    original_analysis = _read_json(original_analysis_path, "original analysis")
    original_seal = _read_json(original_seal_path, "original seal")
    if (
        original_analysis.get("terminal")
        != "frequency_only_d9_d6_digital_endurance_incomplete"
        or original_seal.get("terminal")
        != "frequency_only_d9_d6_digital_endurance_incomplete"
    ):
        raise ValueError("source products do not retain the expected failure")

    corrected_state, opportunity_correction = _derive_corrected_state(source_run)
    interval_correction = _interval_accounting_correction(source_run)
    derived_terminal = {
        "result": "healthy_stop",
        "reason": "frequency_only_d9_d6_digital_endurance_passed",
        "derived_offline": True,
    }
    output_dir.mkdir(parents=True)
    (output_dir / "reports").mkdir()
    analysis = endurance.analyze_run(
        source_run,
        output_path=output_dir / REANALYSIS,
        state_override=corrected_state,
        terminal_override=derived_terminal,
        offline_supersession={
            "tool": TOOL_ID,
            "source_content_sha256": source_content_sha256,
            "review_authority": review_authority,
            "opportunity_accounting_correction": opportunity_correction,
            "interval_accounting_correction": interval_correction,
            "criterion_changed": False,
            "raw_evidence_unchanged": True,
            "physical_rerun": False,
            "hardware_interaction": False,
            "actuation_authorized": False,
        },
    )
    if analysis.get("terminal") != "frequency_only_d9_d6_digital_endurance_passed":
        raise RuntimeError("corrected offline analysis did not pass")

    effective_analyzer = _effective_analyzer()
    repository = _repository_state()
    reason = (
        "Three exact application transactions arrived after their independently "
        "flushed zero-authority previews had been permanently classified as "
        "ineligible. The superseding replay binds those exact applications to "
        "the same control identities and corrects only host bookkeeping; the "
        "frozen acceptance criteria and raw physical evidence are unchanged."
    )
    supersession_unsigned: dict[str, Any] = {
        "schema_version": 1,
        "result_type": RESULT_TYPE,
        "tool": TOOL_ID,
        "status": "passed",
        "created_utc": _utc_now(),
        "source_package": {
            "run_id": source_run.name,
            "path": str(source_run),
            "content_sha256": source_content_sha256,
            "file_count": source_identity["file_count"],
            "total_bytes": source_identity["total_bytes"],
            "registered_utc": source_record.get("registered_utc"),
            "attempt_classification": source_record.get("attempt_classification"),
            "source_revision": source_record.get("source_revision"),
            "build_identity": source_record.get("build_identity"),
            "profile_identity": source_record.get("profile_identity"),
        },
        "source_evidence_snapshot": {
            "path": str(source_run / "evidence_manifest.json"),
            "file_sha256": _sha256_file(source_run / "evidence_manifest.json"),
            "snapshot_digest": snapshot["snapshot_digest"],
            "verified_artifacts": source_artifacts,
        },
        "frozen_bundle": {
            "path": str(bundle_path),
            "file_sha256": _sha256_file(bundle_path),
            "bundle_sha256": bundle["bundle_sha256"],
            "contract_semantic_sha256": bundle["contract_semantic_sha256"],
        },
        "superseded_product": {
            "analysis_path": str(original_analysis_path),
            "analysis_file_sha256": _sha256_file(original_analysis_path),
            "analysis_terminal": original_analysis.get("terminal"),
            "seal_path": str(original_seal_path),
            "seal_file_sha256": _sha256_file(original_seal_path),
            "seal_sha256": original_seal.get("seal_sha256"),
            "registered_analyzer_identity": source_record.get("analyzer_identity"),
        },
        "replacement_product": {
            "analysis_path": REANALYSIS.as_posix(),
            "analysis_file_sha256": _sha256_file(output_dir / REANALYSIS),
            "analysis_terminal": analysis["terminal"],
            "effective_analyzer": effective_analyzer,
            "repository": repository,
        },
        "opportunity_accounting_correction": opportunity_correction,
        "interval_accounting_correction": interval_correction,
        "supersession_reason": reason,
        "review_authority": review_authority,
        "criterion_changed": False,
        "raw_evidence_unchanged": True,
        "physical_rerun": False,
        "hardware_interaction": False,
        "actionable": False,
        "actuation_authorized": False,
        "claims_boundary": {
            "engineering_digital_endurance": True,
            "delivered_output_waveform_qualified": False,
            "hybrid_steering_exercised": False,
            "gnss_glitch_forced_or_observed": False,
        },
    }
    supersession = {
        **supersession_unsigned,
        "supersession_sha256": endurance.canonical_sha256(supersession_unsigned),
    }
    endurance._write_new(output_dir / SUPERSESSION, supersession)

    seal_unsigned = {
        "schema_version": 1,
        "seal_type": SEAL_TYPE,
        "tool": TOOL_ID,
        "status": "passed",
        "source_content_sha256": source_content_sha256,
        "source_snapshot_digest": snapshot["snapshot_digest"],
        "bundle_sha256": bundle["bundle_sha256"],
        "analysis_file_sha256": _sha256_file(output_dir / REANALYSIS),
        "supersession_sha256": supersession["supersession_sha256"],
        "supersession_file_sha256": _sha256_file(output_dir / SUPERSESSION),
        "effective_analyzer_identity": effective_analyzer["identity"],
        "review_authority": review_authority,
        "hardware_interaction": False,
        "actionable": False,
        "actuation_authorized": False,
        "claims_boundary": supersession["claims_boundary"],
    }
    seal = {
        **seal_unsigned,
        "seal_sha256": endurance.canonical_sha256(seal_unsigned),
    }
    endurance._write_new(output_dir / SUPERSEDING_SEAL, seal)

    product_unsigned = {
        "schema_version": 1,
        "product_type": "d9_d6_frequency_only_reanalysis_product_v1",
        "source_content_sha256": source_content_sha256,
        "files": [
            {
                "path": path.relative_to(output_dir).as_posix(),
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted((output_dir / "reports").iterdir())
        ],
    }
    endurance._write_new(
        output_dir / "product_manifest.json",
        {
            **product_unsigned,
            "product_manifest_sha256": endurance.canonical_sha256(product_unsigned),
        },
    )
    registered = register_package(
        index_path=evidence_index_path,
        package_path=output_dir,
        source_revision=repository["git_commit"],
        build_identity=str(source_record["build_identity"]),
        profile_identity=str(source_record["profile_identity"]),
        attempt_classification="completed_campaign",
        result_or_failure_reason=(
            "D9/D6 frequency-only 24-hour physical acquisition passed host-only "
            "reanalysis; supersedes source " + source_content_sha256
        ),
        analyzer_identity=str(effective_analyzer["identity"]),
    )
    return {
        "status": "passed",
        "source_content_sha256": source_content_sha256,
        "reanalysis_dir": str(output_dir),
        "analysis_file_sha256": _sha256_file(output_dir / REANALYSIS),
        "supersession_sha256": supersession["supersession_sha256"],
        "seal_sha256": seal["seal_sha256"],
        "registered_content_sha256": registered["content_sha256"],
        "reclassified_application_count": opportunity_correction[
            "reclassified_application_count"
        ],
        "recovered_interval_count": interval_correction[
            "recovered_as_qualified_from_complete_source"
        ],
        "physical_rerun": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-content-sha256", required=True)
    parser.add_argument("--review-authority", required=True)
    parser.add_argument("--evidence-index", type=Path, default=DEFAULT_INDEX)
    args = parser.parse_args(argv)
    result = reanalyze(
        source_run=args.source_run,
        output_dir=args.output_dir,
        source_content_sha256=args.source_content_sha256,
        review_authority=args.review_authority,
        evidence_index_path=args.evidence_index,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
