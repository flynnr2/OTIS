"""Pure CX318 Stage 5 integer-count tight-deadband state machine.

This module has no command, DAC, transaction, or authority dependency.  It
only converts fresh 600-second accumulated-edge-error observations into the
frozen tight-band state used by the frequency-only controller and its replay.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable


POLICY_ID = "CX318_STAGE5_TIGHT_HYSTERETIC_COUNTS_V1"
AUTHORITATIVE_SPAN_S = 600
TIGHT_ENTRY_ABS_COUNTS = 2
LOOSE_RELEASE_ABS_COUNTS = 4
PERSISTENCE_ESTIMATES = 2

REQUALIFY_OUTSIDE = "REQUALIFY_OUTSIDE"
OUTSIDE = "OUTSIDE"
TIGHT_INSIDE = "TIGHT_INSIDE"


@dataclass(frozen=True)
class TightDeadbandDecision:
    """One non-authorizing policy result for an authoritative estimate."""

    policy_id: str
    state_before: str
    state_after: str
    reason: str
    absolute_edge_error_counts: int | None
    entry_pending_count: int
    release_pending_count: int
    frequency_controller_eligible: bool
    requalified: bool = False
    requalification_reason: str | None = None
    actionable: bool = False
    actuation_authorized: bool = False
    authorization_consumed: bool = False


class TightHystereticDeadband:
    """Stateful, pure implementation of the frozen Stage 5 band semantics."""

    def __init__(self) -> None:
        self._state = REQUALIFY_OUTSIDE
        self._entry_pending = 0
        self._release_pending = 0
        self._session: Hashable | None = None
        self._dac_epoch: Hashable | None = None
        self._have_identity = False

    @property
    def state(self) -> str:
        return self._state

    def _decision(
        self,
        state_before: str,
        reason: str,
        absolute_edge_error_counts: int | None,
        *,
        frequency_controller_eligible: bool = False,
        requalification_reason: str | None = None,
    ) -> TightDeadbandDecision:
        return TightDeadbandDecision(
            policy_id=POLICY_ID,
            state_before=state_before,
            state_after=self._state,
            reason=reason,
            absolute_edge_error_counts=absolute_edge_error_counts,
            entry_pending_count=self._entry_pending,
            release_pending_count=self._release_pending,
            frequency_controller_eligible=frequency_controller_eligible,
            requalified=requalification_reason is not None,
            requalification_reason=requalification_reason,
        )

    def _requalify(self) -> None:
        self._state = REQUALIFY_OUTSIDE
        self._entry_pending = 0
        self._release_pending = 0

    def observe(
        self,
        *,
        accumulated_edge_error_counts: int | None,
        fresh: bool,
        session: Hashable | None,
        dac_epoch: Hashable | None,
    ) -> TightDeadbandDecision:
        """Consume one estimate without creating any live authority.

        A session/DAC-epoch transition clears prior persistence evidence before
        evaluating the current observation.  A fresh, valid 600-second estimate
        in the new identity can therefore receive first-observation credit.
        Invalid or stale estimates clear all pending evidence and leave the band
        in fail-safe requalification.
        """

        state_before = self._state
        requalification_reason: str | None = None
        if session is None or dac_epoch is None:
            self._requalify()
            self._have_identity = False
            return self._decision(state_before, "identity_missing_requalify", None)
        if self._have_identity and session != self._session:
            self._requalify()
            requalification_reason = "session_changed_requalify"
        elif self._have_identity and dac_epoch != self._dac_epoch:
            self._requalify()
            requalification_reason = "dac_epoch_changed_requalify"
        self._session = session
        self._dac_epoch = dac_epoch
        self._have_identity = True

        if not fresh or accumulated_edge_error_counts is None:
            self._requalify()
            return self._decision(
                state_before,
                "invalid_or_stale_requalify",
                None,
                requalification_reason=requalification_reason,
            )
        if isinstance(accumulated_edge_error_counts, bool) or not isinstance(
            accumulated_edge_error_counts, int
        ):
            raise ValueError("accumulated edge error must be an integer count")

        absolute = abs(accumulated_edge_error_counts)
        if self._state == REQUALIFY_OUTSIDE:
            self._state = OUTSIDE

        if self._state == OUTSIDE:
            self._release_pending = 0
            if absolute <= TIGHT_ENTRY_ABS_COUNTS:
                self._entry_pending += 1
                if self._entry_pending >= PERSISTENCE_ESTIMATES:
                    self._state = TIGHT_INSIDE
                    self._entry_pending = 0
                    return self._decision(
                        state_before,
                        "tight_entry_confirmed",
                        absolute,
                        requalification_reason=requalification_reason,
                    )
                return self._decision(
                    state_before,
                    "tight_entry_pending",
                    absolute,
                    requalification_reason=requalification_reason,
                )
            self._entry_pending = 0
            if absolute == TIGHT_ENTRY_ABS_COUNTS + 1:
                return self._decision(
                    state_before,
                    "three_count_outside_hold",
                    absolute,
                    frequency_controller_eligible=True,
                    requalification_reason=requalification_reason,
                )
            return self._decision(
                state_before,
                "outside_loose_evidence",
                absolute,
                frequency_controller_eligible=True,
                requalification_reason=requalification_reason,
            )

        self._entry_pending = 0
        if absolute >= LOOSE_RELEASE_ABS_COUNTS:
            self._release_pending += 1
            if self._release_pending >= PERSISTENCE_ESTIMATES:
                self._state = OUTSIDE
                self._release_pending = 0
                return self._decision(
                    state_before,
                    "loose_release_confirmed",
                    absolute,
                    frequency_controller_eligible=True,
                    requalification_reason=requalification_reason,
                )
            return self._decision(
                state_before,
                "loose_release_pending",
                absolute,
                requalification_reason=requalification_reason,
            )
        self._release_pending = 0
        if absolute == TIGHT_ENTRY_ABS_COUNTS + 1:
            return self._decision(
                state_before,
                "three_count_inside_hold",
                absolute,
                requalification_reason=requalification_reason,
            )
        return self._decision(
            state_before,
            "tight_inside_hold",
            absolute,
            requalification_reason=requalification_reason,
        )
