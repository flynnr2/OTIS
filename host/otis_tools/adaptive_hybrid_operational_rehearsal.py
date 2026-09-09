"""Run the current adaptive-hybrid operational path over a deterministic PTY.

The rehearsal exercises the installed host process topology without opening,
flashing, resetting, or commanding physical hardware.  It deliberately uses
the live supervisor class behind a private, strictly PTY-bound worker instead
of adding a rehearsal switch to the physical entry point.  Its report is an
activation *input candidate* only: it grants no authority and makes no claim
about USB CDC, firmware cross-core execution, DAC/I2C, D14/D8/D10 electrical
capture, or plant response.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import stat
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Iterable

from .abort_transport import send_abort
from .active_status_contract import (
    ACTIVE_STATUS_KEYS,
    ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    SNAPSHOT_BEGIN_KEY,
    SNAPSHOT_COMPLETE_KEY,
    SNAPSHOT_CONTRACT_KEY,
)
from .active_status_live_state import read_live_health_state
from .adaptive_hybrid_bundle import validate_bundle
from .adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    operational_rehearsal_authorization_contract,
    programme_from_mapping,
)
from .adaptive_hybrid_analyze import (
    replay_current_adaptive_hybrid_host_consumers,
)
from .adaptive_hybrid_monitor import (
    _exact_lifecycle_record_progress,
    _maintenance_evidence_progress,
)
from .adaptive_hybrid_policy import (
    AdaptiveHybridDecision,
    AdaptiveHybridObservation,
    AdaptiveHybridPhasePriorityController,
    policy_from_mapping,
)
from .adaptive_hybrid_proposal import validate_proposal
from .adaptive_hybrid_supervisor import (
    FORWARDED_MONITOR_OBSERVABILITY_KEYS,
    FORWARDED_OUTPUT_INTEGRATION_EXPECTED_HEALTH,
    _authoritative_capture_counters,
    create_validated_nonphysical_rehearsal_supervisor,
    load_validated_nonphysical_rehearsal_spec,
)
from .authoritative_inputs import (
    ROOT_PROFILE,
    authoritative_binding,
    authoritative_document,
    validate_authoritative_inputs,
)
from .capture_device import (
    CAPTURE_STATE,
    SEGMENT_CARRIER_STATE,
    SEGMENT_CLOSURE,
    SEGMENT_PROTOCOL_ID,
    SEGMENT_REQUEST,
    SEGMENT_RESPONSE_DIR,
    SEGMENT_TRANSITION_STAGE,
    _capture_state_ready,
    _serial_owner_pids,
)
from .contracts import (
    ACTIVE_HYBRID_DECISION_V2_FIELDS,
    ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS,
    ACTIVE_TRANSACTION_V2_FIELDS,
    CONTRACT_FIELDS,
)
from .evidence import (
    create_evidence_snapshot,
    validate_evidence_snapshot,
    validate_operational_rehearsal_package as _validate_rehearsal_package,
)
from .evidence_finalization import (
    advance_phase,
    begin_finalization,
    set_registration_intent,
)
from .evidence_index import package_identity, register_package, validate_index
from .prewrite_readiness_contract import (
    GNSS_PREWRITE_EXACT,
    HEALTH_INTEGRITY_EXACT,
    canonical_prewrite_fixture,
)
from .run_loader import (
    CAPTURE_IN_PROGRESS_FLAG,
    COMPLETE_MARKER,
    CURRENT_EVIDENCE_EPOCH,
    RunManifest,
)
from .serial_commands import parse_serial_command, send_timestamped_command_to_fifo
from .time_domains import canonical_domain_declaration, validate_domain_declarations


ROOT = Path(__file__).resolve().parents[2]
TOOL_ID = "adaptive_hybrid_operational_rehearsal_v1"
REPORT_KIND = "operational_path_rehearsal"
SEAL_TYPE = "adaptive_hybrid_operational_rehearsal_seal_v1"
ANALYZER_ID = "adaptive_hybrid_operational_rehearsal_analyze_v1"
MODE = "adaptive_hybrid_deterministic_process_topology_rehearsal_pty_v1"
SCENARIO = "adaptive_hybrid_two_transaction_metadata_hold_abort_rotation_v1"
CAPABILITY = "adaptive-hybrid-operational-rehearsal"
REHEARSAL_STAGE = "OTIS_ADAPTIVE_HYBRID_OPERATIONAL_REHEARSAL_PTY"
REPORT_NAME = "adaptive_hybrid_operational_rehearsal_v1.json"
SEAL_PATH = Path("reports/adaptive_hybrid_operational_rehearsal_seal_v1.json")
PROCESS_EVIDENCE_PATH = Path(
    "reports/adaptive_hybrid_operational_process_evidence_v1.json"
)
MONITOR_SAMPLES_PATH = Path("reports/adaptive_hybrid_rehearsal_monitor_v1.jsonl")
TRANSITION_DIR = Path("segments/transition")
TRANSITION_MANIFEST_PATH = TRANSITION_DIR / "run_manifest.json"
TRANSITION_CLOSURE_PATH = TRANSITION_DIR / SEGMENT_CLOSURE
TRANSITION_CAPTURE_STATE_PATH = TRANSITION_DIR / CAPTURE_STATE
TRANSITION_RAW_PATH = TRANSITION_DIR / "raw/serial.log"
TRANSITION_HEALTH_PATH = TRANSITION_DIR / "csv/health.csv"
COMPLETION_TYPE = "adaptive_hybrid_operational_rehearsal"
REQUIRED_BOUNDARIES = (
    "continuous_capture_and_exact_frozen_identity_consumption",
    "actual_capture_and_supervisor_process_topology",
    "setup_arm_and_evidence_ack_through_first_dependent_decision",
    "timeout_periodic_and_repeated_transaction_boundaries",
    "normal_command_transport_obstruction",
    "independent_priority_abort_submission_and_delivery_before_capture_close",
    "atomic_serial_owner_handoff_without_ownerless_interval",
    "clean_stop_shared_current_analyzer_consumers_snapshot_rehearsal_seal_and_successful_registration",
)
RP2040_US = 1_000_000


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _explicit_utc(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _atomic_json(path: Path, value: dict[str, Any], *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    descriptor = os.open(path, flags, 0o444 if exclusive else 0o644)
    try:
        if os.write(descriptor, payload) != len(payload):
            raise OSError(f"short JSON write: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _binding(path: Path) -> dict[str, Any]:
    source = path.resolve()
    if not source.is_file():
        raise ValueError(f"bound artifact is unavailable: {source}")
    return {
        "path": str(source),
        "sha256": _sha256_file(source),
        "size_bytes": source.stat().st_size,
    }


def _binding_exact(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    path = Path(str(value.get("path", ""))).resolve()
    return (
        path.is_file()
        and value.get("path") == str(path)
        and value.get("size_bytes") == path.stat().st_size
        and value.get("sha256", value.get("file_sha256")) == _sha256_file(path)
    )


def _is_pty(device: str) -> bool:
    canonical = os.path.realpath(device)
    return bool(
        device == canonical
        and (
            re.fullmatch(r"/dev/pts/[0-9]+", canonical) is not None
            or re.fullmatch(r"/dev/ttys[0-9]+", canonical) is not None
        )
    )


def _wait_until(
    predicate: Callable[[], bool], timeout_s: float, description: str
) -> None:
    deadline = time.monotonic() + timeout_s
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(0.02)
    suffix = f": {last_error}" if last_error is not None else ""
    raise TimeoutError(f"timed out waiting for {description}{suffix}")


def _write_all_fd(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("zero-byte PTY write")
        view = view[written:]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _wire_row(fields: list[str], row: dict[str, str]) -> bytes:
    return (",".join(row[field] for field in fields) + "\r\n").encode("ascii")


def _rehearsal_files() -> list[dict[str, Any]]:
    return [
        {
            "path": "csv/external_events.csv",
            "contract": "raw_events_v1",
            "record_type": "EVT",
            "optional": True,
        },
        {
            "path": "csv/reference_events.csv",
            "contract": "raw_events_v1",
            "record_type": "REF",
            "optional": True,
        },
        {"path": "csv/count_observations.csv", "contract": "count_observations_v1", "optional": True},
        {"path": "csv/pps_snapshots.csv", "contract": "pps_snapshots_v1", "optional": True},
        {"path": "csv/health.csv", "contract": "health_v1"},
        {"path": "csv/dac_steps.csv", "contract": "dac_steps_v1", "optional": True},
        {"path": "csv/estimates_v2.csv", "contract": "estimates_v2", "optional": True},
        {"path": "csv/control_previews_v1.csv", "contract": "control_previews_v1", "optional": True},
        {"path": "csv/active_transactions_v2.csv", "contract": "active_transactions_v2"},
        {"path": "csv/active_hybrid_decisions_v2.csv", "contract": "active_hybrid_decisions_v2"},
        {"path": "csv/active_hybrid_maintenance_v1.csv", "contract": "active_hybrid_maintenance_v1"},
    ]


def _channels() -> list[dict[str, Any]]:
    return [
        {
            "channel_id": 0,
            "pin": "D10",
            "role": "external_event",
            "record_type": "EVT",
            "authority": "evidence_only",
            "control_authority": False,
            "terminal_authority": False,
        },
        {
            "channel_id": 1,
            "pin": "D14",
            "role": "authoritative_pps_reference",
            "record_type": "REF",
        },
        {
            "channel_id": 2,
            "pin": "D8",
            "role": "oscillator_count",
            "record_type": "CNT",
        },
        {
            "channel_id": 3,
            "pin": "D6",
            "role": "forwarded_D9_monitor_diagnostic_only",
            "record_type": "MNS",
            "control_authority": False,
            "terminal_authority": False,
        },
    ]


def create_rehearsal_run_manifest(
    *,
    run_dir: Path,
    bundle_path: Path,
    bundle: dict[str, Any],
    proposal_path: Path,
    proposal: dict[str, Any],
    device: str,
) -> Path:
    """Create the one nonphysical manifest accepted by the private worker."""

    programme = ADAPTIVE_HYBRID_PROGRAMME
    files = _rehearsal_files()
    value: dict[str, Any] = {
        "schema_version": 1,
        "template": False,
        "run_id": run_dir.name,
        "created_utc": _utc_now(),
        "started_at_utc": _utc_now(),
        "evidence_epoch": CURRENT_EVIDENCE_EPOCH,
        # Keep this deliberately outside the live stage.  Generic current-run
        # loaders must reject a deterministic PTY as a physical campaign.
        "stage": REHEARSAL_STAGE,
        "mode": MODE,
        "scenario": SCENARIO,
        "programme_id": programme.programme_id,
        "run_identity": programme.runtime_run_identity,
        "image_identity": programme.profile_id,
        "board": "deterministic_pty_no_physical_hardware",
        "capture_mode": "real_capture_device_process_over_pty",
        "qualification_evidence": False,
        "physical_actions_performed": 0,
        "actionable": False,
        "actuation_authorized": False,
        "authority_effective": False,
        "closed_loop_control": False,
        "bundle": {
            **_binding(bundle_path),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "proposal": {
            **_binding(proposal_path),
            "proposal_sha256": proposal["proposal_sha256"],
        },
        "activation": {
            "activation_sha256": "0" * 64,
            "status": "rehearsal_no_physical_authority",
        },
        "firmware": bundle["firmware"],
        "authoritative_inputs": bundle["authoritative_inputs"],
        "policy": bundle["policy"],
        "host": {
            "version": TOOL_ID,
            "source_revision": str(bundle["firmware"]["source_revision"]),
            "serial_device": device,
            "baud": 115200,
            "sole_serial_owner": True,
            "serial_owner_count": 1,
            "tool_bindings": bundle["host_tools"],
            "fifos": {
                "normal_command": "control/normal_commands.fifo",
                "emergency_abort": "control/emergency_abort.fifo",
                "host_abort": "control/host_abort.fifo",
            },
        },
        programme.manifest_section: {
            "profile_id": programme.profile_id,
            "run_identity": programme.runtime_run_identity,
            "setup": {"code": programme.setup_code, "applications": 1},
            "automatic_control": {
                "maximum_total_applications": programme.maximum_physical_applications,
                "maximum_step_codes": programme.maximum_step_codes,
                "maximum_cumulative_movement_codes": programme.maximum_cumulative_movement_codes,
                "minimum_applied_cadence_s": programme.minimum_applied_cadence_s,
                "minimum_code": programme.minimum_code,
                "maximum_code": programme.maximum_code,
                "automatic_retry": False,
                "automatic_restore": False,
            },
            "qualification": {
                "qualified_duration_s": programme.qualified_duration_s,
                "qualified_endpoint_contract": "qualified_D14_D8_aperture_count_v2",
                "qualified_d14_aperture_count": programme.qualified_d14_aperture_count,
                "correction_response_reserve_d14_apertures": programme.correction_response_reserve_d14_apertures,
                "absolute_wall_clock_limit_s": programme.absolute_wall_limit_s,
                "no_extension": True,
            },
            "D10": {
                "role": "optional_external_event_evidence",
                "enters_D14_D8_validity_control_or_terminal": False,
            },
        },
        "domains": [
            canonical_domain_declaration("rp2040_monotonic_us32"),
            canonical_domain_declaration("rp2040_monotonic_us64"),
            canonical_domain_declaration("h1_adaptive_hybrid_ocxo_10mhz"),
        ],
        "channels": _channels(),
        "contracts": {
            entry["contract"]: (
                2
                if entry["contract"]
                in {"estimates_v2", "active_transactions_v2", "active_hybrid_decisions_v2"}
                else 1
            )
            for entry in files
        },
        "files": files,
        "expected_artifacts": [
            "raw/serial.log",
            CAPTURE_STATE.as_posix(),
            "reports/adaptive_hybrid_supervisor_state.json",
            "reports/adaptive_hybrid_supervisor_events.jsonl",
            SEGMENT_CLOSURE.as_posix(),
            PROCESS_EVIDENCE_PATH.as_posix(),
            MONITOR_SAMPLES_PATH.as_posix(),
            TRANSITION_MANIFEST_PATH.as_posix(),
            TRANSITION_CLOSURE_PATH.as_posix(),
            TRANSITION_CAPTURE_STATE_PATH.as_posix(),
            TRANSITION_RAW_PATH.as_posix(),
            TRANSITION_HEALTH_PATH.as_posix(),
        ],
        "evidence_artifacts": [
            "raw/serial.log",
            CAPTURE_STATE.as_posix(),
            "reports/adaptive_hybrid_supervisor_state.json",
            "reports/adaptive_hybrid_supervisor_events.jsonl",
            SEGMENT_CLOSURE.as_posix(),
            PROCESS_EVIDENCE_PATH.as_posix(),
            MONITOR_SAMPLES_PATH.as_posix(),
            TRANSITION_MANIFEST_PATH.as_posix(),
            TRANSITION_CLOSURE_PATH.as_posix(),
            TRANSITION_CAPTURE_STATE_PATH.as_posix(),
            TRANSITION_RAW_PATH.as_posix(),
            TRANSITION_HEALTH_PATH.as_posix(),
        ],
    }
    value["manifest_sha256"] = _canonical_sha256(value)
    path = run_dir / "run_manifest.json"
    _atomic_json(path, value, exclusive=True)
    return path


def _validate_manifest_value(
    path: Path,
    value: dict[str, Any],
    *,
    bundle: dict[str, Any],
    proposal: dict[str, Any],
) -> dict[str, Any]:
    programme = programme_from_mapping(value)
    unsigned = {key: item for key, item in value.items() if key != "manifest_sha256"}
    host = value.get("host")
    section = value.get(programme.manifest_section)
    if not isinstance(host, dict) or not isinstance(section, dict):
        raise ValueError("rehearsal manifest host/programme section is malformed")
    device = str(host.get("serial_device", ""))
    expected_fifos = {
        "normal_command": "control/normal_commands.fifo",
        "emergency_abort": "control/emergency_abort.fifo",
        "host_abort": "control/host_abort.fifo",
    }
    artifacts = [
        "raw/serial.log",
        CAPTURE_STATE.as_posix(),
        "reports/adaptive_hybrid_supervisor_state.json",
        "reports/adaptive_hybrid_supervisor_events.jsonl",
        SEGMENT_CLOSURE.as_posix(),
        PROCESS_EVIDENCE_PATH.as_posix(),
        MONITOR_SAMPLES_PATH.as_posix(),
        TRANSITION_MANIFEST_PATH.as_posix(),
        TRANSITION_CLOSURE_PATH.as_posix(),
        TRANSITION_CAPTURE_STATE_PATH.as_posix(),
        TRANSITION_RAW_PATH.as_posix(),
        TRANSITION_HEALTH_PATH.as_posix(),
    ]
    expected_host = {
        "version": TOOL_ID,
        "source_revision": str(bundle["firmware"]["source_revision"]),
        "serial_device": device,
        "baud": 115200,
        "sole_serial_owner": True,
        "serial_owner_count": 1,
        "tool_bindings": bundle["host_tools"],
        "fifos": expected_fifos,
    }
    expected_section = {
        "profile_id": programme.profile_id,
        "run_identity": programme.runtime_run_identity,
        "setup": {"code": programme.setup_code, "applications": 1},
        "automatic_control": {
            "maximum_total_applications": programme.maximum_physical_applications,
            "maximum_step_codes": programme.maximum_step_codes,
            "maximum_cumulative_movement_codes": programme.maximum_cumulative_movement_codes,
            "minimum_applied_cadence_s": programme.minimum_applied_cadence_s,
            "minimum_code": programme.minimum_code,
            "maximum_code": programme.maximum_code,
            "automatic_retry": False,
            "automatic_restore": False,
        },
        "qualification": {
            "qualified_duration_s": programme.qualified_duration_s,
            "qualified_endpoint_contract": "qualified_D14_D8_aperture_count_v2",
            "qualified_d14_aperture_count": programme.qualified_d14_aperture_count,
            "correction_response_reserve_d14_apertures": programme.correction_response_reserve_d14_apertures,
            "absolute_wall_clock_limit_s": programme.absolute_wall_limit_s,
            "no_extension": True,
        },
        "D10": {
            "role": "optional_external_event_evidence",
            "enters_D14_D8_validity_control_or_terminal": False,
        },
    }
    expected_contracts = {
        entry["contract"]: (
            2
            if entry["contract"]
            in {
                "estimates_v2",
                "active_transactions_v2",
                "active_hybrid_decisions_v2",
            }
            else 1
        )
        for entry in _rehearsal_files()
    }
    expected_top_level = {
        "schema_version",
        "template",
        "run_id",
        "created_utc",
        "started_at_utc",
        "evidence_epoch",
        "stage",
        "mode",
        "scenario",
        "programme_id",
        "run_identity",
        "image_identity",
        "board",
        "capture_mode",
        "qualification_evidence",
        "physical_actions_performed",
        "actionable",
        "actuation_authorized",
        "authority_effective",
        "closed_loop_control",
        "bundle",
        "proposal",
        "activation",
        "firmware",
        "authoritative_inputs",
        "policy",
        "host",
        programme.manifest_section,
        "domains",
        "channels",
        "contracts",
        "files",
        "expected_artifacts",
        "evidence_artifacts",
        "manifest_sha256",
    }
    created_valid = _explicit_utc(value.get("created_utc"))
    started_valid = _explicit_utc(value.get("started_at_utc"))
    exact = (
        set(value) == expected_top_level
        and path == path.parent / "run_manifest.json"
        and value.get("run_id") == path.parent.name
        and created_valid
        and started_valid
        and value.get("manifest_sha256") == _canonical_sha256(unsigned)
        and value.get("schema_version") == 1
        and value.get("template") is False
        and value.get("evidence_epoch") == programme.evidence_epoch
        and value.get("stage") == REHEARSAL_STAGE
        and value.get("mode") == MODE
        and value.get("scenario") == SCENARIO
        and value.get("image_identity") == programme.profile_id
        and value.get("run_identity") == programme.runtime_run_identity
        and value.get("qualification_evidence") is False
        and value.get("physical_actions_performed") == 0
        and value.get("actionable") is False
        and value.get("actuation_authorized") is False
        and value.get("authority_effective") is False
        and value.get("closed_loop_control") is False
        and value.get("board") == "deterministic_pty_no_physical_hardware"
        and value.get("capture_mode") == "real_capture_device_process_over_pty"
        and _is_pty(device)
        and host == expected_host
        and value.get("bundle")
        == {**_binding(Path(str(value["bundle"]["path"]))), "bundle_sha256": bundle["bundle_sha256"]}
        and value.get("proposal")
        == {**_binding(Path(str(value["proposal"]["path"]))), "proposal_sha256": proposal["proposal_sha256"]}
        and value.get("activation")
        == {"activation_sha256": "0" * 64, "status": "rehearsal_no_physical_authority"}
        and value.get("firmware") == bundle.get("firmware")
        and value.get("authoritative_inputs") == bundle.get("authoritative_inputs")
        and value.get("policy") == bundle.get("policy")
        and value.get("bundle", {}).get("bundle_sha256") == bundle.get("bundle_sha256")
        and value.get("proposal", {}).get("proposal_sha256") == proposal.get("proposal_sha256")
        and proposal.get("exact_bundle", {}).get("bundle_sha256") == bundle.get("bundle_sha256")
        and section == expected_section
        and value.get("domains")
        == [
            canonical_domain_declaration("rp2040_monotonic_us32"),
            canonical_domain_declaration("rp2040_monotonic_us64"),
            canonical_domain_declaration("h1_adaptive_hybrid_ocxo_10mhz"),
        ]
        and value.get("channels") == _channels()
        and value.get("files") == _rehearsal_files()
        and value.get("contracts") == expected_contracts
        and value.get("expected_artifacts") == artifacts
        and value.get("evidence_artifacts") == artifacts
    )
    if not exact:
        raise ValueError("rehearsal manifest identity or nonphysical boundary differs")
    if not _binding_exact(value.get("bundle")) or not _binding_exact(value.get("proposal")):
        raise ValueError("rehearsal manifest bundle/proposal bytes differ")
    if not all(_binding_exact(item) for item in bundle["host_tools"].values()):
        raise ValueError("rehearsal manifest current host-tool closure differs")
    validate_authoritative_inputs(value.get("authoritative_inputs"))
    domain_errors = validate_domain_declarations(value.get("domains"), require_complete=True)
    if domain_errors:
        raise ValueError("rehearsal manifest time domains differ: " + "; ".join(domain_errors))
    # The live supervisor contract itself is reused below, but only after the
    # private validator has established the exact no-authority PTY boundary.
    load_validated_nonphysical_rehearsal_spec(value)
    return value


def validate_rehearsal_run_manifest(
    path: Path,
    *,
    bundle: dict[str, Any] | None = None,
    proposal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the private PTY manifest without touching physical authority."""

    path = path.resolve()
    value = _read_object(path, "rehearsal run manifest")
    bundle_binding = value.get("bundle", {})
    proposal_binding = value.get("proposal", {})
    selected_bundle = bundle or validate_bundle(
        Path(str(bundle_binding.get("path", ""))).resolve(), ADAPTIVE_HYBRID_PROGRAMME
    )
    selected_proposal = proposal or validate_proposal(
        Path(str(proposal_binding.get("path", ""))).resolve(), ADAPTIVE_HYBRID_PROGRAMME
    )
    return _validate_manifest_value(
        path, value, bundle=selected_bundle, proposal=selected_proposal
    )


