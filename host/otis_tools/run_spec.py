"""One inert immutable configuration for an OTIS adaptive-hybrid run.

The run specification binds firmware, host tools, campaign limits, and runtime
scientific contracts without granting physical authority.  A separate sealed
rehearsal receipt and explicit operator instruction are required to construct a
one-use entry capability.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from tools import build_firmware

from .acquisition_frontier import FRONTIER_PATH, FRONTIER_POLICY, FRONTIER_STATE_PATH
from .adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    BenchAttemptEnvelope,
    envelope_for_purpose,
    integrated_setup_provenance_contract,
    validate_bench_attempt_envelope,
)
from .authoritative_inputs import (
    REFERENCE_ACCEPTANCE_POLICY_PATH,
    ROOT_PROFILE,
    ValidatedAuthoritativeInputs,
    collect_authoritative_inputs,
    validate_authoritative_inputs,
)
from .firmware_artifact import (
    ValidatedFirmwareArtifact,
    load_firmware_artifact,
    validate_frozen_firmware_artifact,
)
from .run_paths import adaptive_hybrid_csv_files
from .time_domains import canonical_domain_declaration, validate_domain_declarations

CONTRACT = "otis_run_spec_v1"
RUN_RECORD_CONTRACT = "otis_run_record_v1"
REHEARSAL_RECEIPT_CONTRACT = "otis_run_spec_rehearsal_receipt_v1"
REHEARSAL_BOUNDARY_CONTRACT = "otis_rehearsal_boundaries_v1"
REHEARSAL_BOUNDARY_REPORT = "reports/rehearsal_boundaries_v1.json"
HOST_TOOLSET_CONTRACT = "otis_host_toolset_v1"
RUN_SPEC_FILENAME = "run_spec.json"
RUN_RECORD_FILENAME = "run_manifest.json"
EXPECTED_BAUD = 115200
CAPTURE_CONFIG = {
    "status_interval_s": 5,
    "write_timeout_s": 1,
    "normal_command_max_age_s": 2,
    "normal_command_batch_limit": 1,
}
FRESH_SERIAL_AUTO_DETECT = "capture_device_--auto-detect_exactly_one_/dev/cu.usbmodem*"
FIFO_PATHS = {
    "normal_command": "control/normal_commands.fifo",
    "emergency_abort": "control/emergency_abort.fifo",
}
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_COMMON_REHEARSAL_OPENING = (
    "capture_and_supervisor_processes_ready",
    "startup_census_preceded_control_authority",
)
_CONTROL_REHEARSAL_BOUNDARIES = (
    "setup_arm_and_acknowledgements_exact",
    "two_progressive_transactions_complete",
    "metadata_hold_nonterminal_and_requalified",
    "unanswered_review_retains_capture_and_lease_without_new_authority",
)
_COMMON_REHEARSAL_CLOSING = (
    "normal_transport_obstruction_detected",
    "priority_abort_delivered_before_capture_close",
    "capture_closed_and_offline_outcome_recorded",
)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError) as error:
        raise ValueError("run specification contains non-canonical JSON") from error


def _digest(value: object) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _utc(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    except FileExistsError as error:
        raise ValueError(f"refusing to overwrite immutable artifact: {path}") from error


def _binding(path: Path, *, relative_to: Path | None = None) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError(f"bound path is not a regular file: {path}")
    data = resolved.read_bytes()
    stored_path = (
        resolved.relative_to(relative_to.resolve()).as_posix()
        if relative_to is not None
        else str(resolved)
    )
    return {
        "path": stored_path,
        "sha256": sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def _host_toolset(module_root: Path | None = None) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[2]
    root = (module_root or (repo_root / "host/otis_tools")).resolve()
    paths = sorted(
        [path for path in root.glob("*.py") if path.name != "__init__.py"]
        + [
            repo_root / "tools/rehearse_host.py",
            repo_root / "tools/otis_rehearsal_device.py",
        ],
        key=lambda path: path.relative_to(repo_root).as_posix(),
    )
    if not paths or any(not path.is_file() for path in paths):
        raise ValueError("host operational toolset is incomplete")
    entries = [_binding(path, relative_to=repo_root) for path in paths]
    unsigned = {
        "schema_version": 1,
        "contract": HOST_TOOLSET_CONTRACT,
        "root": ".",
        "entries": entries,
    }
    return {**unsigned, "toolset_sha256": _digest(unsigned)}


def _validate_host_toolset(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "contract",
        "root",
        "entries",
        "toolset_sha256",
    }:
        raise ValueError("host toolset is malformed")
    unsigned = {key: item for key, item in value.items() if key != "toolset_sha256"}
    entries = value.get("entries")
    if (
        value.get("schema_version") != 1
        or value.get("contract") != HOST_TOOLSET_CONTRACT
        or value.get("root") != "."
        or value.get("toolset_sha256") != _digest(unsigned)
        or not isinstance(entries, list)
        or not entries
    ):
        raise ValueError("host toolset identity differs")
    paths: list[str] = []
    for item in entries:
        relative = item.get("path") if isinstance(item, dict) else None
        path = Path(str(relative))
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256", "size_bytes"}
            or not isinstance(relative, str)
            or path.is_absolute()
            or not (
                (len(path.parts) == 3 and path.parts[:2] == ("host", "otis_tools"))
                or (len(path.parts) == 2 and path.parts[0] == "tools")
            )
            or any(part in {"", ".", ".."} for part in path.parts)
            or not _HEX64.fullmatch(str(item.get("sha256", "")))
            or not isinstance(item.get("size_bytes"), int)
            or isinstance(item.get("size_bytes"), bool)
            or item["size_bytes"] <= 0
        ):
            raise ValueError("host tool binding is unsafe or malformed")
        paths.append(relative)
    if paths != sorted(set(paths)):
        raise ValueError("host tool bindings are duplicated or not ordered")
    return json.loads(_canonical_bytes(value))


def current_host_toolset_sha256() -> str:
    """Return the identity of the complete current operational host toolset."""

    return str(_host_toolset()["toolset_sha256"])


def verify_current_host_toolset(spec: ValidatedRunSpec) -> None:
    expected = spec.document()["host"]["toolset"]
    if _host_toolset() != expected:
        raise ValueError(
            "current host tool bytes differ from the frozen run specification"
        )


def _transaction_identities(inputs: ValidatedAuthoritativeInputs) -> dict[str, str]:
    policy = inputs.document(ROOT_PROFILE)
    bindings = policy.get("bindings")
    if not isinstance(bindings, dict):
        raise TypeError("adaptive-hybrid policy bindings are unavailable")

    def digest(name: str) -> str:
        relative = bindings.get(name)
        if not isinstance(relative, str):
            raise TypeError(f"adaptive-hybrid policy binding {name!r} is unavailable")
        return str(inputs.binding(relative)["sha256"])

    root_sha256 = str(inputs.binding(ROOT_PROFILE)["sha256"])
    return {
        "estimator_sha256": digest("frequency_estimator"),
        "model_sha256": digest("plant_model"),
        "active_policy_sha256": root_sha256,
        "response_policy_sha256": digest("response_classification"),
        "numerical_policy_sha256": root_sha256,
    }


def _reference_acceptance(inputs: ValidatedAuthoritativeInputs) -> dict[str, str]:
    policy = inputs.document(REFERENCE_ACCEPTANCE_POLICY_PATH)
    binding = inputs.binding(REFERENCE_ACCEPTANCE_POLICY_PATH)
    return {
        "policy_id": str(policy["policy_id"]),
        "policy_sha256": str(binding["sha256"]),
        "path": REFERENCE_ACCEPTANCE_POLICY_PATH,
    }


def _setup(bench: BenchAttemptEnvelope) -> dict[str, Any]:
    programme = ADAPTIVE_HYBRID_PROGRAMME
    limit = bench.limits.setup_application_limit
    code = bench.limits.setup_code
    return {
        "authorized_after_entry": limit == 1,
        "code": code,
        "code_hex": f"0x{code:04X}" if code is not None else None,
        "maximum_applications": limit,
        "same_code_reapplication_opens_new_epoch": limit == 1,
        "exact_consumer_epoch_propagation_required": limit == 1,
        "provenance": integrated_setup_provenance_contract(programme),
    }


def _effective_authority(
    bench: BenchAttemptEnvelope, *, physical: bool
) -> dict[str, Any]:
    programme = ADAPTIVE_HYBRID_PROGRAMME
    envelope = bench.as_dict()
    limits = envelope["authority"]
    timing = envelope["timing"]
    automatic = int(limits["automatic_application_limit"])
    return {
        "effective": True,
        "physical_execution": physical,
        "firmware_flash_limit": 1 if physical else 0,
        "reset_for_entry_only": physical,
        "serial_open": True,
        "command_fifo": True,
        "bench_attempt_purpose": bench.purpose,
        "bench_attempt_envelope_sha256": envelope["envelope_sha256"],
        "setup_stimulus": int(limits["setup_application_limit"]) == 1,
        "setup_code": limits["setup_code"],
        "setup_write_limit": limits["setup_application_limit"],
        "control_arm": int(limits["arm_submission_limit"]) > 0,
        "arm_submission_limit": limits["arm_submission_limit"],
        "live_acquisition_limit": 1,
        "maximum_total_automatic_applications": automatic,
        "required_completed_automatic_applications": limits[
            "required_completed_automatic_applications"
        ],
        "maximum_total_physical_control_applications": automatic if physical else 0,
        "total_dac_value_write_limit": limits["total_dac_value_write_limit"],
        "maximum_combined_step_codes": programme.maximum_step_codes if automatic else 0,
        "maximum_cumulative_absolute_movement_codes": programme.maximum_cumulative_movement_codes
        if automatic
        else 0,
        "minimum_applied_cadence_s": programme.minimum_applied_cadence_s
        if automatic
        else None,
        "minimum_code": programme.minimum_code if automatic else None,
        "maximum_code": programme.maximum_code if automatic else None,
        "progress_domain": timing["progress_domain"],
        "qualified_endpoint_contract": timing["endpoint_contract"],
        "automatic_application_admission_deadline_delta": timing[
            "automatic_application_admission_deadline_delta"
        ],
        "correction_response_reserve_delta": timing[
            "correction_response_reserve_delta"
        ],
        "first_dependent_decision_reserve_delta": timing[
            "first_dependent_decision_reserve_delta"
        ],
        "absolute_wall_clock_limit_s": timing["absolute_wall_limit_s"],
        "wall_limit_role": timing["wall_limit_role"],
        **({"wall_limit_origin": timing["wall_limit_origin"]}
           if "wall_limit_origin" in timing else {}),
        "maximum_outstanding_requests": limits["maximum_outstanding_requests"],
        "authority_initially_closed": envelope["causal_state"]["authority_closed"][
            "initial"
        ],
        "automatic_retry": False,
        "arm_retry": False,
        "automatic_restoration": False,
        "live_extension": False,
        "forced_correction": False,
        "authority_consumed_by_first_physical_terminal": physical,
        "setup_provenance": integrated_setup_provenance_contract(programme),
        "host_discrepancy_semantics": envelope["host_discrepancy_semantics"],
    }


def _campaign(bench: BenchAttemptEnvelope) -> dict[str, Any]:
    """Persist one canonical envelope; runtime projections derive all limits."""

    return {
        "operation": ADAPTIVE_HYBRID_PROGRAMME.operation,
        "bench_attempt": bench.as_dict(),
    }


def _required_files() -> list[dict[str, Any]]:
    required = {
        "raw_events_v1",
        "count_observations_v1",
        "pps_snapshots_v2",
        "accepted_pps_spans_v1",
        "estimates_v3",
        "active_transactions_v3",
        "active_hybrid_decisions_v3",
        "active_hybrid_maintenance_v2",
        "relative_phase_observations_v2",
        "phase_estimator_outputs_v2",
    }
    files = [dict(item) for item in adaptive_hybrid_csv_files()]
    for item in files:
        if item["contract"] in required and item.get("record_type") != "EVT":
            item.pop("optional", None)
    return files


def _channels() -> list[dict[str, Any]]:
    return [
        {
            "channel_id": 0,
            "pin": "D10",
            "role": "external_event",
            "record_type": "EVT",
            "record_family": "raw_events_v1",
            "authority": "evidence_only",
            "control_authority": False,
            "terminal_authority": False,
        },
        {
            "channel_id": 1,
            "pin": "D14",
            "role": "authoritative_pps_reference",
            "record_type": "REF",
            "record_family": "raw_events_v1",
        },
        {
            "channel_id": 2,
            "pin": "D8",
            "role": "pps_gated_oscillator_count",
            "record_family": "count_observations_v1",
        },
        {
            "channel_id": 3,
            "pin": "D6",
            "role": "diagnostic_forwarded_d9_clock_monitor_zero_authority",
            "record_family": "forwarded_monitor_snapshots_v1",
            "authority": "diagnostic_only",
            "control_authority": False,
            "terminal_authority": False,
        },
    ]


def _contract_versions(files: list[dict[str, Any]]) -> dict[str, int]:
    return {
        item["contract"]: (
            3
            if item["contract"]
            in {"estimates_v3", "active_transactions_v3", "active_hybrid_decisions_v3"}
            else 2
            if item["contract"]
            in {
                "active_hybrid_maintenance_v2",
                "relative_phase_observations_v2",
                "phase_estimator_outputs_v2",
            }
            else 1
        )
        for item in files
    }


def _runtime(inputs: ValidatedAuthoritativeInputs) -> dict[str, Any]:
    files = _required_files()
    required_csv = [item["path"] for item in files if not item.get("optional")]
    reports = [
        FRONTIER_PATH,
        FRONTIER_STATE_PATH,
        "reports/capture_device_state.json",
        "reports/adaptive_hybrid_supervisor_state.json",
        "reports/adaptive_hybrid_supervisor_events.jsonl",
        "reports/capture_segment_closure_v1.json",
    ]
    policy_binding = inputs.binding(ROOT_PROFILE)
    policy_document = inputs.document(ROOT_PROFILE)
    return {
        "authoritative_inputs": inputs.as_dict(),
        "policy": {
            **policy_binding,
            "policy_id": str(policy_document["policy_id"]),
            "policy_sha256": str(policy_binding["sha256"]),
        },
        "reference_acceptance": _reference_acceptance(inputs),
        "transaction_identities": _transaction_identities(inputs),
        "topology": {
            "sole_reference_input": "D14",
            "sole_oscillator_count_input": "D8",
            "independent_event_input_not_authority": "D10",
            "gnss_role": "same_receiver_D14_qualification_metadata_only",
            "serial_owner_count": 1,
            "serial_owner": "capture_device",
            "normal_and_priority_abort_fifos_distinct": True,
            "serial_device_selection": FRESH_SERIAL_AUTO_DETECT,
            "fifos": dict(FIFO_PATHS),
        },
        "acquisition_frontier": dict(FRONTIER_POLICY),
        "domains": [
            canonical_domain_declaration(name)
            for name in (
                "rp2040_monotonic_us32",
                "rp2040_monotonic_us64",
                "h1_oscillator_10mhz",
            )
        ],
        "channels": _channels(),
        "contracts": _contract_versions(files),
        "files": files,
        "expected_artifacts": [
            *required_csv,
            "raw/serial.log",
            *reports,
            RUN_SPEC_FILENAME,
            RUN_RECORD_FILENAME,
        ],
        "evidence_artifacts": [
            *reports,
            RUN_SPEC_FILENAME,
            RUN_RECORD_FILENAME,
        ],
        "known_limitations": [
            "D14 is the sole PPS/reference input and D8 is the sole oscillator/count input.",
            "D10 external-event evidence never enters timing, control, actuation, or the run terminal.",
            "D9 is the oscillator output; its D6 monitor is diagnostic-only and fails locally.",
        ],
    }


def _identity() -> dict[str, str]:
    programme = ADAPTIVE_HYBRID_PROGRAMME
    return {
        "programme_id": programme.programme_id,
        "image_identity": programme.profile_id,
        "run_identity": programme.runtime_run_identity,
        "evidence_epoch": programme.evidence_epoch,
        "stage": programme.live_stage,
    }


def _build_document(
    artifact: ValidatedFirmwareArtifact,
    *,
    purpose: str,
    created_utc: str,
) -> dict[str, Any]:
    bench = envelope_for_purpose(purpose)
    inputs = validate_authoritative_inputs(collect_authoritative_inputs())
    toolset = _host_toolset()
    repository = build_firmware.repository_context_report()
    unsigned = {
        "schema_version": 1,
        "contract": CONTRACT,
        "created_utc": created_utc,
        "identity": _identity(),
        "firmware": {"artifact": artifact.document()},
        "host": {
            "source_revision": repository["git_commit"],
            "repository_context": repository,
            "toolset": toolset,
            "capture": dict(CAPTURE_CONFIG),
        },
        "campaign": _campaign(bench),
        "runtime": _runtime(inputs),
    }
    return {**unsigned, "run_spec_sha256": _digest(unsigned)}


def _validate_spec_document(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "contract",
        "created_utc",
        "identity",
        "firmware",
        "host",
        "campaign",
        "runtime",
        "run_spec_sha256",
    }:
        raise ValueError("run specification shape differs")
    unsigned = {key: item for key, item in value.items() if key != "run_spec_sha256"}
    if (
        value.get("schema_version") != 1
        or value.get("contract") != CONTRACT
        or not _utc(value.get("created_utc"))
        or value.get("run_spec_sha256") != _digest(unsigned)
        or value.get("identity") != _identity()
    ):
        raise ValueError("run specification identity differs")
    firmware = value.get("firmware")
    if not isinstance(firmware, dict) or set(firmware) != {"artifact"}:
        raise ValueError("run specification firmware boundary is malformed")
    validate_frozen_firmware_artifact(firmware.get("artifact"))
    host = value.get("host")
    if (
        not isinstance(host, dict)
        or set(host) != {"source_revision", "repository_context", "toolset", "capture"}
        or not _HEX40.fullmatch(str(host.get("source_revision", "")))
        or not isinstance(host.get("repository_context"), dict)
        or host["repository_context"].get("firmware_identity_authority") is not False
        or host.get("capture") != CAPTURE_CONFIG
    ):
        raise ValueError("run specification host provenance is malformed")
    _validate_host_toolset(host.get("toolset"))
    campaign = value.get("campaign")
    if not isinstance(campaign, dict) or not isinstance(
        campaign.get("bench_attempt"), dict
    ):
        raise TypeError("run specification campaign is malformed")
    bench = validate_bench_attempt_envelope(campaign["bench_attempt"])
    if campaign != _campaign(bench):
        raise ValueError("run specification campaign envelope differs")
    runtime = value.get("runtime")
    if not isinstance(runtime, dict):
        raise TypeError("run specification runtime is malformed")
    inputs = validate_authoritative_inputs(runtime.get("authoritative_inputs"))
    if runtime != _runtime(inputs):
        raise ValueError("run specification runtime contracts differ")
    errors = validate_domain_declarations(runtime.get("domains"))
    if errors:
        raise ValueError("run specification time domains differ: " + "; ".join(errors))
    return json.loads(_canonical_bytes(value))


@dataclass(frozen=True, slots=True, init=False)
class ValidatedRunSpec:
    _encoded: str
    path: Path
    sha256: str

    def __init__(self, value: dict[str, Any], path: Path) -> None:
        object.__setattr__(self, "_encoded", _canonical_bytes(value).decode("ascii"))
        object.__setattr__(self, "path", path.resolve())
        object.__setattr__(self, "sha256", str(value["run_spec_sha256"]))

    def document(self) -> dict[str, Any]:
        return json.loads(self._encoded)

    @property
    def campaign(self) -> dict[str, Any]:
        return dict(self.document()["campaign"])

    @property
    def firmware(self) -> dict[str, Any]:
        return dict(self.document()["firmware"]["artifact"])

    @property
    def host_toolset_sha256(self) -> str:
        return str(self.document()["host"]["toolset"]["toolset_sha256"])

    def runtime_manifest(self, run_record: Mapping[str, Any]) -> dict[str, Any]:
        record = _validate_run_record(run_record, spec=self)
        value = self.document()
        identity = value["identity"]
        campaign = value["campaign"]
        bench = validate_bench_attempt_envelope(campaign["bench_attempt"])
        runtime = value["runtime"]
        artifact = value["firmware"]["artifact"]
        physical = record["execution_kind"] == "physical"
        authority = _effective_authority(bench, physical=physical)
        automatic = bench.limits.automatic_application_limit
        manifest = {
            "schema_version": 1,
            "evidence_epoch": identity["evidence_epoch"],
            "run_id": record["run_id"],
            "created_utc": record["started_at_utc"],
            "started_at_utc": record["started_at_utc"],
            "stage": identity["stage"],
            "programme_id": identity["programme_id"],
            "run_identity": identity["run_identity"],
            "image_identity": identity["image_identity"],
            "bench_attempt": campaign["bench_attempt"],
            "board": "arduino_nano_rp2040_connect",
            "capture_mode": "pio_fifo_irq_single_reference_owner",
            "control_mode": bench.purpose,
            "closed_loop_control": automatic > 0,
            "actionable": physical
            and (bench.limits.setup_application_limit > 0 or automatic > 0),
            "actuation_authorized": physical
            and (bench.limits.setup_application_limit > 0 or automatic > 0),
            "qualification_evidence": True,
            "execution_kind": record["execution_kind"],
            "entry_authorization": record["entry_authorization"],
            "run_spec": record["run_spec"],
            "firmware": artifact,
            "authoritative_inputs": runtime["authoritative_inputs"],
            "reference_acceptance": runtime["reference_acceptance"],
            "policy": runtime["policy"],
            "transaction_identities": runtime["transaction_identities"],
            "host": {
                "capture_tool": "host.otis_tools.capture_device",
                "supervisor_tool": "host.otis_tools.adaptive_hybrid_supervisor",
                "runner_tool": "host.otis_tools.live_run",
                "analyzer_tool": "host.otis_tools.adaptive_hybrid_analyze",
                "serial_device": record["serial_device"],
                "baud": EXPECTED_BAUD,
                "capture": dict(value["host"]["capture"]),
                **campaign["bench_attempt"]["device_identity"],
                "sole_serial_owner": True,
                "serial_owner_count": 1,
                "fifos": runtime["topology"]["fifos"],
                "tool_bindings": {
                    Path(item["path"]).stem: item
                    for item in value["host"]["toolset"]["entries"]
                },
                "host_toolset_sha256": value["host"]["toolset"]["toolset_sha256"],
                "source_revision": value["host"]["source_revision"],
            },
            "adaptive_hybrid": _runtime_campaign_section(bench, authority),
            "acquisition_frontier": runtime["acquisition_frontier"],
            "domains": runtime["domains"],
            "channels": runtime["channels"],
            "contracts": runtime["contracts"],
            "files": runtime["files"],
            "expected_artifacts": runtime["expected_artifacts"],
            "evidence_artifacts": runtime["evidence_artifacts"],
            "known_limitations": runtime["known_limitations"],
        }
        manifest["manifest_sha256"] = _digest(manifest)
        return manifest


def _runtime_campaign_section(
    bench: BenchAttemptEnvelope, authority: dict[str, Any]
) -> dict[str, Any]:
    envelope = bench.as_dict()
    limits = envelope["authority"]
    timing = envelope["timing"]
    automatic = int(limits["automatic_application_limit"])
    return {
        "mode": "adaptive_hybrid_bench_attempt",
        "purpose": bench.purpose,
        "bench_attempt_envelope_sha256": envelope["envelope_sha256"],
        "profile_id": ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        "run_identity": ADAPTIVE_HYBRID_PROGRAMME.runtime_run_identity,
        "authority": authority,
        "external_event_input": {
            "pin": "D10",
            "channel_id": 0,
            "record_type": "EVT",
            "role": "external_event",
            "optional": True,
            "authority": "evidence_only",
            "control_eligible": False,
            "terminal_eligible": False,
        },
        "setup": {
            **_setup(bench),
            "physical_applied_code_before_setup": integrated_setup_provenance_contract()[
                "physical_applied_code_before_setup"
            ],
        },
        "automatic_control": {
            "authorized": automatic > 0,
            "maximum_total_applications": automatic,
            "maximum_total_automatic_applications": automatic,
            "required_completed_automatic_applications": limits[
                "required_completed_automatic_applications"
            ],
            "arm_submission_limit": limits["arm_submission_limit"],
            "total_dac_value_write_limit": limits["total_dac_value_write_limit"],
            "maximum_step_codes": ADAPTIVE_HYBRID_PROGRAMME.maximum_step_codes
            if automatic
            else 0,
            "maximum_cumulative_movement_codes": ADAPTIVE_HYBRID_PROGRAMME.maximum_cumulative_movement_codes
            if automatic
            else 0,
            "minimum_applied_cadence_s": ADAPTIVE_HYBRID_PROGRAMME.minimum_applied_cadence_s
            if automatic
            else None,
            "minimum_code": ADAPTIVE_HYBRID_PROGRAMME.minimum_code
            if automatic
            else None,
            "maximum_code": ADAPTIVE_HYBRID_PROGRAMME.maximum_code
            if automatic
            else None,
            "maximum_outstanding_requests": limits["maximum_outstanding_requests"],
            "automatic_retry": False,
            "arm_retry": False,
            "automatic_restore": False,
            "forced_correction": False,
        },
        "progressive_authority": {
            "causal_state": envelope["causal_state"],
            "terminal_semantics": envelope["terminal_semantics"],
        },
        "qualification": {
            "progress_domain": timing["progress_domain"],
            "qualified_endpoint_contract": timing["endpoint_contract"],
            "automatic_application_admission_deadline_delta": timing[
                "automatic_application_admission_deadline_delta"
            ],
            "correction_response_reserve_delta": timing[
                "correction_response_reserve_delta"
            ],
            "first_dependent_decision_reserve_delta": timing[
                "first_dependent_decision_reserve_delta"
            ],
            "absolute_wall_clock_limit_s": timing["absolute_wall_limit_s"],
            "qualified_origin": "first_fresh_selected_D14_D8_estimate_after_setup_and_settling"
            if bench.limits.setup_application_limit
            else "first_coherent_no_setup_accepted_D14_D8_aperture_origin",
            "wall_clock_origin": timing.get(
                "wall_limit_origin", "run_manifest.started_at_utc"
            ),
            "wall_limit_role": timing["wall_limit_role"],
            "no_extension": True,
        },
    }


def build_run_spec(
    *,
    firmware_manifest_path: Path,
    purpose: str,
    output_path: Path,
    operator_instruction_ref: str | None = None,
    created_utc: str | None = None,
) -> ValidatedRunSpec:
    if operator_instruction_ref is not None:
        raise ValueError("an inert run specification cannot contain operator authority")
    timestamp = created_utc or _now()
    if not _utc(timestamp):
        raise ValueError("run specification creation timestamp is malformed")
    artifact = load_firmware_artifact(firmware_manifest_path)
    value = _build_document(artifact, purpose=purpose, created_utc=timestamp)
    _write_new(output_path, value)
    return load_run_spec(output_path)


def load_run_spec(path: Path) -> ValidatedRunSpec:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"run specification is unreadable: {path}") from error
    document = _validate_spec_document(value)
    return ValidatedRunSpec(document, path)


class ConsumedEntry:
    __slots__ = ("_recorded", "authorization", "spec_sha256")

    def __init__(self, *, spec_sha256: str, authorization: dict[str, str]) -> None:
        self.spec_sha256 = spec_sha256
        self.authorization = dict(authorization)
        self._recorded = False

    def record_authorization(self, spec: ValidatedRunSpec) -> dict[str, str]:
        if self.spec_sha256 != spec.sha256 or self._recorded:
            raise ValueError("consumed entry is mismatched or already recorded")
        self._recorded = True
        return dict(self.authorization)


class EntryCapability:
    __slots__ = ("_authorization", "_consumed", "_firmware_artifact", "_spec_sha256")

    def __init__(
        self,
        *,
        spec_sha256: str,
        authorization: dict[str, str],
        firmware_artifact: ValidatedFirmwareArtifact,
    ) -> None:
        self._spec_sha256 = spec_sha256
        self._authorization = dict(authorization)
        self._firmware_artifact = firmware_artifact
        self._consumed = False

    @property
    def firmware_artifact(self) -> ValidatedFirmwareArtifact:
        return self._firmware_artifact

    def consume(self, run_spec_sha256: str) -> ConsumedEntry:
        """Consume authority before upload; the returned value records entry later."""

        if self._spec_sha256 != run_spec_sha256 or self._consumed:
            raise ValueError(
                "physical entry capability is mismatched or already consumed"
            )
        self._consumed = True
        return ConsumedEntry(
            spec_sha256=self._spec_sha256, authorization=self._authorization
        )


def required_rehearsal_boundaries(spec: ValidatedRunSpec) -> list[str]:
    purpose = spec.document()["campaign"]["bench_attempt"]["purpose"]
    control = (
        _CONTROL_REHEARSAL_BOUNDARIES
        if purpose == "unattended_72_hour_hybrid_control"
        else ()
    )
    return [*_COMMON_REHEARSAL_OPENING, *control, *_COMMON_REHEARSAL_CLOSING]


def _validate_rehearsal_receipt(
    spec: ValidatedRunSpec,
    receipt: Mapping[str, Any],
    *,
    rehearsal_package_path: Path | None = None,
) -> str:
    expected_keys = {
        "schema_version",
        "contract",
        "status",
        "run_spec_sha256",
        "firmware_artifact_sha256",
        "firmware_binary_sha256",
        "host_toolset_sha256",
        "campaign_envelope_sha256",
        "package",
        "boundaries",
        "receipt_sha256",
    }
    if set(receipt) != expected_keys:
        raise ValueError("rehearsal receipt shape differs")
    unsigned = {key: item for key, item in receipt.items() if key != "receipt_sha256"}
    document = spec.document()
    artifact = document["firmware"]["artifact"]
    campaign = document["campaign"]
    required = required_rehearsal_boundaries(spec)
    package = receipt.get("package")
    boundaries = receipt.get("boundaries")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("contract") != REHEARSAL_RECEIPT_CONTRACT
        or receipt.get("status") != "passed"
        or receipt.get("receipt_sha256") != _digest(unsigned)
        or receipt.get("run_spec_sha256") != spec.sha256
        or receipt.get("firmware_artifact_sha256")
        != artifact["firmware_artifact_sha256"]
        or receipt.get("firmware_binary_sha256") != artifact["uf2"]["sha256"]
        or receipt.get("host_toolset_sha256")
        != document["host"]["toolset"]["toolset_sha256"]
        or receipt.get("campaign_envelope_sha256")
        != campaign["bench_attempt"]["envelope_sha256"]
        or not isinstance(package, dict)
        or set(package) != {"path", "package_content_sha256"}
        or not _HEX64.fullmatch(str(package.get("package_content_sha256", "")))
        or not isinstance(boundaries, dict)
        or set(boundaries) != {"path", "sha256"}
        or boundaries.get("path") != REHEARSAL_BOUNDARY_REPORT
        or not _HEX64.fullmatch(str(boundaries.get("sha256", "")))
    ):
        raise ValueError("rehearsal receipt does not prove the exact run specification")
    from .evidence_package import validate_package

    package_root = (
        rehearsal_package_path
        if rehearsal_package_path is not None
        else Path(str(package["path"]))
    )
    validated = validate_package(package_root)
    if validated.get("package_content_sha256") != package["package_content_sha256"]:
        raise ValueError("rehearsal receipt package content differs")
    run_manifest = validated.get("run_manifest")
    if (
        not isinstance(run_manifest, dict)
        or run_manifest.get("run_spec", {}).get("sha256") != spec.sha256
        or run_manifest.get("execution_kind") != "simulated"
        or run_manifest.get("entry_authorization") is not None
    ):
        raise ValueError(
            "rehearsal package is not a simulated run of the exact run specification"
        )
    analysis = validated.get("analysis")
    capture = validated.get("capture")
    if (
        not isinstance(capture, dict)
        or capture.get("integrity") != "complete"
        or not isinstance(analysis, dict)
        or analysis.get("status") != "passed"
        or analysis.get("outcome")
        not in {
            "qualified_complete",
        "endurance_complete",
            "bounded_nonpass",
            "interrupted_incomplete",
            "diagnostic_complete",
        }
    ):
        raise ValueError(
            "rehearsal package has no completed capture and offline outcome"
        )
    inventory = {
        item.get("path"): item
        for item in validated.get("inventory", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    retained_boundary = inventory.get(REHEARSAL_BOUNDARY_REPORT)
    if (
        not isinstance(retained_boundary, dict)
        or retained_boundary.get("sha256") != boundaries["sha256"]
    ):
        raise ValueError("rehearsal boundary report is absent from the sealed package")
    from .evidence_package import safe_join

    boundary_path = safe_join(package_root.resolve(), REHEARSAL_BOUNDARY_REPORT)
    if sha256(boundary_path.read_bytes()).hexdigest() != boundaries["sha256"]:
        raise ValueError("rehearsal boundary report bytes differ")
    try:
        boundary_report = json.loads(boundary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("rehearsal boundary report is unreadable") from error
    if not isinstance(boundary_report, dict):
        raise TypeError("rehearsal boundary report must be an object")
    boundary_unsigned = {
        key: item for key, item in boundary_report.items() if key != "report_sha256"
    }
    if (
        set(boundary_report)
        != {
            "schema_version",
            "contract",
            "run_spec_sha256",
            "required_boundaries",
            "boundary_results",
            "report_sha256",
        }
        or boundary_report.get("schema_version") != 1
        or boundary_report.get("contract") != REHEARSAL_BOUNDARY_CONTRACT
        or boundary_report.get("run_spec_sha256") != spec.sha256
        or boundary_report.get("required_boundaries") != required
        or boundary_report.get("boundary_results") != {name: True for name in required}
        or boundary_report.get("report_sha256") != _digest(boundary_unsigned)
    ):
        raise ValueError("rehearsal boundary report does not prove required boundaries")
    return str(receipt["receipt_sha256"])


def authorize_entry(
    spec: ValidatedRunSpec,
    *,
    rehearsal_receipt: Mapping[str, Any],
    operator_instruction_ref: str,
    attempt_reason: str,
    firmware_manifest_path: Path | None = None,
    rehearsal_package_path: Path | None = None,
) -> EntryCapability:
    if not isinstance(spec, ValidatedRunSpec):
        raise TypeError("physical entry requires a validated run specification")
    if (
        not isinstance(operator_instruction_ref, str)
        or not operator_instruction_ref.strip()
    ):
        raise ValueError(
            "physical entry requires an explicit operator instruction reference"
        )
    if not isinstance(attempt_reason, str) or not attempt_reason.strip():
        raise ValueError("physical entry requires an explicit attempt reason")
    verify_current_host_toolset(spec)
    artifact = spec.document()["firmware"]["artifact"]
    selected_manifest = (
        firmware_manifest_path
        if firmware_manifest_path is not None
        else Path(artifact["build_manifest"]["path"])
    )
    current_artifact = load_firmware_artifact(selected_manifest)
    if current_artifact.sha256 != artifact["firmware_artifact_sha256"]:
        raise ValueError(
            "physical entry firmware bytes differ from the run specification"
        )
    receipt_sha256 = _validate_rehearsal_receipt(
        spec,
        rehearsal_receipt,
        rehearsal_package_path=rehearsal_package_path,
    )
    return EntryCapability(
        spec_sha256=spec.sha256,
        authorization={
            "rehearsal_receipt_sha256": receipt_sha256,
            "operator_instruction_ref": operator_instruction_ref.strip(),
            "attempt_reason": attempt_reason.strip(),
        },
        firmware_artifact=current_artifact,
    )


def create_run_record(
    spec: ValidatedRunSpec,
    *,
    execution_kind: str,
    run_id: str,
    started_at_utc: str,
    serial_device: str,
    output_path: Path,
    consumed_entry: ConsumedEntry | None = None,
) -> dict[str, Any]:
    if execution_kind not in {"physical", "simulated"}:
        raise ValueError("run execution kind must be physical or simulated")
    if (
        not isinstance(run_id, str)
        or not run_id
        or "/" in run_id
        or run_id in {".", ".."}
    ):
        raise ValueError("run identity is malformed")
    if not _utc(started_at_utc):
        raise ValueError("run start timestamp is malformed")
    if execution_kind == "physical":
        if not serial_device.startswith("/dev/cu.usbmodem") or consumed_entry is None:
            raise ValueError("physical run requires a USB modem and consumed entry")
        entry_authorization: dict[str, str] | None = (
            consumed_entry.record_authorization(spec)
        )
    else:
        if not (serial_device.startswith(("/dev/ttys", "/dev/pts/"))):
            raise ValueError("simulated run requires an actual PTY slave path")
        if consumed_entry is not None:
            raise ValueError("simulated run cannot consume physical entry authority")
        entry_authorization = None
    if output_path.resolve().parent != spec.path.resolve().parent:
        raise ValueError(
            "run record and run specification must share one run directory"
        )
    file_binding = _binding(spec.path, relative_to=output_path.resolve().parent)
    if file_binding["path"] != RUN_SPEC_FILENAME:
        raise ValueError("run specification must be retained as run_spec.json")
    if spec.sha256 != _validate_spec_document(spec.document())["run_spec_sha256"]:
        raise ValueError("run specification binding differs")
    spec_binding = {
        "path": file_binding["path"],
        "sha256": spec.sha256,
        "file_sha256": file_binding["sha256"],
        "size_bytes": file_binding["size_bytes"],
    }
    unsigned = {
        "schema_version": 1,
        "contract": RUN_RECORD_CONTRACT,
        "execution_kind": execution_kind,
        "run_id": run_id,
        "started_at_utc": started_at_utc,
        "serial_device": serial_device,
        "run_spec": spec_binding,
        "entry_authorization": entry_authorization,
    }
    value = {**unsigned, "run_record_sha256": _digest(unsigned)}
    _write_new(output_path, value)
    return value


def _validate_run_record(
    value: Mapping[str, Any], *, spec: ValidatedRunSpec
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "contract",
        "execution_kind",
        "run_id",
        "started_at_utc",
        "serial_device",
        "run_spec",
        "entry_authorization",
        "run_record_sha256",
    }:
        raise ValueError("run record shape differs")
    detached = json.loads(_canonical_bytes(value))
    unsigned = {
        key: item for key, item in detached.items() if key != "run_record_sha256"
    }
    binding = detached.get("run_spec")
    if (
        detached.get("schema_version") != 1
        or detached.get("contract") != RUN_RECORD_CONTRACT
        or detached.get("run_record_sha256") != _digest(unsigned)
        or not _utc(detached.get("started_at_utc"))
        or not isinstance(binding, dict)
        or set(binding) != {"path", "sha256", "file_sha256", "size_bytes"}
        or binding.get("sha256") != spec.sha256
        or binding.get("file_sha256") != sha256(spec.path.read_bytes()).hexdigest()
        or binding.get("path") != RUN_SPEC_FILENAME
        or (spec.path.parent / str(binding.get("path"))).resolve()
        != spec.path.resolve()
        or binding.get("size_bytes") != spec.path.stat().st_size
    ):
        raise ValueError("run record identity or run-spec binding differs")
    kind = detached.get("execution_kind")
    device = detached.get("serial_device")
    entry = detached.get("entry_authorization")
    if kind == "physical":
        if (
            not isinstance(device, str)
            or not device.startswith("/dev/cu.usbmodem")
            or not isinstance(entry, dict)
            or set(entry)
            != {
                "rehearsal_receipt_sha256",
                "operator_instruction_ref",
                "attempt_reason",
            }
            or not _HEX64.fullmatch(str(entry.get("rehearsal_receipt_sha256", "")))
        ):
            raise ValueError("physical run record lacks exact entry authority")
    elif kind == "simulated":
        if (
            not isinstance(device, str)
            or not (device.startswith(("/dev/ttys", "/dev/pts/")))
            or entry is not None
        ):
            raise ValueError(
                "simulated run record claims physical authority or lacks a PTY"
            )
    else:
        raise ValueError("run record execution kind differs")
    return detached
