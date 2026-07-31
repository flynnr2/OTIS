from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json


DIAGNOSTIC_ALGORITHM_VERSION = "diagnostic_transition_engine_v1"
DIAGNOSTIC_CONFIG_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DiagnosticSpec:
    diagnostic_id: str
    subsystem: str
    severity: str
    reason_code: str
    clear_reason_code: str
    observation_effect: str = "none"
    reference_effect: str = "none"
    model_effect: str = "none"
    control_effect: str = "inhibit"
    raise_after: int = 1
    clear_after: int = 1
    update_interval: int = 10


@dataclass
class _Episode:
    number: int = 0
    active: bool = False
    bad_count: int = 0
    clean_count: int = 0
    occurrence_count: int = 0
    first_seen_ticks: int = 0
    last_seen_ticks: int = 0
    first_evidence_refs: str = ""
    latest_evidence_refs: str = ""
    last_token: str = ""


class DiagnosticEngine:
    def __init__(
        self,
        specs: tuple[DiagnosticSpec, ...],
        *,
        config_hash: str | None = None,
    ):
        if len({spec.diagnostic_id for spec in specs}) != len(specs):
            raise ValueError("diagnostic identifiers must be unique")
        for spec in specs:
            if (
                not spec.diagnostic_id
                or spec.raise_after < 1
                or spec.clear_after < 1
                or spec.update_interval < 1
            ):
                raise ValueError(
                    "diagnostic rules require an identifier and positive "
                    "raise/clear/update counts"
                )
        self.specs = {spec.diagnostic_id: spec for spec in specs}
        expected_hash = diagnostic_config_hash(specs)
        if config_hash is not None and config_hash != expected_hash:
            raise ValueError(
                "diagnostic config_hash does not identify the supplied rule table"
            )
        self.config_hash = expected_hash
        self.state = {identifier: _Episode() for identifier in self.specs}
        self.sequence = 0

    def observe(
        self,
        diagnostic_id: str,
        *,
        active: bool,
        ticks: int,
        time_domain: str,
        evidence_refs: str,
        evidence_token: str,
        confidence: str = "1",
    ) -> dict[str, str] | None:
        spec = self.specs[diagnostic_id]
        episode = self.state[diagnostic_id]
        if evidence_token == episode.last_token:
            return None
        episode.last_token = evidence_token

        transition: str | None = None
        if active:
            episode.clean_count = 0
            episode.bad_count += 1
            if not episode.active and episode.bad_count >= spec.raise_after:
                episode.active = True
                episode.number += 1
                episode.occurrence_count = 1
                episode.first_seen_ticks = ticks
                episode.last_seen_ticks = ticks
                episode.first_evidence_refs = evidence_refs
                episode.latest_evidence_refs = evidence_refs
                transition = "raised"
            elif episode.active:
                episode.occurrence_count += 1
                episode.last_seen_ticks = ticks
                episode.latest_evidence_refs = evidence_refs
                if episode.occurrence_count % max(1, spec.update_interval) == 0:
                    transition = "updated"
        else:
            episode.bad_count = 0
            if episode.active:
                episode.clean_count += 1
                if episode.clean_count >= spec.clear_after:
                    episode.active = False
                    episode.last_seen_ticks = ticks
                    episode.latest_evidence_refs = evidence_refs
                    transition = "cleared"
            else:
                episode.clean_count = 0

        if transition is None:
            return None
        self.sequence += 1
        cleared = transition == "cleared"
        return {
            "record_type": "DIAG",
            "schema_version": "1",
            "diagnostic_seq": str(self.sequence),
            "diagnostic_id": spec.diagnostic_id,
            "episode_id": f"{spec.diagnostic_id}:episode:{episode.number}",
            "subsystem": spec.subsystem,
            "severity": spec.severity,
            "state": "cleared" if cleared else "active",
            "transition": transition,
            "diagnostic_confidence": confidence,
            "reason_code": spec.reason_code,
            "clear_reason_code": spec.clear_reason_code if cleared else "",
            "first_seen_ticks": str(episode.first_seen_ticks),
            "last_seen_ticks": str(episode.last_seen_ticks),
            "time_domain": time_domain,
            "occurrence_count": str(episode.occurrence_count),
            "persistence_state": "cleared" if cleared else "confirmed",
            "first_evidence_refs": episode.first_evidence_refs,
            "latest_evidence_refs": episode.latest_evidence_refs,
            "algorithm_version": DIAGNOSTIC_ALGORITHM_VERSION,
            "config_hash": self.config_hash,
            "observation_effect": spec.observation_effect,
            "reference_effect": spec.reference_effect,
            "model_effect": spec.model_effect,
            "control_effect": spec.control_effect,
        }


