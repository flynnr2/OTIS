"""Validate and bind the one operator-authorized CX318 Stage 4 setup write.

This tool is offline-only.  It never opens serial or writes the DAC.  The
source run must already be closed, marked COMPLETE, and immutably snapshotted.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
import argparse
import csv
import json
import os
import tempfile
from typing import Any

from .contracts import CONTRACT_FIELDS, CsvValidationContext, validate_csv
from .cx318_stage4_flash import validate_build_inputs, validate_flash_record
from .cx318_stage4_premise_flash import (
    PROFILE_ID as PREMISE_PROFILE_ID,
    validate_premise_flash_record,
)
from .cx318_stage4_premise_command import (
    CAMPAIGN_LATCH_PATH as PREMISE_CAMPAIGN_LATCH_PATH,
    COMMAND as PREMISE_COMMAND,
    LATCH_PATH as PREMISE_LATCH_PATH,
    TOOL_ID as PREMISE_LATCH_TOOL,
)
from .evidence import validate_evidence_snapshot
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, load_manifest
from .service_plane_probe import HOST_MARKER_PREFIX


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_STAGE = "CX318_STAGE4_STATIC_CODE_SETUP"
EXPECTED_IDENTITY_STAGE = "CX318_STAGE4_POST_FLASH_IDENTITY"
EXPECTED_CODE = 0xA828
EXPECTED_DAC_EPOCH = 1
EXPECTED_COMMANDS = (
    "CONFIG?",
    "DUALCORE?",
    "DAC?",
    "DAC SET 0xA828",
    "DAC?",
)
PROOF_TYPE = "cx318_stage4_exact_static_code_setup_v1"
PRODUCER_TOOL = "cx318_stage4_static_code_preflight_v1"


@dataclass(frozen=True)
class SetupEvidence:
    source_run_path: str
    confirmed_code: int
    dac_epoch: int
    dac_row_sequence: int
    command_sequence: tuple[str, ...]
    source_identities: dict[str, str]
    snapshot_session: int
    opening_snapshot_sequence: int
    closing_snapshot_sequence: int


@dataclass(frozen=True)
class IdentityEvidence:
    identity_run_path: str
    source_identities: dict[str, str]
    snapshot_session: int
    opening_snapshot_sequence: int
    closing_snapshot_sequence: int
    flash_record_path: str
    flash_record_sha256: str
    usb_identity_sha256: str
    board_serial_number: str


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _contract_path(manifest: Any, contract: str) -> Path:
    paths = [
        manifest.root / str(item["path"])
        for item in manifest.files
        if item.get("contract") == contract
    ]
    if len(paths) != 1:
        raise ValueError(f"expected exactly one {contract} artifact, got {len(paths)}")
    return paths[0]


def _repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("setup evidence must be inside the repository") from exc


def _safe_repo_path(value: Any) -> tuple[str, Path]:
    if not isinstance(value, str) or not value:
        raise ValueError("evidence path must be a non-empty repository-relative string")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or value != relative.as_posix():
        raise ValueError("evidence path must be normalized and repository-relative")
    path = REPO_ROOT
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("evidence path must not traverse a symbolic link")
    return value, path


def _safe_run_path(run_dir: Path, value: Any) -> tuple[str, Path]:
    if not isinstance(value, str) or not value:
        raise ValueError("run artifact path must be a non-empty string")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or value != relative.as_posix():
        raise ValueError("run artifact path must be normalized and relative")
    path = run_dir
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("run artifact path must not traverse a symbolic link")
    return value, path


def _host_commands(raw_log: Path) -> tuple[str, ...]:
    accepted: list[str] = []
    sent: list[str] = []
    capture_started = 0
    capture_stopped = 0
    with raw_log.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\r\n")
            if not line.startswith(HOST_MARKER_PREFIX):
                continue
            marker = json.loads(line[len(HOST_MARKER_PREFIX) :])
            if not isinstance(marker, dict):
                raise ValueError("host marker is not a JSON object")
            event = marker.get("event")
            if event == "host_command_accepted":
                accepted.append(str(marker.get("command", "")))
            elif event == "host_command_sent":
                sent.append(str(marker.get("command", "")))
            elif event == "capture_started":
                capture_started += 1
            elif event == "capture_stopped":
                capture_stopped += 1
            elif event in {
                "host_command_rejected",
                "serial_disconnected",
                "parser_error",
                "malformed_utf8",
                "partial_line_dropped",
            }:
                raise ValueError(f"setup capture contains fault marker {event}")
    if capture_started != 1 or capture_stopped != 1:
        raise ValueError("setup capture must contain exactly one start and stop marker")
    if accepted != sent:
        raise ValueError("accepted and sent setup command sequences differ")
    return tuple(sent)


def _require_contiguous_snapshots(rows: list[dict[str, str]]) -> tuple[int, int, int]:
    if len(rows) < 2:
        raise ValueError("setup capture has fewer than two PPS snapshots")
    sessions = {int(row["session"]) for row in rows}
    if len(sessions) != 1:
        raise ValueError("setup capture crosses a snapshot session boundary")
    sequences = [int(row["snapshot_sequence"]) for row in rows]
    references = [int(row["reference_sequence"]) for row in rows]
    if any(row["status"].strip() != "0" for row in rows):
        raise ValueError("setup capture contains an unqualified PPS snapshot")
    if any(right != left + 1 for left, right in zip(sequences, sequences[1:])):
        raise ValueError("setup snapshot sequence is discontinuous")
    if any(right != left + 1 for left, right in zip(references, references[1:])):
        raise ValueError("setup reference sequence is discontinuous")
    return next(iter(sessions)), sequences[0], sequences[-1]


def _safe_health_history(rows: list[dict[str, str]]) -> dict[tuple[str, str], str]:
    latest: dict[tuple[str, str], str] = {}
    violations: list[str] = []
    for row in rows:
        component = row["component"].strip()
        key = row["status_key"].strip()
        value = row["status_value"].strip()
        latest[(component, key)] = value
        lowered = value.lower()
        if key == "partition_fault" and lowered != "none":
            violations.append(f"{component}.{key}={value}")
        if key in {
            "fail_static",
            "actionable",
            "actuation_authorized",
            "authorization_consumed",
            "manual_start_confirmed",
            "arm_eligible",
        } and lowered == "true":
            violations.append(f"{component}.{key}={value}")
        if "dropped" in key or "overflow" in key or key.endswith("_drop_count"):
            try:
                nonzero = int(value, 0) != 0
            except ValueError:
                nonzero = True
            if nonzero:
                violations.append(f"{component}.{key}={value}")
    if violations:
        raise ValueError("unsafe setup health history: " + ", ".join(violations[:8]))
    return latest


def _health_is_safe(rows: list[dict[str, str]], code: int) -> None:
    latest = _safe_health_history(rows)
    code_text = f"0x{code:04X}"
    required = {
        ("dac", "applied_code_known"): "true",
        ("dac", "last_write_ok"): "true",
        ("dac", "last_requested_code"): code_text,
        ("dac", "last_applied_code"): code_text,
    }
    mismatches = {
        f"{component}.{key}": {"expected": expected, "actual": latest.get((component, key))}
        for (component, key), expected in required.items()
        if latest.get((component, key)) != expected
    }
    if mismatches:
        raise ValueError("final DAC health does not confirm setup: " + json.dumps(mismatches, sort_keys=True))


def _raw_records(raw_log: Path, record_type: str) -> list[list[str]]:
    records: list[list[str]] = []
    with raw_log.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        for line in handle:
            if line.split(",", 1)[0] == record_type:
                records.append(next(csv.reader([line.rstrip("\r\n")])))
    return records


def _campaign_root(run_dir: Path) -> Path:
    for candidate in (run_dir, *run_dir.parents):
        if (candidate / "PROGRAMME_STATE.md").is_file():
            return candidate
    raise ValueError("setup run is not inside the durable CX318 campaign ledger")


def _raw_setup_transition(raw_log: Path, expected_dac: list[str]) -> None:
    """Prove the raw-stream ordering unknown -> one write -> known."""
    lines = raw_log.read_text(encoding="utf-8", errors="replace").splitlines()
    sent: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        if not line.startswith(HOST_MARKER_PREFIX):
            continue
        marker = json.loads(line[len(HOST_MARKER_PREFIX) :])
        if isinstance(marker, dict) and marker.get("event") == "host_command_sent":
            sent.append((str(marker.get("command", "")), index))
    if tuple(command for command, _ in sent) != EXPECTED_COMMANDS:
        raise ValueError("raw setup command ordering differs")
    initial_query = sent[2][1]
    write = sent[3][1]
    final_query = sent[4][1]
    if not initial_query < write < final_query:
        raise ValueError("raw setup command positions are not strictly ordered")

    def status_values(start: int, stop: int) -> dict[tuple[str, str], str]:
        latest: dict[tuple[str, str], str] = {}
        fields = CONTRACT_FIELDS["health_v1"]
        for line in lines[start + 1 : stop]:
            if line.split(",", 1)[0] != "STS":
                continue
            values = next(csv.reader([line]))
            if len(values) != len(fields):
                raise ValueError("raw setup STS record has the wrong field count")
            row = dict(zip(fields, values))
            latest[(row["component"].strip(), row["status_key"].strip())] = (
                row["status_value"].strip()
            )
        return latest

    initial = status_values(initial_query, write)
    expected_initial = {
        ("dac", "applied_code_known"): "false",
        ("dac", "last_write_ok"): "false",
        ("dac", "last_requested_code"): "0x0000",
        ("dac", "last_applied_code"): "unavailable",
    }
    if any(initial.get(key) != value for key, value in expected_initial.items()):
        raise ValueError("raw setup lacks ordered pre-write unknown-DAC evidence")

    between_write_and_query = [
        next(csv.reader([line]))
        for line in lines[write + 1 : final_query]
        if line.split(",", 1)[0] == "DAC"
    ]
    if between_write_and_query != [expected_dac]:
        raise ValueError("raw setup lacks exactly one ordered A828 DAC record")

    final = status_values(final_query, len(lines))
    expected_final = {
        ("dac", "applied_code_known"): "true",
        ("dac", "last_write_ok"): "true",
        ("dac", "last_requested_code"): "0xA828",
        ("dac", "last_applied_code"): "0xA828",
    }
    if any(final.get(key) != value for key, value in expected_final.items()):
        raise ValueError("raw setup lacks ordered post-write known-A828 evidence")


def _validate_premise_lineage(
    run_dir: Path, manifest: Any,
) -> tuple[dict[str, Any], dict[str, Path]]:
    lineage = manifest.data.get("premise_firmware", {})
    if not isinstance(lineage, dict) or lineage.get("profile_id") != PREMISE_PROFILE_ID:
        raise ValueError("setup manifest lacks the exact premise firmware identity")
    resolved: dict[str, Path] = {}
    for name in ("matrix", "build_manifest", "uf2", "flash_record"):
        reference = lineage.get(name, {})
        if not isinstance(reference, dict):
            raise ValueError(f"premise {name} reference is malformed")
        _, path = _safe_run_path(run_dir, reference.get("path"))
        if reference.get("sha256") != _sha256_file(path):
            raise ValueError(f"premise {name} hash differs")
        if name == "uf2" and reference.get("size_bytes") != path.stat().st_size:
            raise ValueError("premise UF2 size differs")
        resolved[name] = path
    record = json.loads(resolved["flash_record"].read_text(encoding="utf-8"))
    binding = validate_premise_flash_record(
        record,
        matrix_path=resolved["matrix"],
        build_manifest_path=resolved["build_manifest"],
        uf2_path=resolved["uf2"],
    )
    if lineage.get("artifact_binding") != binding:
        raise ValueError("setup premise artifact binding differs from flash lineage")
    return binding, resolved


def validate_setup_run(run_dir: Path) -> SetupEvidence:
    """Return exact evidence only for the single authorized A828 setup run."""
    run_dir = run_dir.resolve()
    if (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise ValueError("setup capture is still in progress")
    if not (run_dir / "COMPLETE").is_file():
        raise ValueError("setup run is not marked COMPLETE")
    manifest = load_manifest(run_dir)
    if manifest.is_template or manifest.data.get("stage") != EXPECTED_STAGE:
        raise ValueError(f"setup run stage must be {EXPECTED_STAGE}")
    authorization = manifest.data.get("stage4_static_setup", {})
    expected_authorization = {
        "premise_amendment": "operator_authorized_single_setup_write",
        "authorized_code": "0xA828",
        "maximum_setup_attempts": 1,
        "maximum_setup_writes": 1,
        "retry_after_failure": False,
        "opening_dac_epoch": 0,
        "resulting_dac_epoch": EXPECTED_DAC_EPOCH,
        "automatic_authority": False,
        "phase_hybrid_authority": False,
        "gps_transmit_authorized": False,
    }
    if not isinstance(authorization, dict) or any(
        authorization.get(key) != value for key, value in expected_authorization.items()
    ):
        raise ValueError("setup manifest lacks the exact operator-authorized premise amendment")
    premise_binding, premise_paths = _validate_premise_lineage(run_dir, manifest)

    snapshot_path = run_dir / "evidence_manifest.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    failures, warnings = validate_evidence_snapshot(run_dir, manifest)
    if snapshot.get("run_state") != "complete" or failures or warnings:
        raise ValueError(
            "setup evidence snapshot is not a clean complete snapshot: "
            + "; ".join([*failures, *warnings][:6])
        )

    paths = {
        contract: _contract_path(manifest, contract)
        for contract in (
            "pps_snapshots_v1",
            "count_observations_v1",
            "health_v1",
            "dac_steps_v1",
            "environment_v1",
            "active_transactions_v1",
        )
    }
    for contract, path in paths.items():
        result = validate_csv(
            path,
            CsvValidationContext(
                contract=contract,
                known_channels=manifest.known_channels,
                known_domains=manifest.known_domains,
                allow_rp2040_timer0_wrap=True,
            ),
        )
        if not result.ok:
            raise ValueError(f"invalid {contract}: {'; '.join(result.errors[:4])}")

    state_path = run_dir / "reports/capture_device_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    expected_state = {
        "capture_active": False,
        "serial_open": False,
        "parser_errors": 0,
        "malformed_utf8": 0,
        "reconnect_count": 0,
        "commands_rejected": 0,
        "commands_sent": len(EXPECTED_COMMANDS),
    }
    if any(state.get(key) != value for key, value in expected_state.items()):
        raise ValueError("setup capture state is not clean: " + json.dumps(state, sort_keys=True))

    campaign_root = _campaign_root(run_dir)
    latch_path = run_dir / PREMISE_LATCH_PATH
    campaign_latch_path = campaign_root / PREMISE_CAMPAIGN_LATCH_PATH
    latch = json.loads(latch_path.read_text(encoding="utf-8"))
    campaign_latch = json.loads(campaign_latch_path.read_text(encoding="utf-8"))
    expected_latch = {
        "schema_version": 1,
        "tool": PREMISE_LATCH_TOOL,
        "status": "attempt_latched_before_enqueue",
        "run_id": run_dir.name,
        "command": PREMISE_COMMAND,
        "maximum_attempts": 1,
        "retry_authorized": False,
        "capture_pid": state.get("pid"),
        "precommand_sequence": list(EXPECTED_COMMANDS[:3]),
        "campaign_id": campaign_root.name,
        "campaign_latch_path": PREMISE_CAMPAIGN_LATCH_PATH.as_posix(),
    }
    if any(latch.get(key) != value for key, value in expected_latch.items()):
        raise ValueError("setup premise attempt latch is invalid")
    expected_campaign_latch = {
        **expected_latch,
        "run_latch_path": latch_path.relative_to(campaign_root).as_posix(),
    }
    if any(
        campaign_latch.get(key) != value
        for key, value in expected_campaign_latch.items()
    ) or campaign_latch.get("created_utc") != latch.get("created_utc"):
        raise ValueError("campaign-wide premise attempt latch is invalid")

    raw_log = run_dir / "raw/serial.log"
    commands = _host_commands(raw_log)
    if commands != EXPECTED_COMMANDS:
        raise ValueError(f"setup command sequence differs: {commands!r}")
    dac_rows = _read_rows(paths["dac_steps_v1"])
    if len(dac_rows) != 1:
        raise ValueError(f"setup run must contain exactly one DAC row, got {len(dac_rows)}")
    row = dac_rows[0]
    expected_dac = {
        "dac_code_requested": str(EXPECTED_CODE),
        "dac_code_applied": str(EXPECTED_CODE),
        "dac_code_clamped": "0",
        "event": "manual_apply",
        "flags": "0",
    }
    if any(row.get(key, "").strip() != value for key, value in expected_dac.items()):
        raise ValueError("setup DAC row is not an exact successful A828 manual application")
    expected_raw_dac = [
        [row.get(field, "") for field in CONTRACT_FIELDS["dac_steps_v1"]]
        for row in dac_rows
    ]
    if _raw_records(raw_log, "DAC") != expected_raw_dac:
        raise ValueError("raw serial DAC record does not exactly match the single split CSV row")
    _raw_setup_transition(raw_log, expected_raw_dac[0])
    if _read_rows(paths["active_transactions_v1"]):
        raise ValueError("setup run contains an active transaction")
    health_rows = _read_rows(paths["health_v1"])
    _health_is_safe(health_rows, EXPECTED_CODE)
    if not any(
        row["component"].strip() == "dac"
        and row["status_key"].strip() == "applied_code_known"
        and row["status_value"].strip().lower() == "false"
        for row in health_rows
    ):
        raise ValueError("setup run lacks pre-write evidence that the DAC code was unknown")
    latest = _safe_health_history(health_rows)
    required_premise = {
        ("firmware", "git_commit"): premise_binding["git_commit"],
        ("firmware", "source_state"): "clean",
        ("firmware", "source_hash"): premise_binding["source_sha256"],
        ("firmware", "config_hash"): premise_binding["configuration_sha256"],
        ("build", "profile_id"): PREMISE_PROFILE_ID,
        ("build", "enable_cx318_stage4_premise_setup"): "1",
        ("build", "enable_cx318_stage4_preview"): "0",
        ("build", "enable_cx317_i_only_preview"): "0",
        ("build", "enable_cx317_bounded_active"): "0",
        ("build", "enable_dac_ad5693r"): "1",
        ("cx318_premise", "allowed_code"): "0xA828",
        ("cx318_premise", "write_consumed"): "true",
        ("cx318_premise", "actionable"): "false",
        ("cx318_premise", "actuation_authorized"): "false",
        ("cx318_premise", "automatic_authority"): "false",
    }
    premise_mismatches = {
        f"{component}.{key}": {"expected": expected, "actual": latest.get((component, key))}
        for (component, key), expected in required_premise.items()
        if latest.get((component, key)) != expected
    }
    if premise_mismatches:
        raise ValueError(
            "setup premise health mismatch: "
            + json.dumps(premise_mismatches, sort_keys=True)
        )
    sources = {row["source"].strip().lower() for row in _read_rows(paths["environment_v1"])}
    if not {"sht4x", "bmp280"} <= sources:
        raise ValueError(f"setup run lacks both environment streams: {sorted(sources)}")
    session, first_snapshot, last_snapshot = _require_contiguous_snapshots(
        _read_rows(paths["pps_snapshots_v1"])
    )

    identities = {
        "run_manifest_sha256": _sha256_file(manifest.path),
        "evidence_snapshot_sha256": _sha256_file(snapshot_path),
        "raw_serial_sha256": _sha256_file(raw_log),
        "health_sha256": _sha256_file(paths["health_v1"]),
        "dac_steps_sha256": _sha256_file(paths["dac_steps_v1"]),
        "active_transactions_sha256": _sha256_file(paths["active_transactions_v1"]),
        "premise_matrix_sha256": _sha256_file(premise_paths["matrix"]),
        "premise_build_manifest_sha256": _sha256_file(
            premise_paths["build_manifest"]
        ),
        "premise_uf2_sha256": _sha256_file(premise_paths["uf2"]),
        "premise_flash_record_sha256": _sha256_file(
            premise_paths["flash_record"]
        ),
        "premise_attempt_latch_sha256": _sha256_file(latch_path),
        "premise_campaign_latch_sha256": _sha256_file(campaign_latch_path),
    }
    return SetupEvidence(
        source_run_path=_repo_relative(run_dir),
        confirmed_code=EXPECTED_CODE,
        dac_epoch=EXPECTED_DAC_EPOCH,
        dac_row_sequence=int(row["seq"]),
        command_sequence=commands,
        source_identities=identities,
        snapshot_session=session,
        opening_snapshot_sequence=first_snapshot,
        closing_snapshot_sequence=last_snapshot,
    )


def validate_identity_run(identity_run_dir: Path) -> IdentityEvidence:
    identity_run_dir = identity_run_dir.resolve()
    if (identity_run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise ValueError("post-flash identity capture is still in progress")
    if not (identity_run_dir / "COMPLETE").is_file():
        raise ValueError("post-flash identity run is not marked COMPLETE")
    manifest = load_manifest(identity_run_dir)
    if manifest.is_template or manifest.data.get("stage") != EXPECTED_IDENTITY_STAGE:
        raise ValueError(f"identity run stage must be {EXPECTED_IDENTITY_STAGE}")
    lineage = manifest.data.get("post_flash_identity", {})
    if not isinstance(lineage, dict):
        raise ValueError("identity manifest lacks post-flash lineage")
    flash_ref = lineage.get("flash_record", {})
    usb_ref = lineage.get("usb_board_identity", {})
    if not isinstance(flash_ref, dict) or not isinstance(usb_ref, dict):
        raise ValueError("identity manifest lineage artifacts are malformed")
    flash_relative, flash_path = _safe_run_path(identity_run_dir, flash_ref.get("path"))
    usb_relative, usb_path = _safe_run_path(identity_run_dir, usb_ref.get("path"))
    flash_sha = _sha256_file(flash_path)
    usb_sha = _sha256_file(usb_path)
    if flash_ref.get("sha256") != flash_sha or usb_ref.get("sha256") != usb_sha:
        raise ValueError("identity manifest lineage artifact hash differs")
    flash_record = json.loads(flash_path.read_text(encoding="utf-8"))
    usb_report = json.loads(usb_path.read_text(encoding="utf-8"))
    if (
        usb_report.get("schema_version") != 1
        or usb_report.get("tool") != "cx318_stage4_post_flash_usb_identity_v1"
        or usb_report.get("flash_record_sha256") != flash_sha
        or usb_report.get("identity") != flash_record.get("board_after")
        or usb_report.get("device") != manifest.data.get("host", {}).get("serial_device")
    ):
        raise ValueError("post-flash USB identity report does not bind the flashed board")
    snapshot_path = identity_run_dir / "evidence_manifest.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    failures, warnings = validate_evidence_snapshot(identity_run_dir, manifest)
    if snapshot.get("run_state") != "complete" or failures or warnings:
        raise ValueError(
            "identity evidence snapshot is not a clean complete snapshot: "
            + "; ".join([*failures, *warnings][:6])
        )
    paths = {
        contract: _contract_path(manifest, contract)
        for contract in (
            "pps_snapshots_v1",
            "count_observations_v1",
            "health_v1",
            "dac_steps_v1",
            "environment_v1",
            "active_transactions_v1",
        )
    }
    for contract, path in paths.items():
        result = validate_csv(
            path,
            CsvValidationContext(
                contract=contract,
                known_channels=manifest.known_channels,
                known_domains=manifest.known_domains,
                allow_rp2040_timer0_wrap=True,
            ),
        )
        if not result.ok:
            raise ValueError(f"invalid identity {contract}: {'; '.join(result.errors[:4])}")
    state_path = identity_run_dir / "reports/capture_device_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    expected_state = {
        "capture_active": False,
        "serial_open": False,
        "parser_errors": 0,
        "malformed_utf8": 0,
        "reconnect_count": 0,
        "commands_rejected": 0,
        "commands_sent": 2,
    }
    if any(state.get(key) != value for key, value in expected_state.items()):
        raise ValueError("identity capture state is not clean: " + json.dumps(state, sort_keys=True))
    raw_log = identity_run_dir / "raw/serial.log"
    commands = _host_commands(raw_log)
    if commands != ("CONFIG?", "DUALCORE?"):
        raise ValueError(f"identity command sequence differs: {commands!r}")
    if _read_rows(paths["dac_steps_v1"]) or _raw_records(raw_log, "DAC"):
        raise ValueError("post-flash identity run contains a DAC record")
    if _read_rows(paths["active_transactions_v1"]) or _raw_records(raw_log, "ACT"):
        raise ValueError("post-flash identity run contains an active transaction")
    firmware = manifest.data.get("firmware", {})
    latest = _safe_health_history(_read_rows(paths["health_v1"]))
    required = {
        ("firmware", "git_commit"): firmware.get("git_commit"),
        ("firmware", "source_state"): firmware.get("source_state"),
        ("firmware", "source_hash"): firmware.get("source_sha256"),
        ("firmware", "config_hash"): firmware.get("configuration_sha256"),
        ("build", "profile_id"): "cx318_stage4_nonactuating_preview",
        ("build", "enable_cx318_stage4_preview"): "1",
        ("build", "enable_dac_ad5693r"): "0",
        ("build", "enable_cx317_i_only_preview"): "0",
        ("build", "enable_cx317_bounded_active"): "0",
        ("cx318_preview", "confirmed_static_code"): "0xA828",
        ("cx318_preview", "static_code"): "0xA828",
        ("cx318_preview", "dac_epoch"): "1",
        ("cx318_preview", "actionable"): "false",
        ("cx318_preview", "actuation_authorized"): "false",
        ("cx318_preview", "authorization_consumed"): "false",
        ("dual_core", "partition_fault"): "none",
        ("dual_core", "fail_static"): "false",
        ("dual_core", "telemetry_dropped"): "0",
    }
    mismatches = {
        f"{component}.{key}": {"expected": expected, "actual": latest.get((component, key))}
        for (component, key), expected in required.items()
        if latest.get((component, key)) != expected
    }
    if mismatches:
        raise ValueError("post-flash identity health mismatch: " + json.dumps(mismatches, sort_keys=True))
    sources = {row["source"].strip().lower() for row in _read_rows(paths["environment_v1"])}
    if not {"sht4x", "bmp280"} <= sources:
        raise ValueError(f"identity run lacks both environment streams: {sorted(sources)}")
    session, first_snapshot, last_snapshot = _require_contiguous_snapshots(
        _read_rows(paths["pps_snapshots_v1"])
    )
    identities = {
        "run_manifest_sha256": _sha256_file(manifest.path),
        "evidence_snapshot_sha256": _sha256_file(snapshot_path),
        "raw_serial_sha256": _sha256_file(raw_log),
        "health_sha256": _sha256_file(paths["health_v1"]),
        "dac_steps_sha256": _sha256_file(paths["dac_steps_v1"]),
        "active_transactions_sha256": _sha256_file(paths["active_transactions_v1"]),
    }
    return IdentityEvidence(
        identity_run_path=_repo_relative(identity_run_dir),
        source_identities=identities,
        snapshot_session=session,
        opening_snapshot_sequence=first_snapshot,
        closing_snapshot_sequence=last_snapshot,
        flash_record_path=_repo_relative(flash_path),
        flash_record_sha256=flash_sha,
        usb_identity_sha256=usb_sha,
        board_serial_number=str(usb_report["identity"].get("serial_number", "")),
    )


def validate_static_proof(proof: dict[str, Any]) -> SetupEvidence:
    if proof.get("schema_version") != 1 or proof.get("proof_type") != PROOF_TYPE:
        raise ValueError("static-code proof schema_version/type is not the setup-write contract")
    if proof.get("producer_tool") != PRODUCER_TOOL or proof.get("status") != "passed":
        raise ValueError("static-code proof producer/status is invalid")
    evidence = validate_setup_run(_safe_repo_path(proof.get("source_run_path"))[1])
    identity = validate_identity_run(
        _safe_repo_path(proof.get("post_flash_identity_run_path"))[1]
    )
    artifact_paths = proof.get("artifact_paths", {})
    if not isinstance(artifact_paths, dict):
        raise ValueError("static-code proof artifact_paths is malformed")
    matrix_path = _safe_repo_path(artifact_paths.get("rebound_matrix"))[1]
    build_path = _safe_repo_path(artifact_paths.get("build_manifest"))[1]
    uf2_path = _safe_repo_path(artifact_paths.get("uf2"))[1]
    flash_record_path = _safe_repo_path(artifact_paths.get("flash_record"))[1]
    if _repo_relative(flash_record_path) != identity.flash_record_path:
        raise ValueError("static-code proof flash record differs from the identity-run binding")
    build_binding = validate_build_inputs(
        rebound_matrix_path=matrix_path,
        build_manifest_path=build_path,
        uf2_path=uf2_path,
    )
    flash_record = json.loads(flash_record_path.read_text(encoding="utf-8"))
    validate_flash_record(
        flash_record,
        rebound_matrix_path=matrix_path,
        build_manifest_path=build_path,
        uf2_path=uf2_path,
    )
    expected = {
        "confirmed_code": evidence.confirmed_code,
        "dac_epoch": evidence.dac_epoch,
        "physical_code_status": "confirmed_exact_static_code",
        "continuous_identity_to_flash": True,
        "intervening_dac_writes": 0,
        "intervening_power_losses": 0,
        "source_identities": evidence.source_identities,
        "post_flash_identity_identities": identity.source_identities,
        "artifact_identities": {
            "rebound_matrix_sha256": build_binding["matrix_sha256"],
            "build_manifest_sha256": build_binding["build_manifest_sha256"],
            "uf2_sha256": build_binding["uf2_sha256"],
            "flash_record_sha256": _sha256_file(flash_record_path),
        },
    }
    if any(proof.get(key) != value for key, value in expected.items()):
        raise ValueError("static-code proof fields differ from sealed setup evidence")
    flash = proof.get("flash_continuity", {})
    if not isinstance(flash, dict) or flash.get("basis") != (
        "single captured upload with stable USB board identity followed by a sealed exact-build read-only identity run"
    ) or flash.get("flash_completed_utc") != flash_record.get("completed_utc"):
        raise ValueError("static-code proof lacks captured flash and post-flash lineage")
    return evidence


def create_static_proof(
    *, setup_run_dir: Path, identity_run_dir: Path,
    rebound_matrix_path: Path, build_manifest_path: Path, uf2_path: Path,
    flash_record_path: Path, output_path: Path,
) -> tuple[Path, dict[str, Any]]:
    output_path = output_path.resolve()
    if output_path.exists():
        raise FileExistsError(f"static-code proof already exists: {output_path}")
    evidence = validate_setup_run(setup_run_dir)
    identity = validate_identity_run(identity_run_dir)
    rebound_matrix_path = rebound_matrix_path.resolve()
    build_manifest_path = build_manifest_path.resolve()
    uf2_path = uf2_path.resolve()
    flash_record_path = flash_record_path.resolve()
    if _repo_relative(flash_record_path) != identity.flash_record_path:
        raise ValueError("supplied flash record differs from the identity-run binding")
    build_binding = validate_build_inputs(
        rebound_matrix_path=rebound_matrix_path,
        build_manifest_path=build_manifest_path,
        uf2_path=uf2_path,
    )
    flash_record = json.loads(flash_record_path.read_text(encoding="utf-8"))
    validate_flash_record(
        flash_record,
        rebound_matrix_path=rebound_matrix_path,
        build_manifest_path=build_manifest_path,
        uf2_path=uf2_path,
    )
    proof: dict[str, Any] = {
        "schema_version": 1,
        "proof_type": PROOF_TYPE,
        "producer_tool": PRODUCER_TOOL,
        "status": "passed",
        "created_utc": _utc_now(),
        "confirmed_code": evidence.confirmed_code,
        "confirmed_code_hex": f"0x{evidence.confirmed_code:04X}",
        "dac_epoch": evidence.dac_epoch,
        "physical_code_status": "confirmed_exact_static_code",
        "premise_amendment": "operator_authorized_single_setup_write",
        "source_run_path": evidence.source_run_path,
        "source_identities": evidence.source_identities,
        "setup_evidence": asdict(evidence),
        "post_flash_identity_run_path": identity.identity_run_path,
        "post_flash_identity_identities": identity.source_identities,
        "post_flash_identity_evidence": asdict(identity),
        "artifact_paths": {
            "rebound_matrix": _repo_relative(rebound_matrix_path),
            "build_manifest": _repo_relative(build_manifest_path),
            "uf2": _repo_relative(uf2_path),
            "flash_record": _repo_relative(flash_record_path),
        },
        "artifact_identities": {
            "rebound_matrix_sha256": build_binding["matrix_sha256"],
            "build_manifest_sha256": build_binding["build_manifest_sha256"],
            "uf2_sha256": build_binding["uf2_sha256"],
            "flash_record_sha256": _sha256_file(flash_record_path),
        },
        "continuous_identity_to_flash": True,
        "intervening_dac_writes": 0,
        "intervening_power_losses": 0,
        "flash_continuity": {
            "flash_completed_utc": flash_record["completed_utc"],
            "basis": (
                "single captured upload with stable USB board identity followed by "
                "a sealed exact-build read-only identity run"
            ),
            "board_identity": flash_record["board_after"],
            "claims_boundary": (
                "USB/build lineage is captured; external DAC rail continuity remains an "
                "operational observation rather than an electrical register readback"
            ),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output_path.parent,
        prefix=f".{output_path.name}.", suffix=".tmp", delete=False,
    ) as handle:
        json.dump(proof, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(output_path)
    return output_path, proof


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup-run", type=Path, required=True)
    parser.add_argument("--identity-run", type=Path, required=True)
    parser.add_argument("--rebound-matrix", type=Path, required=True)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--uf2", type=Path, required=True)
    parser.add_argument("--flash-record", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    path, proof = create_static_proof(
        setup_run_dir=args.setup_run,
        identity_run_dir=args.identity_run,
        rebound_matrix_path=args.rebound_matrix,
        build_manifest_path=args.build_manifest,
        uf2_path=args.uf2,
        flash_record_path=args.flash_record,
        output_path=args.output,
    )
    print(json.dumps({"status": proof["status"], "output": str(path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
