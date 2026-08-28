"""Fail-static active-transaction parsing and host supervision.

The capture process remains the sole serial owner.  This supervisor has two
independent host inputs: the capture command FIFO and an ABORT-only FIFO.  It
fsyncs each ACT capsule before sending the exact phase acknowledgement.  Phase
1 is therefore the only host action capable of releasing one accepted request
to the firmware actuator owner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import csv
import json
import os
import secrets
import tempfile
import time

from .contracts import CsvValidationContext, validate_csv
from .abort_transport import AbortFifo
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, SUSTAINED_HYBRID_PROFILE_ID
from .serial_commands import send_command_to_fifo


ACTIVE_CSV = Path("csv/active_transactions_v1.csv")
HEALTH_CSV = Path("csv/health.csv")
SUPERVISOR_STATE = Path("reports/cx317_active_supervisor_state.json")
SUPERVISOR_EVENTS = Path("reports/cx317_active_supervisor_events.jsonl")
ARM_PROGRESS_THRESHOLD = 520
LEASE_PERIOD_S = 5.0
QUERY_PERIOD_S = 10.0
PLANT_SIGN_SPLIT_VISIBILITY_TIMEOUT_S = 2.0
PLANT_SIGN_SPLIT_POLL_S = 0.02
# Core 1 releases the exact request to Core 0 with this wrapping-monotonic
# actuator deadline. Core 0 records the exact post-write capture tick; ACT
# records the later Core 1 acknowledgement-consumption second.
CROSS_CORE_ACTUATOR_ACK_MAXIMUM_AGE_S = 30


@dataclass(frozen=True)
class CampaignSpec:
    campaign: str
    profile: str
    run_identity: str
    start_code: int
    correction_limit: int
    cumulative_limit: int
    minimum_code: int = 0xA800
    maximum_code: int = 0xAB00
    maximum_step: int = 21


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _fsync_path(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)
    _fsync_path(path.parent)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _latest_health(path: Path) -> dict[tuple[str, str], str]:
    latest: dict[tuple[str, str], str] = {}
    for row in _read_csv(path):
        if row.get("record_type") == "STS":
            latest[(row.get("component", ""), row.get("status_key", ""))] = row.get(
                "status_value", ""
            )
    return latest


def _cx321_response_is_plant_sign_identification(
    row: dict[str, str]
) -> bool:
    """Classify the first frozen +/−21-code CX321 transaction explicitly."""

    ordinal = int(row["correction_ordinal"])
    delta = int(row["requested_delta_codes"])
    cumulative = int(row["cumulative_after_codes"])
    if ordinal == 1:
        if abs(delta) != 21 or cumulative != 21:
            raise ValueError(
                "CX321 first phase-4 transaction is not the frozen plant-sign stimulus"
            )
        return True
    return False


def _await_cx321_plant_sign_response(
    psq_path: Path,
    *,
    request_sequence: int,
    timeout_s: float = PLANT_SIGN_SPLIT_VISIBILITY_TIMEOUT_S,
) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Bound the serial-split race between ACT and matching PSQ response rows."""

    deadline = time.monotonic() + timeout_s
    while True:
        if psq_path.exists():
            _fsync_path(psq_path)
            rows = _read_csv(psq_path)
            matches = [
                item
                for item in rows
                if item.get("event") == "response"
                and item.get("request_sequence") == str(request_sequence)
            ]
            if matches:
                return rows, matches[-1]
        if time.monotonic() >= deadline:
            raise TimeoutError(
                "CX321 identification ACT response became visible before its "
                "matching PSQ response"
            )
        time.sleep(PLANT_SIGN_SPLIT_POLL_S)


