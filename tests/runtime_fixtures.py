"""Construct the current supervisor from the same run-spec path used at runtime."""
from __future__ import annotations

from pathlib import Path

import pytest

from host.otis_tools.adaptive_hybrid_contract import UNATTENDED_72_HOUR_HYBRID_CONTROL
from host.otis_tools.adaptive_hybrid_supervisor import (
    AdaptiveHybridSupervisor,
    prepare_runtime_context,
)
from host.otis_tools.run_loader import load_manifest
from host.otis_tools.run_spec import create_run_record
from tests.run_spec_fixtures import build_synthetic_spec


def construct_simulated_supervisor(
    run_dir: Path,
    *,
    purpose: str = UNATTENDED_72_HOUR_HYBRID_CONTROL,
) -> AdaptiveHybridSupervisor:
    """Build the real constructor boundary without opening a device."""
    if not (run_dir / "run_manifest.json").exists():
        with pytest.MonkeyPatch.context() as patch:
            spec = build_synthetic_spec(patch, run_dir, purpose=purpose)
        create_run_record(
            spec,
            execution_kind="simulated",
            run_id=run_dir.name,
            started_at_utc="2026-09-12T10:01:00Z",
            serial_device="/dev/ttys999",
            output_path=run_dir / "run_manifest.json",
        )
    manifest = load_manifest(run_dir).data
    return AdaptiveHybridSupervisor(
        runtime_context=prepare_runtime_context(manifest),
        manifest_path=run_dir / "run_manifest.json",
        run_dir=run_dir,
        command_fifo=run_dir / "control/normal_commands.fifo",
        emergency_command_fifo=run_dir / "control/emergency_abort.fifo",
        console_events=False,
    )
