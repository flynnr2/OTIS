"""Deterministic structural preflight for adaptive hybrid regulation.

This preflight is non-authorizing and performs no serial, flash, reset, DAC,
process, FIFO, analyzer, or sealing I/O.  It exercises only the controller and
evidence models at exact native microsecond boundaries.  It can never satisfy
the activation requirement for a genuine operational-path rehearsal.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .adaptive_hybrid_bundle import validate_bundle
from .adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    ADAPTIVE_HYBRID_STRUCTURAL_PREFLIGHT_COVERAGE,
    AdaptiveHybridProgramme,
)
from .adaptive_hybrid_policy import (
    AdaptiveHybridObservation,
    AdaptiveHybridPhasePriorityController,
    policy_from_mapping,
)
from .authoritative_inputs import (
    validate_authoritative_inputs,
    ROOT_PROFILE,
)
from .adaptive_hybrid_proposal import validate_proposal


TOOL_ID = "adaptive_hybrid_structural_preflight_v1"
REPORT_TYPE = "adaptive_hybrid_structural_preflight_v1"


def _canonical_sha256(value: dict[str, Any]) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _observation(
    controller: AdaptiveHybridPhasePriorityController,
    *,
    timestamp_us: int,
    opening: int,
    closing: int,
    metadata_qualified: bool = True,
    phase_valid: bool = True,
    external_event_disposition: str = "absent",
) -> AdaptiveHybridObservation:
    # external_event_disposition is intentionally excluded from the control
    # observation: D10 evidence cannot enter D14/D8 authority or actuation.
    if external_event_disposition not in {"normal", "absent", "noisy", "overflow"}:
        raise ValueError("unknown D10 structural-preflight disposition")
    return AdaptiveHybridObservation(
        timestamp_s=timestamp_us // 1_000_000,
        timestamp_ticks=timestamp_us,
        capture_session=1,
        source_acceptance_epoch=1,
        source_opening_accepted_boundary_ordinal=opening,
        source_closing_accepted_boundary_ordinal=closing,
        dac_epoch=controller.dac_epoch,
        applied_code=controller.applied_code,
        accumulated_edge_error_counts=-1,
        tight_state="TIGHT_INSIDE",
        phase_epoch=1,
        relative_phase_cycles=-4,
        frequency_estimator_id="OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1",
        phase_valid=phase_valid,
        metadata_qualified=metadata_qualified,
    )


def _d10_isolation_replay(policy: Any) -> dict[str, Any]:
    projections: dict[str, list[dict[str, Any]]] = {}
    for disposition in ("normal", "absent", "noisy", "overflow"):
        controller = AdaptiveHybridPhasePriorityController(policy)
        rows = []
        for timestamp_us, opening, closing in (
            (0, 0, 600),
            (600_000_000, 600, 1200),
        ):
            decision = controller.decide(
                _observation(
                    controller,
                    timestamp_us=timestamp_us,
                    opening=opening,
                    closing=closing,
                    external_event_disposition=disposition,
                )
            )
            rows.append(asdict(decision))
        projections[disposition] = rows
    baseline = projections["normal"]
    return {
        "channel_contract": {
            "CH0": {"pin": "D10", "role": "external_event"},
            "CH1": {"pin": "D14", "role": "reference"},
            "EVT": {"pin": "D10", "channel": 0},
            "REF": {"pin": "D14", "channel": 1},
        },
        "dispositions": projections,
        "control_and_terminal_identical": all(
            rows == baseline for rows in projections.values()
        ),
    }


def run(
    *,
    bundle_path: Path,
    proposal_path: Path,
    output_path: Path,
    programme: AdaptiveHybridProgramme = ADAPTIVE_HYBRID_PROGRAMME,
) -> dict[str, Any]:
    bundle = validate_bundle(bundle_path)
    proposal = validate_proposal(proposal_path, programme)
    frozen_inputs = validate_authoritative_inputs(bundle["authoritative_inputs"])
    policy = policy_from_mapping(
        frozen_inputs.document(ROOT_PROFILE),
        policy_sha256=str(
            frozen_inputs.binding(ROOT_PROFILE)["sha256"]
        ),
    )
    controller = AdaptiveHybridPhasePriorityController(policy)

    first_hold = controller.decide(
        _observation(controller, timestamp_us=0, opening=0, closing=600)
    )
    request = controller.decide(
        _observation(
            controller,
            timestamp_us=600_000_000,
            opening=600,
            closing=1200,
        )
    )
    controller.confirm_application(
        request,
        applied_code=request.requested_code,
        dac_epoch=controller.dac_epoch + 1,
        first_consumer_exact=True,
    )
    debt_after_application = asdict(controller.debt)
    response_hold = controller.decide(
        _observation(
            controller,
            timestamp_us=1_200_000_000,
            opening=1200,
            closing=1800,
        )
    )
    controller.complete_response(fresh_exact=True)

    code_before_metadata_hold = controller.applied_code
    debt_before_metadata_hold = asdict(controller.debt)
    controller.enter_metadata_hold()
    metadata_hold = controller.decide(
        _observation(
            controller,
            timestamp_us=1_800_000_000,
            opening=1800,
            closing=2400,
            metadata_qualified=False,
        )
    )
    controller.requalify_metadata(
        acceptance_epoch=1, accepted_boundary_ordinal=2400
    )
    first_requalification = controller.decide(
        _observation(
            controller,
            timestamp_us=2_400_000_000,
            opening=2400,
            closing=3000,
        )
    )
    second_requalification = controller.decide(
        _observation(
            controller,
            timestamp_us=3_000_000_000,
            opening=3000,
            closing=3600,
        )
    )
    d10 = _d10_isolation_replay(policy)
    checks = {
        "bundle_identity_exact": bundle["programme_id"] == programme.programme_id,
        "proposal_non_authorizing": proposal.get("authority", {}).get("effective") is False,
        "first_window_holds": first_hold.reason == "persistence_first_interval_hold",
        "second_window_requests": request.reason == "maintenance_request_ready",
        "application_first_consumer_exact": controller.dac_epoch == 2,
        "response_pending_holds": response_hold.reason == "response_pending_hold",
        "correction_debt_retained": debt_after_application == debt_before_metadata_hold,
        "metadata_anomaly_is_nonterminal_hold": metadata_hold.reason == "metadata_hold",
        "metadata_hold_preserves_code": controller.applied_code == code_before_metadata_hold,
        "first_fresh_window_still_holds": (
            first_requalification.reason == "metadata_requalification_window_hold"
        ),
        "second_fresh_window_requalifies": not controller.metadata_hold,
        "D10_isolation": d10["control_and_terminal_identical"],
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "report_type": REPORT_TYPE,
        "tool": TOOL_ID,
        "created_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        ),
        "programme_id": programme.programme_id,
        "image_identity": programme.profile_id,
        "run_identity": programme.runtime_run_identity,
        "bundle_sha256": bundle["bundle_sha256"],
        "proposal_sha256": proposal["proposal_sha256"],
        "report_kind": "structural_preflight",
        "authorizes_activation": False,
        "physical_actions_performed": 0,
        "status": "passed" if all(checks.values()) else "failed",
        "coverage": list(ADAPTIVE_HYBRID_STRUCTURAL_PREFLIGHT_COVERAGE),
        "native_counter_domain": "rp2040_monotonic_us64",
        "checks": checks,
        "D10_isolation_replay": d10,
        "terminal": asdict(second_requalification),
    }
    report["report_sha256"] = _canonical_sha256(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output_path.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    except FileExistsError as error:
        raise ValueError(
            f"refusing to overwrite structural-preflight report: {output_path}"
        ) from error
    if report["status"] != "passed":
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise ValueError("adaptive-hybrid structural preflight failed: " + ", ".join(failed))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--proposal", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    print(
        json.dumps(
            run(bundle_path=args.bundle, proposal_path=args.proposal, output_path=args.output),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
