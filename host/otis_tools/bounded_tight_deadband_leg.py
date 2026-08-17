"""Exact identities for the matched CX319 lower and upper live legs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .programme_status import (
    BOUNDED_TIGHT_DEADBAND_LIVE_LEG,
    BOUNDED_TIGHT_DEADBAND_UPPER_LIVE_LEG,
)


@dataclass(frozen=True)
class BoundedTightDeadbandLeg:
    gate: str
    leg: str
    profile_id: str
    run_binding_tag: int
    setup_code: int
    required_sign: int
    required_direction: str
    operation: str
    outcome_contract_id: str
    stage: str
    control_mode: str
    proposal_tool: str
    proposal_bundle_id: str
    proposal_filename: Path
    activation_tool: str
    activation_id: str
    activation_filename: Path
    live_seal_filename: Path
    rehearsal_tool: str
    rehearsal_analyzer_tool: str
    rehearsal_seal_type: str
    prerequisite_key: str
    firmware_flash: bool
    flash_record_filename: Path | None
    correction_limit: int = 4
    cumulative_limit_codes: int = 84
    maximum_step_codes: int = 21
    minimum_cadence_s: int = 1800
    maximum_qualified_duration_s: int = 14400
    programme_id: str = "cx319_stabilized_tight_deadband"

    @property
    def run_identity(self) -> str:
        return f"{self.profile_id}:{self.run_binding_tag}"

    @property
    def setup_code_hex(self) -> str:
        return f"0x{self.setup_code:04X}"

    @property
    def prefix(self) -> str:
        return f"cx319_{self.gate.lower()}"


LOWER = BoundedTightDeadbandLeg(
    gate="G2",
    leg="A",
    profile_id="cx319_tight_lower",
    run_binding_tag=3195001,
    setup_code=0xA808,
    required_sign=1,
    required_direction="positive",
    operation=BOUNDED_TIGHT_DEADBAND_LIVE_LEG,
    outcome_contract_id="cx319_g2_leg_a_outcome_contract_v2",
    stage="CX319_G2_LEG_A_FREQUENCY_ONLY_LIVE",
    control_mode="cx319_g2_leg_a_frequency_only_live",
    proposal_tool="cx319_g2_proposal_bundle_v1",
    proposal_bundle_id="cx319_g2_leg_a_proposal_bundle_v1",
    proposal_filename=Path("cx319_g2_leg_a_proposal_bundle_v1.json"),
    activation_tool="cx319_g2_live_activation_v1",
    activation_id="cx319_g2_leg_a_live_activation_v1",
    activation_filename=Path("cx319_g2_live_activation_v1.json"),
    live_seal_filename=Path("reports/cx319_g2_live_leg_seal_v1.json"),
    rehearsal_tool="cx319_g2_accelerated_operational_rehearsal_v1",
    rehearsal_analyzer_tool="cx319_g2_accelerated_analyzer_v1",
    rehearsal_seal_type="cx319_g2_accelerated_operational_rehearsal_seal_v1",
    prerequisite_key="g1_pass",
    firmware_flash=False,
    flash_record_filename=None,
)

UPPER = BoundedTightDeadbandLeg(
    gate="G3",
    leg="B",
    profile_id="cx319_tight_upper",
    run_binding_tag=3195002,
    setup_code=0xA848,
    required_sign=-1,
    required_direction="negative",
    operation=BOUNDED_TIGHT_DEADBAND_UPPER_LIVE_LEG,
    outcome_contract_id="cx319_g3_leg_b_outcome_contract_v1",
    stage="CX319_G3_LEG_B_FREQUENCY_ONLY_LIVE",
    control_mode="cx319_g3_leg_b_frequency_only_live",
    proposal_tool="cx319_g3_proposal_bundle_v1",
    proposal_bundle_id="cx319_g3_leg_b_proposal_bundle_v1",
    proposal_filename=Path("cx319_g3_leg_b_proposal_bundle_v1.json"),
    activation_tool="cx319_g3_live_activation_v1",
    activation_id="cx319_g3_leg_b_live_activation_v1",
    activation_filename=Path("cx319_g3_live_activation_v1.json"),
    live_seal_filename=Path("reports/cx319_g3_live_leg_seal_v1.json"),
    rehearsal_tool="cx319_g3_accelerated_operational_rehearsal_v1",
    rehearsal_analyzer_tool="cx319_g3_accelerated_analyzer_v1",
    rehearsal_seal_type="cx319_g3_accelerated_operational_rehearsal_seal_v1",
    prerequisite_key="g2_pass",
    firmware_flash=True,
    flash_record_filename=Path("reports/cx319_g3_flash_record_v1.json"),
)

RANGE_LOWER = BoundedTightDeadbandLeg(
    gate="PBL",
    leg="L",
    profile_id="cx319_range_part_b_lower",
    run_binding_tag=3196001,
    setup_code=0xA800,
    required_sign=1,
    required_direction="positive",
    operation="conditional_part_b_frequency_only_leg",
    outcome_contract_id="cx319_conditional_part_b_leg_outcome_v1",
    stage="CX319_CONDITIONAL_PART_B_LOWER_FREQUENCY_ONLY_LIVE",
    control_mode="cx319_conditional_part_b_lower_frequency_only_live",
    proposal_tool="cx319_conditional_part_b_proposal_v1",
    proposal_bundle_id="cx319_conditional_part_b_lower_proposal_v1",
    proposal_filename=Path("cx319_conditional_part_b_lower_proposal_v1.json"),
    activation_tool="cx319_conditional_part_b_activation_v1",
    activation_id="cx319_conditional_part_b_lower_activation_v1",
    activation_filename=Path("cx319_conditional_part_b_lower_activation_v1.json"),
    live_seal_filename=Path("reports/cx319_conditional_part_b_lower_seal_v1.json"),
    rehearsal_tool="cx319_conditional_part_b_operational_rehearsal_v1",
    rehearsal_analyzer_tool="cx319_conditional_part_b_rehearsal_analyzer_v1",
    rehearsal_seal_type="cx319_conditional_part_b_rehearsal_seal_v1",
    prerequisite_key="part_a_readiness",
    firmware_flash=True,
    flash_record_filename=Path("reports/cx319_pbl_flash_record_v1.json"),
    correction_limit=9,
    cumulative_limit_codes=189,
    programme_id="CX319_MAPPING_INFORMED_FREQUENCY_TRAVERSAL_V4",
)

RANGE_UPPER = BoundedTightDeadbandLeg(
    gate="PBU",
    leg="U",
    profile_id="cx319_range_part_b_upper",
    run_binding_tag=3196002,
    setup_code=0xA890,
    required_sign=-1,
    required_direction="negative",
    operation="conditional_part_b_frequency_only_leg",
    outcome_contract_id="cx319_conditional_part_b_leg_outcome_v1",
    stage="CX319_CONDITIONAL_PART_B_UPPER_FREQUENCY_ONLY_LIVE",
    control_mode="cx319_conditional_part_b_upper_frequency_only_live",
    proposal_tool="cx319_conditional_part_b_proposal_v1",
    proposal_bundle_id="cx319_conditional_part_b_upper_proposal_v1",
    proposal_filename=Path("cx319_conditional_part_b_upper_proposal_v1.json"),
    activation_tool="cx319_conditional_part_b_activation_v1",
    activation_id="cx319_conditional_part_b_upper_activation_v1",
    activation_filename=Path("cx319_conditional_part_b_upper_activation_v1.json"),
    live_seal_filename=Path("reports/cx319_conditional_part_b_upper_seal_v1.json"),
    rehearsal_tool="cx319_conditional_part_b_operational_rehearsal_v1",
    rehearsal_analyzer_tool="cx319_conditional_part_b_rehearsal_analyzer_v1",
    rehearsal_seal_type="cx319_conditional_part_b_rehearsal_seal_v1",
    prerequisite_key="part_a_readiness",
    firmware_flash=True,
    flash_record_filename=Path("reports/cx319_pbu_flash_record_v1.json"),
    correction_limit=9,
    cumulative_limit_codes=189,
    programme_id="CX319_MAPPING_INFORMED_FREQUENCY_TRAVERSAL_V4",
)


def leg_for(gate: object, leg: object) -> BoundedTightDeadbandLeg:
    try:
        return {
            (LOWER.gate, LOWER.leg): LOWER,
            (UPPER.gate, UPPER.leg): UPPER,
            (RANGE_LOWER.gate, RANGE_LOWER.leg): RANGE_LOWER,
            (RANGE_UPPER.gate, RANGE_UPPER.leg): RANGE_UPPER,
        }[(gate, leg)]
    except KeyError as exc:
        raise ValueError(f"unsupported CX319 bounded live leg: gate={gate!r}, leg={leg!r}") from exc


def leg_for_proposal(proposal: dict[str, object]) -> BoundedTightDeadbandLeg:
    return leg_for(proposal.get("gate"), proposal.get("leg"))


def leg_for_manifest(manifest: dict[str, object]) -> BoundedTightDeadbandLeg:
    cx319 = manifest.get("cx319")
    if not isinstance(cx319, dict):
        raise ValueError("CX319 live manifest is missing its exact leg identity")
    return leg_for(cx319.get("gate"), cx319.get("leg"))
