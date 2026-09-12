"""Load only the current adaptive-hybrid run-manifest contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CANONICAL_MANIFEST = "run_manifest.json"
CAPTURE_IN_PROGRESS_FLAG = "capture_in_progress.flag"
@dataclass(frozen=True)
class RunManifest:
    root: Path
    path: Path
    data: dict

    @property
    def run_id(self) -> str:
        return str(self.data["run_id"])

    @property
    def files(self) -> list[dict]:
        return list(self.data.get("files", []))

    @property
    def stage(self) -> str | None:
        value = self.data.get("stage")
        return None if value in (None, "") else str(value)

    @property
    def capture_mode(self) -> str | None:
        value = self.data.get("capture_mode")
        return str(value) if value not in (None, "") else None

    @property
    def board(self) -> str | None:
        value = self.data.get("board")
        return str(value) if value not in (None, "") else None

    @property
    def firmware_name(self) -> str | None:
        firmware = self.data.get("firmware")
        return str(firmware["image_id"]) if isinstance(firmware, dict) and firmware.get("image_id") else None

    @property
    def firmware_version(self) -> str | None:
        firmware = self.data.get("firmware")
        return str(firmware["build_identity"]) if isinstance(firmware, dict) and firmware.get("build_identity") else None

    @property
    def firmware_git_commit(self) -> str | None:
        firmware = self.data.get("firmware")
        return str(firmware["source_revision"]) if isinstance(firmware, dict) and firmware.get("source_revision") else None

    @property
    def host_tool_version(self) -> str | None:
        host = self.data.get("host")
        return str(host["version"]) if isinstance(host, dict) and host.get("version") else None

    @property
    def host_git_commit(self) -> str | None:
        host = self.data.get("host")
        return str(host["source_revision"]) if isinstance(host, dict) and host.get("source_revision") else None

    @property
    def expected_artifacts(self) -> list[str]:
        expected = self.data.get("expected_artifacts")
        if isinstance(expected, list):
            return [str(item) for item in expected]
        return [str(item["path"]) for item in self.files if item.get("path")]

    @property
    def known_limitations(self) -> list[str]:
        value = self.data.get("known_limitations")
        return [str(item) for item in value] if isinstance(value, list) else []

    @property
    def known_channels(self) -> frozenset[int]:
        return frozenset(
            int(item["channel_id"])
            for item in self.data.get("channels", [])
            if isinstance(item, dict) and "channel_id" in item
        )

    @property
    def known_domains(self) -> frozenset[str]:
        return frozenset(
            str(item["name"])
            for item in self.data.get("domains", [])
            if isinstance(item, dict) and "name" in item
        )


def find_manifest_path(run_dir: Path) -> Path | None:
    path = run_dir / CANONICAL_MANIFEST
    return path if path.exists() else None


def load_manifest(run_dir: Path) -> RunManifest:
    """Load one run record and derive configuration from its retained specification.

    A run record is provenance, not another copy of the configuration. Historical
    formats are read using their recorded source revision rather than guessed.
    """
    from .run_spec import load_run_spec

    root = run_dir.resolve()
    manifest_path = root / CANONICAL_MANIFEST
    record = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError("run record must be an object")
    binding = record.get("run_spec")
    if not isinstance(binding, dict) or not isinstance(binding.get("path"), str):
        raise ValueError("run record has no retained run specification")
    relative = Path(binding["path"])
    spec_path = root / relative
    if relative.is_absolute() or ".." in relative.parts or spec_path.is_symlink():
        raise ValueError("run specification must be a retained relative regular file")
    if root not in spec_path.resolve().parents:
        raise ValueError("run specification escapes the acquisition")
    spec = load_run_spec(spec_path)
    data = spec.runtime_manifest(record)
    files = data.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("run specification must declare observation files")
    seen = set()
    for item in files:
        value = item.get("path") if isinstance(item, dict) else None
        if not isinstance(value, str) or not value:
            raise ValueError("malformed observation path")
        relative = Path(value)
        if (relative.is_absolute() or ".." in relative.parts
                or relative.as_posix() != value or value in seen):
            raise ValueError("observation paths must be unique and relative")
        candidate = root / relative
        if candidate.is_symlink() or root not in candidate.resolve().parents:
            raise ValueError("observation path escapes the acquisition")
        seen.add(value)
    return RunManifest(root=root, path=manifest_path, data=data)
