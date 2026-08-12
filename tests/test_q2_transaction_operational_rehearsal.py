from host.otis_tools.q2_transaction_operational_rehearsal import (
    run_operational_rehearsal,
)


def test_q2_actual_analyzer_seal_and_registration_path(tmp_path) -> None:
    result = run_operational_rehearsal(tmp_path)
    assert result["status"] == "pass"
    assert result["all_checks_passed"] is True
    assert len(result["seal_sha256"]) == 64
    assert len(result["registered_content_sha256"]) == 64