DEFAULT_DIAGNOSTIC_SPECS = (
    DiagnosticSpec(
        "diag.reference.cadence",
        "reference",
        "WARN",
        "reference_cadence_unqualified",
        "reference_cadence_requalified",
        observation_effect="invalidate",
        reference_effect="invalidate",
    ),
    DiagnosticSpec(
        "diag.reference.authority",
        "reference",
        "WARN",
        "reference_authority_unqualified",
        "reference_authority_requalified",
        reference_effect="reduce_trust",
    ),
    DiagnosticSpec(
        "diag.aperture.unqualified",
        "count_path",
        "WARN",
        "counter_aperture_unqualified",
        "counter_aperture_requalified",
        observation_effect="mark_unavailable",
        control_effect="none",
    ),
    DiagnosticSpec(
        "diag.sequence.discontinuity",
        "count_path",
        "WARN",
        "sequence_discontinuity",
        "sequence_continuity_requalified",
        observation_effect="invalidate",
    ),
    DiagnosticSpec(
        "diag.interpolation.support",
        "estimator",
        "WARN",
        "insufficient_interpolation_support",
        "interpolation_support_restored",
        observation_effect="invalidate",
    ),
    DiagnosticSpec(
        "diag.count.window",
        "count_path",
        "FAULT",
        "invalid_or_saturated_count_window",
        "count_window_requalified",
        observation_effect="invalidate",
        clear_after=3,
    ),
    DiagnosticSpec(
        "diag.resource.failure",
        "service_plane",
        "FAULT",
        "resource_failure",
        "resource_recovered",
        observation_effect="mark_unavailable",
        control_effect="inhibit",
    ),
    DiagnosticSpec(
        "diag.plant.inapplicable",
        "control",
        "WARN",
        "plant_model_inapplicable",
        "plant_model_applicable",
        model_effect="not_applicable",
    ),
    DiagnosticSpec(
        "diag.output.loss",
        "service_plane",
        "DEGRADED",
        "output_backpressure_loss",
        "output_path_recovered",
        observation_effect="none",
        reference_effect="none",
        model_effect="none",
        control_effect="none",
    ),
    DiagnosticSpec(
        "diag.estimator.identity",
        "estimator",
        "FAULT",
        "estimator_identity_mismatch",
        "estimator_identity_match_restored",
        model_effect="not_applicable",
    ),
)


def diagnostic_config_payload(
    specs: tuple[DiagnosticSpec, ...],
) -> dict[str, object]:
    return {
        "algorithm_version": DIAGNOSTIC_ALGORITHM_VERSION,
        "rules": [asdict(spec) for spec in specs],
        "schema_version": DIAGNOSTIC_CONFIG_SCHEMA_VERSION,
    }


def diagnostic_config_hash(specs: tuple[DiagnosticSpec, ...]) -> str:
    canonical = json.dumps(
        diagnostic_config_payload(specs),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


DEFAULT_DIAGNOSTIC_CONFIG_HASH = diagnostic_config_hash(
    DEFAULT_DIAGNOSTIC_SPECS
)
