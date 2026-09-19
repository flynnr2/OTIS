#include "otis_status_rows.h"

#include <stdio.h>
#include "otis_protocol.h"

namespace {
bool append(OtisStatusFrame *frame, char value) {
  if (frame->length == sizeof(frame->data)) return false;
  frame->data[frame->length++] = value;
  return true;
}
bool text(OtisStatusFrame *frame, const char *value) {
  static const char hex[] = "0123456789ABCDEF";
  if (value == nullptr) return true;
  for (; *value; ++value) {
    const unsigned char byte = static_cast<unsigned char>(*value);
    if (byte == '%' || byte == ',' || byte == '"' || byte == '\r' || byte == '\n') {
      if (!append(frame, '%') || !append(frame, hex[byte >> 4u]) ||
          !append(frame, hex[byte & 15u])) return false;
    } else if (!append(frame, *value)) return false;
  }
  return true;
}
bool field(OtisStatusFrame *frame, const char *value) {
  return text(frame, value) && append(frame, ',');
}
bool number(OtisStatusFrame *frame, uint32_t value) {
  char buffer[11];
  snprintf(buffer, sizeof(buffer), "%lu", static_cast<unsigned long>(value));
  return field(frame, buffer);
}
}

OtisStatusRows::OtisStatusRows(OtisStatusEmitContext *context) : context_(context) {}
OtisStatusRows::OtisStatusRows(OtisStatusFrame *frame, uint16_t selected,
    uint32_t sequence, uint32_t emission_ticks)
    : frame_(frame), selected_(selected), sequence_(sequence), ticks_(emission_ticks) {
  frame_->length = frame_->sent = 0u;
}
bool OtisStatusRows::take() {
  return context_ != nullptr || visited_++ == selected_;
}
void OtisStatusRows::emit(const char *component, const char *key,
    const char *value, const char *severity, uint32_t flags) {
  if (context_ != nullptr) {
    otis_status_emit(context_, component, key, value, severity, flags);
    return;
  }
  valid_ = field(frame_, "STS") && number(frame_, 1u) &&
      number(frame_, sequence_) && number(frame_, ticks_) &&
      field(frame_, OTIS_DOMAIN_RP2040_MONOTONIC_US32) && field(frame_, component) &&
      field(frame_, key) && field(frame_, value) && field(frame_, severity);
  char buffer[11];
  snprintf(buffer, sizeof(buffer), "%lu", static_cast<unsigned long>(flags));
  valid_ = valid_ && ::text(frame_, buffer) && append(frame_, '\r') && append(frame_, '\n');
  // A formatting failure cannot leak a prefix into the canonical stream.
  if (!valid_) frame_->length = 0u;
}
void OtisStatusRows::text(const char *component, const char *key,
    const char *value, const char *severity, uint32_t flags) {
  if (take()) emit(component, key, value, severity, flags);
}
void OtisStatusRows::u32(const char *component, const char *key,
    uint32_t value, const char *severity, uint32_t flags) {
  if (!take()) return;
  char buffer[11];
  snprintf(buffer, sizeof(buffer), "%lu", static_cast<unsigned long>(value));
  emit(component, key, buffer, severity, flags);
}
void OtisStatusRows::u64(const char *component, const char *key,
    uint64_t value, const char *severity, uint32_t flags) {
  if (!take()) return;
  char buffer[21];
  snprintf(buffer, sizeof(buffer), "%llu", static_cast<unsigned long long>(value));
  emit(component, key, buffer, severity, flags);
}
