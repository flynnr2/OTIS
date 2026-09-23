#include "otis_transport_serial.h"

#include <Arduino.h>
#include <stdio.h>
#include <string.h>
#include <USB.h>
#include <pico/mutex.h>
#include <tusb.h>

#if defined(USE_TINYUSB) || defined(NO_USB) || defined(__FREERTOS)
#error "OTIS diagnostic transport requires the pinned bare-metal Arduino-Pico USB backend"
#endif

namespace {
uint64_t written_bytes = 0u;
constexpr size_t kReservedBytes = 64u;
constexpr size_t kMaximumFrameChunk = 192u;
constexpr size_t kRowCapacity = 1536u;
constexpr size_t kRowQueueDepth = 2u;

struct OutboundRow {
  char data[kRowCapacity];
  uint16_t length;
};

OutboundRow rows[kRowQueueDepth] = {};
char building_row[kRowCapacity] = {};
uint16_t building_length = 0u;
bool building_overflow = false;
uint8_t row_head = 0u;
uint8_t row_tail = 0u;
uint8_t row_count = 0u;
uint16_t active_offset = 0u;
bool active_row = false;
uint32_t dropped_rows = 0u;

void note_row_drop() {
  if (dropped_rows != UINT32_MAX) ++dropped_rows;
}

void finish_row() {
  if (building_overflow || building_length == 0u ||
      row_count == kRowQueueDepth) {
    note_row_drop();
  } else {
    OutboundRow &row = rows[row_tail];
    memcpy(row.data, building_row, building_length);
    row.length = building_length;
    row_tail = static_cast<uint8_t>((row_tail + 1u) % kRowQueueDepth);
    ++row_count;
  }
  building_length = 0u;
  building_overflow = false;
}

size_t append_rows(const char *data, size_t length) {
  if (data == nullptr) return 0u;
  for (size_t i = 0u; i < length; ++i) {
    const char c = data[i];
    if (!building_overflow) {
      if (building_length < kRowCapacity)
        building_row[building_length++] = c;
      else
        building_overflow = true;
    }
    if (c == '\n') finish_row();
  }
  return length;
}

size_t note_written(size_t count) {
  written_bytes += count;
  return count;
}
}  // namespace

bool otis_transport_begin(uint32_t baud) {
  building_length = 0u;
  building_overflow = false;
  row_head = row_tail = row_count = 0u;
  active_offset = 0u;
  active_row = false;
  dropped_rows = 0u;
  Serial.begin(baud);
  return true;
}

size_t otis_transport_write_char(char c) {
  return append_rows(&c, 1u);
}

size_t otis_transport_write_cstr(const char *s) {
  return s == nullptr ? 0u : append_rows(s, strlen(s));
}

size_t otis_transport_try_write_frame_chunk(const uint8_t *data,
                                            size_t length) {
  if (data == nullptr || length == 0u || length > kMaximumFrameChunk)
    return 0u;
  if (!mutex_try_enter(&USB.mutex, nullptr)) return 0u;
  size_t accepted = 0u;
  if (tud_cdc_connected() &&
      tud_cdc_write_available() >= length + kReservedBytes) {
    const size_t written = tud_cdc_write(data, static_cast<uint32_t>(length));
    // TinyUSB only auto-flushes a full packet. Schedule the final short
    // packet without polling USB or waiting for endpoint completion.
    if (written != 0u) tud_cdc_write_flush();
    accepted = note_written(written);
  }
  mutex_exit(&USB.mutex);
  return accepted;
}

bool otis_transport_try_write_diagnostic(const uint8_t *data, size_t length) {
  // Pinned Arduino-Pico 6.1.0: USBClass::usbIRQ and SerialUSB serialize
  // TinyUSB state under USB.mutex. CoreMutex(false) is NOT nonblocking on
  // cross-core contention, so use a single native try-enter instead.
  if (data == nullptr || length == 0u || length > UINT16_MAX) return false;
  if (!mutex_try_enter(&USB.mutex, nullptr)) return false;
  bool accepted = false;
  if (tud_cdc_connected() &&
      tud_cdc_write_available() >= length + kReservedBytes) {
    // cdc_device.c writes at most UINT16_MAX to the FIFO. Capacity admission
    // and this copy share the USB lock: neither another writer nor tud_task's
    // disconnect/reset callbacks can interleave. The optional auto-flush inside
    // tud_cdc_write only covers a full packet; flush also schedules a short
    // final packet without polling or waiting for delivery.
    const size_t written = tud_cdc_write(data, static_cast<uint32_t>(length));
    if (written != 0u) tud_cdc_write_flush();
    note_written(written);
    accepted = written == length;
  }
  mutex_exit(&USB.mutex);
  return accepted;
}

size_t otis_transport_write_uint32(uint32_t v) {
  char decimal[11] = {};
  const int length = snprintf(decimal, sizeof(decimal), "%lu",
                              static_cast<unsigned long>(v));
  return length > 0 && static_cast<size_t>(length) < sizeof(decimal)
             ? append_rows(decimal, static_cast<size_t>(length)) : 0u;
}

size_t otis_transport_available_for_write(void) {
  if (!mutex_try_enter(&USB.mutex, nullptr)) return 0u;
  size_t available = 0u;
  if (tud_cdc_connected()) {
    const size_t raw = tud_cdc_write_available();
    if (raw > kReservedBytes) available = raw - kReservedBytes;
  }
  mutex_exit(&USB.mutex);
  return available;
}

void otis_transport_flush_if_needed(void) {
  // Future output-budgeting hook: serial backpressure detection can decide
  // whether flushing is safe once capture-first loop service is enforced.
}

bool otis_transport_ready(void) {
  return Serial;
}

uint64_t otis_transport_written_bytes(void) { return written_bytes; }

bool otis_transport_row_pending(void) { return active_row || row_count != 0u; }

bool otis_transport_row_active(void) { return active_row; }

uint32_t otis_transport_row_free_slots(void) {
  return static_cast<uint32_t>(kRowQueueDepth - row_count);
}

void otis_transport_service_row(void) {
  if (!active_row) {
    if (row_count == 0u) return;
    active_offset = 0u;
    active_row = true;
  }
  const OutboundRow &row = rows[row_head];
  const size_t remaining = row.length - active_offset;
  const size_t chunk = remaining < kMaximumFrameChunk
                           ? remaining : kMaximumFrameChunk;
  active_offset = static_cast<uint16_t>(active_offset +
      otis_transport_try_write_frame_chunk(
          reinterpret_cast<const uint8_t *>(row.data) + active_offset,
          chunk));
  if (active_offset != row.length) return;
  active_row = false;
  active_offset = 0u;
  row_head = static_cast<uint8_t>((row_head + 1u) % kRowQueueDepth);
  --row_count;
}

void otis_transport_discard_rows(void) {
  while (row_count != 0u) {
    note_row_drop();
    --row_count;
  }
  if (building_length != 0u || building_overflow) note_row_drop();
  building_length = 0u;
  building_overflow = false;
  row_head = row_tail = 0u;
  active_offset = 0u;
  active_row = false;
}

uint32_t otis_transport_row_dropped(void) { return dropped_rows; }
