from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import shutil
import struct
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from host.otis_tools import adaptive_hybrid_bundle as bundle_module
from host.otis_tools import adaptive_hybrid_activation as activation_module
from host.otis_tools import adaptive_hybrid_analyze as analyze_module
from host.otis_tools import adaptive_hybrid_run as run_module
from host.otis_tools import adaptive_hybrid_supervisor as supervisor_module
from host.otis_tools import adaptive_hybrid_transactions as transactions_module
from host.otis_tools import evidence as evidence_module
from host.otis_tools.adaptive_hybrid_activation import (
    OPERATIONAL_REHEARSAL_REQUIRED_BOUNDARIES,
    operational_rehearsal_authorization_contract,
    validate_operational_rehearsal,
)
from host.otis_tools.adaptive_hybrid_analyze import _normalize_terminal
from host.otis_tools.adaptive_hybrid_bundle import (
    create_bundle,
    create_progressive_replay,
    _validate_build,
    validate_bundle,
    validate_frozen_bundle,
    validate_progressive_replay,
)
from host.otis_tools.authoritative_inputs import (
    ROOT_PROFILE,
    authoritative_binding,
    authoritative_summary,
    collect_authoritative_inputs,
)
from host.otis_tools.firmware_binary import (
    EXPECTED_GNSS_PACKET,
    REQUIRED_MARKERS,
    UF2_MAGIC_END,
    UF2_MAGIC_START_0,
    UF2_MAGIC_START_1,
    verify_uf2,
)
from tools import build_firmware
from host.otis_tools.adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    INHIBITED_ZERO_WRITE,
    SINGLE_AUTOMATIC_APPLICATION,
    envelope_for_purpose,
    programme_from_mapping,
)
from host.otis_tools.adaptive_hybrid_health import (
    SETUP_AUTHORITY_CONTRACT,
    SETUP_AUTHORITY_PATH,
    AdaptiveHybridSupervisorBase,
)
from host.otis_tools.adaptive_hybrid_supervisor import load_active_hybrid_spec
from host.otis_tools.adaptive_hybrid_monitor import _diagnostic_review_hold
from host.otis_tools.adaptive_hybrid_transactions import (
    AdaptiveHybridTransactionSupervisor,
    CampaignSpec,
)
from host.otis_tools.contracts import (
    CONTROL_PREVIEW_V1_FIELDS,
    CURRENT_PLANT_MODEL_ID,
    CURRENT_PLANT_MODEL_PATH,
    CURRENT_PLANT_MODEL_REF,
    TIGHT_DEADBAND_DECISION_V1_FIELDS,
    _check_control_preview_v1,
)
from host.otis_tools.capture_device import _require_exact_manifest, _split_targets


