from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


RUN_MANIFEST = "run_manifest.json"
RAW_DIR = "raw"
CSV_DIR = "csv"
REPORTS_DIR = "reports"
RAW_SERIAL_LOG = "serial.log"
RAW_EVENTS_CSV = "raw_events.csv"
COUNT_OBSERVATIONS_CSV = "count_observations.csv"
HEALTH_CSV = "health.csv"


@dataclass(frozen=True)
class RunPaths:
    root: Path

    @property
    def raw_dir(self) -> Path:
        return self.root / RAW_DIR

    @property
    def csv_dir(self) -> Path:
        return self.root / CSV_DIR

    @property
    def reports_dir(self) -> Path:
        return self.root / REPORTS_DIR

    @property
    def manifest(self) -> Path:
        return self.root / RUN_MANIFEST

    @property
    def raw_serial_log(self) -> Path:
        return self.raw_dir / RAW_SERIAL_LOG

    @property
    def raw_events_csv(self) -> Path:
        return self.csv_dir / RAW_EVENTS_CSV

    @property
    def count_observations_csv(self) -> Path:
        return self.csv_dir / COUNT_OBSERVATIONS_CSV

    @property
    def health_csv(self) -> Path:
        return self.csv_dir / HEALTH_CSV


def default_csv_files() -> list[dict[str, str]]:
    return [
        {"path": f"{CSV_DIR}/{RAW_EVENTS_CSV}", "contract": "raw_events_v1"},
        {"path": f"{CSV_DIR}/{COUNT_OBSERVATIONS_CSV}", "contract": "count_observations_v1"},
        {"path": f"{CSV_DIR}/{HEALTH_CSV}", "contract": "health_v1"},
    ]


def ensure_run_layout(run_dir: Path) -> RunPaths:
    paths = RunPaths(run_dir)
    paths.raw_dir.mkdir(parents=True, exist_ok=True)
    paths.csv_dir.mkdir(parents=True, exist_ok=True)
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    return paths
