from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


RUN_MANIFEST = "run_manifest.json"
RAW_DIR = "raw"
CSV_DIR = "csv"
REPORTS_DIR = "reports"
RAW_SERIAL_LOG = "serial.log"
EXTERNAL_EVENTS_CSV = "external_events.csv"
REFERENCE_EVENTS_CSV = "reference_events.csv"
COUNT_OBSERVATIONS_CSV = "count_observations.csv"
PPS_SNAPSHOTS_CSV = "pps_snapshots.csv"
ACCEPTED_PPS_SPANS_CSV = "accepted_pps_spans_v1.csv"
# This is deliberately distinct from the D8 PIO/DMA snapshot evidence above.
# It carries only the D6 observation of the forwarded D9 output and is never a
# substitute for authoritative D14/D8 capture evidence.
FORWARDED_MONITOR_SNAPSHOTS_CSV = "forwarded_monitor_snapshots.csv"
ASSOCIATION_LOSS_DECISIONS_CSV = "association_loss_decisions_v1.csv"
HEALTH_CSV = "health.csv"
DAC_STEPS_CSV = "dac_steps.csv"
ENVIRONMENT_CSV = "environment.csv"
ESTIMATES_CSV = "estimates_v3.csv"
CONTROL_PREVIEWS_CSV = "control_previews_v1.csv"
ACTIVE_TRANSACTIONS_CSV = "active_transactions_v3.csv"
ACTIVE_HYBRID_DECISIONS_CSV = "active_hybrid_decisions_v3.csv"
ACTIVE_HYBRID_MAINTENANCE_CSV = "active_hybrid_maintenance_v2.csv"
RELATIVE_PHASE_OBSERVATIONS_CSV = "relative_phase_observations_v2.csv"
PHASE_ESTIMATOR_OUTPUTS_CSV = "phase_estimator_outputs_v2.csv"
TIGHT_DEADBAND_DECISIONS_CSV = "tight_deadband_decisions_v1.csv"


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
    def external_events_csv(self) -> Path:
        return self.csv_dir / EXTERNAL_EVENTS_CSV

    @property
    def reference_events_csv(self) -> Path:
        return self.csv_dir / REFERENCE_EVENTS_CSV

    @property
    def count_observations_csv(self) -> Path:
        return self.csv_dir / COUNT_OBSERVATIONS_CSV

    @property
    def pps_snapshots_csv(self) -> Path:
        return self.csv_dir / PPS_SNAPSHOTS_CSV

    @property
    def accepted_pps_spans_csv(self) -> Path:
        return self.csv_dir / ACCEPTED_PPS_SPANS_CSV

    @property
    def forwarded_monitor_snapshots_csv(self) -> Path:
        return self.csv_dir / FORWARDED_MONITOR_SNAPSHOTS_CSV

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
    def active_transactions_csv(self) -> Path:
        return self.csv_dir / ACTIVE_TRANSACTIONS_CSV

    @property
    def active_hybrid_decisions_csv(self) -> Path:
        return self.csv_dir / ACTIVE_HYBRID_DECISIONS_CSV

    @property
    def active_hybrid_maintenance_csv(self) -> Path:
        return self.csv_dir / ACTIVE_HYBRID_MAINTENANCE_CSV

    @property
    def relative_phase_observations_csv(self) -> Path:
        return self.csv_dir / RELATIVE_PHASE_OBSERVATIONS_CSV

    @property
    def phase_estimator_outputs_csv(self) -> Path:
        return self.csv_dir / PHASE_ESTIMATOR_OUTPUTS_CSV

    @property
    def tight_deadband_decisions_csv(self) -> Path:
        return self.csv_dir / TIGHT_DEADBAND_DECISIONS_CSV


def default_csv_files() -> list[dict[str, str]]:
    return [
        {
            "path": f"{CSV_DIR}/{EXTERNAL_EVENTS_CSV}",
            "contract": "raw_events_v1",
            "record_type": "EVT",
            "channel_id": 0,
            "pin": "D10",
            "role": "external_event",
            "optional": True,
        },
        {
            "path": f"{CSV_DIR}/{REFERENCE_EVENTS_CSV}",
            "contract": "raw_events_v1",
            "record_type": "REF",
            "channel_id": 1,
            "pin": "D14",
            "role": "authoritative_reference",
        },
        {"path": f"{CSV_DIR}/{COUNT_OBSERVATIONS_CSV}", "contract": "count_observations_v1"},
        {"path": f"{CSV_DIR}/{PPS_SNAPSHOTS_CSV}", "contract": "pps_snapshots_v1", "optional": True},
        {"path": f"{CSV_DIR}/{ACCEPTED_PPS_SPANS_CSV}", "contract": "accepted_pps_spans_v1", "optional": True},
        {
            "path": f"{CSV_DIR}/{FORWARDED_MONITOR_SNAPSHOTS_CSV}",
            "contract": "forwarded_monitor_snapshots_v1",
            "optional": True,
        },
        {
            "path": f"{CSV_DIR}/{ASSOCIATION_LOSS_DECISIONS_CSV}",
            "contract": "association_loss_decisions_v1",
            "optional": True,
        },
        {"path": f"{CSV_DIR}/{HEALTH_CSV}", "contract": "health_v1"},
        {"path": f"{CSV_DIR}/{DAC_STEPS_CSV}", "contract": "dac_steps_v1", "optional": True},
        {"path": f"{CSV_DIR}/{ENVIRONMENT_CSV}", "contract": "environment_v1", "optional": True},
        {
            "path": f"{CSV_DIR}/{ESTIMATES_CSV}",
            "contract": "estimates_v3",
            "optional": True,
        },
        {
            "path": f"{CSV_DIR}/{CONTROL_PREVIEWS_CSV}",
            "contract": "control_previews_v1",
            "optional": True,
        },
        {
            "path": f"{CSV_DIR}/{ACTIVE_TRANSACTIONS_CSV}",
            "contract": "active_transactions_v3",
        },
        {
            "path": f"{CSV_DIR}/{ACTIVE_HYBRID_DECISIONS_CSV}",
            "contract": "active_hybrid_decisions_v3",
        },
        {
            "path": f"{CSV_DIR}/{ACTIVE_HYBRID_MAINTENANCE_CSV}",
            "contract": "active_hybrid_maintenance_v2",
        },
        {
            "path": f"{CSV_DIR}/{RELATIVE_PHASE_OBSERVATIONS_CSV}",
            "contract": "relative_phase_observations_v2",
            "optional": True,
        },
        {
            "path": f"{CSV_DIR}/{PHASE_ESTIMATOR_OUTPUTS_CSV}",
            "contract": "phase_estimator_outputs_v2",
            "optional": True,
        },
        {
            "path": f"{CSV_DIR}/{TIGHT_DEADBAND_DECISIONS_CSV}",
            "contract": "tight_deadband_decisions_v1",
            "optional": True,
        },
    ]


def adaptive_hybrid_csv_files() -> list[dict[str, str]]:
    """Return the sole current adaptive-hybrid capture-product inventory."""

    return default_csv_files()


def ensure_run_layout(run_dir: Path) -> RunPaths:
    paths = RunPaths(run_dir)
    paths.raw_dir.mkdir(parents=True, exist_ok=True)
    paths.csv_dir.mkdir(parents=True, exist_ok=True)
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    return paths
