"""Create and validate the non-authorizing adaptive-hybrid operating bundle."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

from .adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    AdaptiveHybridProgramme,
    integrated_setup_provenance_contract,
    programme_from_mapping,
    progressive_checkpoint_contract,
)
from .adaptive_hybrid_policy import (
    AdaptiveHybridObservation,
    AdaptiveHybridPhasePriorityController,
    policy_from_mapping,
)
from .authoritative_inputs import (
    ROOT_PROFILE,
    authoritative_binding,
    authoritative_document,
    authoritative_summary,
    collect_authoritative_inputs,
    validate_authoritative_inputs,
)
from .firmware_binary import verify_uf2


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_ID = "adaptive_hybrid_exact_bundle_v1"
FRESH_SERIAL_AUTO_DETECT = (
    "capture_device_--auto-detect_exactly_one_/dev/cu.usbmodem*"
)
REQUIRED_FALSE_AUTHORITY = (
    "effective",
    "firmware_flash",
    "reset",
    "serial_access",
    "command_fifo",
    "setup_stimulus",
    "dac_write",
    "control_arm",
    "physical_rehearsal",
    "live_acquisition",
)
LOWER_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
LOWER_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
LOWER_HEX_16 = re.compile(r"^[0-9a-f]{16}$")
HOST_TOOL_MODULES = (
    "adaptive_hybrid_bundle.py",
    "adaptive_hybrid_contract.py",
    "adaptive_hybrid_policy.py",
    "adaptive_hybrid_proposal.py",
    "adaptive_hybrid_evidence.py",
    "adaptive_hybrid_replay.py",
    "adaptive_hybrid_transactions.py",
    "adaptive_hybrid_transport.py",
    "adaptive_hybrid_health.py",
    "adaptive_hybrid_activation.py",
    "adaptive_hybrid_operational_rehearsal.py",
    "adaptive_hybrid_supervisor.py",
    "adaptive_hybrid_run.py",
    "adaptive_hybrid_analyze.py",
    "adaptive_hybrid_structural_preflight.py",
    "adaptive_hybrid_monitor.py",
    "authoritative_inputs.py",
    "firmware_binary.py",
    "active_status_contract.py",
    "active_status_live_state.py",
    "capture_device.py",
    "capture_serial.py",
    "serial_commands.py",
    "abort_transport.py",
    "contracts.py",
    "time_domains.py",
    "evidence.py",
    "evidence_finalization.py",
    "evidence_index.py",
    "prewrite_readiness_contract.py",
    "run_loader.py",
    "run_paths.py",
)


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _binding(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"bound file is unavailable: {path}")
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _require_current_clean_checkout(expected_revision: str) -> None:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise ValueError("cannot establish current firmware source identity") from error
    if revision != expected_revision or status:
        raise ValueError(
            "firmware authorization requires the matching clean current checkout"
        )


def _run_reproducible_firmware_build(
    *,
    build_session_id: str,
    expected_revision: str,
) -> tuple[dict[str, Any], bytes]:
    """Rebuild current firmware in an ignored fresh directory with no bypass."""

    if not LOWER_HEX_16.fullmatch(build_session_id):
        raise ValueError("firmware build session identity is malformed")
    _require_current_clean_checkout(expected_revision)
    build_parent = REPO_ROOT / "build"
    build_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="firmware_reproduction_", dir=build_parent
    ) as temporary:
        output_dir = Path(temporary)
        command = [
            sys.executable,
            str(REPO_ROOT / "tools" / "build_firmware.py"),
            "--output-dir",
            str(output_dir),
            "--build-session-id",
            build_session_id,
        ]
        try:
            result = subprocess.run(
                command,
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as error:
            raise ValueError("independent deterministic firmware rebuild failed") from error
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()[-4000:]
            raise ValueError(
                "independent deterministic firmware rebuild failed"
                + (f": {detail}" if detail else "")
            )
        reproduced_manifest_path = (
            output_dir / "artifacts" / "firmware_build_manifest.json"
        )
        if not reproduced_manifest_path.is_file():
            raise ValueError("deterministic rebuild omitted its firmware manifest")
        reproduced_manifest = _read_object(reproduced_manifest_path)
        artifacts = reproduced_manifest.get("artifacts")
        reproduced_uf2 = (
            [
                item
                for item in artifacts
                if isinstance(item, dict)
                and isinstance(item.get("name"), str)
                and item["name"].endswith(".uf2")
            ]
            if isinstance(artifacts, list)
            else []
        )
        if len(reproduced_uf2) != 1:
            raise ValueError("deterministic rebuild did not bind exactly one UF2")
        artifact = reproduced_uf2[0]
        name = artifact["name"]
        if Path(name).name != name:
            raise ValueError("deterministic rebuild emitted an unsafe UF2 name")
        uf2_path = output_dir / "artifacts" / name
        if not uf2_path.is_file():
            raise ValueError("deterministic rebuild UF2 is unavailable")
        uf2_bytes = uf2_path.read_bytes()
        if (
            artifact.get("sha256") != sha256(uf2_bytes).hexdigest()
            or artifact.get("size_bytes") != len(uf2_bytes)
        ):
            raise ValueError("deterministic rebuild UF2 identity is internally inconsistent")
        return reproduced_manifest, uf2_bytes


def _verify_reproducible_firmware(
    *,
    provenance: dict[str, Any],
    recorded_uf2: Path,
) -> dict[str, Any]:
    invocation = provenance.get("invocation")
    source = provenance.get("source")
    if not isinstance(invocation, dict) or not isinstance(source, dict):
        raise ValueError("firmware rebuild provenance is malformed")
    build_session_id = invocation.get("build_session_id")
    expected_revision = source.get("git_commit")
    if (
        not isinstance(build_session_id, str)
        or not LOWER_HEX_16.fullmatch(build_session_id)
        or not isinstance(expected_revision, str)
        or not LOWER_HEX_40.fullmatch(expected_revision)
    ):
        raise ValueError("firmware rebuild identity is malformed")
    reproduced_manifest, reproduced_uf2 = _run_reproducible_firmware_build(
        build_session_id=build_session_id,
        expected_revision=expected_revision,
    )
    if reproduced_manifest.get("provenance") != provenance:
        raise ValueError("deterministic rebuild provenance differs from the supplied build")
    recorded_bytes = recorded_uf2.read_bytes()
    if reproduced_uf2 != recorded_bytes:
        raise ValueError("supplied firmware UF2 is not the deterministic reproduced image")
    digest = sha256(recorded_bytes).hexdigest()
    return {
        "contract": "otis_deterministic_firmware_reproduction_v1",
        "status": "verified",
        "build_session_id": build_session_id,
        "provenance_equal": True,
        "uf2_byte_identical": True,
        "uf2_sha256": digest,
    }


def _frozen_reproduction_record(
    *, provenance: dict[str, Any], recorded_uf2: Path
) -> dict[str, Any]:
    """Reconstruct the immutable reproduction attestation without compiling.

    Live consumers verify the frozen bundle and artifact bytes.  The physical
    runner separately performs one current deterministic reproduction before
    reserving authority or touching hardware; repeating that compile in each
    downstream process would put offline validation inside the live startup
    deadline.
    """

    invocation = provenance.get("invocation")
    if not isinstance(invocation, dict):
        raise ValueError("firmware rebuild provenance is malformed")
    build_session_id = invocation.get("build_session_id")
    if not isinstance(build_session_id, str) or not LOWER_HEX_16.fullmatch(
        build_session_id
    ):
        raise ValueError("firmware rebuild identity is malformed")
    return {
        "contract": "otis_deterministic_firmware_reproduction_v1",
        "status": "verified",
        "build_session_id": build_session_id,
        "provenance_equal": True,
        "uf2_byte_identical": True,
        "uf2_sha256": sha256(recorded_uf2.read_bytes()).hexdigest(),
    }


def _validate_build(
    build_manifest_path: Path,
    programme: AdaptiveHybridProgramme = ADAPTIVE_HYBRID_PROGRAMME,
    *,
    authoritative_inputs: dict[str, Any] | None = None,
    verify_deterministic_reproduction: bool = True,
) -> dict[str, Any]:
    frozen_inputs = authoritative_inputs or collect_authoritative_inputs()
    frozen_summary = authoritative_summary(frozen_inputs)
    manifest = _read_object(build_manifest_path)
    provenance = manifest.get("provenance", {})
    if not isinstance(provenance, dict):
        raise ValueError("firmware build provenance is malformed")
    configuration = provenance.get("configuration", {})
    source = provenance.get("source", {})
    target = provenance.get("target", {})
    toolchain = provenance.get("toolchain", {})
    invocation = provenance.get("invocation", {})
    if not all(
        isinstance(value, dict)
        for value in (configuration, source, target, toolchain, invocation)
    ):
        raise ValueError("firmware build provenance components are malformed")
    capabilities = manifest.get("capabilities", {})
    external_event = (
        capabilities.get("external_event_capture", {})
        if isinstance(capabilities, dict)
        else {}
    )
    if (
        manifest.get("schema_version") != 1
        or provenance.get("schema_version") != 1
        or configuration.get("image_id") != programme.profile_id
        or configuration.get("firmware_version") != programme.programme_id
        or configuration.get("fqbn") != target.get("fqbn")
        or invocation.get("builder_id") != "otis_fixed_firmware_builder_v1"
        or not isinstance(invocation.get("id"), str)
        or not LOWER_HEX_64.fullmatch(invocation["id"])
        or external_event.get("pin") != "D10"
        or external_event.get("channel") != "CH0"
        or external_event.get("status") != "not_implemented"
        or external_event.get("control_authority") is not False
        or external_event.get("terminal_authority") is not False
    ):
        raise ValueError("firmware build does not select adaptive_hybrid_regulation")
    binary = manifest.get("binary_contract", {})
    authority = binary.get("authority", {}) if isinstance(binary, dict) else {}
    markers = binary.get("required_markers", {}) if isinstance(binary, dict) else {}
    provenance_markers = (
        binary.get("exact_provenance_markers", {})
        if isinstance(binary, dict)
        else {}
    )
    if (
        binary.get("contract") != "otis_adaptive_hybrid_firmware_binary_v1"
        or binary.get("status") != "verified"
        or authority.get("reference") != "D14"
        or authority.get("oscillator_count") != "D8_GPIO20_GPIN0"
        or any(authority.get(name) is not False for name in (
            "d10_control_authority", "d9_control_authority", "d6_control_authority"
        ))
        or not all(markers.get(name) is True for name in (
            "d14_reference", "d8_count_input", "d9_forwarded_output",
            "d6_fail_local_monitor", "gnss_metadata_hold", "image_id",
        ))
        or not isinstance(provenance_markers, dict)
        or not provenance_markers
        or not all(value is True for value in provenance_markers.values())
        or any(binary.get("forbidden_markers_present", {}).values())
    ):
        raise ValueError("firmware binary timing or authority contract differs")
    configuration_sha256 = configuration.get("sha256")
    source_sha256 = source.get("sha256")
    source_revision = source.get("git_commit")
    if (
        not all(
            isinstance(value, str) and LOWER_HEX_64.fullmatch(value)
            for value in (configuration_sha256, source_sha256)
        )
        or not isinstance(source_revision, str)
        or not LOWER_HEX_40.fullmatch(source_revision)
        or source.get("state") != "clean"
    ):
        raise ValueError("firmware build lacks exact source/configuration identity")
    if provenance.get("authoritative_inputs") != frozen_summary:
        raise ValueError("firmware build authoritative profile/schema identity differs")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("firmware artifact list is unavailable")
    if not all(isinstance(item, dict) for item in artifacts):
        raise ValueError("firmware artifact list is malformed")
    uf2 = [
        item
        for item in artifacts
        if isinstance(item.get("name"), str) and item["name"].endswith(".uf2")
    ]
    if len(uf2) != 1:
        raise ValueError("firmware build must bind exactly one UF2")
    generated_headers = [
        item
        for item in artifacts
        if item.get("name") == "otis_build_manifest.generated.h"
    ]
    if len(generated_headers) != 1:
        raise ValueError("firmware build must bind its one generated provenance header")
    uf2_name = uf2[0].get("name")
    if not isinstance(uf2_name, str) or Path(uf2_name).name != uf2_name:
        raise ValueError("firmware UF2 name must be a build-local filename")
    uf2_path = build_manifest_path.parent / uf2_name
    generated_header_path = build_manifest_path.parent / str(
        generated_headers[0]["name"]
    )
    if (
        not uf2_path.is_file()
        or not isinstance(uf2[0].get("sha256"), str)
        or not LOWER_HEX_64.fullmatch(uf2[0]["sha256"])
        or _sha256_file(uf2_path) != uf2[0]["sha256"]
        or uf2_path.stat().st_size != uf2[0].get("size_bytes")
    ):
        raise ValueError("firmware UF2 identity differs from its manifest")
    if (
        not generated_header_path.is_file()
        or not isinstance(generated_headers[0].get("sha256"), str)
        or not LOWER_HEX_64.fullmatch(str(generated_headers[0]["sha256"]))
        or _sha256_file(generated_header_path) != generated_headers[0]["sha256"]
        or generated_header_path.stat().st_size
        != generated_headers[0].get("size_bytes")
    ):
        raise ValueError("generated provenance-header identity differs from its manifest")
    independent_binary = verify_uf2(
        uf2_path,
        authoritative_summary=frozen_summary,
        provenance=provenance,
    )
    if provenance_markers != independent_binary["exact_provenance_markers"]:
        raise ValueError(
            "firmware builder and independent host provenance-marker reports differ"
        )
    if target.get("fqbn") != "rp2040:rp2040:arduino_nano_connect:freq=133":
        raise ValueError("firmware target differs")
    if not toolchain.get("compiler_identity") or not toolchain.get("installed_sha256"):
        raise ValueError("firmware toolchain identity is incomplete")
    resource = manifest.get("resource_budget", {})
    if (
        not isinstance(resource, dict)
        or resource.get("contract") != "otis_firmware_resource_budget_v1"
        or resource.get("status") != "within_budget"
    ):
        raise ValueError("firmware resource budget is not verified")
    reproduction = (
        _verify_reproducible_firmware(
            provenance=provenance,
            recorded_uf2=uf2_path,
        )
        if verify_deterministic_reproduction
        else _frozen_reproduction_record(
            provenance=provenance,
            recorded_uf2=uf2_path,
        )
    )
    return {
        "image_id": programme.profile_id,
        "build_manifest": _binding(build_manifest_path),
        "source_revision": source_revision,
        "source_state": source.get("state"),
        "source_sha256": source_sha256,
        "configuration_sha256": configuration_sha256,
        "build_identity": f"{source_sha256}:{configuration_sha256}",
        "build_provenance_required": True,
        "uf2": _binding(uf2_path),
        "generated_header": _binding(generated_header_path),
        "fqbn": target["fqbn"],
        "toolchain": toolchain,
        "binary_contract": binary,
        "independent_binary_verification": independent_binary,
        "deterministic_reproduction": reproduction,
    }


def _progressive_replay(policy: Any) -> dict[str, Any]:
    """Exercise two complete applications, response holds, and carried debt."""
    controller = AdaptiveHybridPhasePriorityController(policy)

    def observation(timestamp_s: int, opening: int, closing: int) -> AdaptiveHybridObservation:
        return AdaptiveHybridObservation(
            timestamp_s=timestamp_s,
            timestamp_ticks=timestamp_s * 1_000_000,
            capture_session=1,
            source_first_sequence=opening,
            source_last_sequence=closing,
            dac_epoch=controller.dac_epoch,
            applied_code=controller.applied_code,
            accumulated_edge_error_counts=-1,
            tight_state="TIGHT_INSIDE",
            phase_epoch=1,
            relative_phase_cycles=-4,
        )

    first_hold = controller.decide(observation(0, 0, 600))
    first_request = controller.decide(observation(600, 600, 1200))
    controller.confirm_application(
        first_request,
        applied_code=first_request.requested_code,
        dac_epoch=2,
        first_consumer_exact=True,
    )
    first_debt = asdict(controller.debt)
    response_hold = controller.decide(observation(1200, 1200, 1800))
    controller.complete_response(fresh_exact=True)
    cadence_hold = controller.decide(observation(1200, 1200, 1800))
    persistence_hold = controller.decide(observation(1800, 1800, 2400))
    second_request = controller.decide(observation(2400, 2400, 3000))
    controller.confirm_application(
        second_request,
        applied_code=second_request.requested_code,
        dac_epoch=3,
        first_consumer_exact=True,
    )
    second_debt = asdict(controller.debt)
    controller.complete_response(fresh_exact=True)
    checks = {
        "first_persistent_window_holds": (
            first_hold.reason == "persistence_first_interval_hold"
        ),
        "first_request_applies": first_request.requested_delta_codes == 5,
        "response_blocks": response_hold.reason == "response_pending_hold",
        "cadence_holds": cadence_hold.reason == "cadence_hold",
        "persistence_continues": persistence_hold.persistence_count == 2,
        "debt_enters_second_decision": (
            second_request.committed_debt_picocodes == sum(first_debt.values())
        ),
        "second_request_applies": second_request.requested_delta_codes == 5,
        "tagged_debt_bounded": sum(second_debt.values()) == 500_000_000_000,
        "transaction_complete": (
            not controller.request_pending and not controller.response_pending
        ),
    }
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise ValueError("progressive replay failed: " + ", ".join(failed))
    return {
        "replay_id": "adaptive_hybrid_progressive_tagged_debt_replay_v1",
        "status": "passed",
        "policy_id": policy.policy_id,
        "policy_sha256": policy.policy_sha256,
        "checks": checks,
        "lifecycle": {
            "first_hold": asdict(first_hold),
            "first_request": asdict(first_request),
            "first_debt": first_debt,
            "response_hold": asdict(response_hold),
            "second_request": asdict(second_request),
            "second_debt": second_debt,
        },
    }


def create_progressive_replay(
    output_path: Path | None = None,
    *,
    authoritative_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    frozen_inputs = authoritative_inputs or collect_authoritative_inputs()
    root_binding = authoritative_binding(frozen_inputs, ROOT_PROFILE)
    policy = policy_from_mapping(
        authoritative_document(frozen_inputs, ROOT_PROFILE),
        policy_sha256=str(root_binding["sha256"]),
    )
    report = _progressive_replay(policy)
    report["report_sha256"] = _canonical_sha256(report)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output_path.open("x", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
        except FileExistsError as error:
            raise ValueError(f"refusing to overwrite replay: {output_path}") from error
    return report


def validate_progressive_replay(
    report: dict[str, Any],
    *,
    authoritative_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Require the one deterministic replay, not merely a self-consistent hash."""

    expected = create_progressive_replay(authoritative_inputs=authoritative_inputs)
    if report != expected:
        raise ValueError("offline replay differs from the current deterministic replay")
    return report