def _canonical(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _binding(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def _write_uf2(path: Path, payload: bytes) -> None:
    chunks = [payload[index : index + 256] for index in range(0, len(payload), 256)]
    blocks: list[bytes] = []
    for number, chunk in enumerate(chunks):
        block = bytearray(512)
        struct.pack_into(
            "<8I", block, 0,
            UF2_MAGIC_START_0, UF2_MAGIC_START_1, 0,
            0x10000000 + number * 256, len(chunk), number, len(chunks), 0,
        )
        block[32 : 32 + len(chunk)] = chunk
        struct.pack_into("<I", block, 508, UF2_MAGIC_END)
        blocks.append(bytes(block))
    path.write_bytes(b"".join(blocks))


@pytest.mark.parametrize(
    "source",
    (
        "analyzer_discrepancy",
        "parser_discrepancy",
        "independent_replay_discrepancy",
        "live_orchestration_discrepancy",
    ),
)
def test_host_consumer_discrepancy_enters_no_authority_review_hold(
    source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = object.__new__(supervisor_module.AdaptiveHybridSupervisor)
    supervisor.run_dir = tmp_path
    supervisor.state = {
        "host_verification_hold": None,
        "arm_pending": True,
        "arm_sent_at_utc": "2026-09-09T00:00:00Z",
        "terminal": None,
        "terminal_static_code": 43344,
    }
    saves: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    supervisor._save = lambda: saves.append(dict(supervisor.state))
    supervisor._programme_event = lambda _event, **values: events.append(values)
    monkeypatch.setattr(supervisor_module, "_read_csv", lambda _path: [])

    supervisor._enter_host_verification_hold(
        ValueError("retained host discrepancy"), source=source
    )

    hold = supervisor.state["host_verification_hold"]
    assert hold["review_status"] == "operator_review_required"
    assert hold["new_authority"] is False
    assert hold["capture_and_serial_owner_retained"] is True
    assert hold["evidence_ack_policy"] == "continue_exact_withhold_unverifiable"
    assert supervisor.state["arm_pending"] is False
    assert supervisor.state["arm_sent_at_utc"] is None
    assert supervisor.state["terminal"] is None
    assert saves and events

    supervisor._identity_ready = lambda _health: (_ for _ in ()).throw(
        AssertionError("held supervisor attempted setup/arm qualification")
    )
    supervisor._maybe_start_or_arm({})


def test_monitor_and_registration_classify_host_findings_as_review_only() -> None:
    hold = _diagnostic_review_hold(
        integrity_faults=["parser_discrepancy", "independent_replay_discrepancy"],
        supervisor_hold={
            "source": "host_verifier",
            "review_status": "operator_review_required",
        },
        orchestration_hold={
            "error_type": "RuntimeError",
            "review_status": "operator_review_required",
        },
    )
    assert hold is not None
    assert hold["scientific_status"] == "unclassified_pending_operator_review"
    assert hold["nonzero_exit_semantics"] == "attention_required_not_abort_authority"
    assert hold["authority"] == {
        "new_setup": False,
        "new_arm": False,
        "automatic_abort": False,
        "automatic_teardown": False,
        "failed_campaign": False,
    }
    registration = run_module._registration(
        activation={
            "firmware": {
                "source_revision": "a" * 40,
                "build_identity": "source:configuration",
            },
            "image_identity": "adaptive_hybrid_regulation",
        },
        status="review_required",
        reason="offline analyzer disagreement pending operator review",
        analyzer_identity="b" * 64,
    )
    assert registration["attempt_classification"] == "diagnostic"

    exact_nonpass_registration = run_module._registration(
        activation={
            "firmware": {
                "source_revision": "a" * 40,
                "build_identity": "source:configuration",
            },
            "image_identity": "adaptive_hybrid_regulation",
        },
        status="passed",
        reason=(
            "ADAPTIVE_HYBRID passed: "
            "adaptive_hybrid_authority_not_sustained"
        ),
        analyzer_identity="b" * 64,
    )
    assert (
        exact_nonpass_registration["attempt_classification"]
        == run_module.COMPLETED_INDEX_CLASSIFICATION
    )


def test_shared_analyzer_record_replay_has_no_manifest_or_authority_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transactions = [{"event": "manual_start"}]
    decisions = [{"record_type": "AHY"}]
    maintenance = [{"record_type": "AHM"}]
    spec = SimpleNamespace(run_identity="run", profile="image")
    policy = SimpleNamespace(policy_sha256="a" * 64)
    observed: dict[str, object] = {}

    def validate(*args: object, **kwargs: object) -> None:
        observed["transaction_validation"] = (args, kwargs)

    def replay(*args: object, **kwargs: object) -> dict[str, object]:
        observed["maintenance_replay"] = (args, kwargs)
        return {"exact": True}

    monkeypatch.setattr(analyze_module, "validate_transaction_history", validate)
    monkeypatch.setattr(
        analyze_module, "replay_adaptive_hybrid_maintenance_history", replay
    )
    result = analyze_module.replay_current_adaptive_hybrid_records(
        transactions=transactions,
        decisions=decisions,
        maintenance=maintenance,
        spec=spec,
        identities={"estimator_sha256": "b" * 64},
        expected_build_identity="build",
        policy=policy,
        policy_document={"policy_id": "policy"},
        expected_active_policy_sha256="a" * 64,
        estimator_sha256="b" * 64,
    )

    assert result == {
        "transaction_history_exact": True,
        "transaction_row_count": 1,
        "decision_row_count": 1,
        "maintenance_row_count": 1,
        "maintenance_replay": {"exact": True},
    }
    validation_args, validation_kwargs = observed["transaction_validation"]
    assert validation_args[:3] == (
        transactions,
        spec,
        {"estimator_sha256": "b" * 64},
    )
    assert validation_kwargs == {"dual_core": True}
    _replay_args, replay_kwargs = observed["maintenance_replay"]
    assert replay_kwargs["expected_run_identity"] == "run"
    assert replay_kwargs["expected_image_identity"] == "image"


def test_shared_analyzer_host_consumers_recompute_every_applicable_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = SimpleNamespace(root=tmp_path)
    spec = SimpleNamespace(minimum_code=0xA800, maximum_code=0xAB00)
    programme = SimpleNamespace(response_checkpoint_observational=True)
    source_hashes = iter(({"csv/records.csv": "1" * 64},) * 2)
    calls: list[str] = []

    monkeypatch.setattr(
        analyze_module, "_source_hashes", lambda _manifest: next(source_hashes)
    )
    monkeypatch.setattr(analyze_module, "_sha256_file", lambda _path: "2" * 64)
    monkeypatch.setattr(
        analyze_module,
        "_validate_manifest_csvs",
        lambda *_args, **_kwargs: {
            "active_transactions_v2": {
                "authority": "authoritative",
                "exact": True,
            },
            "raw_events_v1:EVT": {
                "authority": "fail_local",
                "exact": False,
            },
        },
    )
    monkeypatch.setattr(
        analyze_module,
        "require_exact_lifecycle_records",
        lambda _manifest: {"exact": True},
    )
    monkeypatch.setattr(
        analyze_module,
        "validate_evidence_snapshot",
        lambda *_args: ([], ["diagnostic warning"]),
    )
    monkeypatch.setattr(
        analyze_module,
        "_one_contract",
        lambda _manifest, contract: tmp_path / f"{contract}.csv",
    )

    def read_csv(path: Path) -> list[dict[str, str]]:
        calls.append(path.name)
        return [{"event": path.stem}]

    monkeypatch.setattr(analyze_module, "_read_csv", read_csv)
    monkeypatch.setattr(
        analyze_module,
        "replay_current_adaptive_hybrid_records",
        lambda **_kwargs: {
            "transaction_history_exact": True,
            "maintenance_replay": {"exact": True},
        },
    )
    monkeypatch.setattr(
        analyze_module,
        "_response_replay",
        lambda *_args, **_kwargs: (True, [{"exact": True}]),
    )
    monkeypatch.setattr(analyze_module, "_read_object", lambda _path: {"state": 1})
    monkeypatch.setattr(analyze_module, "_read_jsonl", lambda _path: [{"event": 1}])
    monkeypatch.setattr(
        analyze_module,
        "_capsules_exact",
        lambda *_args: (True, {"reports/step.json": "3" * 64}),
    )

    result = analyze_module.replay_current_adaptive_hybrid_host_consumers(
        manifest,
        spec=spec,
        identities={"estimator_sha256": "4" * 64},
        expected_build_identity="build",
        policy=SimpleNamespace(),
        policy_document={"policy_id": "policy"},
        expected_active_policy_sha256="5" * 64,
        estimator_sha256="4" * 64,
        response_policy_document={"policy_id": "response"},
        programme=programme,
    )

    assert result["exact"] is True
    assert all(result["checks"].values())
    assert calls == [
        "active_transactions_v2.csv",
        "active_hybrid_decisions_v2.csv",
        "active_hybrid_maintenance_v1.csv",
    ]
    assert result["csv_validation"]["raw_events_v1:EVT"] == {
        "authority": "fail_local",
        "exact": False,
    }
    assert result["consumer_scope"]["physical_D14_D8_measurement_replay"] == (
        "unexercised"
    )
    assert result["consumer_scope"]["D10_optional_event_csv"] == "fail_local"
    assert result["consumer_scope"]["physical_seal_construction"] == "unexercised"
    assert result["evidence_snapshot"]["warnings"] == ["diagnostic warning"]


def test_shared_analyzer_host_consumers_reject_source_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = SimpleNamespace(root=tmp_path)
    source_hashes = iter(({"a": "before"}, {"a": "after"}))
    monkeypatch.setattr(
        analyze_module, "_source_hashes", lambda _manifest: next(source_hashes)
    )
    monkeypatch.setattr(analyze_module, "_sha256_file", lambda _path: "1" * 64)
    monkeypatch.setattr(
        analyze_module,
        "_validate_manifest_csvs",
        lambda *_args, **_kwargs: {"x": {"authority": "authoritative", "exact": True}},
    )
    monkeypatch.setattr(
        analyze_module,
        "require_exact_lifecycle_records",
        lambda _manifest: {"exact": True},
    )
    monkeypatch.setattr(
        analyze_module, "validate_evidence_snapshot", lambda *_args: ([], [])
    )
    monkeypatch.setattr(
        analyze_module,
        "_one_contract",
        lambda _manifest, contract: tmp_path / f"{contract}.csv",
    )
    monkeypatch.setattr(analyze_module, "_read_csv", lambda _path: [])
    monkeypatch.setattr(
        analyze_module,
        "replay_current_adaptive_hybrid_records",
        lambda **_kwargs: {
            "transaction_history_exact": True,
            "maintenance_replay": {"exact": True},
        },
    )
    monkeypatch.setattr(
        analyze_module, "_response_replay", lambda *_args, **_kwargs: (True, [])
    )
    monkeypatch.setattr(analyze_module, "_read_object", lambda _path: {})
    monkeypatch.setattr(analyze_module, "_read_jsonl", lambda _path: [])
    monkeypatch.setattr(
        analyze_module, "_capsules_exact", lambda *_args: (True, {})
    )

    result = analyze_module.replay_current_adaptive_hybrid_host_consumers(
        manifest,
        spec=SimpleNamespace(minimum_code=0, maximum_code=1),
        identities={},
        expected_build_identity="build",
        policy=SimpleNamespace(),
        policy_document={},
        expected_active_policy_sha256="2" * 64,
        estimator_sha256="3" * 64,
        response_policy_document={},
        programme=SimpleNamespace(response_checkpoint_observational=False),
    )

    assert result["exact"] is False
    assert result["checks"]["source_evidence_immutable_during_replay"] is False


def test_complete_exact_act_is_durable_before_phase_acknowledgement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    def atomic(path: Path, value: dict) -> None:
        events.append(f"atomic:{path.name}")

    def fsync(path: Path) -> None:
        events.append(f"fsync:{path.name}")

    monkeypatch.setattr(transactions_module, "_atomic_json", atomic)
    monkeypatch.setattr(transactions_module, "_fsync_path", fsync)
    supervisor = AdaptiveHybridTransactionSupervisor(
        run_dir=tmp_path,
        command_fifo=tmp_path / "command.fifo",
        abort_fifo=tmp_path / "abort.fifo",
        spec=CampaignSpec(
            campaign="adaptive_hybrid_regulation",
            profile="adaptive_hybrid_regulation",
            run_identity="adaptive_hybrid_regulation:1",
            start_code=0xA83C,
            correction_limit=10,
            cumulative_limit=100,
        ),
        identities={},
        expected_build_identity="build",
        allow_manual_start=False,
        allow_arm=False,
        duration_s=None,
        dual_core_transactions=True,
    )
    supervisor._command = lambda command: events.append(f"command:{command}")
    supervisor._event = lambda *_args, **_kwargs: None
    row = {
        "transaction_record_sequence": "1",
        "request_sequence": "1",
        "event": "request_created",
        "event_timestamp_ticks": "123456789",
        "time_domain": "rp2040_monotonic_us64",
    }

    assert supervisor._preserve_and_acknowledge(row, 1)
    command_index = events.index("command:ACTIVE EVIDENCE 1 1")
    assert events.index("fsync:active_transactions_v2.csv") < command_index
    assert events.index("fsync:record_000001_request_created.json") < command_index


def test_programme_mapping_rejects_any_contradictory_current_identity() -> None:
    exact = {
        "programme_id": ADAPTIVE_HYBRID_PROGRAMME.programme_id,
        "image_identity": ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        "run_identity": ADAPTIVE_HYBRID_PROGRAMME.runtime_run_identity,
    }
    assert programme_from_mapping(exact) is ADAPTIVE_HYBRID_PROGRAMME
    for key in exact:
        contradictory = {**exact, key: "retired-or-unknown"}
        with pytest.raises(ValueError, match="non-current"):
            programme_from_mapping(contradictory)


def test_live_setup_command_and_retained_authority_use_current_exact_contract(
    tmp_path: Path,
) -> None:
    supervisor = object.__new__(AdaptiveHybridSupervisorBase)
    supervisor.expected_build_identity = "a" * 64 + ":" + "b" * 64
    supervisor.spec = SimpleNamespace(start_code=ADAPTIVE_HYBRID_PROGRAMME.setup_code)
    supervisor.run_dir = tmp_path
    supervisor.state = {
        "setup_authorization_sequence": 0,
        "setup_authority_path": None,
    }
    supervisor._save = lambda: None
    health = {
        ("adaptive_hybrid", "snapshot_generation_complete"): "17",
        ("adaptive_hybrid", "query_nonce"): "23",
        ("adaptive_hybrid", "uptime_s"): "100",
        ("adaptive_hybrid", "session_id"): "5",
    }

    command, request = supervisor._setup_command(health)
    assert command == (
        "ACTIVE SETUP 1 17 23 130 5 "
        f"0x{ADAPTIVE_HYBRID_PROGRAMME.setup_code:04X} 1 {'b' * 64}"
    )
    path = supervisor._retain_setup_authority(health, request)
    assert path == tmp_path / SETUP_AUTHORITY_PATH
    retained = json.loads(path.read_text(encoding="utf-8"))
    assert retained["contract"] == SETUP_AUTHORITY_CONTRACT
    assert retained["request"] == request
    unsigned = {key: value for key, value in retained.items() if key != "record_sha256"}
    assert retained["record_sha256"] == _canonical(unsigned)
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/adaptive_hybrid_setup_authority_v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(retained)


def test_progressive_replay_requires_current_semantics_not_only_a_hash() -> None:
    replay = create_progressive_replay()
    replay["checks"]["transaction_complete"] = False
    unsigned = {key: value for key, value in replay.items() if key != "report_sha256"}
    replay["report_sha256"] = _canonical(unsigned)

    with pytest.raises(ValueError, match="current deterministic replay"):
        validate_progressive_replay(replay)


def test_firmware_build_validation_rejects_copied_markers_without_reproduction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_manifest = build_firmware.load_manifest()
    source = {
        **build_firmware._capture_source_state(fixed_manifest),
        "source_state": "clean",
    }
    environment = {
        "arduino_cli_version": str(fixed_manifest["arduino_cli_version"]),
        "board_id": "test_board",
        "board_name": "test board",
        "core_installed_sha256": fixed_manifest["target"]["core_installed_sha256"],
        "toolchain_installed_sha256": fixed_manifest["toolchain"]["installed_sha256"],
        "core_path": "/test/core",
        "toolchain_path": "/test/toolchain",
        "compiler_identity": "test_compiler",
    }
    provenance = build_firmware.build_provenance(
        fixed_manifest, environment, source, "0123456789abcdef"
    )
    frozen_summary = provenance["authoritative_inputs"]
    uf2 = tmp_path / "adaptive_hybrid_regulation.uf2"
    semantic_payload = b"\0".join(
        [
            *REQUIRED_MARKERS.values(),
            EXPECTED_GNSS_PACKET,
            *(item["sha256"].encode("ascii") for item in frozen_summary["profiles"]),
        ]
    )
    payload = b"\0".join(
        [
            semantic_payload,
            *(
                value.encode("ascii")
                for value in build_firmware.generated_provenance_values(
                    provenance
                ).values()
            ),
        ]
    )
    _write_uf2(uf2, payload)
    generated_header = tmp_path / "otis_build_manifest.generated.h"
    generated_header.write_text(
        build_firmware.provenance_header(provenance), encoding="utf-8"
    )
    manifest = {
        "schema_version": 1,
        "capabilities": {
            "external_event_capture": {
                "pin": "D10",
                "channel": "CH0",
                "status": "not_implemented",
                "control_authority": False,
                "terminal_authority": False,
            }
        },
        "provenance": {
            **provenance,
        },
        "resource_budget": {"contract": "otis_firmware_resource_budget_v1", "status": "within_budget"},
        "binary_contract": {
            "contract": "otis_adaptive_hybrid_firmware_binary_v1",
            "status": "verified",
            "authority": {
                "reference": "D14",
                "oscillator_count": "D8_GPIO20_GPIN0",
                "d10_control_authority": False,
                "d9_control_authority": False,
                "d6_control_authority": False,
            },
            "required_markers": {
                "d14_reference": True,
                "d8_count_input": True,
                "d9_forwarded_output": True,
                "d6_fail_local_monitor": True,
                "gnss_metadata_hold": True,
                "image_id": True,
            },
            "exact_provenance_markers": {
                name.removeprefix("OTIS_BUILD_").lower(): True
                for name in build_firmware.generated_provenance_values(provenance)
            },
            "forbidden_markers_present": {"retired_command": False},
        },
        "artifacts": [
            {
                "name": uf2.name,
                "sha256": sha256(uf2.read_bytes()).hexdigest(),
                "size_bytes": uf2.stat().st_size,
            },
            {
                "name": generated_header.name,
                "sha256": sha256(generated_header.read_bytes()).hexdigest(),
                "size_bytes": generated_header.stat().st_size,
            },
        ],
    }
    manifest_path = tmp_path / "firmware_build_manifest.json"
    _write_json(manifest_path, manifest)

    marker_report = verify_uf2(
        uf2,
        authoritative_summary=frozen_summary,
        provenance=provenance,
    )
    assert all(marker_report["exact_provenance_markers"].values())

    monkeypatch.setattr(
        bundle_module,
        "_run_reproducible_firmware_build",
        lambda **_kwargs: ({"provenance": provenance}, b"genuine rebuilt UF2"),
    )
    with pytest.raises(ValueError, match="not the deterministic reproduced image"):
        _validate_build(manifest_path)

    manifest["provenance"]["source"]["state"] = "dirty"
    _write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="exact source/configuration identity"):
        _validate_build(manifest_path)
    manifest["provenance"]["source"]["state"] = "clean"

    _write_uf2(uf2, semantic_payload)
    manifest["artifacts"][0].update(
        sha256=sha256(uf2.read_bytes()).hexdigest(),
        size_bytes=uf2.stat().st_size,
    )
    _write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="exact build provenance markers"):
        _validate_build(manifest_path)

    other_provenance = build_firmware.build_provenance(
        fixed_manifest, environment, source, "fedcba9876543210"
    )
    _write_uf2(
        uf2,
        b"\0".join(
            [
                semantic_payload,
                *(
                    value.encode("ascii")
                    for value in build_firmware.generated_provenance_values(
                        other_provenance
                    ).values()
                ),
            ]
        ),
    )
    manifest["artifacts"][0].update(
        sha256=sha256(uf2.read_bytes()).hexdigest(),
        size_bytes=uf2.stat().st_size,
    )
    _write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="exact build provenance markers"):
        _validate_build(manifest_path)

    uf2.write_bytes(b"mutated firmware fixture")
    with pytest.raises(ValueError, match="UF2 identity differs"):
        _validate_build(manifest_path)


