from __future__ import annotations

import json
from pathlib import Path
import re


FIRMWARE = Path("firmware/arduino/otis_nano_rp2040_connect")
INVENTORY = FIRMWARE / "otis_resource_inventory.json"


def test_inventory_matches_every_implemented_queue_and_ring() -> None:
    value = json.loads(INVENTORY.read_text(encoding="utf-8"))
    resources = {item["id"]: item for item in value["resources"]}
    assert set(resources) == {
        "service_to_timing",
        "observation",
        "critical",
        "evidence",
        "telemetry",
        "phase_preview",
        "capture_ring",
        "pps_count_boundary_ring",
    }
    header = (FIRMWARE / "otis_dual_core_partition.h").read_text()
    implementation = (FIRMWARE / "otis_dual_core_partition.cpp").read_text()
    for resource in resources.values():
        assert resource["producer"] != resource["consumer"]
        assert resource["loss_policy"]
        assert resource["maximum_consumer_absence"]
        assert resource["recovery"]
        symbol = resource["capacity_symbol"].removesuffix("-1")
        source = header if "QUEUE_DEPTH" in symbol else (
            FIRMWARE / "otis_config.h"
        ).read_text()
        match = re.search(
            rf"{re.escape(symbol)}\s*(?:=|\s)\s*(\d+)u", source
        )
        assert match is not None, symbol
        declared = int(match.group(1))
        expected = declared - 1 if resource["capacity_symbol"].endswith("-1") else declared
        assert resource["capacity"] == expected
        assert resource["implementation"] in (
            implementation
            + (FIRMWARE / "otis_capture_ring.cpp").read_text()
            + (FIRMWARE / "otis_pps_count_boundary_ring.cpp").read_text()
        )
    assert value["transport"]["maximum_supported_tx_obstruction_ms"] == 2000


def test_inventory_is_referenced_by_architecture_documents() -> None:
    for relative in (
        "docs/10_REFERENCE_ARCHITECTURE/CORE_PARTITIONING.md",
        "docs/50_SOFTWARE/HARDWARE_RESOURCE_OWNERSHIP.md",
    ):
        assert "otis_resource_inventory.json" in Path(relative).read_text()