def create_bundle(
    *,
    build_manifest_path: Path,
    replay_path: Path | None = None,
    programme: AdaptiveHybridProgramme = ADAPTIVE_HYBRID_PROGRAMME,
    _created_utc: str | None = None,
    _authoritative_inputs: dict[str, Any] | None = None,
    _verify_deterministic_reproduction: bool = True,
    _frozen_host_tools: dict[str, Any] | None = None,
) -> dict[str, Any]:
    frozen_inputs = _authoritative_inputs or collect_authoritative_inputs()
    validate_authoritative_inputs(frozen_inputs)
    policy_binding = authoritative_binding(frozen_inputs, ROOT_PROFILE)
    policy = policy_from_mapping(
        authoritative_document(frozen_inputs, ROOT_PROFILE),
        policy_sha256=str(policy_binding["sha256"]),
    )
    replay = (
        create_progressive_replay(authoritative_inputs=frozen_inputs)
        if replay_path is None
        else _read_object(replay_path)
    )
    validate_progressive_replay(replay, authoritative_inputs=frozen_inputs)
    authority = {name: False for name in REQUIRED_FALSE_AUTHORITY}
    authority.update(
        {
            "offline_preparation": True,
            "separate_operator_activation_required": True,
            "consumed_by_first_physical_terminal": True,
        }
    )
    module_root = Path(__file__).resolve().parent
    bundle: dict[str, Any] = {
        "schema_version": 1,
        "bundle_id": programme.bundle_id,
        "programme_id": programme.programme_id,
        "image_identity": programme.profile_id,
        "run_identity": programme.runtime_run_identity,
        "tool": TOOL_ID,
        "created_utc": _created_utc or datetime.now(timezone.utc).replace(
            microsecond=0
        ).isoformat().replace("+00:00", "Z"),
        "status": "frozen_non_effective_physical_proposal_input",
        "authoritative_inputs": frozen_inputs,
        "policy": {
            **policy_binding,
            "policy_id": policy.policy_id,
            "policy_sha256": policy.policy_sha256,
        },
        "firmware": _validate_build(
            build_manifest_path.resolve(),
            programme,
            authoritative_inputs=frozen_inputs,
            verify_deterministic_reproduction=(
                _verify_deterministic_reproduction
            ),
        ),
        "offline_replay": replay,
        "host_tools": (
            _frozen_host_tools
            if _frozen_host_tools is not None
            else {
                path.removesuffix(".py"): _binding(module_root / path)
                for path in HOST_TOOL_MODULES
            }
        ),
        "topology": {
            "sole_reference_input": "D14",
            "sole_oscillator_count_input": "D8",
            "independent_event_input_not_authority": "D10",
            "gnss_role": "same_receiver_D14_qualification_metadata_only",
            "D9_GPOUT0": "D8_GPIO20_GPIN0_to_D9_GPIO21_GPOUT0_integer_divide_one",
            "D6_forwarded_monitor": (
                "D9_through_1k_series_resistor_to_D6_GPIO18_diagnostic_zero_authority"
            ),
            "serial_owner_count": 1,
            "serial_owner": "capture_device",
            "normal_and_priority_abort_fifos_distinct": True,
            "serial_device_selection": FRESH_SERIAL_AUTO_DETECT,
        },
        "setup": {
            "exact_code": programme.setup_code,
            "exact_code_hex": f"0x{programme.setup_code:04X}",
            "one_setup_application": True,
            "same_code_reapplication_opens_new_epoch": True,
            "exact_acknowledgement_required": True,
            "consumer_epoch_propagation_required": [
                "frequency_estimator",
                "phase_estimator",
                "controller",
                "recorder",
                "response_classifier",
            ],
            "provenance": integrated_setup_provenance_contract(programme),
        },
        "finite_limits": {
            "qualified_duration_s": programme.qualified_duration_s,
            "qualified_endpoint_contract": "qualified_D14_D8_aperture_count_v2",
            "qualified_d14_aperture_count": programme.qualified_d14_aperture_count,
            "correction_response_reserve_d14_apertures": (
                programme.correction_response_reserve_d14_apertures
            ),
            "absolute_wall_clock_limit_s": programme.absolute_wall_limit_s,
            "maximum_total_automatic_applications": programme.maximum_applications,
            "maximum_total_physical_control_applications": (
                programme.maximum_physical_applications
            ),
            "maximum_cumulative_absolute_movement_codes": (
                programme.maximum_cumulative_movement_codes
            ),
            "maximum_combined_step_codes": programme.maximum_step_codes,
            "minimum_applied_cadence_s": programme.minimum_applied_cadence_s,
            "minimum_code": programme.minimum_code,
            "maximum_code": programme.maximum_code,
            "maximum_outstanding_requests": 1,
            "automatic_retry": False,
            "automatic_restoration": False,
            "live_extension": False,
        },
        "progressive_authority": {
            "states": sorted(programme.hybrid_states - {"SETUP_PENDING"}),
            **progressive_checkpoint_contract(programme),
            "response_class_sign_and_magnitude_are_admission_gates": False,
        },
        "command_envelope": {
            "identity_queries_before_setup": ["CONFIG?", "DUALCORE?", "DAC?", "ACTIVE?"],
            "setup": (
                "ACTIVE SETUP <authorization> <generation> <nonce> <expiry> "
                f"<session> 0x{programme.setup_code:04X} 1 <configuration_sha256>"
            ),
            "arm": "ACTIVE ARM <authorization_sequence> <nonce> <absolute_expiry_s>",
            "evidence_acknowledgement": (
                "ACTIVE EVIDENCE <request_sequence> <phase_1_to_4>"
            ),
            "priority_abort_only": "ACTIVE ABORT",
            "priority_abort_delivery_required_before_capture_close": True,
        },
        "gnss_metadata_hold": {
            "terminal": False,
            "preserve_last_confirmed_code": True,
            "preserve_estimator_and_phase_history": True,
            "fresh_causal_D14_D8_windows_required_after_metadata_requalification": 2,
        },
        "persistent_maintenance": {
            "enabled": True,
            "policy_id": policy.policy_id,
            "policy_sha256": policy.policy_sha256,
            "frequency_estimator_id": policy.frequency_estimator_id,
            "record_type": programme.maintenance_record_type,
            "record_contract": programme.maintenance_record_contract,
            "fll_pll_correction_debt": True,
            "debt_commit_requires_exact_application_and_first_consumer": True,
            "gnss_metadata_anomaly_enters_nonterminal_hold": True,
        },
        "D10": {
            "role": "external_event",
            "enters_D14_D8_validity_or_steering": False,
            "capture_storage_replay_required_when_present": True,
        },
        "terminal_requirements": {
            "one_confirmed_static_code": True,
            "outstanding_request": False,
            "outstanding_response": False,
            "latent_authority": False,
            "every_terminal_analyzed_sealed_and_registered": True,
        },
        "authority": authority,
    }
    bundle["bundle_sha256"] = _canonical_sha256(bundle)
    return bundle


