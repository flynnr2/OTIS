from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

import pytest


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
    assert consumers  # The guard must actually discover the production calls.
    assert consumers <= service
    assert consumers.isdisjoint(timing), consumers & timing
    # Late attach and detach keep Core 0 live and draining, including the boot
    # handshake: neither core waits for host presence to service its own plane.
    assert "discard_dual_core_outputs_before_first_carrier()" in bodies["setup"]
    loop = bodies["loop"]
    absent = loop[loop.index("if (!otis_transport_ready())"):loop.index("bool frame_active")]
    assert "discard_dual_core_outputs_before_first_carrier()" in absent
    assert "discard_dual_core_outputs_after_transport_fault()" in absent
    assert "otis_transport_ready()" not in bodies["loop1"]
    for service_call in ("drain_pps_count_boundary_ring()", "drain_capture_ring()", "service_tcxo_gate()"):
        assert service_call in bodies["loop1"]


def test_actual_discard_bodies_share_one_concurrent_consumer_across_carrier_modes(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    sketch = SKETCH.read_text()
    discard_bodies = "\n".join(
        f"void {name}() {{ {function_body(sketch, name)} }}"
        for name in (
            "note_pre_carrier_discard", "discard_dual_core_outputs_before_first_carrier",
            "discard_dual_core_outputs_after_transport_fault",
        )
    )
    # Instrument the actual .ino discard bodies at the consumer API boundary.
    # The queue implementations themselves are linked unchanged below.
    for take in OUTPUT_TAKES:
        discard_bodies = discard_bodies.replace(take + "(", "checked_" + take + "(")
    source = r'''
#include <atomic>
#include <cassert>
#include <thread>
#include "otis_dual_core_partition.h"

uint32_t dual_core_pre_carrier_records_discarded = 0;
std::atomic<uint32_t> consumed[6]{};
thread_local bool consumer_thread = false;
constexpr uint32_t rounds = 10000;

#define CHECKED_TAKE(name, type, field, slot) \
bool checked_##name(type *message) { \
  assert(consumer_thread); \
  if (!name(message)) return false; \
  const uint32_t previous = consumed[slot].load(); \
  assert(message->field == previous + 1u); \
  consumed[slot].store(message->field); \
  return true; \
}
CHECKED_TAKE(otis_dual_core_take_observation, OtisObservationMessage, raw_edge.sequence, 0)
CHECKED_TAKE(otis_dual_core_take_monitor_observation, OtisMonitorObservationMessage, sequence, 1)
CHECKED_TAKE(otis_dual_core_take_critical, OtisCriticalRecordMessage, sequence, 2)
CHECKED_TAKE(otis_dual_core_take_telemetry, OtisTelemetryMessage, sequence, 3)
CHECKED_TAKE(otis_dual_core_take_evidence, OtisEvidenceFrameMessage, sequence, 4)
CHECKED_TAKE(otis_dual_core_take_phase_preview, OtisPhasePreviewRecordMessage, observation_sequence, 5)
''' + discard_bodies + r'''

// A live-delivery stand-in uses the same consumer APIs. Native validation here
// covers queue ownership/order and actual discard bodies, not USB formatting.
void deliver_one_round() {
  OtisObservationMessage observation{};
  OtisMonitorObservationMessage monitor{};
  OtisCriticalRecordMessage critical{};
  OtisTelemetryMessage telemetry{};
  OtisEvidenceFrameMessage evidence{};
  OtisPhasePreviewRecordMessage phase{};
  checked_otis_dual_core_take_observation(&observation);
  checked_otis_dual_core_take_monitor_observation(&monitor);
  checked_otis_dual_core_take_critical(&critical);
  checked_otis_dual_core_take_telemetry(&telemetry);
  checked_otis_dual_core_take_evidence(&evidence);
  checked_otis_dual_core_take_phase_preview(&phase);
}

int main() {
  otis_dual_core_partition_reset();
  std::thread producer([] {
    for (uint32_t sequence = 1; sequence <= rounds; ++sequence) {
      // Bound producer lead below every real queue capacity. Full-queue fault
      // policy has its own tests; this check targets concurrent SPSC ownership.
      for (unsigned slot = 0; slot < 6; ++slot)
        while (sequence - consumed[slot].load() > 4u) std::this_thread::yield();
      OtisObservationMessage observation{};
      observation.raw_edge.sequence = sequence;
      assert(otis_dual_core_publish_observation(&observation));
      OtisMonitorObservationMessage monitor{};
      monitor.sequence = sequence;
      assert(otis_dual_core_publish_monitor_observation(&monitor));
      OtisCriticalRecordMessage critical{};
      critical.sequence = sequence;
      assert(otis_dual_core_publish_critical(&critical));
      OtisTelemetryMessage telemetry{};
      telemetry.sequence = sequence;
      assert(otis_dual_core_publish_telemetry(&telemetry));
      OtisEvidenceFrameMessage evidence{};
      evidence.sequence = sequence;
      evidence.length = 1;
      evidence.data[0] = 'x';
      assert(otis_dual_core_publish_evidence(&evidence));
      OtisPhasePreviewRecordMessage phase{};
      phase.observation_sequence = sequence;
      assert(otis_dual_core_publish_phase_preview(&phase));
    }
  });
  std::thread consumer([] {
    consumer_thread = true;
    for (;;) {
      bool complete = true;
      for (unsigned slot = 0; slot < 6; ++slot) complete &= consumed[slot].load() == rounds;
      if (complete) break;
      // Bootstrap/attached/detached/reattached/faulted consumption all stays
      // on this one thread while the producer continues independently.
      const unsigned mode = (consumed[0].load() / 64u) % 5u;
      if (mode == 0 || mode == 2) discard_dual_core_outputs_before_first_carrier();
      else if (mode == 4) discard_dual_core_outputs_after_transport_fault();
      else deliver_one_round();
      std::this_thread::yield();
    }
  });
  producer.join();
  consumer.join();
  assert(dual_core_pre_carrier_records_discarded > 0);
  for (unsigned slot = 0; slot < 6; ++slot) assert(consumed[slot].load() == rounds);
  assert(!otis_dual_core_fail_static());
}
'''
    harness = tmp_path / "output_consumer.cpp"
    executable = tmp_path / "output_consumer"
    harness.write_text(source)
    subprocess.run([compiler, "-std=c++17", "-pthread", "-Wall", "-Wextra", "-Werror", "-I", str(FIRMWARE),
        str(harness), str(FIRMWARE / "otis_dual_core_partition.cpp"), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True, timeout=20)