def _join_cx321_psq_response_to_act(
    *,
    psq_response: dict[str, str],
    act_response: dict[str, str],
    timer_hz: int = 16_000_000,
) -> dict[str, object]:
    """Bind the exact PSQ application tuple to its durable ACT response."""

    if act_response.get("event") != "response":
        raise ValueError("CX321 phase-4 acknowledgement requires an ACT response")
    exact_fields = (
        "request_sequence",
        "application_sequence",
        "requested_delta_codes",
        "requested_code",
        "accepted_code",
        "applied_code",
        "dac_epoch",
    )
    for field in exact_fields:
        try:
            psq_value = int(psq_response[field])
            act_value = int(act_response[field])
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"CX321 PSQ/ACT join lacks canonical {field}"
            ) from exc
        if psq_value != act_value:
            raise ValueError(
                f"CX321 PSQ/ACT {field} differs: {psq_value} != {act_value}"
            )
    try:
        application_ticks = int(psq_response["application_timestamp_ticks"])
        application_s = int(act_response["application_timestamp_s"])
    except (KeyError, ValueError) as exc:
        raise ValueError(
            "CX321 PSQ/ACT application timestamp is not canonical"
        ) from exc
    if application_s < 0 or timer_hz <= 0 or application_ticks < 0:
        raise ValueError(
            "CX321 PSQ/ACT application timestamp is outside its domain"
        )
    # A legitimate cross-core acknowledgement can cross an integer-second
    # boundary. The exact Core 0 write must precede the end of Core 1's
    # consumption second, and their retained coarse-second separation remains
    # bounded by the same 30-second actuator deadline enforced in firmware.
    consumption_second_start = application_s * timer_hz
    consumption_second_end = consumption_second_start + timer_hz
    if application_ticks >= consumption_second_end:
        raise ValueError(
            "CX321 PSQ Core0 application tick follows its ACT Core1 "
            "acknowledgement-consumption second"
        )
    acknowledgement_lag_lower_bound_ticks = max(
        0, consumption_second_start - application_ticks
    )
    if acknowledgement_lag_lower_bound_ticks > (
        CROSS_CORE_ACTUATOR_ACK_MAXIMUM_AGE_S * timer_hz
    ):
        raise ValueError(
            "CX321 PSQ/ACT cross-core acknowledgement exceeds the frozen "
            "30-second actuator deadline"
        )
    return {
        "exact": True,
        "act_transaction_record_sequence": int(
            act_response["transaction_record_sequence"]
        ),
        "request_sequence": int(psq_response["request_sequence"]),
        "application_sequence": int(psq_response["application_sequence"]),
        "application_timestamp_s": application_s,
        "application_timestamp_ticks": application_ticks,
        "acknowledgement_lag_lower_bound_ticks": (
            acknowledgement_lag_lower_bound_ticks
        ),
        "cross_core_actuator_ack_maximum_age_s": (
            CROSS_CORE_ACTUATOR_ACK_MAXIMUM_AGE_S
        ),
        "timer_hz": timer_hz,
    }


def validate_transaction_row(
    row: dict[str, str],
    spec: CampaignSpec,
    identities: dict[str, str],
    expected_build_identity: str,
) -> None:
    exact = {
        "run_identity": spec.run_identity,
        "build_identity": expected_build_identity,
        "profile_identity": spec.profile,
        **identities,
    }
    for field, expected in exact.items():
        if row.get(field) != expected:
            raise ValueError(
                f"ACT identity mismatch for {field}: {row.get(field)!r} != {expected!r}"
            )
    if row.get("actionable") != "false":
        raise ValueError("serialized ACT evidence is actionable")
    event = row.get("event")
    if event == "manual_start":
        if int(row["applied_code"]) != spec.start_code or row.get("i2c_ok") != "true":
            raise ValueError("manual start did not establish the exact campaign start code")
        return

    current = int(row["current_applied_code"])
    requested = int(row["requested_code"])
    delta = int(row["requested_delta_codes"])
    accepted = int(row["accepted_code"])
    ordinal = int(row["correction_ordinal"])
    cumulative_after = int(row["cumulative_after_codes"])
    if not spec.minimum_code <= current <= spec.maximum_code:
        raise ValueError("current applied code is outside the immutable range")
    if requested != current + delta or abs(delta) > spec.maximum_step or delta == 0:
        raise ValueError("requested code/delta violates the immutable step relation")
    if not spec.minimum_code <= requested <= spec.maximum_code:
        raise ValueError("requested code is outside the immutable range")
    if event == "request_created" and accepted != 0:
        raise ValueError("unaccepted cross-core request has a non-zero accepted code")
    if event != "request_created" and accepted != requested:
        raise ValueError("accepted code differs from the immutable request")
    if not 1 <= ordinal <= spec.correction_limit:
        raise ValueError("correction ordinal exceeds the campaign limit")
    if not abs(delta) <= cumulative_after <= spec.cumulative_limit:
        raise ValueError("cumulative-after budget is invalid")

    if event in {"application", "response"}:
        if (
            int(row["applied_code"]) != requested
            or row.get("i2c_ok") != "true"
            or row.get("clamped") != "false"
            or row.get("ambiguous") != "false"
            or row.get("estimator_history_reset") != "true"
            or int(row["application_sequence"]) != ordinal
            or int(row["correction_count"]) != ordinal
            or int(row["cumulative_movement_codes"]) != cumulative_after
        ):
            raise ValueError("application acknowledgement is not exact and unambiguous")


