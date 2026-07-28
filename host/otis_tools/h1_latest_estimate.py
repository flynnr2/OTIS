from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import argparse
import csv


ESTIMATES_RELATIVE_PATH = Path("csv") / "h1_count_frequency_estimates.csv"


@dataclass(frozen=True)
class LatestEstimate:
    count_seq: int | None
    local_pps_frequency_hz: float
    local_pps_ppm: float
    estimator_valid: bool


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes", "valid"}


def _parse_optional_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def read_latest_valid_estimate(run_dir: Path) -> LatestEstimate:
    estimates_path = run_dir / ESTIMATES_RELATIVE_PATH
    if not estimates_path.exists():
        raise FileNotFoundError(f"missing estimator output: {estimates_path}")

    latest: LatestEstimate | None = None
    with estimates_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not _parse_bool(row.get("estimator_valid", "")):
                continue
            frequency_text = row.get("local_pps_frequency_hz", "")
            ppm_text = row.get("local_pps_ppm", "")
            if frequency_text == "" or ppm_text == "":
                continue
            latest = LatestEstimate(
                count_seq=_parse_optional_int(row.get("count_seq")),
                local_pps_frequency_hz=float(frequency_text),
                local_pps_ppm=float(ppm_text),
                estimator_valid=True,
            )

    if latest is None:
        raise ValueError(f"no valid local-PPS estimates found in {estimates_path}")
    return latest


def format_latest_estimate(estimate: LatestEstimate, dac_code: int | None) -> str:
    prefix = f"DAC 0x{dac_code:04X}" if dac_code is not None else "DAC unknown"
    return (
        f"{prefix} | {estimate.local_pps_frequency_hz:.3f} Hz | "
        f"{estimate.local_pps_ppm:+.3f} ppm | valid"
    )


def _parse_dac_code(value: str) -> int:
    code = int(value, 0)
    if not 0 <= code <= 0xFFFF:
        raise argparse.ArgumentTypeError("DAC code must be in the 0x0000..0xFFFF range")
    return code


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print the latest valid local-PPS H1 frequency estimate from an existing h1_characterize CSV."
    )
    parser.add_argument("run_dir", type=Path, help="H1 run directory containing csv/h1_count_frequency_estimates.csv.")
    parser.add_argument("--dac-code", type=_parse_dac_code, help="Operator-applied DAC code to include in the output.")
    args = parser.parse_args()

    try:
        estimate = read_latest_valid_estimate(args.run_dir)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        raise SystemExit(str(exc)) from exc

    print(format_latest_estimate(estimate, args.dac_code))


if __name__ == "__main__":
    main()
