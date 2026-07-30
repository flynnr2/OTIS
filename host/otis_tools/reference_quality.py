from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from typing import Mapping


REFERENCE_QUALITY_ALGORITHM_VERSION = "reference_quality_v1"
DEFAULT_REFERENCE_INVALID_FLAGS = (
    (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 5) | (1 << 12)
)


@dataclass(frozen=True)
class ReferenceQualityConfig:
    nominal_interval_s: float = 1.0
    interval_tolerance_s: float = 0.2
    reference_max_age_s: float = 1.5
    metadata_max_age_s: float = 3600.0
    invalid_flag_mask: int = DEFAULT_REFERENCE_INVALID_FLAGS

    def __post_init__(self) -> None:
        if self.nominal_interval_s <= 0:
            raise ValueError("nominal_interval_s must be positive")
        if self.interval_tolerance_s < 0:
            raise ValueError("interval_tolerance_s must be non-negative")
        if self.interval_tolerance_s >= self.nominal_interval_s:
            raise ValueError(
                "interval_tolerance_s must leave a positive minimum interval"
            )
        if self.reference_max_age_s <= 0 or self.metadata_max_age_s <= 0:
            raise ValueError("reference and metadata maximum ages must be positive")
        if self.invalid_flag_mask < 0:
            raise ValueError("invalid_flag_mask must be non-negative")

    @property
    def config_hash(self) -> str:
        payload = json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("ascii")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ReferenceEvidence:
    seq: int
    ticks: int
    domain: str
    flags: int
    evidence_ref: str


@dataclass(frozen=True)
class ReceiverMetadata:
    ticks: int
    evidence_ref: str
    identity_epoch: str = "unknown"
    receiver_identity: str = "unknown"
    receiver_firmware: str = "unknown"
    authority_state: str = "unknown"
    utc_traceability_state: str = "unknown"
    timing_mode: str = "unknown"
    fix_holdover_state: str = "unknown"
    antenna_state: str = "unknown"
    leap_state: str = "unknown"
    sawtooth_correction_ns: float | None = None
    cable_delay_ns: float | None = None
    pulse_configuration: str = "unknown"
    calibration_ref: str = "unknown"
    reference_standard_uncertainty_s: float | None = None


@dataclass(frozen=True)
class ReferenceQuality:
    cadence_state: str
    capture_path_state: str
    receiver_authority_state: str
    utc_traceability_state: str
    metadata_freshness: str
    qualification_state: str
    reason_codes: tuple[str, ...]


class ReferenceIdentityTracker:
    """Assign deterministic epochs when receiver identity changes.

    A producer-supplied epoch remains authoritative. When it is absent, a
    replay-local epoch is derived only from explicit receiver identity and
    firmware evidence; missing identity never fabricates an epoch.
    """

    def __init__(self) -> None:
        self._fingerprint: tuple[str, str] | None = None
        self._epoch = 0

    def observe(self, metadata: ReceiverMetadata | None) -> ReceiverMetadata | None:
        if metadata is None or metadata.identity_epoch not in {
            "",
            "unknown",
            "unavailable",
        }:
            return metadata
        fingerprint = (metadata.receiver_identity, metadata.receiver_firmware)
        if all(value in {"", "unknown", "unavailable"} for value in fingerprint):
            return metadata
        if fingerprint != self._fingerprint:
            self._fingerprint = fingerprint
            self._epoch += 1
        return replace(
            metadata,
            identity_epoch=f"reference_source_epoch:{self._epoch}",
        )


def _metadata_from_status(
    snapshot: Mapping[tuple[str, str], object],
    *,
    now_ticks: int,
) -> ReceiverMetadata | None:
    def value(key: str, default: str = "unknown") -> str:
        record = snapshot.get(("reference_receiver", key))
        return str(getattr(record, "value", default)) if record is not None else default

    records = [
        record
        for (component, _), record in snapshot.items()
        if component == "reference_receiver"
    ]
    if not records:
        return None
    newest = max(records, key=lambda item: int(getattr(item, "ticks", 0)))
    first_seq = min(int(getattr(item, "seq", 0)) for item in records)
    last_seq = max(int(getattr(item, "seq", 0)) for item in records)

    def optional_float(key: str) -> float | None:
        text = value(key, "")
        if not text or text in {"unknown", "unavailable"}:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    return ReceiverMetadata(
        ticks=int(getattr(newest, "ticks", now_ticks)),
        evidence_ref=(
            "health_v1:STS:reference_receiver:"
            f"{first_seq}-{last_seq}"
        ),
        identity_epoch=value("identity_epoch"),
        receiver_identity=value("identity"),
        receiver_firmware=value("firmware"),
        authority_state=value("authority_state"),
        utc_traceability_state=value("utc_traceability_state"),
        timing_mode=value("timing_mode"),
        fix_holdover_state=value("fix_holdover_state"),
        antenna_state=value("antenna_state"),
        leap_state=value("leap_state"),
        sawtooth_correction_ns=optional_float("sawtooth_correction_ns"),
        cable_delay_ns=optional_float("cable_delay_ns"),
        pulse_configuration=value("pulse_configuration"),
        calibration_ref=value("calibration_ref"),
        reference_standard_uncertainty_s=optional_float(
            "reference_standard_uncertainty_s"
        ),
    )


