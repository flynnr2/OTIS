from __future__ import annotations

from pathlib import Path

from host.otis_tools import d9_d6_frequency_only_endurance as endurance
from host.otis_tools import d9_d6_frequency_only_reanalyze as reanalyze


def test_derive_corrected_state_binds_late_application_to_exact_preview(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "source"
    (run_dir / "csv").mkdir(parents=True)
    state = {
        "terminal": {
            "result": "incomplete",
            "reason": "frequency_only_d9_d6_digital_endurance_incomplete",
            "incomplete_reason": "application_opportunity_identity_mismatch",
        },
        "target_reached": True,
        "automatic_applications": 1,
        "control_opportunity_count": 1,
        "eligible_control_opportunity_count": 0,
        "pending_control_opportunity_sequences": [],
        "lost_opportunity_dispositions": {"ineligible_not_authorized": 1},
    }
    endurance._write_new(run_dir / endurance.SUPERVISOR_STATE_PATH, state)
    control = {
        "control_seq": "4",
        "decision_id": "fixture:4",
        "decision_timestamp_ticks": "64000000",
        "time_domain": "rp2040_timer0",
        "control_state": "ACTIVE",
        "preview_eligibility": "true",
        "limited_delta_codes": "21",
        "preview_available": "true",
        "actuation_authorized": "false",
        "actionable": "false",
        "decision_reason_code": "actionable",
    }
    endurance._write_csv_rows(
        run_dir / "csv" / endurance.CONTROL_PREVIEWS_CSV,
        list(control),
        [control],
    )
    endurance._append_opportunity_event(
        run_dir / endurance.OPPORTUNITY_CAUSAL_LEDGER_PATH,
        {
            "event": "opportunity_observed",
            "control_sequence": 4,
            "control_identity_sha256": endurance.canonical_sha256(control),
            "decision_id": "fixture:4",
            "decision_timestamp_ticks": "64000000",
            "time_domain": "rp2040_timer0",
            "eligible_control_opportunity": False,
            "limited_delta_codes": 21,
            "resolved": True,
            "disposition": "ineligible_not_authorized",
            "resolution_evidence": "control_previews_v1.authority_flags",
            "resolution_transaction_record_sequence": None,
            "resolution_reason": None,
        },
    )
    application = {
        field: "" for field in endurance.ACTIVE_TRANSACTION_V1_FIELDS
    }
    application.update(
        {
            "transaction_record_sequence": "4",
            "event": "application",
            "decision_sequence": "4",
            "request_sequence": "1",
            "dac_epoch": "2",
            "applied_code": str(0xA81D),
            "requested_delta_codes": "21",
        }
    )
    endurance._write_csv_rows(
        run_dir / endurance.ACTIVE_CSV,
        endurance.ACTIVE_TRANSACTION_V1_FIELDS,
        [application],
    )

    corrected, evidence = reanalyze._derive_corrected_state(run_dir)

    assert corrected["terminal"] == state["terminal"]
    assert corrected["eligible_control_opportunity_count"] == 1
    assert corrected["lost_opportunity_dispositions"] == {"applied": 1}
    assert corrected["endpoint_incomplete_reason"] is None
    assert evidence["reclassified_application_count"] == 1
    assert evidence["reclassified_applications"] == [
        {
            "control_sequence": 4,
            "control_identity_sha256": endurance.canonical_sha256(control),
            "transaction_record_sequence": 4,
            "request_sequence": 1,
            "dac_epoch": 2,
            "applied_code": 0xA81D,
            "requested_delta_codes": 21,
        }
    ]
    assert evidence["criterion_changed"] is False
    assert evidence["raw_evidence_unchanged"] is True