@dataclass(frozen=True)
class TransactionFixture:
    request_decision: dict[str, str]
    request_maintenance: dict[str, str]
    phases: tuple[dict[str, str], ...]
    application_maintenance: dict[str, str]
    response_decision: dict[str, str]
    response_decision_maintenance: dict[str, str]
    response_maintenance: dict[str, str]


@dataclass(frozen=True)
class LifecycleFixture:
    manual_start: dict[str, str]
    policy_activation: dict[str, str]
    first_transaction: TransactionFixture
    metadata_hold: dict[str, str]
    metadata_requalified: dict[str, str]
    first_requalification_decision: dict[str, str]
    first_requalification_maintenance: dict[str, str]
    second_requalification_decision: dict[str, str]
    second_requalification_maintenance: dict[str, str]
    second_transaction: TransactionFixture

    @property
    def decisions(self) -> list[dict[str, str]]:
        return [
            self.first_transaction.request_decision,
            self.first_transaction.response_decision,
            self.first_requalification_decision,
            self.second_requalification_decision,
            self.second_transaction.request_decision,
            self.second_transaction.response_decision,
        ]

    @property
    def transactions(self) -> list[dict[str, str]]:
        return [
            self.manual_start,
            *self.first_transaction.phases,
            *self.second_transaction.phases,
        ]

    @property
    def maintenance(self) -> list[dict[str, str]]:
        return [
            self.policy_activation,
            self.first_transaction.request_maintenance,
            self.first_transaction.application_maintenance,
            self.first_transaction.response_decision_maintenance,
            self.first_transaction.response_maintenance,
            self.metadata_hold,
            self.metadata_requalified,
            self.first_requalification_maintenance,
            self.second_requalification_maintenance,
            self.second_transaction.request_maintenance,
            self.second_transaction.application_maintenance,
            self.second_transaction.response_decision_maintenance,
            self.second_transaction.response_maintenance,
        ]


