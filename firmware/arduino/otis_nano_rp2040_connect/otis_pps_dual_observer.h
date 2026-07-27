#ifndef OTIS_PPS_DUAL_OBSERVER_H
#define OTIS_PPS_DUAL_OBSERVER_H

#include <stdint.h>

struct OtisPpsDualObserverStats {
  uint32_t d10_raw_edge_count;
  uint64_t d10_last_edge_timestamp;
  uint64_t d10_last_interval;
  uint32_t d10_short_interval_count;
  uint32_t d10_long_interval_count;
  uint32_t d10_sampled_high_count;
  uint32_t d10_sampled_low_count;
  uint32_t d10_buffer_overflow_count;
  uint32_t d10_buffered_event_count;
  uint32_t d10_consumed_event_count;
  uint32_t pps_burst_count;
  bool pps_burst_active;
  uint64_t pps_burst_start;
  uint64_t pps_burst_last_event;
  uint32_t pps_burst_d10_edges;
  uint32_t pps_burst_d10_short;
};

bool otis_pps_dual_observer_begin(uint32_t d10_gpio);
void otis_pps_dual_observer_service(void);
void otis_pps_dual_observer_get_stats(OtisPpsDualObserverStats *out);

#endif
