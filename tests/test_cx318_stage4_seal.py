from __future__ import annotations

from hashlib import sha256
import csv
import json
from pathlib import Path

import pytest

from host.otis_tools.contracts import CONTRACT_FIELDS
from host.otis_tools.cx318_stage4_seal import (
    RAW_SERIAL_RELATIVE_PATH,
    REQUIRED_ANALYSIS_CHECKS,
    SOURCE_RPH_RELATIVE_PATH,
    Stage4SealError,
    _canonical_digest,
    seal,
)


def _write_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    (run / "raw").mkdir(parents=True)
    (run / "csv").mkdir()
    (run / "reports").mkdir()
    (run / "raw" / "serial.log").write_text("RPH,1,live\n", encoding="utf-8")
    hashes = "a" * 64
    rows = {
        "relative_phase_observations_v1": {
            "record_type": "RPH",
            "schema_version": "1",
            "phase_epoch": "1",
            "observation_sequence": "0",
            "capture_session": "1",
            "opening_snapshot_sequence": "1",
            "closing_snapshot_sequence": "1",
            "opening_reference_sequence": "1",
            "closing_reference_sequence": "1",
            "dac_epoch": "0",
            "source_backend": "pio_wait_cumulative_snapshot_dma_v1",
            "source_file_sha256": "live_stream_unsealed",
            "method_id": "CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1",
            "configuration_sha256": hashes,
            "relative_phase_cycles": "0",
            "relative_phase_time_ns": "0",
            "qualification_state": "epoch_open",
            "observation_age_s": "0",
            "discontinuity_reason": "reset",
            "calibrated_uncertainty_status": "unavailable",
        },
        "phase_estimator_outputs_v1": {
            "record_type": "PHE",
            "schema_version": "1",
            "phase_epoch": "1",
            "observation_sequence": "0",
            "source_relative_phase_observation": "RPH:1:0",
            "raw_relative_phase_cycles": "0",
            "raw_relative_phase_time_ns": "0",
            "filtered_relative_phase_cycles": "0",
            "estimator_id": "CX318_RELATIVE_PHASE_RAW_PLUS_SELECTED600_V1",
            "configuration_sha256": hashes,
            "qualification_state": "initializing",
            "uncertainty_status": "unavailable",
            "reason_codes": "selected_600_interval_frequency_initializing",
        },
        "hybrid_preview_decisions_v1": {
            "record_type": "HPR",
            "schema_version": "1",
            "preview_sequence": "1",
            "candidate_id": "p21600_cap1_v2",
            "candidate_configuration_sha256": hashes,
            "phase_estimator_id": "CX318_RELATIVE_PHASE_RAW_PLUS_SELECTED600_V1",
            "phase_estimator_configuration_sha256": hashes,
            "frequency_estimator_id": "cx317_selected_600s_nonoverlap_v1",
            "frequency_estimator_configuration_sha256": hashes,
            "configuration_sha256": hashes,
            "phase_epoch": "1",
            "observation_sequence": "0",
            "dac_epoch": "0",
            "decision_timestamp_ticks": "16000000",
            "time_domain": "rp2040_timer0",
            "source_phase_estimate": "PHE:1:0",
            "source_frequency_estimate": "unavailable",
            "raw_relative_phase_cycles": "0",
            "modeled_relative_phase_cycles": "0",
            "phase_bias_hz": "0",
            "actual_applied_code": "43008",
            "shadow_code_before": "43008",
            "shadow_code_after": "43008",
            "band_state_before": "OUTSIDE",
            "band_state_after": "OUTSIDE",
            "preview_state": "RELATIVE_PHASE_ACQUIRE",
            "decision_reason": "phase_epoch_reseed",
            "frequency_observation_event": "false",
            "counterfactual_decision": "false",
            "counterfactual_correction": "false",
            "counterfactual_code": "43008",
            "step_limited": "false",
            "range_clamped": "false",
            "correction_count": "0",
            "cumulative_movement_codes": "0",
            "alternating_correction_count": "0",
            "modeled_not_observed_after_divergence": "false",
            "uncertainty_status": "unavailable",
            "actionable": "false",
            "actuation_authorized": "false",
            "authorization_consumed": "false",
        },
    }
    filenames = {
        "relative_phase_observations_v1": "relative_phase_observations_v1.csv",
        "phase_estimator_outputs_v1": "phase_estimator_outputs_v1.csv",
        "hybrid_preview_decisions_v1": "hybrid_preview_decisions_v1.csv",
    }
    for contract, row in rows.items():
        with (run / "csv" / filenames[contract]).open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=CONTRACT_FIELDS[contract])
            writer.writeheader()
            writer.writerow({field: row.get(field, "") for field in CONTRACT_FIELDS[contract]})
    additional_filenames = {
        "count_observations_v1": "count_observations.csv",
        "pps_snapshots_v1": "pps_snapshots.csv",
        "health_v1": "health.csv",
        "environment_v1": "environment.csv",
        "dac_steps_v1": "dac_steps.csv",
        "active_transactions_v1": "active_transactions_v1.csv",
    }
    for contract, filename in additional_filenames.items():
        with (run / "csv" / filename).open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            csv.DictWriter(handle, fieldnames=CONTRACT_FIELDS[contract]).writeheader()
    (run / "reports" / "capture_device_state.json").write_text(
        "{}\n", encoding="utf-8"
    )
    all_filenames = {**additional_filenames, **filenames}
    manifest_path = run / "run_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "cx318-stage4-test",
                "stage": "CX318_STAGE4_NONACTUATING_LIVE_PREVIEW",
                "firmware": {"name": "cx318_preview", "version": "test"},
                "domains": [{"name": "rp2040_timer0", "nominal_hz": 16000000}],
                "evidence_artifacts": [
                    "reports/cx318_stage4_live_analysis_v1.json"
                ],
                "files": [
                    {
                        "path": f"csv/{filename}",
                        "contract": contract,
                    }
                    for contract, filename in all_filenames.items()
                ],
            }
        ),
        encoding="utf-8",
    )
    source_paths = [
        *(run / "csv" / filename for filename in all_filenames.values()),
        run / "raw" / "serial.log",
        run / "reports" / "capture_device_state.json",
    ]
    source_artifacts = {
        path.relative_to(run).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in source_paths
    }
    root = Path(__file__).resolve().parents[1]
    profile_identities = {
        "phase_selected_sha256": sha256(
            (root / "profiles/estimators/cx318_relative_phase_selected_v1.json").read_bytes()
        ).hexdigest(),
        "hybrid_selected_sha256": sha256(
            (root / "profiles/discipline/cx318_hybrid_preview_selected_v1.json").read_bytes()
        ).hexdigest(),
        "frequency_selected_sha256": sha256(
            (root / "profiles/estimators/cx317_pps_gated_selected_v1.json").read_bytes()
        ).hexdigest(),
    }
    (run / "reports" / "cx318_stage4_live_analysis_v1.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tool": "cx318_stage4_live_analyze_v1",
                "status": "passed",
                "run_id": "cx318-stage4-test",
                "run_manifest_sha256": sha256(manifest_path.read_bytes()).hexdigest(),
                "checks": [
                    {"identifier": identifier, "passed": True, "evidence": "test"}
                    for identifier in sorted(REQUIRED_ANALYSIS_CHECKS)
                ],
                "source_artifacts_sha256": dict(sorted(source_artifacts.items())),
                "selected_profile_contract": {"identities": profile_identities},
            }
        ),
        encoding="utf-8",
    )
    (run / "COMPLETE").write_text("\n", encoding="utf-8")
    return run