class _LifecycleBuilder:
    """Generate firmware-shaped current records through the policy oracle."""

    def __init__(self, bundle: dict[str, Any]) -> None:
        self.bundle = bundle
        self.programme = ADAPTIVE_HYBRID_PROGRAMME
        self.policy_document = authoritative_document(
            bundle["authoritative_inputs"], ROOT_PROFILE
        )
        root_binding = authoritative_binding(bundle["authoritative_inputs"], ROOT_PROFILE)
        self.policy = policy_from_mapping(
            self.policy_document, policy_sha256=str(root_binding["sha256"])
        )
        self.bindings = {
            name: authoritative_binding(bundle["authoritative_inputs"], relative)
            for name, relative in self.policy_document["bindings"].items()
        }
        self.controller = AdaptiveHybridPhasePriorityController(
            self.policy,
            setup_applied_code=self.programme.setup_code,
            setup_dac_epoch=1,
        )
        self.hybrid_sequence = 0
        self.maintenance_sequence = 0
        self.burst_sequence = 0

    def _controller_state(self) -> str:
        controller = self.controller
        if controller.fail_static_reason is not None:
            return "FAIL_STATIC"
        if controller.metadata_hold:
            return "METADATA_HOLD"
        if controller.response_pending:
            return "RESPONSE_PENDING"
        if controller.request_pending:
            return "REQUEST_PENDING"
        if controller.persistence_count:
            return "PERSISTENCE_HOLD"
        return "READY"

    def _snapshot(self, suffix: str) -> dict[str, str]:
        controller = self.controller
        return {
            f"maintenance_state_{suffix}": self._controller_state(),
            f"committed_fll_debt_{suffix}_picocodes": str(
                controller.debt.fll_picocodes
            ),
            f"committed_pll_debt_{suffix}_picocodes": str(
                controller.debt.pll_picocodes
            ),
            f"request_pending_{suffix}": str(controller.request_pending).lower(),
            f"response_pending_{suffix}": str(controller.response_pending).lower(),
            f"metadata_hold_{suffix}": str(controller.metadata_hold).lower(),
            f"persistence_count_{suffix}": str(controller.persistence_count),
            f"requalification_window_count_{suffix}": str(
                controller.requalification_window_count
            ),
        }

    def _frontier_relation(self, observation: AdaptiveHybridObservation) -> str:
        closing = (
            self.controller._requalification_last_closing_frontier
            if self.controller.metadata_requalified
            else self.controller.last_closing_frontier
        )
        if closing is None:
            return "first"
        if observation.source_first_sequence < closing:
            return "overlap"
        if observation.source_first_sequence == closing:
            return "contiguous"
        return "gap"

    def _interval_sign(self, observation: AdaptiveHybridObservation) -> int:
        if not observation.phase_valid:
            return 0
        _centre, lower, upper = self.controller._centre(observation)
        return self.controller._sign(lower, upper)

    def _observation(
        self,
        *,
        timestamp_s: int,
        source_first: int,
        source_last: int,
        counts: int,
        phase: int,
    ) -> AdaptiveHybridObservation:
        return AdaptiveHybridObservation(
            timestamp_s=timestamp_s,
            timestamp_ticks=timestamp_s * RP2040_US,
            capture_session=1,
            source_first_sequence=source_first,
            source_last_sequence=source_last,
            dac_epoch=self.controller.dac_epoch,
            applied_code=self.controller.applied_code,
            accumulated_edge_error_counts=counts,
            tight_state="TIGHT_INSIDE",
            phase_epoch=1,
            relative_phase_cycles=phase,
        )

    @staticmethod
    def _hybrid_state(
        controller: AdaptiveHybridPhasePriorityController, *, phase_valid: bool
    ) -> str:
        if controller.fail_static_reason is not None:
            return "FAIL_STATIC"
        if not phase_valid:
            return "PHASE_DEGRADED_FREQUENCY_ONLY"
        if controller.request_pending or controller.response_pending:
            return "FIRST_PHASE_TRANSACTION"
        if controller.application_count == 0:
            return "PHASE_QUALIFY"
        return "HYBRID_TRACKING"

    def _decision_row(
        self,
        observation: AdaptiveHybridObservation,
        decision: AdaptiveHybridDecision,
        *,
        state_before: str,
        applications_before: int,
        movement_before: int,
        authority_state: str,
    ) -> dict[str, str]:
        self.hybrid_sequence += 1
        conservative_gain = 0.000173340101
        fll_hz = decision.raw_fll_picocodes / 1_000_000_000_000 * conservative_gain
        pll_hz = decision.raw_pll_picocodes / 1_000_000_000_000 * conservative_gain
        combined_hz = (
            decision.raw_combined_picocodes / 1_000_000_000_000 * conservative_gain
        )
        row = {field: "0" for field in ACTIVE_HYBRID_DECISION_V2_FIELDS}
        row.update(
            {
                "record_type": "AHY",
                "schema_version": "2",
                "hybrid_record_sequence": str(self.hybrid_sequence),
                "decision_sequence": str(decision.decision_sequence),
                "decision_timestamp_ticks": str(observation.timestamp_ticks),
                "time_domain": "rp2040_monotonic_us64",
                "decision_timestamp_s": str(observation.timestamp_s),
                "run_identity": self.programme.runtime_run_identity,
                "build_identity": str(self.bundle["firmware"]["build_identity"]),
                "image_identity": self.programme.profile_id,
                "capture_session": str(observation.capture_session),
                "source_first_sequence": str(observation.source_first_sequence),
                "source_last_sequence": str(observation.source_last_sequence),
                "frequency_estimator_sha256": self.bindings["frequency_estimator"]["sha256"],
                "frequency_error_hz": f"{-observation.accumulated_edge_error_counts / 600.0:.12f}",
                "accumulated_edge_error_counts": str(observation.accumulated_edge_error_counts),
                "tight_state": observation.tight_state,
                "phase_estimator_sha256": self.bindings["phase_estimator"]["sha256"],
                "phase_epoch": str(observation.phase_epoch),
                "phase_observation_sequence": str(observation.source_last_sequence),
                "relative_phase_cycles": str(observation.relative_phase_cycles),
                "phase_continuous": str(observation.phase_valid).lower(),
                "phase_current": str(observation.phase_valid).lower(),
                "phase_step_detected": "false",
                "phase_recorder_published": str(observation.phase_valid).lower(),
                "current_applied_code": str(observation.applied_code),
                "dac_epoch": str(observation.dac_epoch),
                "phase_applied_code": str(observation.applied_code),
                "phase_dac_epoch": str(observation.dac_epoch),
                "state_before": state_before,
                "state_after": self._hybrid_state(
                    self.controller, phase_valid=observation.phase_valid
                ),
                "frequency_term_hz": f"{fll_hz:.12f}",
                "phase_term_hz": f"{pll_hz:.12f}",
                "combined_demand_hz": f"{combined_hz:.12f}",
                "raw_combined_delta_codes": f"{decision.raw_combined_picocodes / 1_000_000_000_000:.12f}",
                "requested_delta_codes": str(decision.requested_delta_codes),
                "requested_code": str(decision.requested_code),
                "counterfactual_frequency_only_delta_codes": str(
                    decision.counterfactual_frequency_only_delta_codes
                ),
                "phase_materially_influenced": str(
                    decision.phase_materially_influenced
                ).lower(),
                "step_limited": str(decision.step_limited).lower(),
                "range_clamped": str(decision.range_clamped).lower(),
                "cadence_limited": str(decision.cadence_limited).lower(),
                "count_limited": str(decision.count_limited).lower(),
                "cumulative_budget_limited": str(
                    decision.cumulative_budget_limited
                ).lower(),
                "correction_count_before": str(applications_before),
                "cumulative_movement_before_codes": str(movement_before),
                "authority_state": authority_state,
                "response_class": "unavailable",
                "actual_applied_code": str(observation.applied_code),
                "actual_dac_epoch": str(observation.dac_epoch),
                "downstream_epoch_exact": "true",
                "reason": decision.reason,
                "active_policy_sha256": self.policy.policy_sha256,
                "response_policy_sha256": self.bindings["response_classification"]["sha256"],
                "actionable": "false",
            }
        )
        return row

    def _append_decision(
        self,
        observation: AdaptiveHybridObservation,
        *,
        authority_state: str = "ARMED",
    ) -> tuple[AdaptiveHybridDecision, dict[str, str], dict[str, str]]:
        before = {
            **self._snapshot("before"),
            "frontier_relation_before": self._frontier_relation(observation),
            "interval_sign_before": str(self._interval_sign(observation)),
            "current_code": str(self.controller.applied_code),
            "current_epoch": str(self.controller.dac_epoch),
        }
        state_before = self._hybrid_state(
            self.controller, phase_valid=observation.phase_valid
        )
        applications_before = self.controller.application_count
        movement_before = self.controller.cumulative_movement_codes
        decision = self.controller.decide(observation)
        row = self._decision_row(
            observation,
            decision,
            state_before=state_before,
            applications_before=applications_before,
            movement_before=movement_before,
            authority_state=authority_state,
        )
        return decision, row, before

    def _maintenance_row(
        self,
        event: str,
        *,
        before: dict[str, str],
        timestamp_ticks: int,
        reason: str,
        observation: AdaptiveHybridObservation | None = None,
        decision: AdaptiveHybridDecision | None = None,
        hybrid: dict[str, str] | None = None,
        transaction: dict[str, str] | None = None,
        burst_ordinal: int = 1,
        burst_count: int = 1,
        current_code: int | None = None,
        current_epoch: int | None = None,
    ) -> dict[str, str]:
        self.maintenance_sequence += 1
        self.burst_sequence += 1
        row = {field: "0" for field in ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS}
        row.update(
            {
                "record_type": "AHM",
                "schema_version": "1",
                "maintenance_record_sequence": str(self.maintenance_sequence),
                "event": event,
                "event_timestamp_ticks": str(timestamp_ticks),
                "time_domain": "rp2040_monotonic_us64",
                "run_identity": self.programme.runtime_run_identity,
                "build_identity": str(self.bundle["firmware"]["build_identity"]),
                "image_identity": self.programme.profile_id,
                "policy_id": self.programme.policy_id,
                "active_policy_sha256": self.policy.policy_sha256,
                "capture_session": "0",
                "frequency_estimator_sha256": self.bindings["frequency_estimator"]["sha256"],
                "phase_epoch": "0",
                "phase_valid": "false",
                "current_applied_code": str(
                    self.controller.applied_code if current_code is None else current_code
                ),
                "current_dac_epoch": str(
                    self.controller.dac_epoch if current_epoch is None else current_epoch
                ),
                "transaction_event": "none",
                "maintenance_state_before": before["maintenance_state_before"],
                "maintenance_state_after": self._controller_state(),
                "frontier_relation": (
                    before["frontier_relation_before"]
                    if event == "decision"
                    else "not_applicable"
                ),
                "interval_sign": (
                    before.get("interval_sign_before", "0")
                    if observation is not None
                    else "0"
                ),
                "committed_fll_debt_before_picocodes": before[
                    "committed_fll_debt_before_picocodes"
                ],
                "committed_pll_debt_before_picocodes": before[
                    "committed_pll_debt_before_picocodes"
                ],
                "committed_fll_debt_after_picocodes": str(
                    self.controller.debt.fll_picocodes
                ),
                "committed_pll_debt_after_picocodes": str(
                    self.controller.debt.pll_picocodes
                ),
                "request_pending_before": before["request_pending_before"],
                "request_pending_after": str(self.controller.request_pending).lower(),
                "response_pending_before": before["response_pending_before"],
                "response_pending_after": str(self.controller.response_pending).lower(),
                "metadata_hold_before": before["metadata_hold_before"],
                "metadata_hold_after": str(self.controller.metadata_hold).lower(),
                "persistence_count_before": before["persistence_count_before"],
                "persistence_count_after": str(self.controller.persistence_count),
                "requalification_window_count_before": before[
                    "requalification_window_count_before"
                ],
                "requalification_window_count_after": str(
                    self.controller.requalification_window_count
                ),
                "requalification_d14_d8_observation_sequence": (
                    str(self.controller.requalification_frontier)
                    if event == "gnss_metadata_requalified"
                    and self.controller.requalification_frontier is not None
                    else "0"
                ),
                "evidence_burst_sequence": str(self.burst_sequence),
                "evidence_burst_record_ordinal": str(burst_ordinal),
                "evidence_burst_record_count": str(burst_count),
                "reason": reason,
                "actionable": "false",
                "downstream_epoch_exact": "false",
                "requested_code": str(
                    self.controller.applied_code if current_code is None else current_code
                ),
            }
        )
        if observation is not None:
            row.update(
                {
                    "capture_session": str(observation.capture_session),
                    "source_first_sequence": str(observation.source_first_sequence),
                    "source_last_sequence": str(observation.source_last_sequence),
                    "phase_epoch": str(observation.phase_epoch),
                    "phase_observation_sequence": str(observation.source_last_sequence),
                    "phase_valid": str(observation.phase_valid).lower(),
                }
            )
        if hybrid is not None:
            for key in (
                "hybrid_record_sequence",
                "decision_sequence",
                "source_first_sequence",
                "source_last_sequence",
            ):
                row[key] = hybrid[key]
        if decision is not None:
            row.update(
                {
                    "decision_sequence": str(decision.decision_sequence),
                    "raw_fll_demand_picocodes": str(decision.raw_fll_picocodes),
                    "raw_pll_demand_picocodes": str(decision.raw_pll_picocodes),
                    "candidate_total_demand_picocodes": str(
                        decision.raw_combined_picocodes
                        + decision.committed_debt_picocodes
                    ),
                    "safe_cap_codes": str(decision.safe_cap_codes),
                    "requested_delta_codes": str(decision.requested_delta_codes),
                    "requested_code": str(decision.requested_code),
                }
            )
        if transaction is not None:
            row.update(
                {
                    "transaction_record_sequence": transaction[
                        "transaction_record_sequence"
                    ],
                    "transaction_event": transaction["event"],
                    "request_sequence": transaction["request_sequence"],
                    "application_sequence": transaction["application_sequence"],
                }
            )
            if transaction["event"] in {"application", "response"}:
                row.update(
                    {
                        "actual_applied_code": transaction["applied_code"],
                        "actual_dac_epoch": transaction["dac_epoch"],
                        "downstream_epoch_exact": "true",
                    }
                )
        return row

    def _transaction_rows(
        self,
        *,
        decision: AdaptiveHybridDecision,
        observation: AdaptiveHybridObservation,
        first_record: int,
        request_sequence: int,
        application_sequence: int,
        response_timestamp_s: int,
    ) -> tuple[dict[str, str], ...]:
        cumulative = self.controller.cumulative_movement_codes + abs(
            decision.requested_delta_codes
        )
        dac_epoch = self.controller.dac_epoch + 1
        frequency_error = -observation.accumulated_edge_error_counts / 600.0
        observed_response = decision.requested_delta_codes * 0.00017008467693813145
        post_error = frequency_error + observed_response
        common = {
            "record_type": "ACT",
            "schema_version": "2",
            "time_domain": "rp2040_monotonic_us64",
            "run_identity": self.programme.runtime_run_identity,
            "build_identity": str(self.bundle["firmware"]["build_identity"]),
            "image_identity": self.programme.profile_id,
            "session_id": "1",
            "authorization_sequence": str(request_sequence),
            "nonce": str(7_000_000 + request_sequence),
            "request_sequence": str(request_sequence),
            "decision_sequence": str(decision.decision_sequence),
            "source_first_sequence": str(observation.source_first_sequence),
            "source_last_sequence": str(observation.source_last_sequence),
            "decision_timestamp_s": str(observation.timestamp_s),
            "current_applied_code": str(observation.applied_code),
            "requested_delta_codes": str(decision.requested_delta_codes),
            "requested_code": str(decision.requested_code),
            "correction_ordinal": str(application_sequence),
            "cumulative_after_codes": str(cumulative),
            "pre_error_hz": f"{frequency_error:.12f}",
            "consecutive_indeterminate": "0",
            "estimator_sha256": self.bindings["frequency_estimator"]["sha256"],
            "model_sha256": self.bindings["plant_model"]["sha256"],
            "active_policy_sha256": self.policy.policy_sha256,
            "response_policy_sha256": self.bindings["response_classification"]["sha256"],
            "numerical_policy_sha256": self.policy.policy_sha256,
            "actionable": "false",
        }
        phases = (
            {
                "event": "request_created",
                "event_timestamp_ticks": str(observation.timestamp_ticks),
                "accepted_code": "0",
                "accepted_timestamp_s": "0",
                "applied_code": "0",
                "application_sequence": "0",
                "application_timestamp_s": "0",
                "i2c_ok": "false",
                "clamped": "false",
                "ambiguous": "false",
                "dac_epoch": str(observation.dac_epoch),
                "estimator_history_reset": "false",
                "correction_count": str(application_sequence - 1),
                "cumulative_movement_codes": str(
                    cumulative - abs(decision.requested_delta_codes)
                ),
                "post_error_hz": "0.000000000000",
                "observed_response_hz": "0.000000000000",
                "cumulative_response_hz": "0.000000000000",
                "active_state": "REQUEST_PENDING",
                "response_class": "unavailable",
                "reason": "one_combined_request_created",
                "evidence_state": "request_pending",
            },
            {
                "event": "request_accepted",
                "event_timestamp_ticks": str(observation.timestamp_ticks + RP2040_US),
                "accepted_code": str(decision.requested_code),
                "accepted_timestamp_s": str(observation.timestamp_s + 1),
                "applied_code": "0",
                "application_sequence": "0",
                "application_timestamp_s": "0",
                "i2c_ok": "false",
                "clamped": "false",
                "ambiguous": "false",
                "dac_epoch": str(observation.dac_epoch),
                "estimator_history_reset": "false",
                "correction_count": str(application_sequence - 1),
                "cumulative_movement_codes": str(
                    cumulative - abs(decision.requested_delta_codes)
                ),
                "post_error_hz": "0.000000000000",
                "observed_response_hz": "0.000000000000",
                "cumulative_response_hz": "0.000000000000",
                "active_state": "ACCEPTED_AWAITING_APPLICATION",
                "response_class": "unavailable",
                "reason": "request_consumed_actionable_cleared",
                "evidence_state": "acceptance_pending",
            },
            {
                "event": "application",
                "event_timestamp_ticks": str(observation.timestamp_ticks + 2 * RP2040_US),
                "accepted_code": str(decision.requested_code),
                "accepted_timestamp_s": str(observation.timestamp_s + 1),
                "applied_code": str(decision.requested_code),
                "application_sequence": str(application_sequence),
                "application_timestamp_s": str(observation.timestamp_s + 2),
                "i2c_ok": "true",
                "clamped": "false",
                "ambiguous": "false",
                "dac_epoch": str(dac_epoch),
                "estimator_history_reset": "true",
                "correction_count": str(application_sequence),
                "cumulative_movement_codes": str(cumulative),
                "post_error_hz": "0.000000000000",
                "observed_response_hz": "0.000000000000",
                "cumulative_response_hz": "0.000000000000",
                "active_state": "AWAITING_RESPONSE",
                "response_class": "unavailable",
                "reason": "applied_history_reset_response_required",
                "evidence_state": "application_pending",
            },
            {
                "event": "response",
                "event_timestamp_ticks": str(response_timestamp_s * RP2040_US),
                "accepted_code": str(decision.requested_code),
                "accepted_timestamp_s": str(observation.timestamp_s + 1),
                "applied_code": str(decision.requested_code),
                "application_sequence": str(application_sequence),
                "application_timestamp_s": str(observation.timestamp_s + 2),
                "i2c_ok": "true",
                "clamped": "false",
                "ambiguous": "false",
                "dac_epoch": str(dac_epoch),
                "estimator_history_reset": "true",
                "correction_count": str(application_sequence),
                "cumulative_movement_codes": str(cumulative),
                "post_error_hz": f"{post_error:.12f}",
                "observed_response_hz": f"{observed_response:.12f}",
                "cumulative_response_hz": f"{observed_response:.12f}",
                "active_state": "DISARMED",
                "response_class": "healthy_indeterminate_near_resolution",
                "reason": "healthy_evidence_below_empirical_detection_floor",
                "evidence_state": "response_pending",
            },
        )
        return tuple(
            {
                **{field: "" for field in ACTIVE_TRANSACTION_V2_FIELDS},
                **common,
                **phase,
                "transaction_record_sequence": str(first_record + offset),
            }
            for offset, phase in enumerate(phases)
        )

    def _transaction(
        self,
        observation: AdaptiveHybridObservation,
        *,
        first_record: int,
        request_sequence: int,
        application_sequence: int,
        response_timestamp_s: int,
        response_source_last: int,
    ) -> TransactionFixture:
        decision, hybrid, before = self._append_decision(observation)
        if decision.requested_delta_codes == 0:
            raise RuntimeError("rehearsal transaction did not request control")
        phases = self._transaction_rows(
            decision=decision,
            observation=observation,
            first_record=first_record,
            request_sequence=request_sequence,
            application_sequence=application_sequence,
            response_timestamp_s=response_timestamp_s,
        )
        request_maintenance = self._maintenance_row(
            "decision",
            before=before,
            timestamp_ticks=observation.timestamp_ticks,
            reason=decision.reason,
            observation=observation,
            decision=decision,
            hybrid=hybrid,
            transaction=phases[0],
            burst_ordinal=5,
            burst_count=5,
            current_code=observation.applied_code,
            current_epoch=observation.dac_epoch,
        )

        application_before = self._snapshot("before")
        self.controller.confirm_application(
            decision,
            applied_code=decision.requested_code,
            dac_epoch=observation.dac_epoch + 1,
            first_consumer_exact=True,
        )
        application_maintenance = self._maintenance_row(
            "application_first_consumer",
            before=application_before,
            timestamp_ticks=int(phases[2]["event_timestamp_ticks"]),
            reason="application_and_first_consumer_committed",
            observation=observation,
            decision=decision,
            hybrid=hybrid,
            transaction=phases[2],
            burst_ordinal=3,
            burst_count=3,
            current_code=observation.applied_code,
            current_epoch=observation.dac_epoch,
        )

        response_observation = self._observation(
            timestamp_s=response_timestamp_s,
            source_first=observation.source_last_sequence,
            source_last=response_source_last,
            counts=observation.accumulated_edge_error_counts,
            phase=observation.relative_phase_cycles,
        )
        response_decision, response_hybrid, response_before = self._append_decision(
            response_observation, authority_state="AWAITING_RESPONSE"
        )
        if response_decision.reason != "response_pending_hold":
            raise RuntimeError("rehearsal response consumer did not remain held")
        response_hybrid.update(
            {
                "request_sequence": str(request_sequence),
                "acceptance_sequence": str(request_sequence),
                "application_sequence": str(application_sequence),
            }
        )
        response_decision_maintenance = self._maintenance_row(
            "decision",
            before=response_before,
            timestamp_ticks=response_observation.timestamp_ticks,
            reason=response_decision.reason,
            observation=response_observation,
            decision=response_decision,
            hybrid=response_hybrid,
            burst_ordinal=3,
            burst_count=3,
            current_code=self.controller.applied_code,
            current_epoch=self.controller.dac_epoch,
        )
        response_before_state = self._snapshot("before")
        self.controller.complete_response(fresh_exact=True)
        response_maintenance = self._maintenance_row(
            "response_complete",
            before=response_before_state,
            timestamp_ticks=int(phases[3]["event_timestamp_ticks"]),
            reason="response_completed",
            observation=observation,
            decision=decision,
            hybrid=hybrid,
            transaction=phases[3],
            burst_ordinal=3,
            burst_count=3,
            current_code=observation.applied_code,
            current_epoch=observation.dac_epoch,
        )
        return TransactionFixture(
            request_decision=hybrid,
            request_maintenance=request_maintenance,
            phases=phases,
            application_maintenance=application_maintenance,
            response_decision=response_hybrid,
            response_decision_maintenance=response_decision_maintenance,
            response_maintenance=response_maintenance,
        )

    def build(self) -> LifecycleFixture:
        setup = self.programme.setup_code
        # Physical setup is sampled at microsecond resolution and is not
        # expected to land exactly on a whole-second boundary.  Keep the
        # fixture shaped like that producer output so the host must validate
        # the declared floor-second projection rather than exact divisibility.
        setup_timestamp_ticks = 1_200 * RP2040_US + 71_551
        manual = {field: "" for field in ACTIVE_TRANSACTION_V2_FIELDS}
        manual.update(
            {
                "record_type": "ACT",
                "schema_version": "2",
                "transaction_record_sequence": "1",
                "event": "manual_start",
                "event_timestamp_ticks": str(setup_timestamp_ticks),
                "time_domain": "rp2040_monotonic_us64",
                "run_identity": self.programme.runtime_run_identity,
                "build_identity": str(self.bundle["firmware"]["build_identity"]),
                "image_identity": self.programme.profile_id,
                "session_id": "1",
                "authorization_sequence": "0",
                "nonce": "0",
                "request_sequence": "0",
                "decision_sequence": "0",
                "source_first_sequence": "0",
                "source_last_sequence": "0",
                "decision_timestamp_s": "1200",
                "current_applied_code": str(setup),
                "requested_delta_codes": "0",
                "requested_code": str(setup),
                "correction_ordinal": "0",
                "cumulative_after_codes": "0",
                "pre_error_hz": "0.000000000000",
                "accepted_code": str(setup),
                "accepted_timestamp_s": "1200",
                "applied_code": str(setup),
                "application_sequence": "0",
                "application_timestamp_s": "1200",
                "i2c_ok": "true",
                "clamped": "false",
                "ambiguous": "false",
                "dac_epoch": "1",
                "estimator_history_reset": "false",
                "correction_count": "0",
                "cumulative_movement_codes": "0",
                "post_error_hz": "0.000000000000",
                "observed_response_hz": "0.000000000000",
                "cumulative_response_hz": "0.000000000000",
                "consecutive_indeterminate": "0",
                "active_state": "DISARMED",
                "response_class": "unavailable",
                "reason": "manual_start_established",
                "estimator_sha256": self.bindings["frequency_estimator"]["sha256"],
                "model_sha256": self.bindings["plant_model"]["sha256"],
                "active_policy_sha256": self.policy.policy_sha256,
                "response_policy_sha256": self.bindings["response_classification"]["sha256"],
                "numerical_policy_sha256": self.policy.policy_sha256,
                "actionable": "false",
                "evidence_state": "evidence_clear",
            }
        )
        inactive = {
            **self._snapshot("before"),
            "maintenance_state_before": "POLICY_INACTIVE",
        }
        self.controller.new_policy_activation()
        activation = self._maintenance_row(
            "policy_activation",
            before=inactive,
            timestamp_ticks=setup_timestamp_ticks,
            reason="new_policy_activation",
            current_code=setup,
            current_epoch=1,
        )

        first = self._transaction(
            self._observation(
                timestamp_s=1800,
                source_first=1200,
                source_last=1800,
                counts=-1,
                phase=-6,
            ),
            first_record=2,
            request_sequence=1,
            application_sequence=1,
            response_timestamp_s=3300,
            response_source_last=2400,
        )

        hold_origin = self._observation(
            timestamp_s=3300,
            source_first=1800,
            source_last=2400,
            counts=-1,
            phase=-6,
        )
        hold_before = self._snapshot("before")
        self.controller.enter_metadata_hold()
        metadata_hold = self._maintenance_row(
            "gnss_metadata_hold_enter",
            before=hold_before,
            timestamp_ticks=3_301 * RP2040_US,
            reason="recoverable_gnss_metadata_anomaly",
            observation=hold_origin,
            hybrid=first.response_decision,
        )
        requalified_before = self._snapshot("before")
        self.controller.requalify_metadata(2400)
        metadata_requalified = self._maintenance_row(
            "gnss_metadata_requalified",
            before=requalified_before,
            timestamp_ticks=3_302 * RP2040_US,
            reason="fresh_same_receiver_metadata",
            observation=hold_origin,
            hybrid=first.response_decision,
        )

        first_requalification_observation = self._observation(
            timestamp_s=3900,
            source_first=2400,
            source_last=3000,
            counts=0,
            phase=0,
        )
        first_rq, first_rq_hybrid, first_rq_before = self._append_decision(
            first_requalification_observation, authority_state="REFERENCE_HOLD"
        )
        first_rq_maintenance = self._maintenance_row(
            "decision",
            before=first_rq_before,
            timestamp_ticks=first_requalification_observation.timestamp_ticks,
            reason=first_rq.reason,
            observation=first_requalification_observation,
            decision=first_rq,
            hybrid=first_rq_hybrid,
            burst_ordinal=2,
            burst_count=2,
        )

        second_requalification_observation = self._observation(
            timestamp_s=4500,
            source_first=3000,
            source_last=3600,
            counts=0,
            phase=0,
        )
        second_rq, second_rq_hybrid, second_rq_before = self._append_decision(
            second_requalification_observation, authority_state="REFERENCE_HOLD"
        )
        second_rq_maintenance = self._maintenance_row(
            "decision",
            before=second_rq_before,
            timestamp_ticks=second_requalification_observation.timestamp_ticks,
            reason=second_rq.reason,
            observation=second_requalification_observation,
            decision=second_rq,
            hybrid=second_rq_hybrid,
            burst_ordinal=2,
            burst_count=2,
        )
        if self.controller.metadata_hold:
            raise RuntimeError("rehearsal metadata hold did not causally clear")

        second = self._transaction(
            self._observation(
                timestamp_s=5100,
                source_first=3600,
                source_last=4200,
                counts=1,
                phase=6,
            ),
            first_record=6,
            request_sequence=2,
            application_sequence=2,
            response_timestamp_s=6600,
            response_source_last=4800,
        )
        return LifecycleFixture(
            manual_start=manual,
            policy_activation=activation,
            first_transaction=first,
            metadata_hold=metadata_hold,
            metadata_requalified=metadata_requalified,
            first_requalification_decision=first_rq_hybrid,
            first_requalification_maintenance=first_rq_maintenance,
            second_requalification_decision=second_rq_hybrid,
            second_requalification_maintenance=second_rq_maintenance,
            second_transaction=second,
        )


