from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from host.otis_tools import evidence_package, run_spec
from host.otis_tools.adaptive_hybrid_contract import (
    CONTINGENT_72_HOUR_HYBRID_CONTROL,
    INHIBITED_ZERO_WRITE,
)
from host.otis_tools.firmware_artifact import validate_frozen_firmware_artifact
from tests.run_spec_fixtures import (
    build_synthetic_spec,
    canonical_sha256,
    synthetic_firmware_document,
)


def test_run_spec_is_inert_immutable_and_portable(monkeypatch, tmp_path: Path) -> None:
    spec = build_synthetic_spec(
        monkeypatch, tmp_path, purpose=CONTINGENT_72_HOUR_HYBRID_CONTROL
    )
    document = spec.document()
    assert document["contract"] == "otis_run_spec_v1"
    assert document["campaign"] == {
        "operation": "adaptive_hybrid_regulation_live",
        "bench_attempt": document["campaign"]["bench_attempt"],
    }
    assert (
        document["campaign"]["bench_attempt"]["purpose"]
        == CONTINGENT_72_HOUR_HYBRID_CONTROL
    )
    assert set(document["firmware"]) == {"artifact"}
    assert (
        document["host"]["toolset"]["toolset_sha256"]
        != document["firmware"]["artifact"]["source_sha256"]
    )
    frozen_tools = {item["path"] for item in document["host"]["toolset"]["entries"]}
    assert {"tools/rehearse_host.py", "tools/otis_rehearsal_device.py"} <= frozen_tools
    assert not {"bundle", "proposal", "activation"} & set(document)

    document["campaign"]["bench_attempt"]["authority"]["setup_application_limit"] = 999
    assert (
        spec.document()["campaign"]["bench_attempt"]["authority"][
            "setup_application_limit"
        ]
        == 1
    )
    assert run_spec.load_run_spec(spec.path).sha256 == spec.sha256


def test_spec_rejects_embedded_operator_authority(monkeypatch, tmp_path: Path) -> None:
    artifact = validate_frozen_firmware_artifact(synthetic_firmware_document(tmp_path))
    monkeypatch.setattr(run_spec, "load_firmware_artifact", lambda _path: artifact)
    with pytest.raises(ValueError, match="cannot contain operator authority"):
        run_spec.build_run_spec(
            firmware_manifest_path=tmp_path / "ignored.json",
            purpose=INHIBITED_ZERO_WRITE,
            output_path=tmp_path / "run_spec.json",
            operator_instruction_ref="operator said run",
        )


def test_simulated_record_is_pty_only_and_projects_zero_physical_authority(
    monkeypatch, tmp_path: Path
) -> None:
    spec = build_synthetic_spec(
        monkeypatch, tmp_path, purpose=CONTINGENT_72_HOUR_HYBRID_CONTROL
    )
    record = run_spec.create_run_record(
        spec,
        execution_kind="simulated",
        run_id="rehearsal-one",
        started_at_utc="2026-09-12T10:01:00Z",
        serial_device="/dev/ttys999",
        output_path=tmp_path / "run_manifest.json",
    )
    manifest = spec.runtime_manifest(record)
    assert manifest["execution_kind"] == "simulated"
    assert manifest["entry_authorization"] is None
    assert manifest["adaptive_hybrid"]["authority"]["physical_execution"] is False
    assert manifest["adaptive_hybrid"]["authority"]["firmware_flash_limit"] == 0
    assert manifest["host"]["serial_device"] == "/dev/ttys999"
    assert manifest["host"]["capture"] == run_spec.CAPTURE_CONFIG
    assert not {"bundle", "proposal", "activation"} & set(manifest)

    with pytest.raises(ValueError, match="actual PTY"):
        run_spec.create_run_record(
            spec,
            execution_kind="simulated",
            run_id="bad",
            started_at_utc="2026-09-12T10:01:00Z",
            serial_device="/dev/cu.usbmodem123",
            output_path=tmp_path / "bad.json",
        )


