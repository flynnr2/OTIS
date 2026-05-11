from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


@dataclass(frozen=True)
class RunManifest:
    root: Path
    data: dict

    @property
    def run_id(self) -> str:
        return str(self.data["run_id"])

    @property
    def files(self) -> list[dict]:
        return list(self.data.get("files", []))


def load_manifest(run_dir: Path) -> RunManifest:
    manifest_path = run_dir / "run_manifest.json"
    with manifest_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if data.get("schema_version") != 1:
        raise ValueError(f"unsupported manifest schema_version: {data.get('schema_version')!r}")
    if not data.get("run_id"):
        raise ValueError("manifest missing run_id")

    return RunManifest(root=run_dir, data=data)
