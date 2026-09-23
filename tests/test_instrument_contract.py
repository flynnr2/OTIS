from __future__ import annotations

from host.otis_tools.contracts import CONTRACT_FIELDS
from host.otis_tools.firmware_host_contract import RECORD_FIELDS, RECORD_TYPE_TO_CONTRACT
from host.otis_tools.record_splitter import RECORD_CONTRACTS
from host.otis_tools.time_domains import TIME_DOMAINS, forward_progress


def test_current_reader_contains_instrument_evidence_and_excludes_retired_control() -> None:
    required = {"ICM", "IWR", "IAP", "IDC", "IRS", "IST"}
    assert required <= RECORD_CONTRACTS.keys()
    assert {"ACT", "AHY", "AHM"}.isdisjoint(RECORD_CONTRACTS)
    for tag in required:
        contract = RECORD_TYPE_TO_CONTRACT[tag]
        assert CONTRACT_FIELDS[contract] == list(RECORD_FIELDS[contract])
        assert CONTRACT_FIELDS[contract][2] == "record_sequence"


def test_instrument_tick_domain_is_strict_nonwrapping() -> None:
    domain = TIME_DOMAINS["rp2040_timer_us64"]
    assert domain.nominal_hz == 1_000_000
    assert not domain.permits_rollover
    assert forward_progress(10, 9, domain="rp2040_timer_us64").valid is False
