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

    @property
    def is_template(self) -> bool:
        return bool(self.data.get("template", False))

    @property
    def bringup_mode(self) -> str | None:
        mode = self.data.get("bringup_mode")
        return str(mode) if mode is not None else None

    @property
    def known_channels(self) -> frozenset[int]:
        channels: set[int] = set()
        for channel in self.data.get("channels", []):
            if "channel_id" in channel:
                channels.add(int(channel["channel_id"]))
        return frozenset(channels)

    @property
    def known_domains(self) -> frozenset[str]:
        return frozenset(str(domain["name"]) for domain in self.data.get("domains", []) if "name" in domain)


def load_manifest(run_dir: Path) -> RunManifest:
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        manifest_path = run_dir / "manifest.json"
    with manifest_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if data.get("schema_version") != 1:
        raise ValueError(f"unsupported manifest schema_version: {data.get('schema_version')!r}")
    if not data.get("run_id"):
        raise ValueError("manifest missing run_id")
    if not isinstance(data.get("files"), list) or not data["files"]:
        raise ValueError("manifest must list at least one data file")

    return RunManifest(root=run_dir, data=data)
