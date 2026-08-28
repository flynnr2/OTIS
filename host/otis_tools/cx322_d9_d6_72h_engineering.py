"""Isolated 72-qualified-hour CX322/D9/D6 engineering programme.

The executable surface is intentionally limited to immutable bundle freezing,
no-I/O preflight, exact counter-domain accounting, and a PTY operational-path
rehearsal.  It has no live hardware runner and cannot promote D9 waveform
claims.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path
import pty
import re
import secrets
import select
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Mapping

from .active_control_supervisor import RP2040_TIMER0_TICKS_PER_SECOND
from .capture_segment_rotation import prepare_transition, request_rotation
from .run_paths import default_csv_files
from .serial_commands import (
    send_command_to_fifo,
    send_timestamped_command_to_fifo,
)


ROOT = Path(__file__).resolve().parents[2]
PROGRAMME_DIR = (
    ROOT
    / "docs/60_EXPERIMENTS/"
    "OTIS_D9_OUTPUT_AND_ADAPTIVE_STEERING_INTEGRATION_PROGRAMME"
)
CONTRACT_PATH = (
    PROGRAMME_DIR / "cx322_d9_d6_72h_integrated_engineering_contract_v1.json"
)
PARENT_CONTRACT_PATH = (
    PROGRAMME_DIR / "cx322_d9_d6_integration_engineering_contract_v1.json"
)
MATRIX_PATH = ROOT / "firmware/arduino/firmware_matrix.json"
POLICY_PATH = ROOT / "profiles/discipline/cx322_bounded_hybrid_fact_gathering_v1.json"
TOOL_ID = "otis_cx322_d9_d6_72h_integrated_engineering_v1"
BUNDLE_TYPE = "otis_cx322_d9_d6_72h_integrated_engineering_bundle_v1"
CAPABILITY = "cx322-d9-d6-72h-integrated-engineering-rehearsal"
PTY_CAPTURE_SUBCOMMAND = "_bounded-nonphysical-pty-capture"
PTY_DEVICE_ENV = "OTIS_CX322_D9_D6_72H_PTY_DEVICE"
PTY_RUN_DIR_ENV = "OTIS_CX322_D9_D6_72H_PTY_RUN_DIR"
PTY_TOKEN_ENV = "OTIS_CX322_D9_D6_72H_PTY_TOKEN"


def canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _semantic_identity(value: Mapping[str, Any], field: str) -> str:
    unsigned = {key: item for key, item in value.items() if key != field}
    return canonical_sha256(unsigned)


def file_binding(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_file():
        raise ValueError(f"exact bound file absent or symbolic: {path}")
    payload = resolved.read_bytes()
    return {
        "path": str(resolved),
        "size_bytes": len(payload),
        "sha256": sha256(payload).hexdigest(),
    }


def _validate_binding(binding: Mapping[str, Any], *, label: str) -> Path:
    path = Path(str(binding.get("path", "")))
    expected = file_binding(path)
    if dict(binding) != expected:
        raise ValueError(f"{label} bound-file identity differs")
    return path


def _profiles() -> dict[str, dict[str, Any]]:
    matrix = _read_json(MATRIX_PATH)
    profiles = matrix.get("profiles")
    if not isinstance(profiles, list):
        raise ValueError("firmware profile matrix differs")
    return {str(item["id"]): item for item in profiles}


def _validate_exact_profile(contract: Mapping[str, Any]) -> dict[str, str]:
    firmware = contract["firmware"]
    profiles = _profiles()
    profile = profiles.get(str(firmware["profile_id"]))
    base = profiles.get(str(firmware["base_profile_id"]))
    if profile is None or base is None:
        raise ValueError("required CX322 D9/D6 profile is absent")
    expected = {
        **base["defines"],
        **firmware["required_selector_delta"],
    }
    if profile["defines"] != expected:
        raise ValueError("CX322 D9/D6 profile is not exact base plus selector delta")
    defines = profile["defines"]
    required = {
        "OTIS_GNSS_UART_BAUD": "115200u",
        "OTIS_ENABLE_CX320_ACTIVE_HYBRID": "1",
        "OTIS_ENABLE_CX322_DIRECT_HYBRID": "1",
        "OTIS_ENABLE_FORWARDED_D9_OUTPUT": "1",
        "OTIS_ENABLE_FORWARDED_D6_MONITOR": "1",
        "OTIS_ENABLE_D9_D6_READINESS_PROFILE": "0",
        "OTIS_CX317_ACTIVE_START_CODE": "0xA83Cu",
        "OTIS_CX317_ACTIVE_CORRECTION_LIMIT": "4u",
        "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES": "84u",
        "OTIS_CX317_MINIMUM_APPLIED_CADENCE_S": "1800u",
    }
    if any(defines.get(key) != expected_value for key, expected_value in required.items()):
        raise ValueError("CX322 D9/D6 firmware authority selectors differ")
    return defines


def _validate_parent(contract: Mapping[str, Any]) -> dict[str, Any]:
    parent = _read_json(PARENT_CONTRACT_PATH)
    parent_identity = _semantic_identity(parent, "contract_semantic_sha256")
    if parent.get("contract_semantic_sha256") != parent_identity:
        raise ValueError("parent engineering contract semantic identity differs")
    expected = contract["semantic_parent"]
    if (
        parent.get("contract_id") != expected["contract_id"]
        or parent_identity != expected["contract_semantic_sha256"]
        or PARENT_CONTRACT_PATH.name != expected["contract_file"]
    ):
        raise ValueError("72h contract parent binding differs")
    return parent


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    contract = _read_json(path)
    if contract.get("contract_semantic_sha256") != _semantic_identity(
        contract, "contract_semantic_sha256"
    ):
        raise ValueError("72h engineering contract semantic identity differs")
    if contract.get("contract_id") != (
        "OTIS_CX322_D9_D6_72H_INTEGRATED_ENGINEERING_CONTRACT_V1"
    ):
        raise ValueError("72h engineering contract id differs")
    _validate_parent(contract)
    _validate_exact_profile(contract)

    timing = contract["time"]
    if timing != {
        "counter_domain": "rp2040_timer0",
        "nominal_counter_hz": RP2040_TIMER0_TICKS_PER_SECOND,
        "qualified_duration_s": 259_200,
        "qualification_deadline_s": 5_400,
        "absolute_wall_limit_s": 280_800,
        "milestone_interval_qualified_s": 21_600,
        "milestones_qualified_s": [21_600 * number for number in range(1, 13)],
        "qualification_origin": (
            "first_complete_fresh_selected_600_estimate_after_exact_setup_code_"
            "epoch_establishment_and_common_D14_D8_health"
        ),
    }:
        raise ValueError("72h exact counter-domain duration differs")
    if contract["serial"] != {
        "baud": 115200,
        "selection": (
            "capture_device_--auto-detect_fresh_for_every_capture_and_"
            "reenumeration"
        ),
        "required_candidate_count": 1,
        "stored_device_path_permitted": False,
        "stored_board_serial_permitted": False,
        "sole_serial_owner_required": True,
        "independent_abort_delivery_required": True,
    }:
        raise ValueError("72h serial auto-detection/baud contract differs")
    envelope = contract["controller_envelope"]
    expected_envelope = {
        "automatic_application_limit": 4,
        "automatic_cumulative_movement_limit_codes": 84,
        "automatic_step_limit_codes": 21,
        "total_dac_write_limit_including_setup": 5,
        "minimum_application_cadence_s": 1800,
        "maximum_outstanding_transactions": 1,
        "dac_min_code": 0xA800,
        "dac_min_code_hex": "0xA800",
        "dac_max_code": 0xAB00,
        "dac_max_code_hex": "0xAB00",
        "deliberate_reversal_challenge_permitted": False,
        "automatic_retry_permitted": False,
        "restoration_write_permitted": False,
        "close_new_application_admission_before_endpoint_s": 1500,
    }
    if envelope != expected_envelope:
        raise ValueError("72h controller/application envelope differs")
    start = contract["starting_dac"]
    if (
        start["setup_code"] != 0xA83C
        or start["setup_write_limit"] != 1
        or start["setup_counts_as_automatic_application"] is not False
        or start["required_established_epoch"] != 1
        or start["retry_permitted"] is not False
        or start["restoration_permitted"] is not False
    ):
        raise ValueError("72h setup-establishment boundary differs")
    if contract["timing_truth"] != {
        "reference_input": "D14",
        "oscillator_and_control_input": "D8",
        "D14_D8_continuity_required": True,
        "D10_authority_changed": False,
    }:
        raise ValueError("D14/D8 timing-truth boundary differs")
    d9 = contract["d9"]
    if (
        d9["required_state"] != "configured_10mhz_forwarded_unqualified"
        or d9["source"] != "D8_GPIO20_GPIN0"
        or d9["destination"] != "D9_GPIO21_GPOUT0"
        or d9["integer_divider"] != 1
        or d9["fractional_divider"] != 0
        or d9["readback_exact_required"] is not True
        or d9["measurement_authority"] is not False
        or d9["control_authority"] is not False
    ):
        raise ValueError("D9 digital configuration/readback boundary differs")
    d6 = contract["d6"]
    if (
        d6["allowed_statuses"] != ["present", "local_degraded"]
        or d6["measurement_authority"] is not False
        or d6["control_authority"] is not False
    ):
        raise ValueError("D6 zero-authority boundary differs")
    claim = contract["claim_boundary"]
    if (
        claim["programme_class"] != "engineering_non_promotional"
        or claim["waveform_evidence_status"] != "unresolved_oscilloscope_deferred"
        or claim["prompt02_waveform_gate_satisfied"] is not False
        or claim["prompt02_promotion_permitted"] is not False
    ):
        raise ValueError("waveform/non-promotional claim boundary differs")
    return contract


def _configuration(build_manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    provenance = build_manifest.get("provenance")
    if isinstance(provenance, Mapping) and isinstance(
        provenance.get("configuration"), Mapping
    ):
        return provenance["configuration"]
    configuration = build_manifest.get("configuration")
    if isinstance(configuration, Mapping):
        return configuration
    raise ValueError("build manifest lacks exact configuration")


def _validate_build_manifest(
    path: Path, contract: Mapping[str, Any]
) -> dict[str, Any]:
    build = _read_json(path)
    configuration = _configuration(build)
    expected_defines = _validate_exact_profile(contract)
    if (
        configuration.get("profile_id") != contract["firmware"]["profile_id"]
        or configuration.get("defines") != expected_defines
    ):
        raise ValueError("build is not the exact CX322 D9/D6 engineering profile")
    return build


def freeze_bundle(
    *,
    build_manifest_path: Path,
    source_revision: str,
    contract_path: Path = CONTRACT_PATH,
) -> dict[str, object]:
    """Freeze the exact no-authority input bundle; this performs no I/O."""

    if not re.fullmatch(r"[0-9a-f]{40}", source_revision):
        raise ValueError("source revision must be one exact lowercase Git SHA-1")
    contract = load_contract(contract_path)
    _validate_build_manifest(build_manifest_path, contract)
    bindings = {
        "contract": file_binding(contract_path),
        "parent_engineering_contract": file_binding(PARENT_CONTRACT_PATH),
        "firmware_matrix": file_binding(MATRIX_PATH),
        "cx322_policy": file_binding(POLICY_PATH),
        "firmware_build_manifest": file_binding(build_manifest_path),
        "programme_tool": file_binding(Path(__file__)),
        "capture_tool": file_binding(ROOT / "host/otis_tools/capture_device.py"),
        "rotation_tool": file_binding(
            ROOT / "host/otis_tools/capture_segment_rotation.py"
        ),
        "command_tool": file_binding(ROOT / "host/otis_tools/serial_commands.py"),
    }
    unsigned: dict[str, object] = {
        "schema_version": 1,
        "bundle_type": BUNDLE_TYPE,
        "tool": TOOL_ID,
        "effective": False,
        "physical_authority": False,
        "source_revision": source_revision,
        "contract_semantic_sha256": contract["contract_semantic_sha256"],
        "profile_id": contract["firmware"]["profile_id"],
        "serial": contract["serial"],
        "time": contract["time"],
        "starting_dac": contract["starting_dac"],
        "controller_envelope": contract["controller_envelope"],
        "timing_truth": contract["timing_truth"],
        "d9": contract["d9"],
        "d6": contract["d6"],
        "terminals": contract["terminals"],
        "claim_boundary": contract["claim_boundary"],
        "bindings": bindings,
        "remaining_live_components": [
            "authorized_live_runner",
            "unattended_transition_monitor",
            "72h_scientific_analyzer",
            "immutable_finalizer_sealer_and_evidence_registration",
        ],
    }
    return {**unsigned, "bundle_sha256": canonical_sha256(unsigned)}


def validate_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(bundle)
    unsigned = {key: item for key, item in value.items() if key != "bundle_sha256"}
    if value.get("bundle_sha256") != canonical_sha256(unsigned):
        raise ValueError("72h bundle semantic identity differs")
    if (
        value.get("bundle_type") != BUNDLE_TYPE
        or value.get("effective") is not False
        or value.get("physical_authority") is not False
    ):
        raise ValueError("72h bundle type or physical-authority boundary differs")
    bindings = value.get("bindings")
    if not isinstance(bindings, Mapping):
        raise ValueError("72h bundle bindings absent")
    for label in (
        "contract",
        "parent_engineering_contract",
        "firmware_matrix",
        "cx322_policy",
        "firmware_build_manifest",
        "programme_tool",
        "capture_tool",
        "rotation_tool",
        "command_tool",
    ):
        if not isinstance(bindings.get(label), Mapping):
            raise ValueError(f"{label} binding absent")
        _validate_binding(bindings[label], label=label)
    contract_path = Path(str(bindings["contract"]["path"]))
    contract = load_contract(contract_path)
    _validate_build_manifest(
        Path(str(bindings["firmware_build_manifest"]["path"])), contract
    )
    copied = (
        "serial",
        "time",
        "starting_dac",
        "controller_envelope",
        "timing_truth",
        "d9",
        "d6",
        "terminals",
        "claim_boundary",
    )
    if (
        value.get("contract_semantic_sha256")
        != contract["contract_semantic_sha256"]
        or value.get("profile_id") != contract["firmware"]["profile_id"]
        or any(value.get(key) != contract[key] for key in copied)
    ):
        raise ValueError("72h bundle contract projection differs")
    return value


@dataclass
class Engineering72hSupervisor:
    """Exact integer-counter accounting for the isolated engineering run."""

    contract: Mapping[str, Any]
    run_start_ticks: int
    setup_establishments: int = 0
    current_code: int | None = None
    current_epoch: int = 0
    armed_ticks: int | None = None
    last_observation_ticks: int | None = None
    qualified_ticks: int = 0
    automatic_applications: int = 0
    cumulative_movement_codes: int = 0
    last_application_ticks: int | None = None
    milestones: list[int] = field(default_factory=list)
    d6_local_degraded_intervals: int = 0
    terminal: str | None = None

    @property
    def timer_hz(self) -> int:
        return int(self.contract["time"]["nominal_counter_hz"])

    def _stop(self, terminal_key: str) -> None:
        if self.terminal is None:
            self.terminal = str(self.contract["terminals"][terminal_key])

    def record_setup_establishment(
        self,
        *,
        applied_code: int,
        applied_epoch: int,
        application_ticks: int,
        pre_setup_physical_code_readable: bool,
        dac_query_claimed_physical_readback: bool,
        acknowledgement_exact: bool,
        first_dependent_consumer_exact: bool,
    ) -> None:
        start = self.contract["starting_dac"]
        invalid = (
            self.terminal is not None
            or self.armed_ticks is not None
            or self.setup_establishments != 0
            or application_ticks < self.run_start_ticks
            or pre_setup_physical_code_readable
            or dac_query_claimed_physical_readback
            or applied_code != int(start["setup_code"])
            or applied_epoch != int(start["required_established_epoch"])
            or not acknowledgement_exact
            or not first_dependent_consumer_exact
        )
        if invalid:
            self._stop("controller_or_transaction_fault")
            return
        self.setup_establishments = 1
        self.current_code = applied_code
        self.current_epoch = applied_epoch

    def arm(
        self,
        *,
        frontier_ticks: int,
        fresh_auto_detect: bool,
        candidate_count: int,
        baud: int,
        sole_serial_owner: bool,
        independent_abort_ready: bool,
        d9_state: str,
        d9_identity_exact: bool,
        d9_readback_exact: bool,
        d14_d8_healthy: bool,
        gnss_metadata_fresh_same_receiver: bool,
        d6_status: str,
        no_outstanding_transaction: bool,
    ) -> None:
        if self.terminal is not None or self.armed_ticks is not None:
            raise ValueError("72h programme cannot be armed in the current state")
        deadline = int(self.contract["time"]["qualification_deadline_s"])
        if frontier_ticks - self.run_start_ticks > deadline * self.timer_hz:
            self._stop("right_censored_incomplete")
            raise ValueError("72h qualification deadline expired before arming")
        serial = self.contract["serial"]
        d9 = self.contract["d9"]
        if (
            not fresh_auto_detect
            or candidate_count != int(serial["required_candidate_count"])
            or baud != int(serial["baud"])
            or not sole_serial_owner
            or not independent_abort_ready
            or self.setup_establishments != 1
            or self.current_code != int(self.contract["starting_dac"]["setup_code"])
            or self.current_epoch
            != int(self.contract["starting_dac"]["required_established_epoch"])
            or not gnss_metadata_fresh_same_receiver
            or d6_status not in self.contract["d6"]["allowed_statuses"]
            or not no_outstanding_transaction
        ):
            self._stop("identity_or_evidence_fault")
            raise ValueError("72h entry identity or authority gate differs")
        if not d14_d8_healthy:
            self._stop("authoritative_capture_fault")
            raise ValueError("D14/D8 entry truth is not healthy")
        if (
            d9_state != d9["required_state"]
            or not d9_identity_exact
            or not d9_readback_exact
        ):
            self._stop("d9_digital_fault")
            raise ValueError("D9 exact configuration/readback entry gate differs")
        self.armed_ticks = frontier_ticks
        self.last_observation_ticks = frontier_ticks

    def record_automatic_application(
        self,
        *,
        requested_from_code: int,
        applied_code: int,
        applied_epoch: int,
        application_ticks: int,
        outstanding_transactions_before_request: int,
        acknowledgement_exact: bool,
        first_dependent_consumer_exact: bool,
        response_complete: bool,
    ) -> None:
        envelope = self.contract["controller_envelope"]
        if self.armed_ticks is None or self.current_code is None:
            self._stop("controller_or_transaction_fault")
            return
        delta = applied_code - requested_from_code
        preceding_ticks = (
            self.last_application_ticks
            if self.last_application_ticks is not None
            else self.armed_ticks
        )
        remaining_qualified_ticks = (
            int(self.contract["time"]["qualified_duration_s"]) * self.timer_hz
            - self.qualified_ticks
        )
        invalid = (
            self.terminal is not None
            or requested_from_code != self.current_code
            or not 1 <= abs(delta) <= int(envelope["automatic_step_limit_codes"])
            or not int(envelope["dac_min_code"])
            <= applied_code
            <= int(envelope["dac_max_code"])
            or applied_epoch != self.current_epoch + 1
            or application_ticks - preceding_ticks
            < int(envelope["minimum_application_cadence_s"]) * self.timer_hz
            or outstanding_transactions_before_request != 0
            or not acknowledgement_exact
            or not first_dependent_consumer_exact
            or not response_complete
            or remaining_qualified_ticks
            <= int(envelope["close_new_application_admission_before_endpoint_s"])
            * self.timer_hz
        )
        if invalid:
            self._stop("controller_or_transaction_fault")
            return
        next_applications = self.automatic_applications + 1
        next_movement = self.cumulative_movement_codes + abs(delta)
        total_writes = self.setup_establishments + next_applications
        if (
            next_applications > int(envelope["automatic_application_limit"])
            or next_movement
            > int(envelope["automatic_cumulative_movement_limit_codes"])
            or total_writes > int(envelope["total_dac_write_limit_including_setup"])
        ):
            self._stop("controller_or_transaction_fault")
            return
        self.automatic_applications = next_applications
        self.cumulative_movement_codes = next_movement
        self.last_application_ticks = application_ticks
        self.current_code = applied_code
        self.current_epoch = applied_epoch

    def observe_interval(
        self,
        *,
        opening_ticks: int,
        closing_ticks: int,
        measurement_qualified: bool,
        d14_d8_healthy: bool,
        d9_configuration_and_readback_exact: bool,
        d6_status: str,
    ) -> None:
        if self.terminal is not None:
            return
        if self.armed_ticks is None or self.last_observation_ticks is None:
            self._stop("identity_or_evidence_fault")
            return
        if (
            opening_ticks != self.last_observation_ticks
            or closing_ticks <= opening_ticks
            or d6_status not in self.contract["d6"]["allowed_statuses"]
        ):
            self._stop("identity_or_evidence_fault")
            return
        if closing_ticks - self.run_start_ticks > (
            int(self.contract["time"]["absolute_wall_limit_s"]) * self.timer_hz
        ):
            self._stop("right_censored_incomplete")
            return
        if not d14_d8_healthy:
            self._stop("authoritative_capture_fault")
            return
        if not d9_configuration_and_readback_exact:
            self._stop("d9_digital_fault")
            return
        self.last_observation_ticks = closing_ticks
        if d6_status == "local_degraded":
            self.d6_local_degraded_intervals += 1
        if not measurement_qualified:
            return
        target_ticks = int(self.contract["time"]["qualified_duration_s"]) * self.timer_hz
        self.qualified_ticks = min(
            target_ticks,
            self.qualified_ticks + closing_ticks - opening_ticks,
        )
        for milestone in self.contract["time"]["milestones_qualified_s"]:
            if (
                self.qualified_ticks >= int(milestone) * self.timer_hz
                and int(milestone) not in self.milestones
            ):
                self.milestones.append(int(milestone))
        if self.qualified_ticks == target_ticks:
            self._stop("qualified_complete")

    def operator_abort(self) -> None:
        key = (
            "pre_setup_no_write_abort"
            if self.setup_establishments == 0 and self.automatic_applications == 0
            else "operator_abort"
        )
        self._stop(key)

    def summary(self) -> dict[str, object]:
        return {
            "terminal": self.terminal,
            "setup_establishments": self.setup_establishments,
            "automatic_applications": self.automatic_applications,
            "total_dac_writes": self.setup_establishments
            + self.automatic_applications,
            "cumulative_automatic_movement_codes": self.cumulative_movement_codes,
            "qualified_ticks": self.qualified_ticks,
            "qualified_seconds": self.qualified_ticks // self.timer_hz,
            "milestones_qualified_s": list(self.milestones),
            "d6_local_degraded_intervals": self.d6_local_degraded_intervals,
            "last_confirmed_code": self.current_code,
            "last_confirmed_epoch": self.current_epoch,
        }


def no_io_preflight(bundle: Mapping[str, Any]) -> dict[str, object]:
    checked = validate_bundle(bundle)
    return {
        "tool": TOOL_ID,
        "status": "passed",
        "hardware_operations": False,
        "bundle_sha256": checked["bundle_sha256"],
        "profile_id": checked["profile_id"],
        "serial_selection": checked["serial"]["selection"],
        "baud": checked["serial"]["baud"],
        "qualified_duration_s": checked["time"]["qualified_duration_s"],
        "milestones_qualified_s": checked["time"]["milestones_qualified_s"],
        "terminals": checked["terminals"],
        "waveform_evidence_status": checked["claim_boundary"][
            "waveform_evidence_status"
        ],
        "promotion_permitted": False,
        "remaining_live_components": checked["remaining_live_components"],
    }


def _write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def _wait_for(path: Path, *, timeout_s: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.025)
    raise TimeoutError(f"timed out waiting for {path}")


def _read_until(master: int, expected: bytes, *, timeout_s: float = 5.0) -> bytes:
    deadline = time.monotonic() + timeout_s
    observed = b""
    while time.monotonic() < deadline:
        readable, _, _ = select.select([master], [], [], 0.05)
        if readable:
            observed += os.read(master, 4096)
            if expected in observed:
                return observed
    raise TimeoutError(f"PTY did not receive {expected!r}; observed={observed!r}")


def _status(sequence: int, component: str, key: str, value: str) -> bytes:
    return (
        f"STS,1,{sequence},{sequence * RP2040_TIMER0_TICKS_PER_SECOND},"
        "rp2040_timer0,"
        f"{component},{key},{value},INFO,0\r\n"
    ).encode("ascii")


def _bounded_pty_capture_process(argv: list[str]) -> int:
    """Run capture with one explicit nonphysical PTY owner-check seam.

    A PTY necessarily remains open in this parent rehearsal process so it can
    act as the deterministic firmware fixture.  That makes lsof correctly see
    two owners.  The child may bypass only that rotation-time lsof assertion,
    and only when a fresh secret capability, exact device, exact run directory,
    non-actuating rehearsal manifest, and character-device boundary all match.
    The production CaptureDeviceRunner implementation remains unchanged.
    """

    from . import capture_device

    expected_device = os.environ.pop(PTY_DEVICE_ENV, "")
    expected_run_dir = os.environ.pop(PTY_RUN_DIR_ENV, "")
    token = os.environ.pop(PTY_TOKEN_ENV, "")
    if (
        not expected_device
        or not expected_run_dir
        or not re.fullmatch(r"[0-9a-f]{64}", token)
    ):
        raise ValueError("bounded PTY capture seam lacks exact process authority")
    expected_capability = f"{CAPABILITY}:{token}"
    expected_run = Path(expected_run_dir).resolve()
    original = capture_device.CaptureDeviceRunner._verify_sole_serial_owner

    def fixture_owner_check(
        runner: capture_device.CaptureDeviceRunner,
    ) -> dict[str, object]:
        device = Path(runner.config.device)
        manifest_path = runner.current_run_dir / "run_manifest.json"
        try:
            manifest = _read_json(manifest_path)
            is_character_device = stat.S_ISCHR(device.stat().st_mode)
        except (OSError, ValueError, json.JSONDecodeError):
            manifest = {}
            is_character_device = False
        exact_fixture = (
            runner.config.device == expected_device
            and runner.current_run_dir == expected_run
            and runner.config.segment_capability == expected_capability
            and is_character_device
            and manifest.get("stage")
            == "CX322_D9_D6_72H_INTEGRATED_ENGINEERING_REHEARSAL"
            and manifest.get("actionable") is False
            and manifest.get("actuation_authorized") is False
        )
        if not exact_fixture:
            return original(runner)
        return {
            "performed": False,
            "reason": "bounded_explicit_nonphysical_PTY_fixture_owner_seam",
            "owner_pids": [os.getpid()],
            "production_lsof_check_unchanged": True,
            "fixture_capability_sha256": sha256(
                expected_capability.encode("utf-8")
            ).hexdigest(),
        }

    capture_device.CaptureDeviceRunner._verify_sole_serial_owner = (
        fixture_owner_check
    )
    original_argv = sys.argv
    sys.argv = ["host.otis_tools.capture_device", *argv]
    try:
        capture_device.main()
        return 0
    finally:
        sys.argv = original_argv
        capture_device.CaptureDeviceRunner._verify_sole_serial_owner = original


def _run_accelerated_counter_rehearsal(
    contract: Mapping[str, Any], *, run_start_ticks: int = 0
) -> Engineering72hSupervisor:
    hz = int(contract["time"]["nominal_counter_hz"])
    supervisor = Engineering72hSupervisor(contract, run_start_ticks)
    supervisor.record_setup_establishment(
        applied_code=0xA83C,
        applied_epoch=1,
        application_ticks=100,
        pre_setup_physical_code_readable=False,
        dac_query_claimed_physical_readback=False,
        acknowledgement_exact=True,
        first_dependent_consumer_exact=True,
    )
    frontier = 200
    supervisor.arm(
        frontier_ticks=frontier,
        fresh_auto_detect=True,
        candidate_count=1,
        baud=115200,
        sole_serial_owner=True,
        independent_abort_ready=True,
        d9_state="configured_10mhz_forwarded_unqualified",
        d9_identity_exact=True,
        d9_readback_exact=True,
        d14_d8_healthy=True,
        gnss_metadata_fresh_same_receiver=True,
        d6_status="present",
        no_outstanding_transaction=True,
    )
    code = 0xA83C
    epoch = 1
    for number, delta in enumerate((21, -21, 21, -21), start=1):
        next_code = code + delta
        supervisor.record_automatic_application(
            requested_from_code=code,
            applied_code=next_code,
            applied_epoch=epoch + 1,
            application_ticks=frontier + number * 1800 * hz,
            outstanding_transactions_before_request=0,
            acknowledgement_exact=True,
            first_dependent_consumer_exact=True,
            response_complete=True,
        )
        code = next_code
        epoch += 1
    opening = frontier
    for number in range(1, 13):
        closing = frontier + number * 21_600 * hz
        supervisor.observe_interval(
            opening_ticks=opening,
            closing_ticks=closing,
            measurement_qualified=True,
            d14_d8_healthy=True,
            d9_configuration_and_readback_exact=True,
            d6_status="local_degraded" if number == 2 else "present",
        )
        opening = closing
    return supervisor


def pty_operational_rehearsal(
    *, bundle: Mapping[str, Any], output_dir: Path
) -> dict[str, object]:
    """Exercise production capture/FIFOs/rotation with accelerated evidence.

    The PTY supplies a deterministic firmware transcript.  It proves host
    command, capture, abort, and counter-contract behavior only, never a
    physical RP2040, D9 waveform, D6 loopback, or DAC response.
    """

    checked = validate_bundle(bundle)
    contract = load_contract(Path(str(checked["bindings"]["contract"]["path"])))
    output_dir.mkdir(parents=True, exist_ok=False)
    run_dir = output_dir / "run"
    run_dir.mkdir()
    transition_dir = output_dir / "transition"
    carrier_dir = output_dir / "carrier"
    master, slave = pty.openpty()
    device = os.ttyname(slave)
    os.close(slave)
    files = default_csv_files()
    _write_new_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": 1,
            "template": False,
            "run_id": "cx322_d9_d6_72h_engineering_pty",
            "stage": "CX322_D9_D6_72H_INTEGRATED_ENGINEERING_REHEARSAL",
            "profile_id": checked["profile_id"],
            "bundle_sha256": checked["bundle_sha256"],
            "actionable": False,
            "actuation_authorized": False,
            "host": {
                "serial_device": device,
                "baud": 115200,
                "sole_serial_owner": True,
                "capture_tool": "host.otis_tools.capture_device",
            },
            "domains": [
                {
                    "name": "rp2040_timer0",
                    "nominal_hz": RP2040_TIMER0_TICKS_PER_SECOND,
                }
            ],
            "channels": [
                {"channel_id": 1, "role": "authoritative_d14_reference"},
                {"channel_id": 2, "role": "authoritative_d8_count"},
                {
                    "channel_id": 3,
                    "role": "diagnostic_d6_forwarded_d9_monitor",
                    "zero_authority": True,
                },
            ],
            "contracts": {entry["contract"]: 1 for entry in files},
            "files": files,
            "evidence_artifacts": [],
        },
    )
    normal = run_dir / "control/normal_commands.fifo"
    emergency = run_dir / "control/emergency_abort.fifo"
    fixture_token = secrets.token_hex(32)
    fixture_capability = f"{CAPABILITY}:{fixture_token}"
    capture_environment = dict(os.environ)
    capture_environment.update(
        {
            PTY_DEVICE_ENV: device,
            PTY_RUN_DIR_ENV: str(run_dir.resolve()),
            PTY_TOKEN_ENV: fixture_token,
        }
    )
    capture = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "host.otis_tools.cx322_d9_d6_72h_engineering",
            PTY_CAPTURE_SUBCOMMAND,
            "--device",
            device,
            "--baud",
            "115200",
            "--run-dir",
            str(run_dir),
            "--duration-s",
            "30",
            "--command-fifo",
            str(normal),
            "--emergency-command-fifo",
            str(emergency),
            "--normal-command-max-age-s",
            "2",
            "--segment-control-dir",
            str(carrier_dir),
            "--segment-capability",
            fixture_capability,
        ],
        cwd=ROOT,
        env=capture_environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output = ""
    commands: list[str] = []
    configuration_sha256 = "a" * 64
    setup = (
        "ACTIVE SETUP 1 1 1 1000 1 0xA83C 1 " + configuration_sha256
    )
    expected_commands = [
        "CONFIG?",
        "DUALCORE?",
        "DAC?",
        "ACTIVE?",
        setup,
        "ACTIVE ARM 1 2 2000",
    ]
    try:
        _wait_for(normal)
        for command in expected_commands:
            send_timestamped_command_to_fifo(normal, command)
            _read_until(master, (command + "\n").encode("ascii"))
            commands.append(command)
        transcript = b"".join(
            (
                _status(1, "build", "profile_id", checked["profile_id"]),
                _status(2, "serial", "baud", "115200"),
                _status(
                    3,
                    "forwarded_clock_output",
                    "state",
                    "configured_10mhz_forwarded_unqualified",
                ),
                _status(4, "forwarded_clock_output", "readback_valid", "true"),
                _status(5, "d14_reference", "state", "healthy"),
                _status(6, "d8_capture", "state", "healthy"),
                _status(7, "forwarded_clock_monitor", "state", "local_degraded"),
                _status(8, "d14_reference", "state", "healthy"),
                _status(9, "d8_capture", "state", "healthy"),
                _status(10, "cx317_setup", "applied_code", str(0xA83C)),
                _status(11, "cx317_setup", "dac_epoch", "1"),
                _status(12, "cx317_setup", "first_consumer_exact", "true"),
            )
        )
        os.write(master, transcript)
        send_command_to_fifo(emergency, "ACTIVE ABORT")
        _read_until(master, b"ACTIVE ABORT\n")
        commands.append("ACTIVE ABORT")
        time.sleep(0.1)
        prepare_transition(run_dir / "run_manifest.json", transition_dir)
        rotation = request_rotation(
            control_dir=carrier_dir,
            capability=fixture_capability,
            to_run=transition_dir,
            mode="transition",
            operation_id="cx322-d9-d6-72h-engineering-pty",
        )
    finally:
        if capture.poll() is None:
            capture.send_signal(signal.SIGINT)
        try:
            output, _ = capture.communicate(timeout=10)
        finally:
            os.close(master)
    if capture.returncode != 0:
        raise RuntimeError(f"capture rehearsal failed: {output[-1200:]}")
    rotation_owner_check = _read_json(
        run_dir / "reports/capture_segment_closure_v1.json"
    )["serial_owner_check"]
    if rotation_owner_check != {
        "performed": False,
        "reason": "bounded_explicit_nonphysical_PTY_fixture_owner_seam",
        "owner_pids": [capture.pid],
        "production_lsof_check_unchanged": True,
        "fixture_capability_sha256": sha256(
            fixture_capability.encode("utf-8")
        ).hexdigest(),
    }:
        raise RuntimeError("PTY owner-check seam escaped its exact boundary")

    supervisor = _run_accelerated_counter_rehearsal(contract)
    summary = supervisor.summary()
    if summary["terminal"] != contract["terminals"]["qualified_complete"]:
        raise RuntimeError("accelerated 72h counter rehearsal did not complete")
    report: dict[str, object] = {
        "tool": TOOL_ID,
        "status": "passed",
        "hardware_operations": False,
        "mode": "PTY_fixture_with_accelerated_rp2040_timer0_evidence",
        "bundle_sha256": checked["bundle_sha256"],
        "profile_id": checked["profile_id"],
        "baud": 115200,
        "serial_selection": "PTY_fixture_not_auto_detect",
        "commands_observed_in_order": commands,
        "priority_abort_delivered": True,
        "rotation": rotation,
        "rotation_owner_check": rotation_owner_check,
        "accelerated_counter_result": summary,
        "terminal_derived_from_contract": summary["terminal"],
        "d6_local_degradation_did_not_change_terminal": True,
        "waveform_evidence_status": checked["claim_boundary"][
            "waveform_evidence_status"
        ],
        "promotion_permitted": False,
        "real_boundaries_exercised": [
            "production_capture_device_process",
            "normal_timestamped_command_fifo",
            "independent_priority_abort_fifo",
            "single_capture_process_retained_serial_handle_across_rotation",
            "same_owner_logical_rotation",
            "contract_validator",
            "exact_integer_counter_duration_and_milestones",
            "setup_plus_four_automatic_application_accounting",
        ],
        "not_proved": [
            "fresh_USB_auto_detect",
            "production_lsof_sole_serial_owner_check",
            "firmware_binary_runtime_identity",
            "physical_D14_D8_capture",
            "physical_D9_forwarding_waveform_frequency_or_load",
            "physical_D6_loopback",
            "physical_DAC_setup_application_or_oscillator_response",
            "72h_live_host_monitor_analyzer_seal_or_registration",
        ],
    }
    _write_new_json(output_dir / "reports/rehearsal.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == [PTY_CAPTURE_SUBCOMMAND]:
        return _bounded_pty_capture_process(arguments[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--build-manifest", type=Path, required=True)
    freeze.add_argument("--source-revision", required=True)
    freeze.add_argument("--output", type=Path, required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--bundle", type=Path, required=True)
    rehearse = commands.add_parser("rehearse")
    rehearse.add_argument("--bundle", type=Path, required=True)
    rehearse.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(arguments)
    if args.command == "freeze":
        result = freeze_bundle(
            build_manifest_path=args.build_manifest,
            source_revision=args.source_revision,
        )
        _write_new_json(args.output, result)
    elif args.command == "preflight":
        result = no_io_preflight(_read_json(args.bundle))
    else:
        result = pty_operational_rehearsal(
            bundle=_read_json(args.bundle), output_dir=args.output_dir
        )
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