def _receipt(spec: run_spec.ValidatedRunSpec, package_path: Path) -> dict:
    document = spec.document()
    artifact = document["firmware"]["artifact"]
    required = run_spec.required_rehearsal_boundaries(spec)
    boundary_unsigned = {
        "schema_version": 1,
        "contract": run_spec.REHEARSAL_BOUNDARY_CONTRACT,
        "run_spec_sha256": spec.sha256,
        "required_boundaries": required,
        "boundary_results": {name: True for name in required},
    }
    boundary_report = {
        **boundary_unsigned,
        "report_sha256": canonical_sha256(boundary_unsigned),
    }
    boundary_path = package_path / run_spec.REHEARSAL_BOUNDARY_REPORT
    boundary_path.parent.mkdir(parents=True, exist_ok=True)
    boundary_path.write_text(
        json.dumps(boundary_report, sort_keys=True, indent=2) + "\n"
    )
    boundary_sha256 = (
        __import__("hashlib").sha256(boundary_path.read_bytes()).hexdigest()
    )
    unsigned = {
        "schema_version": 1,
        "contract": run_spec.REHEARSAL_RECEIPT_CONTRACT,
        "status": "passed",
        "run_spec_sha256": spec.sha256,
        "firmware_artifact_sha256": artifact["firmware_artifact_sha256"],
        "firmware_binary_sha256": artifact["uf2"]["sha256"],
        "host_toolset_sha256": spec.host_toolset_sha256,
        "campaign_envelope_sha256": document["campaign"]["bench_attempt"][
            "envelope_sha256"
        ],
        "package": {"path": str(package_path), "package_content_sha256": "8" * 64},
        "required_boundaries": required,
        "boundary_results": {name: True for name in required},
        "boundaries": {
            "path": run_spec.REHEARSAL_BOUNDARY_REPORT,
            "sha256": boundary_sha256,
        },
    }
    return {**unsigned, "receipt_sha256": canonical_sha256(unsigned)}


def test_entry_requires_sealed_exact_rehearsal_and_is_consumed_before_record(
    monkeypatch, tmp_path: Path
) -> None:
    spec = build_synthetic_spec(
        monkeypatch, tmp_path, purpose=CONTINGENT_72_HOUR_HYBRID_CONTROL
    )
    receipt = _receipt(spec, tmp_path / "rehearsal")
    monkeypatch.setattr(run_spec, "verify_current_host_toolset", lambda _spec: None)
    artifact = validate_frozen_firmware_artifact(spec.firmware)
    selected_firmware_manifest = tmp_path / "moved" / "firmware_build_manifest.json"
    observed_manifest: list[Path] = []

    def load_selected(path: Path):
        observed_manifest.append(path)
        return artifact

    monkeypatch.setattr(run_spec, "load_firmware_artifact", load_selected)
    moved_rehearsal = tmp_path / "moved-rehearsal"
    moved_boundary = moved_rehearsal / run_spec.REHEARSAL_BOUNDARY_REPORT
    moved_boundary.parent.mkdir(parents=True)
    moved_boundary.write_bytes(
        (tmp_path / "rehearsal" / run_spec.REHEARSAL_BOUNDARY_REPORT).read_bytes()
    )
    observed_packages: list[Path] = []

    def validate_selected_package(path: Path):
        observed_packages.append(path)
        return {
            "package_content_sha256": "8" * 64,
            "run_manifest": {"run_spec": {"sha256": spec.sha256}},
            "capture": {"integrity": "complete"},
            "analysis": {"status": "passed", "outcome": "interrupted_incomplete"},
            "inventory": [
                {
                    "path": run_spec.REHEARSAL_BOUNDARY_REPORT,
                    "sha256": receipt["boundaries"]["sha256"],
                }
            ],
        }

    monkeypatch.setattr(evidence_package, "validate_package", validate_selected_package)
    capability = run_spec.authorize_entry(
        spec,
        rehearsal_receipt=receipt,
        operator_instruction_ref="operator-session-42",
        attempt_reason="first authorized physical entry",
        firmware_manifest_path=selected_firmware_manifest,
        rehearsal_package_path=moved_rehearsal,
    )
    assert observed_packages == [moved_rehearsal]
    assert observed_manifest == [selected_firmware_manifest]
    assert capability.firmware_artifact.sha256 == artifact.sha256
    consumed = capability.consume(spec.sha256)
    with pytest.raises(ValueError, match="already consumed"):
        capability.consume(spec.sha256)
    record = run_spec.create_run_record(
        spec,
        execution_kind="physical",
        run_id="physical-one",
        started_at_utc="2026-09-12T10:02:00Z",
        serial_device="/dev/cu.usbmodem101",
        output_path=tmp_path / "run_manifest.json",
        consumed_entry=consumed,
    )
    assert record["entry_authorization"] == {
        "rehearsal_receipt_sha256": receipt["receipt_sha256"],
        "operator_instruction_ref": "operator-session-42",
        "attempt_reason": "first authorized physical entry",
    }
    with pytest.raises(ValueError, match="already recorded"):
        consumed.record_authorization(spec)