def assess_reference_quality(
    previous: ReferenceEvidence | None,
    current: ReferenceEvidence | None,
    *,
    now_ticks: int,
    domain_hz: float,
    metadata: ReceiverMetadata | None,
    config: ReferenceQualityConfig,
) -> ReferenceQuality:
    reasons: list[str] = []
    cadence = "unavailable"
    capture = "unavailable"
    if current is None:
        reasons.append("reference_unavailable")
    else:
        age_s = (now_ticks - current.ticks) / domain_hz
        if age_s > config.reference_max_age_s:
            cadence = "missing"
            reasons.append("reference_missing")
        elif previous is None:
            reasons.append("reference_continuity_unavailable")
        elif current.seq <= previous.seq:
            cadence = "invalid"
            capture = "sequence_gap"
            reasons.append("reference_sequence_nonmonotonic")
        elif current.flags & config.invalid_flag_mask:
            cadence = "invalid"
            capture = "invalid"
            reasons.append("reference_flagged_invalid")
        else:
            interval_s = (current.ticks - previous.ticks) / domain_hz
            minimum = config.nominal_interval_s - config.interval_tolerance_s
            maximum = config.nominal_interval_s + config.interval_tolerance_s
            capture = "valid"
            if interval_s <= 0:
                cadence = "duplicate"
                reasons.append("reference_pps_duplicate")
            elif interval_s < minimum:
                cadence = "short"
                reasons.append("reference_pps_short_interval")
            elif interval_s > maximum:
                cadence = "long"
                reasons.append("reference_pps_long_interval")
            else:
                cadence = "valid"
                reasons.append("reference_cadence_valid")

    if metadata is None:
        freshness = "missing"
        authority = "unknown"
        utc = "unknown"
        reasons.append("reference_metadata_missing")
    else:
        metadata_age_s = (now_ticks - metadata.ticks) / domain_hz
        freshness = (
            "current"
            if 0 <= metadata_age_s <= config.metadata_max_age_s
            else "stale"
        )
        authority = metadata.authority_state
        utc = metadata.utc_traceability_state
        if freshness == "stale":
            reasons.append("reference_metadata_stale")
        if authority not in {
            "qualified",
            "holdover",
            "fix_unavailable",
            "antenna_fault",
            "invalid",
            "unknown",
            "unavailable",
        }:
            authority = "unknown"
            reasons.append("reference_authority_value_unsupported")
        if utc not in {"valid", "invalid", "unknown", "unavailable"}:
            utc = "unknown"
            reasons.append("reference_utc_value_unsupported")

    if capture in {"sequence_gap", "overflow", "resource_failure", "invalid"}:
        qualification = "capture_path_invalid"
    elif cadence != "valid":
        qualification = "unqualified" if cadence != "unavailable" else "unknown"
    elif freshness != "current":
        qualification = "metadata_stale" if freshness == "stale" else "cadence_valid_authority_unknown"
    elif (
        authority == "antenna_fault"
        or (
            metadata is not None
            and metadata.antenna_state
            in {"fault", "open", "short", "antenna_fault"}
        )
    ):
        qualification = "antenna_fault"
        reasons.append("reference_antenna_fault")
    elif (
        authority == "holdover"
        or (
            metadata is not None
            and metadata.fix_holdover_state == "holdover"
        )
    ):
        qualification = "holdover"
        reasons.append("reference_receiver_holdover")
    elif utc == "invalid":
        qualification = "utc_invalid"
    elif authority == "qualified" and utc == "valid":
        qualification = "qualified"
        reasons.append("reference_receiver_qualified")
    else:
        qualification = "cadence_valid_authority_unknown"
        reasons.append("reference_authority_unknown")

    return ReferenceQuality(
        cadence_state=cadence,
        capture_path_state=capture,
        receiver_authority_state=authority,
        utc_traceability_state=utc,
        metadata_freshness=freshness,
        qualification_state=qualification,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def metadata_from_status(
    snapshot: Mapping[tuple[str, str], object], *, now_ticks: int
) -> ReceiverMetadata | None:
    return _metadata_from_status(snapshot, now_ticks=now_ticks)