def test_stage4_post_capture_seal_creates_external_non_self_referential_binding(
    tmp_path: Path,
) -> None:
    run = _write_run(tmp_path)
    output = tmp_path / "bindings" / "stage4.json"
    raw_before = (run / RAW_SERIAL_RELATIVE_PATH).read_bytes()
    rph_before = (run / SOURCE_RPH_RELATIVE_PATH).read_bytes()

    binding = seal(run, output)

    assert output.is_file()
    assert (run / RAW_SERIAL_RELATIVE_PATH).read_bytes() == raw_before
    assert (run / SOURCE_RPH_RELATIVE_PATH).read_bytes() == rph_before
    assert binding["raw_serial"]["sha256"] == sha256(raw_before).hexdigest()
    assert binding["source_relative_phase"]["sha256"] == sha256(rph_before).hexdigest()
    assert binding["evidence_snapshot"]["created_by_this_seal"] is True
    assert "live_stream_unsealed" not in output.read_text(encoding="utf-8")
    assert all(item["path"] != output.name for item in binding["artifact_inventory"])
    payload = dict(binding)
    assert payload.pop("binding_sha256") == _canonical_digest(payload)
    assert binding["tool_identity"]["tool_id"] == "CX318_STAGE4_POST_CAPTURE_SEAL_V1"
    assert binding["profile_identities"]
    assert binding["build_identities"]["firmware_profile"]["profile_id"] == "cx318_stage4_nonactuating_preview"


def test_stage4_post_capture_seal_reuses_valid_snapshot(tmp_path: Path) -> None:
    run = _write_run(tmp_path)
    first = seal(run, tmp_path / "first.json")
    second = seal(run, tmp_path / "second.json")

    assert first["evidence_snapshot"]["created_by_this_seal"] is True
    assert second["evidence_snapshot"]["created_by_this_seal"] is False
    assert first["evidence_snapshot"]["sha256"] == second["evidence_snapshot"]["sha256"]


def test_stage4_post_capture_seal_rejects_active_capture_without_writing(tmp_path: Path) -> None:
    run = _write_run(tmp_path)
    output = tmp_path / "binding.json"
    (run / "capture_in_progress.flag").write_text("active\n", encoding="utf-8")

    with pytest.raises(Stage4SealError, match="capture is in progress"):
        seal(run, output)

    assert not output.exists()
    assert not (run / "evidence_manifest.json").exists()


def test_stage4_post_capture_seal_requires_derived_artifacts_declared_before_snapshot(
    tmp_path: Path,
) -> None:
    run = _write_run(tmp_path)
    manifest_path = run / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].pop()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(Stage4SealError, match="must be declared before evidence snapshot"):
        seal(run, tmp_path / "binding.json")

    assert not (run / "evidence_manifest.json").exists()


def test_stage4_post_capture_seal_rejects_failed_analysis(tmp_path: Path) -> None:
    run = _write_run(tmp_path)
    analysis_path = run / "reports/cx318_stage4_live_analysis_v1.json"
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    analysis["status"] = "failed"
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")

    with pytest.raises(Stage4SealError, match="identity/status is invalid"):
        seal(run, tmp_path / "binding.json")

    assert not (run / "evidence_manifest.json").exists()


def test_stage4_post_capture_seal_rejects_stale_analysis_sources(
    tmp_path: Path,
) -> None:
    run = _write_run(tmp_path)
    (run / RAW_SERIAL_RELATIVE_PATH).write_text(
        "RPH,1,replaced-after-analysis\n", encoding="utf-8"
    )

    with pytest.raises(Stage4SealError, match="stale for source artifacts"):
        seal(run, tmp_path / "binding.json")

    assert not (run / "evidence_manifest.json").exists()
