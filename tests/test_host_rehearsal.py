from __future__ import annotations

import json

from run_spec_fixtures import build_synthetic_spec

from host.otis_tools.adaptive_hybrid_contract import INHIBITED_ZERO_WRITE
from host.otis_tools.run_spec import required_rehearsal_boundaries
from tools import rehearse_host
from tools.rehearse_host import (
    _owner_metadata_hold_requalified,
    _owner_second_response_confirmed,
    _owner_setup_arm_acknowledged,
    _owner_startup_precedes_authority,
)


def _events(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_abort_gate_requires_second_response_ack_and_first_dependent_consumer(tmp_path):
    events = tmp_path / "reports/adaptive_hybrid_supervisor_events.jsonl"
    _events(events, [{"event": "transaction_phase_acknowledged", "request_sequence": 2, "record_sequence": 8}])
    assert not _owner_second_response_confirmed(tmp_path)
    _events(events, [
        {"event": "transaction_phase_acknowledged", "request_sequence": 2, "record_sequence": 9},
        {"event": "response_classified", "request_sequence": 1},
    ])
    assert not _owner_second_response_confirmed(tmp_path)
    _events(events, [
        {"event": "transaction_phase_acknowledged", "request_sequence": 2, "record_sequence": 9},
        {"event": "response_classified", "request_sequence": 2},
    ])
    assert _owner_second_response_confirmed(tmp_path)


def test_inhibited_spec_excludes_control_transaction_boundaries(monkeypatch, tmp_path):
    spec = build_synthetic_spec(monkeypatch, tmp_path, purpose=INHIBITED_ZERO_WRITE)
    boundaries = required_rehearsal_boundaries(spec)
    assert "setup_arm_and_acknowledgements_exact" not in boundaries
    assert "two_progressive_transactions_complete" not in boundaries
    assert "metadata_hold_nonterminal_and_requalified" not in boundaries
    assert boundaries == [
        "capture_and_supervisor_processes_ready",
        "startup_census_preceded_control_authority",
        "normal_transport_obstruction_detected",
        "priority_abort_delivered_before_capture_close",
        "capture_closed_and_offline_outcome_recorded",
    ]


def test_public_cli_allows_default_external_receipt(monkeypatch, tmp_path, capsys):
    observed = {}

    def fake_rehearse(**kwargs):
        observed.update(kwargs)
        return {"receipt": "external.json"}

    monkeypatch.setattr(rehearse_host, "rehearse", fake_rehearse)
    assert rehearse_host.main([
        "--spec-path", str(tmp_path / "run_spec.json"),
        "--run-dir", str(tmp_path / "run"),
    ]) == 0
    assert observed["receipt_path"] is None
    assert '"receipt": "external.json"' in capsys.readouterr().out


def test_owner_events_prove_control_sequence_and_metadata_requalification(tmp_path):
    events = tmp_path / "reports/adaptive_hybrid_supervisor_events.jsonl"
    _events(events, [
        {"event": "adaptive_hybrid_regulation_startup_census_established", "authority_admitted": True},
        {"event": "command_submitted", "command": "ACTIVE SETUP 1"},
        {"event": "host_written", "command": "ACTIVE SETUP 1"},
        {"event": "host_written", "command": "ACTIVE ARM 1"},
        *[
            {"event": "transaction_phase_acknowledged", "record_sequence": sequence}
            for sequence in range(2, 6)
        ],
        {"event": "adaptive_hybrid_regulation_gnss_metadata_hold_entered", "d14_d8_measurement_continues": True},
        {"event": "adaptive_hybrid_regulation_gnss_metadata_hold_requalified"},
    ])
    assert _owner_startup_precedes_authority(tmp_path, control_rehearsal=True)
    assert _owner_setup_arm_acknowledged(tmp_path)
    assert _owner_metadata_hold_requalified(tmp_path)


def test_inhibited_owner_event_rejects_control_command(tmp_path):
    events = tmp_path / "reports/adaptive_hybrid_supervisor_events.jsonl"
    _events(events, [
        {"event": "adaptive_hybrid_regulation_startup_census_established", "authority_admitted": True},
        {"event": "command_submitted", "command": "ACTIVE SETUP 1"},
    ])
    assert not _owner_startup_precedes_authority(tmp_path, control_rehearsal=False)
