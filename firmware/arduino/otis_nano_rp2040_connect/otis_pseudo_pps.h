#ifndef OTIS_PSEUDO_PPS_H
#define OTIS_PSEUDO_PPS_H

#include <stddef.h>
#include <stdint.h>

#include "otis_pseudo_pps_schedule.h"

enum class OtisPseudoPpsState : uint8_t {
  Disabled = 0,
  Idle,
  Armed,
  Running,
  Complete,
  Aborted,
  ResourceFault,
  UnderflowFault,
};

struct OtisPseudoPpsStatus {
  OtisPseudoPpsState state;
  const char *profile_id;
  uint16_t profile_version;
  uint16_t step_count;
  uint16_t truth_emitted;
  uint32_t session;
  uint32_t pin_sample_count;
  uint32_t output_high_sample_count;
  uint32_t reference_high_sample_count;
  uint32_t system_clock_hz;
  uint32_t pio_clock_hz;
  int8_t pio_state_machine;
  int8_t dma_channel;
};

bool otis_pseudo_pps_begin(void);
bool otis_pseudo_pps_arm(const char *profile_id);
bool otis_pseudo_pps_start(void);
bool otis_pseudo_pps_stop(void);
void otis_pseudo_pps_latch_resource_fault(void);
void otis_pseudo_pps_service(void);
void otis_pseudo_pps_get_status(OtisPseudoPpsStatus *status);
const char *otis_pseudo_pps_state_name(OtisPseudoPpsState state);

#endif
