from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import struct
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from host.otis_tools import adaptive_hybrid_bundle as bundle_module
from host.otis_tools import adaptive_hybrid_transactions as transactions_module
from host.otis_tools.adaptive_hybrid_activation import validate_operational_rehearsal
from host.otis_tools.adaptive_hybrid_analyze import _normalize_terminal
from host.otis_tools.adaptive_hybrid_bundle import (
    create_bundle,
    create_progressive_replay,
    _validate_build,
    validate_bundle,
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
    programme_from_mapping,
)
from host.otis_tools.adaptive_hybrid_health import (
    SETUP_AUTHORITY_CONTRACT,
    SETUP_AUTHORITY_PATH,
    AdaptiveHybridSupervisorBase,
)
from host.otis_tools.adaptive_hybrid_supervisor import load_active_hybrid_spec
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


def test_activation_rejects_structural_and_unimplemented_rehearsals(tmp_path: Path) -> None:
    structural = tmp_path / "structural.json"
    _write_json(structural, {"report_kind": "structural_preflight"})
    with pytest.raises(ValueError, match="structural preflight cannot authorize"):
        validate_operational_rehearsal(structural, bundle={}, proposal={})

    asserted = tmp_path / "asserted.json"
    _write_json(asserted, {"report_kind": "operational_rehearsal"})
    with pytest.raises(ValueError, match="no genuine .* producer is implemented"):
        validate_operational_rehearsal(asserted, bundle={}, proposal={})


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
