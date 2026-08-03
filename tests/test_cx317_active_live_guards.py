from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
MATRIX = ROOT / "firmware/arduino/firmware_matrix.json"


def _hash(relative: str) -> str:
    return sha256((ROOT / relative).read_bytes()).hexdigest()


def test_live_firmware_embeds_every_exact_frozen_identity() -> None:
    policy_path = "profiles/discipline/cx317_bounded_active_v1.json"
    policy = json.loads((ROOT / policy_path).read_text(encoding="utf-8"))
    source = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    bindings = policy["bindings"]

    assert _hash(policy_path) in source
    assert bindings["plant_model_sha256"] in source
    assert bindings["selected_estimator_sha256"] in source
    assert bindings["numerical_preview_policy_sha256"] in source
    assert bindings["response_policy_sha256"] in source
    assert 'OTIS_BUILD_SOURCE_SHA256 ":" OTIS_BUILD_CONFIG_SHA256' in source
    assert "const char *run_identity" in (
        FIRMWARE / "otis_cx317_active_transaction.h"
    ).read_text(encoding="utf-8")


def test_only_actuator_owner_has_controller_to_dac_call_and_no_retry() -> None:
    owner = (FIRMWARE / "otis_cx317_active_actuator.cpp").read_text(
        encoding="utf-8"
    )
    active = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    preview = (FIRMWARE / "otis_cx317_preview_live.cpp").read_text(
        encoding="utf-8"
    )

    assert owner.count("otis_dac_ad5693r_set_raw(") == 1
    assert "otis_dac_ad5693r_set_raw(" not in active
    assert "otis_dac_ad5693r_set_raw(" not in preview
    assert owner.count("otis_cx317_active_actuator_apply_once") == 1
    assert "for (" not in owner and "while (" not in owner
    assert "automatic_restore" not in owner
    assert "retry" not in owner.lower()
    assert '"automatic_retry", "false"' in active
    assert '"automatic_restore", "false"' in active


def test_active_commands_cannot_supply_feedback_code_or_actionability() -> None:
    parser = (FIRMWARE / "otis_serial_command.cpp").read_text(encoding="utf-8")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )

    arm_parse = parser[
        parser.index('strncmp(command, "ACTIVE ARM ",') :
        parser.index('strcmp(command, "ACTIVE ABORT")')
    ]
    assert "parse_u16_code" not in arm_parse
    assert "actionable" not in arm_parse.lower()
    assert "values[3]" in sketch
    assert "otis_cx317_active_live_arm(values[0], values[1], values[2]" in sketch
    assert "requested_code" not in sketch[
        sketch.index("OtisSerialCommandKind::ActiveArm") :
        sketch.index("OtisSerialCommandKind::ActiveAbort")
    ]


def test_manual_path_is_exact_start_once_and_faults_other_active_commands() -> None:
    live = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(encoding="utf-8")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )

    assert "code == OTIS_CX317_ACTIVE_START_CODE" in live
    assert "!manual_start_confirmed" in live
    handler = sketch[
        sketch.index("void handle_dac_set") :
        sketch.index("#if OTIS_ENABLE_H1_DAC_SWEEP", sketch.index("void handle_dac_set"))
    ]
    assert handler.index("otis_cx317_active_live_manual_start_allowed") < handler.index(
        "otis_dac_ad5693r_set_raw"
    )
    assert 'otis_cx317_active_live_abort("nonprogramme_manual_dac_command")' in handler


def test_every_authority_gate_reaches_both_arm_and_request() -> None:
    transaction = (FIRMWARE / "otis_cx317_active_transaction.cpp").read_text(
        encoding="utf-8"
    )
    live = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    fields = [
        "gnss_metadata_valid",
        "gnss_identity_stable",
        "gnss_3d_evidence",
        "raw_pps_valid",
        "count_valid",
        "estimator_valid",
        "model_applicable",
        "temperature_valid",
        "applied_code_confirmed",
        "capture_owner_live",
        "abort_path_live",
        "transaction_evidence_available",
    ]
    eligibility = transaction[
        transaction.index("bool otis_cx317_active_eligibility_valid") :
        transaction.index("void otis_cx317_active_fault")
    ]
    for field in fields:
        assert f"value->{field}" in eligibility
    assert transaction.count("otis_cx317_active_eligibility_valid(eligibility)") == 2
    assert "latest_health.applied_code == transaction.applied_code" in live


def test_status_formatting_cannot_mutate_controller_state() -> None:
    source = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    emitter = source[
        source.index("void otis_cx317_active_live_emit_status") :
        source.index("const char *otis_cx317_active_live_run_identity")
    ]

    assert not re.search(r"transaction\.[A-Za-z_]+\s*=(?!=)", emitter)
    assert "otis_cx317_active_arm" not in emitter
    assert "otis_cx317_active_make_request" not in emitter
    assert "otis_cx317_active_actuator_apply_once" not in emitter


def test_all_supported_nonprogramme_profiles_compile_active_out() -> None:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    for profile in matrix["profiles"]:
        if profile["expect"] != "pass":
            continue
        enabled = profile["defines"].get(
            "OTIS_ENABLE_CX317_BOUNDED_ACTIVE", "0"
        )
        if profile["id"] in {
            "cx317_bounded_active_campaign_a",
            "cx317_bounded_active_campaign_b",
        }:
            assert enabled == "1"
        else:
            assert enabled == "0"