def test_deterministic_reproduction_requires_exact_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uf2 = tmp_path / "recorded.uf2"
    uf2.write_bytes(b"byte-identical image")
    provenance = {
        "source": {"git_commit": "a" * 40},
        "invocation": {"build_session_id": "0123456789abcdef"},
    }
    monkeypatch.setattr(
        bundle_module,
        "_run_reproducible_firmware_build",
        lambda **_kwargs: (
            {"provenance": {**provenance, "schema_version": 999}},
            uf2.read_bytes(),
        ),
    )

    with pytest.raises(ValueError, match="rebuild provenance differs"):
        bundle_module._verify_reproducible_firmware(
            provenance=provenance,
            recorded_uf2=uf2,
        )


def test_bundle_rejects_self_consistent_authority_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_manifest = tmp_path / "build.json"
    _write_json(build_manifest, {"build": "fixture"})
    firmware = {
        "image_id": ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        "build_identity": "a" * 64 + ":" + "b" * 64,
        "build_manifest": _binding(build_manifest),
    }
    monkeypatch.setattr(bundle_module, "_validate_build", lambda *_args, **_kwargs: firmware)
    bundle = create_bundle(build_manifest_path=build_manifest)
    path = tmp_path / "bundle.json"
    _write_json(path, bundle)
    assert validate_bundle(path)["authority"]["dac_write"] is False

    bundle["authority"]["dac_write"] = True
    unsigned = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    bundle["bundle_sha256"] = _canonical(unsigned)
    _write_json(path, bundle)
    with pytest.raises(ValueError, match="topology, limit, or authority"):
        validate_bundle(path)