def test_rehearsal_receipt_rejects_package_or_boundary_substitution(
    monkeypatch, tmp_path: Path
) -> None:
    spec = build_synthetic_spec(
        monkeypatch, tmp_path, purpose=CONTINGENT_72_HOUR_HYBRID_CONTROL
    )
    receipt = _receipt(spec, tmp_path / "rehearsal")
    monkeypatch.setattr(run_spec, "verify_current_host_toolset", lambda _spec: None)
    monkeypatch.setattr(
        run_spec,
        "load_firmware_artifact",
        lambda _path: validate_frozen_firmware_artifact(spec.firmware),
    )
    monkeypatch.setattr(
        evidence_package,
        "validate_package",
        lambda _path: {
            "package_content_sha256": "9" * 64,
            "run_manifest": {"run_spec": {"sha256": spec.sha256}},
        },
    )
    with pytest.raises(ValueError, match="package content differs"):
        run_spec.authorize_entry(
            spec,
            rehearsal_receipt=receipt,
            operator_instruction_ref="operator",
            attempt_reason="attempt",
        )

    changed = deepcopy(receipt)
    changed["boundary_results"][run_spec.required_rehearsal_boundaries(spec)[0]] = False
    unsigned = {key: value for key, value in changed.items() if key != "receipt_sha256"}
    changed["receipt_sha256"] = canonical_sha256(unsigned)
    with pytest.raises(ValueError, match="does not prove"):
        run_spec.authorize_entry(
            spec,
            rehearsal_receipt=changed,
            operator_instruction_ref="operator",
            attempt_reason="attempt",
        )


def test_entry_rejects_boundary_report_not_matching_sealed_inventory(
    monkeypatch, tmp_path: Path
) -> None:
    spec = build_synthetic_spec(
        monkeypatch, tmp_path, purpose=CONTINGENT_72_HOUR_HYBRID_CONTROL
    )
    package_path = tmp_path / "rehearsal"
    receipt = _receipt(spec, package_path)
    artifact = validate_frozen_firmware_artifact(spec.firmware)
    monkeypatch.setattr(run_spec, "verify_current_host_toolset", lambda _spec: None)
    monkeypatch.setattr(run_spec, "load_firmware_artifact", lambda _path: artifact)
    monkeypatch.setattr(
        evidence_package,
        "validate_package",
        lambda _path: {
            "package_content_sha256": "8" * 64,
            "run_manifest": {"run_spec": {"sha256": spec.sha256}},
            "capture": {"integrity": "complete"},
            "analysis": {"status": "passed", "outcome": "interrupted_incomplete"},
            "inventory": [
                {
                    "path": run_spec.REHEARSAL_BOUNDARY_REPORT,
                    "sha256": receipt["boundaries"]["sha256"],
                }
            ],
        },
    )
    (package_path / run_spec.REHEARSAL_BOUNDARY_REPORT).write_text("{}\n")
    with pytest.raises(ValueError, match="boundary report bytes differ"):
        run_spec.authorize_entry(
            spec,
            rehearsal_receipt=receipt,
            operator_instruction_ref="operator",
            attempt_reason="attempt",
        )


def test_frozen_firmware_document_rejects_source_or_configuration_contradiction(
    tmp_path: Path,
) -> None:
    document = synthetic_firmware_document(tmp_path)
    assert (
        validate_frozen_firmware_artifact(document).build_identity
        == document["build_identity"]
    )
    document["source_revision"] = "9" * 40
    document["firmware_artifact_sha256"] = __import__(
        "host.otis_tools.firmware_artifact",
        fromlist=["firmware_artifact_identity_sha256"],
    ).firmware_artifact_identity_sha256(document)
    with pytest.raises(ValueError, match="contradict provenance"):
        validate_frozen_firmware_artifact(document)


def test_host_tool_change_changes_spec_without_changing_firmware(
    monkeypatch, tmp_path: Path
) -> None:
    first = build_synthetic_spec(
        monkeypatch, tmp_path / "first", purpose=INHIBITED_ZERO_WRITE
    )
    first_document = first.document()
    changed_toolset = deepcopy(first_document["host"]["toolset"])
    changed_toolset["entries"][0]["sha256"] = "a" * 64
    unsigned_toolset = {
        key: value for key, value in changed_toolset.items() if key != "toolset_sha256"
    }
    changed_toolset["toolset_sha256"] = canonical_sha256(unsigned_toolset)
    artifact = validate_frozen_firmware_artifact(first.firmware)
    monkeypatch.setattr(run_spec, "load_firmware_artifact", lambda _path: artifact)
    monkeypatch.setattr(run_spec, "_host_toolset", lambda: deepcopy(changed_toolset))
    second_path = tmp_path / "second" / "run_spec.json"
    second = run_spec.build_run_spec(
        firmware_manifest_path=tmp_path / "ignored.json",
        purpose=INHIBITED_ZERO_WRITE,
        output_path=second_path,
        created_utc="2026-09-12T10:00:00Z",
    )
    assert second.firmware == first.firmware
    assert second.sha256 != first.sha256
    assert second.host_toolset_sha256 != first.host_toolset_sha256


