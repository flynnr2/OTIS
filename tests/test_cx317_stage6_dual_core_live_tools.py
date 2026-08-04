from __future__ import annotations

import json
from pathlib import Path

from host.otis_tools.cx317_stage6_dual_core_analyze import (
    EXPECTED_BUILD_MANIFEST,
    EXPECTED_COMMIT,
    EXPECTED_CONFIG,
    EXPECTED_SOURCE,
    EXPECTED_UF2,
)
from host.otis_tools.cx317_stage6_dual_core_supervisor import (
    EXPECTED_CODE,
    EXPECTED_LIVE_IDENTITY,
    _exact_live_identity,
    _exact_state_ack,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "profiles/run_templates/cx317_dual_core_post_campaign_preview_v1/manifest.json"


def test_stage6_live_manifest_is_exact_non_actionable_contract() -> None:
    value = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    firmware = value["firmware"]
    assert value["template"] is True
    assert value["stage"] == "CX317_DUAL_CORE_POST_CAMPAIGN_PREVIEW"
    assert firmware["git_commit"] == EXPECTED_COMMIT
    assert firmware["source_state"] == "clean"
    assert firmware["source_sha256"] == EXPECTED_SOURCE
    assert firmware["configuration_sha256"] == EXPECTED_CONFIG
    assert firmware["build_manifest_sha256"] == EXPECTED_BUILD_MANIFEST
    assert firmware["uf2_sha256"] == EXPECTED_UF2
    assert value["host"]["firmware_build_parent"] == EXPECTED_COMMIT
    assert EXPECTED_LIVE_IDENTITY[("firmware", "git_commit")] == EXPECTED_COMMIT
    assert EXPECTED_LIVE_IDENTITY[("firmware", "source_hash")] == EXPECTED_SOURCE
    assert EXPECTED_LIVE_IDENTITY[("firmware", "config_hash")] == EXPECTED_CONFIG
    assert value["controller_preview"]["active_live_update_codes"] == 0
    assert value["actionable"] is False
    assert value["actuation_authorized"] is False
    schedule = value["controller_preview"]["mechanism_schedule_after_state_ack_s"]
    assert schedule == {
        "service_load_start": 2500,
        "service_load_requests": 60,
        "service_load_period_s": 1,
        "controlled_gnss_invalidation": 2700,
        "explicit_recovery": 2720,
        "final_status_query": 4650,
    }


def test_state_ack_requires_one_exact_idempotent_a82a_row(tmp_path: Path) -> None:
    path = tmp_path / "dac_steps.csv"
    path.write_text(
        "record_type,schema_version,dac_seq,dac_id,timestamp_ticks,time_domain,event,dac_code_requested,dac_code_applied,dac_code_clamped,settle_time_s,temperature_c,temperature_source,flags\n"
        f"DAC,1,1,dac:1,1,rp2040_timer0,manual_apply,{EXPECTED_CODE},{EXPECTED_CODE},0,0,,,0\n",
        encoding="utf-8",
    )
    assert _exact_state_ack(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"DAC,1,2,dac:2,2,rp2040_timer0,manual_apply,{EXPECTED_CODE},{EXPECTED_CODE},0,0,,,0\n")
    assert not _exact_state_ack(path)


def test_preflight_requires_exact_firmware_build_and_gnss_identity(tmp_path: Path) -> None:
    path = tmp_path / "health.csv"
    header = "record_type,schema_version,status_seq,timestamp_ticks,time_domain,component,status_key,status_value,severity,flags\n"
    rows = [
        f"STS,1,{index},{index},rp2040_timer0,{component},{key},{value},info,0"
        for index, ((component, key), value) in enumerate(EXPECTED_LIVE_IDENTITY.items())
    ]
    rows.append(
        f"STS,1,{len(rows)},{len(rows)},rp2040_timer0,pps_d14,accepted_pps_count,1,info,0"
    )
    path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
    assert _exact_live_identity(path)
    path.write_text(header + "\n".join(rows[:-1]) + "\n", encoding="utf-8")
    assert not _exact_live_identity(path)


def test_stage6_supervisor_has_only_one_predetermined_dac_command() -> None:
    source = (ROOT / "host/otis_tools/cx317_stage6_dual_core_supervisor.py").read_text(encoding="utf-8")
    assert source.count('send_command_to_fifo(command_fifo, f"DAC SET') == 1
    assert "ACTIVE ARM" not in source
    assert "ACTIVE LEASE" not in source
    assert "automatic restore" not in source.lower()
