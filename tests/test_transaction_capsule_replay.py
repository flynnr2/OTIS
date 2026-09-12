"""Retained record, durable capsule, and owner acknowledgement are separate facts."""
import json
from host.otis_tools.adaptive_hybrid_replay import replay_transaction_capsules


def test_response_capsule_alone_does_not_prove_owner_acknowledgement(tmp_path):
    row = {"event": "response", "request_sequence": "2", "transaction_record_sequence": "9"}
    capsule = tmp_path / "reports/step_002/record_000009_response.json"
    capsule.parent.mkdir(parents=True)
    capsule.write_text(json.dumps(row))
    state = {"acknowledged_record_sequences": []}
    observed = replay_transaction_capsules(tmp_path, [row], [], state)
    assert not observed["exact"]
    assert any("ACT record 9: phase 4 acknowledgement" in error for error in observed["errors"])
    assert any("owner acknowledged ACT frontier" in error for error in observed["errors"])
    events = [{"event": "transaction_phase_acknowledged", "record_sequence": 9, "phase": 4}]
    state["acknowledged_record_sequences"] = [9]
    confirmed = replay_transaction_capsules(tmp_path, [row], events, state)
    assert confirmed["exact"] and confirmed["errors"] == []
