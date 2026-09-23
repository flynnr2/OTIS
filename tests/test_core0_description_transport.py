"""Exercise the sketch's provenance cursor through the real STS serializer and row queue."""

import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def _description_source() -> str:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text()
    start = sketch.index("void service_core0_description(void) {")
    opening = sketch.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (sketch[end] == "{") - (sketch[end] == "}")
        end += 1
    return sketch[start:end]


def test_actual_core0_description_survives_stalled_then_healthy_usb(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("native C++ compiler unavailable")
    (tmp_path / "pico").mkdir()
    (tmp_path / "pico/mutex.h").write_text("""
#pragma once
#include <stdint.h>
struct mutex_t {};
bool mutex_try_enter(mutex_t*, uint32_t*);
void mutex_exit(mutex_t*);
""")
    (tmp_path / "USB.h").write_text("""
#pragma once
#include <pico/mutex.h>
struct USBStub { mutex_t mutex; };
extern USBStub USB;
""")
    (tmp_path / "Arduino.h").write_text("""
#pragma once
#include <stddef.h>
#include <stdint.h>
struct SerialStub {
 void begin(uint32_t) {}
 operator bool() { return true; }
};
extern SerialStub Serial;
""")
    (tmp_path / "tusb.h").write_text("""
#pragma once
#include <stdint.h>
bool tud_cdc_connected();
uint32_t tud_cdc_write_available();
uint32_t tud_cdc_write(const void*, uint32_t);
uint32_t tud_cdc_write_flush();
""")

    cursor = _description_source()
    macro_names = set(re.findall(r"\bOTIS_[A-Z0-9_]+\b", cursor))
    excluded = {
        "OTIS_SEVERITY_INFO", "OTIS_FLAG_NONE",
        "OTIS_FLAG_CONFIGURATION_ASSUMPTION", "OTIS_INSTRUMENT_START_CODE",
    }
    definitions = "\n".join(
        f'#define {name} "{name}"' for name in sorted(macro_names - excluded)
    )
    harness = tmp_path / "description.cpp"
    harness.write_text(f"""
#include <assert.h>
#include <stdio.h>
#include <string>
#include <Arduino.h>
#include <USB.h>
#include "otis_emit.h"
#include "otis_protocol.h"
#include "otis_transport_serial.h"
#define OTIS_INSTRUMENT_START_CODE 43000u
{definitions}
SerialStub Serial;
USBStub USB;
static bool locked = false;
static bool contention = false;
static uint32_t capacity = 64u;
static std::string wire;
bool mutex_try_enter(mutex_t*, uint32_t*) {{
  if (contention) return false;
  assert(!locked); locked = true; return true;
}}
void mutex_exit(mutex_t*) {{ assert(locked); locked = false; }}
bool tud_cdc_connected() {{ assert(locked); return true; }}
uint32_t tud_cdc_write_available() {{ assert(locked); return capacity; }}
uint32_t tud_cdc_write(const void* data, uint32_t count) {{
  assert(locked && count + 64u <= capacity);
  wire.append(static_cast<const char*>(data), count);
  capacity -= count;
  return count;
}}
uint32_t tud_cdc_write_flush() {{ assert(locked); return 0u; }}
static uint32_t status_sequence = 0u;
static bool core0_description_pending = true;
static uint16_t core0_description_cursor = 0u;
static uint32_t core0_description_generation = 7u;
struct BootSnapshot {{ uint32_t current_reset_reason; }};
BootSnapshot otisBootBreadcrumbSnapshot() {{ return {{42u}}; }}
void emit_status_direct(const char* component, const char* key,
                        const char* value, const char* severity,
                        uint32_t flags) {{
  otis_emit_health(++status_sequence, 100u, "rp2040_monotonic_us32",
                   component, key, value, severity, flags);
}}
void emit_status_u32(const char* component, const char* key,
                     uint32_t value, const char* severity, uint32_t flags) {{
  char decimal[11];
  snprintf(decimal, sizeof(decimal), "%lu", static_cast<unsigned long>(value));
  emit_status_direct(component, key, decimal, severity, flags);
}}
{cursor}
int main() {{
  otis_transport_begin(115200u);
  service_core0_description();
  service_core0_description();
  assert(core0_description_cursor == 2u);
  assert(otis_transport_row_free_slots() == 0u);
  contention = true;
  for (unsigned i = 0u; i < 100u; ++i) {{
    otis_transport_service_row();
    service_core0_description();
  }}
  assert(core0_description_cursor == 2u);
  assert(otis_transport_row_dropped() == 0u);
  assert(wire.empty());
  contention = false;
  for (unsigned i = 0u;
       i < 500u && (core0_description_pending || otis_transport_row_pending());
       ++i) {{
    capacity = 4096u;  // host drains each service cycle
    otis_transport_service_row();
    service_core0_description();
  }}
  assert(!core0_description_pending && !otis_transport_row_pending());
  assert(otis_transport_row_dropped() == 0u);
  assert(!locked);
  fwrite(wire.data(), 1u, wire.size(), stdout);
}}
""")
    executable = tmp_path / "description"
    subprocess.run([
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-I", str(tmp_path), "-I", str(FIRMWARE), str(harness),
        str(FIRMWARE / "otis_emit.cpp"),
        str(FIRMWARE / "otis_transport_serial.cpp"),
        "-o", str(executable),
    ], check=True)
    result = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
    rows = [line.removesuffix("\r").split(",") for line in result.stdout.splitlines()]
    expected_fields = re.findall(r'\{"([a-z0-9_]+)","([a-z0-9_]+)",', cursor)
    assert len(expected_fields) == 38
    expected = Counter(expected_fields)
    expected.update({
        ("configuration", "generation_begin"): 1,
        ("boot", "reset_reason"): 1,
        ("instrument", "startup_code"): 1,
        ("configuration", "generation_complete"): 1,
    })
    assert len(rows) == 42
    assert all(len(row) == 10 and row[0:2] == ["STS", "1"] for row in rows)
    assert Counter((row[5], row[6]) for row in rows) == expected
    assert [int(row[2]) for row in rows] == list(range(1, 43))
    assert rows[0][5:8] == ["configuration", "generation_begin", "7"]
    assert rows[-1][5:8] == ["configuration", "generation_complete", "7"]
    assert {"contract_sha256", "source_hash", "config_hash", "provenance_hash",
            "plant_model_sha256", "response_sha256", "boot_mode"} <= {
                row[6] for row in rows
            }