IMMUTABLE_REQUEST_FIELDS = (
    "run_identity",
    "build_identity",
    "profile_identity",
    "session_id",
    "authorization_sequence",
    "nonce",
    "request_sequence",
    "decision_sequence",
    "source_first_sequence",
    "source_last_sequence",
    "decision_timestamp_s",
    "current_applied_code",
    "requested_delta_codes",
    "requested_code",
    "correction_ordinal",
    "cumulative_after_codes",
    "pre_error_hz",
    "estimator_sha256",
    "model_sha256",
    "active_policy_sha256",
    "response_policy_sha256",
    "numerical_policy_sha256",
)


def validate_transaction_history(
    rows: list[dict[str, str]],
    spec: CampaignSpec,
    identities: dict[str, str],
    expected_build_identity: str,
    *,
    dual_core: bool,
) -> None:
    """Validate the complete durable prefix before releasing any phase.

    Per-row schema checks are insufficient for actuator release: a later row
    could be individually in range while referring to a different request.
    This check binds every phase to the exact request_created/request_accepted
    capsule, enforces event order and budgets cumulatively, and accepts only a
    final incomplete prefix while the corresponding live phase is pending.
    """
    if not rows:
        return
    sequences = [int(row["transaction_record_sequence"]) for row in rows]
    if sequences != list(range(1, len(rows) + 1)):
        raise ValueError("ACT transaction record sequence is not contiguous")
    for row in rows:
        validate_transaction_row(
            row, spec, identities, expected_build_identity
        )
    if rows[0].get("event") != "manual_start" or any(
        row.get("event") == "manual_start" for row in rows[1:]
    ):
        raise ValueError("ACT history requires exactly one leading manual_start")

    expected_events = (
        ("request_created", "core0_accepted", "application", "response")
        if dual_core
        else ("request_accepted", "application", "response")
    )
    automatic = rows[1:]
    index = 0
    expected_request_sequence = 1
    expected_ordinal = 1
    previous_code = spec.start_code
    previous_cumulative = 0
    while index < len(automatic):
        first = automatic[index]
        request_sequence = int(first["request_sequence"])
        if request_sequence != expected_request_sequence:
            raise ValueError("ACT request sequence is not contiguous")
        group: list[dict[str, str]] = []
        while index < len(automatic) and int(
            automatic[index]["request_sequence"]
        ) == request_sequence:
            group.append(automatic[index])
            index += 1
        events = [row["event"] for row in group]
        failure_index = len(expected_events) - 2
        valid_failure = (
            len(events) == failure_index + 1
            and events[:failure_index] == list(expected_events[:failure_index])
            and events[-1] == "application_fault"
        )
        valid_prefix = events == list(expected_events[: len(events)])
        if not valid_prefix and not valid_failure:
            raise ValueError(
                f"ACT request {request_sequence} phase order is invalid: {events}"
            )
        if len(events) > len(expected_events):
            raise ValueError("ACT request contains too many phases")
        if index < len(automatic) and not (
            len(events) == len(expected_events) and valid_prefix
        ):
            raise ValueError("a new ACT request follows an incomplete transaction")
        if valid_failure and index < len(automatic):
            raise ValueError("ACT application fault is not terminal")

        for row in group[1:]:
            changed = [
                field
                for field in IMMUTABLE_REQUEST_FIELDS
                if row.get(field) != first.get(field)
            ]
            if changed:
                raise ValueError(
                    f"ACT request {request_sequence} immutable fields changed: "
                    + ", ".join(changed)
                )
        delta = int(first["requested_delta_codes"])
        cumulative_after = int(first["cumulative_after_codes"])
        if int(first["correction_ordinal"]) != expected_ordinal:
            raise ValueError("ACT correction ordinal is not contiguous")
        if int(first["current_applied_code"]) != previous_code:
            raise ValueError("ACT request does not start at the last applied code")
        if cumulative_after != previous_cumulative + abs(delta):
            raise ValueError("ACT cumulative movement does not equal prior plus step")

        application = next(
            (row for row in group if row["event"] == "application"), None
        )
        if application is not None:
            previous_code = int(application["applied_code"])
            previous_cumulative = cumulative_after
        if len(events) == len(expected_events) and valid_prefix:
            expected_request_sequence += 1
            expected_ordinal += 1
        elif index < len(automatic):
            raise ValueError("ACT history continues after an incomplete prefix")