def build_lifecycle_fixture(bundle: dict[str, Any]) -> LifecycleFixture:
    """Return the deterministic current record choreography."""

    return _LifecycleBuilder(bundle).build()


class DeterministicPtyInstrument:
    """Small firmware-shaped peer for the real capture/supervisor topology.

    This is intentionally not a firmware simulator.  It supplies deterministic
    records at each host protocol boundary so the host's process, FIFO,
    durability, replay, and ordering claims can be tested without physical I/O.
    """

    def __init__(self, master_fd: int, bundle: dict[str, Any]) -> None:
        self.master_fd = master_fd
        self.bundle = bundle
        self.programme = ADAPTIVE_HYBRID_PROGRAMME
        self.fixture = build_lifecycle_fixture(bundle)
        self.identities = {
            "run_identity": self.programme.runtime_run_identity,
            "build_identity": str(bundle["firmware"]["build_identity"]),
            "image_identity": self.programme.profile_id,
            "estimator_sha256": authoritative_binding(
                bundle["authoritative_inputs"],
                authoritative_document(
                    bundle["authoritative_inputs"], ROOT_PROFILE
                )["bindings"]["frequency_estimator"],
            )["sha256"],
            "model_sha256": authoritative_binding(
                bundle["authoritative_inputs"],
                authoritative_document(
                    bundle["authoritative_inputs"], ROOT_PROFILE
                )["bindings"]["plant_model"],
            )["sha256"],
            "active_policy_sha256": bundle["policy"]["policy_sha256"],
            "response_policy_sha256": authoritative_binding(
                bundle["authoritative_inputs"],
                authoritative_document(
                    bundle["authoritative_inputs"], ROOT_PROFILE
                )["bindings"]["response_classification"],
            )["sha256"],
            "numerical_policy_sha256": bundle["policy"]["policy_sha256"],
        }
        self.stop_event = threading.Event()
        self.ready_for_obstruction = threading.Event()
        self.abort_observed = threading.Event()
        self.error: BaseException | None = None
        self.commands: list[str] = []
        self.generation = 0
        self.status_sequence = 0
        self.query_nonce = 1
        self.setup = False
        self.selected_interval_count = 0
        self.transaction_index = 0
        self.evidence_phase = "evidence_clear"
        self.metadata_state = "normal"
        self.first_checkpoint = False
        self._lock = threading.Lock()
        self._timers: list[threading.Timer] = []

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._run, name="otis-pty-instrument")
        thread.start()
        return thread

    def stop(self) -> None:
        self.stop_event.set()
        for timer in self._timers:
            timer.cancel()

    def _later(self, delay_s: float, callback: Callable[[], None]) -> None:
        timer = threading.Timer(delay_s, callback)
        timer.daemon = True
        self._timers.append(timer)
        timer.start()

    def _emit_rows(self, fields: list[str], rows: Iterable[dict[str, str]]) -> None:
        with self._lock:
            for row in rows:
                _write_all_fd(self.master_fd, _wire_row(fields, row))

    def _emit_nonactive_health(self) -> None:
        self._emit_provenance_health()
        prewrite = canonical_prewrite_fixture(
            expected_identity=self.identities,
            planned_live_stimulus_code=self.programme.setup_code,
        )
        health = {
            **GNSS_PREWRITE_EXACT,
            **HEALTH_INTEGRITY_EXACT,
            **FORWARDED_OUTPUT_INTEGRATION_EXPECTED_HEALTH,
            **{
                key: value
                for key, value in prewrite.items()
                if key[0] == "dac"
            },
            ("forwarded_clock_output", "first_valid_ticks"): "1000000",
            ("forwarded_clock_monitor", "state"): "diagnostic_only",
            ("forwarded_clock_monitor", "configured"): "true",
            ("forwarded_clock_monitor", "running"): "true",
            ("forwarded_clock_monitor", "session"): "1",
            ("forwarded_clock_monitor", "snapshot_count"): "1",
            ("forwarded_clock_monitor", "no_snapshot_count"): "0",
            ("forwarded_clock_monitor", "fifo_backlog_count"): "0",
            ("forwarded_clock_monitor", "pio_rxstall_count"): "0",
            ("forwarded_clock_monitor", "fault_flags"): "0",
        }
        self._emit_health_map(health)

    def _emit_provenance_health(self) -> None:
        firmware = self.bundle["firmware"]
        if firmware.get("build_provenance_required") is not True:
            return
        binding = firmware.get("build_manifest", {})
        build = _read_object(
            Path(str(binding.get("path", ""))).resolve(),
            "frozen firmware build manifest",
        )
        provenance = build["provenance"]
        source = provenance["source"]
        configuration = provenance["configuration"]
        target = provenance["target"]
        toolchain = provenance["toolchain"]
        invocation = provenance["invocation"]
        items = [
            (("build", "provenance_format"), "otis_fixed_firmware_build_v1"),
            (("firmware", "git_commit"), str(source["git_commit"])),
            (("firmware", "source_state"), str(source["state"])),
            (("firmware", "source_hash"), str(source["sha256"])),
            (("firmware", "config_hash"), str(configuration["sha256"])),
            (("system", "board"), str(target["board_id"])),
            (("system", "board_name"), str(target["board_name"])),
            (("system", "fqbn"), str(target["fqbn"])),
            (("system", "arduino_core_provider"), str(target["core_provider"])),
            (("system", "arduino_core_version"), str(target["core_version"])),
            (("system", "arduino_core_installed_hash"), str(target["core_installed_sha256"])),
            (("build", "image_id"), str(configuration["image_id"])),
            (("build", "toolchain"), f"{toolchain['name']}@{toolchain['version']}"),
            (("build", "compiler"), str(toolchain["compiler_identity"])),
            (("build", "toolchain_installed_hash"), str(toolchain["installed_sha256"])),
            (("build", "arduino_cli_version"), str(invocation["arduino_cli_version"])),
            (("build", "invocation_id"), str(invocation["id"])),
        ]
        self._emit_health_items(items)

    def _active_health(self) -> dict[tuple[str, str], str]:
        health = canonical_prewrite_fixture(
            expected_identity=self.identities,
            planned_live_stimulus_code=self.programme.setup_code,
        )
        active = {
            key: value
            for (component, key), value in health.items()
            if component == "adaptive_hybrid"
        }
        active.update(
            {
                "query_nonce": str(self.query_nonce),
                "gnss_metadata_hold_active": "false",
                "gnss_metadata_hold_transaction_pending": "false",
                "gnss_metadata_hold_entry_sequence": "0",
                "gnss_metadata_requalification_sequence": "0",
                "gnss_metadata_qualification_frontier": "0",
                "d14_d8_observation_sequence": "0",
                "hybrid_state": "SETUP_PENDING",
                "hybrid_reason": "awaiting_exact_setup",
                "first_phase_checkpoint_passed": "false",
                "phase_nonzero_application_count": "0",
                "phase_material_application_count": "0",
                "frequency_only_application_count": "0",
            }
        )
        if self.abort_observed.is_set():
            active["fail_static"] = "true"
            active["arm_eligible"] = "false"
        if self.setup:
            applied_count = self._applied_transaction_count()
            active.update(
                {
                    "manual_start_confirmed": "true",
                    "confirmed_applied_code_known": "true",
                    "confirmed_applied_code": str(self._applied_code()),
                    "dac_epoch": str(1 + applied_count),
                    "correction_count": str(applied_count),
                    "cumulative_movement_codes": str(6 * applied_count),
                    "selected_interval_count": str(self.selected_interval_count),
                    "state": self._active_state(),
                    "reason": self._active_reason(),
                    "hybrid_state": self._hybrid_state(),
                    "hybrid_reason": "deterministic_rehearsal_fixture",
                    "evidence_pending": str(
                        self.evidence_phase != "evidence_clear"
                    ).lower(),
                    "evidence_phase": self.evidence_phase,
                    "evidence_request_sequence": str(
                        self.transaction_index
                        if self.evidence_phase != "evidence_clear"
                        else 0
                    ),
                    "arm_eligible": str(
                        self.metadata_state in {"normal", "requalified"}
                        and self.evidence_phase == "evidence_clear"
                        and self.selected_interval_count >= 520
                        and self.transaction_index < 2
                    ).lower(),
                    "setup_gnss_eligible": str(
                        self.metadata_state != "hold"
                    ).lower(),
                    "gnss_metadata_hold_active": str(
                        self.metadata_state == "hold"
                    ).lower(),
                    "gnss_metadata_hold_transaction_pending": "false",
                    "gnss_metadata_hold_entry_sequence": (
                        "1" if self.metadata_state in {"hold", "requalified"} else "0"
                    ),
                    "gnss_metadata_requalification_sequence": (
                        "2" if self.metadata_state == "requalified" else "0"
                    ),
                    "gnss_metadata_qualification_frontier": (
                        "2400" if self.metadata_state == "requalified" else "0"
                    ),
                    "d14_d8_observation_sequence": (
                        "3600" if self.metadata_state == "requalified" else "2400"
                    ),
                    "first_phase_checkpoint_passed": str(
                        self.first_checkpoint
                    ).lower(),
                    "phase_nonzero_application_count": str(applied_count),
                    "phase_material_application_count": str(applied_count),
                    "frequency_only_application_count": "0",
                    "uptime_s": str(1200 + 2100 * self.transaction_index),
                }
            )
            health[("dac", "applied_code_known")] = "true"
            health[("dac", "last_write_ok")] = "true"
            health[("dac", "last_applied_code")] = str(self._applied_code())
        return {
            **{
                key: value
                for key, value in health.items()
                if key[0] != "adaptive_hybrid"
            },
            **{("adaptive_hybrid", key): value for key, value in active.items()},
        }

    def _applied_transaction_count(self) -> int:
        if self.evidence_phase in {"request_pending", "acceptance_pending"}:
            return max(0, self.transaction_index - 1)
        return self.transaction_index

    def _applied_code(self) -> int:
        applied_count = self._applied_transaction_count()
        if applied_count == 0:
            return self.programme.setup_code
        transaction = (
            self.fixture.first_transaction
            if applied_count == 1
            else self.fixture.second_transaction
        )
        return int(transaction.phases[2]["applied_code"])

    def _active_state(self) -> str:
        if self.abort_observed.is_set():
            return "ABORTED"
        if self.metadata_state == "hold":
            return "GNSS_METADATA_HOLD"
        return "DISARMED" if self.evidence_phase == "evidence_clear" else {
            "request_pending": "REQUEST_PENDING",
            "acceptance_pending": "ACCEPTED_AWAITING_APPLICATION",
            "application_pending": "AWAITING_RESPONSE",
            "response_pending": "DISARMED",
        }[self.evidence_phase]

    def _active_reason(self) -> str:
        if self.abort_observed.is_set():
            return "host_abort"
        if self.metadata_state == "hold":
            return "recoverable_gnss_metadata_anomaly"
        return "deterministic_rehearsal_fixture"

    def _hybrid_state(self) -> str:
        if self.abort_observed.is_set():
            return "FAIL_STATIC"
        if self.evidence_phase != "evidence_clear":
            return "FIRST_PHASE_TRANSACTION"
        if self.transaction_index == 0:
            return "PHASE_QUALIFY"
        return "HYBRID_TRACKING"

    def _emit_health_items(self, health: Iterable[tuple[tuple[str, str], str]]) -> None:
        rows: list[dict[str, str]] = []
        for (component, key), value in health:
            self.status_sequence += 1
            rows.append(
                {
                    "record_type": "STS",
                    "schema_version": "1",
                    "status_seq": str(self.status_sequence),
                    "timestamp_ticks": str(self.status_sequence * 1000),
                    "status_domain": "rp2040_monotonic_us64",
                    "component": component,
                    "status_key": key,
                    "status_value": value,
                    "severity": "INFO",
                    "flags": "0",
                }
            )
        self._emit_rows(CONTRACT_FIELDS["health_v1"], rows)

    def _emit_health_map(self, health: dict[tuple[str, str], str]) -> None:
        self._emit_health_items((key, health[key]) for key in sorted(health))

    def _emit_idle_wakeup(self) -> None:
        # Timer callbacks publish complete record groups from separate threads.
        # Serialize the otherwise empty carrier wake-up with those groups so it
        # can never split a decision-bearing record in the PTY byte stream.
        with self._lock:
            _write_all_fd(self.master_fd, b"\n")

    def _emit_snapshot(self) -> None:
        self.generation += 1
        active = {
            key: value
            for (component, key), value in self._active_health().items()
            if component == "adaptive_hybrid"
        }
        ordered: list[tuple[str, str]] = [
            (SNAPSHOT_BEGIN_KEY, str(self.generation)),
            (SNAPSHOT_CONTRACT_KEY, ACTIVE_STATUS_SNAPSHOT_CONTRACT),
            *((key, active[key]) for key in ACTIVE_STATUS_KEYS),
            (SNAPSHOT_COMPLETE_KEY, str(self.generation)),
        ]
        self._emit_health_items(
            (("adaptive_hybrid", key), value) for key, value in ordered
        )

    def _emit_initial_observations(self) -> None:
        self._emit_rows(
            CONTRACT_FIELDS["raw_events_v1"],
            [
                {
                    "record_type": "EVT",
                    "schema_version": "1",
                    "event_seq": "1",
                    "channel_id": "0",
                    "edge": "R",
                    "timestamp_ticks": "1000000",
                    "capture_domain": "rp2040_monotonic_us64",
                    "flags": "0",
                },
                {
                    "record_type": "REF",
                    "schema_version": "1",
                    "event_seq": "1",
                    "channel_id": "1",
                    "edge": "R",
                    "timestamp_ticks": "1000000",
                    "capture_domain": "rp2040_monotonic_us64",
                    "flags": "0",
                },
            ],
        )
        self._emit_rows(
            CONTRACT_FIELDS["count_observations_v1"],
            [
                {
                    "record_type": "CNT",
                    "schema_version": "1",
                    "count_seq": "1",
                    "channel_id": "2",
                    "gate_open_ticks": "0",
                    "gate_close_ticks": "1000000",
                    "gate_domain": "rp2040_monotonic_us64",
                    "counted_edges": "10000000",
                    "source_edge": "R",
                    "source_domain": "h1_adaptive_hybrid_ocxo_10mhz",
                    "flags": "0",
                }
            ],
        )
        self._emit_rows(
            CONTRACT_FIELDS["pps_snapshots_v1"],
            [
                {
                    "record_type": "SNP",
                    "schema_version": "1",
                    "session": "1",
                    "snapshot_sequence": "1",
                    "cumulative_down_counter": "4294967295",
                    "reference_sequence": "1",
                    "reference_timestamp_ticks": "1000000",
                    "status": "0",
                    "backend": "pio_wait_cumulative_snapshot_dma_v1",
                }
            ],
        )

    def _emit_transaction(self, transaction: TransactionFixture) -> None:
        self._emit_rows(
            ACTIVE_HYBRID_DECISION_V2_FIELDS,
            [transaction.request_decision, transaction.response_decision],
        )
        self._emit_rows(ACTIVE_TRANSACTION_V2_FIELDS, transaction.phases)
        self._emit_rows(
            ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS,
            [
                transaction.request_maintenance,
                transaction.application_maintenance,
                transaction.response_decision_maintenance,
                transaction.response_maintenance,
            ],
        )

    def _enter_hold(self) -> None:
        if self.stop_event.is_set() or self.transaction_index != 1:
            return
        self.metadata_state = "hold"
        self._emit_rows(
            ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS, [self.fixture.metadata_hold]
        )
        self._emit_snapshot()
        # Retain the anomaly state long enough for the real supervisor loop to
        # consume it before publishing the causally later qualification.
        self._later(2.5, self._requalify)

    def _requalify(self) -> None:
        if self.stop_event.is_set():
            return
        self.metadata_state = "requalified"
        self.selected_interval_count = 0
        self._emit_rows(
            ACTIVE_HYBRID_DECISION_V2_FIELDS,
            [
                self.fixture.first_requalification_decision,
                self.fixture.second_requalification_decision,
            ],
        )
        self._emit_rows(
            ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS,
            [
                self.fixture.metadata_requalified,
                self.fixture.first_requalification_maintenance,
                self.fixture.second_requalification_maintenance,
            ],
        )
        self._emit_snapshot()
        # Keep this complete low-progress generation visible across at least
        # one genuine supervisor polling cycle.  Advancing immediately to 600
        # would let the live-health reducer replace the reset generation before
        # the supervisor can latch the fresh arm-progress epoch.
        self._later(2.5, self._make_armable)

    def _make_armable(self) -> None:
        if self.stop_event.is_set():
            return
        self.selected_interval_count = 600
        self._emit_snapshot()

    def _handle_command(self, command: str) -> None:
        self.commands.append(command)
        if command in {"CONFIG?", "DUALCORE?", "DAC?"}:
            self._emit_nonactive_health()
            return
        if command.startswith("ACTIVE LEASE "):
            return
        if command.startswith("ACTIVE SNAPSHOT "):
            self.query_nonce = int(command.rsplit(" ", 1)[1])
            self._emit_snapshot()
            if self.transaction_index == 2 and self.evidence_phase == "evidence_clear":
                self.ready_for_obstruction.set()
            return
        if command.startswith("ACTIVE SETUP "):
            if self.setup:
                raise RuntimeError("deterministic fixture received duplicate setup")
            self.setup = True
            self.selected_interval_count = 0
            self._emit_rows(
                ACTIVE_TRANSACTION_V2_FIELDS, [self.fixture.manual_start]
            )
            self._emit_rows(
                ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS,
                [self.fixture.policy_activation],
            )
            self._emit_snapshot()
            # The real supervisor must first consume this low-progress setup
            # generation before the same epoch becomes armable at 600.
            self._later(2.5, self._make_armable)
            return
        if command.startswith("ACTIVE ARM "):
            if self.evidence_phase != "evidence_clear" or self.transaction_index >= 2:
                raise RuntimeError("deterministic fixture received impossible arm")
            self.transaction_index += 1
            self.selected_interval_count = 0
            self.first_checkpoint = False
            self.evidence_phase = "request_pending"
            transaction = (
                self.fixture.first_transaction
                if self.transaction_index == 1
                else self.fixture.second_transaction
            )
            self._emit_transaction(transaction)
            self._emit_snapshot()
            return
        if command.startswith("ACTIVE EVIDENCE "):
            fields = command.split()
            request, phase = int(fields[2]), int(fields[3])
            if request != self.transaction_index:
                raise RuntimeError("deterministic evidence request identity changed")
            expected = {
                1: "request_pending",
                2: "acceptance_pending",
                3: "application_pending",
                4: "response_pending",
            }[phase]
            if self.evidence_phase != expected:
                raise RuntimeError("deterministic evidence phase order changed")
            self.evidence_phase = {
                1: "acceptance_pending",
                2: "application_pending",
                3: "response_pending",
                4: "evidence_clear",
            }[phase]
            if phase == 4:
                self.first_checkpoint = True
            self._emit_snapshot()
            if phase == 4 and self.transaction_index == 1:
                self._later(0.5, self._enter_hold)
            return
        if command == "ACTIVE ABORT":
            self.abort_observed.set()
            self._emit_snapshot()
            return
        if command == "ACTIVE?":
            self._emit_snapshot()
            return
        raise RuntimeError(f"unhandled deterministic instrument command: {command}")

    def _run(self) -> None:
        buffer = bytearray()
        try:
            self._emit_initial_observations()
            while not self.stop_event.is_set():
                readable, _, _ = select.select([self.master_fd], [], [], 0.05)
                if not readable:
                    # Wake the genuine capture reader so it services FIFO
                    # ingress promptly; an empty line is not a device record.
                    self._emit_idle_wakeup()
                    continue
                try:
                    chunk = os.read(self.master_fd, 4096)
                except OSError as exc:
                    if exc.errno == 5 and not self.stop_event.is_set():
                        time.sleep(0.02)
                        continue
                    raise
                if not chunk:
                    continue
                buffer.extend(chunk)
                while b"\n" in buffer:
                    raw, _, remainder = buffer.partition(b"\n")
                    buffer[:] = remainder
                    command = raw.rstrip(b"\r").decode("ascii").strip()
                    if command:
                        self._handle_command(command)
        except BaseException as exc:
            self.error = exc
            self.stop_event.set()


