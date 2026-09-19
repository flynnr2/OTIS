import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_diagnostic_usb_admission_is_bounded_and_reserves_canonical_capacity(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("native compiler unavailable")
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
 size_t print(char) { return 1; }
 size_t print(const char*) { return 0; }
 size_t print(uint32_t) { return 0; }
 size_t write(const uint8_t*, size_t) { return 0; }
 int availableForWrite() { return 0; }
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
    harness = tmp_path / "test.cpp"
    harness.write_text("""
#include <assert.h>
#include <string.h>
#include <Arduino.h>
#include <USB.h>
#include "otis_transport_serial.h"
SerialStub Serial;
USBStub USB;
bool locked, contention, connected = true;
uint32_t capacity = 128u, attempts, exits, queries, writes;
char copied[256];
bool mutex_try_enter(mutex_t* m, uint32_t*) {
 assert(m == &USB.mutex); ++attempts;
 if (contention) return false;
 assert(!locked); locked = true; return true;
}
void mutex_exit(mutex_t*) { assert(locked); locked = false; ++exits; }
bool tud_cdc_connected() { assert(locked); ++queries; return connected; }
uint32_t tud_cdc_write_available() { assert(locked); ++queries; return capacity; }
uint32_t tud_cdc_write(const void* p, uint32_t n) {
 assert(locked && n <= capacity); ++writes;
 memcpy(copied, p, n); capacity -= n; return n;
}
uint32_t tud_cdc_write_flush() { assert(locked); return 0u; }
int main() {
 const uint8_t row[] = "diagnostic\\n";
 const uint32_t n = sizeof(row) - 1u;
 assert(!otis_transport_try_write_diagnostic(nullptr, n));
 assert(!otis_transport_try_write_diagnostic(row, 0));
 assert(!otis_transport_try_write_diagnostic(row, 65536u));
 assert(attempts == 0);
 contention = true;
 assert(!otis_transport_try_write_diagnostic(row, n));
 assert(attempts == 1 && exits == 0 && queries == 0 && writes == 0);
 contention = false; connected = false;
 assert(!otis_transport_try_write_diagnostic(row, n));
 assert(exits == 1 && queries == 1 && !locked);
 connected = true; capacity = n + 63u;
 assert(!otis_transport_try_write_diagnostic(row, n));
 assert(exits == 2 && writes == 0 && !locked);
 capacity = n + 64u;
 assert(otis_transport_try_write_diagnostic(row, n));
 assert(exits == 3 && writes == 1 && capacity == 64u && !locked);
 assert(memcmp(copied, row, n) == 0);
 assert(otis_transport_written_bytes() == n);
 assert(!otis_transport_try_write_diagnostic(row, n));
 assert(writes == 1 && otis_transport_written_bytes() == n && !locked);
 // The pending canonical row yields on congestion or lock contention.
 uint8_t canonical[256]; memset(canonical, 'S', sizeof(canonical));
 const auto initial = otis_transport_written_bytes();
 contention = true;
 assert(otis_transport_try_write_canonical(canonical, 256u) == 0u);
 contention = false; capacity = 0u;
 assert(otis_transport_try_write_canonical(canonical, 256u) == 0u);
 assert(otis_transport_written_bytes() == initial);
 capacity = 256u;
 assert(otis_transport_try_write_canonical(canonical, 256u) == 192u);
 assert(capacity == 64u && !locked);
 assert(otis_transport_try_write_canonical(canonical + 192u, 64u) == 64u);
 assert(capacity == 0u && otis_transport_written_bytes() == initial + 256u);
 connected = false; capacity = 256u;
 assert(otis_transport_try_write_canonical(canonical, 256u) == 0u);
 assert(!locked && capacity == 256u);
}
""")
    executable = tmp_path / "diagnostic_transport"
    subprocess.run([
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-I", str(tmp_path), "-I", str(FIRMWARE), str(harness),
        str(FIRMWARE / "otis_transport_serial.cpp"), "-o", str(executable),
    ], check=True)
    subprocess.run([str(executable)], check=True)


def test_diagnostic_admission_never_polls_or_uses_blocking_serial_wrapper():
    source = (FIRMWARE / "otis_transport_serial.cpp").read_text()
    body = source.split("bool otis_transport_try_write_diagnostic(", 1)[1]
    body = body.split("size_t otis_transport_write_uint32", 1)[0]
    code = "\n".join(line.split("//", 1)[0] for line in body.splitlines())
    for forbidden in ("Serial.", "tud_task(", "CoreMutex", "while (", "for (",
                      "mutex_enter_blocking", "delay(", "sleep_"):
        assert forbidden not in code
    assert code.count("mutex_try_enter(") == 1
    assert code.count("tud_cdc_write(") == 1
    assert code.count("mutex_exit(") == 1


def test_pending_canonical_usb_service_is_one_bounded_attempt():
    source = (FIRMWARE / "otis_transport_serial.cpp").read_text()
    body = source.split("size_t otis_transport_try_write_canonical(", 1)[1]
    body = body.split("bool otis_transport_try_write_diagnostic", 1)[0]
    for forbidden in ("Serial.", "tud_task(", "CoreMutex", "while (", "for (",
                      "mutex_enter_blocking", "delay(", "sleep_"):
        assert forbidden not in body
    assert body.count("mutex_try_enter(") == 1
    assert body.count("tud_cdc_write(") == 1
    assert body.count("mutex_exit(") == 1
    assert "chunk > 192u" in body
