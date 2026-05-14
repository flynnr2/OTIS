#ifndef OTIS_CAPTURE_RING_H
#define OTIS_CAPTURE_RING_H

#include <stdint.h>

struct OtisCapturedEdge {
  uint32_t channel_id;
  bool reference_record;
  char edge;
  uint64_t timestamp_ticks;
  uint32_t flags;
};

void otis_capture_ring_reset(void);
bool otis_capture_ring_push_from_isr(uint32_t channel_id,
                                     bool reference_record,
                                     char edge);
bool otis_capture_ring_pop(OtisCapturedEdge *record);
void otis_capture_ring_note_drop(void);
uint32_t otis_capture_ring_dropped_count(void);
uint8_t otis_capture_ring_depth(void);

#endif
