from __future__ import annotations

from pathlib import Path

from .run_loader import load_manifest


def render_report(run_dir: Path) -> str:
    manifest = load_manifest(run_dir)

    lines: list[str] = []
    lines.append(f"Run: {manifest.run_id}")
    lines.append("")
    lines.append("Contracts:")

    for file_entry in manifest.files:
        lines.append(f"- {file_entry['contract']}: {file_entry['path']}")

    return "\n".join(lines)