def _supervisor_worker(manifest_path: Path, run_dir: Path) -> int:
    """Run the live supervisor only behind the private PTY validator."""

    manifest_path = manifest_path.resolve()
    run_dir = run_dir.resolve()
    if manifest_path != run_dir / "run_manifest.json":
        raise ValueError("rehearsal supervisor manifest is outside its run")
    private = _read_object(manifest_path, "rehearsal run manifest")
    bundle_path = Path(str(private.get("bundle", {}).get("path", ""))).resolve()
    proposal_path = Path(str(private.get("proposal", {}).get("path", ""))).resolve()
    bundle = _read_object(bundle_path, "rehearsal bundle")
    proposal = _read_object(proposal_path, "rehearsal proposal")
    for value, field, label in (
        (bundle, "bundle_sha256", "bundle"),
        (proposal, "proposal_sha256", "proposal"),
    ):
        claimed = value.get(field)
        unsigned = {key: item for key, item in value.items() if key != field}
        if claimed != _canonical_sha256(unsigned):
            raise ValueError(f"rehearsal worker {label} semantic hash differs")
    private = _validate_manifest_value(
        manifest_path.resolve(), private, bundle=bundle, proposal=proposal
    )
    supervisor = create_validated_nonphysical_rehearsal_supervisor(
        validated_manifest=private,
        manifest_path=manifest_path,
        run_dir=run_dir,
        command_fifo=run_dir / private["host"]["fifos"]["normal_command"],
        emergency_command_fifo=(
            run_dir / private["host"]["fifos"]["emergency_abort"]
        ),
        abort_fifo=run_dir / private["host"]["fifos"]["host_abort"],
        expected_build_identity=str(private["firmware"]["build_identity"]),
        duration_s=120.0,
        console_events=False,
    )
    return supervisor.run()


def _monitor_worker(
    run_dir: Path, manifest_path: Path, stop_path: Path
) -> int:
    """Retain bounded, read-only samples from the current monitor validators."""

    run_dir = run_dir.resolve()
    manifest_path = manifest_path.resolve()
    if manifest_path != run_dir / "run_manifest.json":
        raise ValueError("rehearsal monitor manifest is outside its run")
    private = _read_object(manifest_path, "rehearsal monitor manifest")
    if private.get("stage") != REHEARSAL_STAGE:
        raise ValueError("rehearsal monitor requires the private PTY stage")
    programme = programme_from_mapping(private)
    expected_build_identity = str(private.get("firmware", {}).get("build_identity", ""))
    if not expected_build_identity:
        raise ValueError("rehearsal monitor build identity is unavailable")
    while not stop_path.exists():
        now = time.time()
        try:
            lifecycle = _exact_lifecycle_record_progress(run_dir, now=now)
            maintenance = _maintenance_evidence_progress(
                run_dir,
                programme=programme,
                expected_build_identity=expected_build_identity,
                now=now,
            )
            supervisor_state = _read_object(
                run_dir / "reports/adaptive_hybrid_supervisor_state.json",
                "rehearsal supervisor state",
            )
            sample = {
                "schema_version": 1,
                "sampled_utc": _utc_now(),
                "capture_state": (
                    _read_object(
                        run_dir / CAPTURE_STATE, "rehearsal capture state"
                    )
                    if (run_dir / CAPTURE_STATE).is_file()
                    else None
                ),
                "supervisor": {
                    "manual_start_sent": supervisor_state.get(
                        "manual_start_sent"
                    ),
                    "setup_confirmed": bool(
                        supervisor_state.get("setup_confirmed_utc")
                    ),
                    "acknowledged_record_sequences": supervisor_state.get(
                        "acknowledged_record_sequences"
                    ),
                    "later_authority_released": supervisor_state.get(
                        "later_authority_released"
                    ),
                    "gnss_metadata_hold_count": supervisor_state.get(
                        "gnss_metadata_hold_count"
                    ),
                    "terminal": supervisor_state.get("terminal"),
                },
                "lifecycle": lifecycle,
                "maintenance": maintenance,
            }
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            sample = {
                "schema_version": 1,
                "sampled_utc": _utc_now(),
                "pending": True,
                "diagnostic": str(exc),
            }
        _append_jsonl(run_dir / MONITOR_SAMPLES_PATH, sample)
        time.sleep(0.1)
    return 0


