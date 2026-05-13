from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


MANIFEST_CANDIDATES = ("run_manifest.json", "manifest.json")
CAPTURE_IN_PROGRESS_FLAG = "capture_in_progress.flag"
COMPLETE_MARKER = "COMPLETE"
SW1_CAPTURE_MODE = "irq_reconstructed"
SW1_LIMITATION_TEXT = (
    "SW1 capture mode: irq_reconstructed. Timestamps are suitable for bench "
    "validation and protocol bring-up, not final PIO/DMA metrology."
)


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
    def bringup_mode(self) -> str | None:
        mode = self.data.get("bringup_mode")
        return str(mode) if mode is not None else None

    @property
    def stage(self) -> str | None:
        stage = self.data.get("stage")
        if stage not in (None, ""):
            return str(stage)
        if "h0_sw1" in self.root.parts:
            return "SW1"
        firmware = self.data.get("firmware")
        if isinstance(firmware, dict) and firmware.get("version") == "SW1":
            return "SW1"
        return None

    @property
    def h_phase(self) -> str | None:
        phase = self.data.get("h_phase")
        if phase not in (None, ""):
            return str(phase)
        if "h0_sw1" in self.root.parts or str(self.data.get("run_id", "")).startswith("h0_"):
            return "H0"
        return None

    @property
    def capture_mode(self) -> str | None:
        mode = self.data.get("capture_mode")
        if mode not in (None, ""):
            return str(mode)
        firmware = self.data.get("firmware")
        if isinstance(firmware, dict) and firmware.get("capture_mode"):
            return str(firmware["capture_mode"])
        if self.bringup_mode == "SW1_SYNTHETIC_USB":
            return "synthetic_usb"
        if self.stage == "SW1":
            return SW1_CAPTURE_MODE
        return None

    @property
    def board(self) -> str | None:
        board = self.data.get("board")
        if board not in (None, ""):
            return str(board)
        hardware = self.data.get("hardware")
        if isinstance(hardware, dict) and hardware.get("capture_board"):
            return str(hardware["capture_board"])
        return None

    @property
    def firmware_name(self) -> str | None:
        firmware = self.data.get("firmware")
        if isinstance(firmware, dict) and firmware.get("name"):
            return str(firmware["name"])
        name = self.data.get("firmware_name")
        return str(name) if name not in (None, "") else None

    @property
    def firmware_version(self) -> str | None:
        version = self.data.get("firmware_version")
        if version not in (None, ""):
            return str(version)
        firmware = self.data.get("firmware")
        if isinstance(firmware, dict) and firmware.get("version"):
            return str(firmware["version"])
        return None

    @property
    def firmware_git_commit(self) -> str | None:
        commit = self.data.get("firmware_git_commit")
        if commit not in (None, ""):
            return str(commit)
        firmware = self.data.get("firmware")
        if isinstance(firmware, dict) and firmware.get("git_commit"):
            return str(firmware["git_commit"])
        return None

    @property
    def host_tool_version(self) -> str | None:
        version = self.data.get("host_tool_version")
        if version not in (None, ""):
            return str(version)
        host = self.data.get("host")
        if isinstance(host, dict) and host.get("version"):
            return str(host["version"])
        return None

    @property
    def host_git_commit(self) -> str | None:
        commit = self.data.get("host_git_commit")
        if commit not in (None, ""):
            return str(commit)
        host = self.data.get("host")
        if isinstance(host, dict) and host.get("git_commit"):
            return str(host["git_commit"])
        return None

    @property
    def expected_artifacts(self) -> list[str]:
        expected = self.data.get("expected_artifacts")
        if isinstance(expected, list):
            return [str(item) for item in expected]
        return [str(file_entry.get("path", "")) for file_entry in self.files if file_entry.get("path")]

    @property
    def known_limitations(self) -> list[str]:
        limitations = self.data.get("known_limitations")
        if isinstance(limitations, list):
            return [str(item) for item in limitations]
        return []

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


@dataclass(frozen=True)
class RunState:
    capture_in_progress: bool
    complete: bool


def find_manifest_path(run_dir: Path) -> Path | None:
    for candidate in MANIFEST_CANDIDATES:
        path = run_dir / candidate
        if path.exists():
            return path
    return None


def inspect_run_state(run_dir: Path) -> RunState:
    return RunState(
        capture_in_progress=(run_dir / CAPTURE_IN_PROGRESS_FLAG).exists(),
        complete=(run_dir / COMPLETE_MARKER).exists(),
    )


def load_manifest(run_dir: Path) -> RunManifest:
    manifest_path = find_manifest_path(run_dir)
    if manifest_path is None:
        names = " or ".join(MANIFEST_CANDIDATES)
        raise FileNotFoundError(f"missing manifest: expected {names} in {run_dir}")
    with manifest_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if data.get("schema_version") != 1:
        raise ValueError(f"unsupported manifest schema_version: {data.get('schema_version')!r}")
    if not data.get("run_id"):
        raise ValueError("manifest missing run_id")
    if not isinstance(data.get("files"), list) or not data["files"]:
        raise ValueError("manifest must list at least one data file")

    return RunManifest(root=run_dir, path=manifest_path, data=data)
