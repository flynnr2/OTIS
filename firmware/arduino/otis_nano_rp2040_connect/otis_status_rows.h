#ifndef OTIS_STATUS_ROWS_H
#define OTIS_STATUS_ROWS_H

#include <stddef.h>
#include <stdint.h>
#include "otis_status_emit.h"

// One retained, complete periodic STS row. The caller owns the serial stream
// until sent == length; formatting never writes to USB or allocates memory.
struct OtisStatusFrame {
  char data[384];
  uint16_t length;
  uint16_t sent;
};

// Visit a fixed immutable status view, formatting only the selected row.
// This keeps field definitions shared with full CONFIG emission without a
// second queue or a copy of the entire formatted report. Nonselected numeric
// fields do not run printf. A traversal has a fixed, finite field count.
class OtisStatusRows {
 public:
  explicit OtisStatusRows(OtisStatusEmitContext *context);
  OtisStatusRows(OtisStatusFrame *frame, uint16_t selected,
                 uint32_t sequence, uint32_t emission_ticks);
  void text(const char *component, const char *key, const char *value,
            const char *severity, uint32_t flags);
  void u32(const char *component, const char *key, uint32_t value,
           const char *severity, uint32_t flags);
  void u64(const char *component, const char *key, uint64_t value,
           const char *severity, uint32_t flags);
  bool selected() const { return selected_ < visited_; }
  bool last() const { return selected_ + 1u == visited_; }
  bool valid() const { return valid_; }
 private:
  bool take();
  void emit(const char *, const char *, const char *, const char *, uint32_t);
  OtisStatusEmitContext *context_ = nullptr;
  OtisStatusFrame *frame_ = nullptr;
  uint16_t selected_ = 0u;
  uint16_t visited_ = 0u;
  uint32_t sequence_ = 0u;
  uint32_t ticks_ = 0u;
  bool valid_ = true;
};

#endif