def _transition_manifest(*, target: Path, device: str) -> Path:
    value = {
        "schema_version": 1,
        "template": False,
        "run_id": target.name,
        "created_utc": _utc_now(),
        "stage": SEGMENT_TRANSITION_STAGE,
        "mode": "same_owner_no_authority_drainage",
        "actionable": False,
        "actuation_authorized": False,
        "host": {"serial_device": device, "baud": 115200},
        "channels": _channels(),
        "files": [
            {
                "path": "csv/health.csv",
                "contract": "health_v1",
                "optional": True,
            }
        ],
    }
    path = target / "run_manifest.json"
    _atomic_json(path, value, exclusive=True)
    return path


def _fill_fifo_to_obstruction(path: Path) -> dict[str, Any]:
    descriptor = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
    writes = 0
    bytes_written = 0
    obstructed = False
    try:
        while writes < 1_000_000:
            line = (
                f"OTISQ1 {time.monotonic_ns()} ACTIVE SNAPSHOT "
                f"{1 + writes % 4_000_000_000}\n"
            ).encode("ascii")
            try:
                written = os.write(descriptor, line)
            except BlockingIOError:
                obstructed = True
                break
            writes += 1
            bytes_written += written
    finally:
        os.close(descriptor)
    if not obstructed:
        raise RuntimeError("normal command FIFO did not reach bounded obstruction")
    return {
        "method": "capture_process_sigstop_then_nonblocking_fifo_fill",
        "fifo": str(path),
        "successful_writes": writes,
        "bytes_written_before_eagain": bytes_written,
        "write_obstruction_errno": errno.EAGAIN,
        "bounded": True,
    }


def _rotate_to_transition(
    *, run_dir: Path, transition_dir: Path, capture_pid: int, device: str
) -> dict[str, Any]:
    transition_dir.mkdir(parents=True, exist_ok=False)
    transition_manifest = _transition_manifest(target=transition_dir, device=device)
    carrier_path = run_dir / "carrier" / SEGMENT_CARRIER_STATE
    carrier = _read_object(carrier_path, "segment carrier state")
    request_id = sha256(
        f"{run_dir}:{transition_dir}:{capture_pid}".encode("utf-8")
    ).hexdigest()[:32]
    request = {
        "schema_version": 1,
        "protocol": SEGMENT_PROTOCOL_ID,
        "request_id": request_id,
        "capability": CAPABILITY,
        "expected_pid": capture_pid,
        "expected_generation": int(carrier["transport_generation"]),
        "from_run": str(run_dir),
        "to_run": str(transition_dir),
        "expected_manifest_sha256": _sha256_file(transition_manifest),
        "mode": "transition",
        "command_fifo": None,
        "emergency_command_fifo": None,
    }
    _atomic_json(run_dir / "carrier" / SEGMENT_REQUEST, request, exclusive=True)
    response_path = (
        run_dir / "carrier" / SEGMENT_RESPONSE_DIR / f"{request_id}.json"
    )
    _wait_until(
        lambda: response_path.is_file(), 10.0, "same-owner segment response"
    )
    response = _read_object(response_path, "same-owner segment response")
    if response.get("status") != "completed":
        raise RuntimeError("same-owner segment rotation was rejected: " + str(response))
    closure = _read_object(run_dir / SEGMENT_CLOSURE, "source segment closure")
    if not (
        response.get("pid") == capture_pid
        and response.get("serial_reopened") is False
        and closure.get("owner_pid") == capture_pid
        and closure.get("closure_mode") == "same_owner_logical_rotation"
        and closure.get("physical_serial_open") is True
        and closure.get("serial_reopened") is False
    ):
        raise RuntimeError("same-owner segment closure identity differs")
    return {
        "request": request,
        "response": response,
        "source_closure": closure,
        "ownerless_interval": False,
    }


def _process_command(module: str, *arguments: str) -> list[str]:
    return [sys.executable, "-m", module, *arguments]


def _launch(command: list[str], log_path: Path) -> tuple[subprocess.Popen[str], Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("x", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=handle,
        stderr=handle,
        text=True,
        start_new_session=True,
    )
    return process, handle


def _run_process_topology(
    *,
    run_dir: Path,
    manifest_path: Path,
    bundle: dict[str, Any],
    device: str,
    master_fd: int,
    slave_fd: int,
) -> dict[str, Any]:
    capture: subprocess.Popen[str] | None = None
    supervisor: subprocess.Popen[str] | None = None
    monitor: subprocess.Popen[str] | None = None
    handles: list[Any] = []
    emulator: DeterministicPtyInstrument | None = None
    emulator_thread: threading.Thread | None = None
    capture_continued = False
    stop_monitor = run_dir / "control/monitor.stop"
    transition_dir = run_dir / TRANSITION_DIR
    try:
        # The caller created the manifest with this exact slave path.  The
        # parent retains the master solely for deterministic device records.
        if os.path.realpath(os.ttyname(slave_fd)) != device or not _is_pty(device):
            raise RuntimeError("rehearsal device is not this process's exact PTY slave")
        capture, handle = _launch(
            _process_command(
                "host.otis_tools.capture_device",
                "--device",
                device,
                "--run-dir",
                str(run_dir),
                "--duration-s",
                "120",
                "--status-interval",
                "1",
                "--command-fifo",
                str(run_dir / "control/normal_commands.fifo"),
                "--emergency-command-fifo",
                str(run_dir / "control/emergency_abort.fifo"),
                "--write-timeout-s",
                "1",
                "--normal-command-max-age-s",
                "2",
                "--segment-control-dir",
                str(run_dir / "carrier"),
                "--segment-capability",
                CAPABILITY,
            ),
            run_dir / "reports/capture_device.stdout.log",
        )
        handles.append(handle)
        os.close(slave_fd)
        slave_fd = -1
        emulator = DeterministicPtyInstrument(master_fd, bundle)
        emulator_thread = emulator.start()
        _wait_until(
            lambda: (
                capture.poll() is None
                and _capture_state_ready(run_dir, capture.pid)
                and (run_dir / "control/normal_commands.fifo").is_fifo()
                and (run_dir / "control/emergency_abort.fifo").is_fifo()
            ),
            10.0,
            "real capture process and command ingress",
        )
        if _serial_owner_pids(device) != {capture.pid}:
            raise RuntimeError("capture process is not the sole PTY slave owner")

        supervisor, handle = _launch(
            _process_command(
                "host.otis_tools.adaptive_hybrid_operational_rehearsal",
                "_supervisor_worker",
                "--manifest",
                str(manifest_path),
                "--run-dir",
                str(run_dir),
            ),
            run_dir / "reports/adaptive_hybrid_supervisor.stdout.log",
        )
        handles.append(handle)
        monitor, handle = _launch(
            _process_command(
                "host.otis_tools.adaptive_hybrid_operational_rehearsal",
                "_monitor_worker",
                "--run-dir",
                str(run_dir),
                "--manifest",
                str(manifest_path),
                "--stop-path",
                str(stop_monitor),
            ),
            run_dir / "reports/adaptive_hybrid_monitor.stdout.log",
        )
        handles.append(handle)
        _wait_until(
            lambda: (
                supervisor.poll() is None
                and monitor.poll() is None
                and (run_dir / "control/host_abort.fifo").is_fifo()
            ),
            10.0,
            "supervisor, monitor, and independent abort ingress",
        )

        def lifecycle_complete() -> bool:
            if emulator is not None and emulator.error is not None:
                raise RuntimeError(str(emulator.error))
            state = _read_object(
                run_dir / "reports/adaptive_hybrid_supervisor_state.json",
                "supervisor state",
            )
            return bool(
                emulator is not None
                and emulator.ready_for_obstruction.is_set()
                and state.get("acknowledged_record_sequences")
                == list(range(2, 10))
                and state.get("inflight_evidence_acknowledgement") is None
                and state.get("response_count") == 2
                and state.get("later_authority_released") is True
                and state.get("gnss_metadata_hold_count") == 1
                and state.get("gnss_metadata_hold") is None
                and state.get("host_verification_hold") is None
            )

        _wait_until(lifecycle_complete, 90.0, "two exact progressive transactions")
        stale_line = (
            f"OTISQ1 {time.monotonic_ns() - 3_000_000_000} ACTIVE?\n"
        ).encode("ascii")
        stale_fd = os.open(
            run_dir / "control/normal_commands.fifo",
            os.O_WRONLY | os.O_NONBLOCK,
        )
        try:
            os.write(stale_fd, stale_line)
        finally:
            os.close(stale_fd)
        _wait_until(
            lambda: int(
                _read_object(run_dir / CAPTURE_STATE, "capture state").get(
                    "commands_rejected", 0
                )
            )
            == 1,
            5.0,
            "stale normal command rejection",
        )
        os.kill(capture.pid, signal.SIGSTOP)
        obstruction = _fill_fifo_to_obstruction(
            run_dir / "control/normal_commands.fifo"
        )
        abort_started = time.monotonic()
        send_abort(run_dir / "control/host_abort.fifo")
        _wait_until(
            lambda: supervisor.poll() is not None,
            8.0,
            "supervisor priority abort submission",
        )
        supervisor_exit = supervisor.wait(timeout=1.0)
        if supervisor_exit != 3:
            raise RuntimeError(f"supervisor abort exit was {supervisor_exit}, expected 3")
        os.kill(capture.pid, signal.SIGCONT)
        capture_continued = True
        _wait_until(
            lambda: (
                emulator is not None
                and emulator.abort_observed.is_set()
                and int(
                    _read_object(run_dir / CAPTURE_STATE, "capture state").get(
                        "emergency_aborts_sent", 0
                    )
                )
                == 1
            ),
            8.0,
            "priority abort transmission and deterministic consumption",
        )
        abort_elapsed = time.monotonic() - abort_started
        if abort_elapsed > 8.0:
            raise RuntimeError("priority abort delivery exceeded its bounded deadline")

        rotation = _rotate_to_transition(
            run_dir=run_dir,
            transition_dir=transition_dir,
            capture_pid=capture.pid,
            device=device,
        )
        capture.send_signal(signal.SIGTERM)
        capture_exit = capture.wait(timeout=10.0)
        if capture_exit != 0:
            raise RuntimeError(f"capture process exited {capture_exit}")
        transition_closure_path = transition_dir / SEGMENT_CLOSURE
        rotation["transition_closure"] = _read_object(
            transition_closure_path, "transition segment closure"
        )
        rotation["transition_manifest_binding"] = _binding(
            transition_dir / "run_manifest.json"
        )
        rotation["transition_closure_binding"] = _binding(
            transition_closure_path
        )
        if not (
            rotation["transition_closure"].get("owner_pid") == capture.pid
            and rotation["transition_closure"].get("closure_mode")
            == "physical_serial_close"
            and rotation["transition_closure"].get("physical_serial_open") is False
        ):
            raise RuntimeError("transition segment did not close the same owner cleanly")
        stop_monitor.parent.mkdir(parents=True, exist_ok=True)
        stop_monitor.touch()
        monitor_exit = monitor.wait(timeout=5.0)
        if monitor_exit != 0:
            raise RuntimeError(f"monitor worker exited {monitor_exit}")
        emulator.stop()
        emulator_thread.join(timeout=2.0)
        if emulator.error is not None:
            raise RuntimeError(f"deterministic PTY instrument failed: {emulator.error}")
        terminal = _read_object(
            run_dir / "reports/adaptive_hybrid_supervisor_state.json",
            "terminal supervisor state",
        ).get("terminal")
        return {
            "schema_version": 1,
            "tool": TOOL_ID,
            "nonphysical": True,
            "physical_actions_performed": 0,
            "processes": {
                "capture": {"pid": capture.pid, "exit": capture_exit},
                "supervisor": {"pid": supervisor.pid, "exit": supervisor_exit},
                "monitor": {"pid": monitor.pid, "exit": monitor_exit},
            },
            "sole_serial_owner": {
                "device": device,
                "owner_pid": capture.pid,
                "owner_count": 1,
            },
            "normal_transport_obstruction": obstruction,
            "stale_normal_command": {
                "age_s": 3.0,
                "configured_max_age_s": 2.0,
                "capture_rejected_count": 1,
            },
            "priority_abort": {
                "host_abort_submitted": True,
                "supervisor_emergency_submission": True,
                "capture_emergency_transmission_count": 1,
                "instrument_abort_consumed": True,
                "delivery_elapsed_s": abort_elapsed,
                "delivery_before_source_capture_close": True,
            },
            "rotation": rotation,
            "terminal": terminal,
            "commands": list(emulator.commands),
            "D10": {
                "records": 1,
                "role": "optional_external_event_evidence",
                "control_authority": False,
                "terminal_authority": False,
            },
        }
    finally:
        if capture is not None and capture.poll() is None:
            if not capture_continued:
                try:
                    os.kill(capture.pid, signal.SIGCONT)
                except ProcessLookupError:
                    pass
            capture.terminate()
            try:
                capture.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                capture.kill()
                capture.wait(timeout=3.0)
        for process in (supervisor, monitor):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3.0)
        if emulator is not None:
            emulator.stop()
        if emulator_thread is not None:
            emulator_thread.join(timeout=2.0)
        if master_fd >= 0:
            os.close(master_fd)
        if slave_fd >= 0:
            os.close(slave_fd)
        for handle in handles:
            handle.close()


