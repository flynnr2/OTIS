"""Frozen engineering-only D9/D6 frequency-control endurance programme.

This module intentionally cannot produce a Prompt 02 waveform or soak-pass
claim.  It provides the exact counter-domain accounting and process seams for
a later authorized digital/non-interference endurance acquisition.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import pty
import select
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from typing import Any, Callable, Mapping

from .abort_transport import AbortFifo
from .board_identity import read_board_identity
from .active_control_supervisor import (
    RP2040_TIMER0_TICKS_PER_SECOND,
    _parse_utc_epoch,
)
from .adaptive_steering_offline import RequestReleaseState
from .active_transactions import (
    ACTIVE_CSV,
    CampaignSpec,
    SUPERVISOR_EVENTS,
    SUPERVISOR_STATE,
    validate_transaction_history,
)
from .bounded_tight_deadband_prewrite_contract import (
    PrewriteReadiness,
    canonical_prewrite_fixture,
    evaluate_prewrite_readiness as evaluate_setup_prewrite_readiness,
)
from .capture_device import _detect_single_device
from .capture_runtime_checks import _capture_state_ready, _markers, _serial_owner_pids
from .capture_segment_rotation import prepare_transition, request_rotation
from .contracts import (
    ACTIVE_TRANSACTION_V1_FIELDS,
    ACTIVE_TRANSACTION_V2_FIELDS,
    CONTRACT_FIELDS,
    CONTRACT_SCHEMA_VERSIONS,
)
from .cx322_non_effective_operational_semantics import (
    Cx322OperationalState,
    OperationalMode,
    metadata_loss,
)
from .evidence import create_evidence_snapshot
from .evidence_index import register_package
from .frequency_control_supervisor import (
    CORRECTION_RESPONSE_RESERVE_S,
    FrequencyControlSupervisor,
    TightDeadbandLeg,
)
from .gnss_operational_baud_policy import (
    GNSS_OPERATIONAL_BAUD_POLICY,
    GNSS_OPERATIONAL_REQUIRED_DEFINES,
    gnss_operational_runtime_invariant_errors,
    require_exact_gnss_operational_baud_policy,
)
from .no_write_qualification_supervisor import load_no_write_qualification_spec
from .measurement_replay import (
    COUNT_INVALID_FLAGS,
    EXPECTED_BACKEND as EXPECTED_D8_SNAPSHOT_BACKEND,
    REFERENCE_INVALID_FLAGS,
)
from .run_paths import (
    ACTIVE_TRANSACTIONS_V2_CSV,
    CONTROL_PREVIEWS_CSV,
    COUNT_OBSERVATIONS_CSV,
    ESTIMATES_CSV,
    PPS_SNAPSHOTS_CSV,
    RAW_EVENTS_CSV,
    exact_active_timing_csv_files,
)
from .serial_commands import send_command_to_fifo, send_timestamped_command_to_fifo
from .time_domains import forward_progress


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "docs/60_EXPERIMENTS/OTIS_D9_OUTPUT_AND_ADAPTIVE_STEERING_INTEGRATION_PROGRAMME/d9_d6_frequency_only_digital_endurance_contract_v1.json"
TOOL_ID = "otis_d9_d6_frequency_only_digital_endurance_v1"
# ``rp2040_timer0`` is the emitted 16 MHz capture counter.  All endurance
# thresholds remain in this domain from record ingestion through analysis.
TIMER_HZ = RP2040_TIMER0_TICKS_PER_SECOND
LIVE_STAGE = "OTIS_D9_D6_FREQUENCY_ONLY_DIGITAL_ENDURANCE_LIVE"
EVIDENCE_EPOCH = "OTIS_D9_D6_FREQUENCY_ONLY_DIGITAL_ENDURANCE_EPOCH_1"
CAPABILITY = "d9-d6-frequency-only-digital-endurance-v1"
EXPECTED_UPLOAD_FQBN = "rp2040:rp2040:arduino_nano_connect:freq=133"
ANALYSIS_PATH = Path("reports/d9_d6_frequency_only_digital_endurance_analysis_v1.json")
SEAL_PATH = Path("reports/d9_d6_frequency_only_digital_endurance_seal_v1.json")
FIRMWARE_ENTRY_PATH = Path("reports/d9_d6_frequency_only_firmware_entry_v1.json")
RUN_LIFECYCLE_PATH = Path("reports/d9_d6_frequency_only_run_lifecycle_v1.json")
RETAINED_UPLOAD_ATTEMPT_PATH = Path(
    "inputs/d9_d6_frequency_only_firmware_upload_attempt_v1.json"
)
# The programme overlays retain the established active supervisor records;
# they are not a second controller or second acknowledgement path.
SUPERVISOR_STATE_PATH = SUPERVISOR_STATE
SUPERVISOR_EVENTS_PATH = SUPERVISOR_EVENTS
ABORT_FIFO_PATH = Path("control/independent_abort.fifo")
RESPONSE_HORIZONS_S = (600, 1500, 3600, 7200, 21600)
CANDIDATE_FLL_WINDOWS_S = (60, 120, 300, 600, 1200, 1800)
SELECTED_FLL_WINDOW_S = 600
CANDIDATE_WINDOW_MINIMUM_ESTIMATES = 2
CANDIDATE_WINDOW_SHORT_NOISE_RATIO = Fraction(5, 4)
CANDIDATE_WINDOW_MATERIAL_NOISE_REDUCTION = Fraction(1, 5)
CANDIDATE_WINDOW_MAXIMUM_GROUP_DELAY_S = 300
APPLICATION_ADMISSION_RESERVE_S = 1500
CAPTURE_EVIDENCE_DRAIN_MARGIN_S = 180
D9_CONFIGURATION_SNAPSHOT_COMPLETION_TIMEOUT_S = 30.0
EXACT_LIFECYCLE_TIME_DOMAIN = "rp2040_timer0_extended"
U32_MASK = (1 << 32) - 1
QUALIFIED_INTERVAL_LEDGER_PATH = Path(
    "reports/d9_d6_frequency_only_qualified_interval_ledger_v1.jsonl"
)
LOST_OPPORTUNITY_PATH = Path(
    "reports/d9_d6_frequency_only_opportunity_ledger_v1.json"
)
OPPORTUNITY_CAUSAL_LEDGER_PATH = Path(
    "reports/d9_d6_frequency_only_opportunity_causal_ledger_v1.jsonl"
)

# This is the firmware register/GPIO readback contract.  It establishes only
# that the selected digital configuration was emitted; it deliberately makes
# no claim about the delivered electrical waveform after the 1 kOhm link.
EXPECTED_D9_HEALTH = {
    ("build", "enable_forwarded_d9_output"): "1",
    ("build", "enable_forwarded_d6_monitor"): "1",
    ("forwarded_clock_output", "contract_id"): "OTIS_D9_D6_READINESS_CONTRACT_V1",
    ("forwarded_clock_output", "contract_sha256"): "a6a08d14a03a87b5e0308880c64799baf2e7afecc23cad22d1532f297960de4d",
    ("forwarded_clock_output", "state"): "configured_10mhz_forwarded_unqualified",
    ("forwarded_clock_output", "source"): "D8_GPIO20_GPIN0",
    ("forwarded_clock_output", "destination"): "D9_GPIO21_GPOUT0",
    ("forwarded_clock_output", "integer_divider"): "1",
    ("forwarded_clock_output", "fractional_divider"): "0",
    ("forwarded_clock_output", "applied_auxsrc"): "1",
    ("forwarded_clock_output", "applied_integer_divider"): "1",
    ("forwarded_clock_output", "applied_fractional_divider"): "0",
    ("forwarded_clock_output", "source_gpio_function"): "8",
    ("forwarded_clock_output", "destination_gpio_function"): "8",
    ("forwarded_clock_output", "inversion"): "0",
    ("forwarded_clock_output", "drive_strength_ma"): "2",
    ("forwarded_clock_output", "slew_rate"): "slow",
    ("forwarded_clock_output", "nominal_frequency_hz"): "10000000",
    ("forwarded_clock_output", "readback_valid"): "true",
}
D6_OBSERVABILITY_KEYS = (
    ("forwarded_clock_monitor", "state"),
    ("forwarded_clock_monitor", "configured"),
    ("forwarded_clock_monitor", "running"),
    ("forwarded_clock_monitor", "fault_flags"),
)

ACTIVE_TRANSACTION_TIMING_JOIN_FIELDS = (
    "transaction_record_sequence",
    "event",
    "run_identity",
    "build_identity",
    "profile_identity",
    "session_id",
    "request_sequence",
    "decision_sequence",
    "source_first_sequence",
    "source_last_sequence",
    "authorization_sequence",
    "nonce",
    "accepted_code",
    "applied_code",
    "application_sequence",
    "dac_epoch",
    "reason",
)


def _exact_capture_contract() -> dict[str, object]:
    """Return the one capture inventory authorized for the revised 24 h run."""

    files = exact_active_timing_csv_files()
    # ACT1 and DAC remain mandatory campaign products. AT2 is already
    # mandatory in the revised inventory; AH2 is declared but optional for the
    # deliberately frequency-only profile.
    for entry in files:
        if entry["contract"] in {"active_transactions_v1", "dac_steps_v1"}:
            entry.pop("optional", None)
    return {
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": TIMER_HZ},
            {"name": EXACT_LIFECYCLE_TIME_DOMAIN, "nominal_hz": TIMER_HZ},
        ],
        "contracts": {
            entry["contract"]: CONTRACT_SCHEMA_VERSIONS[entry["contract"]]
            for entry in files
        },
        "files": files,
    }


def _firmware_flash_authority() -> dict[str, object]:
    return {
        "firmware_flash_limit": 1,
        "automatic_flash_retry": False,
        "automatic_firmware_restoration": False,
        "fqbn": EXPECTED_UPLOAD_FQBN,
    }


def _require_exact_capture_contract(value: Mapping[str, Any], *, owner: str) -> None:
    expected = _exact_capture_contract()
    mismatches = [key for key, item in expected.items() if value.get(key) != item]
    if mismatches:
        raise ValueError(
            f"{owner} exact capture declaration differs: " + ", ".join(mismatches)
        )


def canonical_sha256(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    value = _read(path)
    unsigned = {key: item for key, item in value.items() if key != "contract_semantic_sha256"}
    if value.get("contract_semantic_sha256") != canonical_sha256(unsigned):
        raise ValueError("frequency-only endurance contract semantic identity differs")
    if value.get("profile_id") != "d9_d6_frequency_only_lower":
        raise ValueError("frequency-only endurance profile differs")
    if value.get("serial") != {"baud": 115200, "selection": "fresh_capture_device_auto_detect_every_enumeration", "stored_path_permitted": False}:
        raise ValueError("frequency-only endurance serial contract differs")
    require_exact_gnss_operational_baud_policy(
        value.get("gnss_uart_policy", {}), owner="frequency-only endurance"
    )
    if any(value["authority"].get(key) is not False for key in ("hybrid_pll", "phase_request", "d9_control", "d6_control", "d10_control", "automatic_retry", "nominal_restoration")):
        raise ValueError("frequency-only endurance authority boundary differs")
    if value["envelope"] != {"qualified_duration_s": 86400, "initial_qualification_deadline_s": 5400, "absolute_wall_limit_s": 108000, "milestone_qualified_duration_s": 21600, "maximum_setup_establishments": 1, "maximum_automatic_applications": 48, "maximum_total_physical_dac_writes": 49, "maximum_cumulative_movement_codes": 1008, "maximum_step_codes": 21, "minimum_application_cadence_s": 1800, "maximum_outstanding_transactions": 1, "automatic_limits_are_nonbinding_cadence_derived_ceilings": True, "dac_min_code": "0xA800", "dac_max_code": "0xAB00"}:
        raise ValueError("frequency-only endurance envelope differs")
    if value.get("starting_dac") != {"exact_setup_code": "0xA808", "setup_establishments": 1, "setup_retry": False, "automatic_restore": False, "required_first_consumer_and_response_path": True}:
        raise ValueError("frequency-only endurance exact setup/response boundary differs")
    if value.get("sustained_discipline") != {"minimum_automatic_applications": 0, "first_complete_application_path_required_if_any_application_occurs": True, "healthy_response_classifications_are_observational": True, "authority_ceiling_exhaustion_before_endpoint": "continue_observation_and_classify_incomplete_only_if_a_later_eligible_opportunity_is_suppressed_inside_open_admission", "application_admission_close_before_qualified_endpoint_s": APPLICATION_ADMISSION_RESERVE_S, "longer_analysis_horizons_do_not_close_control_admission": True, "response_horizons_s": list(RESPONSE_HORIZONS_S), "stationary_dac_epoch_only": True}:
        raise ValueError("frequency-only sustained-discipline objective differs")
    if value.get("candidate_fll_window_analysis") != {"observational_only": True, "candidate_windows_s": list(CANDIDATE_FLL_WINDOWS_S), "selected_window_s": SELECTED_FLL_WINDOW_S, "stationary_support": "qualified_consecutive_same_session_dac_code_and_epoch_after_settling", "aggregation": "exact_integer_edge_and_tick_sums_with_rational_derived_metrics_before_display_floats", "minimum_complete_estimates": CANDIDATE_WINDOW_MINIMUM_ESTIMATES, "noise_metric": "exact_successive_difference_mean_square_hz2", "quantization_metric": "worst_case_one_edge_resolution_hz", "latency_metric": "boxcar_group_delay_s", "drift_metric": "exact_start_to_end_hz_per_hour", "too_short_noise_ratio_vs_selected": 1.25, "too_long_material_noise_reduction_fraction": 0.2, "maximum_appropriate_group_delay_s": CANDIDATE_WINDOW_MAXIMUM_GROUP_DELAY_S}:
        raise ValueError("frequency-only candidate FLL window analysis differs")
    if value.get("gnss_metadata_hold") != {
        "mode": "GNSS_METADATA_HOLD",
        "d14_d8_measurement_continues": True,
        "new_correction_authority": False,
        "last_confirmed_dac_code_preserved": True,
        "fresh_causal_requalification_required": True,
        "authority": "effective_firmware_and_live_supervisor_semantics",
        "required_emitted_identity_fields": [
            "session_id",
            "confirmed_applied_code_known",
            "confirmed_applied_code",
            "dac_epoch",
            "gnss_metadata_hold_entry_sequence",
            "gnss_metadata_requalification_sequence",
            "gnss_metadata_qualification_frontier",
            "d14_d8_observation_sequence",
        ],
    }:
        raise ValueError("frequency-only GNSS metadata hold semantics differ")
    return value


def _binding(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"exact input absent: {path}")
    return {"path": str(path.resolve()), "size_bytes": path.stat().st_size, "sha256": sha256(path.read_bytes()).hexdigest()}


def _exact_firmware(build_manifest_path: Path, *, source_revision: str) -> dict[str, object]:
    """Extract and bind the firmware identities the device must emit."""
    build = _read(build_manifest_path)
    provenance = build.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("build manifest lacks generated provenance")
    source = provenance.get("source")
    configuration = provenance.get("configuration")
    artifacts = build.get("artifacts")
    if not isinstance(source, dict) or not isinstance(configuration, dict) or not isinstance(artifacts, list):
        raise ValueError("build manifest provenance/artifacts are incomplete")
    if source.get("git_commit") != source_revision:
        raise ValueError("caller source revision differs from exact build provenance")
    source_sha = source.get("sha256")
    config_sha = configuration.get("sha256")
    if not all(isinstance(value, str) and len(value) == 64 for value in (source_sha, config_sha)):
        raise ValueError("build manifest source/configuration SHA-256 identities are malformed")
    uf2_entries = [entry for entry in artifacts if isinstance(entry, dict) and str(entry.get("name", "")).endswith(".uf2")]
    if len(uf2_entries) != 1:
        raise ValueError("build manifest must declare exactly one UF2 artifact")
    uf2_path = build_manifest_path.resolve().parent / str(uf2_entries[0]["name"])
    uf2_binding = _binding(uf2_path)
    if uf2_binding["sha256"] != uf2_entries[0].get("sha256") or uf2_binding["size_bytes"] != uf2_entries[0].get("size_bytes"):
        raise ValueError("UF2 file differs from its build-manifest artifact identity")
    fqbn = configuration.get("fqbn")
    if fqbn != EXPECTED_UPLOAD_FQBN:
        raise ValueError("build manifest FQBN differs from the activated upload target")
    return {
        "profile_id": configuration.get("profile_id"),
        "source_revision": source_revision,
        "source_sha256": source_sha,
        "configuration_sha256": config_sha,
        "build_identity": f"{source_sha}:{config_sha}",
        "fqbn": fqbn,
        "build_manifest": _binding(build_manifest_path),
        "uf2": uf2_binding,
    }


def freeze_bundle(*, build_manifest_path: Path, source_revision: str, contract_path: Path = CONTRACT_PATH) -> dict[str, object]:
    """Freeze a no-I/O bundle only after the exact selected build exists."""
    contract = load_contract(contract_path)
    build = _read(build_manifest_path)
    configuration = build.get("provenance", {}).get("configuration", {})
    defines = configuration.get("defines", {})
    forbidden = ("OTIS_ENABLE_CX320_ACTIVE_HYBRID", "OTIS_ENABLE_CX321_ACTIVE_HYBRID", "OTIS_ENABLE_CX322_DIRECT_HYBRID", "OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION", "OTIS_ENABLE_CX318_STAGE4_PREVIEW", "OTIS_ENABLE_CX318_STAGE5_PREVIEW")
    if configuration.get("profile_id") != contract["profile_id"] or any(defines.get(key, "0") != "0" for key in forbidden):
        raise ValueError("build is not exact zero-hybrid frequency-only profile")
    required = {
        "OTIS_ENABLE_FORWARDED_D9_OUTPUT": "1",
        "OTIS_ENABLE_FORWARDED_D6_MONITOR": "1",
        "OTIS_GNSS_UART_BAUD": "115200u",
        "OTIS_ENABLE_DUAL_CORE_PARTITION": "1",
        "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "1",
        "OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW": "1",
        "OTIS_CX317_ACTIVE_CAMPAIGN": (
            "OTIS_CX317_ACTIVE_CAMPAIGN_D9_D6_FREQUENCY_ONLY_ENDURANCE"
        ),
        "OTIS_CX317_ACTIVE_START_CODE": "0xA808u",
        "OTIS_CX317_ACTIVE_CORRECTION_LIMIT": "48u",
        "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES": "1008u",
        "OTIS_DAC_MIN_CODE": "0xA800u",
        "OTIS_DAC_MAX_CODE": "0xAB00u",
        "OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG": "600u",
        "OTIS_CX317_SETTLING_EXCLUSION_S": "900u",
        "OTIS_CX317_FULL_HISTORY_RESET_S": "1500u",
        "OTIS_CX317_RECOVERY_FRESH_SUPPORT_S": "600u",
        "OTIS_CX317_DECISION_CADENCE_S": "1800u",
        "OTIS_CX317_MINIMUM_APPLIED_CADENCE_S": "1800u",
        **GNSS_OPERATIONAL_REQUIRED_DEFINES,
    }
    if any(defines.get(key) != expected for key, expected in required.items()):
        raise ValueError("build lacks exact D9/D6/FLL selectors")
    firmware = _exact_firmware(build_manifest_path, source_revision=source_revision)
    if firmware["profile_id"] != contract["profile_id"]:
        raise ValueError("build provenance profile differs from frequency-only contract")
    unsigned: dict[str, object] = {"schema_version": 1, "bundle_type": "otis_d9_d6_frequency_only_digital_endurance_bundle_v1", "tool": TOOL_ID, "effective": False, "physical_authority": False, "source_revision": source_revision, "contract": _binding(contract_path), "contract_semantic_sha256": contract["contract_semantic_sha256"], "firmware_build": firmware["build_manifest"], "firmware": firmware, "profile_id": contract["profile_id"], "serial": contract["serial"], "gnss_uart_policy": contract["gnss_uart_policy"], "terminal_family": contract["terminal_family"], "unresolved_delivered_output_claims": contract["unresolved_delivered_output_claims"]}
    return {**unsigned, "bundle_sha256": canonical_sha256(unsigned)}


def validate_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(bundle)
    unsigned = {key: item for key, item in value.items() if key != "bundle_sha256"}
    if value.get("bundle_sha256") != canonical_sha256(unsigned):
        raise ValueError("frequency-only endurance bundle identity differs")
    contract_path = Path(str(value["contract"]["path"]))
    contract = load_contract(contract_path)
    if value.get("contract") != _binding(contract_path):
        raise ValueError("frequency-only endurance frozen contract file identity differs")
    build_path = Path(str(value["firmware_build"]["path"]))
    if value.get("firmware_build") != _binding(build_path):
        raise ValueError("frequency-only endurance frozen firmware build identity differs")
    if value.get("firmware") != _exact_firmware(build_path, source_revision=str(value.get("source_revision", ""))):
        raise ValueError("frequency-only endurance firmware source/configuration/UF2 identity differs")
    if value.get("contract_semantic_sha256") != contract["contract_semantic_sha256"] or value.get("profile_id") != contract["profile_id"]:
        raise ValueError("frequency-only endurance bundle contract/profile differs")
    if value.get("gnss_uart_policy") != GNSS_OPERATIONAL_BAUD_POLICY:
        raise ValueError("frequency-only endurance bundle GNSS UART policy differs")
    if value.get("effective") is not False or value.get("physical_authority") is not False:
        raise ValueError("bundle must remain non-effective before live activation")
    return value


@dataclass
class EnduranceSupervisor:
    """Exact counter-domain qualified-time and FLL budget accounting."""

    contract: Mapping[str, Any]
    armed_ticks: int | None = None
    qualified_ticks: int = 0
    terminal: str | None = None
    milestones: list[int] = field(default_factory=list)
    setup_establishments: int = 0
    automatic_applications: int = 0
    cumulative_movement_codes: int = 0
    last_application_ticks: int | None = None
    elapsed_ticks: int = 0
    last_closing_ticks: int | None = None
    last_count_sequence: int | None = None
    target_reached: bool = False
    authority_ceiling_exhausted: bool = False
    authority_ceiling_decision_sequence: int | None = None
    endpoint_incomplete_reason: str | None = None
    invalid_interval_count: int = 0

    @classmethod
    def from_state(
        cls, contract: Mapping[str, Any], state: Mapping[str, Any]
    ) -> "EnduranceSupervisor":
        """Restore only canonical ledger fields from the durable supervisor state."""
        value = cls(contract)
        for name in (
            "armed_ticks",
            "qualified_ticks",
            "setup_establishments",
            "automatic_applications",
            "cumulative_movement_codes",
            "last_application_ticks",
            "elapsed_ticks",
            "last_closing_ticks",
            "last_count_sequence",
            "target_reached",
            "authority_ceiling_exhausted",
            "authority_ceiling_decision_sequence",
            "endpoint_incomplete_reason",
            "invalid_interval_count",
        ):
            if name in state:
                setattr(value, name, state[name])
        if "counter_terminal" in state:
            value.terminal = state["counter_terminal"]
        milestones = state.get("milestones_qualified_s", state.get("milestones", []))
        if isinstance(milestones, list):
            value.milestones = [int(item) for item in milestones]
        if state.get("last_qualified_count_sequence") is not None:
            value.last_count_sequence = int(state["last_qualified_count_sequence"])
        return value

    def state_fields(self) -> dict[str, Any]:
        return {
            "armed_ticks": self.armed_ticks,
            "qualified_ticks": self.qualified_ticks,
            "qualified_duration_s": self.qualified_ticks // TIMER_HZ,
            "milestones_qualified_s": list(self.milestones),
            "setup_establishments": self.setup_establishments,
            "automatic_applications": self.automatic_applications,
            "total_physical_dac_writes": (
                self.setup_establishments + self.automatic_applications
            ),
            "cumulative_movement_codes": self.cumulative_movement_codes,
            "last_application_ticks": self.last_application_ticks,
            "elapsed_ticks": self.elapsed_ticks,
            "last_closing_ticks": self.last_closing_ticks,
            "last_qualified_count_sequence": self.last_count_sequence,
            "target_reached": self.target_reached,
            "authority_ceiling_exhausted": self.authority_ceiling_exhausted,
            "authority_ceiling_decision_sequence": (
                self.authority_ceiling_decision_sequence
            ),
            "endpoint_incomplete_reason": self.endpoint_incomplete_reason,
            "invalid_interval_count": self.invalid_interval_count,
            "counter_terminal": self.terminal,
        }

    def arm(self, *, frontier_ticks: int, d9_state: str, d9_readback_exact: bool, d14_d8_healthy: bool, outstanding_transaction: bool, applied_code: int, dac_epoch: int) -> None:
        exact_setup_code = int(str(self.contract["starting_dac"]["exact_setup_code"]), 0)
        if self.armed_ticks is not None or not d9_readback_exact or d9_state != self.contract["d9"]["required_state"] or not d14_d8_healthy or outstanding_transaction or applied_code != exact_setup_code or dac_epoch != 1:
            raise ValueError("SOAK_ARMED gate differs")
        self.armed_ticks = frontier_ticks

    def observe_interval(self, *, opening_ticks: int, closing_ticks: int, measurement_qualified: bool, d9_valid: bool, count_sequence: int | None = None) -> None:
        if self.armed_ticks is None or self.terminal is not None or self.target_reached:
            return
        interval = forward_progress(
            opening_ticks,
            closing_ticks,
            domain="rp2040_timer0",
            allow_equal=False,
        )
        previous = self.armed_ticks if self.last_closing_ticks is None else self.last_closing_ticks
        gap = forward_progress(
            previous,
            opening_ticks,
            domain="rp2040_timer0",
            allow_equal=True,
        )
        sequence_invalid = (
            count_sequence is not None
            and self.last_count_sequence is not None
            and not _u32_successor(self.last_count_sequence, count_sequence)
        )
        if not interval.valid or interval.distance_ticks is None or not gap.valid or gap.distance_ticks is None or sequence_invalid:
            self.terminal = "frequency_only_d9_d6_invalid_due_to_identity_or_evidence_failure"; return
        self.elapsed_ticks += gap.distance_ticks + interval.distance_ticks
        self.last_closing_ticks = closing_ticks
        if count_sequence is not None:
            self.last_count_sequence = count_sequence
        envelope = self.contract["envelope"]
        if self.elapsed_ticks > int(envelope["absolute_wall_limit_s"]) * TIMER_HZ:
            self.terminal = "frequency_only_d9_d6_digital_endurance_incomplete"; return
        if not d9_valid:
            self.terminal = "frequency_only_d9_d6_digital_noninterference_failed"; return
        if measurement_qualified:
            self.qualified_ticks += interval.distance_ticks
            step = int(envelope["milestone_qualified_duration_s"]) * TIMER_HZ
            while len(self.milestones) < 4 and self.qualified_ticks >= (len(self.milestones) + 1) * step:
                self.milestones.append((len(self.milestones) + 1) * int(envelope["milestone_qualified_duration_s"]))
            if self.qualified_ticks >= int(envelope["qualified_duration_s"]) * TIMER_HZ:
                self.target_reached = True
        else:
            self.invalid_interval_count += 1
        if self.elapsed_ticks > int(envelope["initial_qualification_deadline_s"]) * TIMER_HZ and self.qualified_ticks == 0:
            self.terminal = "frequency_only_d9_d6_digital_endurance_incomplete"

    def record_fll_transaction(self, *, setup_establishment: bool, requested_delta_codes: int, application_ticks: int, phase_or_hybrid: bool, decision_sequence: int | None = None) -> None:
        if self.terminal is not None or phase_or_hybrid or abs(requested_delta_codes) > int(self.contract["envelope"]["maximum_step_codes"]):
            self.terminal = "frequency_only_d9_d6_controller_or_transaction_fault"; return
        if setup_establishment:
            self.setup_establishments += 1
            if self.setup_establishments > int(self.contract["envelope"]["maximum_setup_establishments"]): self.terminal = "frequency_only_d9_d6_controller_or_transaction_fault"
            return
        if self.last_application_ticks is not None and application_ticks - self.last_application_ticks < int(self.contract["envelope"]["minimum_application_cadence_s"]) * TIMER_HZ:
            self.terminal = "frequency_only_d9_d6_controller_or_transaction_fault"; return
        self.automatic_applications += 1; self.cumulative_movement_codes += abs(requested_delta_codes); self.last_application_ticks = application_ticks
        envelope = self.contract["envelope"]
        if (
            self.automatic_applications > int(envelope["maximum_automatic_applications"])
            or self.cumulative_movement_codes > int(envelope["maximum_cumulative_movement_codes"])
            or self.setup_establishments + self.automatic_applications
            > int(envelope["maximum_total_physical_dac_writes"])
        ):
            self.terminal = "frequency_only_d9_d6_controller_or_transaction_fault"
            return
        if (
            self.automatic_applications
            == int(envelope["maximum_automatic_applications"])
            or self.cumulative_movement_codes
            == int(envelope["maximum_cumulative_movement_codes"])
        ):
            self.authority_ceiling_exhausted = True
            self.authority_ceiling_decision_sequence = decision_sequence


def no_io_preflight(bundle: Mapping[str, Any]) -> dict[str, object]:
    value = validate_bundle(bundle)
    return {
        "schema_version": 1,
        "tool": TOOL_ID,
        "report_type": "frequency_only_exact_no_io_preflight_v1",
        "status": "passed",
        "hardware_operations": False,
        "bundle_sha256": value["bundle_sha256"],
        "profile_id": value["profile_id"],
        "firmware_build_identity": value["firmware"]["build_identity"],
        "firmware_build_manifest_sha256": value["firmware_build"]["sha256"],
        "firmware_flash_authority": _firmware_flash_authority(),
        "gnss_uart_policy": value["gnss_uart_policy"],
        "terminal_family": value["terminal_family"],
        "unresolved_delivered_output_claims": value["unresolved_delivered_output_claims"],
    }


def _validate_activation_report(
    report: Mapping[str, Any],
    *,
    report_type: str,
    bundle: Mapping[str, Any],
) -> None:
    expected = {
        "status": "passed",
        "hardware_operations": False,
        "bundle_sha256": bundle["bundle_sha256"],
        "profile_id": bundle["profile_id"],
        "firmware_build_identity": bundle["firmware"]["build_identity"],
        "firmware_build_manifest_sha256": bundle["firmware_build"]["sha256"],
        "firmware_flash_authority": _firmware_flash_authority(),
    }
    if report.get("report_type") != report_type:
        raise ValueError(f"activation {report_type} report type differs")
    mismatches = [key for key, value in expected.items() if report.get(key) != value]
    if mismatches:
        raise ValueError(
            f"activation {report_type} identity or verdict differs: "
            + ", ".join(mismatches)
        )
    if report_type == "frequency_only_exact_operational_rehearsal_v1":
        required_true = (
            "priority_abort_delivered",
            "abort_delivery_retained_before_capture_close",
            "actual_supervisor_exercised",
            "one_outstanding_transaction_enforced",
            "accelerated_exact_counter_endpoint_reached",
            "gnss_metadata_hold_effective_live_supervisor_fault_injection",
            "gnss_metadata_hold_confirmed_session_code_epoch_bound",
            "gnss_metadata_hold_fresh_causal_requalification_exercised",
            "opportunity_causal_ledger_exercised",
            "production_upload_orchestration_exercised",
            "deterministic_upload_and_reenumeration_injected",
            "exactly_one_upload_no_retry_enforced",
            "global_activation_consumption_replay_blocked",
            "pre_upload_fresh_auto_detect_exercised",
            "post_upload_fresh_auto_detect_exercised",
            "capture_own_auto_detect_command_exercised",
            "firmware_policy_identity_replayed_by_live_supervisor",
            "actual_frequency_only_exact_counter_arm_exercised",
        )
        false_fields = [key for key in required_true if report.get(key) is not True]
        if (
            false_fields
            or report.get("mode") != "PTY_fixture"
            or int(report.get("complete_response_transactions", 0)) < 2
        ):
            raise ValueError(
                "activation operational rehearsal coverage differs: "
                + ", ".join(false_fields or ["mode_or_transaction_coverage"])
            )


def activate_bundle(
    *,
    bundle_path: Path,
    preflight_report_path: Path,
    rehearsal_report_path: Path,
    operator_authorization_ref: str,
) -> dict[str, Any]:
    """Create the only artifact that may authorize the exact physical run.

    The frozen candidate remains permanently non-effective.  Activation binds
    it to successful retained results from the exact no-I/O preflight and the
    actual PTY operational-path rehearsal, including the selected build.
    """
    bundle_path = bundle_path.resolve()
    preflight_report_path = preflight_report_path.resolve()
    rehearsal_report_path = rehearsal_report_path.resolve()
    operator_authorization_ref = operator_authorization_ref.strip()
    if not operator_authorization_ref:
        raise ValueError("frequency-only activation lacks operator authorization")
    bundle = validate_bundle(_read(bundle_path))
    preflight = _read(preflight_report_path)
    rehearsal = _read(rehearsal_report_path)
    _validate_activation_report(
        preflight,
        report_type="frequency_only_exact_no_io_preflight_v1",
        bundle=bundle,
    )
    _validate_activation_report(
        rehearsal,
        report_type="frequency_only_exact_operational_rehearsal_v1",
        bundle=bundle,
    )
    unsigned = {
        "schema_version": 1,
        "activation_type": "otis_d9_d6_frequency_only_live_activation_v1",
        "tool": TOOL_ID,
        "effective": True,
        "physical_authority": True,
        "authority": _firmware_flash_authority(),
        "operator_authorization_ref": operator_authorization_ref,
        "candidate_bundle": _binding(bundle_path),
        "candidate_bundle_sha256": bundle["bundle_sha256"],
        "contract_semantic_sha256": bundle["contract_semantic_sha256"],
        "profile_id": bundle["profile_id"],
        "firmware_build_identity": bundle["firmware"]["build_identity"],
        "firmware_build_manifest_sha256": bundle["firmware_build"]["sha256"],
        "capture_evidence_contract": _exact_capture_contract(),
        "preflight_report": _binding(preflight_report_path),
        "rehearsal_report": _binding(rehearsal_report_path),
    }
    return {**unsigned, "activation_sha256": canonical_sha256(unsigned)}


def validate_activation(activation: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    value = dict(activation)
    unsigned = {key: item for key, item in value.items() if key != "activation_sha256"}
    if value.get("activation_sha256") != canonical_sha256(unsigned):
        raise ValueError("frequency-only live activation identity differs")
    if (
        value.get("activation_type")
        != "otis_d9_d6_frequency_only_live_activation_v1"
        or value.get("effective") is not True
        or value.get("physical_authority") is not True
        or not isinstance(value.get("operator_authorization_ref"), str)
        or not str(value.get("operator_authorization_ref")).strip()
        or value.get("authority") != _firmware_flash_authority()
    ):
        raise ValueError("frequency-only live activation authority differs")
    bundle_path = Path(str(value["candidate_bundle"]["path"]))
    if value.get("candidate_bundle") != _binding(bundle_path):
        raise ValueError("activated frequency-only candidate bundle file differs")
    bundle = validate_bundle(_read(bundle_path))
    preflight_path = Path(str(value["preflight_report"]["path"]))
    rehearsal_path = Path(str(value["rehearsal_report"]["path"]))
    if value.get("preflight_report") != _binding(preflight_path):
        raise ValueError("activated frequency-only preflight report differs")
    if value.get("rehearsal_report") != _binding(rehearsal_path):
        raise ValueError("activated frequency-only rehearsal report differs")
    _validate_activation_report(
        _read(preflight_path),
        report_type="frequency_only_exact_no_io_preflight_v1",
        bundle=bundle,
    )
    _validate_activation_report(
        _read(rehearsal_path),
        report_type="frequency_only_exact_operational_rehearsal_v1",
        bundle=bundle,
    )
    expected = {
        "candidate_bundle_sha256": bundle["bundle_sha256"],
        "contract_semantic_sha256": bundle["contract_semantic_sha256"],
        "profile_id": bundle["profile_id"],
        "firmware_build_identity": bundle["firmware"]["build_identity"],
        "firmware_build_manifest_sha256": bundle["firmware_build"]["sha256"],
        "authority": _firmware_flash_authority(),
        "capture_evidence_contract": _exact_capture_contract(),
    }
    mismatches = [key for key, expected_value in expected.items() if value.get(key) != expected_value]
    if mismatches:
        raise ValueError("frequency-only activation exact bindings differ: " + ", ".join(mismatches))
    return value, bundle


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle: json.dump(value, handle, indent=2, sort_keys=True); handle.write("\n")


def _activation_upload_attempt_path(activation: Mapping[str, Any]) -> Path:
    """Return one caller-independent consumption path for an activation SHA."""

    candidate_bundle = activation.get("candidate_bundle")
    activation_sha256 = activation.get("activation_sha256")
    if (
        not isinstance(candidate_bundle, Mapping)
        or not isinstance(candidate_bundle.get("path"), str)
        or not isinstance(activation_sha256, str)
        or len(activation_sha256) != 64
    ):
        raise ValueError("physical activation lacks a global upload-consumption identity")
    bundle_path = Path(str(candidate_bundle["path"])).resolve()
    return bundle_path.parent / (
        f".{bundle_path.name}.{activation_sha256}.firmware-upload-attempt.json"
    )


def _reserve_activation_upload_attempt(
    *,
    path: Path,
    activation: Mapping[str, Any],
    bundle: Mapping[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    """Durably consume one activation immediately before the upload attempt.

    The O_EXCL reservation is intentionally never removed or rewritten.  Even
    an empty/partial file left by a host crash consumes the activation and
    therefore fails closed rather than permitting an ambiguous second flash.
    """

    firmware = bundle["firmware"]
    unsigned = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "operation": "exact_d9_d6_frequency_only_firmware_upload_attempt",
        "status": "upload_attempt_irrevocably_reserved",
        "created_utc": _utc_now(),
        "activation_sha256": activation["activation_sha256"],
        "bundle_sha256": bundle["bundle_sha256"],
        "intended_run_dir": str(run_dir.resolve()),
        "fqbn": firmware["fqbn"],
        "build_identity": firmware["build_identity"],
        "build_manifest_sha256": firmware["build_manifest"]["sha256"],
        "uf2_sha256": firmware["uf2"]["sha256"],
        "firmware_flash_limit": 1,
        "automatic_retry_permitted": False,
    }
    record = {**unsigned, "record_sha256": canonical_sha256(unsigned)}
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise FileExistsError(
            "activation already has a firmware-upload reservation; upload is forbidden"
        ) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        # The reservation is the safety record.  Never unlink it on error: an
        # ambiguous attempt must permanently consume this activation.
        raise
    return record


def _validate_upload_attempt_reservation(
    record: Mapping[str, Any],
    *,
    activation: Mapping[str, Any],
    bundle: Mapping[str, Any],
    run_dir: Path,
) -> None:
    unsigned = {key: value for key, value in record.items() if key != "record_sha256"}
    firmware = bundle["firmware"]
    expected = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "operation": "exact_d9_d6_frequency_only_firmware_upload_attempt",
        "status": "upload_attempt_irrevocably_reserved",
        "activation_sha256": activation["activation_sha256"],
        "bundle_sha256": bundle["bundle_sha256"],
        "intended_run_dir": str(run_dir.resolve()),
        "fqbn": firmware["fqbn"],
        "build_identity": firmware["build_identity"],
        "build_manifest_sha256": firmware["build_manifest"]["sha256"],
        "uf2_sha256": firmware["uf2"]["sha256"],
        "firmware_flash_limit": 1,
        "automatic_retry_permitted": False,
    }
    if (
        record.get("record_sha256") != canonical_sha256(unsigned)
        or not isinstance(record.get("created_utc"), str)
        or any(record.get(key) != value for key, value in expected.items())
    ):
        raise ValueError("firmware-upload attempt reservation identity differs")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_replace(path: Path, value: Mapping[str, Any]) -> None:
    """Atomically publish mutable supervisor state, never evidence results."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def fresh_capture_device_auto_detect() -> str:
    """Resolve exactly one device immediately before a capture enumeration.

    The returned path is evidence only.  No caller may use it as a stored
    future selection: ``capture_device`` repeats its own auto-detect before
    opening the serial endpoint and rejects a changed result.
    """
    return _detect_single_device()


