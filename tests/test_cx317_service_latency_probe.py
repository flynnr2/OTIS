from __future__ import annotations

from pathlib import Path

import pytest

from host.otis_tools.cx317_service_latency_probe import (
    derive_ack_deadline,
    matching_status_count,
)


def test_derive_ack_deadline_uses_measured_maximum_plus_one_pps_interval() -> None:
    result = derive_ack_deadline(0.125)
    assert result["margin_s"] == 1.0
    assert result["proposed_ack_deadline_s"] == pytest.approx(1.125)
    assert result["source_hierarchy"] == "2,4"


def test_matching_status_count_uses_dac_applied_code_known_rows(tmp_path: Path) -> None:
    path = tmp_path / "health.csv"
    path.write_text(
        "record_type,schema_version,status_seq,timestamp_ticks,status_domain,component,status_key,status_value,severity,flags\n"
        "STS,1,1,1,rp2040_timer0,dac,applied_code_known,false,WARN,0\n"
        "STS,1,2,2,rp2040_timer0,dac,last_write_ok,false,WARN,0\n"
        "STS,1,3,3,rp2040_timer0,dac,applied_code_known,false,WARN,0\n",
        encoding="utf-8",
    )
    assert matching_status_count(path) == 2


@pytest.mark.parametrize("value", [-1.0, float("inf"), float("nan")])
def test_derive_ack_deadline_rejects_invalid_measurement(value: float) -> None:
    with pytest.raises(ValueError):
        derive_ack_deadline(value)
