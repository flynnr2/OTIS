"""Load only the current adaptive-hybrid run-manifest contract."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


CANONICAL_MANIFEST = "run_manifest.json"
CAPTURE_IN_PROGRESS_FLAG = "capture_in_progress.flag"
COMPLETE_MARKER = "COMPLETE"
CURRENT_EVIDENCE_EPOCH = "OTIS_ADAPTIVE_HYBRID_EVIDENCE_EPOCH_1"
CURRENT_STAGE = "OTIS_ADAPTIVE_HYBRID_REGULATION_LIVE"
CURRENT_PROFILE_ID = "adaptive_hybrid_regulation"
CURRENT_PROGRAMME_ID = "OTIS_ADAPTIVE_HYBRID_REGULATION_V1"


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
    def is_template(self) -> bool:
        return bool(self.data.get("template", False))

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


@dataclass(frozen=True)
class RunState:
    capture_in_progress: bool
    complete: bool


def find_manifest_path(run_dir: Path) -> Path | None:
    path = run_dir / CANONICAL_MANIFEST
    return path if path.exists() else None


def inspect_run_state(run_dir: Path) -> RunState:
    return RunState(
        capture_in_progress=(run_dir / CAPTURE_IN_PROGRESS_FLAG).exists(),
        complete=(run_dir / COMPLETE_MARKER).exists(),
    )


def _require_current_identity(data: dict) -> None:
    section = data.get("adaptive_hybrid")
    if not isinstance(section, dict):
        raise ValueError("manifest lacks adaptive_hybrid operating descriptor")
    if (
        data.get("evidence_epoch") != CURRENT_EVIDENCE_EPOCH
        or data.get("stage") != CURRENT_STAGE
        or data.get("programme_id") != CURRENT_PROGRAMME_ID
        or data.get("image_identity") != CURRENT_PROFILE_ID
        or section.get("profile_id") != CURRENT_PROFILE_ID
    ):
        raise ValueError("manifest does not satisfy the current adaptive-hybrid identity")


def load_manifest(run_dir: Path) -> RunManifest:
    manifest_path = find_manifest_path(run_dir)
    if manifest_path is None:
        raise FileNotFoundError(f"missing canonical {CANONICAL_MANIFEST} in {run_dir}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError(f"unsupported manifest schema_version: {data.get('schema_version')!r}")
    if not data.get("run_id"):
        raise ValueError("manifest missing run_id")
    if not isinstance(data.get("files"), list) or not data["files"]:
        raise ValueError("manifest must list at least one data file")
    _require_current_identity(data)
    return RunManifest(root=run_dir, path=manifest_path, data=data)
