from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools import gnss_baud_envelope_bundle as bundle
from tools.firmware_matrix import (
    GENERATED_HEADER_NAME,
    GNSS_BAUD_CHARACTERIZATION_BINARY_MARKERS,
    GNSS_BAUD_CHARACTERIZATION_PACKETS,
    _gnss_binary_contract,
    configuration_hash,
    configuration_payload,
    load_matrix,
    source_input_hash,
)


def _artifact(path: Path) -> dict[str, object]:
    return {
        "name": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path.read_bytes()).hexdigest(),
    }


def _operational(
    contract_sha256: str,
    terminal: str = "multi_baud_characterization_complete",
    *,
    rate_local_fault_continued: bool = True,
) -> dict[str, object]:
    continuation = terminal == "multi_baud_characterization_continuation_complete"
    return {
        "schema_version": 1,
        "tool": "otis_gnss_baud_envelope_accelerated_operational_check_v1",
        "status": "passed",
        "programme_id": bundle.PROGRAMME_ID,
        "contract_file_sha256": contract_sha256,
        "hardware_operations": {
            "physical_serial_opens": 0,
            "firmware_flashes": 0,
            "board_resets": 0,
            "receiver_writes": 0,
            "dac_writes": 0,
        },
        "analyzer_mutation_regressions": (
            {"continuation_source_and_schedule_binding": True}
            if continuation
            else {
                "invalid_final_state": True,
                "negative_transition_milestone": True,
                "peak_cadence_and_tail_identity": True,
                "phase_order_or_transition_binding": True,
            }
        ),
        "transport_obstruction": {
            "priority_abort_observed_in_capture": True,
            "sole_serial_owner_verified": True,
            "sole_serial_owner_verified_after_resume": True,
            "owner_pid_unchanged_across_obstruction": True,
            "capture_resumed": True,
        },
        "atomic_rotation": {"status": "completed", "serial_reopened": False},
        "recovery_branches": {
            "recovery_at_other_baud": True,
            "five_rate_unrecoverable_terminal": {
                "terminal": "serial_link_unrecoverable"
            },
            "d14_d8_noninterference_terminal": {"reason": "d14_d8_capture_loss"},
            "idempotent_duplicate_result": True,
        },
        "temporary_registration_valid": True,
        "rate_local_fault_continued": rate_local_fault_continued,
        "terminal": {
            "terminal": terminal,
            "last_confirmed_baud": 9600,
            "final_identity_confirmed": True,
            "final_configuration_confirmed": True,
            "final_metadata_requalified": True,
        },
    }