def test_frozen_bundle_validation_does_not_repeat_firmware_reproduction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_manifest = tmp_path / "build.json"
    _write_json(build_manifest, {"build": "fixture"})
    firmware = {
        "image_id": ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        "build_identity": "a" * 64 + ":" + "b" * 64,
        "build_manifest": _binding(build_manifest),
    }
    reproduction_modes: list[bool] = []

    def fake_validate_build(
        *_args: object,
        verify_deterministic_reproduction: bool = True,
        **_kwargs: object,
    ) -> dict[str, object]:
        reproduction_modes.append(verify_deterministic_reproduction)
        return firmware

    monkeypatch.setattr(bundle_module, "_validate_build", fake_validate_build)
    bundle_path = tmp_path / "bundle.json"
    _write_json(bundle_path, create_bundle(build_manifest_path=build_manifest))
    assert reproduction_modes == [True]

    reproduction_modes.clear()
    validate_frozen_bundle(bundle_path)
    assert reproduction_modes == [False]

    validate_bundle(bundle_path)
    assert reproduction_modes == [False, True]

    recorded_binding = bundle_module._binding

    def changed_checkout_binding(path: Path) -> dict[str, object]:
        binding = recorded_binding(path)
        if path.suffix == ".py":
            return {**binding, "sha256": "f" * 64}
        return binding

    monkeypatch.setattr(bundle_module, "_binding", changed_checkout_binding)
    validate_frozen_bundle(bundle_path)
    with pytest.raises(ValueError, match="tool, topology, limit, or authority"):
        validate_bundle(bundle_path)


