#ifndef OTIS_DAC_AD5693R_H
#define OTIS_DAC_AD5693R_H

#include <stdint.h>

#include "otis_config.h"

struct OtisDacAd5693rStatus {
  bool enabled;
  bool initialized;
  bool last_write_ok;
  uint8_t i2c_address;
  uint16_t min_code;
  uint16_t max_code;
  uint16_t last_requested_code;
  uint16_t last_applied_code;
  const char *gain_mode;
  const char *reference_mode;
};

bool otis_dac_ad5693r_begin(void);
bool otis_dac_ad5693r_reset(void);
bool otis_dac_ad5693r_set_raw(uint16_t code);
bool otis_dac_ad5693r_is_enabled(void);
bool otis_dac_ad5693r_is_initialized(void);
uint16_t otis_dac_ad5693r_clamp_code(uint16_t code);
void otis_dac_ad5693r_get_status(OtisDacAd5693rStatus *out);

#endif