def _campaign_inputs(tmp_path: Path, profile_id: str) -> dict[str, Path]:
    matrix = load_matrix()
    profile = next(item for item in matrix["profiles"] if item["id"] == profile_id)
    elf = tmp_path / "candidate.elf"
    elf.write_bytes(
        b"synthetic ELF D14 D8_GPIO20_GPIN0\x00"
        + b"\x00".join(sorted(GNSS_BAUD_CHARACTERIZATION_PACKETS))
        + b"\x00"
        + b"\x00".join(GNSS_BAUD_CHARACTERIZATION_BINARY_MARKERS.values())
    )
    paths = [
        tmp_path / "candidate.bin",
        elf,
        tmp_path / GENERATED_HEADER_NAME,
        tmp_path / "candidate.map",
        tmp_path / "candidate.uf2",
    ]
    paths[0].write_bytes(b"synthetic bin")
    paths[2].write_text("synthetic generated header\n", encoding="utf-8")
    paths[3].write_bytes(b"synthetic map")
    paths[4].write_bytes(b"synthetic uf2")
    artifacts = [_artifact(path) for path in paths]
    source_sha256 = source_input_hash()
    configuration = configuration_payload(matrix, profile)
    configuration["sha256"] = configuration_hash(matrix, profile)
    manifest = {
        "schema_version": 1,
        "provenance": {
            "source": {
                "git_commit": "2" * 40,
                "state": "synthetic",
                "sha256": source_sha256,
            },
            "configuration": configuration,
        },
        "gnss_binary_contract": _gnss_binary_contract(profile, tmp_path),
        "artifacts": artifacts,
    }
    manifest_path = tmp_path / "firmware_build_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    spec = bundle._profile_spec(profile_id)
    checks = {
        "frozen_contract_identity": True,
        "exact_profile_and_current_source_identity": True,
        "no_dac_or_control_authority": True,
        "generated_profile_header_retained": True,
        "five_packet_binary_contract": True,
        "D14_D8_topology_source_and_binary": True,
        "memory_budget_within_bound": True,
        "all_artifact_hashes_and_sizes": True,
        "physical_authority_false": True,
    }
    if spec["continuation"]:
        checks["startup_discovery_hint_bound_to_sealed_observed_baud"] = True
    preflight = {
        "schema_version": 1,
        "tool": "otis_gnss_baud_characterization_profile_preflight_v1",
        "status": "passed",
        "programme_id": bundle.PROGRAMME_ID,
        "profile_id": profile_id,
        "contract": {"sha256": spec["contract_sha256"]},
        "build_manifest": {
            "sha256": sha256(manifest_path.read_bytes()).hexdigest()
        },
        "configuration_sha256": configuration["sha256"],
        "source_sha256": source_sha256,
        "binary_contract": manifest["gnss_binary_contract"],
        "artifacts": sorted(artifacts, key=lambda entry: Path(str(entry["name"])).suffix),
        "checks": checks,
        "hardware_operations": {
            "serial_devices_opened": 0,
            "bytes_transmitted": 0,
            "firmware_flashes": 0,
            "board_resets": 0,
            "dac_writes": 0,
            "receiver_baud_changes": 0,
        },
    }
    if spec["continuation"]:
        contract = json.loads(Path(spec["contract_path"]).read_text(encoding="utf-8"))
        preflight["startup_discovery"] = contract["startup_discovery"]
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(
        json.dumps(preflight, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    operational_path = tmp_path / "operational.json"
    operational_path.write_text(
        json.dumps(
            _operational(
                str(spec["contract_sha256"]),
                (
                    "multi_baud_characterization_continuation_complete"
                    if spec["continuation"]
                    else "multi_baud_characterization_complete"
                ),
                rate_local_fault_continued=(
                    profile_id != bundle.GNSS_BAUD_RESUME_PROFILE_ID
                ),
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "manifest": manifest_path,
        "preflight": preflight_path,
        "operational": operational_path,
        "contract": Path(spec["contract_path"]),
    }


@pytest.fixture
def stable_bundle_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bundle,
        "_source_state",
        lambda: {"git_commit": "test", "dirty": True},
    )
    monkeypatch.setattr(bundle, "_environment", lambda: {"python": "test"})


def _candidate(
    tmp_path: Path,
    profile_id: str,
) -> tuple[dict[str, object], Path, dict[str, Path]]:
    inputs = _campaign_inputs(tmp_path, profile_id)
    candidate_path = tmp_path / "candidate.json"
    candidate = bundle.create_candidate(
        contract_path=inputs["contract"],
        build_manifest_path=inputs["manifest"],
        preflight_path=inputs["preflight"],
        operational_check_path=inputs["operational"],
        output_path=candidate_path,
        profile_id=profile_id,
    )
    return candidate, candidate_path, inputs


def _reidentify(value: dict[str, object], identity_field: str) -> None:
    value[identity_field] = bundle.canonical_sha256(
        {key: item for key, item in value.items() if key != identity_field}
    )


def test_continuation_candidate_binds_prefix_mapping_schedule_and_attachment(
    tmp_path: Path, stable_bundle_host: None
) -> None:
    candidate, _, _ = _candidate(tmp_path, bundle.GNSS_BAUD_CONTINUATION_PROFILE_ID)

    assert candidate["schedule"]["total_confirmed_online_seconds"] == 35700
    assert candidate["schedule"]["segment_count"] == 6
    assert candidate["continuation"]["local_request_sequences"] == [1, 2, 3, 4, 5, 6]
    assert [
        item["logical_segment_id"]
        for item in candidate["continuation"]["local_to_logical_segment_map"]
    ] == ["S06", "S07", "S08", "S09", "S10", "S11"]
    attachment = candidate["continuation"]["attachment"]
    assert attachment["initial_confirmed_baud"] == "fresh_attachment_baud_from_allowlist"
    assert attachment["allowed_bauds"] == [9600, 19200, 38400, 57600, 115200]
    assert attachment["deadline_ms"] == 120000
    assert attachment["programme_command_before_fresh_attachment_permitted"] is False
    assert candidate["continuation"]["prefix_validation"]["status"] == (
        "validated_against_original_manifest_and_contract"
    )
    assert candidate["run_manifest_template"]["gnss_baud_envelope"][
        "continuation"
    ] == candidate["continuation"]


def test_resume_candidate_binds_exact_tail_and_failed_predecessor(
    tmp_path: Path, stable_bundle_host: None
) -> None:
    candidate, candidate_path, _ = _candidate(
        tmp_path, bundle.GNSS_BAUD_RESUME_PROFILE_ID
    )
    assert candidate["schedule"]["total_confirmed_online_seconds"] == 24600
    assert candidate["schedule"]["segment_count"] == 2
    assert [
        item["logical_segment_id"]
        for item in candidate["continuation"]["local_to_logical_segment_map"]
    ] == ["S10", "S11"]
    assert candidate["startup_discovery"]["hint_baud"] == 115200
    assert candidate["continuation"]["prefix_validation"]["source_run_id"] == (
        "live_20260827T092556Z"
    )
    assert candidate["continuation"]["prefix_validation"][
        "interrupted_s10_soak_duration_credited"
    ] is False

    run_id = "live_20990103T000000Z"
    activation = bundle.create_activation(
        candidate_path=candidate_path,
        output_path=tmp_path / "resume_activation.json",
        operator="test operator",
        authority_source="test authority",
        run_id=run_id,
        run_dir=bundle.LIVE_RUN_ROOT / run_id,
        device=Path("/dev/cu.test-otis"),
    )
    assert activation["schedule"]["total_confirmed_online_seconds"] == 24600
    assert activation["startup_discovery"]["hint_baud"] == 115200
    assert bundle.load_and_validate(candidate_path, tmp_path / "resume_activation.json")


def test_original_candidate_path_remains_full_programme_and_has_no_continuation(
    tmp_path: Path, stable_bundle_host: None
) -> None:
    candidate, _, _ = _candidate(tmp_path, bundle.GNSS_BAUD_ENVELOPE_PROFILE_ID)

    assert set(candidate) == bundle.ORIGINAL_CANDIDATE_KEYS
    assert candidate["schedule"]["total_confirmed_online_seconds"] == 43200
    assert candidate["schedule"]["segment_count"] == 11
    assert "startup_discovery" not in candidate
    assert "continuation" not in candidate
    assert bundle.validate_candidate(candidate) == candidate


@pytest.mark.parametrize(
    "mutation",
    ("startup", "prefix", "mapping", "schedule"),
)
def test_continuation_candidate_rejects_identity_preserving_semantic_tamper(
    tmp_path: Path, stable_bundle_host: None, mutation: str
) -> None:
    candidate, _, _ = _candidate(tmp_path, bundle.GNSS_BAUD_CONTINUATION_PROFILE_ID)
    tampered = deepcopy(candidate)
    if mutation == "startup":
        tampered["startup_discovery"]["hint_baud"] = 38400
    elif mutation == "prefix":
        tampered["continuation"]["prefix_source_hashes"][
            "supervisor_events_sha256"
        ] = "0" * 64
    elif mutation == "mapping":
        tampered["continuation"]["local_to_logical_segment_map"][0][
            "logical_segment_id"
        ] = "S01"
    else:
        tampered["schedule"]["total_confirmed_online_seconds"] = 43200
    _reidentify(tampered, "bundle_id")

    with pytest.raises(ValueError, match="continuation provenance|programme binding"):
        bundle.validate_candidate(tampered)


def test_continuation_candidate_rejects_wrong_build_profile(
    tmp_path: Path, stable_bundle_host: None
) -> None:
    inputs = _campaign_inputs(tmp_path, bundle.GNSS_BAUD_ENVELOPE_PROFILE_ID)

    with pytest.raises(ValueError, match="build profile"):
        bundle.create_candidate(
            contract_path=Path(
                bundle._profile_spec(bundle.GNSS_BAUD_CONTINUATION_PROFILE_ID)[
                    "contract_path"
                ]
            ),
            build_manifest_path=inputs["manifest"],
            preflight_path=inputs["preflight"],
            operational_check_path=inputs["operational"],
            output_path=tmp_path / "candidate.json",
            profile_id=bundle.GNSS_BAUD_CONTINUATION_PROFILE_ID,
        )


def test_candidate_revalidation_rejects_build_manifest_tampering(
    tmp_path: Path, stable_bundle_host: None
) -> None:
    candidate, _, inputs = _candidate(
        tmp_path, bundle.GNSS_BAUD_CONTINUATION_PROFILE_ID
    )
    manifest = json.loads(inputs["manifest"].read_text(encoding="utf-8"))
    manifest["provenance"]["source"]["sha256"] = "0" * 64
    inputs["manifest"].write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="build manifest identity differs"):
        bundle.validate_candidate(candidate)


@pytest.mark.parametrize("mutation", ("attachment", "startup", "prefix", "schedule"))
def test_continuation_activation_binds_all_continuation_identity_and_rejects_tamper(
    tmp_path: Path, stable_bundle_host: None, mutation: str
) -> None:
    candidate, candidate_path, _ = _candidate(
        tmp_path, bundle.GNSS_BAUD_CONTINUATION_PROFILE_ID
    )
    run_id = "live_20990102T000000Z"
    activation = bundle.create_activation(
        candidate_path=candidate_path,
        output_path=tmp_path / "activation.json",
        operator="test operator",
        authority_source="test authority",
        run_id=run_id,
        run_dir=bundle.LIVE_RUN_ROOT / run_id,
        device=Path("/dev/cu.test-otis"),
    )

    assert set(activation) == bundle.CONTINUATION_ACTIVATION_KEYS
    assert activation["startup_discovery"] == candidate["startup_discovery"]
    assert activation["continuation"] == candidate["continuation"]
    assert activation["schedule"]["total_confirmed_online_seconds"] == 35700

    tampered = deepcopy(activation)
    if mutation == "attachment":
        tampered["continuation"]["attachment"]["allowed_bauds"] = [57600]
    elif mutation == "startup":
        tampered["startup_discovery"]["hint_baud"] = 38400
    elif mutation == "prefix":
        tampered["continuation"]["prefix_source_hashes"][
            "supervisor_events_sha256"
        ] = "0" * 64
    else:
        tampered["schedule"]["total_confirmed_online_seconds"] = 43200
    _reidentify(tampered, "activation_id")
    with pytest.raises(ValueError, match="continuation binding"):
        bundle.validate_activation(candidate_path, candidate, tampered)
