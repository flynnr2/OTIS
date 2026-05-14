#include "otis_dac_ad5693r.h"

#if OTIS_ENABLE_DAC_AD5693R
#include <Arduino.h>
#include <Wire.h>
#endif

namespace {

constexpr uint8_t kDacAddress = static_cast<uint8_t>(OTIS_DAC_AD5693R_I2C_ADDRESS);
constexpr uint16_t kDacMinCode = static_cast<uint16_t>(OTIS_DAC_MIN_CODE);
constexpr uint16_t kDacMaxCode = static_cast<uint16_t>(OTIS_DAC_MAX_CODE);

bool dac_initialized = false;
bool dac_last_write_ok = false;
uint16_t dac_last_requested_code = 0u;
uint16_t dac_last_applied_code = kDacMinCode;

void fill_status(OtisDacAd5693rStatus *out) {
  if (out == nullptr) {
    return;
  }

  out->enabled = otis_dac_ad5693r_is_enabled();
  out->initialized = dac_initialized;
  out->last_write_ok = dac_last_write_ok;
  out->i2c_address = kDacAddress;
  out->min_code = kDacMinCode;
  out->max_code = kDacMaxCode;
  out->last_requested_code = dac_last_requested_code;
  out->last_applied_code = dac_last_applied_code;
  out->gain_mode = "1x";
  out->reference_mode = "external_or_breakout_default";
}

}  // namespace

bool otis_dac_ad5693r_begin(void) {
#if OTIS_ENABLE_DAC_AD5693R
  Wire.begin();
  Wire.beginTransmission(kDacAddress);
  uint8_t result = Wire.endTransmission();
  dac_initialized = (result == 0u);
  dac_last_write_ok = dac_initialized;
  return dac_initialized;
#else
  dac_initialized = false;
  dac_last_write_ok = false;
  return false;
#endif
}

bool otis_dac_ad5693r_reset(void) {
#if OTIS_ENABLE_DAC_AD5693R
  Wire.beginTransmission(0x00);
  Wire.write(0x06);
  uint8_t result = Wire.endTransmission();
  dac_last_write_ok = (result == 0u);
  if (dac_last_write_ok) {
    delay(1);
  }
  return dac_last_write_ok;
#else
  dac_last_write_ok = false;
  return false;
#endif
}

uint16_t otis_dac_ad5693r_clamp_code(uint16_t code) {
  if (code < kDacMinCode) {
    return kDacMinCode;
  }
  if (code > kDacMaxCode) {
    return kDacMaxCode;
  }
  return code;
}

bool otis_dac_ad5693r_set_raw(uint16_t code) {
  dac_last_requested_code = code;
  uint16_t clamped_code = otis_dac_ad5693r_clamp_code(code);

#if OTIS_ENABLE_DAC_AD5693R
  if (!dac_initialized) {
    dac_last_write_ok = false;
    return false;
  }

  Wire.beginTransmission(kDacAddress);
  Wire.write(0x30);  // AD5693R write-and-update DAC register command.
  Wire.write(static_cast<uint8_t>(clamped_code >> 8));
  Wire.write(static_cast<uint8_t>(clamped_code & 0xFFu));
  uint8_t result = Wire.endTransmission();
  dac_last_write_ok = (result == 0u);
  if (dac_last_write_ok) {
    dac_last_applied_code = clamped_code;
  }
  return dac_last_write_ok;
#else
  (void)clamped_code;
  dac_last_write_ok = false;
  return false;
#endif
}

bool otis_dac_ad5693r_is_enabled(void) {
#if OTIS_ENABLE_DAC_AD5693R
  return true;
#else
  return false;
#endif
}

bool otis_dac_ad5693r_is_initialized(void) {
  return dac_initialized;
}

void otis_dac_ad5693r_get_status(OtisDacAd5693rStatus *out) {
  fill_status(out);
}
