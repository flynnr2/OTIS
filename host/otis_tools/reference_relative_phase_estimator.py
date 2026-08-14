"""Offline reference-relative phase stream and candidate estimators.

CX317 is the oscillator identity.  This module is host-only and has no serial,
command, active-controller, actuator, DAC, or I2C dependency.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import json
import math
from typing import Any

from jsonschema import Draft202012Validator

from .time_domains import forward_progress, time_domain


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = (
    REPO_ROOT / "profiles/estimators/cx318_relative_phase_candidates_v1.json"
)
DEFAULT_SCHEMA = (
    REPO_ROOT / "schemas/cx318_relative_phase_candidates_v1.schema.json"
)
RAW_METHOD_ID = "CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1"


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load_profile(
    path: Path = DEFAULT_PROFILE, schema_path: Path = DEFAULT_SCHEMA
) -> tuple[dict[str, Any], str]:
    profile = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(profile)
    for binding in profile["bindings"].values():
        source = REPO_ROOT / binding["path"]
        if not source.is_file() or _sha256_file(source) != binding["sha256"]:
            raise ValueError(f"candidate source binding differs: {source}")
    if any(profile["authority"].values()):
        raise ValueError("relative-phase candidate authority must remain false")
    return profile, _sha256_file(path)


@dataclass(frozen=True)
class Snapshot:
    session: int
    snapshot_sequence: int
    cumulative_down_counter: int
    reference_sequence: int
    reference_timestamp_ticks: int
    status: int = 0
    backend: str = "pio_wait_cumulative_snapshot_dma_v1"


@dataclass(frozen=True)
class PhaseRecord:
    phase_epoch: int
    observation_sequence: int
    capture_session: int
    opening_snapshot_sequence: int
    closing_snapshot_sequence: int
    opening_reference_sequence: int
    closing_reference_sequence: int
    dac_epoch: int
    interval_edges: int | None
    edge_error_cycles: int | None
    relative_phase_cycles: int
    relative_phase_time_ns: float
    qualification_state: str
    observation_age_s: float
    discontinuity_reason: str | None
    calibrated_uncertainty_status: str
    source_backend: str
    method_id: str
    configuration_sha256: str
    accepted: bool


@dataclass(frozen=True)
class CandidateEstimate:
    candidate_id: str
    phase_epoch: int
    observation_sequence: int
    dac_epoch: int
    raw_relative_phase_cycles: int
    filtered_relative_phase_cycles: float
    estimated_frequency_error_hz: float | None
    qualification_state: str
    uncertainty_status: str
    actionable: bool = False
    actuation_authorized: bool = False
    authorization_consumed: bool = False


class RelativePhaseAccumulator:
    """Fail-closed streaming implementation of the frozen raw phase boundary."""

    def __init__(
        self,
        *,
        nominal_edges: int,
        timer_ticks_per_second: int,
        period_ns_per_cycle: float,
        configuration_sha256: str,
        reference_timestamp_domain: str,
        counter_width_bits: int = 32,
        reference_interval_minimum_s: float = 0.8,
        reference_interval_maximum_s: float = 1.2,
        expected_backend: str = "pio_wait_cumulative_snapshot_dma_v1",
    ) -> None:
        if nominal_edges <= 0 or timer_ticks_per_second <= 0:
            raise ValueError("nominal edges and timer rate must be positive")
        self.nominal_edges = nominal_edges
        self.timer_ticks_per_second = timer_ticks_per_second
        self.period_ns_per_cycle = period_ns_per_cycle
        self.configuration_sha256 = configuration_sha256
        self.reference_timestamp_domain = reference_timestamp_domain
        timestamp_semantics = time_domain(reference_timestamp_domain)
        if timer_ticks_per_second != timestamp_semantics.nominal_hz:
            raise ValueError(
                f"timer_ticks_per_second={timer_ticks_per_second} contradicts "
                f"{reference_timestamp_domain} nominal_hz="
                f"{timestamp_semantics.nominal_hz}"
            )
        self.modulus = 1 << counter_width_bits
        self.minimum_reference_ticks = round(
            reference_interval_minimum_s * timer_ticks_per_second
        )
        self.maximum_reference_ticks = round(
            reference_interval_maximum_s * timer_ticks_per_second
        )
        self.expected_backend = expected_backend
        self.phase_epoch = 0
        self._observation_sequence = 0
        self._cumulative = 0
        self._previous: Snapshot | None = None
        self._pending_reason = "initial_epoch"

    def _record(
        self,
        current: Snapshot,
        *,
        dac_epoch: int,
        interval_edges: int | None,
        edge_error: int | None,
        qualification_state: str,
        observation_age_s: float,
        reason: str | None,
        accepted: bool,
        opening: Snapshot | None = None,
    ) -> PhaseRecord:
        source = opening or self._previous or current
        return PhaseRecord(
            phase_epoch=self.phase_epoch,
            observation_sequence=self._observation_sequence,
            capture_session=current.session,
            opening_snapshot_sequence=source.snapshot_sequence,
            closing_snapshot_sequence=current.snapshot_sequence,
            opening_reference_sequence=source.reference_sequence,
            closing_reference_sequence=current.reference_sequence,
            dac_epoch=dac_epoch,
            interval_edges=interval_edges,
            edge_error_cycles=edge_error,
            relative_phase_cycles=self._cumulative,
            relative_phase_time_ns=(
                self._cumulative * self.period_ns_per_cycle
            ),
            qualification_state=qualification_state,
            observation_age_s=observation_age_s,
            discontinuity_reason=reason,
            calibrated_uncertainty_status="unavailable",
            source_backend=current.backend,
            method_id=RAW_METHOD_ID,
            configuration_sha256=self.configuration_sha256,
            accepted=accepted,
        )

    def _open_epoch(
        self,
        current: Snapshot,
        *,
        dac_epoch: int,
        observation_age_s: float,
        reason: str,
    ) -> PhaseRecord:
        self.phase_epoch += 1
        self._observation_sequence = 0
        self._cumulative = 0
        self._previous = current
        self._pending_reason = ""
        return self._record(
            current,
            dac_epoch=dac_epoch,
            interval_edges=None,
            edge_error=None,
            qualification_state="epoch_open",
            observation_age_s=observation_age_s,
            reason=reason,
            accepted=False,
            opening=current,
        )

    def _invalidate(
        self,
        current: Snapshot,
        *,
        dac_epoch: int,
        observation_age_s: float,
        reason: str,
    ) -> PhaseRecord:
        record = self._record(
            current,
            dac_epoch=dac_epoch,
            interval_edges=None,
            edge_error=None,
            qualification_state="invalid",
            observation_age_s=observation_age_s,
            reason=reason,
            accepted=False,
        )
        self._previous = None
        self._pending_reason = reason
        return record

    def process(
        self,
        current: Snapshot,
        *,
        counted_edges: int | None,
        reference_qualified: bool = True,
        dac_epoch: int = 0,
        observation_age_s: float = 0.0,
        reset: bool = False,
    ) -> PhaseRecord:
        if (
            current.session < 0
            or current.snapshot_sequence < 0
            or current.reference_sequence < 0
            or not 0 <= current.cumulative_down_counter < self.modulus
            or current.reference_timestamp_ticks < 0
            or counted_edges is not None
            and counted_edges < 0
            or observation_age_s < 0
        ):
            raise ValueError("malformed relative-phase input")
        if current.backend != self.expected_backend:
            return self._invalidate(
                current,
                dac_epoch=dac_epoch,
                observation_age_s=observation_age_s,
                reason="snapshot_backend_mismatch",
            )
        if current.status != 0:
            return self._invalidate(
                current,
                dac_epoch=dac_epoch,
                observation_age_s=observation_age_s,
                reason="snapshot_status_invalid",
            )
        if not reference_qualified:
            return self._invalidate(
                current,
                dac_epoch=dac_epoch,
                observation_age_s=observation_age_s,
                reason="reference_invalid_or_stale",
            )
        if reset:
            self._previous = None
            self._pending_reason = "reset"
        if self._previous is None:
            return self._open_epoch(
                current,
                dac_epoch=dac_epoch,
                observation_age_s=observation_age_s,
                reason=self._pending_reason or "continuity_requalified",
            )

        previous = self._previous
        if current.session != previous.session:
            return self._open_epoch(
                current,
                dac_epoch=dac_epoch,
                observation_age_s=observation_age_s,
                reason="capture_session_change",
            )
        if current.snapshot_sequence <= previous.snapshot_sequence:
            return self._invalidate(
                current,
                dac_epoch=dac_epoch,
                observation_age_s=observation_age_s,
                reason="snapshot_reordered_or_duplicate",
            )
        if current.reference_sequence <= previous.reference_sequence:
            return self._invalidate(
                current,
                dac_epoch=dac_epoch,
                observation_age_s=observation_age_s,
                reason="reference_reordered_or_duplicate",
            )
        if (
            current.snapshot_sequence != previous.snapshot_sequence + 1
            or current.reference_sequence != previous.reference_sequence + 1
        ):
            return self._open_epoch(
                current,
                dac_epoch=dac_epoch,
                observation_age_s=observation_age_s,
                reason="snapshot_or_reference_sequence_gap",
            )
        progress = forward_progress(
            previous.reference_timestamp_ticks,
            current.reference_timestamp_ticks,
            domain=self.reference_timestamp_domain,
            allow_equal=False,
        )
        if not progress.valid or progress.distance_ticks is None:
            return self._invalidate(
                current,
                dac_epoch=dac_epoch,
                observation_age_s=observation_age_s,
                reason="reference_timestamp_reordered",
            )
        reference_ticks = progress.distance_ticks
        if reference_ticks > self.maximum_reference_ticks:
            return self._open_epoch(
                current,
                dac_epoch=dac_epoch,
                observation_age_s=observation_age_s,
                reason="reference_pps_long_interval",
            )
        if reference_ticks < self.minimum_reference_ticks:
            return self._open_epoch(
                current,
                dac_epoch=dac_epoch,
                observation_age_s=observation_age_s,
                reason="reference_pps_short_interval",
            )

        interval_edges = (
            previous.cumulative_down_counter
            - current.cumulative_down_counter
        ) % self.modulus
        if counted_edges is None or counted_edges != interval_edges:
            return self._open_epoch(
                current,
                dac_epoch=dac_epoch,
                observation_age_s=observation_age_s,
                reason="snapshot_count_association_mismatch",
            )
        opening = previous
        edge_error = interval_edges - self.nominal_edges
        self._cumulative += edge_error
        self._observation_sequence += 1
        self._previous = current
        return self._record(
            current,
            dac_epoch=dac_epoch,
            interval_edges=interval_edges,
            edge_error=edge_error,
            qualification_state="qualified",
            observation_age_s=observation_age_s,
            reason=None,
            accepted=True,
            opening=opening,
        )


class _PointWindow:
    def __init__(self, window_intervals: int) -> None:
        self.window_intervals = window_intervals
        self.points: deque[tuple[int, int]] = deque()
        self.phase_epoch: int | None = None
        self.dac_epoch: int | None = None
        self.sum_x = 0.0
        self.sum_y = 0.0
        self.sum_xx = 0.0
        self.sum_xy = 0.0

    def clear(self) -> None:
        self.points.clear()
        self.sum_x = 0.0
        self.sum_y = 0.0
        self.sum_xx = 0.0
        self.sum_xy = 0.0

    def update(self, record: PhaseRecord) -> bool:
        if record.qualification_state == "invalid":
            self.clear()
            self.phase_epoch = None
            self.dac_epoch = None
            return False
        if self.phase_epoch != record.phase_epoch or self.dac_epoch != record.dac_epoch:
            self.clear()
            self.phase_epoch = record.phase_epoch
            self.dac_epoch = record.dac_epoch
        if len(self.points) == self.window_intervals + 1:
            old_x, old_y = self.points.popleft()
            self.sum_x -= old_x
            self.sum_y -= old_y
            self.sum_xx -= old_x * old_x
            self.sum_xy -= old_x * old_y
        point = (record.observation_sequence, record.relative_phase_cycles)
        self.points.append(point)
        x, y = point
        self.sum_x += x
        self.sum_y += y
        self.sum_xx += x * x
        self.sum_xy += x * y
        return len(self.points) == self.window_intervals + 1

    def endpoint_frequency(self) -> float | None:
        if len(self.points) != self.window_intervals + 1:
            return None
        first, last = self.points[0], self.points[-1]
        return (last[1] - first[1]) / (last[0] - first[0])

    def regression(self) -> tuple[float, float] | None:
        count = len(self.points)
        if count != self.window_intervals + 1:
            return None
        denominator = self.sum_xx - self.sum_x * self.sum_x / count
        if denominator == 0:
            return None
        slope = (
            self.sum_xy - self.sum_x * self.sum_y / count
        ) / denominator
        x_mean = self.sum_x / count
        y_mean = self.sum_y / count
        intercept = y_mean - slope * x_mean
        return intercept + slope * self.points[-1][0], slope


class CandidateSuite:
    """Deterministic derived estimators; the raw PhaseRecord is never changed."""

    def __init__(self, profile: dict[str, Any]) -> None:
        self.raw_window = _PointWindow(
            int(profile["raw_boundary"]["authoritative_frequency_support_intervals"])
        )
        self.regressions = {
            int(window): _PointWindow(int(window))
            for window in profile["rolling_regression"]["window_intervals"]
        }
        self.alpha_beta_parameters = {
            item["candidate_id"]: (float(item["alpha"]), float(item["beta"]))
            for item in profile["alpha_beta"]["parameter_grid"]
        }
        self.alpha_beta_state: dict[str, tuple[int, int, float, float]] = {}

    @staticmethod
    def _estimate(
        candidate_id: str,
        record: PhaseRecord,
        *,
        filtered_phase: float,
        frequency: float | None,
        qualification: str,
    ) -> CandidateEstimate:
        return CandidateEstimate(
            candidate_id=candidate_id,
            phase_epoch=record.phase_epoch,
            observation_sequence=record.observation_sequence,
            dac_epoch=record.dac_epoch,
            raw_relative_phase_cycles=record.relative_phase_cycles,
            filtered_relative_phase_cycles=filtered_phase,
            estimated_frequency_error_hz=frequency,
            qualification_state=qualification,
            uncertainty_status="unavailable",
        )

    def process(self, record: PhaseRecord) -> list[CandidateEstimate]:
        if record.qualification_state == "invalid":
            self.raw_window.update(record)
            for window in self.regressions.values():
                window.update(record)
            self.alpha_beta_state.clear()
            return []

        results: list[CandidateEstimate] = []
        self.raw_window.update(record)
        raw_frequency = self.raw_window.endpoint_frequency()
        results.append(
            self._estimate(
                RAW_METHOD_ID,
                record,
                filtered_phase=float(record.relative_phase_cycles),
                frequency=raw_frequency,
                qualification=(
                    "qualified" if raw_frequency is not None else "initializing"
                ),
            )
        )

        for size, window in self.regressions.items():
            window.update(record)
            regression = window.regression()
            filtered_phase = (
                regression[0]
                if regression is not None
                else float(record.relative_phase_cycles)
            )
            frequency = regression[1] if regression is not None else None
            results.append(
                self._estimate(
                    f"CX318_RELATIVE_PHASE_ROLLING_OLS_V1_{size}S",
                    record,
                    filtered_phase=filtered_phase,
                    frequency=frequency,
                    qualification=(
                        "qualified" if frequency is not None else "initializing"
                    ),
                )
            )

        for candidate_id, (alpha, beta) in self.alpha_beta_parameters.items():
            state = self.alpha_beta_state.get(candidate_id)
            if (
                state is None
                or state[0] != record.phase_epoch
                or state[1] != record.dac_epoch
                or record.observation_sequence == 0
            ):
                phase = float(record.relative_phase_cycles)
                frequency = 0.0
                qualification = "initializing"
            else:
                phase_epoch, dac_epoch, phase, frequency = state
                predicted = phase + frequency
                residual = record.relative_phase_cycles - predicted
                phase = predicted + alpha * residual
                frequency = frequency + beta * residual
                qualification = "qualified"
                assert phase_epoch == record.phase_epoch
                assert dac_epoch == record.dac_epoch
            self.alpha_beta_state[candidate_id] = (
                record.phase_epoch,
                record.dac_epoch,
                phase,
                frequency,
            )
            results.append(
                self._estimate(
                    f"CX318_RELATIVE_PHASE_ALPHA_BETA_V1_{candidate_id}",
                    record,
                    filtered_phase=phase,
                    frequency=frequency,
                    qualification=qualification,
                )
            )
        return results


def deterministic_digest(
    records: list[PhaseRecord], estimates: list[CandidateEstimate]
) -> str:
    payload = {
        "records": [asdict(record) for record in records],
        "estimates": [asdict(estimate) for estimate in estimates],
    }
    return sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def corrective_frequency_direction(relative_phase_cycles: float) -> int:
    """Return only the sign required by later preview; this has no authority."""

    if not math.isfinite(relative_phase_cycles):
        raise ValueError("relative phase must be finite")
    if relative_phase_cycles > 0:
        return -1
    if relative_phase_cycles < 0:
        return 1
    return 0