def analyze_and_seal_rehearsal(
    *,
    run_dir: Path,
    manifest_value: dict[str, Any],
    bundle: dict[str, Any],
) -> dict[str, Any]:
    """Recompute every decision-bearing rehearsal claim and write one seal."""

    process_evidence = _read_object(
        run_dir / PROCESS_EVIDENCE_PATH, "rehearsal process evidence"
    )
    manifest = RunManifest(
        run_dir, run_dir / "run_manifest.json", manifest_value
    )
    spec, identities = load_validated_nonphysical_rehearsal_spec(manifest_value)
    policy_document = authoritative_document(
        bundle["authoritative_inputs"], ROOT_PROFILE
    )
    policy_binding = authoritative_binding(
        bundle["authoritative_inputs"], ROOT_PROFILE
    )
    policy = policy_from_mapping(
        policy_document, policy_sha256=str(policy_binding["sha256"])
    )
    shared_consumers = replay_current_adaptive_hybrid_host_consumers(
        manifest,
        spec=spec,
        identities=identities,
        expected_build_identity=str(bundle["firmware"]["build_identity"]),
        expected_active_policy_sha256=policy.policy_sha256,
        policy=policy,
        policy_document=policy_document,
        estimator_sha256=identities["estimator_sha256"],
        response_policy_document=authoritative_document(
            bundle["authoritative_inputs"],
            str(policy_document["bindings"]["response_classification"]),
        ),
        programme=ADAPTIVE_HYBRID_PROGRAMME,
    )
    csv_validation = shared_consumers["csv_validation"]
    shared_replay = shared_consumers["record_replay"]
    replay = shared_replay["maintenance_replay"]
    supervisor = _read_object(
        run_dir / "reports/adaptive_hybrid_supervisor_state.json",
        "rehearsal supervisor state",
    )
    events = [
        json.loads(line)
        for line in (
            run_dir / "reports/adaptive_hybrid_supervisor_events.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    commands = process_evidence["commands"]
    parsed_commands = [parse_serial_command(command).normalized for command in commands]
    if parsed_commands != commands:
        raise ValueError("rehearsal process command transcript is non-canonical")
    phases = [
        tuple(map(int, command.split()[2:4]))
        for command in commands
        if command.startswith("ACTIVE EVIDENCE ")
    ]
    d10_path = run_dir / "csv/external_events.csv"
    try:
        d10_rows = _read_csv(d10_path)
        d10_diagnostic = {
            "present": d10_path.is_file(),
            "rows": len(d10_rows),
            "contract_errors": csv_validation.get(
                "raw_events_v1:EVT", {}
            ).get("errors", []),
        }
    except (OSError, csv.Error, UnicodeError) as exc:
        d10_rows = []
        d10_diagnostic = {
            "present": d10_path.is_file(),
            "rows": 0,
            "contract_errors": [str(exc)],
        }
    raw = (run_dir / "raw/serial.log").read_text(
        encoding="utf-8", errors="replace"
    )
    raw_markers: list[dict[str, Any]] = []
    for line in raw.splitlines():
        prefix = "# OTIS_HOST "
        if not line.startswith(prefix):
            continue
        value = json.loads(line[len(prefix) :])
        if isinstance(value, dict):
            raw_markers.append(value)
    raw_commands = [
        str(marker["command"])
        for marker in raw_markers
        if marker.get("event") == "host_command_sent"
    ]
    raw_events = [str(marker.get("event")) for marker in raw_markers]
    emergency_position = (
        raw_events.index("emergency_abort_sent")
        if "emergency_abort_sent" in raw_events
        else -1
    )
    close_position = (
        raw_events.index("capture_stopped")
        if "capture_stopped" in raw_events
        else -1
    )
    monitor_rows = [
        json.loads(line)
        for line in (run_dir / MONITOR_SAMPLES_PATH)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    source_capture_state = _read_object(
        run_dir / CAPTURE_STATE, "closed source capture state"
    )
    source_closure = _read_object(
        run_dir / SEGMENT_CLOSURE, "source segment closure"
    )
    rotation = process_evidence.get("rotation", {})
    transition_manifest_binding = rotation.get("transition_manifest_binding")
    transition_closure_binding = rotation.get("transition_closure_binding")
    expected_transition_manifest = run_dir / TRANSITION_MANIFEST_PATH
    expected_transition_closure = run_dir / TRANSITION_CLOSURE_PATH
    transition_bindings_exact = (
        _binding_exact(transition_manifest_binding)
        and _binding_exact(transition_closure_binding)
        and isinstance(transition_manifest_binding, dict)
        and isinstance(transition_closure_binding, dict)
        and transition_manifest_binding.get("path")
        == str(expected_transition_manifest.resolve())
        and transition_closure_binding.get("path")
        == str(expected_transition_closure.resolve())
    )
    transition_closure = (
        _read_object(
            Path(str(transition_closure_binding["path"])),
            "transition segment closure",
        )
        if transition_bindings_exact
        else {}
    )
    transition_manifest = (
        _read_object(expected_transition_manifest, "transition segment manifest")
        if transition_bindings_exact
        else {}
    )
    request = rotation.get("request", {})
    request_id = request.get("request_id") if isinstance(request, dict) else None
    retained_response_path = (
        run_dir / "carrier" / SEGMENT_RESPONSE_DIR / f"{request_id}.json"
        if isinstance(request_id, str)
        else run_dir / "carrier/responses/invalid.json"
    )
    retained_response = (
        _read_object(retained_response_path, "retained transition response")
        if retained_response_path.is_file()
        else {}
    )
    transition_capture_state = (
        _read_object(
            run_dir / TRANSITION_CAPTURE_STATE_PATH,
            "closed transition capture state",
        )
        if (run_dir / TRANSITION_CAPTURE_STATE_PATH).is_file()
        else {}
    )
    transition_raw = (
        (run_dir / TRANSITION_RAW_PATH).read_text(
            encoding="utf-8", errors="replace"
        )
        if (run_dir / TRANSITION_RAW_PATH).is_file()
        else ""
    )
    transition_raw_markers = []
    for line in transition_raw.splitlines():
        if line.startswith("# OTIS_HOST "):
            marker = json.loads(line[len("# OTIS_HOST ") :])
            if isinstance(marker, dict):
                transition_raw_markers.append(marker)
    transition_health_header = (
        (run_dir / TRANSITION_HEALTH_PATH)
        .read_text(encoding="utf-8")
        .splitlines()[:1]
        if (run_dir / TRANSITION_HEALTH_PATH).is_file()
        else []
    )
    transition_manifest_exact = (
        set(transition_manifest)
        == {
            "schema_version",
            "template",
            "run_id",
            "created_utc",
            "stage",
            "mode",
            "actionable",
            "actuation_authorized",
            "host",
            "channels",
            "files",
        }
        and transition_manifest.get("schema_version") == 1
        and transition_manifest.get("template") is False
        and transition_manifest.get("run_id") == (run_dir / TRANSITION_DIR).name
        and _explicit_utc(transition_manifest.get("created_utc"))
        and transition_manifest.get("stage") == SEGMENT_TRANSITION_STAGE
        and transition_manifest.get("mode") == "same_owner_no_authority_drainage"
        and transition_manifest.get("actionable") is False
        and transition_manifest.get("actuation_authorized") is False
        and transition_manifest.get("host")
        == {"serial_device": manifest_value["host"]["serial_device"], "baud": 115200}
        and transition_manifest.get("channels") == _channels()
        and transition_manifest.get("files")
        == [
            {
                "path": "csv/health.csv",
                "contract": "health_v1",
                "optional": True,
            }
        ]
    )
    closure_fields = {
        "schema_version",
        "protocol",
        "closed_utc",
        "run",
        "run_manifest_sha256",
        "device",
        "baud",
        "owner_pid",
        "transport_generation",
        "closure_mode",
        "logical_segment_closed",
        "physical_serial_open",
        "serial_reopened",
        "next_run",
        "request_id",
        "serial_owner_check",
        "counters",
    }
    counter_fields = {
        "bytes_written",
        "lines_seen",
        "lines_parsed",
        "malformed_utf8",
        "parser_errors",
        "reconnect_count",
        "commands_sent",
        "commands_rejected",
        "emergency_aborts_sent",
    }
    request_exact = (
        isinstance(request, dict)
        and set(request)
        == {
            "schema_version",
            "protocol",
            "request_id",
            "capability",
            "expected_pid",
            "expected_generation",
            "from_run",
            "to_run",
            "expected_manifest_sha256",
            "mode",
            "command_fifo",
            "emergency_command_fifo",
        }
        and request.get("schema_version") == 1
        and request.get("protocol") == SEGMENT_PROTOCOL_ID
        and isinstance(request_id, str)
        and re.fullmatch(r"[0-9a-f]{32}", request_id) is not None
        and request.get("capability") == CAPABILITY
        and request.get("expected_generation") == 1
        and request.get("mode") == "transition"
        and request.get("command_fifo") is None
        and request.get("emergency_command_fifo") is None
    )
    response_exact = (
        isinstance(retained_response, dict)
        and set(retained_response)
        == {
            "schema_version",
            "request_id",
            "utc",
            "status",
            "pid",
            "from_run",
            "to_run",
            "transport_generation",
            "serial_reopened",
            "reconnect_count",
        }
        and retained_response.get("schema_version") == 1
        and retained_response.get("request_id") == request_id
        and _explicit_utc(retained_response.get("utc"))
        and retained_response.get("status") == "completed"
        and retained_response == rotation.get("response")
    )
    closures_exact = (
        set(source_closure) == closure_fields
        and set(transition_closure) == closure_fields
        and source_closure.get("schema_version") == 1
        and transition_closure.get("schema_version") == 1
        and source_closure.get("protocol") == SEGMENT_PROTOCOL_ID
        and transition_closure.get("protocol") == SEGMENT_PROTOCOL_ID
        and _explicit_utc(source_closure.get("closed_utc"))
        and _explicit_utc(transition_closure.get("closed_utc"))
        and isinstance(source_closure.get("counters"), dict)
        and isinstance(transition_closure.get("counters"), dict)
        and set(source_closure["counters"]) == counter_fields
        and set(transition_closure["counters"]) == counter_fields
        and all(
            type(value) is int and value >= 0
            for value in [
                *source_closure["counters"].values(),
                *transition_closure["counters"].values(),
            ]
        )
    )
    capture_pid = source_closure.get("owner_pid")
    supervisor_events_commands = [
        str(event["command"])
        for event in events
        if event.get("event") == "command_submitted"
    ]
    setup_commands = [
        command for command in raw_commands if command.startswith("ACTIVE SETUP ")
    ]
    arm_commands = [
        command for command in raw_commands if command.startswith("ACTIVE ARM ")
    ]
    authority = _read_object(
        run_dir / "reports/adaptive_hybrid_setup_authority_v1.json",
        "rehearsal setup authority",
    )
    setup_request = authority.get("request", {})
    transactions = _read_csv(run_dir / "csv/active_transactions_v2.csv")
    manual_start = transactions[0] if transactions else {}
    authority_unsigned = {
        key: value for key, value in authority.items() if key != "record_sha256"
    }
    authority_sha256 = _canonical_sha256(authority_unsigned)
    expected_setup_confirmation = {
        "transaction_record_sequence": int(
            manual_start.get("transaction_record_sequence", "-1")
        ),
        "event_timestamp_ticks": int(manual_start.get("event_timestamp_ticks", "-1")),
        "time_domain": manual_start.get("time_domain"),
        "session_id": int(manual_start.get("session_id", "-1")),
        "applied_code": int(manual_start.get("applied_code", "-1")),
        "dac_epoch": int(manual_start.get("dac_epoch", "-1")),
        "setup_authorization_sequence": int(
            setup_request.get("authorization_sequence", -1)
        ),
        "setup_status_generation": int(setup_request.get("status_generation", -1)),
        "setup_query_nonce": int(setup_request.get("query_nonce", -1)),
        "setup_authority_record_sha256": authority_sha256,
    }
    programme_event_prefix = f"{ADAPTIVE_HYBRID_PROGRAMME.key}_"
    setup_confirmation_events = [
        event
        for event in events
        if event.get("event")
        == programme_event_prefix + "setup_first_consumer_confirmed"
    ]
    setup_confirmation_event_exact = (
        len(setup_confirmation_events) == 1
        and _explicit_utc(setup_confirmation_events[0].get("utc"))
        and {
            key: value
            for key, value in setup_confirmation_events[0].items()
            if key not in {"event", "utc"}
        }
        == expected_setup_confirmation
    )
    setup_command_exact = setup_commands == [
        "ACTIVE SETUP "
        f"{setup_request.get('authorization_sequence')} "
        f"{setup_request.get('status_generation')} {setup_request.get('query_nonce')} "
        f"{setup_request.get('expires_s')} {setup_request.get('session_id')} "
        f"0x{int(setup_request.get('requested_code', 0)):04X} "
        f"{setup_request.get('one_shot_ordinal')} {setup_request.get('configuration_identity')}"
    ]
    arm_events = [
        event
        for event in events
        if event.get("event") == programme_event_prefix + "one_decision_armed"
    ]
    arm_command_exact = len(arm_commands) == len(arm_events) == 2
    if arm_command_exact:
        for command, event in zip(arm_commands, arm_events, strict=True):
            fields = command.split()
            arm_command_exact &= (
                int(fields[2]) == int(event["authorization_sequence"])
                and int(fields[4]) == int(event["expiry_s"])
                and int(fields[3]) > 0
            )
    first_checkpoint_event_index = next(
        (
            index
            for index, event in enumerate(events)
            if event.get("event")
            == programme_event_prefix + "firmware_evidence_acknowledgement_confirmed"
            and event.get("request_sequence") == 1
            and event.get("phase") == 4
        ),
        -1,
    )
    second_arm_event_index = next(
        (
            index
            for index, event in enumerate(events)
            if event.get("event") == programme_event_prefix + "one_decision_armed"
            and event.get("authorization_sequence") == 2
        ),
        -1,
    )
    stale_markers = [
        marker
        for marker in raw_markers
        if marker.get("event") == "host_command_rejected"
    ]
    checks = {
        "private_nonphysical_manifest_exact": manifest_value.get("stage")
        == REHEARSAL_STAGE,
        "process_command_transcript_matches_raw": commands == raw_commands,
        "supervisor_commands_match_capture_prefix": supervisor_events_commands
        == raw_commands[: len(supervisor_events_commands)],
        "actual_capture_process_bound_to_closure": capture_pid
        == process_evidence.get("processes", {}).get("capture", {}).get("pid")
        == source_capture_state.get("pid"),
        "setup_command_bound_to_retained_authority": setup_command_exact,
        "two_arm_envelopes_bound_to_supervisor_events": arm_command_exact,
        "progressive_evidence_phases_exact": phases
        == [(request, phase) for request in (1, 2) for phase in (1, 2, 3, 4)],
        "periodic_lease_and_snapshot_boundaries": sum(
            command.startswith("ACTIVE LEASE ") for command in raw_commands
        )
        >= 1
        and sum(command.startswith("ACTIVE SNAPSHOT ") for command in raw_commands)
        >= 8,
        "stale_command_timeout_rejected": len(stale_markers) == 1
        and "stale or from the future" in str(stale_markers[0].get("reason"))
        and int(source_closure.get("counters", {}).get("commands_rejected", 0))
        == 1,
        "first_dependent_checkpoint_before_second_arm": supervisor.get(
            "later_authority_released"
        )
        is True
        and 0 <= first_checkpoint_event_index < second_arm_event_index,
        "setup_first_consumer_exact": manual_start.get("event") == "manual_start"
        and authority.get("record_sha256") == authority_sha256
        and supervisor.get("setup_confirmation") == expected_setup_confirmation
        and _explicit_utc(supervisor.get("setup_confirmed_utc"))
        and setup_confirmation_event_exact,
        "metadata_hold_requalified_without_actuation": supervisor.get(
            "gnss_metadata_hold_count"
        )
        == 1
        and supervisor.get("gnss_metadata_hold") is None,
        "two_transactions_replayed": replay.get("exact") is True
        and shared_replay.get("transaction_history_exact") is True
        and shared_replay.get("transaction_row_count") == 9,
        "shared_current_analyzer_consumers_exact": shared_consumers.get("exact")
        is True,
        "normal_fifo_revoked_after_obstruction": "normal_command_ingress_revoked"
        in raw_events
        and int(
            process_evidence.get("normal_transport_obstruction", {}).get(
                "bytes_written_before_eagain", 0
            )
        )
        > 0,
        "priority_abort_preceded_source_close": emergency_position >= 0
        and close_position > emergency_position
        and int(source_closure.get("counters", {}).get("emergency_aborts_sent", 0))
        == 1
        and supervisor.get("terminal", {}).get("reason")
        == "independent_host_abort_fifo",
        "same_owner_rotation_then_physical_close": transition_bindings_exact
        and transition_manifest_exact
        and request_exact
        and response_exact
        and closures_exact
        and rotation.get("ownerless_interval") is False
        and request.get("from_run") == str(run_dir)
        and request.get("to_run")
        == str((run_dir / TRANSITION_DIR).resolve())
        and request.get("expected_pid") == capture_pid
        and request.get("expected_manifest_sha256")
        == _sha256_file(expected_transition_manifest)
        and retained_response.get("pid") == capture_pid
        and retained_response.get("from_run") == str(run_dir)
        and retained_response.get("to_run")
        == str((run_dir / TRANSITION_DIR).resolve())
        and retained_response.get("transport_generation") == 2
        and retained_response.get("serial_reopened") is False
        and retained_response.get("reconnect_count") == 0
        and rotation.get("source_closure") == source_closure
        and rotation.get("transition_closure") == transition_closure
        and source_closure.get("owner_pid") == transition_closure.get("owner_pid")
        and source_closure.get("run") == str(run_dir)
        and source_closure.get("run_manifest_sha256")
        == _sha256_file(run_dir / "run_manifest.json")
        and source_closure.get("device") == manifest_value["host"]["serial_device"]
        and source_closure.get("baud") == 115200
        and source_closure.get("transport_generation") == 1
        and source_closure.get("closure_mode") == "same_owner_logical_rotation"
        and source_closure.get("logical_segment_closed") is True
        and source_closure.get("physical_serial_open") is True
        and source_closure.get("serial_reopened") is False
        and source_closure.get("next_run")
        == str((run_dir / TRANSITION_DIR).resolve())
        and source_closure.get("request_id") == request_id
        and source_closure.get("serial_owner_check")
        == {"performed": True, "owner_pids": [capture_pid]}
        and transition_closure.get("run")
        == str((run_dir / TRANSITION_DIR).resolve())
        and transition_closure.get("run_manifest_sha256")
        == _sha256_file(expected_transition_manifest)
        and transition_closure.get("device")
        == manifest_value["host"]["serial_device"]
        and transition_closure.get("baud") == 115200
        and transition_closure.get("transport_generation") == 2
        and transition_closure.get("closure_mode") == "physical_serial_close"
        and transition_closure.get("logical_segment_closed") is True
        and transition_closure.get("physical_serial_open") is False
        and transition_closure.get("serial_reopened") is False
        and transition_closure.get("next_run") is None
        and transition_closure.get("request_id") is None
        and transition_closure.get("serial_owner_check") is None
        and transition_capture_state.get("pid") == capture_pid
        and transition_capture_state.get("capture_active") is False
        and transition_capture_state.get("serial_open") is False
        and transition_capture_state.get("logical_segment_closed") is True
        and transition_capture_state.get("physical_serial_open") is False
        and transition_capture_state.get("transport_generation") == 2
        and transition_capture_state.get("command_fifo_configured") is False
        and transition_capture_state.get("emergency_command_fifo_configured") is False
        and transition_health_header
        == [",".join(CONTRACT_FIELDS["health_v1"])]
        and [marker.get("event") for marker in transition_raw_markers]
        == ["capture_started", "capture_stopped"],
        "read_only_monitor_observed_lifecycle": any(
            not row.get("pending", False) for row in monitor_rows
        ),
        "supervisor_terminal_is_operator_abort": supervisor.get("terminal", {}).get(
            "reason"
        )
        == "independent_host_abort_fifo",
        "host_events_durable": any(
            event.get("event")
            == programme_event_prefix + "setup_first_consumer_confirmed"
            for event in events
        )
        and sum(
            event.get("event") == "transaction_phase_acknowledged"
            for event in events
        )
        == 8,
    }
    if not all(checks.values()):
        failed = sorted(name for name, value in checks.items() if not value)
        raise ValueError("operational rehearsal analysis failed: " + ", ".join(failed))
    snapshot = _read_object(
        run_dir / "evidence_manifest.json", "rehearsal evidence snapshot"
    )
    snapshot_failures, snapshot_warnings = validate_evidence_snapshot(
        run_dir, manifest
    )
    if snapshot_failures or snapshot_warnings:
        raise ValueError("rehearsal snapshot changed before sealing")
    sources = {
        str(item["path"]): str(item["sha256"])
        for item in snapshot["artifacts"]
    }
    seal: dict[str, Any] = {
        "schema_version": 1,
        "seal_type": SEAL_TYPE,
        "tool": ANALYZER_ID,
        "tool_sha256": _sha256_file(Path(__file__)),
        "created_utc": _utc_now(),
        "run_id": manifest.run_id,
        "report_kind": REPORT_KIND,
        "programme_id": ADAPTIVE_HYBRID_PROGRAMME.programme_id,
        "run_identity": ADAPTIVE_HYBRID_PROGRAMME.runtime_run_identity,
        "image_identity": ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        "build_identity": str(bundle["firmware"]["build_identity"]),
        "bundle_sha256": bundle["bundle_sha256"],
        "policy_sha256": bundle["policy"]["policy_sha256"],
        "status": "passed",
        "primary_decision": "adaptive_hybrid_operational_rehearsal_passed",
        "checks": checks,
        "csv_validation": csv_validation,
        "maintenance_replay": replay,
        "shared_current_analyzer_consumers": shared_consumers,
        "evidence_snapshot": {
            "path": "evidence_manifest.json",
            "snapshot_digest": snapshot["snapshot_digest"],
            "failures": [],
            "warnings": [],
        },
        "source_sha256": sources,
        "process_evidence_sha256": _sha256_file(run_dir / PROCESS_EVIDENCE_PATH),
        "D10_diagnostic": d10_diagnostic,
        "D10_semantics": {
            "manifest_channel": manifest_value["channels"][0],
            "control_consumer": None,
            "terminal_consumer": None,
            "absence_noise_or_invalidity_fail_local": True,
        },
        "claim_boundary": {
            "activation_input_only": True,
            "physical_plant_qualification": False,
            "USB_CDC_or_firmware_execution_proven": False,
            "physical_actions_performed": 0,
        },
    }
    seal["seal_sha256"] = _canonical_sha256(seal)
    _atomic_json(run_dir / SEAL_PATH, seal, exclusive=True)
    return seal


def validate_operational_rehearsal_package(
    location: Path,
    *,
    source_revision: str,
    build_identity: str,
    image_identity: str,
    result_or_failure_reason: str,
    analyzer_identity: str,
) -> dict[str, str]:
    """Independently validate one immutable successful rehearsal package."""

    return _validate_rehearsal_package(
        location,
        source_revision=source_revision,
        build_identity=build_identity,
        image_identity=image_identity,
        result_or_failure_reason=result_or_failure_reason,
        analyzer_identity=analyzer_identity,
    )


def _registration_metadata(
    bundle: dict[str, Any], *, classification: str, reason: str
) -> dict[str, str]:
    return {
        "source_revision": str(bundle["firmware"]["source_revision"]),
        "build_identity": str(bundle["firmware"]["build_identity"]),
        "image_identity": ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        "attempt_classification": classification,
        "result_or_failure_reason": reason,
        "analyzer_identity": _sha256_file(Path(__file__)),
    }


def _run_validated(
    *,
    bundle_path: Path,
    bundle: dict[str, Any],
    proposal_path: Path,
    proposal: dict[str, Any],
    run_dir: Path,
    evidence_index_path: Path,
) -> Path:
    """Run an already validated frozen bundle without any physical operation."""

    run_dir = run_dir.resolve()
    evidence_index_path = evidence_index_path.expanduser().resolve()
    try:
        evidence_index_path.relative_to(run_dir)
    except ValueError:
        pass
    else:
        raise ValueError(
            "operational rehearsal evidence index must be outside the immutable "
            "package"
        )
    run_dir.mkdir(parents=True, exist_ok=False)
    master_fd, slave_fd = pty.openpty()
    device = os.path.realpath(os.ttyname(slave_fd))
    if not _is_pty(device):
        os.close(master_fd)
        os.close(slave_fd)
        raise RuntimeError("pty.openpty returned a non-canonical slave path")
    manifest_path = create_rehearsal_run_manifest(
        run_dir=run_dir,
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
        device=device,
    )
    manifest_value = validate_rehearsal_run_manifest(
        manifest_path, bundle=bundle, proposal=proposal
    )
    initial_registration = _registration_metadata(
        bundle,
        classification="diagnostic",
        reason="adaptive-hybrid operational rehearsal finalization pending",
    )
    journal = begin_finalization(
        run_dir=run_dir,
        index_path=evidence_index_path,
        registration=initial_registration,
        required_seal=SEAL_PATH,
    )
    process_evidence = _run_process_topology(
        run_dir=run_dir,
        manifest_path=manifest_path,
        bundle=bundle,
        device=device,
        master_fd=master_fd,
        slave_fd=slave_fd,
    )
    _atomic_json(run_dir / PROCESS_EVIDENCE_PATH, process_evidence, exclusive=True)
    advance_phase(
        journal,
        "capture_closed",
        {
            "capture_exit": process_evidence["processes"]["capture"]["exit"],
            "priority_abort_delivered": True,
            "same_owner_rotation": True,
        },
    )
    completion = {
        "schema_version": 1,
        "completion": COMPLETION_TYPE,
        "completed_utc": _utc_now(),
        "run_id": run_dir.name,
        "terminal": process_evidence["terminal"],
        "physical_actions_performed": 0,
        "claim_boundary": "deterministic_host_operational_path_only",
    }
    _atomic_json(run_dir / COMPLETE_MARKER, completion, exclusive=True)
    advance_phase(journal, "completion", {"completion": COMPLETION_TYPE})
    snapshot_path = create_evidence_snapshot(
        run_dir,
        manifest=RunManifest(run_dir, manifest_path, manifest_value),
    )
    snapshot = _read_object(snapshot_path, "rehearsal evidence snapshot")
    advance_phase(
        journal,
        "snapshot",
        {"snapshot_digest": snapshot["snapshot_digest"]},
    )
    seal = analyze_and_seal_rehearsal(
        run_dir=run_dir,
        manifest_value=manifest_value,
        bundle=bundle,
    )
    advance_phase(
        journal,
        "analysis",
        {"analyzer": ANALYZER_ID, "status": seal["status"]},
    )
    advance_phase(
        journal,
        "seal",
        {"path": SEAL_PATH.as_posix(), "seal_sha256": seal["seal_sha256"]},
    )
    identity = package_identity(run_dir)
    success_metadata = _registration_metadata(
        bundle,
        classification="successful_rehearsal",
        reason="adaptive-hybrid operational rehearsal passed",
    )
    registration = register_package(
        index_path=evidence_index_path,
        package_path=run_dir,
        expected_content_sha256=identity["content_sha256"],
        **success_metadata,
    )
    registration_metadata = success_metadata
    successful_registration = True
    success_error: str | None = None
    set_registration_intent(
        journal,
        registration=registration_metadata,
        expected_content_sha256=identity["content_sha256"],
    )
    advance_phase(
        journal,
        "registration",
        {
            "content_sha256": registration["content_sha256"],
            "attempt_classification": registration["attempt_classification"],
        },
    )
    seal_checks = seal["checks"]
    boundary_results = {
        "continuous_capture_and_exact_frozen_identity_consumption": bool(
            seal_checks["private_nonphysical_manifest_exact"]
            and seal_checks["actual_capture_process_bound_to_closure"]
            and seal_checks["process_command_transcript_matches_raw"]
        ),
        "actual_capture_and_supervisor_process_topology": bool(
            seal_checks["actual_capture_process_bound_to_closure"]
            and seal_checks["supervisor_commands_match_capture_prefix"]
            and seal_checks["read_only_monitor_observed_lifecycle"]
        ),
        "setup_arm_and_evidence_ack_through_first_dependent_decision": bool(
            seal_checks["setup_command_bound_to_retained_authority"]
            and seal_checks["setup_first_consumer_exact"]
            and seal_checks["progressive_evidence_phases_exact"]
            and seal_checks["first_dependent_checkpoint_before_second_arm"]
        ),
        "timeout_periodic_and_repeated_transaction_boundaries": bool(
            seal_checks["periodic_lease_and_snapshot_boundaries"]
            and seal_checks["stale_command_timeout_rejected"]
            and seal_checks["two_arm_envelopes_bound_to_supervisor_events"]
            and seal_checks["two_transactions_replayed"]
        ),
        "normal_command_transport_obstruction": bool(
            seal_checks["normal_fifo_revoked_after_obstruction"]
        ),
        "independent_priority_abort_submission_and_delivery_before_capture_close": bool(
            seal_checks["priority_abort_preceded_source_close"]
            and seal_checks["supervisor_terminal_is_operator_abort"]
        ),
        "atomic_serial_owner_handoff_without_ownerless_interval": bool(
            seal_checks["same_owner_rotation_then_physical_close"]
        ),
        "clean_stop_shared_current_analyzer_consumers_snapshot_rehearsal_seal_and_successful_registration": bool(
            seal.get("status") == "passed"
            and seal_checks["shared_current_analyzer_consumers_exact"]
            and snapshot.get("run_state") == "complete"
            and successful_registration
        ),
    }
    if tuple(boundary_results) != REQUIRED_BOUNDARIES:
        raise RuntimeError("derived rehearsal boundary ordering differs")
    authorization_contract = operational_rehearsal_authorization_contract(
        bundle=bundle, proposal=proposal
    )
    required_evidence = dict(authorization_contract["required_evidence"])
    required_evidence["shared_current_analyzer_consumers_exact"] = bool(
        seal_checks["shared_current_analyzer_consumers_exact"]
    )
    required_evidence["successful_rehearsal_registration"] = (
        successful_registration
    )
    claim_boundary = dict(authorization_contract["claim_boundary"])
    claim_boundary["authorizes_activation_input_only"] = successful_registration
    report: dict[str, Any] = {
        **authorization_contract,
        "tool": TOOL_ID,
        "tool_binding": _binding(Path(__file__)),
        "status": (
            "passed"
            if successful_registration
            else "passed_pending_successful_rehearsal_registration"
        ),
        "created_utc": _utc_now(),
        "boundary_results": boundary_results,
        "required_evidence": required_evidence,
        "package": {
            "path": str(run_dir),
            "content_sha256": identity["content_sha256"],
            "file_count": identity["file_count"],
            "total_bytes": identity["total_bytes"],
        },
        "manifest": _binding(manifest_path),
        "evidence_snapshot": {
            **_binding(snapshot_path),
            "snapshot_digest": snapshot["snapshot_digest"],
        },
        "seal": {**_binding(run_dir / SEAL_PATH), "seal_sha256": seal["seal_sha256"]},
        "process_evidence": _binding(run_dir / PROCESS_EVIDENCE_PATH),
        "registration": {
            "index_path": str(evidence_index_path.resolve()),
            "content_sha256": registration["content_sha256"],
            "attempt_classification": registration["attempt_classification"],
            "successful_rehearsal_validation_error": success_error,
        },
        "activation_input_ready": successful_registration,
        "minimal_remaining_extension": (
            None
            if successful_registration
            else (
                "evidence_index._validated_success_package must dispatch "
                "successful_rehearsal to validate_operational_rehearsal_package "
                "for the new seal path instead of the physical campaign seal"
            )
        ),
        "claim_boundary": claim_boundary,
    }
    report["report_sha256"] = _canonical_sha256(report)
    report_path = run_dir.parent / f"{run_dir.name}-{REPORT_NAME}"
    _atomic_json(report_path, report, exclusive=True)
    return report_path


def run_operational_rehearsal(
    *,
    bundle_path: Path,
    proposal_path: Path,
    run_dir: Path,
    evidence_index_path: Path,
) -> Path:
    bundle_path = bundle_path.resolve()
    proposal_path = proposal_path.resolve()
    bundle = validate_bundle(bundle_path, ADAPTIVE_HYBRID_PROGRAMME)
    proposal = validate_proposal(proposal_path, ADAPTIVE_HYBRID_PROGRAMME)
    return _run_validated(
        bundle_path=bundle_path,
        bundle=bundle,
        proposal_path=proposal_path,
        proposal=proposal,
        run_dir=run_dir,
        evidence_index_path=evidence_index_path,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_subparsers(dest="operation", required=True)
    run = operations.add_parser("run")
    run.add_argument("--bundle", type=Path, required=True)
    run.add_argument("--proposal", type=Path, required=True)
    run.add_argument("--run-dir", type=Path, required=True)
    run.add_argument("--evidence-index", type=Path, required=True)
    supervisor = operations.add_parser("_supervisor_worker")
    supervisor.add_argument("--manifest", type=Path, required=True)
    supervisor.add_argument("--run-dir", type=Path, required=True)
    monitor = operations.add_parser("_monitor_worker")
    monitor.add_argument("--manifest", type=Path, required=True)
    monitor.add_argument("--run-dir", type=Path, required=True)
    monitor.add_argument("--stop-path", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == "run":
            path = run_operational_rehearsal(
                bundle_path=args.bundle,
                proposal_path=args.proposal,
                run_dir=args.run_dir,
                evidence_index_path=args.evidence_index,
            )
            print(path)
            return 0
        if args.operation == "_supervisor_worker":
            return _supervisor_worker(args.manifest, args.run_dir)
        return _monitor_worker(args.run_dir, args.manifest, args.stop_path)
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
