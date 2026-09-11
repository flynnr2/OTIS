from __future__ import annotations

from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json

import pytest

from host.otis_tools import adaptive_hybrid_activation
from host.otis_tools import evidence as evidence_module
from host.otis_tools import evidence_index as evidence_index_module
from host.otis_tools.adaptive_hybrid_contract import (
    CONTINGENT_72_HOUR_HYBRID_CONTROL,
    envelope_for_purpose,
)
from host.otis_tools.evidence import EvidenceError, create_evidence_snapshot
from host.otis_tools.evidence_index import (
    CURRENT_SEAL_PATH,
    HOST_REVIEW_RESOLUTION_PATH,
    _parser,
    _resolved_completion_terminal,
    load_index,
    mothball_package,
    package_identity,
    register_package,
    register_analysis_supersession,
    supersede_append_only_registration,
    validate_index,
    validate_completed_diagnostic_journal,
)
from host.otis_tools.run_loader import RunManifest


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def test_success_registration_uses_exact_null_completion_supersession(
    tmp_path: Path,
) -> None:
    original_analyzer = "a" * 64
    review_analyzer = "b" * 64
    terminal = {
        "result": "healthy_stop",
        "reason": "inhibited_zero_write_complete",
        "preliminary_decision": "pending_offline_scientific_analysis",
        "last_confirmed_code": None,
        "utc": "2026-09-09T17:01:54Z",
    }
    unsigned = {
        "schema_version": 1,
        "report_type": "adaptive_hybrid_hybrid_host_review_resolution_v1",
        "recorded_utc": "2026-09-09T17:10:00Z",
        "resolution": "deterministic_host_endpoint_mismatch_superseded",
        "original_hold_preserved": True,
        "physical_rerun": False,
        "device_or_actuator_io": False,
        "new_authority": False,
        "absent_artifacts": [
            "reports/adaptive_hybrid_setup_authority_v1.json"
        ],
        "source_sha256": {"supervisor_state": "c" * 64},
        "original_tool_sha256": {
            "adaptive_hybrid_analyze": original_analyzer
        },
        "review_tool_sha256": {
            "adaptive_hybrid_analyze": review_analyzer
        },
        "terminal": terminal,
    }
    resolution = {
        **unsigned,
        "resolution_sha256": sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    _write_json(tmp_path / HOST_REVIEW_RESOLUTION_PATH, resolution)
    completion = {"terminal": None, "orchestration_error": None}
    seal = {
        "host_review_resolution": {
            "path": HOST_REVIEW_RESOLUTION_PATH.as_posix(),
            "resolution_sha256": resolution["resolution_sha256"],
            "source_sha256": resolution["source_sha256"],
        }
    }

    observed, resolved = _resolved_completion_terminal(
        location=tmp_path,
        completion=completion,
        seal=seal,
        original_analyzer_sha256=original_analyzer,
        analyzer_identity=review_analyzer,
    )

    assert observed == terminal
    assert resolved is True

    resolution["physical_rerun"] = True
    unsigned = {
        key: value
        for key, value in resolution.items()
        if key != "resolution_sha256"
    }
    resolution["resolution_sha256"] = sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    seal["host_review_resolution"]["resolution_sha256"] = resolution[
        "resolution_sha256"
    ]
    _write_json(tmp_path / HOST_REVIEW_RESOLUTION_PATH, resolution)
    with pytest.raises(ValueError, match="review resolution differs"):
        _resolved_completion_terminal(
            location=tmp_path,
            completion=completion,
            seal=seal,
            original_analyzer_sha256=original_analyzer,
            analyzer_identity=review_analyzer,
        )


def test_register_cli_uses_exact_image_identity_option(tmp_path: Path) -> None:
    args = _parser().parse_args(
        [
            "--index", str(tmp_path / "index.json"), "register", str(tmp_path / "run"),
            "--source-revision", "revision-1", "--build-identity", "build-1",
            "--image-identity", "adaptive_hybrid_regulation",
            "--attempt-classification", "successful_rehearsal",
            "--result-or-failure-reason", "passed", "--analyzer-identity", "analyzer-1",
        ]
    )
    assert args.image_identity == "adaptive_hybrid_regulation"
    with pytest.raises(SystemExit):
        _parser().parse_args(
            [
                "--index", str(tmp_path / "index.json"), "register", str(tmp_path / "run"),
                "--source-revision", "revision-1", "--build-identity", "build-1",
                "--profile-identity", "adaptive_hybrid_regulation",
                "--attempt-classification", "successful_rehearsal",
                "--result-or-failure-reason", "passed", "--analyzer-identity", "analyzer-1",
            ]
        )
    supersede = _parser().parse_args(
        [
            "--index",
            str(tmp_path / "index.json"),
            "supersede-append-only-registration",
            "a" * 64,
            "b" * 64,
            "--reason",
            "offline finalization appended a seal",
            "--confirm-all-predecessor-files-retained",
        ]
    )
    assert supersede.confirm_all_predecessor_files_retained is True


def test_analysis_supersession_registration_is_idempotent_and_rejects_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index_path = tmp_path / "external/index.json"
    index = evidence_index_module._empty_index("2026-09-09T00:00:00Z")
    index["packages"]["a" * 64] = {
        "content_sha256": "a" * 64,
        "storage_locations": [str(tmp_path / "source")],
        "attempt_classification": "diagnostic",
    }
    evidence_index_module.save_index(index_path, index)
    validation = {
        "contract": evidence_index_module.ANALYSIS_SUPERSESSION_KIND,
        "source_content_sha256": "a" * 64,
        "original_seal_sha256": "b" * 64,
        "corrected_seal_sha256": "c" * 64,
        "corrected_analyzer_identity": "d" * 64,
        "primary_decision": "inhibited_zero_write_complete",
        "supersession_sha256": "e" * 64,
    }
    current_tool_requirements: list[bool] = []

    def validate(_location: Path, _index: dict, *, require_current_tools: bool):
        current_tool_requirements.append(require_current_tools)
        return dict(validation)

    monkeypatch.setattr(
        evidence_index_module,
        "_validated_analysis_supersession_artifact",
        validate,
    )
    first = tmp_path / "addendum-1"
    first.mkdir()
    (first / "seal.json").write_text("first\n", encoding="utf-8")

    record = register_analysis_supersession(
        index_path=index_path, addendum_path=first
    )
    repeated = register_analysis_supersession(
        index_path=index_path, addendum_path=first
    )
    assert repeated == record
    assert current_tool_requirements == [True, False]
    assert record["artifact_kind"] == (
        evidence_index_module.ANALYSIS_SUPERSESSION_KIND
    )
    assert record["supersession_validation"] == validation
    identity = package_identity(first)
    assert evidence_index_module._supersession_index_record_exact(
        record,
        content_sha256=identity["content_sha256"],
        identity=identity,
        validation=validation,
    )
    for field in (
        "artifact_kind",
        "source_content_sha256",
        "original_seal_sha256",
        "corrected_seal_sha256",
        "corrected_analyzer_identity",
        "supersession_validation",
    ):
        tampered = dict(record)
        tampered[field] = "tampered"
        assert not evidence_index_module._supersession_index_record_exact(
            tampered,
            content_sha256=identity["content_sha256"],
            identity=identity,
            validation=validation,
        )

    second = tmp_path / "addendum-2"
    second.mkdir()
    (second / "seal.json").write_text("different\n", encoding="utf-8")
    with pytest.raises(ValueError, match="conflicting analysis supersession"):
        register_analysis_supersession(
            index_path=index_path, addendum_path=second
        )


def test_completed_diagnostic_journal_validation_is_exact(tmp_path: Path) -> None:
    content = "a" * 64
    analyzer = "b" * 64
    seal_identity = "c" * 64
    timestamp = "2026-09-09T00:00:00Z"
    source = {
        "content_sha256": content,
        "path": str((tmp_path / "run").resolve()),
    }
    original_seal = {
        "tool_sha256": analyzer,
        "seal_sha256": seal_identity,
    }
    manifest = {
        "image_identity": "adaptive_hybrid_regulation",
        "firmware": {
            "source_revision": "d" * 40,
            "build_identity": "build",
        },
    }
    phase_details = {
        "capture_closed": {
            "capture_exit": 0,
            "capture_alive_at_entry": True,
            "automatic_abort_or_teardown": False,
            "host_review_required": True,
        },
        "completion": {
            "terminal": {
                "result": "healthy_stop",
                "reason": "inhibited_zero_write_complete",
                "last_confirmed_code": None,
            },
            "orchestration_error": "",
            "review_resolution": str(tmp_path / HOST_REVIEW_RESOLUTION_PATH),
        },
        "snapshot": {"path": str(tmp_path / "evidence_manifest.json")},
        "analysis": {
            "status": "review_required",
            "primary_decision": "operator_review_required",
            "tool_sha256": analyzer,
            "exact_lifecycle_records": {"exact": True},
        },
        "seal": {
            "path": str(tmp_path / CURRENT_SEAL_PATH),
            "seal_sha256": seal_identity,
        },
        "registration": {"content_sha256": content},
    }
    phase_order = tuple(phase_details)
    journal = {
        "contract": "otis_evidence_finalization_v1",
        "created_utc": timestamp,
        "updated_utc": timestamp,
        "expected_content_sha256": content,
        "index_path": str((tmp_path / "index.json").resolve()),
        "phase_order": list(phase_order),
        "phases": {
            phase: {"completed_utc": timestamp, "details": details}
            for phase, details in phase_details.items()
        },
        "primary_failure": None,
        "registration": {
            "analyzer_identity": analyzer,
            "attempt_classification": "diagnostic",
            "build_identity": "build",
            "image_identity": "adaptive_hybrid_regulation",
            "result_or_failure_reason": (
                "ADAPTIVE_HYBRID offline finalization recovery: "
                "operator_review_required"
            ),
            "source_revision": "d" * 40,
        },
        "required_seal": CURRENT_SEAL_PATH.as_posix(),
        "run_dir": str((tmp_path / "run").resolve()),
        "secondary_failures": [],
    }
    validate_completed_diagnostic_journal(
        journal,
        source=source,
        original_seal=original_seal,
        source_manifest=manifest,
    )

    for phase in phase_order:
        tampered = json.loads(json.dumps(journal))
        tampered["phases"][phase] = None
        with pytest.raises(ValueError, match="journal phase differs"):
            validate_completed_diagnostic_journal(
                tampered,
                source=source,
                original_seal=original_seal,
                source_manifest=manifest,
            )


def test_source_registration_projection_excludes_mutable_stewardship() -> None:
    record = {
        "content_sha256": "a" * 64,
        "file_count": 1,
        "total_bytes": 2,
        "file_manifest": [{"path": "raw", "sha256": "b" * 64}],
        "source_revision": "c" * 40,
        "build_identity": "build",
        "image_identity": "image",
        "attempt_classification": "diagnostic",
        "result_or_failure_reason": "retained",
        "analyzer_identity": "d" * 64,
        "storage_locations": ["/first"],
        "lifecycle_status": "active",
        "registered_utc": "2026-09-09T00:00:00Z",
        "mothball": None,
    }
    before = evidence_index_module.source_registration_projection(record)
    record["storage_locations"].append("/second")
    record["lifecycle_status"] = "mothballed"
    record["mothball"] = {"reason": "reviewed"}
    after = evidence_index_module.source_registration_projection(record)
    assert after == before


def test_supersession_nested_replay_semantics_are_exact() -> None:
    shared_maintenance = {
        "policy_id": "policy",
        "policy_sha256": "a" * 64,
        "decision_count": 0,
        "phase_nonzero_decision_count": 0,
        "phase_material_decision_count": 0,
        "unmatched_request_decision_sequences": [],
        "completed_response_decision_sequences": [],
        "all_response_checkpoints_passed": True,
        "comparisons": [],
    }
    original_maintenance = {
        **shared_maintenance,
        "exact": False,
        "replay_mode": "active",
        "controller_state_authority": "active",
    }
    corrected_maintenance = {
        **shared_maintenance,
        "exact": True,
        "applicability": "not_applicable",
        "reason": (
            "inhibited_zero_write_frozen_authority_forbids_controller_records"
        ),
        "replay_mode": "not_applicable_no_controller_authority",
        "controller_state_authority": "none",
    }
    assert evidence_index_module._maintenance_supersession_exact(
        original_maintenance, corrected_maintenance
    )
    corrected_maintenance["decision_count"] = 1
    assert not evidence_index_module._maintenance_supersession_exact(
        original_maintenance, corrected_maintenance
    )

    original_measurement = {
        "estimate_sequence_exact": True,
        "selected_count": 1,
        "selected_nonoverlap": True,
        "D10": {"authority": "evidence_only"},
        "D14": {"channel_exact": True},
        "comparisons": [
            {
                "estimate_id": "estimate-1",
                "total_counted_edges": 5_999_999_999,
                "absolute_frequency_difference_hz": 2.7e-10,
                "absolute_error_difference_hz": 2.7e-10,
                "pass": False,
            }
        ],
    }
    corrected_measurement = {
        **original_measurement,
        "calculation_domain": (
            "firmware_ieee754_binary64_then_fixed_12_decimal"
        ),
        "comparisons": [
            {
                "estimate_id": "estimate-1",
                "total_counted_edges": 5_999_999_999,
                "absolute_frequency_difference_hz": 1.45e-13,
                "absolute_error_difference_hz": 1.45e-13,
                "pass": True,
            }
        ],
    }
    assert evidence_index_module._measurement_supersession_exact(
        original_measurement, corrected_measurement
    )
    corrected_measurement["comparisons"][0][
        "absolute_frequency_difference_hz"
    ] = 6e-13
    assert not evidence_index_module._measurement_supersession_exact(
        original_measurement, corrected_measurement
    )
    corrected_measurement["comparisons"][0][
        "absolute_frequency_difference_hz"
    ] = float("nan")
    assert not evidence_index_module._measurement_supersession_exact(
        original_measurement, corrected_measurement
    )


def test_snapshot_rejects_symlink_in_retained_report_tree(tmp_path: Path) -> None:
    run = tmp_path / "run"
    reports = run / "reports"
    reports.mkdir(parents=True)
    manifest_path = run / "run_manifest.json"
    raw = run / "raw/serial.log"
    raw.parent.mkdir()
    raw.write_text("retained\n", encoding="utf-8")
    _write_json(manifest_path, {"schema_version": 1, "run_id": run.name})
    (run / "COMPLETE").write_text("complete\n", encoding="utf-8")
    (reports / "escaped.json").symlink_to(tmp_path / "outside.json")
    manifest = RunManifest(
        run,
        manifest_path,
        {
            "schema_version": 1,
            "run_id": run.name,
            "template": False,
            "files": [{"path": "raw/serial.log"}],
        },
    )

    with pytest.raises(EvidenceError, match="symbolic link"):
        create_evidence_snapshot(run, manifest=manifest)


def _register(index_path: Path, package: Path) -> dict:
    return register_package(
        index_path=index_path,
        package_path=package,
        source_revision="revision-1",
        build_identity="build-sha256-1",
        image_identity="adaptive_hybrid_regulation",
        attempt_classification="diagnostic",
        result_or_failure_reason="raw diagnostic evidence retained",
        analyzer_identity="platform-rehearsal-analyzer-1",
    )


def _parallel_register(arguments: tuple[str, str]) -> str:
    index, package = arguments
    return str(_register(Path(index), Path(package))["content_sha256"])


def test_package_identity_is_recursive_deterministic_and_content_addressed(
    tmp_path: Path,
) -> None:
    package = tmp_path / "run"
    package.mkdir()
    (package / "b.txt").write_text("two\n", encoding="utf-8")
    nested = package / "nested"
    nested.mkdir()
    (nested / "a.txt").write_text("one\n", encoding="utf-8")

    first = package_identity(package)
    second = package_identity(package)
    assert first == second
    assert first["file_count"] == 2
    assert [entry["relative_path"] for entry in first["files"]] == [
        "b.txt",
        "nested/a.txt",
    ]

    (nested / "a.txt").write_text("changed\n", encoding="utf-8")
    assert package_identity(package)["content_sha256"] != first["content_sha256"]


def test_register_validate_and_detect_package_mutation(tmp_path: Path) -> None:
    index_path = tmp_path / "external" / "index.json"
    package = tmp_path / "run"
    package.mkdir()
    evidence = package / "raw.csv"
    evidence.write_text("record\n", encoding="utf-8")

    record = _register(index_path, package)
    assert record["lifecycle_status"] == "active"
    assert validate_index(index_path)["valid"] is True

    evidence.write_text("mutated\n", encoding="utf-8")
    validation = validate_index(index_path)
    assert validation["valid"] is False
    assert validation["packages"][0]["locations"][0]["status"] == "mismatch"


def test_append_only_registration_supersession_preserves_both_identities(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "external/index.json"
    package = tmp_path / "run"
    package.mkdir()
    (package / "raw.csv").write_text("record\n", encoding="utf-8")
    predecessor = _register(index_path, package)
    (package / "final-seal.json").write_text("sealed\n", encoding="utf-8")
    successor = _register(index_path, package)

    assert validate_index(index_path)["valid"] is False
    with pytest.raises(ValueError, match="requires confirmation"):
        supersede_append_only_registration(
            index_path=index_path,
            predecessor_content_sha256=predecessor["content_sha256"],
            successor_content_sha256=successor["content_sha256"],
            reason="offline finalization appended the retained seal",
            confirm_all_predecessor_files_retained=False,
        )

    disposed = supersede_append_only_registration(
        index_path=index_path,
        predecessor_content_sha256=predecessor["content_sha256"],
        successor_content_sha256=successor["content_sha256"],
        reason="offline finalization appended the retained seal",
        confirm_all_predecessor_files_retained=True,
    )
    repeated = supersede_append_only_registration(
        index_path=index_path,
        predecessor_content_sha256=predecessor["content_sha256"],
        successor_content_sha256=successor["content_sha256"],
        reason="offline finalization appended the retained seal",
        confirm_all_predecessor_files_retained=True,
    )

    assert repeated == disposed
    assert disposed["lifecycle_status"] == "superseded_registration"
    disposition = disposed["registration_supersession"]
    assert disposition["successor_content_sha256"] == successor["content_sha256"]
    assert disposition["added_relative_paths"] == ["final-seal.json"]
    assert disposition["all_predecessor_files_retained_unchanged"] is True
    assert disposition["evidence_preserved"] is True
    assert disposition["data_deleted"] is False
    validation = validate_index(index_path)
    assert validation["valid"] is True
    predecessor_result = next(
        item
        for item in validation["packages"]
        if item["content_sha256"] == predecessor["content_sha256"]
    )
    assert predecessor_result["valid"] is True
    assert predecessor_result["locations"][0]["status"] == (
        "superseded_by_append_only_successor"
    )


def test_append_only_registration_supersession_rejects_changed_predecessor_file(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "external/index.json"
    package = tmp_path / "run"
    package.mkdir()
    raw = package / "raw.csv"
    raw.write_text("original\n", encoding="utf-8")
    predecessor = _register(index_path, package)
    raw.write_text("changed\n", encoding="utf-8")
    (package / "final-seal.json").write_text("sealed\n", encoding="utf-8")
    successor = _register(index_path, package)

    with pytest.raises(ValueError, match="not an exact append-only evolution"):
        supersede_append_only_registration(
            index_path=index_path,
            predecessor_content_sha256=predecessor["content_sha256"],
            successor_content_sha256=successor["content_sha256"],
            reason="must not conceal changed evidence",
            confirm_all_predecessor_files_retained=True,
        )
    assert load_index(index_path)["packages"][predecessor["content_sha256"]][
        "lifecycle_status"
    ] == "active"


def test_append_only_registration_supersession_tamper_invalidates_index(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "external/index.json"
    package = tmp_path / "run"
    package.mkdir()
    (package / "raw.csv").write_text("record\n", encoding="utf-8")
    predecessor = _register(index_path, package)
    (package / "final-seal.json").write_text("sealed\n", encoding="utf-8")
    successor = _register(index_path, package)
    supersede_append_only_registration(
        index_path=index_path,
        predecessor_content_sha256=predecessor["content_sha256"],
        successor_content_sha256=successor["content_sha256"],
        reason="offline finalization appended the retained seal",
        confirm_all_predecessor_files_retained=True,
    )
    index = load_index(index_path)
    index["packages"][predecessor["content_sha256"]][
        "registration_supersession"
    ]["data_deleted"] = True
    evidence_index_module.save_index(index_path, index)

    assert validate_index(index_path)["valid"] is False


def test_append_only_registration_requires_live_in_place_successor(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "external/index.json"
    original_location = tmp_path / "run"
    original_location.mkdir()
    (original_location / "raw.csv").write_text("record\n", encoding="utf-8")
    predecessor = _register(index_path, original_location)
    (original_location / "final-seal.json").write_text("sealed\n", encoding="utf-8")
    successor = _register(index_path, original_location)
    moved_location = tmp_path / "moved-run"
    original_location.rename(moved_location)
    index = load_index(index_path)
    index["packages"][successor["content_sha256"]]["storage_locations"].append(
        str(moved_location)
    )
    evidence_index_module.save_index(index_path, index)

    with pytest.raises(ValueError, match="not an exact append-only evolution"):
        supersede_append_only_registration(
            index_path=index_path,
            predecessor_content_sha256=predecessor["content_sha256"],
            successor_content_sha256=successor["content_sha256"],
            reason="a shared missing pathname is insufficient",
            confirm_all_predecessor_files_retained=True,
        )


def test_append_only_successor_mutation_invalidates_disposition(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "external/index.json"
    package = tmp_path / "run"
    package.mkdir()
    (package / "raw.csv").write_text("record\n", encoding="utf-8")
    predecessor = _register(index_path, package)
    (package / "final-seal.json").write_text("sealed\n", encoding="utf-8")
    successor = _register(index_path, package)
    supersede_append_only_registration(
        index_path=index_path,
        predecessor_content_sha256=predecessor["content_sha256"],
        successor_content_sha256=successor["content_sha256"],
        reason="offline finalization appended the retained seal",
        confirm_all_predecessor_files_retained=True,
    )

    (package / "later-mutation.txt").write_text("unexpected\n", encoding="utf-8")
    assert validate_index(index_path)["valid"] is False


def test_mothball_rejects_append_only_registration_disposition(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "external/index.json"
    package = tmp_path / "run"
    package.mkdir()
    (package / "raw.csv").write_text("record\n", encoding="utf-8")
    predecessor = _register(index_path, package)
    (package / "final-seal.json").write_text("sealed\n", encoding="utf-8")
    successor = _register(index_path, package)
    supersede_append_only_registration(
        index_path=index_path,
        predecessor_content_sha256=predecessor["content_sha256"],
        successor_content_sha256=successor["content_sha256"],
        reason="offline finalization appended the retained seal",
        confirm_all_predecessor_files_retained=True,
    )
    summary = tmp_path / "summary.md"
    summary.write_text("Reviewed.\n", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot be mothballed"):
        mothball_package(
            index_path=index_path,
            content_sha256=predecessor["content_sha256"],
            reviewed_summary_path=summary,
            reason="not a supported combined lifecycle",
            confirm_no_active_dependency=True,
        )
    assert validate_index(index_path)["valid"] is True


def test_duplicate_content_rejects_conflicting_provenance(tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    package = tmp_path / "run"
    package.mkdir()
    (package / "raw.csv").write_text("record\n", encoding="utf-8")
    _register(index_path, package)

    with pytest.raises(ValueError, match="different source_revision"):
        register_package(
            index_path=index_path,
            package_path=package,
            source_revision="other-revision",
            build_identity="build-sha256-1",
            image_identity="adaptive_hybrid_regulation",
            attempt_classification="diagnostic",
            result_or_failure_reason="all rehearsal gates passed",
            analyzer_identity="platform-rehearsal-analyzer-1",
        )


@pytest.mark.parametrize(
    "classification",
    ("successful_rehearsal", "successful_qualification", "completed_campaign"),
)
def test_success_classification_rejects_arbitrary_unsealed_directory(
    tmp_path: Path, classification: str
) -> None:
    package = tmp_path / "run"
    package.mkdir()
    (package / "raw.csv").write_text("record\n", encoding="utf-8")

    with pytest.raises(
        ValueError, match="successful (?:evidence registration requires|rehearsal package)"
    ):
        register_package(
            index_path=tmp_path / "index.json",
            package_path=package,
            source_revision="revision-1",
            build_identity="build-sha256-1",
            image_identity="adaptive_hybrid_regulation",
            attempt_classification=classification,
            result_or_failure_reason="claimed success",
            analyzer_identity="analyzer-1",
        )
    assert not (tmp_path / "index.json").exists()


def test_successful_rehearsal_dispatches_to_independent_package_validator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "rehearsal"
    package.mkdir()
    (package / "evidence.txt").write_text("retained\n", encoding="utf-8")
    observed: dict[str, object] = {}
    validation = {
        "contract": "otis_validated_success_package_v1",
        "evidence_snapshot_sha256": "1" * 64,
        "seal_path": "reports/adaptive_hybrid_operational_rehearsal_seal_v1.json",
        "seal_sha256": "2" * 64,
        "seal_status": "passed",
        "primary_decision": "operational_path_rehearsal_passed",
    }

    def validate(location: Path, **metadata: str) -> dict[str, str]:
        observed["location"] = location
        observed["metadata"] = metadata
        return validation

    monkeypatch.setattr(
        evidence_module,
        "validate_operational_rehearsal_package",
        validate,
        raising=False,
    )
    record = register_package(
        index_path=tmp_path / "index.json",
        package_path=package,
        source_revision="a" * 40,
        build_identity="b" * 64 + ":" + "c" * 64,
        image_identity="adaptive_hybrid_regulation",
        attempt_classification="successful_rehearsal",
        result_or_failure_reason="adaptive-hybrid operational rehearsal passed",
        analyzer_identity="d" * 64,
    )

    assert observed == {
        "location": package.resolve(),
        "metadata": {
            "source_revision": "a" * 40,
            "build_identity": "b" * 64 + ":" + "c" * 64,
            "image_identity": "adaptive_hybrid_regulation",
            "result_or_failure_reason": (
                "adaptive-hybrid operational rehearsal passed"
            ),
            "analyzer_identity": "d" * 64,
        },
    }
    assert record["package_validation"] == validation


def test_successful_qualification_derives_validation_from_completed_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = tmp_path / "run"
    (run / "raw").mkdir(parents=True)
    raw = run / "raw/serial.log"
    raw.write_text("retained serial evidence\n", encoding="utf-8")
    analyzer_identity = "a" * 64
    source_revision = "1" * 40
    build_identity = "source:configuration"
    primary_decision = "adaptive_hybrid_qualified_complete"
    manifest = {
        "schema_version": 1,
        "evidence_epoch": "OTIS_ADAPTIVE_HYBRID_EVIDENCE_EPOCH_1",
        "template": False,
        "run_id": run.name,
        "stage": "OTIS_ADAPTIVE_HYBRID_REGULATION_LIVE",
        "programme_id": "OTIS_ADAPTIVE_HYBRID_REGULATION_V1",
        "run_identity": "adaptive_hybrid_regulation:1",
        "image_identity": "adaptive_hybrid_regulation",
        "adaptive_hybrid": {"profile_id": "adaptive_hybrid_regulation"},
        "bench_attempt": envelope_for_purpose(
            CONTINGENT_72_HOUR_HYBRID_CONTROL
        ).as_dict(),
        "firmware": {
            "source_revision": source_revision,
            "build_identity": build_identity,
        },
        "policy": {"policy_id": "OTIS_ADAPTIVE_HYBRID_REGULATION_V1"},
        "host": {
            "tool_bindings": {
                "adaptive_hybrid_analyze": {"sha256": analyzer_identity}
            }
        },
        "files": [{"path": "raw/serial.log"}],
    }
    _write_json(run / "run_manifest.json", manifest)
    completion = {
        "completion": "adaptive_hybrid_finite_physical_campaign",
        "terminal": {
            "result": "healthy_stop",
            "reason": primary_decision,
            "preliminary_decision": "pending_offline_scientific_analysis",
            "primary_decision": None,
            "last_confirmed_code": 0xA84D,
        },
        "orchestration_error": None,
    }
    _write_json(run / "COMPLETE", completion)
    report = run / "reports/step_0001/record_0001.json"
    response = run / "carrier/responses/response_0001.json"
    _write_json(report, {"decision": "retained"})
    _write_json(response, {"acknowledgement": "retained"})
    _write_json(
        run / "reports/adaptive_hybrid_supervisor_state.json",
        {"qualified_d14_accepted_apertures": 259_200},
    )
    snapshot_path = create_evidence_snapshot(run)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    retained = {item["path"]: item["role"] for item in snapshot["artifacts"]}
    assert retained["COMPLETE"] == "completion_marker"
    assert retained["reports/step_0001/record_0001.json"] == "retained_evidence"
    assert retained["carrier/responses/response_0001.json"] == "retained_evidence"
    seal = {
        "schema_version": 1,
        "seal_type": "adaptive_hybrid_physical_seal_v1",
        "tool": "adaptive_hybrid_analyze_v1",
        "tool_sha256": analyzer_identity,
        "created_utc": "2026-09-09T00:00:00Z",
        "run_id": run.name,
        "run_identity": manifest["run_identity"],
        "build_identity": build_identity,
        "image_identity": manifest["image_identity"],
        "programme_id": manifest["programme_id"],
        "policy_id": manifest["policy"]["policy_id"],
        "status": "passed",
        "evidence_integrity": "passed",
        "scientific_outcome": "qualified_complete",
        "primary_decision": primary_decision,
        "terminal_result": "healthy_stop",
        "terminal_reason": primary_decision,
        "host_review_resolution": None,
        "checks": {"all_current_checks": True},
        "csv_validation": {},
        "exact_lifecycle_records": {},
        "maintenance_replay": {},
        "measurement_replay": {},
        "response_replay": {},
        "transaction_capsule_sha256": {},
        "evidence_snapshot": {
            "path": "evidence_manifest.json",
            "failures": [],
            "warnings": [],
        },
        "source_sha256": {"raw/serial.log": sha256(raw.read_bytes()).hexdigest()},
        "D10_semantics": {},
        "host_discrepancy_authority": {
            "review_required": False,
            "new_setup": False,
            "new_arm": False,
            "automatic_abort": False,
            "automatic_teardown": False,
            "failed_campaign": False,
            "raw_evidence_preserved": True,
        },
        "limitations": [],
    }
    seal["seal_sha256"] = sha256(
        json.dumps(seal, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    _write_json(run / CURRENT_SEAL_PATH, seal)
    monkeypatch.setattr(
        adaptive_hybrid_activation,
        "validate_frozen_run_manifest",
        lambda _path: manifest,
    )

    with pytest.raises(ValueError, match="metadata differs"):
        register_package(
            index_path=tmp_path / "external/index.json",
            package_path=run,
            source_revision=source_revision,
            build_identity=build_identity,
            image_identity="adaptive_hybrid_regulation",
            attempt_classification="successful_qualification",
            result_or_failure_reason=f"qualified: {primary_decision}",
            analyzer_identity="b" * 64,
        )

    record = register_package(
        index_path=tmp_path / "external/index.json",
        package_path=run,
        source_revision=source_revision,
        build_identity=build_identity,
        image_identity="adaptive_hybrid_regulation",
        attempt_classification="successful_qualification",
        result_or_failure_reason=f"qualified: {primary_decision}",
        analyzer_identity=analyzer_identity,
    )

    assert record["package_validation"] == {
        "contract": "otis_validated_success_package_v1",
        "evidence_snapshot_sha256": snapshot["snapshot_digest"],
        "seal_path": CURRENT_SEAL_PATH.as_posix(),
        "seal_sha256": seal["seal_sha256"],
        "seal_status": "passed",
        "evidence_integrity": "passed",
        "scientific_outcome": "qualified_complete",
        "primary_decision": primary_decision,
    }


def test_mothball_requires_dependency_confirmation_and_reviewed_summary(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "index.json"
    package = tmp_path / "run"
    package.mkdir()
    (package / "raw.csv").write_text("record\n", encoding="utf-8")
    record = _register(index_path, package)
    summary = tmp_path / "summary.md"
    summary.write_text("Reviewed result.\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no active dependency"):
        mothball_package(
            index_path=index_path,
            content_sha256=record["content_sha256"],
            reviewed_summary_path=summary,
            reason="superseded by reviewed result",
            confirm_no_active_dependency=False,
        )

    updated = mothball_package(
        index_path=index_path,
        content_sha256=record["content_sha256"],
        reviewed_summary_path=summary,
        reason="superseded by reviewed result",
        confirm_no_active_dependency=True,
    )
    assert updated["lifecycle_status"] == "mothballed"
    assert updated["mothball"]["reviewed_summary_sha256"]


def test_index_is_never_allowed_inside_git_repository(tmp_path: Path) -> None:
    package = tmp_path / "run"
    package.mkdir()
    with pytest.raises(ValueError, match="outside the Git repository"):
        load_index(Path(__file__).resolve().parents[1] / "evidence-index.json")


def test_parallel_registration_preserves_every_package(tmp_path: Path) -> None:
    index_path = tmp_path / "external" / "index.json"
    packages: list[Path] = []
    for ordinal in range(12):
        package = tmp_path / f"run-{ordinal}"
        package.mkdir()
        (package / "raw.csv").write_text(f"record-{ordinal}\n", encoding="utf-8")
        packages.append(package)

    with ProcessPoolExecutor(max_workers=6) as executor:
        identities = list(
            executor.map(
                _parallel_register,
                [(str(index_path), str(package)) for package in packages],
            )
        )

    index = load_index(index_path)
    assert len(set(identities)) == 12
    assert set(index["packages"]) == set(identities)
    assert validate_index(index_path)["valid"] is True