def test_live_supervisor_consumes_frozen_manifest_without_reproduction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_identity = "a" * 64 + ":" + "b" * 64
    manifest = {"firmware": {"build_identity": build_identity}}
    manifest_path = tmp_path / "run_manifest.json"
    _write_json(manifest_path, manifest)
    frozen_calls: list[Path] = []

    def frozen_validator(path: Path) -> dict[str, object]:
        frozen_calls.append(path)
        return manifest

    def current_validator(_path: Path) -> dict[str, object]:
        raise AssertionError("live supervisor repeated current firmware validation")

    monkeypatch.setattr(
        activation_module, "validate_frozen_run_manifest", frozen_validator
    )
    monkeypatch.setattr(
        activation_module, "validate_run_manifest", current_validator
    )
    spec = object()
    identities = object()
    monkeypatch.setattr(
        supervisor_module,
        "load_active_hybrid_spec",
        lambda _manifest: (spec, identities),
    )
    monkeypatch.setattr(
        supervisor_module,
        "AdaptiveHybridSupervisor",
        lambda **kwargs: kwargs,
    )

    result = supervisor_module.create_supervisor(
        manifest_path=manifest_path,
        run_dir=tmp_path,
        command_fifo=tmp_path / "normal.fifo",
        emergency_command_fifo=tmp_path / "emergency.fifo",
        abort_fifo=tmp_path / "abort.fifo",
        expected_build_identity=build_identity,
    )
    assert frozen_calls == [manifest_path]
    assert result["manifest"] == manifest


def test_live_manifest_requires_matching_current_reproduction_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activation = {"activation_sha256": "1" * 64}
    bundle = {
        "bundle_sha256": "2" * 64,
        "firmware": {
            "build_identity": "3" * 64 + ":" + "4" * 64,
            "uf2": {"sha256": "5" * 64},
        },
    }
    proposal = {"proposal_sha256": "6" * 64}
    monkeypatch.setattr(
        activation_module,
        "validate_activation",
        lambda *_args, **_kwargs: (activation, bundle, proposal),
    )

    *_, capability = activation_module.validate_activation_for_physical_entry(
        tmp_path / "activation.json"
    )
    activation_module._require_current_reproduction_capability(
        capability,
        activation=activation,
        bundle=bundle,
        proposal=proposal,
    )
    with pytest.raises(ValueError, match="current firmware reproduction capability"):
        activation_module._require_current_reproduction_capability(
            None,
            activation=activation,
            bundle=bundle,
            proposal=proposal,
        )
    with pytest.raises(ValueError, match="current firmware reproduction capability"):
        activation_module._require_current_reproduction_capability(
            replace(capability, uf2_sha256="7" * 64),
            activation=activation,
            bundle=bundle,
            proposal=proposal,
        )


def test_bundle_validation_consumes_embedded_profile_and_schema_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_manifest = tmp_path / "build.json"
    _write_json(build_manifest, {"build": "fixture"})
    firmware = {
        "image_id": ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        "build_identity": "a" * 64 + ":" + "b" * 64,
        "build_manifest": _binding(build_manifest),
    }
    monkeypatch.setattr(
        bundle_module, "_validate_build", lambda *_args, **_kwargs: firmware
    )
    bundle = create_bundle(build_manifest_path=build_manifest)
    assert len(bundle["authoritative_inputs"]["profiles"]) == 5
    assert len(bundle["authoritative_inputs"]["schemas"]) == 7
    assert bundle["policy"]["path"] == (
        "profiles/discipline/adaptive_hybrid_regulation_v1.json"
    )
    path = tmp_path / "bundle.json"
    _write_json(path, bundle)

    def live_profile_access_is_a_bug(*_args, **_kwargs):
        raise AssertionError("bundle validation read the live profile/schema checkout")

    monkeypatch.setattr(
        bundle_module, "collect_authoritative_inputs", live_profile_access_is_a_bug
    )
    assert validate_bundle(path)["bundle_sha256"] == bundle["bundle_sha256"]

    bundle["authoritative_inputs"]["schemas"] = [
        item
        for item in bundle["authoritative_inputs"]["schemas"]
        if item["path"] != "schemas/run_evidence_v1.schema.json"
    ]
    input_unsigned = {
        key: value
        for key, value in bundle["authoritative_inputs"].items()
        if key != "set_sha256"
    }
    bundle["authoritative_inputs"]["set_sha256"] = _canonical(input_unsigned)
    bundle_unsigned = {
        key: value for key, value in bundle.items() if key != "bundle_sha256"
    }
    bundle["bundle_sha256"] = _canonical(bundle_unsigned)
    _write_json(path, bundle)
    with pytest.raises(ValueError, match="exact current schema set"):
        validate_bundle(path)


def test_authoritative_input_collection_rejects_an_unreferenced_extra_profile(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / "profiles", tmp_path / "profiles")
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    _write_json(tmp_path / "profiles/discipline/stray.json", {"stray": True})
    with pytest.raises(ValueError, match="exact transitive authoritative closure"):
        collect_authoritative_inputs(repo_root=tmp_path)


def test_live_runtime_envelope_consumes_frozen_profiles_not_checkout_paths() -> None:
    frozen = collect_authoritative_inputs()
    policy = authoritative_binding(frozen, ROOT_PROFILE)
    manifest = {
        "programme_id": ADAPTIVE_HYBRID_PROGRAMME.programme_id,
        "image_identity": ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        "run_identity": ADAPTIVE_HYBRID_PROGRAMME.runtime_run_identity,
        "stage": ADAPTIVE_HYBRID_PROGRAMME.live_stage,
        "manifest_sha256": "1" * 64,
        "bundle": {"bundle_sha256": "2" * 64},
        "firmware": {
            "build_identity": "3" * 64 + ":" + "4" * 64,
            "uf2": {"sha256": "5" * 64},
        },
        "authoritative_inputs": frozen,
        "policy": {
            **policy,
            "policy_id": ADAPTIVE_HYBRID_PROGRAMME.policy_id,
            "policy_sha256": policy["sha256"],
        },
        "started_at_utc": "2026-08-13T00:00:00Z",
        "bench_attempt": envelope_for_purpose(
            SINGLE_AUTOMATIC_APPLICATION
        ).as_dict(),
        ADAPTIVE_HYBRID_PROGRAMME.manifest_section: {},
    }
    spec, identities = load_active_hybrid_spec(manifest)
    assert spec.profile == ADAPTIVE_HYBRID_PROGRAMME.profile_id
    assert identities["active_policy_sha256"] == policy["sha256"]
    assert identities["estimator_sha256"] == next(
        item["sha256"]
        for item in frozen["profiles"]
        if item["path"]
        == "profiles/estimators/pps_gated_frequency_estimator_v1.json"
    )


def test_activation_rejects_structural_and_unbound_rehearsals(tmp_path: Path) -> None:
    structural = tmp_path / "structural.json"
    _write_json(structural, {"report_kind": "structural_preflight"})
    with pytest.raises(ValueError, match="structural preflight cannot authorize"):
        validate_operational_rehearsal(structural, bundle={}, proposal={})

    asserted = tmp_path / "asserted.json"
    _write_json(asserted, {"report_kind": "operational_rehearsal"})
    with pytest.raises(ValueError, match="authorization inputs are incomplete"):
        validate_operational_rehearsal(asserted, bundle={}, proposal={})


