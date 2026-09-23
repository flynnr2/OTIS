from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
SKETCH = FIRMWARE / "otis_nano_rp2040_connect.ino"
OUTPUT_TAKES = (
    "otis_dual_core_take_observation", "otis_dual_core_take_monitor_observation",
    "otis_dual_core_take_critical", "otis_dual_core_take_telemetry",
    "otis_dual_core_take_evidence", "otis_dual_core_take_phase_preview",
)


def function_body(source: str, name: str) -> str:
    match = re.search(rf"\b{name}\s*\([^;{{}}]*\)\s*\{{", source)
    assert match, name
    start = match.end() - 1
    depth = 0
    for end in range(start, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[start + 1:end]
    raise AssertionError(f"unclosed {name}")


def test_output_queue_consumers_are_reachable_only_from_core0_sketch_roots():
    source = SKETCH.read_text()
    source = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S)
    names = set(re.findall(r"^[A-Za-z_][\w:*&<> ]*\s+(\w+)\s*\([^;{}]*\)\s*\{", source, re.M))
    bodies = {name: function_body(source, name) for name in names}

    def reachable(root):
        reached, pending = set(), [root]
        while pending:
            name = pending.pop()
            if name in reached:
                continue
            reached.add(name)
            calls = set(re.findall(r"\b(\w+)\s*\(", bodies[name]))
            pending.extend((calls & names) - reached)
        return reached

    timing = reachable("setup1") | reachable("loop1")
    service = reachable("setup") | reachable("loop")
    consumers = {name for name, body in bodies.items() if any(f"{take}(" in body for take in OUTPUT_TAKES)}
    assert consumers & service  # Discover actual production consumers.
    assert consumers.isdisjoint(timing), consumers & timing
    assert (consumers & (service | timing)) <= service
    # Late attach and detach keep Core 0 live and draining, including the boot
    # handshake: neither core waits for host presence to service its own plane.
    assert "discard_dual_core_outputs_before_first_carrier()" in bodies["setup"]
    loop = bodies["loop"]
    absent = loop[loop.index("if (!otis_transport_ready())"):loop.index("bool frame_active")]
    assert "discard_dual_core_outputs_before_first_carrier()" in absent
    assert "service_instrument_executor()" in loop[:loop.index("if (!otis_transport_ready())")]
    assert "service_serial_commands(false);" in absent
    assert "otis_transport_ready()" not in bodies["loop1"]
    for service_call in ("drain_reference_snapshots()", "service_tcxo_gate()"):
        assert service_call in bodies["loop1"]