def _validate_bundle(
    path: Path,
    programme: AdaptiveHybridProgramme | None = None,
    *,
    verify_deterministic_reproduction: bool,
) -> dict[str, Any]:
    bundle = _read_object(path.resolve())
    claimed = bundle.pop("bundle_sha256", None)
    observed = _canonical_sha256(bundle)
    bundle["bundle_sha256"] = claimed
    programme = programme or programme_from_mapping(bundle)
    if claimed != observed:
        raise ValueError("bundle semantic identity differs")
    frozen_inputs = bundle.get("authoritative_inputs")
    validate_authoritative_inputs(frozen_inputs)
    if (
        bundle.get("bundle_id") != programme.bundle_id
        or bundle.get("programme_id") != programme.programme_id
        or bundle.get("image_identity") != programme.profile_id
        or bundle.get("run_identity") != programme.runtime_run_identity
    ):
        raise ValueError("bundle identity differs")
    created_utc = bundle.get("created_utc")
    firmware = bundle.get("firmware")
    build_manifest = firmware.get("build_manifest") if isinstance(firmware, dict) else None
    if not isinstance(created_utc, str) or not isinstance(build_manifest, dict):
        raise ValueError("bundle creation or firmware identity is incomplete")
    try:
        parsed_created = datetime.fromisoformat(created_utc.replace("Z", "+00:00"))
        build_manifest_path = Path(str(build_manifest["path"])).resolve()
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("bundle creation or firmware identity is malformed") from error
    if not created_utc.endswith("Z") or parsed_created.tzinfo is None:
        raise ValueError("bundle creation time must be an explicit UTC instant")
    expected = create_bundle(
        build_manifest_path=build_manifest_path,
        programme=programme,
        _created_utc=created_utc,
        _authoritative_inputs=frozen_inputs,
        _verify_deterministic_reproduction=verify_deterministic_reproduction,
        _frozen_host_tools=(
            bundle.get("host_tools")
            if not verify_deterministic_reproduction
            else None
        ),
    )
    if bundle != expected:
        raise ValueError(
            "bundle build, firmware, replay, policy, tool, topology, limit, or authority identity differs"
        )
    return bundle


