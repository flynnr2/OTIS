#include "otis_transport_serial.h"

#include <Arduino.h>
#include <USB.h>
#include <pico/mutex.h>
#include <tusb.h>

#if defined(USE_TINYUSB) || defined(NO_USB) || defined(__FREERTOS)
#error "OTIS diagnostic transport requires the pinned bare-metal Arduino-Pico USB backend"
#endif

namespace {
uint64_t written_bytes = 0u;

size_t note_written(size_t count) {
  written_bytes += count;
  return count;
}
}  // namespace

bool otis_transport_begin(uint32_t baud) {
  Serial.begin(baud);
  return true;
}

size_t otis_transport_write_char(char c) {
  return note_written(Serial.print(c));
}

size_t otis_transport_write_cstr(const char *s) {
  return note_written(Serial.print(s));
}

size_t otis_transport_write_bytes(const uint8_t *data, size_t length) {
  return note_written(Serial.write(data, length));
}

size_t otis_transport_try_write_canonical(const uint8_t *data, size_t length) {
  if (data == nullptr || length == 0u) return 0u;
  if (!mutex_try_enter(&USB.mutex, nullptr)) return 0u;
  size_t written = 0u;
  if (tud_cdc_connected()) {
    const size_t available = tud_cdc_write_available();
    size_t chunk = length < available ? length : available;
    if (chunk > 192u) chunk = 192u;
    if (chunk != 0u) {
      written = tud_cdc_write(data, static_cast<uint32_t>(chunk));
      // TinyUSB's flush only attempts to schedule one endpoint transfer; it
      // does not wait for USB or call tud_task. Include a short final packet.
      if (written != 0u) tud_cdc_write_flush();
    }
  }
  mutex_exit(&USB.mutex);
  return note_written(written);
}

bool otis_transport_try_write_diagnostic(const uint8_t *data, size_t length) {
  // Pinned Arduino-Pico 6.1.0: USBClass::usbIRQ and SerialUSB serialize
  // TinyUSB state under USB.mutex. CoreMutex(false) is NOT nonblocking on
  // cross-core contention, so use a single native try-enter instead.
  if (data == nullptr || length == 0u || length > UINT16_MAX) return false;
  if (!mutex_try_enter(&USB.mutex, nullptr)) return false;
  bool accepted = false;
  constexpr uint32_t reserved_bytes = 64u;
  if (tud_cdc_connected() &&
      tud_cdc_write_available() >= length + reserved_bytes) {
    // cdc_device.c writes at most UINT16_MAX to the FIFO. Capacity admission
    // and this copy share the USB lock: neither another writer nor tud_task's
    // disconnect/reset callbacks can interleave. The optional auto-flush inside
    // tud_cdc_write only schedules an endpoint transfer; it does not poll.
    const size_t written = tud_cdc_write(data, static_cast<uint32_t>(length));
    note_written(written);
    accepted = written == length;
  }
  mutex_exit(&USB.mutex);
  return accepted;
}

size_t otis_transport_write_uint32(uint32_t v) {
  return note_written(Serial.print(v));
}

size_t otis_transport_available_for_write(void) {
  if (!Serial) {
    return 0u;
  }
  int available = Serial.availableForWrite();
  return available > 0 ? (size_t)available : 0u;
}

void otis_transport_flush_if_needed(void) {
  // Future output-budgeting hook: serial backpressure detection can decide
  // whether flushing is safe once capture-first loop service is enforced.
}

bool otis_transport_ready(void) {
  return Serial;
}

uint64_t otis_transport_written_bytes(void) { return written_bytes; }
