"""Frozen contract validation for the cross-campaign offline programme.

This module deliberately has no capture, serial, firmware-build, or actuator
imports.  The contract is a fail-closed boundary between immutable completed
evidence and the derived study products.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


CONTRACT_ID_V1 = "OTIS_CROSS_CAMPAIGN_ADAPTIVE_STEERING_OFFLINE_V1"
CONTRACT_ID_V2 = "OTIS_CROSS_CAMPAIGN_ADAPTIVE_STEERING_OFFLINE_V2"
EXPECTED_CANDIDATES = (
    "cx322_unchanged",
    "cx322_tagged_debt_with_bounded_backcalculation",
    "cx322_tagged_debt_backcalculation_plus_same_sign_persistence",
)
EXPECTED_TERMINALS = (
    "provisional_finite_policy_delta_recommended_pending_d9_gate",
    "provisional_cx322_unchanged_pending_d9_gate",
    "study_invalid_due_to_evidence_or_replay_mismatch",
)
FORBIDDEN_AUTHORITY = (
    "serial_access",
    "live_process_access",
    "active_gnss_soak_input",
    "firmware_build",
    "firmware_edit",
    "firmware_flash",
    "reset",
    "dac_write",
    "control_arm",
    "physical_rehearsal",
    "live_acquisition",
)


def canonical_sha256(value: object) -> str:
    """Return the programme's stable semantic digest."""

    return sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _load_v1(value: dict[str, Any]) -> dict[str, Any]:
    """Strictly validate the original frozen V1 contract."""

    _require(isinstance(value, dict), "analysis contract root must be an object")
    _require(value.get("schema_version") == 1, "unsupported contract schema")
    _require(value.get("contract_id") == CONTRACT_ID_V1, "unexpected contract id")
    _require(
        value.get("status") == "prospectively_frozen_before_candidate_results",
        "analysis contract is not prospectively frozen",
    )
    claimed = value.get("contract_sha256")
    unsigned = {key: item for key, item in value.items() if key != "contract_sha256"}
    _require(
        isinstance(claimed, str) and claimed == canonical_sha256(unsigned),
        "analysis contract semantic identity differs",
    )

    authority = value.get("authority")
    _require(isinstance(authority, dict), "authority must be an object")
    _require(authority.get("offline_analysis") is True, "offline authority missing")
    _require(
        authority.get("completed_evidence_read_only") is True,
        "source evidence must be read-only",
    )
    _require(
        authority.get("isolated_worktree_required") is True,
        "isolated worktree boundary missing",
    )
    _require(
        all(authority.get(name) is False for name in FORBIDDEN_AUTHORITY),
        "contract grants live, firmware, or actuator authority",
    )

    sources = value.get("sources")
    _require(isinstance(sources, list) and len(sources) == 3, "exactly three sources required")
    source_ids = [item.get("source_id") for item in sources]
    _require(
        source_ids == ["cx317_fll_baseline", "cx322_coherent", "attempt4_sustained"],
        "required source ordering or identity differs",
    )
    for source in sources:
        _require(source.get("required") is True, "all primary sources must be required")
        consumed = source.get("consumed_files")
        _require(isinstance(consumed, dict) and consumed, "source consumed-file ledger empty")
        _require(
            all(
                isinstance(relative, str)
                and relative
                and isinstance(digest, str)
                and len(digest) == 64
                for relative, digest in consumed.items()
            ),
            "malformed consumed-file binding",
        )

    candidates = value.get("controller_comparison", {}).get("candidates")
    _require(
        isinstance(candidates, list)
        and tuple(item.get("candidate_id") for item in candidates) == EXPECTED_CANDIDATES,
        "candidate set or ordering differs",
    )
    _require(
        value.get("terminal_outcomes") == list(EXPECTED_TERMINALS),
        "terminal set differs",
    )
    _require(
        value.get("phase_analysis", {}).get("horizons_s")
        == [600, 1500, 3600, 7200, 21600],
        "phase horizons differ",
    )
    tau = value.get("stability_analysis", {}).get("tau_grid_s")
    _require(
        isinstance(tau, list)
        and tau == sorted(set(tau))
        and set(value["phase_analysis"]["horizons_s"]) <= set(tau),
        "stability tau grid is malformed or omits phase horizons",
    )
    _require(
        value.get("segmentation", {}).get("phase_epoch_join") == "forbidden",
        "phase joining must remain forbidden",
    )
    _require(
        value.get("counterfactual_model", {})
        .get("held_out_validation", {})
        .get("invalidity")
        == "any_required_gate_failure_blocks_changed_policy_recommendation",
        "model invalidity is not fail-closed",
    )
    return value


