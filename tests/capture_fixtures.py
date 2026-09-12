"""Current run-spec fixture for real capture tests; no legacy manifest builder."""
from datetime import datetime, timezone
from pathlib import Path
import pytest
from host.otis_tools.adaptive_hybrid_contract import CONTINGENT_72_HOUR_HYBRID_CONTROL
from host.otis_tools.run_spec import create_run_record
from tests.run_spec_fixtures import build_synthetic_spec


def write_simulated_run(root: Path, device: str = "/dev/ttys999") -> dict:
    with pytest.MonkeyPatch.context() as patch:
        spec = build_synthetic_spec(patch, root, purpose=CONTINGENT_72_HOUR_HYBRID_CONTROL)
    record = create_run_record(spec, execution_kind="simulated", run_id=root.name,
        started_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        serial_device=device, output_path=root / "run_manifest.json")
    return spec.runtime_manifest(record)
