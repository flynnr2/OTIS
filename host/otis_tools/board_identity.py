"""Identity check for the accepted OTIS Arduino Nano RP2040 bench board."""

from __future__ import annotations

import json
import subprocess


EXPECTED_SERIAL = "503533748A919118"
EXPECTED_VID = "0x2341"
EXPECTED_PID = "0x005E"
EXPECTED_FQBN = "rp2040:rp2040:arduino_nano_connect"


def read_board_identity(
    device: str, *, arduino_cli: str = "arduino-cli"
) -> dict[str, str]:
    value = json.loads(
        subprocess.run(
            [arduino_cli, "board", "list", "--format", "json"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )
    matches = [
        item
        for item in value.get("detected_ports", [])
        if item.get("port", {}).get("address") == device
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one board at {device}, got {len(matches)}"
        )
    item = matches[0]
    port = item["port"]
    properties = port.get("properties", {})
    boards = item.get("matching_boards", [])
    identity = {
        "address": str(port.get("address", "")),
        "hardware_id": str(
            port.get("hardware_id", item.get("hardware_id", ""))
        ),
        "serial_number": str(properties.get("serialNumber", "")),
        "vid": str(properties.get("vid", "")),
        "pid": str(properties.get("pid", "")),
        "product": str(properties.get("product", "")),
        "board_name": (
            str(boards[0].get("name", "")) if len(boards) == 1 else ""
        ),
        "board_fqbn": (
            str(boards[0].get("fqbn", "")) if len(boards) == 1 else ""
        ),
    }
    if (
        identity["serial_number"] != EXPECTED_SERIAL
        or identity["hardware_id"] != EXPECTED_SERIAL
        or identity["vid"].lower() != EXPECTED_VID.lower()
        or identity["pid"].lower() != EXPECTED_PID.lower()
        or identity["board_fqbn"] != EXPECTED_FQBN
    ):
        raise ValueError(
            "connected board identity differs from the accepted OTIS bench board"
        )
    return identity
