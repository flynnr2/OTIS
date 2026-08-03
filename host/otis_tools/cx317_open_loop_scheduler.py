"""Fail-closed plan validation and dry-run scheduling for CX317 Stage 5.

This module cannot derive commands from frequency error.  Hardware execution
is deliberately unavailable until a selected estimator binding, measured
deadline slack, and separate physical safety gate are supplied.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import argparse
import json
import math
import tempfile
from typing import Any


PLAN_ID = "CX317_PPS_GATED_OPEN_LOOP_V1"
EXPECTED_PROFILE = "cx317_pps_gated_open_loop"
EXPECTED_BACKEND = "OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO"
EXPECTED_METHOD = "PPS_CUMULATIVE_SNAPSHOT_SPAN_V1"
INITIAL_SEQUENCE_CODES = (
    0xA950,
    0xA850,
    0xA800,
    0xA850,
    0xA950,
    0xAA50,
    0xAB00,
    0xAA50,
    0xA950,
)


@dataclass(frozen=True)
class CampaignStep:
    label: str
    code: int


@dataclass(frozen=True)
class CampaignPlan:
    plan_id: str
    firmware_profile: str
    firmware_configuration_sha256: str
    firmware_uf2_sha256: str
    measurement_backend: str
    estimator_method_id: str
    selected_estimator_config_sha256: str | None
    selected_authoritative_span_s: int | None
    initial_warmup_s: int
    dwell_s: int
    settling_exclusion_s: int
    min_code: int
    max_code: int
    sequence: tuple[CampaignStep, ...]
    final_safe_code: int
    ack_deadline_s: float | None
    deadline_slack_s: float | None
    automatic_restore: bool
    feedback_derived_commands: bool
    hardware_authorized: bool
    amendment_status: str
    provenance: dict[str, str]
    config_hash: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "CampaignPlan":
        expected = {
            "schema_version",
            "plan_id",
            "firmware_profile",
            "firmware_configuration_sha256",
            "firmware_uf2_sha256",
            "measurement_backend",
            "estimator_method_id",
            "selected_estimator_config_sha256",
            "selected_authoritative_span_s",
            "initial_warmup_s",
            "dwell_s",
            "settling_exclusion_s",
            "dac_clamp",
            "sequence",
            "final_safe_code",
            "ack_deadline_s",
            "deadline_slack_s",
            "automatic_restore",
            "feedback_derived_commands",
            "hardware_authorized",
            "amendment_status",
            "provenance",
        }
        if set(value) != expected:
            raise ValueError(
                "campaign plan fields differ; "
                f"missing={sorted(expected - set(value))}, "
                f"extra={sorted(set(value) - expected)}"
            )
        if value["schema_version"] != 1 or value["plan_id"] != PLAN_ID:
            raise ValueError("unsupported campaign plan")
        if value["firmware_profile"] != EXPECTED_PROFILE:
            raise ValueError("campaign requires the dedicated firmware profile")
        firmware_configuration_sha256 = _sha256(
            value["firmware_configuration_sha256"],
            "firmware configuration hash",
        )
        firmware_uf2_sha256 = _sha256(
            value["firmware_uf2_sha256"], "firmware UF2 hash"
        )
        if value["measurement_backend"] != EXPECTED_BACKEND:
            raise ValueError("campaign requires the PPS-gated ratio backend")
        if value["estimator_method_id"] != EXPECTED_METHOD:
            raise ValueError("campaign estimator method mismatch")
        clamp = value["dac_clamp"]
        if not isinstance(clamp, dict) or set(clamp) != {"min_code", "max_code"}:
            raise ValueError("campaign DAC clamp is malformed")
        minimum = _integer(clamp["min_code"], "minimum DAC code")
        maximum = _integer(clamp["max_code"], "maximum DAC code")
        if not 0 <= minimum <= maximum <= 0xFFFF:
            raise ValueError("campaign DAC clamp is outside 16-bit range")
        raw_steps = value["sequence"]
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("campaign sequence must be a non-empty list")
        steps: list[CampaignStep] = []
        for item in raw_steps:
            if not isinstance(item, dict) or set(item) != {"label", "code"}:
                raise ValueError("campaign step fields must be label/code")
            label = str(item["label"]).strip()
            code = _integer(item["code"], "campaign step code")
            if not label or not minimum <= code <= maximum:
                raise ValueError("campaign step is empty or outside the clamp")
            steps.append(CampaignStep(label, code))
        amendment = str(value["amendment_status"])
        codes = tuple(step.code for step in steps)
        if amendment == "none" and codes != INITIAL_SEQUENCE_CODES:
            raise ValueError("unamended plan differs from the Stage 5 initial sequence")
        if amendment == "none" and (minimum, maximum) != (0xA800, 0xAB00):
            raise ValueError("unamended plan differs from the Stage 5 initial clamp")
        if amendment not in {"none", "documented_safety_or_resolution_reason"}:
            raise ValueError("campaign amendment status is invalid")
        warmup = _positive_integer(value["initial_warmup_s"], "initial warmup")
        dwell = _positive_integer(value["dwell_s"], "dwell")
        settling = _positive_integer(value["settling_exclusion_s"], "settling exclusion")
        if settling >= dwell:
            raise ValueError("settling exclusion must leave settled dwell evidence")
        final_safe = _integer(value["final_safe_code"], "final safe code")
        if not minimum <= final_safe <= maximum or steps[-1].code != final_safe:
            raise ValueError("last campaign step must equal the final safe code")
        selected_hash = value["selected_estimator_config_sha256"]
        if selected_hash is not None and (
            not isinstance(selected_hash, str)
            or len(selected_hash) != 64
            or any(character not in "0123456789abcdef" for character in selected_hash)
        ):
            raise ValueError("selected estimator hash must be null or lowercase SHA-256")
        selected_span = value["selected_authoritative_span_s"]
        if selected_span is not None:
            selected_span = _positive_integer(selected_span, "selected span")
            if selected_span > dwell - settling:
                raise ValueError("selected span does not fit the settled dwell support")
        ack_deadline = value["ack_deadline_s"]
        if ack_deadline is not None and (
            isinstance(ack_deadline, bool)
            or not isinstance(ack_deadline, (int, float))
            or not math.isfinite(float(ack_deadline))
            or float(ack_deadline) <= 0
        ):
            raise ValueError("ack deadline must be null or positive finite seconds")
        slack = value["deadline_slack_s"]
        if slack is not None and (
            isinstance(slack, bool)
            or not isinstance(slack, (int, float))
            or not math.isfinite(float(slack))
            or float(slack) <= 0
        ):
            raise ValueError("deadline slack must be null or positive finite seconds")
        provenance = value["provenance"]
        required_provenance = {
            "sequence",
            "warmup",
            "dwell",
            "settling_exclusion",
            "clamp",
            "dac_code_domain",
            "selected_span_fit",
            "final_safe_code",
            "deadline_slack",
            "firmware_binding",
        }
        if (
            not isinstance(provenance, dict)
            or set(provenance) != required_provenance
            or any(not str(item).strip() for item in provenance.values())
        ):
            raise ValueError("campaign numerical provenance is incomplete")
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return cls(
            plan_id=PLAN_ID,
            firmware_profile=EXPECTED_PROFILE,
            firmware_configuration_sha256=firmware_configuration_sha256,
            firmware_uf2_sha256=firmware_uf2_sha256,
            measurement_backend=EXPECTED_BACKEND,
            estimator_method_id=EXPECTED_METHOD,
            selected_estimator_config_sha256=selected_hash,
            selected_authoritative_span_s=selected_span,
            initial_warmup_s=warmup,
            dwell_s=dwell,
            settling_exclusion_s=settling,
            min_code=minimum,
            max_code=maximum,
            sequence=tuple(steps),
            final_safe_code=final_safe,
            ack_deadline_s=(
                float(ack_deadline) if ack_deadline is not None else None
            ),
            deadline_slack_s=float(slack) if slack is not None else None,
            automatic_restore=_false(value["automatic_restore"], "automatic restore"),
            feedback_derived_commands=_false(
                value["feedback_derived_commands"], "feedback-derived commands"
            ),
            hardware_authorized=_false(value["hardware_authorized"], "hardware authorization"),
            amendment_status=amendment,
            provenance={key: str(item) for key, item in provenance.items()},
            config_hash=sha256(canonical.encode("utf-8")).hexdigest(),
        )

    def require_hardware_binding(self) -> None:
        if self.selected_estimator_config_sha256 is None:
            raise ValueError("selected estimator hash is unavailable")
        if self.selected_authoritative_span_s is None:
            raise ValueError("selected authoritative span is unavailable")
        if self.ack_deadline_s is None:
            raise ValueError("scheduler acknowledgement deadline is unavailable")
        if self.deadline_slack_s is None:
            raise ValueError("measured scheduler deadline slack is unavailable")
        if self.hardware_authorized:
            raise ValueError(
                "plan files never self-authorize hardware; use a separate physical safety gate"
            )


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def _positive_integer(value: Any, label: str) -> int:
    result = _integer(value, label)
    if result <= 0:
        raise ValueError(f"{label} must be positive")
    return result


def _sha256(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _false(value: Any, label: str) -> bool:
    if value is not False:
        raise ValueError(f"{label} must remain false")
    return False


def load_plan(path: Path) -> CampaignPlan:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("campaign plan must be a JSON object")
    return CampaignPlan.from_mapping(value)


def dry_run_events(plan: CampaignPlan) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = [
        {"event": "warmup_start", "planned_elapsed_s": 0},
        {
            "event": "warmup_complete",
            "planned_elapsed_s": plan.initial_warmup_s,
        },
    ]
    elapsed = plan.initial_warmup_s
    for index, step in enumerate(plan.sequence):
        events.extend(
            [
                {
                    "event": "transition_request",
                    "step_index": index,
                    "label": step.label,
                    "code": step.code,
                    "planned_elapsed_s": elapsed,
                },
                {
                    "event": "settling_exclusion_complete",
                    "step_index": index,
                    "code": step.code,
                    "planned_elapsed_s": elapsed + plan.settling_exclusion_s,
                },
                {
                    "event": "dwell_complete",
                    "step_index": index,
                    "code": step.code,
                    "planned_elapsed_s": elapsed + plan.dwell_s,
                },
            ]
        )
        elapsed += plan.dwell_s
    events.append(
        {
            "event": "campaign_complete_fail_static",
            "code": plan.final_safe_code,
            "planned_elapsed_s": elapsed,
            "automatic_restore": False,
        }
    )
    return events


def write_dry_run(plan_path: Path, output_path: Path) -> Path:
    plan = load_plan(plan_path)
    result = {
        "schema_version": 1,
        "plan_id": plan.plan_id,
        "plan_config_sha256": plan.config_hash,
        "source_plan": {"path": str(plan_path), "sha256": _sha256_file(plan_path)},
        "hardware_execution": False,
        "feedback_derived_commands": False,
        "events": dry_run_events(plan),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output_path.parent, delete=False
    ) as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(output_path)
    return output_path


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and dry-run the fail-closed CX317 open-loop plan."
    )
    parser.add_argument("plan", type=Path)
    parser.add_argument("--dry-run-output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        output = write_dry_run(args.plan, args.dry_run_output)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
