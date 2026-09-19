"""Actual live mailbox/formatter with a deterministic nonblocking transport."""
import shutil
import subprocess
from pathlib import Path

import pytest

from host.otis_tools.service_latency import decode_reports

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


@pytest.fixture(scope="module")
def live_harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler unavailable")
    executable = tmp_path_factory.mktemp("service_latency_live") / "harness"
    subprocess.run(
        [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror",
         "-fsanitize=undefined,address", "-I", str(FIRMWARE),
         str(ROOT / "tests/cpp/service_latency_live_harness.cpp"),
         str(FIRMWARE / "otis_service_latency.cpp"),
         str(FIRMWARE / "otis_service_latency_live.cpp"), "-o", str(executable)],
        check=True,
    )
    return executable


def _rows(harness: Path, mode: str = "normal") -> list[dict[str, int]]:
    result = subprocess.run([str(harness), mode], check=True, capture_output=True, text=True)
    rows = []
    for line in result.stdout.splitlines():
        assert line.startswith("LAT,")
        row = dict(field.split("=", 1) for field in line.split(",")[1:])
        rows.append({key: int(value) for key, value in row.items()})
    return rows


def test_mailbox_complete_cycle_cadence_and_coherent_identities(live_harness: Path) -> None:
    rows = _rows(live_harness)
    reports = {generation: [r for r in rows if r["g"] == generation]
               for generation in range(1, 21)}
    for generation, report in reports.items():
        assert [r["p"] for r in report] == list(range(7))
        index = (generation - 1) % 10
        assert {(r["c"], r["s"]) for r in report} == {(index % 2 + 1, index // 2)}
        summary, histogram, minimum, maximum, tail0, tail1, noneligible = report
        updated = generation == 11
        assert summary["e"] == (3 if updated else 2)
        assert (summary["m"], summary["a"], summary["x"], summary["d"]) == (
            1, 1, 2 if updated else 1, 0)
        assert summary["hw"] == 0 and summary["t"] == 1000
        assert sum(histogram[f"b{i}"] for i in range(8)) == summary["e"]
        assert histogram["hv"] == 1 and histogram["b0"] == 1
        assert minimum["seq"] == 41 and minimum["start"] == 0xfffffff0
        assert minimum["end"] == 0xfffffff1
        for sample in [minimum, maximum, tail0, tail1]:
            assert sample["session"] == 99 and sample["have"] == 1
            assert sample["status"] == 0 and sample["domain"] == 1
        assert maximum["seq"] == (45 if updated else 42)
        assert tail0["seq"] == maximum["seq"]
        assert tail1["seq"] == (42 if updated else 41)
        assert noneligible["seq"] == 44 and noneligible["session"] == 99
        assert noneligible["status"] == 2 and noneligible["have"] == 1


def test_congested_diagnostics_do_not_write_or_block_later_reports(live_harness: Path) -> None:
    rows = _rows(live_harness, "congested")
    assert rows and min(r["g"] for r in rows) == 11
    summaries = [r for r in rows if r["p"] == 0]
    assert len(summaries) == 10
    assert {r["d"] for r in summaries} == {7}
    assert all(r["e"] >= 2 and r["m"] == 1 and r["a"] == 1 for r in summaries)


def test_actual_firmware_rows_survive_host_decode_and_loss_detection(live_harness: Path) -> None:
    result = subprocess.run([str(live_harness)], check=True, capture_output=True, text=True)
    lines = result.stdout.splitlines()
    reports = decode_reports(lines)
    assert len(reports) == 20
    assert all(report["status"] == "complete" for report in reports)
    assert reports[0]["parts"]["3"]["seq"] == 42
    assert reports[10]["parts"]["3"]["seq"] == 45
    assert all(not report["hardware_to_service_available"] for report in reports)
    missing = decode_reports(lines[:3] + lines[4:])
    assert missing[0]["status"] == "missing" and missing[0]["missing_parts"] == [3]
    duplicated = decode_reports(lines[:1] + lines)
    assert duplicated[0]["status"] == "ambiguous"
    assert "duplicate part 0" in duplicated[0]["errors"]
