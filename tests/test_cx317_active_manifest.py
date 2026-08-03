from __future__ import annotations

from pathlib import Path
import json

from host.otis_tools.cx317_active_manifest import create_active_manifest


def test_active_manifest_binds_clean_artifact_and_requires_act_and_dac(tmp_path: Path) -> None:
    build_manifest = tmp_path / "firmware_build_manifest.json"
    build_manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifacts": [
                    {"name": "firmware.uf2", "sha256": "d" * 64, "size_bytes": 123}
                ],
                "provenance": {
                    "source": {
                        "git_commit": "1" * 40,
                        "state": "clean",
                        "sha256": "a" * 64,
                    },
                    "configuration": {
                        "profile_id": "cx317_bounded_active_campaign_a",
                        "sha256": "b" * 64,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    run_dir = tmp_path / "run_a"
    path = create_active_manifest(
        campaign="A",
        run_dir=run_dir,
        build_manifest_path=build_manifest,
        serial_device="/dev/cu.fixture",
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["firmware"]["build_identity"] == "a" * 64 + ":" + "b" * 64
    required = {
        entry["contract"]
        for entry in manifest["files"]
        if not entry.get("optional")
    }
    assert {"active_transactions_v1", "dac_steps_v1"} <= required
    assert manifest["active_campaign"]["maximum_step_codes"] == 21
    assert manifest["host"]["sole_serial_owner"] is True
