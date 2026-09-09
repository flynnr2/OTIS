"""Shared fail-closed runtime contract for the fixed programme's setup gate.

The pre-setup preview is zero-authority observation context. Only the planned
setup transaction can establish a physically confirmed DAC code. This module
performs no I/O and has no actuation authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

from .active_status_contract import ACTIVE_STATUS_KEYS


RUNTIME_CONTRACT_ID = "adaptive_hybrid_prewrite_runtime_contract_v1"
RAW_PPS_QUALIFICATION_DEADLINE_S = 660

Health = Mapping[tuple[str, str], str]

HEALTH_INTEGRITY_EXACT = {
    ("capture", "dropped_count"): "0",
    ("capture", "pps_count_boundary_dropped_count"): "0",
    ("dual_core", "telemetry_dropped"): "0",
    ("dual_core", "service_publish_failures"): "0",
    ("dual_core", "partition_fault"): "none",
    ("dual_core", "fail_static"): "false",
    ("adaptive_hybrid", "fail_static"): "false",
}

TELEMETRY_DROP_KEY = ("dual_core", "telemetry_dropped")
GNSS_OPERATIONAL_PREWRITE_EXACT = {
    ("gnss_receiver", "uart_configuration"): "uart0_configuration_blind_default_or_retained_115200_v1",
    ("gnss_receiver", "operational_baud_policy"): "configuration_blind_default_or_retained_115200_v1",
    ("gnss_receiver", "operational_bootstrap_state"): "complete",
    ("gnss_receiver", "operational_bootstrap_ordered_source_bauds"): "9600%2C115200",
    ("gnss_receiver", "operational_bootstrap_settle_ms"): "1200",
    ("gnss_receiver", "operational_bootstrap_attempt_count"): "2",
    ("gnss_receiver", "target_baud_command_attempt_count"): "2",
    ("gnss_receiver", "post_bootstrap_target_baud_command_attempt_count"): "0",
    ("gnss_receiver", "operational_bootstrap_peripheral_complete_count"): "2",
    ("gnss_receiver", "operational_bootstrap_completed_rate_mask"): "3",
    ("gnss_receiver", "operational_bootstrap_first_completed_baud"): "9600",
    ("gnss_receiver", "operational_bootstrap_second_completed_baud"): "115200",
    ("gnss_receiver", "local_uart_baud"): "115200",
    ("gnss_receiver", "local_uart_baud_epoch"): "2",
    ("gnss_receiver", "post_bootstrap_baud_change_count"): "0",
    ("gnss_receiver", "autodiscovery_enabled"): "false",
}
GNSS_PREWRITE_EXACT = {
    ("gnss_receiver", "initialized"): "true",
    ("gnss_receiver", "link_state"): "online",
    ("gnss_receiver", "link_online"): "true",
    ("gnss_receiver", "configuration_confirmed"): "true",
    ("gnss_receiver", "confirmed_baud"): "115200",
    ("gnss_receiver", "rx_only"): "true",
    ("gnss_receiver", "metadata_fresh"): "true",
    ("gnss_receiver", "checksum_requalified"): "true",
    ("gnss_receiver", "gsa_3d_fresh"): "true",
    ("gnss_receiver", "gsa_checksum_requalified"): "true",
    ("gnss_receiver", "identity_epoch"): "1",
    ("gnss_receiver", "identity_stable"): "true",
    ("gnss_receiver", "metadata_control_eligible"): "true",
    ("gnss_receiver", "raw_pps_control_eligible"): "true",
    ("gnss_receiver", "control_eligible"): "true",
    **GNSS_OPERATIONAL_PREWRITE_EXACT,
}

# These are the firmware's exact, current inputs to the one-shot SETUP
# authority decision.  Broad receiver/capture health is not an acceptable
# proxy: the device can legitimately keep either input false while D14 or GNSS
# metadata is still qualifying after boot.  That state is a bounded pre-setup
# hold and must never be allowed to consume the sole setup request.
SETUP_AUTHORITY_EXACT = {
    ("adaptive_hybrid", "setup_gnss_eligible"): "true",
    ("adaptive_hybrid", "setup_reference_eligible"): "true",
    ("adaptive_hybrid", "setup_partition_healthy"): "true",
}


@dataclass(frozen=True)
class PrewriteReadiness:
    contract_id: str
    ready: bool
    missing: tuple[str, ...]
    mismatches: tuple[str, ...]
    planned_live_stimulus_code: str
    physical_dac_confirmation: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    def diagnostic(self) -> str:
        details = [*self.missing, *self.mismatches]
        return "; ".join(details) if details else "ready"


@dataclass(frozen=True)
class PrewriteHealthIntegrity:
    clean: bool
    missing: tuple[str, ...]
    mismatches: tuple[str, ...]

    def diagnostic(self) -> str:
        details = [*self.missing, *self.mismatches]
        return "; ".join(details) if details else "clean"


def _key_name(key: tuple[str, str]) -> str:
    return f"{key[0]}.{key[1]}"


def _expect(
    health: Health,
    expected: Mapping[tuple[str, str], str],
    missing: list[str],
    mismatches: list[str],
) -> None:
    for key, required in expected.items():
        observed = health.get(key)
        name = _key_name(key)
        if observed is None:
            missing.append(f"missing {name}")
        elif observed != required:
            mismatches.append(
                f"{name}={observed!r}, expected {required!r}"
            )


def _require_unsigned(
    health: Health,
    key: tuple[str, str],
    missing: list[str],
    mismatches: list[str],
    *,
    nonzero: bool = False,
) -> None:
    observed = health.get(key)
    name = _key_name(key)
    if observed is None:
        missing.append(f"missing {name}")
        return
    try:
        value = int(observed)
    except ValueError:
        mismatches.append(f"{name}={observed!r}, expected unsigned integer")
        return
    if value < 0 or (nonzero and value == 0):
        qualifier = "positive" if nonzero else "unsigned"
        mismatches.append(f"{name}={observed!r}, expected {qualifier} integer")


def evaluate_health_integrity(
    health: Health, *, telemetry_drop_baseline: int = 0
) -> PrewriteHealthIntegrity:
    missing: list[str] = []
    mismatches: list[str] = []
    for status_key in ACTIVE_STATUS_KEYS:
        key = ("adaptive_hybrid", status_key)
        if key not in health:
            missing.append(f"missing {_key_name(key)}")
    normalized = dict(health)
    observed_drop = health.get(TELEMETRY_DROP_KEY)
    if observed_drop is not None:
        try:
            if int(observed_drop) != telemetry_drop_baseline:
                mismatches.append(
                    "dual_core.telemetry_dropped differs from frozen attach baseline"
                )
        except ValueError:
            mismatches.append("dual_core.telemetry_dropped is not an integer")
        normalized[TELEMETRY_DROP_KEY] = "0"
    _expect(normalized, HEALTH_INTEGRITY_EXACT, missing, mismatches)
    return PrewriteHealthIntegrity(
        clean=not missing and not mismatches,
        missing=tuple(missing),
        mismatches=tuple(mismatches),
    )


def evaluate_prewrite_readiness(
    health: Health,
    *,
    expected_identity: Mapping[str, str],
    planned_live_stimulus_code: int,
    active_row_count: int,
    dac_row_count: int,
    telemetry_drop_baseline: int = 0,
    contract_id: str = RUNTIME_CONTRACT_ID,
) -> PrewriteReadiness:
    """Evaluate the exact no-write state preceding live adaptive-hybrid setup.

    Missing status is never treated as healthy.  The caller decides how much
    bounded startup grace to allow while the first complete status burst is
    arriving; once evaluated as ready, any later regression is a failure.
    """

    missing: list[str] = []
    mismatches: list[str] = []

    integrity = evaluate_health_integrity(
        health, telemetry_drop_baseline=telemetry_drop_baseline
    )
    missing.extend(integrity.missing)
    mismatches.extend(integrity.mismatches)

    exact = {
        **{
            ("adaptive_hybrid", key): value
            for key, value in expected_identity.items()
        },
        ("adaptive_hybrid", "enabled"): "true",
        ("adaptive_hybrid", "state"): "DISARMED",
        ("adaptive_hybrid", "evidence_pending"): "false",
        ("adaptive_hybrid", "evidence_phase"): "evidence_clear",
        ("adaptive_hybrid", "capture_lease_live"): "true",
        ("adaptive_hybrid", "manual_start_confirmed"): "false",
        ("adaptive_hybrid", "arm_eligible"): "false",
        ("adaptive_hybrid", "fail_static"): "false",
        ("adaptive_hybrid", "evidence_request_sequence"): "0",
        ("adaptive_hybrid", "expected_setup_code"): (
            f"0x{planned_live_stimulus_code:04X}"
        ),
        ("adaptive_hybrid", "confirmed_applied_code_known"): "false",
        ("adaptive_hybrid", "confirmed_applied_code"): "unavailable",
        ("adaptive_hybrid", "correction_count"): "0",
        ("adaptive_hybrid", "cumulative_movement_codes"): "0",
        ("adaptive_hybrid", "dac_epoch"): "0",
        ("adaptive_hybrid", "automatic_retry"): "false",
        ("adaptive_hybrid", "automatic_restore"): "false",
        ("dac", "applied_code_known"): "false",
        ("dac", "last_write_ok"): "false",
        ("dac", "last_applied_code"): "unavailable",
    }
    _expect(health, exact, missing, mismatches)
    _expect(health, GNSS_PREWRITE_EXACT, missing, mismatches)
    for key, required in SETUP_AUTHORITY_EXACT.items():
        observed = health.get(key)
        name = _key_name(key)
        if observed is None:
            missing.append(f"missing {name}")
        elif observed != required:
            mismatches.append(
                f"{name}={observed!r}, expected {required!r} before setup"
            )
    for key, nonzero in (
        (("adaptive_hybrid", "session_id"), True),
        (("adaptive_hybrid", "uptime_s"), False),
        (("adaptive_hybrid", "selected_interval_count"), False),
    ):
        _require_unsigned(
            health, key, missing, mismatches, nonzero=nonzero
        )

    if active_row_count != 0:
        mismatches.append(
            f"active transaction row count={active_row_count}, expected 0"
        )
    if dac_row_count != 0:
        mismatches.append(f"DAC transaction row count={dac_row_count}, expected 0")

    # The canonical-key pass above and exact-value pass overlap deliberately.
    # Deduplicate so diagnostics remain compact and deterministic.
    missing_exact = tuple(dict.fromkeys(missing))
    mismatches_exact = tuple(dict.fromkeys(mismatches))
    return PrewriteReadiness(
        contract_id=contract_id,
        ready=not missing_exact and not mismatches_exact,
        missing=missing_exact,
        mismatches=mismatches_exact,
        planned_live_stimulus_code=f"0x{planned_live_stimulus_code:04X}",
        physical_dac_confirmation="unknown_before_live_stimulus",
    )


def environment_streams_ready(sources: Sequence[str] | set[str]) -> bool:
    return {value.lower() for value in sources} >= {"sht4x", "bmp280"}


def canonical_prewrite_fixture(
    *,
    expected_identity: Mapping[str, str],
    planned_live_stimulus_code: int,
) -> dict[tuple[str, str], str]:
    """Return the canonical no-I/O fixture used by the exact preflight."""

    active = {key: "present" for key in ACTIVE_STATUS_KEYS}
    active.update(
        {
            **expected_identity,
            "enabled": "true",
            "state": "DISARMED",
            "reason": "initialized_disarmed",
            "evidence_pending": "false",
            "evidence_phase": "evidence_clear",
            "capture_lease_live": "true",
            "manual_start_confirmed": "false",
            "arm_eligible": "false",
            "fail_static": "false",
            "session_id": "1",
            "uptime_s": "30",
            "evidence_request_sequence": "0",
            "expected_setup_code": f"0x{planned_live_stimulus_code:04X}",
            "confirmed_applied_code_known": "false",
            "confirmed_applied_code": "unavailable",
            "correction_count": "0",
            "cumulative_movement_codes": "0",
            "dac_epoch": "0",
            "selected_interval_count": "0",
            "automatic_retry": "false",
            "automatic_restore": "false",
            "setup_gnss_eligible": "true",
            "setup_reference_eligible": "true",
            "setup_partition_healthy": "true",
        }
    )
    health = {("adaptive_hybrid", key): value for key, value in active.items()}
    health.update(
        {
            ("dac", "applied_code_known"): "false",
            ("dac", "last_write_ok"): "false",
            ("dac", "last_applied_code"): "unavailable",
            **HEALTH_INTEGRITY_EXACT,
        }
    )
    health.update(GNSS_PREWRITE_EXACT)
    return health