def test_rehearsal_authorization_contract_binds_real_path_and_denies_authority() -> None:
    required_tools = {
        name: {"path": f"/frozen/{name}.py", "sha256": "1" * 64, "size_bytes": 1}
        for name in (
            "capture_device",
            "adaptive_hybrid_operational_rehearsal",
            "adaptive_hybrid_supervisor",
            "adaptive_hybrid_run",
            "adaptive_hybrid_analyze",
            "evidence",
            "evidence_finalization",
            "evidence_index",
        )
    }
    contract = operational_rehearsal_authorization_contract(
        bundle={
            "bundle_sha256": "2" * 64,
            "firmware": {
                "source_revision": "3" * 40,
                "build_identity": "4" * 64 + ":" + "5" * 64,
                "uf2": {"sha256": "6" * 64},
            },
            "policy": {"policy_sha256": "7" * 64},
            "authoritative_inputs": {"set_sha256": "8" * 64},
            "host_tools": required_tools,
        },
        proposal={"proposal_sha256": "9" * 64},
    )
    assert tuple(contract["required_boundaries"]) == (
        OPERATIONAL_REHEARSAL_REQUIRED_BOUNDARIES
    )
    assert not any("shadow" in boundary for boundary in contract["required_boundaries"])
    assert (
        contract["required_evidence"]["shared_current_analyzer_consumers_exact"]
        is True
    )
    assert contract["required_evidence"]["successful_rehearsal_registration"] is True
    assert contract["host_discrepancy_semantics"] == {
        "review_required_hold": True,
        "new_setup_or_arm": False,
        "automatic_abort_or_teardown": False,
        "failed_campaign_authority": False,
    }
    assert contract["claim_boundary"] == {
        "authorizes_activation_input_only": True,
        "is_not_physical_plant_qualification": True,
        "grants_no_retry_extension_or_restoration": True,
        "physical_actions_performed": 0,
    }


def _passing_rehearsal_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, dict[str, object], dict[str, object], dict[str, object]]:
    package = tmp_path / "rehearsal-run"
    package.mkdir()
    manifest = package / "run_manifest.json"
    snapshot = package / "evidence_manifest.json"
    seal = package / evidence_module.OPERATIONAL_REHEARSAL_SEAL_PATH
    process_evidence = (
        package / evidence_module.OPERATIONAL_REHEARSAL_PROCESS_EVIDENCE_PATH
    )
    for artifact in (manifest, snapshot, seal, process_evidence):
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(f"{artifact.name}\n", encoding="utf-8")

    tools = tmp_path / "tools"
    host_tools: dict[str, object] = {}
    for name in (
        "capture_device",
        "adaptive_hybrid_operational_rehearsal",
        "adaptive_hybrid_supervisor",
        "adaptive_hybrid_run",
        "adaptive_hybrid_analyze",
        "evidence",
        "evidence_finalization",
        "evidence_index",
    ):
        tool = tools / f"{name}.py"
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.write_text(f"# {name}\n", encoding="utf-8")
        host_tools[name] = _binding(tool)
    bundle: dict[str, object] = {
        "bundle_sha256": "1" * 64,
        "firmware": {
            "source_revision": "2" * 40,
            "build_identity": "3" * 64 + ":" + "4" * 64,
            "uf2": {"sha256": "5" * 64},
        },
        "policy": {"policy_sha256": "6" * 64},
        "authoritative_inputs": {"set_sha256": "7" * 64},
        "host_tools": host_tools,
    }
    proposal: dict[str, object] = {"proposal_sha256": "8" * 64}
    contract = operational_rehearsal_authorization_contract(
        bundle=bundle, proposal=proposal
    )
    _write_json(
        manifest,
        {
            "programme_id": ADAPTIVE_HYBRID_PROGRAMME.programme_id,
            "run_identity": ADAPTIVE_HYBRID_PROGRAMME.runtime_run_identity,
            "image_identity": ADAPTIVE_HYBRID_PROGRAMME.profile_id,
            "bundle": {"bundle_sha256": bundle["bundle_sha256"]},
            "proposal": {"proposal_sha256": proposal["proposal_sha256"]},
        },
    )
    package_identity = {
        "content_sha256": "9" * 64,
        "file_count": 4,
        "total_bytes": sum(
            artifact.stat().st_size
            for artifact in (manifest, snapshot, seal, process_evidence)
        ),
        "files": [
            {"relative_path": artifact.relative_to(package).as_posix()}
            for artifact in (manifest, snapshot, seal, process_evidence)
        ],
    }
    package_validation = {
        "contract": "otis_validated_success_package_v1",
        "evidence_snapshot_sha256": "a" * 64,
        "seal_path": evidence_module.OPERATIONAL_REHEARSAL_SEAL_PATH.as_posix(),
        "seal_sha256": "b" * 64,
        "seal_status": "passed",
        "primary_decision": "adaptive_hybrid_operational_rehearsal_passed",
    }
    monkeypatch.setattr(
        evidence_module,
        "validate_operational_rehearsal_package",
        lambda *_args, **_kwargs: package_validation,
    )
    monkeypatch.setattr(
        evidence_module, "package_identity", lambda _path: package_identity
    )
    index_path = tmp_path / "evidence_index_v1.json"
    producer_sha256 = host_tools["adaptive_hybrid_operational_rehearsal"]["sha256"]
    index_record = {
        "content_sha256": package_identity["content_sha256"],
        "file_count": package_identity["file_count"],
        "total_bytes": package_identity["total_bytes"],
        "file_manifest": package_identity["files"],
        "storage_locations": [str(package.resolve())],
        "source_revision": bundle["firmware"]["source_revision"],
        "build_identity": bundle["firmware"]["build_identity"],
        "image_identity": ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        "attempt_classification": "successful_rehearsal",
        "result_or_failure_reason": "adaptive-hybrid operational rehearsal passed",
        "analyzer_identity": producer_sha256,
        "package_validation": package_validation,
        "lifecycle_status": "active",
        "registered_utc": "2026-09-09T08:00:00Z",
        "mothball": None,
    }
    _write_json(
        index_path,
        {
            "schema_version": evidence_module.EVIDENCE_INDEX_SCHEMA_VERSION,
            "index_id": evidence_module.EVIDENCE_INDEX_ID,
            "created_utc": "2026-09-09T07:59:59Z",
            "updated_utc": "2026-09-09T08:00:00Z",
            "packages": {package_identity["content_sha256"]: index_record},
        },
    )
    report: dict[str, object] = {
        **contract,
        "tool": evidence_module.OPERATIONAL_REHEARSAL_TOOL_ID,
        "tool_binding": host_tools["adaptive_hybrid_operational_rehearsal"],
        "created_utc": "2026-09-09T08:00:01Z",
        "boundary_results": {
            boundary: True for boundary in contract["required_boundaries"]
        },
        "package": {
            key: package_identity[key]
            for key in ("content_sha256", "file_count", "total_bytes")
        }
        | {"path": str(package.resolve())},
        "manifest": _binding(manifest),
        "evidence_snapshot": {
            **_binding(snapshot),
            "snapshot_digest": package_validation["evidence_snapshot_sha256"],
        },
        "seal": {
            **_binding(seal),
            "seal_sha256": package_validation["seal_sha256"],
        },
        "process_evidence": _binding(process_evidence),
        "registration": {
            "index_path": str(index_path.resolve()),
            "content_sha256": package_identity["content_sha256"],
            "attempt_classification": "successful_rehearsal",
            "successful_rehearsal_validation_error": None,
        },
        "activation_input_ready": True,
        "minimal_remaining_extension": None,
    }
    report["report_sha256"] = _canonical(report)
    report_path = tmp_path / (
        f"{package.name}-{evidence_module.OPERATIONAL_REHEARSAL_REPORT_NAME}"
    )
    _write_json(report_path, report)
    return report_path, report, bundle, proposal