def _board_identity_fingerprint(identity: Mapping[str, Any]) -> dict[str, str]:
    return {
        key: str(identity.get(key, ""))
        for key in (
            "hardware_id",
            "serial_number",
            "vid",
            "pid",
            "product",
            "board_name",
            "board_fqbn",
        )
    }


def _execute_activation_authorized_upload(
    *,
    run_dir: Path,
    activation: Mapping[str, Any],
    bundle: Mapping[str, Any],
    arduino_cli: str = "arduino-cli",
    fresh_detect: Callable[[], str] | None = None,
    identity_reader: Callable[[str], Mapping[str, Any]] | None = None,
    owner_reader: Callable[[str], set[int]] | None = None,
    upload_runner: Callable[..., Any] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    reenumeration_timeout_s: float = 30.0,
    hardware_operations: bool = True,
    upload_attempt_path: Path | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Execute the single-upload production entry path with injectable I/O.

    The PTY rehearsal calls this exact function with deterministic injections;
    only the live call permits hardware operations.
    """

    if reenumeration_timeout_s <= 0:
        raise ValueError("USB re-enumeration timeout must be positive")
    if (run_dir / FIRMWARE_ENTRY_PATH).exists():
        raise FileExistsError("firmware-entry record already exists; upload is forbidden")
    if activation.get("authority") != _firmware_flash_authority():
        raise ValueError("activation does not grant exactly one non-retrying flash")
    if hardware_operations and (
        activation.get("effective") is not True
        or activation.get("physical_authority") is not True
    ):
        raise ValueError("physical upload lacks effective activation authority")
    if hardware_operations:
        if upload_attempt_path is not None:
            raise ValueError("physical upload-attempt path cannot be caller-selected")
        checked_activation, checked_bundle = validate_activation(activation)
        if checked_activation != dict(activation) or checked_bundle != dict(bundle):
            raise ValueError("physical upload activation/bundle identity differs")
    firmware = bundle.get("firmware")
    if not isinstance(firmware, Mapping):
        raise ValueError("activated firmware binding is absent")
    if firmware.get("fqbn") != EXPECTED_UPLOAD_FQBN:
        raise ValueError("activated firmware FQBN differs")
    uf2 = firmware.get("uf2")
    build_manifest = firmware.get("build_manifest")
    if not isinstance(uf2, Mapping) or not isinstance(build_manifest, Mapping):
        raise ValueError("activated build/UF2 binding is absent")
    if dict(uf2) != _binding(Path(str(uf2.get("path", "")))):
        raise ValueError("activated UF2 changed before upload")
    if dict(build_manifest) != _binding(
        Path(str(build_manifest.get("path", "")))
    ):
        raise ValueError("activated build manifest changed before upload")

    reservation_path = (
        _activation_upload_attempt_path(activation)
        if hardware_operations
        else (
            upload_attempt_path
            if upload_attempt_path is not None
            else run_dir / "reports/rehearsal_firmware_upload_attempt_v1.json"
        )
    )
    if reservation_path.exists():
        raise FileExistsError(
            "activation already has a firmware-upload reservation; upload is forbidden"
        )

    detect = fresh_detect or fresh_capture_device_auto_detect
    identify = identity_reader or (
        lambda device: read_board_identity(device, arduino_cli=arduino_cli)
    )
    owners = owner_reader or _serial_owner_pids
    run_upload = upload_runner or subprocess.run
    sleeper = sleep_fn or time.sleep

    device_before = detect()
    if owners(device_before):
        raise RuntimeError(
            f"pre-upload auto-detected device already has a serial owner: {device_before}"
        )
    board_before = dict(identify(device_before))
    command = [
        arduino_cli,
        "upload",
        "--port",
        device_before,
        "--fqbn",
        str(firmware["fqbn"]),
        "--input-file",
        str(uf2["path"]),
    ]
    reservation = _reserve_activation_upload_attempt(
        path=reservation_path,
        activation=activation,
        bundle=bundle,
        run_dir=run_dir,
    )
    started_utc = _utc_now()
    try:
        completed = run_upload(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        completed = SimpleNamespace(
            returncode=-1,
            stdout=str(exc.stdout or ""),
            stderr=str(exc.stderr or "") + "; upload_timeout",
        )
    stdout = str(getattr(completed, "stdout", ""))
    stderr = str(getattr(completed, "stderr", ""))
    exit_code = int(getattr(completed, "returncode", -1))
    device_after: str | None = None
    board_after: dict[str, Any] | None = None
    reappearance_error = ""
    post_upload_auto_detect_attempts = 0
    if exit_code == 0:
        deadline = time.monotonic() + reenumeration_timeout_s
        while time.monotonic() < deadline:
            post_upload_auto_detect_attempts += 1
            try:
                candidate = detect()
                if owners(candidate):
                    raise RuntimeError("re-enumerated device has a serial owner")
                candidate_identity = dict(identify(candidate))
                if _board_identity_fingerprint(candidate_identity) != (
                    _board_identity_fingerprint(board_before)
                ):
                    raise ValueError("post-upload board identity differs")
                device_after = candidate
                board_after = candidate_identity
                break
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                reappearance_error = str(exc)
                sleeper(0.5)

    passed = exit_code == 0 and device_after is not None and board_after is not None
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "operation": "exact_d9_d6_frequency_only_firmware_upload",
        "status": "passed" if passed else "failed",
        "hardware_operations": hardware_operations,
        "started_utc": started_utc,
        "completed_utc": _utc_now(),
        "firmware_flash_count": 1,
        "automatic_retry_performed": False,
        "command": command,
        "exit_code": exit_code,
        "stdout_sha256": sha256(stdout.encode()).hexdigest(),
        "stderr_sha256": sha256(stderr.encode()).hexdigest(),
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
        "fqbn": firmware["fqbn"],
        "device_selection": "fresh_auto_detect_before_and_after_upload",
        "device_before": device_before,
        "device_after": device_after,
        "post_upload_auto_detect_attempts": post_upload_auto_detect_attempts,
        "usb_reenumerated_and_identified": board_after is not None,
        "serial_path_changed": device_after not in {None, device_before},
        "board_before": board_before,
        "board_after": board_after,
        "board_before_sha256": canonical_sha256(board_before),
        "board_after_sha256": (
            canonical_sha256(board_after) if board_after is not None else None
        ),
        "board_identity_fingerprint_sha256": canonical_sha256(
            _board_identity_fingerprint(board_before)
        ),
        "board_reappearance_error": reappearance_error,
        "activation_sha256": activation.get("activation_sha256"),
        "bundle_sha256": bundle.get("bundle_sha256"),
        "upload_attempt_reservation": _binding(reservation_path),
        "upload_attempt_reservation_record_sha256": reservation["record_sha256"],
        "build_identity": firmware.get("build_identity"),
        "build_manifest_sha256": build_manifest.get("sha256"),
        "uf2_sha256": uf2.get("sha256"),
        "profile_id": firmware.get("profile_id"),
    }
    record = {**unsigned, "record_sha256": canonical_sha256(unsigned)}
    _write_new(run_dir / FIRMWARE_ENTRY_PATH, record)
    if not passed:
        raise RuntimeError(
            "exact firmware upload or USB re-enumeration failed; retry is forbidden"
        )
    assert device_after is not None and board_after is not None
    return device_after, board_after, record


def _latest_health(path: Path) -> dict[tuple[str, str], str]:
    if not path.is_file():
        return {}
    result: dict[tuple[str, str], str] = {}
    with path.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            component = row.get("component")
            key = row.get("status_key")
            value = row.get("status_value")
            if component and key and value is not None:
                result[(component, key)] = value
    return result


def _d9_gate(health: Mapping[tuple[str, str], str]) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    mismatches: list[str] = []
    for key, expected in EXPECTED_D9_HEALTH.items():
        observed = health.get(key)
        label = f"{key[0]}.{key[1]}"
        if observed is None:
            missing.append(label)
        elif observed != expected:
            mismatches.append(f"{label}={observed!r}, expected {expected!r}")
    first_valid = health.get(("forwarded_clock_output", "first_valid_ticks"))
    try:
        if first_valid is None or int(first_valid) <= 0:
            missing.append("forwarded_clock_output.first_valid_ticks")
    except ValueError:
        mismatches.append("forwarded_clock_output.first_valid_ticks must be positive")
    return missing, mismatches


def _d6_observability(health: Mapping[tuple[str, str], str]) -> list[str]:
    return [f"{component}.{key}" for component, key in D6_OBSERVABILITY_KEYS if (component, key) not in health]


def _health_d14_d8_healthy(health: Mapping[tuple[str, str], str]) -> bool:
    """Conservative health gate shared by arm and live supervision.

    The emitted health protocol has evolved across CX317 profiles, so accept
    the documented healthy values while requiring both authority components to
    be present.  A missing or unknown value is never silently treated clean.
    """
    d14 = health.get(("pps", "state"), health.get(("d14", "state"), ""))
    d8 = health.get(("frequency_control", "state"), health.get(("d8", "state"), ""))
    return d14.lower() in {"valid", "healthy", "running", "qualified"} and d8.lower() in {"valid", "healthy", "running", "qualified", "frequency_only"}


def _safe_int(value: object) -> int | None:
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        return None


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _reconcile_exact_transaction_timing(
    *, run_dir: Path, transactions: list[dict[str, str]]
) -> dict[str, object]:
    """Require a one-to-one, identity-exact AT2 timing row for every ACT1 row."""

    path = run_dir / "csv" / ACTIVE_TRANSACTIONS_V2_CSV
    if not path.is_file():
        raise ValueError("retained active_transactions_v2 timing evidence is absent")
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ACTIVE_TRANSACTION_V2_FIELDS:
            raise ValueError("active_transactions_v2 retained header differs")
        timings = list(reader)

    transaction_by_sequence: dict[str, dict[str, str]] = {}
    for row in transactions:
        sequence = row.get("transaction_record_sequence", "")
        if not sequence or sequence in transaction_by_sequence:
            raise ValueError("ACT1 transaction sequence is absent or duplicated")
        transaction_by_sequence[sequence] = row

    timing_sequences: list[int] = []
    timestamps: list[int] = []
    seen_transactions: set[str] = set()
    mismatches: list[str] = []
    for row_number, timing in enumerate(timings, start=1):
        if None in timing or any(
            timing.get(field) is None for field in ACTIVE_TRANSACTION_V2_FIELDS
        ):
            raise ValueError(
                f"active_transactions_v2 row {row_number} is malformed"
            )
        try:
            timing_sequence = int(timing["timing_record_sequence"], 10)
            event_ticks = int(timing["event_timestamp_ticks"], 10)
            int(timing["transaction_record_sequence"], 10)
        except ValueError as exc:
            raise ValueError(
                f"active_transactions_v2 row {row_number} counter differs"
            ) from exc
        if (
            timing["record_type"] != "AT2"
            or timing["schema_version"]
            != str(CONTRACT_SCHEMA_VERSIONS["active_transactions_v2"])
            or timing["time_domain"] != EXACT_LIFECYCLE_TIME_DOMAIN
            or timing_sequence <= 0
            or event_ticks < 0
        ):
            raise ValueError(
                f"active_transactions_v2 row {row_number} identity differs"
            )
        timing_sequences.append(timing_sequence)
        timestamps.append(event_ticks)
        transaction_sequence = timing["transaction_record_sequence"]
        source = transaction_by_sequence.get(transaction_sequence)
        if source is None:
            mismatches.append(f"orphan_AT2_sequence={transaction_sequence}")
            continue
        if transaction_sequence in seen_transactions:
            mismatches.append(f"duplicate_AT2_sequence={transaction_sequence}")
            continue
        seen_transactions.add(transaction_sequence)
        differing_fields = [
            field
            for field in ACTIVE_TRANSACTION_TIMING_JOIN_FIELDS
            if timing[field] != source[field]
        ]
        if differing_fields:
            mismatches.append(
                f"AT2_join_mismatch_sequence={transaction_sequence}:"
                + ",".join(differing_fields)
            )

    if any(
        current <= previous
        for previous, current in zip(timing_sequences, timing_sequences[1:])
    ):
        mismatches.append("AT2_timing_record_sequence_not_strictly_increasing")
    if any(current < previous for previous, current in zip(timestamps, timestamps[1:])):
        mismatches.append("AT2_event_timestamp_ticks_moved_backward")
    missing = sorted(set(transaction_by_sequence) - seen_transactions, key=int)
    if missing:
        mismatches.append("missing_AT2_sequence=" + ",".join(missing))
    if mismatches:
        raise ValueError(
            "ACT1/AT2 exact timing reconciliation failed: " + "; ".join(mismatches)
        )
    if not transactions or len(timings) != len(transactions):
        raise ValueError("ACT1/AT2 exact timing reconciliation is incomplete")
    return {
        "time_domain": EXACT_LIFECYCLE_TIME_DOMAIN,
        "ACT1_rows": len(transactions),
        "AT2_rows": len(timings),
        "one_to_one_exact": True,
        "coarse_seconds_used_as_ticks": False,
        "first_event_timestamp_ticks": timestamps[0],
        "last_event_timestamp_ticks": timestamps[-1],
    }


def _exact_application_ticks(
    *, run_dir: Path, transactions: list[dict[str, str]]
) -> list[int]:
    """Return application ticks only after full ACT1/AT2 reconciliation."""

    timings = _read_csv_rows(run_dir / "csv" / ACTIVE_TRANSACTIONS_V2_CSV)
    by_transaction = {
        row["transaction_record_sequence"]: row for row in timings
    }
    result: list[int] = []
    for transaction in transactions:
        if transaction.get("event") != "application":
            continue
        timing = by_transaction.get(transaction["transaction_record_sequence"])
        if timing is None or timing.get("event") != "application":
            raise ValueError("application lacks its exact reconciled AT2 timestamp")
        result.append(int(timing["event_timestamp_ticks"], 10))
    return result


def _validate_exact_application_cadence(
    application_ticks: list[int], *, minimum_cadence_s: int
) -> None:
    minimum_ticks = minimum_cadence_s * TIMER_HZ
    for previous, current in zip(application_ticks, application_ticks[1:]):
        if current <= previous or current - previous < minimum_ticks:
            raise ValueError(
                "frequency-only exact AT2 application cadence is below "
                f"{minimum_cadence_s}s"
            )


def _u32_distance(previous: int, current: int) -> int:
    return (current - previous) & U32_MASK


def _u32_successor(previous: int, current: int) -> bool:
    return _u32_distance(previous, current) == 1


def _unique_rows(
    rows: list[dict[str, str]], field: str
) -> tuple[dict[int, dict[str, str]], set[int]]:
    result: dict[int, dict[str, str]] = {}
    duplicates: set[int] = set()
    for row in rows:
        value = _safe_int(row.get(field))
        if value is None:
            continue
        if value in result:
            duplicates.add(value)
        else:
            result[value] = row
    return result, duplicates


def _application_epoch_at_count_sequence(
    transaction_rows: list[dict[str, str]], count_sequence: int
) -> tuple[int | None, int | None, int | None]:
    manual = [row for row in transaction_rows if row.get("event") == "manual_start"]
    if len(manual) != 1:
        return None, None, None
    epoch = _safe_int(manual[0].get("dac_epoch"))
    code = _safe_int(manual[0].get("applied_code"))
    latest_boundary: int | None = None
    for row in transaction_rows:
        if row.get("event") != "application":
            continue
        boundary = _safe_int(row.get("source_last_sequence"))
        candidate_epoch = _safe_int(row.get("dac_epoch"))
        candidate_code = _safe_int(row.get("applied_code"))
        if boundary is None or candidate_epoch is None or candidate_code is None:
            continue
        # The selected interval ending at source_last_sequence belongs to the
        # pre-write epoch.  Only a causally later count may consume the new DAC
        # epoch; this also prevents a decision-bearing window straddling a write.
        distance = _u32_distance(boundary, count_sequence)
        if 0 < distance < (1 << 31):
            epoch = candidate_epoch
            code = candidate_code
            if latest_boundary is None or _u32_distance(latest_boundary, boundary) < (1 << 31):
                latest_boundary = boundary
    return epoch, code, latest_boundary


def canonical_d14_d8_intervals(run_dir: Path) -> list[dict[str, Any]]:
    """Causally join authoritative D14 REF/SNP and D8 CNT evidence.

    D6 is intentionally absent from this reconstruction.  Its status is a
    separately reported local diagnostic and can neither qualify nor veto an
    authoritative interval.
    """
    # CNT is the producer commit/frontier record: firmware emits and capture
    # flushes its supporting REF and SNP first.  Read the frontier before its
    # support files so a concurrent append cannot expose a new CNT against
    # stale REF/SNP snapshots and turn a transient host read into a permanent
    # one-second exclusion.
    count_rows = _read_csv_rows(run_dir / "csv" / COUNT_OBSERVATIONS_CSV)
    snapshot_rows = _read_csv_rows(run_dir / "csv" / PPS_SNAPSHOTS_CSV)
    raw_rows = _read_csv_rows(run_dir / "csv" / RAW_EVENTS_CSV)
    transaction_rows = _read_csv_rows(run_dir / ACTIVE_CSV)
    snapshots, duplicate_snapshots = _unique_rows(snapshot_rows, "snapshot_sequence")
    counts, duplicate_counts = _unique_rows(count_rows, "count_seq")
    refs_by_ticks: dict[int, list[tuple[int, dict[str, str]]]] = {}
    for position, row in enumerate(raw_rows):
        if (
            row.get("record_type") == "REF"
            and row.get("schema_version") == "1"
            and row.get("channel_id") == "1"
            and row.get("edge") == "R"
            and row.get("capture_domain") == "rp2040_timer0"
        ):
            timestamp = _safe_int(row.get("timestamp_ticks"))
            if timestamp is not None:
                refs_by_ticks.setdefault(timestamp, []).append((position, row))
    result: list[dict[str, Any]] = []
    previous_count_sequence: int | None = None
    # Preserve the retained producer order.  Sorting a uint32 sequence would
    # invert the stream at rollover and reject an otherwise exact ledger.
    ordered_sequences: list[int] = []
    seen_count_sequences: set[int] = set()
    for count in count_rows:
        sequence = _safe_int(count.get("count_seq"))
        if sequence is None or sequence in seen_count_sequences:
            continue
        seen_count_sequences.add(sequence)
        ordered_sequences.append(sequence)
    for sequence in ordered_sequences:
        count = counts[sequence]
        opening = snapshots.get((sequence - 1) & U32_MASK)
        closing = snapshots.get(sequence)
        reasons: list[str] = []
        if sequence in duplicate_counts:
            reasons.append("duplicate_count_sequence")
        if sequence in duplicate_snapshots:
            reasons.append("duplicate_closing_snapshot_sequence")
        if opening is None:
            reasons.append("missing_opening_snapshot")
        if closing is None:
            reasons.append("missing_closing_snapshot")
        if previous_count_sequence is not None and not _u32_successor(
            previous_count_sequence, sequence
        ):
            reasons.append("nonconsecutive_count_sequence")
        previous_count_sequence = sequence
        opening_ticks = _safe_int(count.get("gate_open_ticks"))
        closing_ticks = _safe_int(count.get("gate_close_ticks"))
        counted_edges = _safe_int(count.get("counted_edges"))
        count_flags = _safe_int(count.get("flags"))
        if (
            count.get("record_type") != "CNT"
            or count.get("schema_version") != "1"
        ):
            reasons.append("count_record_identity_mismatch")
        if count.get("channel_id") != "2" or count.get("source_edge") != "R":
            reasons.append("d8_count_wire_identity_mismatch")
        if count.get("gate_domain") != "rp2040_timer0":
            reasons.append("count_gate_domain_mismatch")
        if count.get("source_domain") != "h1_cx317_ocxo_10mhz":
            reasons.append("count_source_domain_mismatch")
        if count_flags is None or count_flags & COUNT_INVALID_FLAGS:
            reasons.append("count_invalid_flags")
        progress = None
        if opening_ticks is None or closing_ticks is None:
            reasons.append("count_gate_ticks_missing")
        else:
            progress = forward_progress(
                opening_ticks,
                closing_ticks,
                domain="rp2040_timer0",
                allow_equal=False,
            )
            if not progress.valid:
                reasons.append(f"count_gate_progress_{progress.reason}")
        session: int | None = None
        opening_reference_sequence: int | None = None
        closing_reference_sequence: int | None = None
        if opening is not None and closing is not None:
            if any(
                row.get("record_type") != "SNP"
                or row.get("schema_version") != "1"
                for row in (opening, closing)
            ):
                reasons.append("snapshot_record_identity_mismatch")
            opening_status = _safe_int(opening.get("status"))
            closing_status = _safe_int(closing.get("status"))
            if opening_status != 0 or closing_status != 0:
                reasons.append("snapshot_status_invalid")
            if any(
                row.get("backend") != EXPECTED_D8_SNAPSHOT_BACKEND
                for row in (opening, closing)
            ):
                reasons.append("snapshot_backend_mismatch")
            opening_session = _safe_int(opening.get("session"))
            closing_session = _safe_int(closing.get("session"))
            if opening_session is None or opening_session != closing_session:
                reasons.append("capture_session_change")
            else:
                session = closing_session
            opening_snapshot_sequence = _safe_int(opening.get("snapshot_sequence"))
            closing_snapshot_sequence = _safe_int(closing.get("snapshot_sequence"))
            if (
                opening_snapshot_sequence is None
                or closing_snapshot_sequence is None
                or not _u32_successor(opening_snapshot_sequence, closing_snapshot_sequence)
            ):
                reasons.append("nonconsecutive_snapshot_sequence")
            opening_reference_sequence = _safe_int(opening.get("reference_sequence"))
            closing_reference_sequence = _safe_int(closing.get("reference_sequence"))
            if (
                opening_reference_sequence is None
                or closing_reference_sequence is None
                or not _u32_successor(opening_reference_sequence, closing_reference_sequence)
            ):
                reasons.append("nonconsecutive_d14_reference_sequence")
            if closing_snapshot_sequence != sequence:
                reasons.append("count_closing_snapshot_sequence_mismatch")
            opening_reference_ticks = _safe_int(opening.get("reference_timestamp_ticks"))
            closing_reference_ticks = _safe_int(closing.get("reference_timestamp_ticks"))
            if opening_ticks != opening_reference_ticks:
                reasons.append("count_gate_open_snapshot_mismatch")
            if closing_ticks != closing_reference_ticks:
                reasons.append("count_gate_close_snapshot_mismatch")
            opening_counter = _safe_int(opening.get("cumulative_down_counter"))
            closing_counter = _safe_int(closing.get("cumulative_down_counter"))
            if (
                opening_counter is None
                or closing_counter is None
                or counted_edges is None
                or ((opening_counter - closing_counter) & U32_MASK) != counted_edges
            ):
                reasons.append("snapshot_count_parity_mismatch")
            opening_refs = refs_by_ticks.get(opening_reference_ticks or -1, [])
            closing_refs = refs_by_ticks.get(closing_reference_ticks or -1, [])
            if len(opening_refs) != 1:
                reasons.append("opening_d14_raw_event_not_unique")
            if len(closing_refs) != 1:
                reasons.append("closing_d14_raw_event_not_unique")
            if len(opening_refs) == 1 and len(closing_refs) == 1:
                opening_position, opening_ref = opening_refs[0]
                closing_position, closing_ref = closing_refs[0]
                if closing_position != opening_position + 1:
                    reasons.append("d14_raw_event_stream_not_adjacent")
                opening_flags = _safe_int(opening_ref.get("flags"))
                closing_flags = _safe_int(closing_ref.get("flags"))
                if (
                    opening_flags is None
                    or closing_flags is None
                    or opening_flags & REFERENCE_INVALID_FLAGS
                    or closing_flags & REFERENCE_INVALID_FLAGS
                ):
                    reasons.append("d14_raw_event_invalid_flags")
        dac_epoch, applied_code, last_application_sequence = (
            _application_epoch_at_count_sequence(transaction_rows, sequence)
        )
        if dac_epoch is None or applied_code is None:
            reasons.append("applied_dac_epoch_identity_unavailable")
        duration_ticks = progress.distance_ticks if progress and progress.valid else None
        frequency_error_hz: float | None = None
        if duration_ticks and counted_edges is not None:
            # This is a D14-relative one-reference-interval observation.  The
            # RP2040 timer measures capture aperture diagnostics; it is not the
            # frequency reference and must not redefine a GNSS-PPS second.
            frequency_error_hz = float(counted_edges - 10_000_000)
        settling_complete = bool(
            last_application_sequence is None
            or _u32_distance(last_application_sequence, sequence) > 900
        )
        result.append(
            {
                "count_sequence": sequence,
                "session": session,
                "opening_reference_sequence": opening_reference_sequence,
                "closing_reference_sequence": closing_reference_sequence,
                "opening_ticks": opening_ticks,
                "closing_ticks": closing_ticks,
                "duration_ticks": duration_ticks,
                "counted_edges": counted_edges,
                "frequency_error_hz": frequency_error_hz,
                "dac_epoch": dac_epoch,
                "applied_code": applied_code,
                "last_application_source_sequence": last_application_sequence,
                "settling_complete": settling_complete,
                "measurement_qualified": not reasons,
                "exclusion_reasons": reasons,
            }
        )
    return result


def gnss_metadata_hold_oracle_fact(
    *, capture_session: str, frontier: int, applied_code: int, dac_epoch: int
) -> dict[str, Any]:
    """Project a hold for deterministic rehearsal comparison only.

    Live authority comes from the firmware-emitted hold state and the exact
    supervisor checks below; this oracle cannot activate or clear a hold.
    """
    state = Cx322OperationalState(
        mode=OperationalMode.ACTIVE,
        capture_session=capture_session,
        measurement_frontier=frontier,
        last_confirmed_code=applied_code,
        last_confirmed_dac_epoch=dac_epoch,
        metadata_sequence=0,
        phase_epoch=None,
        phase_frontier=None,
        phase_evidence_qualified=False,
        rearm_inhibit_reason="none",
        d9_output_valid=True,
        d9_output_reason="digital_readback_exact_waveform_unqualified",
    )
    transition = metadata_loss(
        state, request_state=RequestReleaseState.OUTCOME_RESOLVED
    )
    return {
        "mode": transition.state.mode.value,
        "action": transition.action,
        "measurement_continues": transition.measurement_continues,
        "effective_actuation_permitted": transition.effective_actuation_permitted,
        "control_rearm_eligible": transition.control_rearm_eligible,
        "last_confirmed_code": transition.state.last_confirmed_code,
        "last_confirmed_dac_epoch": transition.state.last_confirmed_dac_epoch,
    }


def _metadata_hold_active(health: Mapping[tuple[str, str], str]) -> bool:
    state = health.get(("cx317_active", "state"), "")
    reason = health.get(("cx317_active", "reason"), "").lower()
    return state == "GNSS_METADATA_HOLD" or (
        state == "REFERENCE_HOLD" and any(token in reason for token in ("gnss", "metadata"))
    )


def _confirmed_hold_identity(
    health: Mapping[tuple[str, str], str],
) -> dict[str, int]:
    if health.get(("cx317_active", "confirmed_applied_code_known")) != "true":
        raise ValueError("GNSS metadata hold lacks confirmed applied DAC identity")
    values = {
        "session_id": _safe_int(health.get(("cx317_active", "session_id"))),
        "applied_code": _safe_int(
            health.get(("cx317_active", "confirmed_applied_code"))
        ),
        "dac_epoch": _safe_int(health.get(("cx317_active", "dac_epoch"))),
        "correction_count": _safe_int(
            health.get(("cx317_active", "correction_count"))
        ),
        "cumulative_movement_codes": _safe_int(
            health.get(("cx317_active", "cumulative_movement_codes"))
        ),
    }
    missing = [key for key, value in values.items() if value is None]
    if missing:
        raise ValueError(
            "GNSS metadata hold emitted identity is incomplete: "
            + ", ".join(missing)
        )
    return {key: int(value) for key, value in values.items()}


def _correction_admission_closed(qualified_ticks: int, target_ticks: int) -> bool:
    return qualified_ticks >= target_ticks - APPLICATION_ADMISSION_RESERVE_S * TIMER_HZ


def _counter_checkpoint(accounting: EnduranceSupervisor) -> dict[str, Any]:
    state = accounting.state_fields()
    return {
        key: state[key]
        for key in (
            "armed_ticks",
            "qualified_ticks",
            "milestones_qualified_s",
            "elapsed_ticks",
            "last_closing_ticks",
            "last_qualified_count_sequence",
            "target_reached",
            "invalid_interval_count",
            "counter_terminal",
        )
    }


def _read_interval_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    previous: int | None = None
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"qualified interval ledger line {line_number} is not an object")
        sequence = _safe_int(row.get("count_sequence"))
        checkpoint = row.get("counter_accounting_after")
        if sequence is None or not isinstance(checkpoint, dict):
            raise ValueError(
                f"qualified interval ledger line {line_number} lacks its restart checkpoint"
            )
        if _safe_int(checkpoint.get("processed_count_sequence")) != sequence:
            raise ValueError(
                f"qualified interval ledger line {line_number} checkpoint identity differs"
            )
        if previous is not None and not _u32_successor(previous, sequence):
            raise ValueError(
                f"qualified interval ledger line {line_number} is not the uint32 successor"
            )
        previous = sequence
        rows.append(row)
    return rows


def _read_opportunity_causal_ledger(
    path: Path,
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    if not path.is_file():
        return [], {}
    events: list[dict[str, Any]] = []
    opportunities: dict[int, dict[str, Any]] = {}
    previous_sha = "0" * 64
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"opportunity ledger line {line_number} is not an object")
        declared_sha = row.get("record_sha256")
        unsigned = {key: value for key, value in row.items() if key != "record_sha256"}
        if (
            row.get("ledger_record_sequence") != len(events) + 1
            or row.get("prior_record_sha256") != previous_sha
            or declared_sha != canonical_sha256(unsigned)
        ):
            raise ValueError(f"opportunity ledger line {line_number} chain differs")
        sequence = _safe_int(row.get("control_sequence"))
        if sequence is None:
            raise ValueError(f"opportunity ledger line {line_number} lacks control sequence")
        event = row.get("event")
        if event == "opportunity_observed":
            if sequence in opportunities:
                raise ValueError(f"duplicate opportunity sequence {sequence} in ledger")
            opportunities[sequence] = dict(row)
        elif event == "opportunity_resolved":
            retained = opportunities.get(sequence)
            if retained is None or retained.get("resolved") is True:
                raise ValueError(f"invalid opportunity resolution sequence {sequence}")
            if row.get("control_identity_sha256") != retained.get(
                "control_identity_sha256"
            ):
                raise ValueError(f"opportunity resolution identity differs for {sequence}")
            retained.update(
                {
                    "resolved": True,
                    "disposition": row.get("disposition"),
                    "resolution_evidence": row.get("resolution_evidence"),
                    "resolution_transaction_record_sequence": row.get(
                        "resolution_transaction_record_sequence"
                    ),
                    "resolution_reason": row.get("resolution_reason"),
                }
            )
        elif event == "opportunity_reclassified":
            retained = opportunities.get(sequence)
            if (
                retained is None
                or retained.get("resolved") is not True
                or row.get("control_identity_sha256")
                != retained.get("control_identity_sha256")
                or row.get("prior_disposition") != retained.get("disposition")
                or retained.get("disposition") != "ineligible_not_authorized"
                or retained.get("resolution_evidence")
                != "control_previews_v1.authority_flags"
                or row.get("disposition") != "applied"
                or row.get("resolution_evidence")
                != "active_transactions_v1.application"
                or _safe_int(row.get("resolution_transaction_record_sequence"))
                is None
            ):
                raise ValueError(
                    f"invalid opportunity reclassification sequence {sequence}"
                )
            retained.update(
                {
                    "eligible_control_opportunity": True,
                    "disposition": "applied",
                    "resolution_evidence": row.get("resolution_evidence"),
                    "resolution_transaction_record_sequence": row.get(
                        "resolution_transaction_record_sequence"
                    ),
                    "resolution_reason": row.get("resolution_reason"),
                }
            )
        else:
            raise ValueError(f"opportunity ledger line {line_number} event differs")
        events.append(row)
        previous_sha = str(declared_sha)
    observed = list(opportunities)
    for previous, current in zip(observed, observed[1:]):
        if not _u32_successor(previous, current):
            raise ValueError(
                f"opportunity ledger control sequence gap: {previous} -> {current}"
            )
    return events, opportunities


def _append_opportunity_event(path: Path, payload: Mapping[str, Any]) -> None:
    events, _ = _read_opportunity_causal_ledger(path)
    unsigned = {
        "schema_version": 1,
        "ledger_record_sequence": len(events) + 1,
        "prior_record_sha256": (
            str(events[-1]["record_sha256"]) if events else "0" * 64
        ),
        **payload,
    }
    row = {**unsigned, "record_sha256": canonical_sha256(unsigned)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def create_live_manifest(
    *,
    run_dir: Path,
    activation_path: Path,
    activation: Mapping[str, Any],
    resolved_device: str,
    board_identity: Mapping[str, Any],
    firmware_entry: Mapping[str, Any],
) -> dict[str, Any]:
    """Create the immutable operational manifest before the carrier opens.

    ``resolved_device`` is recorded solely as the observed fresh enumeration.
    The capture command still receives ``--auto-detect`` and validates a new
    enumeration against it before owning the port.
    """
    checked_activation, checked = validate_activation(activation)
    activation_path = activation_path.resolve()
    if _read(activation_path) != checked_activation:
        raise ValueError("live activation artifact path/content differs")
    if not resolved_device.startswith("/dev/"):
        raise ValueError("fresh auto-detect did not return a device path")
    firmware_entry_unsigned = {
        key: value for key, value in firmware_entry.items() if key != "record_sha256"
    }
    reservation_binding = firmware_entry.get("upload_attempt_reservation")
    if not isinstance(reservation_binding, Mapping):
        raise ValueError("live firmware-entry upload reservation is absent")
    reservation_path = Path(str(reservation_binding.get("path", "")))
    if dict(reservation_binding) != _binding(reservation_path):
        raise ValueError("live firmware-entry upload reservation binding differs")
    reservation = _read(reservation_path)
    _validate_upload_attempt_reservation(
        reservation,
        activation=checked_activation,
        bundle=checked,
        run_dir=run_dir,
    )
    if (
        firmware_entry.get("record_sha256")
        != canonical_sha256(firmware_entry_unsigned)
        or firmware_entry.get("status") != "passed"
        or firmware_entry.get("firmware_flash_count") != 1
        or firmware_entry.get("automatic_retry_performed") is not False
        or firmware_entry.get("device_after") != resolved_device
        or firmware_entry.get("board_after") != dict(board_identity)
        or firmware_entry.get("activation_sha256")
        != checked_activation["activation_sha256"]
        or firmware_entry.get("bundle_sha256") != checked["bundle_sha256"]
        or firmware_entry.get("fqbn") != checked["firmware"]["fqbn"]
        or firmware_entry.get("uf2_sha256")
        != checked["firmware"]["uf2"]["sha256"]
        or firmware_entry.get("upload_attempt_reservation_record_sha256")
        != reservation["record_sha256"]
    ):
        raise ValueError("live firmware-entry record differs from activation")
    firmware_entry_path = run_dir / FIRMWARE_ENTRY_PATH
    if _read(firmware_entry_path) != dict(firmware_entry):
        raise ValueError("retained live firmware-entry record differs")
    capture_contract = _exact_capture_contract()
    files = list(capture_contract["files"])
    retained_reservation_path = run_dir / RETAINED_UPLOAD_ATTEMPT_PATH
    _write_new(retained_reservation_path, reservation)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "compatibility_floor": EVIDENCE_EPOCH,
        "template": False,
        "run_id": run_dir.name,
        "created_utc": _utc_now(),
        "started_at_utc": _utc_now(),
        "stage": LIVE_STAGE,
        "qualification_evidence": True,
        "actionable": True,
        "actuation_authorized": True,
        "frequency_only_engineering": {
            "contract_id": load_contract()["contract_id"],
            "profile_id": checked["profile_id"],
            "bundle_sha256": checked["bundle_sha256"],
            "activation_sha256": checked_activation["activation_sha256"],
            "activation_artifact": _binding(activation_path),
            "d9_required_state": load_contract()["d9"]["required_state"],
            "d6_control_authority": False,
            "d9_control_authority": False,
            "phase_or_hybrid_authority": False,
            "digital_endurance_only": True,
        },
        "firmware": {
            "build_provenance_required": True,
            "build_manifest_sha256": checked["firmware"]["build_manifest"]["sha256"],
            "source_revision": checked["firmware"]["source_revision"],
            "source_sha256": checked["firmware"]["source_sha256"],
            "configuration_sha256": checked["firmware"]["configuration_sha256"],
            "build_identity": checked["firmware"]["build_identity"],
            "fqbn": checked["firmware"]["fqbn"],
            "uf2": checked["firmware"]["uf2"],
            "entry_record": _binding(firmware_entry_path),
            "entry_record_sha256": firmware_entry["record_sha256"],
            "upload_attempt_reservation": _binding(reservation_path),
            "retained_upload_attempt_reservation": _binding(
                retained_reservation_path
            ),
            "board_identity_after_upload": dict(board_identity),
        },
        "host": {
            "capture_tool": "host.otis_tools.capture_device",
            "supervisor_tool": TOOL_ID,
            "serial_selection": "fresh_auto_detect_each_enumeration",
            "observed_fresh_device": resolved_device,
            "baud": 115200,
            "sole_serial_owner": True,
            "independent_abort_fifo": str(ABORT_FIFO_PATH),
            "rotation_capability": CAPABILITY,
            "post_upload_fresh_device": resolved_device,
            "capture_performs_own_auto_detect_before_open": True,
        },
        "finite_timing": {
            "authority_and_wall_terminal_s": int(
                load_contract()["envelope"]["absolute_wall_limit_s"]
            ),
            "capture_duration_s": int(
                load_contract()["envelope"]["absolute_wall_limit_s"]
            )
            + CAPTURE_EVIDENCE_DRAIN_MARGIN_S,
            "post_terminal_evidence_drain_and_abort_margin_s": (
                CAPTURE_EVIDENCE_DRAIN_MARGIN_S
            ),
        },
        "domains": capture_contract["domains"],
        "channels": [
            {"channel_id": 1, "role": "authoritative_d14_reference", "record_family": "raw_events_v1"},
            {"channel_id": 2, "role": "authoritative_d8_count", "record_family": "count_observations_v1"},
            {"channel_id": 3, "role": "diagnostic_d6_forwarded_d9_monitor", "record_family": "forwarded_monitor_snapshots_v1", "authority": "diagnostic_only", "control_authority": False, "terminal_authority": False},
        ],
        "contracts": capture_contract["contracts"],
        "files": files,
        "evidence_artifacts": [
            "inputs/live_activation.json", "inputs/frozen_bundle.json",
            "inputs/firmware_build_manifest.json",
            str(SUPERVISOR_STATE_PATH), str(SUPERVISOR_EVENTS_PATH),
            "reports/capture_device_state.json", "reports/capture_segment_closure_v1.json",
            str(FIRMWARE_ENTRY_PATH), str(RUN_LIFECYCLE_PATH),
            str(RETAINED_UPLOAD_ATTEMPT_PATH),
            str(ANALYSIS_PATH), str(SEAL_PATH), "COMPLETE",
        ],
        "known_limitations": [
            "Engineering digital/non-interference endurance only; D9 waveform evidence remains unresolved.",
            "D6 is a local diagnostic sidecar and cannot qualify D14/D8 or steering.",
            "No voltage, duty-cycle, edge, ringing, load, propagation-delay, jitter, or independently referenced frequency claim is made.",
        ],
    }
    _write_new(run_dir / "run_manifest.json", manifest)
    _write_new(run_dir / "inputs/live_activation.json", checked_activation)
    _write_new(run_dir / "inputs/frozen_bundle.json", checked)
    source_build = Path(str(checked["firmware"]["build_manifest"]["path"]))
    _write_new(run_dir / "inputs/firmware_build_manifest.json", _read(source_build))
    return manifest


def live_capture_command(*, run_dir: Path, expected_device: str, duration_s: int) -> list[str]:
    """The sole hardware-opening command for a live run.

    It never accepts a retained device path as a selection input.
    """
    if duration_s <= 0:
        raise ValueError("live duration must be positive")
    return [
        sys.executable, "-m", "host.otis_tools.capture_device", "--auto-detect",
        "--expected-auto-detect-device", expected_device, "--baud", "115200",
        "--run-dir", str(run_dir), "--duration-s", str(duration_s),
        "--status-interval", "5", "--command-fifo", str(run_dir / "control/normal_commands.fifo"),
        "--emergency-command-fifo", str(run_dir / "control/emergency_abort.fifo"),
        "--write-timeout-s", "1", "--normal-command-max-age-s", "2",
        "--segment-control-dir", str(run_dir / "control/segment_carrier"),
        "--segment-capability", CAPABILITY,
    ]


@dataclass
class FrequencyOnlyLiveSupervisor:
    """Consume only retained capture records and hold fail-static on faults.

    It deliberately emits no DAC command.  It can account for firmware FLL
    transactions that appear in the canonical stream, but phase/hybrid or an
    out-of-envelope transaction terminates the engineering programme.  This
    keeps control authority with the frozen firmware/transaction contract and
    prevents an ad-hoc host controller from becoming a second actuator.
    """

    run_dir: Path
    bundle: Mapping[str, Any]
    contract: Mapping[str, Any]
    accounting: EnduranceSupervisor = field(init=False)
    consumed_count_sequences: set[int] = field(default_factory=set)
    consumed_transaction_sequences: set[int] = field(default_factory=set)
    d6_missing: list[str] = field(default_factory=list)
    arm_error: str | None = None
    abort_delivery: str | None = None
    started_monotonic: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self.accounting = EnduranceSupervisor(self.contract)

    @property
    def normal_fifo(self) -> Path:
        return self.run_dir / "control/normal_commands.fifo"

    @property
    def emergency_fifo(self) -> Path:
        return self.run_dir / "control/emergency_abort.fifo"

    def _event(self, event: str, **detail: object) -> None:
        path = self.run_dir / SUPERVISOR_EVENTS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"utc": _utc_now(), "event": event, **detail}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _state(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "tool": TOOL_ID,
            "updated_utc": _utc_now(),
            "bundle_sha256": self.bundle["bundle_sha256"],
            "armed_ticks": self.accounting.armed_ticks,
            "qualified_ticks": self.accounting.qualified_ticks,
            "qualified_duration_s": self.accounting.qualified_ticks / TIMER_HZ,
            "milestones_qualified_s": self.accounting.milestones,
            "terminal": self.accounting.terminal,
            "setup_establishments": self.accounting.setup_establishments,
            "automatic_applications": self.accounting.automatic_applications,
            "cumulative_movement_codes": self.accounting.cumulative_movement_codes,
            "d6_missing_observability": self.d6_missing,
            "arm_error": self.arm_error,
            "abort_delivery": self.abort_delivery,
            "supervisor_elapsed_s": time.monotonic() - self.started_monotonic,
            "automatic_dac_commands_sent_by_host": 0,
            "phase_or_hybrid_commands_sent_by_host": 0,
        }

    def publish(self) -> None:
        _write_replace(self.run_dir / SUPERVISOR_STATE_PATH, self._state())

    def arm_from_health(self) -> bool:
        health = _latest_health(self.run_dir / "csv/health.csv")
        missing, mismatches = _d9_gate(health)
        self.d6_missing = _d6_observability(health)
        # The live supervisor does not invent a DAC/epoch.  The emitted health
        # record is the only acceptable arm source; variant names are explicit
        # so a missing firmware field rejects rather than defaulting.
        code = _safe_int(health.get(("dac", "applied_code"), health.get(("cx317_active", "applied_code"))))
        epoch = _safe_int(health.get(("dac", "epoch"), health.get(("cx317_active", "dac_epoch"))))
        outstanding = health.get(("cx317_active", "transaction_outstanding"), "false").lower() == "true"
        frontier = _safe_int(health.get(("forwarded_clock_output", "first_valid_ticks")))
        if missing or frontier is None or code is None or epoch is None or not _health_d14_d8_healthy(health):
            # Startup absence is a bounded freshness wait, not immediate
            # contradictory evidence.  The caller turns it into a terminal
            # only at the frozen startup deadline.
            self.arm_error = "; ".join([*missing, "missing_or_unhealthy_d14_d8_or_dac_state"])
            self.publish()
            return False
        if mismatches:
            self.arm_error = "; ".join(mismatches)
            self.accounting.terminal = "frequency_only_d9_d6_invalid_due_to_identity_or_evidence_failure"
            self._event("arm_rejected", reason=self.arm_error, d6_missing=self.d6_missing)
            self.publish()
            return False
        try:
            self.accounting.arm(frontier_ticks=frontier, d9_state=health[("forwarded_clock_output", "state")], d9_readback_exact=True, d14_d8_healthy=True, outstanding_transaction=outstanding, applied_code=code, dac_epoch=epoch)
        except ValueError as exc:
            self.arm_error = str(exc)
            self.accounting.terminal = "frequency_only_d9_d6_invalid_due_to_identity_or_evidence_failure"
            self._event("arm_rejected", reason=self.arm_error)
            self.publish()
            return False
        self._event("soak_armed", frontier_ticks=frontier, dac_code=code, dac_epoch=epoch, d6_missing=self.d6_missing)
        self.publish()
        return True

    def _observe_counts(self, health: Mapping[tuple[str, str], str]) -> None:
        path = self.run_dir / "csv/count_observations.csv"
        if not path.is_file():
            return
        d9_valid = not _d9_gate(health)[0] and not _d9_gate(health)[1]
        with path.open("r", newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                sequence = _safe_int(row.get("count_seq"))
                opening = _safe_int(row.get("gate_open_ticks"))
                closing = _safe_int(row.get("gate_close_ticks"))
                if sequence is None or opening is None or closing is None or sequence in self.consumed_count_sequences:
                    continue
                self.consumed_count_sequences.add(sequence)
                exact_interval = (
                    row.get("channel_id") == "2"
                    and row.get("gate_domain") == "rp2040_timer0"
                    and row.get("flags") == "0"
                    and closing > opening
                )
                before = list(self.accounting.milestones)
                self.accounting.observe_interval(opening_ticks=opening, closing_ticks=closing, measurement_qualified=exact_interval, d9_valid=d9_valid)
                for milestone in self.accounting.milestones[len(before):]:
                    self._event("qualified_milestone", qualified_duration_s=milestone, count_seq=sequence)

    def _observe_transactions(self) -> None:
        path = self.run_dir / "csv/active_transactions.csv"
        if not path.is_file():
            return
        with path.open("r", newline="", encoding="utf-8") as handle:
            transaction_rows = list(csv.DictReader(handle))
        timing_rows = _read_csv_rows(
            self.run_dir / "csv" / ACTIVE_TRANSACTIONS_V2_CSV
        )
        # ACT1 is published immediately before AT2.  A poll between them is a
        # freshness gap, not evidence failure; retain no consumption mark and
        # retry once the exact sidecar catches up.
        if len(timing_rows) < len(transaction_rows):
            return
        _reconcile_exact_transaction_timing(
            run_dir=self.run_dir, transactions=transaction_rows
        )
        applications = [
            row for row in transaction_rows if row.get("event") == "application"
        ]
        application_ticks_by_record = {
            row["transaction_record_sequence"]: ticks
            for row, ticks in zip(
                applications,
                _exact_application_ticks(
                    run_dir=self.run_dir, transactions=transaction_rows
                ),
            )
        }
        for row in transaction_rows:
            sequence = _safe_int(row.get("transaction_record_sequence"))
            if sequence is None or sequence in self.consumed_transaction_sequences:
                continue
            self.consumed_transaction_sequences.add(sequence)
            event = row.get("event", "")
            if event not in {"manual_start", "application"}:
                continue
            requested = _safe_int(row.get("requested_delta_codes"))
            # Presence of any active phase/hybrid semantics is a terminal;
            # strings are deliberately checked before no-op application.
            state = row.get("active_state", "").lower()
            phase_or_hybrid = "phase" in state or "hybrid" in state
            if requested is None:
                self.accounting.terminal = "frequency_only_d9_d6_controller_or_transaction_fault"
                self._event("transaction_rejected", transaction_sequence=sequence, reason="malformed_transaction_fields")
                continue
            exact_ticks = (
                0
                if event == "manual_start"
                else application_ticks_by_record[
                    row["transaction_record_sequence"]
                ]
            )
            self.accounting.record_fll_transaction(setup_establishment=(event == "manual_start"), requested_delta_codes=requested, application_ticks=exact_ticks, phase_or_hybrid=phase_or_hybrid, decision_sequence=_safe_int(row.get("decision_sequence")))
            self._event("observed_fll_transaction", transaction_sequence=sequence, event_name=event, requested_delta_codes=requested, phase_or_hybrid=phase_or_hybrid)

    def poll(self) -> None:
        health = _latest_health(self.run_dir / "csv/health.csv")
        self.d6_missing = _d6_observability(health)
        if self.accounting.armed_ticks is not None and self.accounting.terminal is None:
            missing, mismatches = _d9_gate(health)
            if missing or mismatches:
                self.accounting.terminal = "frequency_only_d9_d6_digital_noninterference_failed"
                self._event("d9_noninterference_terminal", missing=missing, mismatches=mismatches)
            else:
                self._observe_counts(health)
                self._observe_transactions()
        self.publish()

    def forward_abort_and_confirm_delivery(self, timeout_s: float = 15.0) -> None:
        """Keep the serial owner alive until the priority record is retained."""
        self._event("independent_abort_requested")
        send_command_to_fifo(self.emergency_fifo, "ACTIVE ABORT")
        deadline = time.monotonic() + timeout_s
        raw_path = self.run_dir / "raw/serial.log"
        while time.monotonic() < deadline:
            if any(item.get("event") == "emergency_abort_sent" for item in _markers(raw_path)):
                self.abort_delivery = "capture_priority_abort_sent"
                self.accounting.terminal = "operator_abort"
                self._event("independent_abort_delivered")
                self.publish()
                return
            time.sleep(0.05)
        self.abort_delivery = "bounded_delivery_failure"
        self.accounting.terminal = "frequency_only_d9_d6_invalid_due_to_identity_or_evidence_failure"
        self._event("independent_abort_delivery_failure")
        self.publish()
        raise TimeoutError("independent abort was not delivered by capture within bound")


class D9D6FrequencyOnlyEnduranceSupervisor(FrequencyControlSupervisor):
    """24-hour/D9-D6 overlay on the established active transaction engine."""

    def __init__(self, *, bundle: Mapping[str, Any], **kwargs: object) -> None:
        contract = load_contract()
        _, inherited_identities, inherited_leg = load_no_write_qualification_spec("A")
        firmware = bundle["firmware"]
        if not isinstance(firmware, Mapping):
            raise ValueError("frozen firmware binding is absent")
        spec = CampaignSpec(
            campaign="d9_d6_frequency_only_digital_endurance",
            profile=contract["profile_id"],
            run_identity="d9_d6_frequency_only_endurance:1",
            start_code=int(str(contract["starting_dac"]["exact_setup_code"]), 0),
            correction_limit=int(contract["envelope"]["maximum_automatic_applications"]),
            cumulative_limit=int(contract["envelope"]["maximum_cumulative_movement_codes"]),
            minimum_code=0xA800,
            maximum_code=0xAB00,
            maximum_step=int(contract["envelope"]["maximum_step_codes"]),
        )
        super().__init__(
            mode="live", leg=TightDeadbandLeg("A", inherited_leg.required_direction, inherited_leg.required_direction_name),
            allow_manual_start=True, allow_arm=True, spec=spec,
            identities=inherited_identities,
            tight_deadband_policy_sha256=inherited_identities[
                "active_policy_sha256"
            ],
            expected_build_identity=str(firmware["build_identity"]),
            prewrite_contract_startup_grace_s=float(contract["envelope"]["initial_qualification_deadline_s"]),
            # This inherited value controls only the legacy wall-clock response
            # horizon.  Keep it beyond the live wall ceiling; the overlay below
            # closes admission and terminates solely in retained TIMER0 ticks.
            qualified_timeout_s=(
                int(contract["envelope"]["absolute_wall_limit_s"])
                + CORRECTION_RESPONSE_RESERVE_S
                + 1
            ),
            observational_responses=True,
            **kwargs,
        )
        self.bundle = bundle
        self.contract = contract
        ledger_rows = _read_interval_ledger(
            self.run_dir / QUALIFIED_INTERVAL_LEDGER_PATH
        )
        restored_state = dict(self.state)
        if ledger_rows:
            restored_state.update(ledger_rows[-1]["counter_accounting_after"])
        self.accounting = EnduranceSupervisor.from_state(contract, restored_state)
        self.consumed_count_sequences = {
            int(row["count_sequence"]) for row in ledger_rows
        }
        self.state.setdefault("programme_id", contract["contract_id"])
        self.state.setdefault("d9_d6_overlay", True)
        self.state.setdefault("d9_exact_readback_established", False)
        self.state.setdefault("d9_exact_readback_established_utc", None)
        self.state.setdefault("exact_setup_code", "0xA808")
        self.state.setdefault("qualified_counter_domain", "rp2040_timer0")
        self.state.setdefault("soak_armed_frontier_ticks", self.accounting.armed_ticks)
        self.state.setdefault("soak_armed_count_sequence", None)
        self.state.setdefault("d6_missing_observability", [])
        self.state.setdefault("lost_opportunity_dispositions", {})
        _, retained_opportunities = _read_opportunity_causal_ledger(
            self.run_dir / OPPORTUNITY_CAUSAL_LEDGER_PATH
        )
        self.state.setdefault("last_opportunity_decision_sequence", None)
        self.state.setdefault("control_opportunity_count", len(retained_opportunities))
        self.state.setdefault("eligible_control_opportunity_count", 0)
        self.state.setdefault("pending_control_opportunity_sequences", [])
        self.state.setdefault("gnss_metadata_hold_active", False)
        self.state.setdefault("gnss_metadata_hold_count", 0)
        self.state.setdefault("gnss_metadata_hold_oracle", None)
        self.state.setdefault("gnss_metadata_hold_identity", None)
        self.state.setdefault("transaction_outstanding_high_watermark", 0)
        self.state.setdefault("first_complete_application_path_observed", False)
        self._d9_configuration_wait_started_monotonic = time.monotonic()
        self.state.update(self.accounting.state_fields())
        self._save()

    def _prewrite_readiness(
        self, health: dict[tuple[str, str], str]
    ) -> PrewriteReadiness:
        """Bind setup authority to the exact GNSS and D9/D6 boot state."""

        identity = {
            "run_identity": self.spec.run_identity,
            "build_identity": self.expected_build_identity,
            "profile_identity": self.spec.profile,
            **self.identities,
        }
        readiness = evaluate_setup_prewrite_readiness(
            health,
            expected_identity=identity,
            planned_live_stimulus_code=self.spec.start_code,
            active_row_count=len(_read_csv_rows(self.run_dir / ACTIVE_CSV)),
            dac_row_count=len(
                _read_csv_rows(self.run_dir / "csv" / "dac_steps.csv")
            ),
            telemetry_drop_baseline=0,
        )
        mismatches = list(readiness.mismatches)
        if health.get(("cx317_active", "query_nonce")) != str(
            self.state["host_attach_query_nonce"]
        ):
            mismatches.append("solicited post-attachment snapshot is absent")
        return PrewriteReadiness(
            contract_id=(
                "d9_d6_frequency_only_active_prewrite_runtime_contract_v1"
            ),
            ready=not readiness.missing and not mismatches,
            missing=readiness.missing,
            mismatches=tuple(dict.fromkeys(mismatches)),
            inherited_preview_baseline_code=(
                readiness.inherited_preview_baseline_code
            ),
            inherited_preview_baseline_provenance=(
                readiness.inherited_preview_baseline_provenance
            ),
            planned_live_stimulus_code=readiness.planned_live_stimulus_code,
            physical_dac_confirmation=readiness.physical_dac_confirmation,
        )

    def _persist_accounting(self) -> None:
        self.state.update(self.accounting.state_fields())
        self._save()

    def _process_transactions(self) -> None:
        """Retain every complete response as observation and rebuild the ledger."""
        super()._process_transactions()
        rows = _read_csv_rows(self.run_dir / ACTIVE_CSV)
        if not rows:
            return
        validate_transaction_history(
            rows,
            self.spec,
            self.identities,
            self.expected_build_identity,
            dual_core=True,
        )
        timing_rows = _read_csv_rows(
            self.run_dir / "csv" / ACTIVE_TRANSACTIONS_V2_CSV
        )
        # The serial splitter may expose ACT1 one poll before its immediately
        # following AT2.  Wait for that bounded freshness gap before making
        # any overlay accounting decision.
        if len(timing_rows) < len(rows):
            return
        _reconcile_exact_transaction_timing(
            run_dir=self.run_dir, transactions=rows
        )
        application_ticks = _exact_application_ticks(
            run_dir=self.run_dir, transactions=rows
        )
        _validate_exact_application_cadence(
            application_ticks,
            minimum_cadence_s=int(
                self.contract["envelope"]["minimum_application_cadence_s"]
            ),
        )
        manual = [row for row in rows if row.get("event") == "manual_start"]
        applications = [row for row in rows if row.get("event") == "application"]
        responses = [row for row in rows if row.get("event") == "response"]
        if len(manual) != 1:
            raise ValueError("frequency-only endurance requires exactly one setup")
        if len(applications) > int(
            self.contract["envelope"]["maximum_automatic_applications"]
        ):
            raise ValueError("frequency-only automatic application ceiling exceeded")
        cumulative = sum(abs(int(row["requested_delta_codes"])) for row in applications)
        if cumulative > int(
            self.contract["envelope"]["maximum_cumulative_movement_codes"]
        ):
            raise ValueError("frequency-only cumulative movement ceiling exceeded")
        total_writes = len(manual) + len(applications)
        if total_writes > int(
            self.contract["envelope"]["maximum_total_physical_dac_writes"]
        ):
            raise ValueError("frequency-only total physical write ceiling exceeded")
        outstanding = int(
            bool(
                rows
                and rows[-1].get("event")
                not in {"manual_start", "response", "request_withdrawn"}
            )
        )
        if outstanding > int(
            self.contract["envelope"]["maximum_outstanding_transactions"]
        ):
            raise ValueError("more than one frequency-only transaction is outstanding")
        self.state["transaction_outstanding"] = outstanding
        self.state["transaction_outstanding_high_watermark"] = max(
            int(self.state.get("transaction_outstanding_high_watermark", 0)),
            outstanding,
        )
        self.state["setup_establishments"] = len(manual)
        self.state["automatic_applications"] = len(applications)
        self.state["total_physical_dac_writes"] = total_writes
        self.state["cumulative_movement_codes"] = cumulative
        self.state["response_count"] = len(responses)
        self.state["first_complete_application_path_observed"] = bool(responses)
        self.accounting.setup_establishments = len(manual)
        self.accounting.automatic_applications = len(applications)
        self.accounting.cumulative_movement_codes = cumulative
        if applications:
            self.accounting.last_application_ticks = application_ticks[-1]
        envelope = self.contract["envelope"]
        if (
            len(applications) == int(envelope["maximum_automatic_applications"])
            or cumulative == int(envelope["maximum_cumulative_movement_codes"])
        ):
            self.accounting.authority_ceiling_exhausted = True
            self.accounting.authority_ceiling_decision_sequence = int(
                applications[-1]["decision_sequence"]
            )
        self._persist_accounting()

    def _update_lost_opportunities(
        self, health: Mapping[tuple[str, str], str]
    ) -> None:
        controls = _read_csv_rows(self.run_dir / "csv" / CONTROL_PREVIEWS_CSV)
        sequences = [_safe_int(row.get("control_seq")) for row in controls]
        if any(sequence is None for sequence in sequences):
            raise ValueError("control opportunity evidence lacks an exact sequence")
        exact_sequences = [int(sequence) for sequence in sequences if sequence is not None]
        if len(set(exact_sequences)) != len(exact_sequences):
            raise ValueError("duplicate control opportunity sequence")
        for previous, current in zip(exact_sequences, exact_sequences[1:]):
            if not _u32_successor(previous, current):
                raise ValueError(
                    f"missing control opportunity sequence: {previous} -> {current}"
                )
        transaction_rows = _read_csv_rows(self.run_dir / ACTIVE_CSV)
        transactions_by_decision: dict[int, list[dict[str, str]]] = {}
        for transaction in transaction_rows:
            decision_sequence = _safe_int(transaction.get("decision_sequence"))
            if decision_sequence is not None and decision_sequence != 0:
                transactions_by_decision.setdefault(decision_sequence, []).append(
                    transaction
                )
        ledger_path = self.run_dir / OPPORTUNITY_CAUSAL_LEDGER_PATH
        _, retained = _read_opportunity_causal_ledger(ledger_path)
        for row in controls:
            sequence = _safe_int(row.get("control_seq"))
            assert sequence is not None
            identity = canonical_sha256(row)
            prior = retained.get(sequence)
            if prior is not None and prior.get("control_identity_sha256") != identity:
                raise ValueError(
                    f"control opportunity {sequence} changed after it was retained"
                )
            related = transactions_by_decision.get(sequence, [])
            related_events = {item.get("event") for item in related}
            applications = [
                item for item in related if item.get("event") == "application"
            ]
            if len(applications) > 1:
                raise ValueError(
                    f"multiple applications claim control opportunity {sequence}"
                )
            application = applications[0] if applications else None
            metadata_withdrawal = next(
                (
                    item
                    for item in related
                    if item.get("event") == "request_withdrawn"
                    and item.get("reason", "").startswith("gnss_metadata_")
                ),
                None,
            )
            reason = row.get("decision_reason_code", "").lower()
            control_state = row.get("control_state", "")
            limited_delta = _safe_int(row.get("limited_delta_codes"))
            eligible_control_demand = (
                row.get("preview_available") == "true"
                and row.get("preview_eligibility") == "true"
                and limited_delta not in {None, 0}
            )
            eligible = (
                eligible_control_demand
                and row.get("actuation_authorized") == "true"
                and row.get("actionable") == "true"
            )
            disposition: str | None
            resolution_evidence: str | None
            resolution_transaction_sequence: int | None = None
            resolution_reason: str | None = None
            if application is not None:
                disposition = "applied"
                resolution_evidence = "active_transactions_v1.application"
                resolution_transaction_sequence = _safe_int(
                    application.get("transaction_record_sequence")
                )
                if resolution_transaction_sequence is None:
                    raise ValueError(
                        f"application for control opportunity {sequence} lacks "
                        "its transaction record sequence"
                    )
                # The exact application is later causal evidence that this was
                # an eligible opportunity.  Its earlier preview can legitimately
                # precede the authority release in the independently flushed CSV.
                eligible = True
            elif metadata_withdrawal is not None:
                disposition = "gnss_metadata_hold"
                resolution_reason = metadata_withdrawal.get("reason")
                resolution_transaction_sequence = _safe_int(
                    metadata_withdrawal.get("transaction_record_sequence")
                )
                resolution_evidence = (
                    "active_transactions_v1.request_withdrawn:"
                    f"{resolution_reason}"
                )
            elif "request_withdrawn" in related_events:
                disposition = "request_withdrawn_before_release"
                resolution_evidence = "active_transactions_v1.request_withdrawn"
            elif reason == "decision_cadence_hold":
                disposition = "cadence_hold"
                resolution_evidence = "control_previews_v1.decision_reason_code"
            elif limited_delta == 0 or reason in {"inside_deadband", "zero_delta"}:
                disposition = "no_demand"
                resolution_evidence = "control_previews_v1.exact_zero_demand"
            elif "gnss" in reason and "metadata" in reason:
                disposition = "gnss_metadata_hold"
                resolution_evidence = "control_previews_v1.decision_reason_code"
            elif control_state in {
                "SETTLING_INHIBIT",
                "QUALIFYING",
                "WARMUP_INHIBIT",
            }:
                disposition = "settling_or_requalification_hold"
                resolution_evidence = "control_previews_v1.control_state"
            elif row.get("preview_available") != "true" or row.get(
                "preview_eligibility"
            ) != "true":
                disposition = "ineligible_estimate_or_reference"
                resolution_evidence = "control_previews_v1.preview_eligibility"
            elif (
                eligible_control_demand
                and not related_events
                and self.accounting.authority_ceiling_exhausted
                and self.accounting.authority_ceiling_decision_sequence
                is not None
                and 0
                < _u32_distance(
                    self.accounting.authority_ceiling_decision_sequence,
                    sequence,
                )
                < (1 << 31)
                and not self.state.get("exact_response_admission_closed_utc")
            ):
                disposition = "authority_ceiling_closed"
                resolution_evidence = "frequency_only_supervisor_state"
                self.accounting.endpoint_incomplete_reason = (
                    "eligible_opportunity_suppressed_by_authority_ceiling"
                )
                eligible = True
            elif row.get("actuation_authorized") != "true" or row.get(
                "actionable"
            ) != "true":
                disposition = "ineligible_not_authorized"
                resolution_evidence = "control_previews_v1.authority_flags"
            elif self.state.get("exact_response_admission_closed_utc"):
                disposition = "exact_response_admission_closed"
                resolution_evidence = "frequency_only_supervisor_state"
            elif related_events:
                disposition = None
                resolution_evidence = "active_transaction_in_progress"
            else:
                disposition = None
                resolution_evidence = "awaiting_exact_disposition_evidence"
            if prior is None:
                _append_opportunity_event(
                    ledger_path,
                    {
                        "event": "opportunity_observed",
                        "control_sequence": sequence,
                        "control_identity_sha256": identity,
                        "decision_id": row.get("decision_id"),
                        "decision_timestamp_ticks": row.get(
                            "decision_timestamp_ticks"
                        ),
                        "time_domain": row.get("time_domain"),
                        "eligible_control_opportunity": eligible,
                        "limited_delta_codes": limited_delta,
                        "resolved": disposition is not None,
                        "disposition": disposition,
                        "resolution_evidence": resolution_evidence,
                        "resolution_transaction_record_sequence": (
                            resolution_transaction_sequence
                        ),
                        "resolution_reason": resolution_reason,
                    },
                )
                _, retained = _read_opportunity_causal_ledger(ledger_path)
                continue
            if (
                prior.get("resolved") is True
                and prior.get("disposition") == "ineligible_not_authorized"
                and prior.get("resolution_evidence")
                == "control_previews_v1.authority_flags"
                and disposition == "applied"
            ):
                _append_opportunity_event(
                    ledger_path,
                    {
                        "event": "opportunity_reclassified",
                        "control_sequence": sequence,
                        "control_identity_sha256": identity,
                        "prior_disposition": "ineligible_not_authorized",
                        "disposition": "applied",
                        "resolution_evidence": resolution_evidence,
                        "resolution_transaction_record_sequence": (
                            resolution_transaction_sequence
                        ),
                        "resolution_reason": (
                            "late_exact_application_supersedes_preview_only_"
                            "classification"
                        ),
                    },
                )
                _, retained = _read_opportunity_causal_ledger(ledger_path)
                continue
            if (
                prior.get("resolved") is True
                and disposition == "applied"
                and prior.get("disposition") != "applied"
            ):
                raise ValueError(
                    f"application conflicts with retained disposition for {sequence}"
                )
            if prior.get("resolved") is not True and disposition is not None:
                _append_opportunity_event(
                    ledger_path,
                    {
                        "event": "opportunity_resolved",
                        "control_sequence": sequence,
                        "control_identity_sha256": identity,
                        "disposition": disposition,
                        "resolution_evidence": resolution_evidence,
                        "resolution_transaction_record_sequence": (
                            resolution_transaction_sequence
                        ),
                        "resolution_reason": resolution_reason,
                    },
                )
                _, retained = _read_opportunity_causal_ledger(ledger_path)
        dispositions: dict[str, int] = {}
        pending: list[int] = []
        eligible_count = 0
        for sequence, item in retained.items():
            if item.get("eligible_control_opportunity") is True:
                eligible_count += 1
            if item.get("resolved") is not True:
                pending.append(sequence)
                continue
            disposition = str(item.get("disposition"))
            dispositions[disposition] = dispositions.get(disposition, 0) + 1
        last_seen = exact_sequences[-1] if exact_sequences else None
        self.state["lost_opportunity_dispositions"] = dispositions
        self.state["last_opportunity_decision_sequence"] = last_seen
        self.state["control_opportunity_count"] = len(retained)
        self.state["eligible_control_opportunity_count"] = eligible_count
        self.state["pending_control_opportunity_sequences"] = pending
        if dispositions.get("authority_ceiling_closed", 0):
            self.accounting.endpoint_incomplete_reason = (
                "eligible_opportunity_suppressed_by_authority_ceiling"
            )
        self.state.update(self.accounting.state_fields())
        _write_replace(
            self.run_dir / LOST_OPPORTUNITY_PATH,
            {
                "schema_version": 1,
                "last_decision_sequence": last_seen,
                "control_opportunity_count": len(retained),
                "eligible_control_opportunity_count": eligible_count,
                "pending_control_opportunity_sequences": pending,
                "every_sequence_unique_and_contiguous": True,
                "dispositions": dispositions,
                "scientifically_appropriate_suppressions": [
                    "no_demand",
                    "cadence_hold",
                    "settling_or_requalification_hold",
                    "gnss_metadata_hold",
                    "exact_response_admission_closed",
                    "authority_ceiling_closed",
                    "ineligible_estimate_or_reference",
                    "ineligible_not_authorized",
                    "request_withdrawn_before_release",
                ],
                "platform_lost_opportunity_dispositions": [],
            },
        )
        self._save()

    def _opportunity_accounting_complete(self) -> tuple[bool, str | None]:
        count = int(self.state.get("control_opportunity_count", 0))
        pending = self.state.get("pending_control_opportunity_sequences", [])
        if count == 0:
            return False, "control_opportunity_evidence_absent"
        if not isinstance(pending, list) or pending:
            return False, "control_opportunity_disposition_incomplete"
        dispositions = self.state.get("lost_opportunity_dispositions", {})
        if not isinstance(dispositions, dict):
            return False, "control_opportunity_disposition_invalid"
        if int(dispositions.get("applied", 0)) != int(
            self.state.get("automatic_applications", 0)
        ):
            return False, "application_opportunity_identity_mismatch"
        return True, None

    def _update_metadata_hold(
        self, health: Mapping[tuple[str, str], str]
    ) -> None:
        active = _metadata_hold_active(health)
        prior = bool(self.state.get("gnss_metadata_hold_active"))
        if active and not prior:
            if health.get(("cx317_active", "gnss_metadata_hold_active")) != "true":
                raise ValueError("GNSS metadata hold state lacks its effective firmware flag")
            observed = _confirmed_hold_identity(health)
            entry_sequence = _safe_int(
                health.get(("cx317_active", "gnss_metadata_hold_entry_sequence"))
            )
            if entry_sequence is None:
                raise ValueError("GNSS metadata hold lacks entry sequence")
            self.state["gnss_metadata_hold_identity"] = {
                "entry_sequence": entry_sequence,
                **observed,
                "transaction_resolution_pending": (
                    health.get(
                        ("cx317_active", "gnss_metadata_hold_transaction_pending")
                    )
                    == "true"
                ),
            }
            self.state["gnss_metadata_hold_count"] = int(
                self.state.get("gnss_metadata_hold_count", 0)
            ) + 1
            self._event(
                "frequency_only_gnss_metadata_hold_entered",
                measurement_continues=True,
                new_correction_authority=False,
                **self.state["gnss_metadata_hold_identity"],
            )
        elif active and prior:
            identity = self.state.get("gnss_metadata_hold_identity")
            if not isinstance(identity, dict):
                raise ValueError("frequency-only GNSS metadata hold identity was not retained")
            observed = _confirmed_hold_identity(health)
            observed_with_entry = {
                "entry_sequence": _safe_int(
                    health.get(("cx317_active", "gnss_metadata_hold_entry_sequence"))
                ),
                **observed,
            }
            expected = {
                key: value
                for key, value in identity.items()
                if key != "transaction_resolution_pending"
            }
            if identity.get("transaction_resolution_pending"):
                if (
                    health.get(
                        ("cx317_active", "gnss_metadata_hold_transaction_pending")
                    )
                    != "true"
                ):
                    identity.update(observed_with_entry)
                    identity["transaction_resolution_pending"] = False
                    self.state["gnss_metadata_hold_identity"] = identity
                    self._event(
                        "frequency_only_gnss_metadata_hold_transaction_resolved",
                        **observed_with_entry,
                    )
            elif observed_with_entry != expected:
                raise ValueError(
                    "frequency-only actuation identity changed (session/code/epoch) during "
                    "GNSS metadata hold"
                )
        elif prior and not active:
            identity = self.state.get("gnss_metadata_hold_identity")
            entry_sequence = (
                identity.get("entry_sequence")
                if isinstance(identity, dict)
                else None
            )
            metadata_sequence = _safe_int(
                health.get(
                    ("cx317_active", "gnss_metadata_requalification_sequence")
                )
            )
            qualification_frontier = _safe_int(
                health.get(
                    ("cx317_active", "gnss_metadata_qualification_frontier")
                )
            )
            observation_sequence = _safe_int(
                health.get(("cx317_active", "d14_d8_observation_sequence"))
            )
            observed = _confirmed_hold_identity(health)
            if (
                entry_sequence is None
                or metadata_sequence is None
                or metadata_sequence <= entry_sequence
                or qualification_frontier is None
                or observation_sequence is None
                or observation_sequence <= qualification_frontier
                or health.get(("cx317_active", "state")) != "DISARMED"
                or not isinstance(identity, dict)
                or any(
                    observed[key] != identity.get(key)
                    for key in (
                        "session_id",
                        "applied_code",
                        "dac_epoch",
                        "correction_count",
                        "cumulative_movement_codes",
                    )
                )
            ):
                raise ValueError(
                    "frequency-only GNSS metadata hold cleared without "
                    "fresh causal same-session/code/epoch D14/D8 requalification"
                )
            self._event(
                "frequency_only_gnss_metadata_hold_left_after_fresh_causal_requalification",
                metadata_sequence=metadata_sequence,
                qualification_frontier=qualification_frontier,
                post_qualification_observation_sequence=observation_sequence,
                **observed,
            )
        self.state["gnss_metadata_hold_active"] = active
        self._save()

    def _check_fail_static_health(self, health: dict[tuple[str, str], str]) -> None:
        super()._check_fail_static_health(health)
        gnss_missing, gnss_mismatches = (
            gnss_operational_runtime_invariant_errors(
                health,
                require_present=(
                    self.state["prewrite_contract_ready_utc"] is not None
                ),
            )
        )
        if gnss_missing or gnss_mismatches:
            self._abort(
                "frequency_only_d9_d6_invalid_due_to_identity_or_evidence_failure"
            )
            self._event(
                "frequency_only_gnss_bootstrap_runtime_invariant_terminal",
                missing=gnss_missing,
                mismatches=gnss_mismatches,
            )
            return
        if (
            not self.state.get("d9_exact_readback_established")
            and health.get(("command", "config_snapshot")) != "end"
        ):
            wait_s = (
                time.monotonic()
                - self._d9_configuration_wait_started_monotonic
            )
            if wait_s >= D9_CONFIGURATION_SNAPSHOT_COMPLETION_TIMEOUT_S:
                self._abort(
                    "frequency_only_d9_d6_digital_noninterference_failed"
                )
                self._event(
                    "frequency_only_d9_configuration_snapshot_timeout",
                    timeout_s=D9_CONFIGURATION_SNAPSHOT_COMPLETION_TIMEOUT_S,
                    observed_config_snapshot=health.get(
                        ("command", "config_snapshot")
                    ),
                )
            return
        missing, mismatches = _d9_gate(health)
        if missing or mismatches:
            self._abort("frequency_only_d9_d6_digital_noninterference_failed")
            self._event(
                "frequency_only_d9_exact_readback_terminal",
                missing=missing,
                mismatches=mismatches,
            )
            return
        if not self.state.get("d9_exact_readback_established"):
            self.state["d9_exact_readback_established"] = True
            self.state["d9_exact_readback_established_utc"] = _utc_now()
            self._event(
                "frequency_only_d9_exact_readback_established_after_complete_"
                "configuration_snapshot"
            )
        self.state["d6_missing_observability"] = _d6_observability(health)
        self._update_metadata_hold(health)
        self._update_lost_opportunities(health)
        self._save()

    def _arm_exact_counter_accounting(
        self, health: dict[tuple[str, str], str]
    ) -> None:
        if self.accounting.armed_ticks is not None:
            return
        if self.state.get("qualification_started_utc") is None:
            return
        if (
            self.state.get("arm_pending")
            or health.get(("cx317_active", "state")) != "DISARMED"
            or health.get(("cx317_active", "evidence_phase")) != "evidence_clear"
            or health.get(("cx317_active", "manual_start_confirmed")) != "true"
        ):
            return
        setup_rows = [
            row
            for row in _read_csv_rows(self.run_dir / ACTIVE_CSV)
            if row.get("event") == "manual_start"
        ]
        if len(setup_rows) != 1:
            self._abort("frequency_only_setup_establishment_not_exactly_once")
            return
        setup = setup_rows[0]
        applied_code = _safe_int(setup.get("applied_code"))
        dac_epoch = _safe_int(setup.get("dac_epoch"))
        interval_rows = canonical_d14_d8_intervals(self.run_dir)
        valid_rows = [
            row
            for row in interval_rows
            if row["measurement_qualified"]
            and row["closing_ticks"] is not None
        ]
        if not valid_rows or applied_code is None or dac_epoch is None:
            return
        frontier_row = valid_rows[-1]
        frontier_ticks = int(frontier_row["closing_ticks"])
        frontier_sequence = int(frontier_row["count_sequence"])
        missing, mismatches = _d9_gate(health)
        try:
            self.accounting.arm(
                frontier_ticks=frontier_ticks,
                d9_state=str(health.get(("forwarded_clock_output", "state"), "")),
                d9_readback_exact=not missing and not mismatches,
                d14_d8_healthy=True,
                outstanding_transaction=False,
                applied_code=applied_code,
                dac_epoch=dac_epoch,
            )
        except ValueError:
            self._abort("frequency_only_soak_armed_gate_differs")
            return
        self.consumed_count_sequences = {
            int(row["count_sequence"]) for row in interval_rows
        }
        self.state["soak_armed_frontier_ticks"] = frontier_ticks
        self.state["soak_armed_count_sequence"] = frontier_sequence
        self._persist_accounting()
        self._event(
            "frequency_only_soak_armed",
            frontier_ticks=frontier_ticks,
            count_sequence=frontier_sequence,
            applied_code=applied_code,
            dac_epoch=dac_epoch,
        )

    def _observe_exact_counter_intervals(
        self, health: dict[tuple[str, str], str]
    ) -> None:
        if self.accounting.armed_ticks is None or self.accounting.terminal is not None:
            return
        missing, mismatches = _d9_gate(health)
        d9_valid = not missing and not mismatches
        for row in canonical_d14_d8_intervals(self.run_dir):
            sequence = _safe_int(row.get("count_sequence"))
            opening = _safe_int(row.get("opening_ticks"))
            closing = _safe_int(row.get("closing_ticks"))
            if (
                sequence is None
                or opening is None
                or closing is None
                or sequence in self.consumed_count_sequences
            ):
                continue
            self.consumed_count_sequences.add(sequence)
            exact_interval = bool(row["measurement_qualified"])
            before = list(self.accounting.milestones)
            self.accounting.observe_interval(
                opening_ticks=opening,
                closing_ticks=closing,
                measurement_qualified=exact_interval,
                d9_valid=d9_valid,
                count_sequence=sequence,
            )
            checkpoint = _counter_checkpoint(self.accounting)
            checkpoint["processed_count_sequence"] = sequence
            retained_row = {
                **row,
                "d9_digital_readback_exact": d9_valid,
                "counter_accounting_after": checkpoint,
            }
            ledger = self.run_dir / QUALIFIED_INTERVAL_LEDGER_PATH
            ledger.parent.mkdir(parents=True, exist_ok=True)
            with ledger.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(retained_row, sort_keys=True, allow_nan=False) + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
            for milestone in self.accounting.milestones[len(before):]:
                self._event(
                    "frequency_only_qualified_milestone",
                    qualified_duration_s=milestone,
                    qualified_ticks=self.accounting.qualified_ticks,
                    count_sequence=sequence,
                )
        self._persist_accounting()

    def _maybe_start_or_arm(
        self, health: dict[tuple[str, str], str]
    ) -> None:
        if not self.state.get("d9_exact_readback_established"):
            return
        if _metadata_hold_active(health):
            return
        if self.state.get("manual_start_sent") and self.accounting.armed_ticks is None:
            return
        # Only the frozen exact-response checkpoint closes control admission.
        # Longer scientific horizons are observational and may be explicitly
        # right-censored by the next application or the endpoint.
        target_ticks = int(self.contract["envelope"]["qualified_duration_s"]) * TIMER_HZ
        if (
            self.accounting.armed_ticks is not None
            and _correction_admission_closed(
                self.accounting.qualified_ticks, target_ticks
            )
        ):
            response_reserve_ticks = APPLICATION_ADMISSION_RESERVE_S * TIMER_HZ
            if self.state.get("exact_response_admission_closed_utc") is None:
                self.state["exact_response_admission_closed_utc"] = _utc_now()
                self._save()
                self._event(
                    "frequency_only_correction_admission_closed_for_exact_response",
                    qualified_ticks=self.accounting.qualified_ticks,
                    required_response_reserve_ticks=response_reserve_ticks,
                )
            return
        if self.accounting.authority_ceiling_exhausted:
            return
        super()._maybe_start_or_arm(health)

    def _maybe_finish(self, health: dict[tuple[str, str], str], now_epoch: float, elapsed_monotonic_s: float) -> None:
        """Keep the shared setup/arm/transaction path live to the 24h endpoint."""
        del elapsed_monotonic_s
        if self.state["terminal"] is not None:
            return
        setup = self.state["setup_confirmed_utc"]
        self._arm_exact_counter_accounting(health)
        if self.accounting.armed_ticks is None:
            if setup is not None and now_epoch - _parse_utc_epoch(setup) >= int(
                self.contract["envelope"]["initial_qualification_deadline_s"]
            ):
                self._abort("frequency_only_qualification_deadline_expired")
            return
        self._observe_exact_counter_intervals(health)
        if self.accounting.terminal is not None:
            self._abort(self.accounting.terminal)
            return
        if not self.accounting.target_reached:
            return
        if self.state["arm_pending"]:
            return
        if (
            health.get(("cx317_active", "state")) != "DISARMED"
            or health.get(("cx317_active", "evidence_phase")) != "evidence_clear"
            or health.get(("cx317_active", "evidence_pending")) == "true"
            or int(self.state.get("transaction_outstanding", 0)) != 0
        ):
            return
        applications = int(self.state.get("automatic_applications", 0))
        responses = int(self.state.get("response_count", 0))
        if responses != applications:
            return
        self._update_lost_opportunities(health)
        opportunities_complete, opportunity_reason = (
            self._opportunity_accounting_complete()
        )
        if not opportunities_complete and self.accounting.endpoint_incomplete_reason is None:
            self.accounting.endpoint_incomplete_reason = opportunity_reason
            self._persist_accounting()
        incomplete = self.accounting.endpoint_incomplete_reason
        self.state["terminal"] = {
            "result": "healthy_stop" if incomplete is None else "incomplete",
            "reason": (
                "frequency_only_d9_d6_digital_endurance_passed"
                if incomplete is None
                else "frequency_only_d9_d6_digital_endurance_incomplete"
            ),
            "incomplete_reason": incomplete,
            "utc": _utc_now(),
        }
        self._save()
        self._event("frequency_only_24h_endpoint_reached")


def create_live_supervisor(*, run_dir: Path, bundle: Mapping[str, Any], duration_s: float | None = None) -> D9D6FrequencyOnlyEnduranceSupervisor:
    return D9D6FrequencyOnlyEnduranceSupervisor(
        bundle=bundle,
        run_dir=run_dir,
        command_fifo=run_dir / "control/normal_commands.fifo",
        emergency_command_fifo=run_dir / "control/emergency_abort.fifo",
        abort_fifo=run_dir / ABORT_FIFO_PATH,
        duration_s=duration_s,
        console_events=False,
    )


def _wait_for_capture_ready(run_dir: Path, capture: subprocess.Popen[str], timeout_s: float) -> None:
    normal = run_dir / "control/normal_commands.fifo"
    emergency = run_dir / "control/emergency_abort.fifo"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if capture.poll() is not None:
            raise RuntimeError("capture exited before serial ownership was established")
        if normal.exists() and emergency.exists() and _capture_state_ready(run_dir, capture.pid):
            return
        time.sleep(0.05)
    raise TimeoutError("capture did not establish FIFOs and serial ownership")


def _stop_capture(capture: subprocess.Popen[str]) -> None:
    if capture.poll() is None:
        capture.send_signal(signal.SIGINT)
    try:
        capture.wait(timeout=30)
    except subprocess.TimeoutExpired:
        capture.kill()
        capture.wait(timeout=10)


def _wait_for_priority_abort_delivery(run_dir: Path, timeout_s: float = 15.0) -> str:
    """Keep capture alive until priority abort submission has a retained result."""
    deadline = time.monotonic() + timeout_s
    raw_path = run_dir / "raw/serial.log"
    while time.monotonic() < deadline:
        markers = _markers(raw_path)
        if any(item.get("event") == "emergency_abort_sent" for item in markers):
            return "capture_priority_abort_sent"
        if any(item.get("event") == "emergency_abort_delivery_failure" for item in markers):
            return "bounded_delivery_failure"
        time.sleep(0.05)
    return "bounded_delivery_failure"


def _capture_closure_success(
    *, run_dir: Path, expected_device: str
) -> tuple[bool, dict[str, Any] | None, str]:
    path = run_dir / "reports/capture_segment_closure_v1.json"
    if not path.is_file():
        return False, None, "capture_segment_closure_absent"
    closure = _read(path)
    manifest_sha256 = sha256((run_dir / "run_manifest.json").read_bytes()).hexdigest()
    success = (
        closure.get("run_manifest_sha256") == manifest_sha256
        and closure.get("device") == expected_device
        and closure.get("baud") == 115200
        and closure.get("logical_segment_closed") is True
        and closure.get("physical_serial_open") is False
        and closure.get("closure_mode") == "physical_serial_close"
        and closure.get("serial_reopened") is False
    )
    return (
        success,
        closure,
        "capture_segment_closed_exact" if success else "capture_segment_closure_differs",
    )


def _record_run_lifecycle(
    *,
    run_dir: Path,
    terminal_reason: str,
    capture_returncode: int | None,
    expected_device: str,
) -> dict[str, Any]:
    closure_ok, closure, closure_reason = _capture_closure_success(
        run_dir=run_dir, expected_device=expected_device
    )
    closure_path = run_dir / "reports/capture_segment_closure_v1.json"
    manifest_path = run_dir / "run_manifest.json"
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "status": (
            "capture_closed_successfully"
            if capture_returncode == 0 and closure_ok
            else "capture_close_failed"
        ),
        "completed_utc": _utc_now(),
        "terminal": terminal_reason,
        "capture_returncode": capture_returncode,
        "capture_closure_success": closure_ok,
        "capture_closure_reason": closure_reason,
        "capture_closure": (
            _binding(closure_path) if closure_path.is_file() else None
        ),
        "capture_closure_record_sha256": (
            canonical_sha256(closure) if closure is not None else None
        ),
        "run_manifest_sha256": sha256(manifest_path.read_bytes()).hexdigest(),
        "authority_and_wall_terminal_s": int(
            load_contract()["envelope"]["absolute_wall_limit_s"]
        ),
        "capture_duration_s": int(
            load_contract()["envelope"]["absolute_wall_limit_s"]
        )
        + CAPTURE_EVIDENCE_DRAIN_MARGIN_S,
        "post_terminal_evidence_drain_and_abort_margin_s": (
            CAPTURE_EVIDENCE_DRAIN_MARGIN_S
        ),
        "expected_post_upload_device": expected_device,
    }
    record = {**unsigned, "record_sha256": canonical_sha256(unsigned)}
    _write_new(run_dir / RUN_LIFECYCLE_PATH, record)
    return record


def run_live(*, activation_path: Path, run_dir: Path, startup_timeout_s: float = 300.0, monitor_period_s: float = 5.0) -> dict[str, Any]:
    """Execute one finite physical acquisition under an exact live activation.

    This is intentionally blocking: the process owner remains present and the
    independent abort FIFO is serviced until a terminal is retained.  It must
    be invoked only after the no-I/O preflight and PTY operational rehearsal
    for the exact candidate bundle have passed and been bound into the supplied
    activation artifact.
    """
    if startup_timeout_s <= 0 or monitor_period_s <= 0 or monitor_period_s > 60:
        raise ValueError("startup timeout and monitor period must be positive; monitor period is at most 60 s")
    run_dir = run_dir.resolve()
    if run_dir.exists():
        raise FileExistsError("live run directory must not already exist")
    activation_path = activation_path.resolve()
    activation, bundle = validate_activation(_read(activation_path))
    run_dir.mkdir(parents=True)
    detected, board_identity, firmware_entry = _execute_activation_authorized_upload(
        run_dir=run_dir,
        activation=activation,
        bundle=bundle,
    )
    create_live_manifest(
        run_dir=run_dir,
        activation_path=activation_path,
        activation=activation,
        resolved_device=detected,
        board_identity=board_identity,
        firmware_entry=firmware_entry,
    )
    absolute_wall_limit_s = int(
        load_contract()["envelope"]["absolute_wall_limit_s"]
    )
    command = live_capture_command(
        run_dir=run_dir,
        expected_device=detected,
        duration_s=absolute_wall_limit_s + CAPTURE_EVIDENCE_DRAIN_MARGIN_S,
    )
    launcher_log = run_dir / "reports/capture_launcher.log"
    capture_output = launcher_log.open("x", encoding="utf-8")
    supervisor = create_live_supervisor(
        run_dir=run_dir, bundle=bundle,
        duration_s=float(absolute_wall_limit_s),
    )
    terminal_reason = "capture_startup_failed"
    capture: subprocess.Popen[str] | None = None
    lifecycle: dict[str, Any] | None = None
    try:
        capture = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=capture_output,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        _wait_for_capture_ready(run_dir, capture, startup_timeout_s)
        if _serial_owner_pids(detected) != {capture.pid}:
            raise RuntimeError("capture did not become the sole serial owner")
        # The shared supervisor owns CONFIG/DAC queries, ACTIVE SNAPSHOT,
        # exact ACTIVE SETUP 0xA808, ACTIVE ARM, transaction capsules,
        # first-consumer acknowledgement, response handling, and independent
        # abort delivery.  This runner never substitutes a parallel loop.
        result_code = supervisor.run()
        terminal = supervisor.state.get("terminal")
        terminal_reason = str(terminal.get("reason")) if isinstance(terminal, dict) else f"supervisor_exit_{result_code}"
    except BaseException as exc:
        supervisor._event("frequency_only_runner_exception", exception=type(exc).__name__, detail=str(exc))
        supervisor._abort(f"frequency_only_runner_fault:{exc}")
        terminal_reason = "frequency_only_d9_d6_invalid_due_to_identity_or_evidence_failure"
        raise
    finally:
        if capture is not None:
            terminal = supervisor.state.get("terminal")
            clean_endpoint = isinstance(terminal, dict) and terminal.get("reason") in {
                "frequency_only_d9_d6_digital_endurance_passed",
                "frequency_only_d9_d6_digital_endurance_incomplete",
            }
            if not clean_endpoint and capture.poll() is None:
                delivery = _wait_for_priority_abort_delivery(run_dir)
                supervisor.state["abort_delivery"] = delivery
                supervisor._save()
            _stop_capture(capture)
        capture_output.close()
        if (run_dir / "run_manifest.json").is_file():
            lifecycle = _record_run_lifecycle(
                run_dir=run_dir,
                terminal_reason=terminal_reason,
                capture_returncode=(
                    capture.returncode if capture is not None else None
                ),
                expected_device=detected,
            )
    if lifecycle is None or lifecycle["status"] != "capture_closed_successfully":
        raise RuntimeError("capture did not return zero with exact retained closure")
    return {
        "tool": TOOL_ID,
        "run_dir": str(run_dir),
        "terminal": terminal_reason,
        "capture_returncode": capture.returncode if capture is not None else None,
        "firmware_flash_count": firmware_entry["firmware_flash_count"],
        "firmware_entry_sha256": firmware_entry["record_sha256"],
        "capture_duration_s": absolute_wall_limit_s + CAPTURE_EVIDENCE_DRAIN_MARGIN_S,
        "authority_and_wall_terminal_s": absolute_wall_limit_s,
        "next_step": "finalize only after capture returncode is zero and all declared evidence is present",
    }


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "rms": None,
            "mad": None,
            "p95_absolute": None,
            "maximum_absolute": None,
        }
    ordered_abs = sorted(abs(value) for value in values)
    p95_index = min(len(ordered_abs) - 1, math.ceil(0.95 * len(ordered_abs)) - 1)
    median = statistics.median(values)
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": median,
        "rms": math.sqrt(statistics.fmean(value * value for value in values)),
        "mad": statistics.median(abs(value - median) for value in values),
        "p95_absolute": ordered_abs[p95_index],
        "maximum_absolute": ordered_abs[-1],
    }


def _slope_metrics(points: list[tuple[int, float]]) -> dict[str, Any]:
    if len(points) < 2:
        return {
            "sample_count": len(points),
            "ols_hz_per_hour": None,
            "theil_sen_hz_per_hour": None,
            "residual_rms_hz": None,
            "start_to_end_delta_hz": None,
        }
    origin = points[0][0]
    x = [(item[0] - origin) / 3600.0 for item in points]
    y = [item[1] for item in points]
    x_mean = statistics.fmean(x)
    y_mean = statistics.fmean(y)
    denominator = sum((value - x_mean) ** 2 for value in x)
    ols = (
        sum((xv - x_mean) * (yv - y_mean) for xv, yv in zip(x, y))
        / denominator
        if denominator
        else 0.0
    )
    intercept = y_mean - ols * x_mean
    residual_rms = math.sqrt(
        statistics.fmean(
            (yv - (intercept + ols * xv)) ** 2 for xv, yv in zip(x, y)
        )
    )
    pair_slopes = [
        (y[j] - y[i]) / (x[j] - x[i])
        for i in range(len(x))
        for j in range(i + 1, len(x))
        if x[j] != x[i]
    ]
    return {
        "sample_count": len(points),
        "ols_hz_per_hour": ols,
        "theil_sen_hz_per_hour": statistics.median(pair_slopes),
        "residual_rms_hz": residual_rms,
        "start_to_end_delta_hz": y[-1] - y[0],
    }


def _selected_window_fitness(run_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    intervals = canonical_d14_d8_intervals(run_dir)
    interval_by_sequence = {row["count_sequence"]: row for row in intervals}
    transactions = _read_csv_rows(run_dir / ACTIVE_CSV)
    windows: list[dict[str, Any]] = []
    for row in _read_csv_rows(run_dir / "csv" / ESTIMATES_CSV):
        if row.get("estimator_version") != "cx317_selected_600s_nonoverlap_v1":
            continue
        reasons: list[str] = []
        last = _safe_int(row.get("source_count_seq"))
        accepted = _safe_int(row.get("accepted_sample_count"))
        if last is None or accepted != 600:
            reasons.append("selected_window_identity_or_support_count_mismatch")
            support: list[dict[str, Any]] = []
        else:
            support = [
                interval_by_sequence.get((last - offset) & U32_MASK)
                for offset in range(599, -1, -1)
            ]
            if any(item is None for item in support):
                reasons.append("selected_window_missing_canonical_interval")
                support = [item for item in support if item is not None]
        expected_fields = {
            "observation_validity": "valid",
            "reference_validity": "valid",
            "reference_continuity": "true",
            "count_validity": "valid",
            "count_continuity": "true",
            "diagnostic_health": "healthy",
        }
        for field, expected in expected_fields.items():
            if row.get(field) != expected:
                reasons.append(f"selected_{field}_not_{expected}")
        if support and any(not item["measurement_qualified"] for item in support):
            reasons.append("selected_window_contains_unqualified_interval")
        epochs = {item["dac_epoch"] for item in support}
        codes = {item["applied_code"] for item in support}
        if len(epochs) != 1 or len(codes) != 1:
            reasons.append("selected_window_straddles_dac_epoch")
        epoch, code, latest_boundary = (
            _application_epoch_at_count_sequence(transactions, last)
            if last is not None
            else (None, None, None)
        )
        settled = bool(
            last is not None
            and (
                latest_boundary is None
                or _u32_distance(latest_boundary, last) > 900
            )
        )
        error = None
        try:
            error = float(row["frequency_error_hz"])
            if not math.isfinite(error):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            reasons.append("selected_frequency_error_invalid")
        windows.append(
            {
                "estimate_id": row.get("estimate_id"),
                "source_reference_first_sequence": _safe_int(row.get("source_reference_first_seq")),
                "source_reference_last_sequence": _safe_int(row.get("source_reference_last_seq")),
                "source_count_sequence": last,
                "accepted_sample_count": accepted,
                "dac_epoch": epoch,
                "applied_code": code,
                "settling_complete": settled,
                "frequency_error_hz": error,
                "window_qualified": not reasons,
                "exclusion_reasons": reasons,
            }
        )
    valid = [row for row in windows if row["window_qualified"]]
    settled = [row for row in valid if row["settling_complete"]]
    return windows, {
        "selected_window_count": len(windows),
        "qualified_window_count": len(valid),
        "stationary_settled_window_count": len(settled),
        "qualified_coverage_fraction": len(valid) / len(windows) if windows else None,
        "invalid_or_missing_window_count": len(windows) - len(valid),
    }


def _fraction_evidence(value: Fraction) -> dict[str, int | float]:
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "display_value": float(value),
    }


def _candidate_fll_window_fitness(
    intervals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare predeclared boxcar windows without changing runtime authority."""

    segments: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for row in intervals:
        stationary = (
            row.get("measurement_qualified") is True
            and row.get("settling_complete") is True
            and row.get("session") is not None
            and row.get("dac_epoch") is not None
            and row.get("applied_code") is not None
            and _safe_int(row.get("counted_edges")) is not None
            and _safe_int(row.get("duration_ticks")) not in {None, 0}
        )
        same_segment = bool(
            current
            and _u32_successor(
                int(current[-1]["count_sequence"]),
                int(row["count_sequence"]),
            )
            and all(
                row.get(field) == current[-1].get(field)
                for field in ("session", "dac_epoch", "applied_code")
            )
        )
        if not stationary:
            if current:
                segments.append(current)
                current = []
            continue
        if current and not same_segment:
            segments.append(current)
            current = []
        current.append(row)
    if current:
        segments.append(current)

    candidates: dict[int, dict[str, Any]] = {}
    for duration_s in CANDIDATE_FLL_WINDOWS_S:
        windows: list[dict[str, Any]] = []
        errors: list[tuple[int, int, Fraction]] = []
        drift_support: list[dict[str, Any]] = []
        one_edge_resolutions: list[Fraction] = []
        for segment_index, segment in enumerate(segments):
            segment_errors: list[tuple[int, int, int, Fraction]] = []
            segment_elapsed_ticks = 0
            segment_elapsed_d14_intervals = 0
            complete_count = len(segment) // duration_s
            for window_index in range(complete_count):
                support = segment[
                    window_index * duration_s : (window_index + 1) * duration_s
                ]
                total_edges = sum(int(row["counted_edges"]) for row in support)
                total_ticks = sum(int(row["duration_ticks"]) for row in support)
                support_intervals = len(support)
                error = Fraction(
                    total_edges - 10_000_000 * support_intervals,
                    support_intervals,
                )
                one_edge = Fraction(1, support_intervals)
                one_edge_resolutions.append(one_edge)
                segment_elapsed_ticks += total_ticks
                segment_elapsed_d14_intervals += support_intervals
                last_sequence = int(support[-1]["count_sequence"])
                errors.append((segment_index, last_sequence, error))
                segment_errors.append(
                    (
                        last_sequence,
                        segment_elapsed_d14_intervals,
                        segment_elapsed_ticks,
                        error,
                    )
                )
                windows.append(
                    {
                        "stationary_segment": segment_index,
                        "session": support[0]["session"],
                        "dac_epoch": support[0]["dac_epoch"],
                        "applied_code": support[0]["applied_code"],
                        "source_first_count_sequence": support[0][
                            "count_sequence"
                        ],
                        "source_last_count_sequence": last_sequence,
                        "support_interval_count": len(support),
                        "summed_counted_edges": total_edges,
                        "summed_duration_ticks": total_ticks,
                        "frequency_reference_domain": "D14_reference_intervals",
                        "aperture_diagnostic_domain": "rp2040_timer0",
                        "stationary_segment_elapsed_end_ticks": (
                            segment_elapsed_ticks
                        ),
                        "stationary_segment_elapsed_end_d14_intervals": (
                            segment_elapsed_d14_intervals
                        ),
                        "frequency_error_hz": _fraction_evidence(error),
                        "one_edge_resolution_hz": _fraction_evidence(one_edge),
                    }
                )
            if len(segment_errors) >= 2:
                (
                    first_sequence,
                    first_d14_intervals,
                    first_ticks,
                    first_error,
                ) = segment_errors[0]
                (
                    last_sequence,
                    last_d14_intervals,
                    last_ticks,
                    last_error,
                ) = segment_errors[-1]
                span_ticks = last_ticks - first_ticks
                span_d14_intervals = last_d14_intervals - first_d14_intervals
                if span_ticks > 0 and span_d14_intervals > 0:
                    slope = (last_error - first_error) * Fraction(
                        3600, span_d14_intervals
                    )
                    drift_support.append(
                        {
                            "stationary_segment": segment_index,
                            "estimate_count": len(segment_errors),
                            "source_first_count_sequence": first_sequence,
                            "source_last_count_sequence": last_sequence,
                            "source_span_d14_intervals": span_d14_intervals,
                            "source_span_ticks": span_ticks,
                            "source_span_s": _fraction_evidence(
                                Fraction(span_ticks, TIMER_HZ)
                            ),
                            "start_to_end_hz_per_hour": _fraction_evidence(slope),
                        }
                    )
        differences = [
            current_error - previous_error
            for (previous_segment, _, previous_error),
            (current_segment, _, current_error) in zip(errors, errors[1:])
            if previous_segment == current_segment
        ]
        noise_mse = (
            sum((difference * difference for difference in differences), Fraction())
            / len(differences)
            if differences
            else None
        )
        candidates[duration_s] = {
            "window_s": duration_s,
            "complete_stationary_window_count": len(windows),
            "successive_difference_count": len(differences),
            "noise": {
                "successive_difference_mean_square_hz2": (
                    _fraction_evidence(noise_mse) if noise_mse is not None else None
                ),
                "successive_difference_rms_hz": (
                    math.sqrt(float(noise_mse)) if noise_mse is not None else None
                ),
            },
            "quantization": {
                "worst_case_one_edge_resolution_hz": (
                    _fraction_evidence(max(one_edge_resolutions))
                    if one_edge_resolutions
                    else None
                )
            },
            "latency": {
                "boxcar_group_delay_s": _fraction_evidence(
                    Fraction(duration_s, 2)
                )
            },
            "drift_support": drift_support,
            "windows": windows,
            "assessment": "pending_selected_baseline",
            "assessment_reason": "pending_selected_baseline",
        }
    selected = candidates[SELECTED_FLL_WINDOW_S]
    selected_mse_record = selected["noise"][
        "successive_difference_mean_square_hz2"
    ]
    selected_mse = (
        Fraction(
            int(selected_mse_record["numerator"]),
            int(selected_mse_record["denominator"]),
        )
        if selected_mse_record is not None
        else None
    )
    selected_supported = (
        selected["complete_stationary_window_count"]
        >= CANDIDATE_WINDOW_MINIMUM_ESTIMATES
        and selected_mse is not None
    )
    for duration_s, candidate in candidates.items():
        mse_record = candidate["noise"]["successive_difference_mean_square_hz2"]
        mse = (
            Fraction(int(mse_record["numerator"]), int(mse_record["denominator"]))
            if mse_record is not None
            else None
        )
        if (
            candidate["complete_stationary_window_count"]
            < CANDIDATE_WINDOW_MINIMUM_ESTIMATES
            or mse is None
        ):
            candidate["assessment"] = "insufficient_evidence"
            candidate["assessment_reason"] = (
                "fewer_than_two_complete_stationary_estimates"
            )
            continue
        if not selected_supported or selected_mse is None:
            candidate["assessment"] = "insufficient_evidence"
            candidate["assessment_reason"] = "selected_600s_baseline_unavailable"
            continue
        short_noise_limit = selected_mse * (
            CANDIDATE_WINDOW_SHORT_NOISE_RATIO
            * CANDIDATE_WINDOW_SHORT_NOISE_RATIO
        )
        material_long_noise_limit = selected_mse * (
            (Fraction(1) - CANDIDATE_WINDOW_MATERIAL_NOISE_REDUCTION)
            ** 2
        )
        if duration_s < SELECTED_FLL_WINDOW_S and mse > short_noise_limit:
            candidate["assessment"] = "too_short"
            candidate["assessment_reason"] = (
                "successive_difference_noise_exceeds_1_25x_selected_600s"
            )
        elif (
            duration_s > SELECTED_FLL_WINDOW_S
            and Fraction(duration_s, 2)
            > CANDIDATE_WINDOW_MAXIMUM_GROUP_DELAY_S
            and not (
                selected_mse > 0 and mse <= material_long_noise_limit
            )
        ):
            candidate["assessment"] = "too_long"
            candidate["assessment_reason"] = (
                "group_delay_exceeds_300s_without_20pct_noise_reduction"
            )
        else:
            candidate["assessment"] = "appropriate"
            candidate["assessment_reason"] = (
                "predeclared_noise_and_group_delay_criteria_satisfied"
            )

    return {
        "observational_only": True,
        "runtime_authority_changed": False,
        "source": "canonical_1s_D14_D8_intervals",
        "frequency_reference_domain": "D14_reference_intervals",
        "aperture_diagnostic_domain": "rp2040_timer0",
        "stationary_support": (
            "qualified_consecutive_same_session_dac_code_and_epoch_after_settling"
        ),
        "exact_aggregation": (
            "integer_edge_and_tick_sums_then_rational_metrics_before_display"
        ),
        "predeclared_criteria": {
            "candidate_windows_s": list(CANDIDATE_FLL_WINDOWS_S),
            "selected_window_s": SELECTED_FLL_WINDOW_S,
            "minimum_complete_estimates": CANDIDATE_WINDOW_MINIMUM_ESTIMATES,
            "too_short_noise_ratio_vs_selected": float(
                CANDIDATE_WINDOW_SHORT_NOISE_RATIO
            ),
            "too_long_material_noise_reduction_fraction": float(
                CANDIDATE_WINDOW_MATERIAL_NOISE_REDUCTION
            ),
            "maximum_appropriate_group_delay_s": (
                CANDIDATE_WINDOW_MAXIMUM_GROUP_DELAY_S
            ),
        },
        "candidates": {
            str(duration_s): candidate
            for duration_s, candidate in candidates.items()
        },
    }


def _stationary_epoch_metrics(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_epoch: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in windows:
        if (
            row["window_qualified"]
            and row["settling_complete"]
            and row["dac_epoch"] is not None
            and row["applied_code"] is not None
        ):
            by_epoch.setdefault((row["dac_epoch"], row["applied_code"]), []).append(row)
    result: list[dict[str, Any]] = []
    for (epoch, code), rows in sorted(by_epoch.items()):
        rows.sort(key=lambda item: item["source_count_sequence"])
        points = [
            (int(row["source_count_sequence"]), float(row["frequency_error_hz"]))
            for row in rows
        ]
        values = [item[1] for item in points]
        result.append(
            {
                "dac_epoch": epoch,
                "applied_code": code,
                "source_first_count_sequence": points[0][0],
                "source_last_count_sequence": points[-1][0],
                "frequency_error": _distribution(values),
                "drift": _slope_metrics(points),
            }
        )
    return result


def _response_and_horizon_metrics(
    transactions: list[dict[str, str]],
    windows: list[dict[str, Any]],
    *,
    endpoint_source_sequence: int | None = None,
) -> dict[str, Any]:
    applications = [row for row in transactions if row.get("event") == "application"]
    responses = {
        int(row["request_sequence"]): row
        for row in transactions
        if row.get("event") == "response"
    }
    valid_windows = [row for row in windows if row["window_qualified"]]
    per_application: list[dict[str, Any]] = []
    pooled: dict[int, list[float]] = {horizon: [] for horizon in RESPONSE_HORIZONS_S}
    for index, application in enumerate(applications):
        request = int(application["request_sequence"])
        source = int(application["source_last_sequence"])
        epoch = int(application["dac_epoch"])
        code = int(application["applied_code"])
        delta = int(application["requested_delta_codes"])
        pre_error = float(application["pre_error_hz"])
        next_source = (
            int(applications[index + 1]["source_last_sequence"])
            if index + 1 < len(applications)
            else None
        )
        next_distance = (
            _u32_distance(source, next_source) if next_source is not None else None
        )
        endpoint_distance = (
            _u32_distance(source, endpoint_source_sequence)
            if endpoint_source_sequence is not None
            else None
        )
        horizon_facts: list[dict[str, Any]] = []
        for horizon in RESPONSE_HORIZONS_S:
            candidate = next(
                (
                    row
                    for row in valid_windows
                    if row["dac_epoch"] == epoch
                    and row["applied_code"] == code
                    and _u32_distance(source, int(row["source_count_sequence"])) >= horizon
                    and (
                        next_source is None
                        or _u32_distance(source, int(row["source_count_sequence"]))
                        < _u32_distance(source, next_source)
                    )
                ),
                None,
            )
            if horizon == 1500 and request in responses:
                response = responses[request]
                post_error = float(response["post_error_hz"])
                observed = float(response["observed_response_hz"])
                available = True
                fact_source = "ACT_exact_response_checkpoint"
                actual_elapsed = 1500
            elif candidate is not None:
                post_error = float(candidate["frequency_error_hz"])
                observed = post_error - pre_error
                available = True
                fact_source = "selected_600s_same_dac_epoch"
                actual_elapsed = _u32_distance(
                    source, int(candidate["source_count_sequence"])
                )
            else:
                available = False
                post_error = observed = None
                if next_distance is not None and next_distance < horizon:
                    fact_source = "right_censored_by_next_application"
                    actual_elapsed = next_distance
                elif endpoint_distance is not None and endpoint_distance < horizon:
                    fact_source = "right_censored_by_exact_endpoint"
                    actual_elapsed = endpoint_distance
                else:
                    fact_source = "unknown_missing_or_invalid_horizon_evidence"
                    actual_elapsed = None
            fact = {
                "horizon_s": horizon,
                "available": available,
                "source": fact_source,
                "actual_elapsed_s": actual_elapsed,
                "pre_error_hz": pre_error,
                "post_error_hz": post_error,
                "observed_response_hz": observed,
                "observed_gain_hz_per_code": (
                    observed / delta if available and delta else None
                ),
                "direction_matches_positive_gain_prior": (
                    observed * delta > 0 if available else None
                ),
            }
            if available and delta:
                pooled[horizon].append(observed / delta)
            horizon_facts.append(fact)
        same_epoch_errors = [
            float(row["frequency_error_hz"])
            for row in valid_windows
            if row["dac_epoch"] == epoch and row["applied_code"] == code
        ]
        per_application.append(
            {
                "request_sequence": request,
                "dac_epoch": epoch,
                "applied_code": code,
                "requested_delta_codes": delta,
                "pre_error_hz": pre_error,
                "response_class": responses.get(request, {}).get("response_class"),
                "response_complete": request in responses,
                "same_epoch_peak_absolute_error_hz": max(
                    (abs(value) for value in same_epoch_errors), default=None
                ),
                "zero_crossing_observed": any(
                    value == 0 or value * pre_error < 0 for value in same_epoch_errors
                ),
                "overshoot_ratio": (
                    max(
                        (abs(value) for value in same_epoch_errors if value * pre_error < 0),
                        default=0.0,
                    )
                    / abs(pre_error)
                    if pre_error
                    else None
                ),
                "horizons": horizon_facts,
            }
        )
    return {
        "horizons_s": list(RESPONSE_HORIZONS_S),
        "per_application": per_application,
        "pooled_gain_hz_per_code": {
            str(horizon): _distribution(values) for horizon, values in pooled.items()
        },
        "missing_horizons_are_never_treated_as_zero": True,
        "right_censor_requires_exact_pre_horizon_application_or_endpoint": True,
    }


def _chatter_metrics(transactions: list[dict[str, str]]) -> dict[str, Any]:
    applications = [row for row in transactions if row.get("event") == "application"]
    deltas = [int(row["requested_delta_codes"]) for row in applications]
    directions = [(value > 0) - (value < 0) for value in deltas if value]
    reversals = sum(left != right for left, right in zip(directions, directions[1:]))
    cumulative = sum(abs(value) for value in deltas)
    net = sum(deltas)
    codes = [int(row["applied_code"]) for row in applications]
    return {
        "application_count": len(applications),
        "cumulative_absolute_movement_codes": cumulative,
        "net_movement_codes": net,
        "net_to_path_efficiency": abs(net) / cumulative if cumulative else None,
        "direction_reversal_count": reversals,
        "alternating_triplet_count": sum(
            directions[i] != directions[i + 1]
            and directions[i + 1] != directions[i + 2]
            for i in range(max(0, len(directions) - 2))
        ),
        "minimum_applied_code": min(codes) if codes else None,
        "maximum_applied_code": max(codes) if codes else None,
        "minimum_range_margin_codes": min(
            (min(code - 0xA800, 0xAB00 - code) for code in codes),
            default=None,
        ),
    }


def _frequency_horizon_metrics(windows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [
        row
        for row in windows
        if row["window_qualified"] and row["settling_complete"]
    ]
    by_epoch: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in valid:
        by_epoch.setdefault((row["dac_epoch"], row["applied_code"]), []).append(row)
    result: dict[str, Any] = {}
    for horizon in RESPONSE_HORIZONS_S:
        minimum_windows = max(1, math.ceil(horizon / 600))
        segments: list[dict[str, Any]] = []
        for (epoch, code), rows in by_epoch.items():
            rows.sort(key=lambda item: item["source_count_sequence"])
            for end in range(minimum_windows - 1, len(rows)):
                segment = rows[end - minimum_windows + 1 : end + 1]
                span = _u32_distance(
                    int(segment[0]["source_count_sequence"]),
                    int(segment[-1]["source_count_sequence"]),
                ) + 600
                if span < horizon:
                    continue
                values = [float(row["frequency_error_hz"]) for row in segment]
                segments.append(
                    {
                        "dac_epoch": epoch,
                        "applied_code": code,
                        "source_first_count_sequence": segment[0]["source_count_sequence"],
                        "source_last_count_sequence": segment[-1]["source_count_sequence"],
                        "actual_span_s": span,
                        "frequency_error": _distribution(values),
                        "drift": _slope_metrics(
                            [
                                (
                                    int(row["source_count_sequence"]),
                                    float(row["frequency_error_hz"]),
                                )
                                for row in segment
                            ]
                        ),
                    }
                )
        result[str(horizon)] = {
            "required_stationary_selected_windows": minimum_windows,
            "complete_segment_count": len(segments),
            "segments": segments,
        }
    return result


def _validate_live_package_lifecycle(
    *, run_dir: Path, manifest: Mapping[str, Any]
) -> dict[str, Any]:
    """Rebind retained activation/build/upload/capture facts before analysis."""

    manifest_path = run_dir / "run_manifest.json"
    manifest_sha256 = sha256(manifest_path.read_bytes()).hexdigest()
    retained_activation = _read(run_dir / "inputs/live_activation.json")
    activation, bundle = validate_activation(retained_activation)
    activation_artifact = manifest.get("frequency_only_engineering", {}).get(
        "activation_artifact"
    )
    if not isinstance(activation_artifact, Mapping):
        raise ValueError("live manifest activation artifact is absent")
    source_activation_path = Path(str(activation_artifact.get("path", "")))
    if (
        dict(activation_artifact) != _binding(source_activation_path)
        or _read(source_activation_path) != retained_activation
        or manifest.get("frequency_only_engineering", {}).get("activation_sha256")
        != activation["activation_sha256"]
        or manifest.get("frequency_only_engineering", {}).get("bundle_sha256")
        != bundle["bundle_sha256"]
    ):
        raise ValueError("retained activation/bundle binding differs")
    if _read(run_dir / "inputs/frozen_bundle.json") != bundle:
        raise ValueError("retained frozen bundle differs from activated bundle")
    source_build_path = Path(str(bundle["firmware"]["build_manifest"]["path"]))
    if _read(run_dir / "inputs/firmware_build_manifest.json") != _read(
        source_build_path
    ):
        raise ValueError("retained firmware build manifest differs")
    expected_firmware = bundle["firmware"]
    manifest_firmware = manifest.get("firmware")
    if not isinstance(manifest_firmware, Mapping) or any(
        manifest_firmware.get(key) != expected_firmware[key]
        for key in (
            "source_revision",
            "source_sha256",
            "configuration_sha256",
            "build_identity",
            "fqbn",
            "uf2",
        )
    ) or manifest_firmware.get("build_manifest_sha256") != bundle[
        "firmware_build"
    ]["sha256"]:
        raise ValueError("live manifest firmware identity differs")

    entry_path = run_dir / FIRMWARE_ENTRY_PATH
    entry = _read(entry_path)
    entry_unsigned = {
        key: value for key, value in entry.items() if key != "record_sha256"
    }
    reservation_binding = entry.get("upload_attempt_reservation")
    if not isinstance(reservation_binding, Mapping):
        raise ValueError("retained firmware-entry upload reservation is absent")
    reservation_path = Path(str(reservation_binding.get("path", "")))
    if dict(reservation_binding) != _binding(reservation_path):
        raise ValueError("retained firmware-entry upload reservation binding differs")
    reservation = _read(reservation_path)
    _validate_upload_attempt_reservation(
        reservation,
        activation=activation,
        bundle=bundle,
        run_dir=run_dir,
    )
    retained_reservation_path = run_dir / RETAINED_UPLOAD_ATTEMPT_PATH
    if (
        _read(retained_reservation_path) != reservation
        or manifest_firmware.get("upload_attempt_reservation")
        != _binding(reservation_path)
        or manifest_firmware.get("retained_upload_attempt_reservation")
        != _binding(retained_reservation_path)
    ):
        raise ValueError("retained firmware-upload attempt reservation differs")
    if (
        manifest_firmware.get("entry_record") != _binding(entry_path)
        or entry.get("record_sha256") != canonical_sha256(entry_unsigned)
        or manifest_firmware.get("entry_record_sha256")
        != entry.get("record_sha256")
        or entry.get("status") != "passed"
        or entry.get("hardware_operations") is not True
        or entry.get("firmware_flash_count") != 1
        or entry.get("automatic_retry_performed") is not False
        or entry.get("upload_attempt_reservation_record_sha256")
        != reservation["record_sha256"]
        or entry.get("activation_sha256") != activation["activation_sha256"]
        or entry.get("bundle_sha256") != bundle["bundle_sha256"]
        or entry.get("fqbn") != expected_firmware["fqbn"]
        or entry.get("build_identity") != expected_firmware["build_identity"]
        or entry.get("build_manifest_sha256")
        != expected_firmware["build_manifest"]["sha256"]
        or entry.get("uf2_sha256") != expected_firmware["uf2"]["sha256"]
        or entry.get("profile_id") != expected_firmware["profile_id"]
        or entry.get("board_after")
        != manifest_firmware.get("board_identity_after_upload")
        or entry.get("board_before_sha256")
        != canonical_sha256(entry.get("board_before"))
        or entry.get("board_after_sha256")
        != canonical_sha256(entry.get("board_after"))
        or entry.get("board_identity_fingerprint_sha256")
        != canonical_sha256(_board_identity_fingerprint(entry.get("board_before", {})))
        or _board_identity_fingerprint(entry.get("board_before", {}))
        != _board_identity_fingerprint(entry.get("board_after", {}))
    ):
        raise ValueError("retained firmware-entry identity differs")

    expected_device = str(manifest.get("host", {}).get("post_upload_fresh_device", ""))
    if (
        not expected_device
        or entry.get("device_after") != expected_device
        or manifest.get("host", {}).get(
            "capture_performs_own_auto_detect_before_open"
        )
        is not True
    ):
        raise ValueError("post-upload capture device binding differs")
    closure_ok, closure, closure_reason = _capture_closure_success(
        run_dir=run_dir, expected_device=expected_device
    )
    if not closure_ok or closure is None:
        raise ValueError(f"retained capture closure differs: {closure_reason}")
    capture_state = _read(run_dir / "reports/capture_device_state.json")
    if (
        capture_state.get("capture_active") is not False
        or capture_state.get("serial_open") is not False
        or capture_state.get("logical_segment_closed") is not True
        or capture_state.get("physical_serial_open") is not False
    ):
        raise ValueError("retained capture final state differs")
    lifecycle_path = run_dir / RUN_LIFECYCLE_PATH
    lifecycle = _read(lifecycle_path)
    lifecycle_unsigned = {
        key: value for key, value in lifecycle.items() if key != "record_sha256"
    }
    if (
        lifecycle.get("record_sha256") != canonical_sha256(lifecycle_unsigned)
        or lifecycle.get("status") != "capture_closed_successfully"
        or lifecycle.get("capture_returncode") != 0
        or lifecycle.get("capture_closure_success") is not True
        or lifecycle.get("capture_closure")
        != _binding(run_dir / "reports/capture_segment_closure_v1.json")
        or lifecycle.get("capture_closure_record_sha256")
        != canonical_sha256(closure)
        or lifecycle.get("run_manifest_sha256") != manifest_sha256
        or lifecycle.get("authority_and_wall_terminal_s") != 108000
        or lifecycle.get("capture_duration_s")
        != 108000 + CAPTURE_EVIDENCE_DRAIN_MARGIN_S
        or lifecycle.get("post_terminal_evidence_drain_and_abort_margin_s")
        != CAPTURE_EVIDENCE_DRAIN_MARGIN_S
    ):
        raise ValueError("retained run lifecycle or capture return differs")
    return {
        "activation_sha256": activation["activation_sha256"],
        "bundle_sha256": bundle["bundle_sha256"],
        "build_identity": expected_firmware["build_identity"],
        "fqbn": expected_firmware["fqbn"],
        "firmware_entry_sha256": entry["record_sha256"],
        "manifest_sha256": manifest_sha256,
        "capture_closure_sha256": lifecycle["capture_closure"]["sha256"],
        "capture_returncode": 0,
        "capture_duration_s": lifecycle["capture_duration_s"],
        "authority_and_wall_terminal_s": lifecycle[
            "authority_and_wall_terminal_s"
        ],
    }


def analyze_run(
    run_dir: Path,
    *,
    output_path: Path | None = None,
    state_override: Mapping[str, Any] | None = None,
    terminal_override: Mapping[str, Any] | None = None,
    offline_supersession: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce the engineering-only analysis before immutable sealing."""
    run_dir = run_dir.resolve()
    manifest = _read(run_dir / "run_manifest.json")
    if manifest.get("stage") != LIVE_STAGE or manifest.get("compatibility_floor") != EVIDENCE_EPOCH:
        raise ValueError("not a frequency-only digital endurance live package")
    _require_exact_capture_contract(manifest, owner="frequency-only live manifest")
    lifecycle_provenance = _validate_live_package_lifecycle(
        run_dir=run_dir, manifest=manifest
    )
    recorded_state = _read(run_dir / SUPERVISOR_STATE_PATH)
    state = dict(state_override) if state_override is not None else recorded_state
    recorded_terminal_state = recorded_state.get("terminal")
    terminal_state = (
        dict(terminal_override)
        if terminal_override is not None
        else recorded_terminal_state
    )
    if not isinstance(terminal_state, dict) or not terminal_state.get("result"):
        raise ValueError("shared active supervisor terminal is absent")
    terminal = str(terminal_state.get("reason"))
    health = _latest_health(run_dir / "csv/health.csv")
    d9_missing, d9_mismatches = _d9_gate(health)
    contract = load_contract()
    transaction_rows = _read_csv_rows(run_dir / ACTIVE_CSV)
    _, identities, _ = load_no_write_qualification_spec("A")
    spec = CampaignSpec(
        campaign="d9_d6_frequency_only_digital_endurance",
        profile=contract["profile_id"],
        run_identity="d9_d6_frequency_only_endurance:1",
        start_code=0xA808,
        correction_limit=48,
        cumulative_limit=1008,
        minimum_code=0xA800,
        maximum_code=0xAB00,
        maximum_step=21,
    )
    validate_transaction_history(
        transaction_rows,
        spec,
        identities,
        str(manifest["firmware"]["build_identity"]),
        dual_core=True,
    )
    exact_transaction_timing = _reconcile_exact_transaction_timing(
        run_dir=run_dir,
        transactions=transaction_rows,
    )
    exact_application_ticks = _exact_application_ticks(
        run_dir=run_dir, transactions=transaction_rows
    )
    _validate_exact_application_cadence(
        exact_application_ticks,
        minimum_cadence_s=int(
            contract["envelope"]["minimum_application_cadence_s"]
        ),
    )
    manual = [row for row in transaction_rows if row.get("event") == "manual_start"]
    applications = [row for row in transaction_rows if row.get("event") == "application"]
    responses = [row for row in transaction_rows if row.get("event") == "response"]
    cumulative = sum(abs(int(row["requested_delta_codes"])) for row in applications)
    codes = [int(row["applied_code"]) for row in applications]
    transaction_quiescent = bool(
        transaction_rows
        and transaction_rows[-1].get("event")
        in {"manual_start", "response", "request_withdrawn"}
    )
    windows, window_fitness = _selected_window_fitness(run_dir)
    candidate_window_fitness = _candidate_fll_window_fitness(
        canonical_d14_d8_intervals(run_dir)
    )
    stationary = _stationary_epoch_metrics(windows)
    stationary_errors = [
        float(row["frequency_error_hz"])
        for row in windows
        if row["window_qualified"] and row["settling_complete"]
    ]
    envelope = contract["envelope"]
    first_path_exact = not applications or (
        bool(responses)
        and int(responses[0]["request_sequence"])
        == int(applications[0]["request_sequence"])
    )
    ceiling_exhausted = (
        len(applications) == int(envelope["maximum_automatic_applications"])
        or cumulative == int(envelope["maximum_cumulative_movement_codes"])
    )
    opportunity_count = int(state.get("control_opportunity_count", 0))
    pending_opportunities = state.get("pending_control_opportunity_sequences", [])
    opportunity_dispositions = state.get("lost_opportunity_dispositions", {})
    opportunity_accounting_complete = (
        opportunity_count > 0
        and isinstance(pending_opportunities, list)
        and not pending_opportunities
        and isinstance(opportunity_dispositions, dict)
        and int(opportunity_dispositions.get("applied", 0)) == len(applications)
    )
    if terminal == "frequency_only_d9_d6_digital_endurance_passed" and not opportunity_accounting_complete:
        raise ValueError(
            "passed endpoint lacks complete per-opportunity causal accounting"
        )
    d6_rows = _read_csv_rows(run_dir / "csv/forwarded_monitor_snapshots.csv")
    d6_sequences = [
        int(row["snapshot_sequence"])
        for row in d6_rows
        if _safe_int(row.get("snapshot_sequence")) is not None
    ]
    d6_continuous = all(
        _u32_successor(left, right)
        for left, right in zip(d6_sequences, d6_sequences[1:])
    )
    d6_valid = sum(
        row.get("record_type") == "MNS"
        and row.get("channel_id") == "3"
        and _safe_int(row.get("status")) == 0
        for row in d6_rows
    )
    envelope_invariants = {
        "setup_count_exactly_one": len(manual) == 1,
        "automatic_application_ceiling_respected": len(applications) <= 48,
        "total_physical_write_ceiling_respected": len(manual) + len(applications) <= 49,
        "cumulative_absolute_movement_ceiling_respected": cumulative <= 1008,
        "per_step_ceiling_respected": all(
            abs(int(row["requested_delta_codes"])) <= 21 for row in applications
        ),
        "dac_range_respected": all(0xA800 <= code <= 0xAB00 for code in codes),
        "one_outstanding_transaction_and_endpoint_quiescent": transaction_quiescent,
        "setup_retry_count": 0,
        "restore_write_count": 0,
        "phase_or_hybrid_authority_or_application_count": 0,
        "first_complete_consumer_response_path_exact": first_path_exact,
        "limits_are_nonbinding_ceiling_not_target": True,
        "minimum_exact_AT2_application_cadence_respected": True,
    }
    analysis = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "analysis_identity": canonical_sha256({"tool": TOOL_ID, "contract": load_contract()["contract_semantic_sha256"]}),
        "run_id": manifest["run_id"],
        "bundle_sha256": manifest["frequency_only_engineering"]["bundle_sha256"],
        "terminal": terminal,
        "active_supervisor_terminal": recorded_terminal_state,
        "derived_terminal": terminal_state,
        "lifecycle_provenance": lifecycle_provenance,
        "qualified_duration_s": state.get("qualified_duration_s"),
        "milestones_qualified_s": state.get("milestones_qualified_s"),
        "d9_digital_readback_exact_at_analysis": not d9_missing and not d9_mismatches,
        "d9_missing": d9_missing,
        "d9_mismatches": d9_mismatches,
        "d6_missing_observability": state.get("d6_missing_observability", []),
        "d6_diagnostic_only": {
            "snapshot_count": len(d6_rows),
            "valid_snapshot_count": d6_valid,
            "snapshot_sequence_continuous": d6_continuous,
            "control_authority": False,
            "measurement_qualification_authority": False,
            "terminal_authority": False,
        },
        "exact_transaction_timing": exact_transaction_timing,
        "envelope": {
            "maximum_automatic_applications": 48,
            "maximum_cumulative_absolute_codes": 1008,
            "maximum_total_physical_dac_writes": 49,
            "observed_automatic_applications": len(applications),
            "observed_cumulative_absolute_codes": cumulative,
            "observed_total_physical_dac_writes": len(manual) + len(applications),
            "automatic_application_utilization_fraction": len(applications) / 48,
            "cumulative_path_utilization_fraction": cumulative / 1008,
            "total_write_utilization_fraction": (len(manual) + len(applications)) / 49,
            "authority_ceiling_exhausted": ceiling_exhausted,
            "ceiling_values_are_not_activity_targets": True,
            "invariants": envelope_invariants,
        },
        "fll_window_fitness": {
            **window_fitness,
            "implemented_selected_estimator_window_s": 600,
            "shorter_window_fitness_assessed": True,
            "longer_window_fitness_assessed": True,
            "candidate_window_comparison": candidate_window_fitness,
            "limitation": (
                "Candidate windows are offline observational reconstructions "
                "from canonical D14/D8 evidence; only the selected 600 s "
                "estimator had runtime control authority."
            ),
            "windows": windows,
        },
        "d14_relative_frequency_error_hz": _distribution(stationary_errors),
        "stationary_dac_epoch_vcocxo_drift": stationary,
        "frequency_horizons_s": _frequency_horizon_metrics(windows),
        "response_and_overshoot": _response_and_horizon_metrics(
            transaction_rows,
            windows,
            endpoint_source_sequence=_safe_int(
                state.get("last_qualified_count_sequence")
            ),
        ),
        "chatter": _chatter_metrics(transaction_rows),
        "lost_opportunities": {
            "control_opportunity_count": opportunity_count,
            "eligible_control_opportunity_count": state.get(
                "eligible_control_opportunity_count", 0
            ),
            "pending_control_opportunity_sequences": pending_opportunities,
            "every_eligible_opportunity_has_exact_disposition": opportunity_accounting_complete,
            "zero_automatic_applications_valid_only_with_nonempty_complete_ledger": True,
            "dispositions": opportunity_dispositions,
            "deadband_and_cadence_holds_are_not_failures": True,
            "platform_loss_requires_an_explicit_platform_disposition": True,
        },
        "gnss_metadata_hold": {
            "episode_count": state.get("gnss_metadata_hold_count", 0),
            "active_at_endpoint": state.get("gnss_metadata_hold_active", False),
            "effective_firmware_and_live_supervisor_semantics": True,
            "last_retained_session_code_epoch_identity": state.get(
                "gnss_metadata_hold_identity"
            ),
            "d14_d8_measurement_continues": True,
            "new_correction_authority": False,
            "fresh_causal_requalification_required": True,
        },
        "host_automatic_dac_commands_sent": state.get("automatic_dac_commands_sent_by_host"),
        "host_phase_or_hybrid_commands_sent": state.get("phase_or_hybrid_commands_sent_by_host"),
        "engineering_only": True,
        "unresolved_delivered_output_claims": contract["unresolved_delivered_output_claims"],
        "physical_waveform_qualification": False,
    }
    if offline_supersession is not None:
        analysis["offline_supersession"] = dict(offline_supersession)
    _write_new(
        output_path.resolve() if output_path is not None else run_dir / ANALYSIS_PATH,
        analysis,
    )
    return analysis


def seal_and_register(*, run_dir: Path, index_path: Path) -> dict[str, Any]:
    """Seal an already-stopped package, snapshot it, then register its tree."""
    run_dir = run_dir.resolve()
    if (run_dir / "capture_in_progress.flag").exists():
        raise RuntimeError("capture remains active; refusing to seal mutable evidence")
    analysis = analyze_run(run_dir)
    manifest = _read(run_dir / "run_manifest.json")
    seal_unsigned = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "run_id": manifest["run_id"],
        "analysis_sha256": sha256((run_dir / ANALYSIS_PATH).read_bytes()).hexdigest(),
        "bundle_sha256": analysis["bundle_sha256"],
        "terminal": analysis["terminal"],
        "engineering_only": True,
        "unresolved_delivered_output_claims": analysis["unresolved_delivered_output_claims"],
    }
    _write_new(run_dir / SEAL_PATH, {**seal_unsigned, "seal_sha256": canonical_sha256(seal_unsigned)})
    (run_dir / "COMPLETE").touch(exist_ok=False)
    snapshot = create_evidence_snapshot(run_dir)
    result = register_package(
        index_path=index_path,
        package_path=run_dir,
        source_revision=str(manifest["firmware"]["source_revision"]),
        build_identity=str(manifest["firmware"]["build_manifest_sha256"]),
        profile_identity=str(manifest["frequency_only_engineering"]["profile_id"]),
        attempt_classification=("completed_campaign" if analysis["terminal"] == "frequency_only_d9_d6_digital_endurance_passed" else "failed_qualification"),
        result_or_failure_reason=str(analysis["terminal"]),
        analyzer_identity=sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    return {"analysis": str(run_dir / ANALYSIS_PATH), "seal": str(run_dir / SEAL_PATH), "snapshot": str(snapshot), "registered_content_sha256": result["content_sha256"], "terminal": analysis["terminal"]}


def _rehearsal_transaction_rows(bundle: Mapping[str, Any]) -> list[dict[str, str]]:
    """Two complete frequency-only lifecycles for the actual supervisor path."""
    from .active_hybrid_rehearsal import _transaction_rows

    _, identities, _ = load_no_write_qualification_spec("A")
    build_identity = str(bundle["firmware"]["build_identity"])
    current_code = 0xA808
    rows: list[dict[str, str]] = []
    cumulative = 0
    record_sequence = 2
    for request, (timestamp_s, delta) in enumerate(((1800, 1), (3600, -1)), start=1):
        cumulative += abs(delta)
        decision = SimpleNamespace(
            decision_sequence=request,
            source_first_sequence=timestamp_s - 599,
            source_last_sequence=timestamp_s,
            timestamp_s=timestamp_s,
            current_applied_code=current_code,
            requested_delta_codes=delta,
            requested_code=current_code + delta,
            frequency_error_hz=-delta * 0.001,
        )
        phases = _transaction_rows(
            decision,
            record_sequence=record_sequence,
            request_sequence=request,
            application_sequence=request,
            dac_epoch=request + 1,
            cumulative_movement=cumulative,
            run_identity="d9_d6_frequency_only_endurance:1",
            build_identity=build_identity,
            policy_sha256=identities["active_policy_sha256"],
            estimator_sha256=identities["estimator_sha256"],
            model_sha256=identities["model_sha256"],
            response_policy_sha256=identities["response_policy_sha256"],
            numerical_policy_sha256=identities["numerical_policy_sha256"],
            profile_identity="d9_d6_frequency_only_lower",
        )
        rows.extend(phases)
        current_code += delta
        record_sequence += len(phases)
    manual = dict(rows[0])
    manual.update(
        {
            "transaction_record_sequence": "1",
            "event": "manual_start",
            "authorization_sequence": "0",
            "nonce": "0",
            "request_sequence": "0",
            "decision_sequence": "0",
            "source_first_sequence": "0",
            "source_last_sequence": "0",
            "decision_timestamp_s": "1",
            "current_applied_code": str(0xA808),
            "requested_delta_codes": "0",
            "requested_code": str(0xA808),
            "correction_ordinal": "0",
            "cumulative_after_codes": "0",
            "pre_error_hz": "0.000000000000",
            "accepted_code": str(0xA808),
            "accepted_timestamp_s": "1",
            "applied_code": str(0xA808),
            "application_sequence": "0",
            "application_timestamp_s": "1",
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
            "evidence_state": "evidence_clear",
        }
    )
    return [manual, *rows]


def _rehearsal_transaction_timing_rows(
    transactions: list[dict[str, str]],
) -> list[dict[str, str]]:
    phase_offset = {
        "manual_start": 0,
        "request_created": 0,
        "core0_accepted": 1,
        "application": 2,
        "response": 3,
        "request_withdrawn": 1,
    }
    result: list[dict[str, str]] = []
    for timing_sequence, transaction in enumerate(transactions, start=1):
        row = {field: "" for field in ACTIVE_TRANSACTION_V2_FIELDS}
        row.update(
            {
                field: transaction[field]
                for field in ACTIVE_TRANSACTION_TIMING_JOIN_FIELDS
            }
        )
        event = transaction["event"]
        row.update(
            {
                "record_type": "AT2",
                "schema_version": "2",
                "timing_record_sequence": str(timing_sequence),
                "event_timestamp_ticks": str(
                    int(transaction["decision_timestamp_s"]) * TIMER_HZ
                    + phase_offset[event]
                ),
                "time_domain": EXACT_LIFECYCLE_TIME_DOMAIN,
            }
        )
        result.append(row)
    return result


def _write_csv_rows(
    path: Path, fields: list[str] | tuple[str, ...], rows: list[dict[str, str]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def pty_operational_rehearsal(*, bundle: Mapping[str, Any], output_dir: Path) -> dict[str, object]:
    """Exercise capture plus the actual repeated-transaction supervisor path."""
    checked = validate_bundle(bundle); output_dir.mkdir(parents=True, exist_ok=False)
    run_dir = output_dir / "run"; run_dir.mkdir(); transition = output_dir / "transition"; carrier = output_dir / "carrier"
    master, slave = pty.openpty(); device = os.ttyname(slave); os.close(slave)
    upload_commands: list[list[str]] = []
    detected_devices = iter((device, device))
    rehearsal_board = {
        "address": device,
        "hardware_id": "PTY_REHEARSAL_BOARD",
        "serial_number": "PTY_REHEARSAL_BOARD",
        "vid": "0x0000",
        "pid": "0x0000",
        "product": "deterministic PTY fixture",
        "board_name": "deterministic PTY fixture",
        "board_fqbn": "rp2040:rp2040:arduino_nano_connect",
    }

    def injected_upload(command: list[str], **_: object) -> SimpleNamespace:
        upload_commands.append(command)
        return SimpleNamespace(returncode=0, stdout="deterministic upload", stderr="")

    rehearsal_activation = {
        "activation_sha256": canonical_sha256(
            {
                "mode": "PTY_NON_EFFECTIVE_REHEARSAL",
                "bundle_sha256": checked["bundle_sha256"],
            }
        ),
        "effective": False,
        "physical_authority": False,
        "authority": _firmware_flash_authority(),
    }
    rehearsal_upload_attempt_path = (
        output_dir / "rehearsal_activation_firmware_upload_attempt_v1.json"
    )
    post_upload_device, post_upload_board, rehearsal_firmware_entry = (
        _execute_activation_authorized_upload(
            run_dir=run_dir,
            activation=rehearsal_activation,
            bundle=checked,
            fresh_detect=lambda: next(detected_devices),
            identity_reader=lambda observed: {**rehearsal_board, "address": observed},
            owner_reader=lambda _: set(),
            upload_runner=injected_upload,
            sleep_fn=lambda _: None,
            reenumeration_timeout_s=1.0,
            hardware_operations=False,
            upload_attempt_path=rehearsal_upload_attempt_path,
        )
    )
    replay_run_dir = output_dir / "forbidden_activation_replay"
    replay_run_dir.mkdir()
    try:
        _execute_activation_authorized_upload(
            run_dir=replay_run_dir,
            activation=rehearsal_activation,
            bundle=checked,
            fresh_detect=lambda: (_ for _ in ()).throw(
                AssertionError("consumed activation reached device detection")
            ),
            identity_reader=lambda _: rehearsal_board,
            owner_reader=lambda _: set(),
            upload_runner=injected_upload,
            sleep_fn=lambda _: None,
            reenumeration_timeout_s=1.0,
            hardware_operations=False,
            upload_attempt_path=rehearsal_upload_attempt_path,
        )
    except FileExistsError:
        global_activation_consumption_replay_blocked = True
    else:
        raise RuntimeError("consumed rehearsal activation permitted a second upload")
    production_capture_command = live_capture_command(
        run_dir=run_dir,
        expected_device=post_upload_device,
        duration_s=int(load_contract()["envelope"]["absolute_wall_limit_s"])
        + CAPTURE_EVIDENCE_DRAIN_MARGIN_S,
    )
    if (
        len(upload_commands) != 1
        or upload_commands[0].count("--input-file") != 1
        or "--auto-detect" not in production_capture_command
        or "--device" in production_capture_command
    ):
        raise RuntimeError("deterministic production upload/capture orchestration differs")
    capture_contract = _exact_capture_contract()
    _write_new(
        run_dir / "run_manifest.json",
        {
            "schema_version": 1,
            "template": False,
            "run_id": "d9_d6_frequency_only_endurance_pty",
            "stage": "D9_D6_FREQUENCY_ONLY_DIGITAL_ENDURANCE_REHEARSAL",
            "profile_id": checked["profile_id"],
            "bundle_sha256": checked["bundle_sha256"],
            "firmware_upload_rehearsal": {
                "record": _binding(run_dir / FIRMWARE_ENTRY_PATH),
                "record_sha256": rehearsal_firmware_entry["record_sha256"],
                "post_upload_device": post_upload_device,
                "post_upload_board": post_upload_board,
                "hardware_operations": False,
            },
            "actionable": False,
            "actuation_authorized": False,
            "host": {
                "serial_device": device,
                "baud": 115200,
                "sole_serial_owner": True,
                "capture_tool": "host.otis_tools.capture_device",
            },
            **capture_contract,
            "channels": [
                {"channel_id": 1, "role": "authoritative_d14_reference"},
                {"channel_id": 2, "role": "authoritative_d8_count"},
                {
                    "channel_id": 3,
                    "role": "diagnostic_d6_forwarded_d9_monitor",
                    "zero_authority": True,
                },
            ],
            "evidence_artifacts": [],
        },
    )
    normal = run_dir / "control/normal_commands.fifo"; emergency = run_dir / "control/emergency_abort.fifo"
    capture = subprocess.Popen([sys.executable, "-m", "host.otis_tools.capture_device", "--device", device, "--baud", "115200", "--run-dir", str(run_dir), "--duration-s", "20", "--command-fifo", str(normal), "--emergency-command-fifo", str(emergency), "--normal-command-max-age-s", "2", "--segment-control-dir", str(carrier), "--segment-capability", "d9-d6-frequency-only-endurance-rehearsal"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not normal.exists(): time.sleep(.05)
        if not normal.exists(): raise RuntimeError("capture FIFO unavailable")
        send_timestamped_command_to_fifo(normal, "CONFIG?")
        time.sleep(.1); send_command_to_fifo(emergency, "ACTIVE ABORT")
        deadline = time.monotonic() + 5; observed = b""
        while time.monotonic() < deadline:
            readable, _, _ = select.select([master], [], [], .1)
            if readable: observed += os.read(master, 4096)
            if b"ACTIVE ABORT\n" in observed: break
        if b"ACTIVE ABORT\n" not in observed: raise RuntimeError("priority abort not delivered")
        prepare_transition(run_dir / "run_manifest.json", transition)
        rotation = request_rotation(control_dir=carrier, capability="d9-d6-frequency-only-endurance-rehearsal", to_run=transition, mode="transition", operation_id="d9-d6-frequency-only-endurance-pty")
    finally:
        if capture.poll() is None: capture.send_signal(signal.SIGINT)
        output, _ = capture.communicate(timeout=10); os.close(master)
    if capture.returncode != 0: raise RuntimeError(f"capture rehearsal failed: {output[-1000:]}")
    supervisor = create_live_supervisor(run_dir=run_dir, bundle=checked)
    startup_commands: list[str] = []
    supervisor._command = startup_commands.append  # type: ignore[method-assign]
    startup_identity = {
        "run_identity": supervisor.spec.run_identity,
        "build_identity": supervisor.expected_build_identity,
        "profile_identity": supervisor.spec.profile,
        **supervisor.identities,
    }
    startup_health = canonical_prewrite_fixture(
        expected_identity=startup_identity,
        planned_live_stimulus_code=supervisor.spec.start_code,
    )
    startup_health.update({
        ("cx317_active", "run_identity"): supervisor.spec.run_identity,
        ("cx317_active", "build_identity"): supervisor.expected_build_identity,
        ("cx317_active", "profile_identity"): supervisor.spec.profile,
        ("cx317_active", "session_id"): "4",
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "reason"): "initialized_disarmed",
        ("cx317_active", "manual_start_confirmed"): "false",
        ("cx317_active", "snapshot_generation_complete"): "7",
        ("cx317_active", "query_nonce"): str(
            supervisor.state["host_attach_query_nonce"]
        ),
        ("cx317_active", "uptime_s"): "1000",
        ("forwarded_clock_output", "first_valid_ticks"): "100",
        **EXPECTED_D9_HEALTH,
    })
    for key, value in supervisor.identities.items():
        startup_health[("cx317_active", key)] = value
    startup_health[("cx317_active", "setup_gnss_eligible")] = "false"
    startup_health[("cx317_active", "setup_reference_eligible")] = "false"
    supervisor._check_fail_static_health({})
    supervisor._check_fail_static_health(
        {("command", "config_snapshot"): "begin"}
    )
    supervisor._maybe_start_or_arm(startup_health)
    if startup_commands or supervisor.state["terminal"] is not None:
        raise RuntimeError(
            "frequency-only startup did not hold while CONFIG was backlogged"
        )
    startup_health[("command", "config_snapshot")] = "end"
    supervisor._check_fail_static_health(startup_health)
    supervisor._maybe_start_or_arm(startup_health)
    if startup_commands or not supervisor.state["d9_exact_readback_established"]:
        raise RuntimeError(
            "frequency-only setup authority hold did not inhibit setup after "
            "D9 establishment"
        )
    startup_health[("cx317_active", "setup_gnss_eligible")] = "true"
    startup_health[("cx317_active", "setup_reference_eligible")] = "true"
    supervisor._maybe_start_or_arm(startup_health)
    setup_commands = [
        command
        for command in startup_commands
        if command.startswith("ACTIVE SETUP ")
    ]
    if (
        len(setup_commands) != 1
        or not supervisor.state["d9_exact_readback_established"]
        or supervisor.state["terminal"] is not None
    ):
        raise RuntimeError(
            "frequency-only startup did not establish D9 before exact setup"
        )
    tdb_row = {
        field: "" for field in CONTRACT_FIELDS["tight_deadband_decisions_v1"]
    }
    tdb_row.update(
        {
            "record_type": "TDB",
            "schema_version": "1",
            "decision_sequence": "1",
            "estimate_id": "est:cx317:selected600:000001",
            "decision_timestamp_ticks": str(600 * TIMER_HZ),
            "time_domain": "rp2040_timer0",
            "capture_session": "4",
            "dac_epoch": "1",
            "integer_edge_error_counts": "4",
            "absolute_edge_error_counts": "4",
            "state_before": "REQUALIFY_OUTSIDE",
            "state_after": "OUTSIDE",
            "entry_counter": "0",
            "release_counter": "0",
            "transition": "true",
            "frequency_controller_eligible": "true",
            "requalified": "false",
            "requalification_reason": "",
            "historical_v2_inside": "false",
            "symmetric_two_count_inside": "false",
            "policy_id": "CX318_STAGE5_TIGHT_HYSTERETIC_COUNTS_V1",
            "policy_sha256": supervisor.identities["active_policy_sha256"],
            "actionable": "false",
            "actuation_authorized": "false",
            "authorization_consumed": "false",
            "reason_codes": "outside_loose_evidence",
        }
    )
    _write_csv_rows(
        run_dir / "csv/tight_deadband_decisions_v1.csv",
        CONTRACT_FIELDS["tight_deadband_decisions_v1"],
        [tdb_row],
    )
    replayed_tdb = supervisor._latest_tdb()
    if (
        replayed_tdb is None
        or replayed_tdb["policy_sha256"]
        != supervisor.identities["active_policy_sha256"]
        or supervisor.tight_deadband_policy_sha256
        != supervisor.identities["active_policy_sha256"]
    ):
        raise RuntimeError(
            "frequency-only live supervisor did not replay the firmware policy identity"
        )
    transaction_rows = _rehearsal_transaction_rows(checked)
    _write_csv_rows(
        run_dir / ACTIVE_CSV,
        ACTIVE_TRANSACTION_V1_FIELDS,
        transaction_rows,
    )
    _write_csv_rows(
        run_dir / "csv" / ACTIVE_TRANSACTIONS_V2_CSV,
        ACTIVE_TRANSACTION_V2_FIELDS,
        _rehearsal_transaction_timing_rows(transaction_rows),
    )
    supervisor.state["acknowledged_record_sequences"] = list(
        range(2, len(transaction_rows) + 1)
    )
    supervisor.state["observed_manual_record_sequences"] = [1]
    supervisor._save()
    supervisor._process_transactions()
    opening_ticks = 100
    closing_ticks = opening_ticks + TIMER_HZ
    _write_csv_rows(
        run_dir / "csv/raw_events.csv",
        CONTRACT_FIELDS["raw_events_v1"],
        [
            {
                "record_type": "REF",
                "schema_version": "1",
                "event_seq": "1",
                "channel_id": "1",
                "edge": "R",
                "timestamp_ticks": str(opening_ticks),
                "capture_domain": "rp2040_timer0",
                "flags": "0",
            },
            {
                "record_type": "REF",
                "schema_version": "1",
                "event_seq": "2",
                "channel_id": "1",
                "edge": "R",
                "timestamp_ticks": str(closing_ticks),
                "capture_domain": "rp2040_timer0",
                "flags": "0",
            },
        ],
    )
    _write_csv_rows(
        run_dir / "csv/pps_snapshots.csv",
        CONTRACT_FIELDS["pps_snapshots_v1"],
        [
            {
                "record_type": "SNP",
                "schema_version": "1",
                "session": "4",
                "snapshot_sequence": "0",
                "cumulative_down_counter": "20000000",
                "reference_sequence": "10",
                "reference_timestamp_ticks": str(opening_ticks),
                "status": "0",
                "backend": EXPECTED_D8_SNAPSHOT_BACKEND,
            },
            {
                "record_type": "SNP",
                "schema_version": "1",
                "session": "4",
                "snapshot_sequence": "1",
                "cumulative_down_counter": "10000000",
                "reference_sequence": "11",
                "reference_timestamp_ticks": str(closing_ticks),
                "status": "0",
                "backend": EXPECTED_D8_SNAPSHOT_BACKEND,
            },
        ],
    )
    _write_csv_rows(
        run_dir / "csv/count_observations.csv",
        CONTRACT_FIELDS["count_observations_v1"],
        [
            {
                "record_type": "CNT",
                "schema_version": "1",
                "count_seq": "1",
                "channel_id": "2",
                "gate_open_ticks": str(opening_ticks),
                "gate_close_ticks": str(closing_ticks),
                "gate_domain": "rp2040_timer0",
                "counted_edges": "10000000",
                "source_edge": "R",
                "source_domain": "h1_cx317_ocxo_10mhz",
                "flags": "0",
            }
        ],
    )
    startup_health.update(
        {
            ("cx317_active", "manual_start_confirmed"): "true",
            ("cx317_active", "confirmed_applied_code_known"): "true",
            ("cx317_active", "confirmed_applied_code"): str(
                supervisor.spec.start_code
            ),
            ("cx317_active", "dac_epoch"): "1",
            ("cx317_active", "evidence_phase"): "evidence_clear",
            ("cx317_active", "evidence_pending"): "false",
        }
    )
    supervisor._maybe_qualify(startup_health)
    supervisor._maybe_finish(startup_health, time.time(), 0.0)
    if (
        supervisor.accounting.armed_ticks != closing_ticks
        or supervisor.state["soak_armed_frontier_ticks"] != closing_ticks
        or supervisor.state["soak_armed_count_sequence"] != 1
        or supervisor.state["terminal"] is not None
    ):
        raise RuntimeError(
            "actual frequency-only supervisor exact-counter arm transition differed"
        )
    _write_csv_rows(
        run_dir / "csv" / CONTROL_PREVIEWS_CSV,
        [
            "control_seq",
            "decision_id",
            "decision_timestamp_ticks",
            "time_domain",
            "control_state",
            "preview_eligibility",
            "limited_delta_codes",
            "preview_available",
            "actuation_authorized",
            "actionable",
            "decision_reason_code",
        ],
        [
            {
                "control_seq": str(sequence),
                "decision_id": f"rehearsal:{sequence}",
                "decision_timestamp_ticks": str(timestamp_s * TIMER_HZ),
                "time_domain": "rp2040_timer0",
                "control_state": "ACTIVE",
                "preview_eligibility": "true",
                "limited_delta_codes": str(delta),
                "preview_available": "true",
                "actuation_authorized": "true",
                "actionable": "true",
                "decision_reason_code": "actionable_request",
            }
            for sequence, (timestamp_s, delta) in enumerate(
                ((1800, 1), (3600, -1)), start=1
            )
        ],
    )
    supervisor._update_lost_opportunities({})
    if (
        supervisor.state["response_count"] != 2
        or supervisor.state["automatic_applications"] != 2
        or supervisor.state["transaction_outstanding"] != 0
        or supervisor.state["lost_opportunity_dispositions"] != {"applied": 2}
        or supervisor.state["pending_control_opportunity_sequences"]
        or supervisor.state["terminal"] is not None
    ):
        raise RuntimeError("actual frequency-only supervisor did not retain repeated responses observationally")
    last_response = [
        row for row in transaction_rows if row.get("event") == "response"
    ][-1]
    hold_health = {
        ("cx317_active", "state"): "GNSS_METADATA_HOLD",
        ("cx317_active", "reason"): "gnss_metadata_unqualified_hold",
        ("cx317_active", "gnss_metadata_hold_active"): "true",
        ("cx317_active", "confirmed_applied_code_known"): "true",
        ("cx317_active", "confirmed_applied_code"): last_response[
            "applied_code"
        ],
        ("cx317_active", "dac_epoch"): last_response["dac_epoch"],
        ("cx317_active", "correction_count"): last_response["correction_count"],
        ("cx317_active", "cumulative_movement_codes"): last_response[
            "cumulative_movement_codes"
        ],
        ("cx317_active", "session_id"): last_response["session_id"],
        ("cx317_active", "gnss_metadata_hold_entry_sequence"): "40",
        ("cx317_active", "gnss_metadata_hold_transaction_pending"): "false",
    }
    supervisor._update_metadata_hold(hold_health)
    recovered_health = {
        **hold_health,
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "gnss_metadata_hold_active"): "false",
        ("cx317_active", "reason"): (
            "reference_requalified_fresh_authorization_required"
        ),
        ("cx317_active", "gnss_metadata_requalification_sequence"): "41",
        ("cx317_active", "gnss_metadata_qualification_frontier"): "100",
        ("cx317_active", "d14_d8_observation_sequence"): "101",
    }
    supervisor._update_metadata_hold(recovered_health)
    if (
        supervisor.state["gnss_metadata_hold_active"]
        or supervisor.state["gnss_metadata_hold_count"] != 1
    ):
        raise RuntimeError(
            "actual frequency-only supervisor GNSS metadata hold rehearsal differed"
        )
    accelerated_contract = json.loads(json.dumps(load_contract()))
    accelerated_contract["envelope"]["qualified_duration_s"] = 4
    accelerated_contract["envelope"]["milestone_qualified_duration_s"] = 1
    accounting = EnduranceSupervisor(accelerated_contract)
    accounting.arm(
        frontier_ticks=0,
        d9_state="configured_10mhz_forwarded_unqualified",
        d9_readback_exact=True,
        d14_d8_healthy=True,
        outstanding_transaction=False,
        applied_code=0xA808,
        dac_epoch=1,
    )
    for second in range(4):
        accounting.observe_interval(
            opening_ticks=second * TIMER_HZ,
            closing_ticks=(second + 1) * TIMER_HZ,
            measurement_qualified=True,
            d9_valid=True,
            count_sequence=second + 1,
        )
    metadata_fact = gnss_metadata_hold_oracle_fact(
        capture_session="rehearsal",
        frontier=3600,
        applied_code=0xA808,
        dac_epoch=3,
    )
    production_target_ticks = (
        int(load_contract()["envelope"]["qualified_duration_s"]) * TIMER_HZ
    )
    long_analysis_horizon_keeps_admission_open = not _correction_admission_closed(
        production_target_ticks - max(RESPONSE_HORIZONS_S) * TIMER_HZ,
        production_target_ticks,
    )
    exact_response_reserve_closes_admission = _correction_admission_closed(
        production_target_ticks - APPLICATION_ADMISSION_RESERVE_S * TIMER_HZ,
        production_target_ticks,
    )
    if (
        not accounting.target_reached
        or metadata_fact["mode"] != "GNSS_METADATA_HOLD"
        or metadata_fact["effective_actuation_permitted"] is not False
        or metadata_fact["measurement_continues"] is not True
        or not long_analysis_horizon_keeps_admission_open
        or not exact_response_reserve_closes_admission
    ):
        raise RuntimeError("accelerated endpoint or GNSS metadata-hold oracle differed")
    report = {"schema_version": 1, "tool": TOOL_ID, "report_type": "frequency_only_exact_operational_rehearsal_v1", "status": "passed", "hardware_operations": False, "bundle_sha256": checked["bundle_sha256"], "profile_id": checked["profile_id"], "firmware_build_identity": checked["firmware"]["build_identity"], "firmware_build_manifest_sha256": checked["firmware_build"]["sha256"], "firmware_flash_authority": _firmware_flash_authority(), "mode": "PTY_fixture", "baud": 115200, "serial_selection": "PTY_fixture_not_auto_detect", "production_upload_orchestration_exercised": True, "deterministic_upload_and_reenumeration_injected": True, "exactly_one_upload_no_retry_enforced": True, "global_activation_consumption_replay_blocked": global_activation_consumption_replay_blocked, "pre_upload_fresh_auto_detect_exercised": True, "post_upload_fresh_auto_detect_exercised": True, "capture_own_auto_detect_command_exercised": True, "firmware_policy_identity_replayed_by_live_supervisor": True, "actual_frequency_only_exact_counter_arm_exercised": True, "rehearsal_firmware_entry_sha256": rehearsal_firmware_entry["record_sha256"], "production_capture_duration_s": int(load_contract()["envelope"]["absolute_wall_limit_s"]) + CAPTURE_EVIDENCE_DRAIN_MARGIN_S, "authority_and_wall_terminal_s": int(load_contract()["envelope"]["absolute_wall_limit_s"]), "priority_abort_delivered": True, "abort_delivery_retained_before_capture_close": True, "rotation": rotation, "actual_supervisor_exercised": True, "backlogged_configuration_startup_hold_exercised": True, "no_setup_before_d9_exact_readback_established": True, "setup_authority_false_holds_without_consuming_setup": True, "setup_issued_only_after_fresh_exact_authority_snapshot": True, "complete_response_transactions": 2, "responses_retained_observationally": True, "one_outstanding_transaction_enforced": True, "opportunity_causal_ledger_exercised": True, "accelerated_exact_counter_endpoint_reached": True, "application_admission_reserve_s": APPLICATION_ADMISSION_RESERVE_S, "long_analysis_horizon_keeps_control_admission_open": long_analysis_horizon_keeps_admission_open, "gnss_metadata_hold_deterministic_oracle_comparison": metadata_fact, "gnss_metadata_hold_effective_live_supervisor_fault_injection": True, "gnss_metadata_hold_confirmed_session_code_epoch_bound": True, "gnss_metadata_hold_fresh_causal_requalification_exercised": True, "analyzer_metric_paths_exercised": {"response_horizons_s": list(RESPONSE_HORIZONS_S), "long_horizons_right_censor_without_closing_control": True, "chatter": _chatter_metrics(transaction_rows), "response": _response_and_horizon_metrics(transaction_rows, [])}, "unresolved_delivered_output_claims": checked["unresolved_delivered_output_claims"], "not_proved": ["physical_USB_enumeration", "physical_firmware_upload", "physical_firmware_field_emission", "physical_cross_core_propagation", "physical_D9_waveform_or_load", "physical_D6_loopback", "physical_D14_D8_or_DAC_response"]}
    _write_new(output_dir / "reports/rehearsal.json", report); return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze"); freeze.add_argument("--build-manifest", type=Path, required=True); freeze.add_argument("--source-revision", required=True); freeze.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("preflight"); check.add_argument("--bundle", type=Path, required=True); check.add_argument("--output", type=Path, required=True)
    rehearse = sub.add_parser("rehearse-pty"); rehearse.add_argument("--bundle", type=Path, required=True); rehearse.add_argument("--output-dir", type=Path, required=True)
    activate = sub.add_parser("activate"); activate.add_argument("--bundle", type=Path, required=True); activate.add_argument("--preflight-report", type=Path, required=True); activate.add_argument("--rehearsal-report", type=Path, required=True); activate.add_argument("--operator-authorization-ref", required=True); activate.add_argument("--output", type=Path, required=True)
    live = sub.add_parser("run-live", help="blocking physical run; performs fresh auto-detect at each serial enumeration")
    live.add_argument("--activation", type=Path, required=True); live.add_argument("--run-dir", type=Path, required=True)
    live.add_argument("--startup-timeout-s", type=float, default=300.0); live.add_argument("--monitor-period-s", type=float, default=5.0)
    seal = sub.add_parser("seal-register"); seal.add_argument("--run-dir", type=Path, required=True); seal.add_argument("--index", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "freeze":
        result = freeze_bundle(build_manifest_path=args.build_manifest, source_revision=args.source_revision); _write_new(args.output, result)
    elif args.command == "preflight":
        result = no_io_preflight(_read(args.bundle)); _write_new(args.output, result)
    elif args.command == "rehearse-pty":
        result = pty_operational_rehearsal(bundle=_read(args.bundle), output_dir=args.output_dir)
    elif args.command == "activate":
        result = activate_bundle(bundle_path=args.bundle, preflight_report_path=args.preflight_report, rehearsal_report_path=args.rehearsal_report, operator_authorization_ref=args.operator_authorization_ref); _write_new(args.output, result)
    elif args.command == "run-live":
        result = run_live(activation_path=args.activation, run_dir=args.run_dir, startup_timeout_s=args.startup_timeout_s, monitor_period_s=args.monitor_period_s)
    else:
        result = seal_and_register(run_dir=args.run_dir, index_path=args.index)
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