class ActiveTransactionSupervisor:
    def __init__(
        self,
        *,
        run_dir: Path,
        command_fifo: Path,
        abort_fifo: Path,
        spec: CampaignSpec,
        identities: dict[str, str],
        expected_build_identity: str,
        allow_manual_start: bool,
        allow_arm: bool,
        duration_s: float | None,
        emergency_command_fifo: Path | None = None,
        console_events: bool = False,
        dual_core_transactions: bool = False,
        observational_responses: bool = False,
    ) -> None:
        self.run_dir = run_dir
        self.command_fifo = command_fifo
        self.abort_fifo = abort_fifo
        self.spec = spec
        self.identities = identities
        self.expected_build_identity = expected_build_identity
        self.allow_manual_start = allow_manual_start
        self.allow_arm = allow_arm
        self.duration_s = duration_s
        self.emergency_command_fifo = emergency_command_fifo
        self.console_events = console_events
        self.dual_core_transactions = dual_core_transactions
        self.observational_responses = observational_responses
        self.state_path = run_dir / SUPERVISOR_STATE
        self.events_path = run_dir / SUPERVISOR_EVENTS
        self.state = self._load_state()

    def _load_state(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {
            "schema_version": 1,
            "campaign": self.spec.campaign,
            "started_at_utc": _utc_now(),
            "lease_sequence": 0,
            "authorization_sequence": 0,
            "manual_start_sent": False,
            "arm_pending": False,
            "acknowledged_record_sequences": [],
            "inflight_evidence_acknowledgement": None,
            "observed_manual_record_sequences": [],
            "initial_session_id": None,
            "terminal": None,
        }

    def _prepare_evidence_acknowledgement(
        self, row: dict[str, str], phase: int
    ) -> dict[str, object]:
        return {}

    def _confirm_evidence_acknowledgement(
        self, acknowledgement: dict[str, object]
    ) -> bool:
        return True

    def _save(self) -> None:
        _atomic_json(self.state_path, self.state)

    def _event(self, event: str, **fields: object) -> None:
        payload = {"utc": _utc_now(), "event": event, **fields}
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if self.console_events:
            print(json.dumps(payload, sort_keys=True), flush=True)

    def _command(self, command: str) -> None:
        send_command_to_fifo(self.command_fifo, command)
        self._event("command_submitted", command=command)

    def _abort(self, reason: str) -> None:
        try:
            if self.emergency_command_fifo is not None:
                send_command_to_fifo(
                    self.emergency_command_fifo, "ACTIVE ABORT"
                )
                self._event(
                    "emergency_device_abort_submitted",
                    reason=reason,
                )
            else:
                self._command("ACTIVE ABORT")
        except (OSError, SystemExit, ValueError) as exc:
            self._event("device_abort_submission_failed", reason=reason, error=str(exc))
        self.state["terminal"] = {"result": "aborted", "reason": reason, "utc": _utc_now()}
        self._save()

    def _identity_ready(self, health: dict[tuple[str, str], str]) -> bool:
        expected = {
            "run_identity": self.spec.run_identity,
            "build_identity": self.expected_build_identity,
            "profile_identity": self.spec.profile,
            **self.identities,
        }
        for key, value in expected.items():
            observed = health.get(("cx317_active", key))
            if observed is None:
                return False
            if observed != value:
                raise ValueError(f"live {key} mismatch: {observed!r} != {value!r}")
        session = int(health.get(("cx317_active", "session_id"), "0"))
        if session == 0:
            return False
        if self.state["initial_session_id"] is None:
            self.state["initial_session_id"] = session
            self._save()
        elif session != self.state["initial_session_id"]:
            raise ValueError("active snapshot session changed during the campaign")
        return True

    def _preserve_and_acknowledge(self, row: dict[str, str], phase: int) -> None:
        record_sequence = int(row["transaction_record_sequence"])
        request_sequence = int(row["request_sequence"])
        step = request_sequence if request_sequence else 0
        capsule_dir = self.run_dir / "reports" / f"step_{step:03d}"
        capsule_dir.mkdir(parents=True, exist_ok=True)
        capsule = capsule_dir / (
            f"record_{record_sequence:06d}_{row['event']}.json"
        )
        if capsule.exists():
            existing = json.loads(capsule.read_text(encoding="utf-8"))
            if existing != row:
                raise ValueError(f"immutable capsule collision at {capsule}")
        else:
            _atomic_json(capsule, row)
        active_csv = self.run_dir / ACTIVE_CSV
        _fsync_path(active_csv)
        _fsync_path(capsule)
        hybrid_profile = self.spec.profile in {
            "cx320_active_hybrid",
            "cx321_active_hybrid",
            "cx322_direct_hybrid",
            "cx322_d9_d6_integration_engineering",
            SUSTAINED_HYBRID_PROFILE_ID,
        }
        acknowledgement_command = f"ACTIVE EVIDENCE {request_sequence} {phase}"
        plant_sign_response = False
        identification_phase4 = (
            self.spec.profile == "cx321_active_hybrid"
            and phase == 4
            and _cx321_response_is_plant_sign_identification(row)
        )
        if identification_phase4:
            from .cx321_plant_sign_evidence_guard import (
                PlantSignReplayContext,
                complete_plant_sign_evidence_chain,
                replay_plant_sign_evidence,
                replay_plant_sign_windows_against_snapshots,
            )

            psq_path = self.run_dir / "csv/plant_sign_qualification_v1.csv"
            psq_rows, response_psq = _await_cx321_plant_sign_response(
                psq_path, request_sequence=request_sequence
            )
            if (
                response_psq.get("run_identity") != self.spec.run_identity
                or response_psq.get("build_identity")
                != self.expected_build_identity
                or response_psq.get("profile_identity") != self.spec.profile
                or int(response_psq.get("capture_session", "0"))
                != int(self.state.get("initial_session_id") or 0)
            ):
                raise ValueError(
                    "CX321 plant-sign response identity differs from the active run"
                )
            expected_plant_sign = getattr(self, "plant_sign_identities", None)
            if not isinstance(expected_plant_sign, dict) or any(
                response_psq.get(field) != expected
                for field, expected in expected_plant_sign.items()
            ):
                raise ValueError(
                    "CX321 plant-sign response provenance differs from the frozen manifest"
                )
            response_index = psq_rows.index(response_psq)
            prefix = psq_rows[: response_index + 1]
            context = PlantSignReplayContext(
                run_identity=response_psq["run_identity"],
                build_identity=response_psq["build_identity"],
                profile_identity=response_psq["profile_identity"],
                policy_sha256=response_psq["policy_sha256"],
                plant_sign_gate_sha256=response_psq["plant_sign_gate_sha256"],
                identification_estimator_sha256=response_psq[
                    "identification_estimator_sha256"
                ],
                identification_estimator_config_sha256=response_psq[
                    "identification_estimator_config_sha256"
                ],
                natural_frequency_estimator_sha256=response_psq[
                    "natural_frequency_estimator_sha256"
                ],
                capture_session=int(response_psq["capture_session"]),
            )
            attestation = replay_plant_sign_evidence(prefix, context)
            if not attestation["passed"]:
                raise ValueError(
                    "CX321 plant-sign response did not pass exact replay"
                )
            snapshot_path = self.run_dir / "csv/pps_snapshots.csv"
            _fsync_path(snapshot_path)
            snapshot_proof = replay_plant_sign_windows_against_snapshots(
                prefix,
                _read_csv(snapshot_path),
                context,
            )
            act_join = _join_cx321_psq_response_to_act(
                psq_response=response_psq,
                act_response=row,
                timer_hz=context.timer_hz,
            )
            complete_chain = complete_plant_sign_evidence_chain(
                psq_replay=attestation,
                snapshot_window_proof=snapshot_proof,
                act_response_join=act_join,
            )
            attestation["psq_replay_attestation_sha256"] = attestation[
                "attestation_sha256"
            ]
            attestation["act_response_join"] = act_join
            attestation["snapshot_window_proof"] = snapshot_proof
            attestation["complete_evidence_chain"] = complete_chain
            # This is the opaque digest consumed and echoed by firmware.  It
            # now binds PSQ + raw SNP + ACT, while the PSQ-only digest remains
            # explicit above for deterministic independent replay.
            attestation["attestation_sha256"] = complete_chain[
                "attestation_sha256"
            ]
            plant_sign_response = True
            acknowledgement_command = (
                f"ACTIVE EVIDENCE {request_sequence} 4 "
                f"{attestation['response_record_sequence']} "
                f"{attestation['response_counts']} "
                f"{attestation['application_sequence']} "
                f"{attestation['dac_epoch']} "
                f"{attestation['response_source_last_sequence']} "
                f"{attestation['attestation_sha256']}"
            )
            attestation_path = capsule_dir / (
                f"record_{record_sequence:06d}_plant_sign_replay_attestation.json"
            )
            _atomic_json(attestation_path, attestation)
            _fsync_path(attestation_path)
        if hybrid_profile and phase == 4 and not plant_sign_response:
            from .active_hybrid_evidence_guard import (
                replay_response_before_acknowledgement,
            )

            active_hybrid_csv = (
                self.run_dir / "csv/active_hybrid_decisions_v1.csv"
            )
            _fsync_path(active_hybrid_csv)
            attestation = replay_response_before_acknowledgement(
                active_hybrid_csv=active_hybrid_csv,
                active_transactions_csv=active_csv,
                response_row=row,
                policy_path=getattr(self, "natural_policy_path", None),
                expected_profile_identity=self.spec.profile,
                expected_active_policy_sha256=getattr(
                    self, "expected_active_policy_sha256", None
                ),
                plant_sign_csv=(
                    self.run_dir / "csv/plant_sign_qualification_v1.csv"
                    if self.spec.profile == "cx321_active_hybrid"
                    else None
                ),
                estimates_csv=self.run_dir / "csv/estimates_v2.csv",
            )
            attestation_path = capsule_dir / (
                f"record_{record_sequence:06d}_response_replay_attestation.json"
            )
            _atomic_json(attestation_path, attestation)
            _fsync_path(attestation_path)
        if hybrid_profile:
            inflight = self.state.get("inflight_evidence_acknowledgement")
            if inflight is None:
                inflight = {
                    "record_sequence": record_sequence,
                    "request_sequence": request_sequence,
                    "phase": phase,
                    "host_write_confirmed": False,
                    **self._prepare_evidence_acknowledgement(row, phase),
                }
                self.state["inflight_evidence_acknowledgement"] = inflight
                self._save()
                self._command(acknowledgement_command)
                inflight["host_write_confirmed"] = True
                self._save()
            elif (
                int(inflight.get("record_sequence", -1)) != record_sequence
                or int(inflight.get("request_sequence", -1)) != request_sequence
                or int(inflight.get("phase", -1)) != phase
            ):
                raise ValueError(
                    "a different active-hybrid evidence acknowledgement is already inflight"
                )
            if not self._confirm_evidence_acknowledgement(inflight):
                raise ValueError(
                    "active-hybrid evidence acknowledgement reached the host serial write "
                    "boundary but firmware consumption is unconfirmed"
                )
        else:
            self._command(f"ACTIVE EVIDENCE {request_sequence} {phase}")
        acknowledged = self.state["acknowledged_record_sequences"]
        if record_sequence not in acknowledged:
            acknowledged.append(record_sequence)
            acknowledged.sort()
        self.state["inflight_evidence_acknowledgement"] = None
        self._save()
        self._event(
            "transaction_phase_acknowledged",
            record_sequence=record_sequence,
            request_sequence=request_sequence,
            phase=phase,
            capsule=str(capsule),
        )

    def _process_transactions(self) -> None:
        path = self.run_dir / ACTIVE_CSV
        if not path.exists():
            return
        validation = validate_csv(
            path,
            CsvValidationContext("active_transactions_v1", frozenset(), frozenset()),
        )
        if validation.errors:
            raise ValueError("ACT contract validation failed: " + "; ".join(validation.errors))
        rows = _read_csv(path)
        validate_transaction_history(
            rows,
            self.spec,
            self.identities,
            self.expected_build_identity,
            dual_core=self.dual_core_transactions,
        )
        acknowledged = set(self.state["acknowledged_record_sequences"])
        observed_manual = set(self.state["observed_manual_record_sequences"])
        for row in rows:
            record_sequence = int(row["transaction_record_sequence"])
            validate_transaction_row(
                row, self.spec, self.identities, self.expected_build_identity
            )
            event = row["event"]
            if event == "manual_start":
                if record_sequence in observed_manual:
                    continue
                self._event(
                    "manual_start_observed",
                    record_sequence=record_sequence,
                    applied_code=int(row["applied_code"]),
                )
                self.state["observed_manual_record_sequences"].append(
                    record_sequence
                )
                self.state["observed_manual_record_sequences"].sort()
                self._save()
                continue
            if record_sequence in acknowledged:
                continue
            phases = (
                {
                    "request_created": 1,
                    "core0_accepted": 2,
                    "application": 3,
                    "application_fault": 3,
                    "response": 4,
                }
                if self.dual_core_transactions
                else {
                    "request_accepted": 1,
                    "application": 2,
                    "application_fault": 2,
                    "response": 3,
                }
            )
            phase = phases[event]
            self._preserve_and_acknowledge(row, phase)
            if event in {"request_accepted", "request_created"}:
                self._event(
                    (
                        "core1_request_released_after_durable_capsule"
                        if self.dual_core_transactions
                        else "automatic_request_released_after_durable_capsule"
                    ),
                    request_sequence=int(row["request_sequence"]),
                    requested_code=int(row["requested_code"]),
                    delta_codes=int(row["requested_delta_codes"]),
                )
            elif event == "core0_accepted":
                self._event(
                    "core0_acceptance_released_after_durable_capsule",
                    request_sequence=int(row["request_sequence"]),
                    accepted_code=int(row["accepted_code"]),
                )
            elif event == "application_fault":
                raise ValueError("single I2C application attempt failed")
            elif event == "application":
                self.state["arm_pending"] = False
                if self.dual_core_transactions:
                    self.state["arm_sent_at_utc"] = None
                self._save()
                self._event(
                    (
                        "cross_core_application_confirmed"
                        if self.dual_core_transactions
                        else "automatic_application_confirmed"
                    ),
                    request_sequence=int(row["request_sequence"]),
                    applied_code=int(row["applied_code"]),
                    correction_count=int(row["correction_count"]),
                    cumulative_movement_codes=int(row["cumulative_movement_codes"]),
                )
            elif event == "response":
                classification = row["response_class"]
                correction_count = int(row["correction_count"])
                active_state = row["active_state"]
                if self.dual_core_transactions:
                    self.state["response_count"] += 1
                self._event(
                    "response_classified",
                    request_sequence=int(row["request_sequence"]),
                    response_class=classification,
                    post_error_hz=float(row["post_error_hz"]),
                    observed_response_hz=float(row["observed_response_hz"]),
                    **(
                        {"response_count": self.state["response_count"]}
                        if self.dual_core_transactions
                        else {}
                    ),
                )
                if active_state == "OUT_OF_MODEL_HOLD":
                    self.state["terminal"] = {
                        "result": "held",
                        "reason": "out_of_model_hold",
                        "response_class": classification,
                        "utc": _utc_now(),
                    }
                elif self.observational_responses and classification != (
                    "measurement_or_actuator_fault"
                ):
                    self._event(
                        "response_retained_as_nonterminal_observation",
                        request_sequence=int(row["request_sequence"]),
                        response_class=classification,
                    )
                elif classification in {"inside_deadband", "limit_reached"}:
                    self.state["terminal"] = {
                        "result": "healthy_stop",
                        "reason": classification,
                        "utc": _utc_now(),
                    }
                elif classification in {
                    "wrong_sign",
                    "excess_response",
                    "growing_error",
                    "measurement_or_actuator_fault",
                }:
                    self.state["terminal"] = {
                        "result": "fault",
                        "reason": classification,
                        "utc": _utc_now(),
                    }
                elif correction_count >= self.spec.correction_limit:
                    self.state["terminal"] = {
                        "result": "healthy_stop",
                        "reason": "correction_limit_reached",
                        "utc": _utc_now(),
                    }
                self._save()

    def _renew_lease(self) -> None:
        self.state["lease_sequence"] += 1
        self._command(f"ACTIVE LEASE {self.state['lease_sequence']}")
        self._save()

    def _maybe_start_or_arm(self, health: dict[tuple[str, str], str]) -> None:
        if not self._identity_ready(health):
            return
        state = health.get(("cx317_active", "state"), "")
        reason = health.get(("cx317_active", "reason"), "")
        if state == "FAULT":
            raise ValueError(f"device active state faulted: {reason}")
        if state == "ABORTED":
            raise ValueError(f"device active state aborted: {reason}")
        if state == "REFERENCE_HOLD":
            return
        if state == "OUT_OF_MODEL_HOLD":
            self.state["terminal"] = {
                "result": "held",
                "reason": reason or "out_of_model_hold",
                "utc": _utc_now(),
            }
            self._save()
            self._event("campaign_fail_static_hold", reason=reason)
            return

        manual_confirmed = health.get(
            ("cx317_active", "manual_start_confirmed")
        ) == "true"
        if (
            self.allow_manual_start
            and not manual_confirmed
            and not self.state["manual_start_sent"]
            and state == "DISARMED"
        ):
            self._command(f"DAC SET 0x{self.spec.start_code:04X}")
            self.state["manual_start_sent"] = True
            self._save()
            self._event("manual_start_requested", code=self.spec.start_code)
            return
        if not self.allow_arm or not manual_confirmed or self.state["arm_pending"]:
            return
        progress = int(
            health.get(("cx317_active", "selected_interval_count"), "0")
        )
        arm_eligible = health.get(("cx317_active", "arm_eligible")) == "true"
        evidence_clear = (
            health.get(("cx317_active", "evidence_phase")) == "evidence_clear"
        )
        correction_count = int(
            health.get(("cx317_active", "correction_count"), "0")
        )
        if (
            state == "DISARMED"
            and arm_eligible
            and evidence_clear
            and progress >= ARM_PROGRESS_THRESHOLD
            and correction_count < self.spec.correction_limit
        ):
            uptime = int(health[("cx317_active", "uptime_s")])
            self.state["authorization_sequence"] += 1
            sequence = self.state["authorization_sequence"]
            nonce = secrets.randbits(32) or 1
            expiry = uptime + 110
            self._command(f"ACTIVE ARM {sequence} {nonce} {expiry}")
            self.state["arm_pending"] = True
            self._save()
            self._event(
                "one_decision_armed",
                authorization_sequence=sequence,
                nonce=nonce,
                expiry_s=expiry,
                selected_interval_count=progress,
            )

    def run(self) -> int:
        capture_flag = self.run_dir / CAPTURE_IN_PROGRESS_FLAG
        if not capture_flag.exists():
            raise RuntimeError("capture is not marked in progress")
        started = time.monotonic()
        last_lease = 0.0
        last_query = 0.0
        with AbortFifo(self.abort_fifo) as abort:
            self._event(
                "supervisor_started",
                campaign=self.spec.campaign,
                abort_fifo=str(self.abort_fifo),
            )
            self._command("CONFIG?")
            self._command("DAC?")
            while True:
                now = time.monotonic()
                if abort.poll():
                    self._abort("independent_host_abort_fifo")
                    return 3
                if not capture_flag.exists():
                    self._abort("capture_owner_lost")
                    return 4
                if self.duration_s is not None and now - started > self.duration_s:
                    self._abort("supervisor_duration_expired")
                    return 5
                if now - last_lease >= LEASE_PERIOD_S:
                    self._renew_lease()
                    last_lease = now
                if now - last_query >= QUERY_PERIOD_S:
                    self._command("ACTIVE?")
                    last_query = now
                self._process_transactions()
                if self.state["terminal"] is not None:
                    self._event("campaign_terminal", **self.state["terminal"])
                    return (
                        0
                        if self.state["terminal"]["result"]
                        in {"healthy_stop", "held"}
                        else 2
                    )
                health = _latest_health(self.run_dir / HEALTH_CSV)
                self._maybe_start_or_arm(health)
                time.sleep(0.2)
