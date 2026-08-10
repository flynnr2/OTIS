from __future__ import annotations

import csv
from hashlib import sha256
import io
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


@pytest.fixture(scope="session")
def stage5_engine_harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    output = tmp_path_factory.mktemp("cx318_stage5_engine") / "engine"
    defines = [
        "OTIS_ENABLE_CX318_STAGE5_PREVIEW=1",
        "OTIS_CX318_STAGE5_INITIAL_CODE=0xA828u",
        "OTIS_CX318_STAGE5_INITIAL_DAC_EPOCH=0u",
        "OTIS_ENABLE_CX317_I_ONLY_PREVIEW=1",
        "OTIS_ENABLE_CX317_BOUNDED_ACTIVE=1",
        "OTIS_ENABLE_DUAL_CORE_PARTITION=1",
        "OTIS_ENABLE_DAC_AD5693R=1",
        "OTIS_DAC_MIN_CODE=0xA800u",
        "OTIS_DAC_MAX_CODE=0xAB00u",
        "OTIS_ENABLE_GNSS_RECEIVER=1",
        "OTIS_GNSS_UART_TX_ENABLED=0",
        "OTIS_ENABLE_ENV_SENSORS=1",
        "OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED=1",
        "OTIS_TCXO_COUNTER_BACKEND=OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO",
        "OTIS_CX317_ACTIVE_CAMPAIGN=OTIS_CX317_ACTIVE_CAMPAIGN_CX318_STAGE5_LOWER",
        "OTIS_CX317_ACTIVE_START_CODE=0xA808u",
        "OTIS_CX317_ACTIVE_CORRECTION_LIMIT=4u",
        "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES=84u",
    ]
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            *(f"-D{define}" for define in defines),
            str(ROOT / "tests/cpp/cx318_stage5_i_only_engine_harness.cpp"),
            str(FIRMWARE / "otis_cx317_i_only_engine.cpp"),
            str(FIRMWARE / "otis_cx318_stage5_tight_deadband.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(output),
        ],
        check=True,
        cwd=ROOT,
    )
    return output


def _rows(harness: Path) -> dict[str, dict[str, str]]:
    completed = subprocess.run(
        [str(harness)], check=True, text=True, capture_output=True, cwd=ROOT
    )
    return {
        row["label"]: row
        for row in csv.DictReader(io.StringIO(completed.stdout))
    }


def test_stage5_firmware_uses_persistent_integer_band_not_v2_float_gate(
    stage5_engine_harness: Path,
) -> None:
    rows = _rows(stage5_engine_harness)
    assert rows["entry_1"]["tight_reason"] == "tight_entry_pending"
    assert rows["entry_1"]["preview_available"] == "1"
    assert rows["entry_1"]["controller_eligible"] == "0"
    assert rows["entry_2"]["state_after"] == "TIGHT_INSIDE"
    assert rows["inside_3"]["state_after"] == "TIGHT_INSIDE"
    assert rows["release_1"]["tight_reason"] == "loose_release_pending"
    assert rows["release_2"]["state_after"] == "OUTSIDE"
    assert rows["release_2"]["controller_eligible"] == "1"
    # Four counts is outside and uses the I-only controller, rather than the
    # historical symmetric V2 hold.
    assert int(rows["release_2"]["limited_delta_codes"]) > 0


def test_stage5_epoch_enforces_applied_cadence_and_requalifies(
    stage5_engine_harness: Path,
) -> None:
    rows = _rows(stage5_engine_harness)
    assert rows["epoch_cadence"]["reason"] == "decision_cadence_hold"
    assert rows["epoch_cadence"]["preview_available"] == "0"
    assert rows["epoch_cadence"]["requalified"] == "1"
    assert rows["epoch_cadence"]["state_before"] == "OUTSIDE"
    assert rows["epoch_eligible"]["preview_available"] == "1"
    assert rows["epoch_eligible"]["tight_reason"] == "three_count_outside_hold"
    assert rows["session_entry_1"]["requalified"] == "1"
    assert rows["session_entry_1"]["entry_pending"] == "1"
    assert rows["session_entry_2"]["state_after"] == "TIGHT_INSIDE"


def test_stage5_firmware_binds_policy_and_keeps_phase_preview_one_way() -> None:
    policy = ROOT / "profiles/discipline/cx318_stage5_tight_active_v1.json"
    policy_hash = sha256(policy.read_bytes()).hexdigest()
    active = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(encoding="utf-8")
    preview = (FIRMWARE / "otis_cx317_preview_live.cpp").read_text(encoding="utf-8")
    cx318 = (FIRMWARE / "otis_cx318_preview_live.cpp").read_text(encoding="utf-8")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(encoding="utf-8")

    assert policy_hash in active
    assert policy_hash in preview
    assert "cx318_stage5_tight_lower:3185001" in active
    assert "cx318_stage5_tight_upper:3185002" in active
    decision = preview[
        preview.index("OtisCx317ActiveLiveDecision active_decision") :
        preview.index("otis_cx317_active_live_on_decision", preview.index("OtisCx317ActiveLiveDecision active_decision"))
    ]
    assert "frequency_error_hz" in decision
    assert "tight_deadband.frequency_controller_eligible" in decision
    assert "phase" not in decision.lower()
    assert "hybrid" not in decision.lower()
    assert "otis_dac_ad5693r_set_raw" not in cx318
    assert "otis_cx317_active_live_on_decision" not in cx318
    assert "otis_cx318_preview_live_update_applied_code" in sketch


def test_stage5_setup_opens_epoch_and_rehearsal_seed_cannot_arm() -> None:
    active = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(encoding="utf-8")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(encoding="utf-8")
    manual = active[
        active.index("bool otis_cx317_active_live_manual_start_allowed") :
        active.index("void otis_cx317_active_live_on_decision")
    ]
    static_context = sketch[
        sketch.index("OtisCx317StaticCodeState cx317_static_code_state") :
        sketch.index("void service_cx317_active_health")
    ]

    assert "transaction_bound" in manual
    assert "transaction.dac_epoch = 1u" in manual
    assert "transaction.last_application_s = now_s" in manual
    assert "transaction.have_last_application = true" in manual
    assert "OTIS_CX318_STAGE5_INITIAL_CODE" in static_context
    # The seed is returned only to the preview input.  Active health still reads
    # dual_core_static_code directly and therefore remains unconfirmed/unarmable.
    health = sketch[
        sketch.index("void service_cx317_active_health") :
        sketch.index(
            "const char *edge_string",
            sketch.index("void service_cx317_active_health"),
        )
    ]
    assert "dual_core_static_code.available" in health
    assert "OTIS_CX318_STAGE5_INITIAL_CODE" not in health


def test_stage5_tdb_wire_contract_explicitly_serializes_zero_authority() -> None:
    preview = (FIRMWARE / "otis_cx317_preview_live.cpp").read_text(encoding="utf-8")
    assert "integer_edge_error_counts,absolute_edge_error_counts" in preview
    assert "frequency_controller_eligible,requalified,requalification_reason" in preview
    assert "historical_v2_inside,symmetric_two_count_inside" in preview
    assert "false,false,false,%s" in preview