def test_activation_independently_validates_successful_rehearsal_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path, report, bundle, proposal = _passing_rehearsal_report(
        tmp_path, monkeypatch
    )
    binding = validate_operational_rehearsal(
        report_path,
        bundle=bundle,
        proposal=proposal,
        require_current_tools=False,
    )

    assert binding == {
        **_binding(report_path),
        "report_sha256": report["report_sha256"],
        "package_content_sha256": report["package"]["content_sha256"],
        "evidence_snapshot_sha256": report["evidence_snapshot"][
            "snapshot_digest"
        ],
        "seal_sha256": report["seal"]["seal_sha256"],
    }


@pytest.mark.parametrize(
    ("section", "field", "replacement"),
    (
        ("boundary_results", OPERATIONAL_REHEARSAL_REQUIRED_BOUNDARIES[0], False),
        ("required_evidence", "shared_current_analyzer_consumers_exact", False),
        ("claim_boundary", "physical_actions_performed", 1),
        ("identity", "build_identity", "different"),
        ("registration", "attempt_classification", "diagnostic"),
    ),
)
def test_activation_rejects_rehashed_rehearsal_report_claim_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    field: str,
    replacement: object,
) -> None:
    report_path, report, bundle, proposal = _passing_rehearsal_report(
        tmp_path, monkeypatch
    )
    report[section][field] = replacement
    report["report_sha256"] = _canonical(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    _write_json(report_path, report)

    with pytest.raises(ValueError, match="rehearsal .* differs"):
        validate_operational_rehearsal(
            report_path,
            bundle=bundle,
            proposal=proposal,
            require_current_tools=False,
        )


@pytest.mark.parametrize(
    ("terminal", "exact", "decision"),
    [
        (
            {
                "result": "healthy_stop",
                "reason": ADAPTIVE_HYBRID_PROGRAMME.qualified_endpoint_reason,
                "preliminary_decision": "pending_offline_scientific_analysis",
            },
            True,
            ADAPTIVE_HYBRID_PROGRAMME.qualified_endpoint_reason,
        ),
        (
            {
                "result": "aborted",
                "reason": "operator requested stop",
                "primary_decision": "adaptive_hybrid_operator_abort",
            },
            True,
            "adaptive_hybrid_operator_abort",
        ),
        (
            {
                "result": "nonpass",
                "reason": "independently verified firmware response terminal",
                "primary_decision": "adaptive_hybrid_authority_not_sustained",
            },
            True,
            "adaptive_hybrid_authority_not_sustained",
        ),
        (
            {
                "result": "nonpass",
                "reason": "invalid qualified claim",
                "primary_decision": ADAPTIVE_HYBRID_PROGRAMME.qualified_endpoint_reason,
            },
            False,
            None,
        ),
    ],
)
def test_terminal_normalization_preserves_canonical_scientific_decision(
    terminal: dict[str, object], exact: bool, decision: str | None
) -> None:
    observed_exact, observed_decision, _, _ = _normalize_terminal(
        terminal, ADAPTIVE_HYBRID_PROGRAMME
    )
    assert observed_exact is exact
    assert observed_decision == decision


def test_terminal_normalization_accepts_exact_zero_write_success() -> None:
    bench_attempt = envelope_for_purpose(INHIBITED_ZERO_WRITE).as_dict()
    terminal = {
        "result": "healthy_stop",
        "reason": "inhibited_zero_write_complete",
        "preliminary_decision": "pending_offline_scientific_analysis",
        "last_confirmed_code": None,
    }

    exact, decision, result, reason = _normalize_terminal(
        terminal,
        ADAPTIVE_HYBRID_PROGRAMME,
        bench_attempt=bench_attempt,
    )

    assert exact is True
    assert decision == "inhibited_zero_write_complete"
    assert result == "healthy_stop"
    assert reason == "inhibited_zero_write_complete"


def test_terminal_normalization_rejects_fabricated_zero_write_success() -> None:
    bench_attempt = envelope_for_purpose(INHIBITED_ZERO_WRITE).as_dict()
    terminal = {
        "result": "healthy_stop",
        "reason": "inhibited_zero_write_complete",
        "preliminary_decision": "pending_offline_scientific_analysis",
        "last_confirmed_code": None,
    }
    fabricated_envelope = json.loads(json.dumps(bench_attempt))
    fabricated_envelope["authority"]["total_dac_value_write_limit"] = 1
    contradictory_code = {**terminal, "last_confirmed_code": 0xA84D}
    contradictory_primary = {
        **terminal,
        "primary_decision": "inhibited_zero_write_complete",
    }

    rejected = (
        _normalize_terminal(terminal, ADAPTIVE_HYBRID_PROGRAMME),
        _normalize_terminal(
            terminal,
            ADAPTIVE_HYBRID_PROGRAMME,
            bench_attempt=envelope_for_purpose(
                SINGLE_AUTOMATIC_APPLICATION
            ).as_dict(),
        ),
        _normalize_terminal(
            terminal,
            ADAPTIVE_HYBRID_PROGRAMME,
            bench_attempt=fabricated_envelope,
        ),
        _normalize_terminal(
            contradictory_code,
            ADAPTIVE_HYBRID_PROGRAMME,
            bench_attempt=bench_attempt,
        ),
        _normalize_terminal(
            contradictory_primary,
            ADAPTIVE_HYBRID_PROGRAMME,
            bench_attempt=bench_attempt,
        ),
    )
    assert all(exact is False and decision is None for exact, decision, _, _ in rejected)


def test_terminal_normalization_uses_exact_success_for_other_bench_purpose() -> None:
    programme_terminal = {
        "result": "healthy_stop",
        "reason": ADAPTIVE_HYBRID_PROGRAMME.qualified_endpoint_reason,
        "preliminary_decision": "pending_offline_scientific_analysis",
        "last_confirmed_code": 0xA84D,
    }
    bench_terminal = {
        **programme_terminal,
        "reason": "single_automatic_application_recovery_complete",
    }
    bench_attempt = envelope_for_purpose(
        SINGLE_AUTOMATIC_APPLICATION
    ).as_dict()

    exact, decision, _, _ = _normalize_terminal(
        bench_terminal,
        ADAPTIVE_HYBRID_PROGRAMME,
        bench_attempt=bench_attempt,
    )
    assert exact is True
    assert decision == "single_automatic_application_recovery_complete"

    exact, decision, _, _ = _normalize_terminal(
        programme_terminal,
        ADAPTIVE_HYBRID_PROGRAMME,
        bench_attempt=bench_attempt,
    )
    assert exact is False
    assert decision is None


def _write_host_review_resolution_fixture(
    tmp_path: Path,
) -> tuple[dict[str, object], dict[str, object], Path]:
    supervisor_state: dict[str, object] = {
        "terminal": None,
        "host_verification_hold": {
            "source": "bench_attempt_wall_endpoint_observer",
            "error": "zero-write wall endpoint lacks a clear static terminal",
            "review_status": "operator_review_required",
            "new_authority": False,
        },
    }
    source_paths = {
        "supervisor_state": tmp_path / analyze_module.SUPERVISOR_STATE,
        "live_status": tmp_path / analyze_module.LIVE_STATE_PATH,
        "capture_state": tmp_path / analyze_module.CAPTURE_STATE,
        "capture_closure": tmp_path / analyze_module.CAPTURE_CLOSURE,
        "active_transactions": tmp_path / analyze_module.ACTIVE_TRANSACTIONS,
        "dac_steps": tmp_path / analyze_module.DAC_STEPS,
        "completion": tmp_path / analyze_module.COMPLETE_MARKER,
    }
    _write_json(source_paths["supervisor_state"], supervisor_state)
    for key, path in source_paths.items():
        if key != "supervisor_state":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"retained-{key}\n", encoding="utf-8")
    original_tools = {
        "adaptive_hybrid_supervisor": "1" * 64,
        "adaptive_hybrid_run": "2" * 64,
        "adaptive_hybrid_analyze": "3" * 64,
    }
    manifest: dict[str, object] = {
        "programme_id": ADAPTIVE_HYBRID_PROGRAMME.programme_id,
        "run_identity": ADAPTIVE_HYBRID_PROGRAMME.runtime_run_identity,
        "image_identity": ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        "host": {
            "tool_bindings": {
                name: {"sha256": digest}
                for name, digest in original_tools.items()
            }
        },
    }
    module_root = Path(analyze_module.__file__).resolve().parent
    terminal = {
        "result": "healthy_stop",
        "reason": "inhibited_zero_write_complete",
        "preliminary_decision": "pending_offline_scientific_analysis",
        "last_confirmed_code": None,
        "utc": "2026-09-09T12:00:00Z",
    }
    unsigned = {
        "schema_version": 1,
        "report_type": "adaptive_hybrid_hybrid_host_review_resolution_v1",
        "recorded_utc": "2026-09-09T12:00:01Z",
        "resolution": "deterministic_host_endpoint_mismatch_superseded",
        "original_hold_preserved": True,
        "physical_rerun": False,
        "device_or_actuator_io": False,
        "new_authority": False,
        "absent_artifacts": [
            "reports/adaptive_hybrid_setup_authority_v1.json"
        ],
        "source_sha256": {
            key: sha256(path.read_bytes()).hexdigest()
            for key, path in source_paths.items()
        },
        "original_tool_sha256": original_tools,
        "review_tool_sha256": {
            name: sha256((module_root / f"{name}.py").read_bytes()).hexdigest()
            for name in original_tools
        },
        "terminal": terminal,
    }
    resolution = {**unsigned, "resolution_sha256": _canonical(unsigned)}
    resolution_path = tmp_path / analyze_module.HOST_REVIEW_RESOLUTION
    _write_json(resolution_path, resolution)
    return manifest, supervisor_state, resolution_path


