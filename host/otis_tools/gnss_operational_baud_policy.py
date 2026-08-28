"""Exact ordinary-firmware GNSS UART0 boot-to-115200 contract."""

from __future__ import annotations

from typing import Any, Mapping


GNSS_OPERATIONAL_BAUD_POLICY: dict[str, object] = {
    "policy_id": "configuration_blind_default_or_retained_115200_v1",
    "target_baud": 115200,
    "ordinary_receiver_start_states": [9600, 115200],
    "ordered_source_bauds": [9600, 115200],
    "command": "$PMTK251,115200*1F\r\n",
    "attempts_per_source_baud": 1,
    "maximum_total_attempts": 2,
    "response_gated": False,
    "autodiscovery_permitted": False,
    "fallback_scan_permitted": False,
    "rx_epoch_isolation_required": True,
    "settle_after_peripheral_drain_ms": 1200,
    "final_validation_baud": 115200,
    "post_bootstrap_baud_change_permitted": False,
    "post_bootstrap_promotion_retry_permitted": False,
}

GNSS_OPERATIONAL_REQUIRED_DEFINES = {
    "OTIS_GNSS_UART_BAUD": "115200u",
    "OTIS_GNSS_OPERATIONAL_CONFIG_BLIND_PROMOTION": "1",
    "OTIS_GNSS_OPERATIONAL_PROMOTION_SETTLE_MS": "1200u",
}

GNSS_OPERATIONAL_PREWRITE_EXACT = {
    ("gnss_receiver", "uart_configuration"): (
        "uart0_configuration_blind_default_or_retained_115200_v1"
    ),
    ("gnss_receiver", "operational_baud_policy"): (
        "configuration_blind_default_or_retained_115200_v1"
    ),
    ("gnss_receiver", "operational_bootstrap_state"): "complete",
    ("gnss_receiver", "operational_bootstrap_ordered_source_bauds"): (
        "9600,115200"
    ),
    ("gnss_receiver", "operational_bootstrap_settle_ms"): "1200",
    ("gnss_receiver", "operational_bootstrap_attempt_count"): "2",
    ("gnss_receiver", "target_baud_command_attempt_count"): "2",
    (
        "gnss_receiver",
        "post_bootstrap_target_baud_command_attempt_count",
    ): "0",
    (
        "gnss_receiver",
        "operational_bootstrap_peripheral_complete_count",
    ): "2",
    ("gnss_receiver", "operational_bootstrap_completed_rate_mask"): "3",
    ("gnss_receiver", "operational_bootstrap_first_completed_baud"): "9600",
    (
        "gnss_receiver",
        "operational_bootstrap_second_completed_baud",
    ): "115200",
    ("gnss_receiver", "local_uart_baud"): "115200",
    ("gnss_receiver", "local_uart_baud_epoch"): "2",
    ("gnss_receiver", "post_bootstrap_baud_change_count"): "0",
    ("gnss_receiver", "autodiscovery_enabled"): "false",
}

GNSS_OPERATIONAL_RUNTIME_EXACT = dict(GNSS_OPERATIONAL_PREWRITE_EXACT)


def require_exact_gnss_operational_baud_policy(
    value: Mapping[str, Any], *, owner: str
) -> None:
    if dict(value) != GNSS_OPERATIONAL_BAUD_POLICY:
        raise ValueError(f"{owner} GNSS operational baud policy differs")


def gnss_operational_runtime_invariant_errors(
    health: Mapping[tuple[str, str], str], *, require_present: bool
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return immutable bootstrap omissions and changes from live status."""

    missing: list[str] = []
    mismatches: list[str] = []
    for key, required in GNSS_OPERATIONAL_RUNTIME_EXACT.items():
        observed = health.get(key)
        name = f"{key[0]}.{key[1]}"
        if observed is None:
            if require_present:
                missing.append(name)
        elif observed != required:
            mismatches.append(f"{name}={observed!r}, expected {required!r}")
    return tuple(missing), tuple(mismatches)
