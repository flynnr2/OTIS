"""Shared fail-closed runtime contract for pre-write readiness gates.

The inherited A828 preview baseline and a leg's planned A808/A848 stimulus are
different facts.  This module keeps their provenance explicit and provides the
single readiness predicate used by the supervisor, rehearsal seal, promotion,
and offline preflight.  It performs no I/O and has no actuation authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

from .active_status_contract import ACTIVE_STATUS_KEYS


RUNTIME_CONTRACT_ID = "cx318_stage5_prewrite_runtime_contract_v1"
INHERITED_PREVIEW_BASELINE_CODE = 0xA828
INHERITED_PREVIEW_BASELINE_PROVENANCE = (
    "stage4_sealed_build_bound_preview_not_physical_dac_confirmation"
)

Health = Mapping[tuple[str, str], str]

HEALTH_INTEGRITY_EXACT = {
    ("capture", "dropped_count"): "0",
    ("capture", "pps_count_boundary_dropped_count"): "0",
    ("dual_core", "telemetry_dropped"): "0",
    ("dual_core", "service_publish_failures"): "0",
    ("dual_core", "partition_fault"): "none",
    ("dual_core", "fail_static"): "false",
    ("cx317_active", "fail_static"): "false",
    ("cx317_preview", "telemetry_dropped_frames"): "0",
    ("cx317_preview", "actionable"): "false",
    ("cx317_preview", "actuation_authorized"): "false",
    ("cx318_preview", "actionable"): "false",
    ("cx318_preview", "actuation_authorized"): "false",
    ("cx318_preview", "authorization_consumed"): "false",
}


@dataclass(frozen=True)
class PrewriteReadiness:
    contract_id: str
    ready: bool
    missing: tuple[str, ...]
    mismatches: tuple[str, ...]
    inherited_preview_baseline_code: str
    inherited_preview_baseline_provenance: str
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


def evaluate_health_integrity(health: Health) -> PrewriteHealthIntegrity:
    missing: list[str] = []
    mismatches: list[str] = []
    for status_key in ACTIVE_STATUS_KEYS:
        key = ("cx317_active", status_key)
        if key not in health:
            missing.append(f"missing {_key_name(key)}")
    _expect(health, HEALTH_INTEGRITY_EXACT, missing, mismatches)
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
    contract_id: str = RUNTIME_CONTRACT_ID,
    inherited_preview_baseline_provenance: str = (
        INHERITED_PREVIEW_BASELINE_PROVENANCE
    ),
) -> PrewriteReadiness:
    """Evaluate the exact no-write state preceding a Stage 5 live stimulus.

    Missing status is never treated as healthy.  The caller decides how much
    bounded startup grace to allow while the first complete status burst is
    arriving; once evaluated as ready, any later regression is a failure.
    """

    missing: list[str] = []
    mismatches: list[str] = []

    integrity = evaluate_health_integrity(health)
    missing.extend(integrity.missing)
    mismatches.extend(integrity.mismatches)

    exact = {
        **{
            ("cx317_active", key): value
            for key, value in expected_identity.items()
        },
        ("cx317_active", "enabled"): "true",
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "evidence_pending"): "false",
        ("cx317_active", "evidence_phase"): "evidence_clear",
        ("cx317_active", "capture_lease_live"): "true",
        ("cx317_active", "manual_start_confirmed"): "false",
        ("cx317_active", "arm_eligible"): "false",
        ("cx317_active", "fail_static"): "false",
        ("cx317_active", "evidence_request_sequence"): "0",
        ("cx317_active", "expected_setup_code"): (
            f"0x{planned_live_stimulus_code:04X}"
        ),
        ("cx317_active", "confirmed_applied_code_known"): "false",
        ("cx317_active", "confirmed_applied_code"): "unavailable",
        ("cx317_active", "correction_count"): "0",
        ("cx317_active", "cumulative_movement_codes"): "0",
        ("cx317_active", "dac_epoch"): "0",
        ("cx317_active", "automatic_retry"): "false",
        ("cx317_active", "automatic_restore"): "false",
        ("cx318_preview", "static_code"): "0xA828",
        ("cx318_preview", "applied_code"): "0xA828",
        ("cx318_preview", "dac_epoch"): "0",
        ("dac", "applied_code_known"): "false",
        ("dac", "last_write_ok"): "false",
        ("dac", "last_applied_code"): "unavailable",
    }
    _expect(health, exact, missing, mismatches)
    for key, nonzero in (
        (("cx317_active", "session_id"), True),
        (("cx317_active", "uptime_s"), False),
        (("cx317_active", "selected_interval_count"), False),
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
        inherited_preview_baseline_code="0xA828",
        inherited_preview_baseline_provenance=(
            inherited_preview_baseline_provenance
        ),
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
        }
    )
    health = {("cx317_active", key): value for key, value in active.items()}
    health.update(
        {
            ("cx318_preview", "static_code"): "0xA828",
            ("cx318_preview", "applied_code"): "0xA828",
            ("cx318_preview", "dac_epoch"): "0",
            ("cx317_preview", "actionable"): "false",
            ("cx317_preview", "actuation_authorized"): "false",
            ("cx318_preview", "actionable"): "false",
            ("cx318_preview", "actuation_authorized"): "false",
            ("cx318_preview", "authorization_consumed"): "false",
            ("dac", "applied_code_known"): "false",
            ("dac", "last_write_ok"): "false",
            ("dac", "last_applied_code"): "unavailable",
            **HEALTH_INTEGRITY_EXACT,
        }
    )
    return health