def test_analyzer_consumes_exact_zero_write_host_review_resolution(
    tmp_path: Path,
) -> None:
    manifest, supervisor_state, _ = _write_host_review_resolution_fixture(
        tmp_path
    )
    terminal, exact, identity = analyze_module._validated_host_review_resolution(
        run_dir=tmp_path,
        manifest=manifest,
        bench_attempt=envelope_for_purpose(INHIBITED_ZERO_WRITE).as_dict(),
        supervisor_state=supervisor_state,
    )

    assert exact is True
    assert terminal is not None
    assert terminal["reason"] == "inhibited_zero_write_complete"
    assert identity is not None
    assert identity["path"] == str(analyze_module.HOST_REVIEW_RESOLUTION)
    assert len(identity["source_sha256"]) == 7


def test_analyzer_rejects_tampered_zero_write_host_review_resolution(
    tmp_path: Path,
) -> None:
    manifest, supervisor_state, resolution_path = (
        _write_host_review_resolution_fixture(tmp_path)
    )
    resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
    resolution["physical_rerun"] = True
    unsigned = {
        key: value
        for key, value in resolution.items()
        if key != "resolution_sha256"
    }
    resolution["resolution_sha256"] = _canonical(unsigned)
    resolution_path.write_text(
        json.dumps(resolution, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="contract or identity differs"):
        analyze_module._validated_host_review_resolution(
            run_dir=tmp_path,
            manifest=manifest,
            bench_attempt=envelope_for_purpose(INHIBITED_ZERO_WRITE).as_dict(),
            supervisor_state=supervisor_state,
        )


def test_control_preview_binds_exact_current_plant_profile() -> None:
    row = {field: "" for field in CONTROL_PREVIEW_V1_FIELDS}
    row.update(
        {
            "plant_model_ref": CURRENT_PLANT_MODEL_REF,
            "plant_model_id": CURRENT_PLANT_MODEL_ID,
            "plant_model_version": "1",
            "plant_model_hash": sha256(CURRENT_PLANT_MODEL_PATH.read_bytes()).hexdigest(),
        }
    )
    errors: list[str] = []
    _check_control_preview_v1(row, 1, errors)
    assert not [error for error in errors if "plant_model_" in error]

    row["plant_model_version"] = "2"
    row["plant_model_hash"] = "0" * 64
    errors = []
    _check_control_preview_v1(row, 1, errors)
    assert "row 1: plant_model_version must be 1" in errors
    assert "row 1: plant_model_hash must match the current plant profile bytes" in errors


def test_tight_deadband_field_names_are_current_and_ordered() -> None:
    first = TIGHT_DEADBAND_DECISION_V1_FIELDS.index("three_count_band_inside")
    second = TIGHT_DEADBAND_DECISION_V1_FIELDS.index("two_count_band_inside")
    assert second == first + 1
    retired_fragments = ("historical_", "symmetric_")
    assert not any(
        field.startswith(retired_fragments)
        for field in TIGHT_DEADBAND_DECISION_V1_FIELDS
    )


def test_capture_refuses_to_invent_a_manifest_or_default_inventory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="existing exact run manifest"):
        _require_exact_manifest(tmp_path)
    with pytest.raises(ValueError, match="existing exact run manifest"):
        _split_targets(tmp_path)