def validate_frozen_bundle(
    path: Path,
    programme: AdaptiveHybridProgramme | None = None,
) -> dict[str, Any]:
    """Validate immutable bundle bytes without repeating a firmware compile."""

    return _validate_bundle(
        path,
        programme,
        verify_deterministic_reproduction=False,
    )


def validate_bundle(
    path: Path,
    programme: AdaptiveHybridProgramme | None = None,
) -> dict[str, Any]:
    """Validate a bundle and reproduce its firmware from the current checkout."""

    return _validate_bundle(
        path,
        programme,
        verify_deterministic_reproduction=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-manifest", type=Path)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate", type=Path)
    parser.add_argument("--generate-progressive-replay", action="store_true")
    args = parser.parse_args(argv)
    if args.generate_progressive_replay:
        if args.output is None:
            parser.error("replay generation requires --output")
        result = create_progressive_replay(args.output)
    elif args.validate is not None:
        result = validate_bundle(args.validate)
    else:
        if args.build_manifest is None:
            parser.error("bundle creation requires --build-manifest")
        result = create_bundle(
            build_manifest_path=args.build_manifest,
            replay_path=args.replay,
        )
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            try:
                with args.output.open("x", encoding="utf-8") as stream:
                    json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
                    stream.write("\n")
            except FileExistsError as error:
                parser.error(f"refusing to overwrite bundle: {args.output}")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
