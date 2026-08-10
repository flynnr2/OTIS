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
PPS_SNAPSHOTS_CSV = "pps_snapshots.csv"
ASSOCIATION_LOSS_DECISIONS_CSV = "association_loss_decisions_v1.csv"
HEALTH_CSV = "health.csv"
DAC_STEPS_CSV = "dac_steps.csv"
ENVIRONMENT_CSV = "environment.csv"
REFERENCE_OBSERVATIONS_CSV = "reference_observations_v1.csv"
DIAGNOSTICS_CSV = "diagnostics_v1.csv"
ESTIMATES_CSV = "estimates_v2.csv"
CONTROL_PREVIEWS_CSV = "control_previews_v1.csv"
ACTIVE_TRANSACTIONS_CSV = "active_transactions_v1.csv"
RELATIVE_PHASE_OBSERVATIONS_CSV = "relative_phase_observations_v1.csv"
PHASE_ESTIMATOR_OUTPUTS_CSV = "phase_estimator_outputs_v1.csv"
HYBRID_PREVIEW_DECISIONS_CSV = "hybrid_preview_decisions_v1.csv"
TIGHT_DEADBAND_DECISIONS_CSV = "tight_deadband_decisions_v1.csv"
PSEUDO_PPS_TRUTH_CSV = "pseudo_pps_truth.csv"


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
    def pps_snapshots_csv(self) -> Path:
        return self.csv_dir / PPS_SNAPSHOTS_CSV

    @property
    def association_loss_decisions_csv(self) -> Path:
        return self.csv_dir / ASSOCIATION_LOSS_DECISIONS_CSV

    @property
    def health_csv(self) -> Path:
        return self.csv_dir / HEALTH_CSV

    @property
    def environment_csv(self) -> Path:
        return self.csv_dir / ENVIRONMENT_CSV

    @property
    def dac_steps_csv(self) -> Path:
        return self.csv_dir / DAC_STEPS_CSV

    @property
    def pseudo_pps_truth_csv(self) -> Path:
        return self.csv_dir / PSEUDO_PPS_TRUTH_CSV

    @property
    def active_transactions_csv(self) -> Path:
        return self.csv_dir / ACTIVE_TRANSACTIONS_CSV

    @property
    def relative_phase_observations_csv(self) -> Path:
        return self.csv_dir / RELATIVE_PHASE_OBSERVATIONS_CSV

    @property
    def phase_estimator_outputs_csv(self) -> Path:
        return self.csv_dir / PHASE_ESTIMATOR_OUTPUTS_CSV

    @property
    def hybrid_preview_decisions_csv(self) -> Path:
        return self.csv_dir / HYBRID_PREVIEW_DECISIONS_CSV

    @property
    def tight_deadband_decisions_csv(self) -> Path:
        return self.csv_dir / TIGHT_DEADBAND_DECISIONS_CSV


def default_csv_files() -> list[dict[str, str]]:
    return [
        {"path": f"{CSV_DIR}/{RAW_EVENTS_CSV}", "contract": "raw_events_v1"},
        {"path": f"{CSV_DIR}/{COUNT_OBSERVATIONS_CSV}", "contract": "count_observations_v1"},
        {"path": f"{CSV_DIR}/{PPS_SNAPSHOTS_CSV}", "contract": "pps_snapshots_v1", "optional": True},
        {
            "path": f"{CSV_DIR}/{ASSOCIATION_LOSS_DECISIONS_CSV}",
            "contract": "association_loss_decisions_v1",
            "optional": True,
        },
        {"path": f"{CSV_DIR}/{HEALTH_CSV}", "contract": "health_v1"},
        {"path": f"{CSV_DIR}/{DAC_STEPS_CSV}", "contract": "dac_steps_v1", "optional": True},
        {"path": f"{CSV_DIR}/{ENVIRONMENT_CSV}", "contract": "environment_v1", "optional": True},
        {
            "path": f"{CSV_DIR}/{REFERENCE_OBSERVATIONS_CSV}",
            "contract": "reference_observations_v1",
            "optional": True,
        },
        {
            "path": f"{CSV_DIR}/{DIAGNOSTICS_CSV}",
            "contract": "diagnostics_v1",
            "optional": True,
        },
        {
            "path": f"{CSV_DIR}/{ESTIMATES_CSV}",
            "contract": "estimates_v2",
            "optional": True,
        },
        {
            "path": f"{CSV_DIR}/{CONTROL_PREVIEWS_CSV}",
            "contract": "control_previews_v1",
            "optional": True,
        },
        {
            "path": f"{CSV_DIR}/{ACTIVE_TRANSACTIONS_CSV}",
            "contract": "active_transactions_v1",
            "optional": True,
        },
        {
            "path": f"{CSV_DIR}/{RELATIVE_PHASE_OBSERVATIONS_CSV}",
            "contract": "relative_phase_observations_v1",
            "optional": True,
        },
        {
            "path": f"{CSV_DIR}/{PHASE_ESTIMATOR_OUTPUTS_CSV}",
            "contract": "phase_estimator_outputs_v1",
            "optional": True,
        },
        {
            "path": f"{CSV_DIR}/{HYBRID_PREVIEW_DECISIONS_CSV}",
            "contract": "hybrid_preview_decisions_v1",
            "optional": True,
        },
        {
            "path": f"{CSV_DIR}/{TIGHT_DEADBAND_DECISIONS_CSV}",
            "contract": "tight_deadband_decisions_v1",
            "optional": True,
        },
        {"path": f"{CSV_DIR}/{PSEUDO_PPS_TRUTH_CSV}", "contract": "pseudo_pps_truth_v1", "optional": True},
    ]


def ensure_run_layout(run_dir: Path) -> RunPaths:
    paths = RunPaths(run_dir)
    paths.raw_dir.mkdir(parents=True, exist_ok=True)
    paths.csv_dir.mkdir(parents=True, exist_ok=True)
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    return paths