def test_firmware_artifact_identity_is_portable_across_recorded_paths(
    tmp_path: Path,
) -> None:
    from host.otis_tools import firmware_artifact

    original = synthetic_firmware_document(tmp_path / "builder-one")
    moved = deepcopy(original)
    for name in ("build_manifest", "uf2", "generated_header"):
        moved[name]["path"] = str(tmp_path / "archive" / Path(moved[name]["path"]).name)
    # A later host-only commit changes the retained build record's repository
    # context, but not the firmware artifact it records.
    moved["build_manifest"]["sha256"] = "a" * 64
    moved["build_manifest"]["size_bytes"] += 17
    moved["firmware_artifact_sha256"] = (
        firmware_artifact.firmware_artifact_identity_sha256(moved)
    )

    assert moved["firmware_artifact_sha256"] == original["firmware_artifact_sha256"]
    assert (
        validate_frozen_firmware_artifact(moved).sha256
        == original["firmware_artifact_sha256"]
    )

    moved["uf2"]["sha256"] = "b" * 64
    assert (
        firmware_artifact.firmware_artifact_identity_sha256(moved)
        != original["firmware_artifact_sha256"]
    )


def test_rehearsal_boundaries_are_purpose_specific(monkeypatch, tmp_path: Path) -> None:
    controlled = build_synthetic_spec(
        monkeypatch, tmp_path / "controlled", purpose=CONTINGENT_72_HOUR_HYBRID_CONTROL
    )
    inhibited = build_synthetic_spec(
        monkeypatch, tmp_path / "inhibited", purpose=INHIBITED_ZERO_WRITE
    )
    control_only = {
        "setup_arm_and_acknowledgements_exact",
        "two_progressive_transactions_complete",
        "metadata_hold_nonterminal_and_requalified",
    }
    assert control_only <= set(run_spec.required_rehearsal_boundaries(controlled))
    assert control_only.isdisjoint(run_spec.required_rehearsal_boundaries(inhibited))
    assert run_spec.required_rehearsal_boundaries(inhibited) == [
        "capture_and_supervisor_processes_ready",
        "startup_census_preceded_control_authority",
        "normal_transport_obstruction_detected",
        "priority_abort_delivered_before_capture_close",
        "capture_closed_and_offline_outcome_recorded",
    ]


def test_firmware_reproduction_is_explicit_and_reuses_recorded_session(
    monkeypatch, tmp_path: Path
) -> None:
    from host.otis_tools import firmware_artifact
    from tools import build_firmware

    artifact = validate_frozen_firmware_artifact(synthetic_firmware_document(tmp_path))
    retained = artifact.document()
    current = {
        "source_state": "clean",
        "source_sha256": retained["source_sha256"],
        "firmware_audit_revision": retained["source_revision"],
        "config_sha256": retained["configuration_sha256"],
        "firmware_inputs": retained["firmware_inputs"],
    }
    monkeypatch.setattr(build_firmware, "load_manifest", lambda: {"fixed": True})
    monkeypatch.setattr(
        build_firmware, "capture_source_state", lambda _manifest: current
    )
    observed: dict[str, object] = {}

    def build(_manifest, output_dir, *, arduino_cli, build_session_id):
        observed.update(
            output_dir=output_dir,
            arduino_cli=arduino_cli,
            build_session_id=build_session_id,
        )
        return {"build_manifest": str(tmp_path / "reproduced.json")}

    monkeypatch.setattr(build_firmware, "build_firmware", build)
    monkeypatch.setattr(
        firmware_artifact, "load_firmware_artifact", lambda _path: artifact
    )
    receipt = firmware_artifact.reproduce_firmware(
        artifact, output_dir=tmp_path / "output", arduino_cli="pinned-cli"
    )
    assert observed["build_session_id"] == retained["build_session_id"]
    assert observed["arduino_cli"] == "pinned-cli"
    assert receipt["status"] == "verified"
    assert receipt["uf2_sha256"] == retained["uf2"]["sha256"]