def _load_v2(path: Path, overlay: dict[str, Any]) -> dict[str, Any]:
    """Validate V2 and materialize its explicit overlay over preserved V1."""

    _require(overlay.get("contract_id") == CONTRACT_ID_V2, "unexpected contract id")
    _require(
        overlay.get("status")
        == "prospectively_refrozen_after_v1_normalization_review_before_v2_candidate_results",
        "analysis contract is not prospectively refrozen",
    )
    claimed = overlay.get("contract_sha256")
    unsigned = {key: item for key, item in overlay.items() if key != "contract_sha256"}
    _require(
        isinstance(claimed, str) and claimed == canonical_sha256(unsigned),
        "analysis contract semantic identity differs",
    )
    base_name = overlay.get("base_contract_path")
    _require(
        isinstance(base_name, str)
        and Path(base_name).name == base_name
        and base_name == "analysis_contract_v1.json",
        "V2 base contract path is not the preserved V1 sibling",
    )
    base_path = path.parent / base_name
    base = _load_v1(json.loads(base_path.read_text(encoding="utf-8")))
    _require(
        base["contract_sha256"] == overlay.get("base_contract_sha256"),
        "V2 base contract semantic identity differs",
    )

    value = deepcopy(base)
    value.update(
        {
            "schema_version": 2,
            "contract_id": CONTRACT_ID_V2,
            "status": overlay["status"],
            "contract_sha256": claimed,
            "base_contract_sha256": overlay["base_contract_sha256"],
            "supersedes": overlay["supersedes"],
            "normalization_v2": overlay["normalization_v2"],
            "environment_analysis_v2": overlay["environment_analysis_v2"],
            "counterfactual_v2": overlay["counterfactual_v2"],
            "outputs_v2": overlay["outputs_v2"],
        }
    )
    overlays = overlay.get("source_overlays")
    _require(isinstance(overlays, dict), "V2 source overlays missing")
    for source in value["sources"]:
        source_id = source["source_id"]
        source_overlay = overlays.get(source_id)
        _require(isinstance(source_overlay, dict), f"V2 source overlay missing: {source_id}")
        source["count_source_domain"] = source_overlay["count_source_domain"]
        additions = source_overlay.get("additional_consumed_files", {})
        _require(isinstance(additions, dict), "malformed additional consumed-file ledger")
        source["consumed_files"].update(additions)

    value["selected_frequency_analysis"] = {
        **value["selected_frequency_analysis"],
        **overlay["normalization_v2"]["selected_frequency"],
        "estimator_id": overlay["normalization_v2"]["selected_frequency"][
            "estimator_version"
        ],
    }
    value["environment_analysis"] = {
        **value["environment_analysis"],
        **overlay["environment_analysis_v2"],
    }
    return value


def load_analysis_contract(path: Path) -> dict[str, Any]:
    """Load a frozen contract, preserving V1 while defaulting new work to V2."""

    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), "analysis contract root must be an object")
    if value.get("schema_version") == 1:
        return _load_v1(value)
    if value.get("schema_version") == 2:
        return _load_v2(path, value)
    raise ValueError("unsupported contract schema")


def validate_output_location(output: Path, source_roots: list[Path]) -> Path:
    """Require a new derived tree outside all immutable source packages."""

    resolved = output.expanduser().resolve()
    for source in source_roots:
        root = source.expanduser().resolve()
        if resolved == root or root in resolved.parents:
            raise ValueError(f"derived output is below immutable source: {root}")
    if resolved.exists() and any(resolved.iterdir()):
        raise ValueError("derived output must be new or empty")
    return resolved
