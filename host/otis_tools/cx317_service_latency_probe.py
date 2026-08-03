"""Measure the no-write capture-FIFO/DAC-status service path for Stage 5."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import csv
import json
import math
import statistics
import tempfile
import time

from .serial_commands import send_command_to_fifo


TOOL_VERSION = "cx317_no_write_service_latency_v1"
STATUS_KEY = "applied_code_known"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def matching_status_count(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("component") == "dac" and row.get("status_key") == STATUS_KEY:
                count += 1
    return count


def derive_ack_deadline(maximum_observed_latency_s: float) -> dict[str, float | str]:
    if not math.isfinite(maximum_observed_latency_s) or maximum_observed_latency_s < 0:
        raise ValueError("maximum observed latency must be finite and nonnegative")
    margin_s = 1.0
    return {
        "maximum_observed_latency_s": maximum_observed_latency_s,
        "margin_s": margin_s,
        "proposed_ack_deadline_s": maximum_observed_latency_s + margin_s,
        "calculation": "maximum observed no-write end-to-end service latency plus one nominal accepted PPS interval",
        "disposition": "architecture screen",
        "source_hierarchy": "2,4",
        "applicability": "scheduler acknowledgement deadline proposal only; the first live write must still acknowledge before this deadline and establishes the write-specific slack",
    }


def probe_latency(
    fifo: Path,
    health_csv: Path,
    output: Path,
    *,
    repeats: int,
    response_timeout_s: float,
    spacing_s: float,
) -> Path:
    if repeats < 1:
        raise ValueError("repeats must be at least one")
    if response_timeout_s <= 0 or spacing_s < 0:
        raise ValueError("response timeout must be positive and spacing nonnegative")
    results: list[float] = []
    started_at_utc = _utc_now()
    for index in range(repeats):
        prior = matching_status_count(health_csv)
        started = time.monotonic()
        send_command_to_fifo(fifo, "DAC?")
        deadline = started + response_timeout_s
        while time.monotonic() < deadline:
            if matching_status_count(health_csv) > prior:
                results.append(time.monotonic() - started)
                break
            time.sleep(0.005)
        else:
            raise TimeoutError(f"read-only DAC? response {index + 1} timed out")
        if index + 1 < repeats and spacing_s:
            time.sleep(spacing_s)

    maximum = max(results)
    result = {
        "schema_version": 1,
        "tool_version": TOOL_VERSION,
        "started_at_utc": started_at_utc,
        "completed_at_utc": _utc_now(),
        "command": "DAC?",
        "hardware_actuation": False,
        "serial_dac_write_commands": 0,
        "repeat_count": repeats,
        "response_timeout_s": response_timeout_s,
        "spacing_s": spacing_s,
        "observed_latency_s": results,
        "minimum_observed_latency_s": min(results),
        "median_observed_latency_s": statistics.median(results),
        "maximum_observed_latency_s": maximum,
        "deadline_proposal": derive_ack_deadline(maximum),
        "limitations": [
            "Read-only DAC? response exercises capture FIFO, serial framing, firmware command dispatch and returned DAC status but not an I2C DAC write.",
            "The first live manual-write acknowledgement must be timed separately and must have positive deadline slack.",
            "The one-second margin is the nominal accepted PPS observation interval, not a controller cadence or a hardware settling allowance."
        ]
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(output)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure the Stage 5 read-only capture-FIFO/DAC-status latency.")
    parser.add_argument("--fifo", type=Path, required=True)
    parser.add_argument("--health-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--response-timeout-s", type=float, default=5.0)
    parser.add_argument("--spacing-s", type=float, default=1.0)
    args = parser.parse_args(argv)
    try:
        print(
            probe_latency(
                args.fifo,
                args.health_csv,
                args.output,
                repeats=args.repeats,
                response_timeout_s=args.response_timeout_s,
                spacing_s=args.spacing_s,
            )
        )
    except (OSError, TimeoutError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
