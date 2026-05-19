#ifndef OTIS_ENV_SENSORS_H
#define OTIS_ENV_SENSORS_H

#include <stdint.h>

#include "otis_config.h"

struct OtisEnvSensorStatus {
  bool sht4x_enabled;
  bool sht4x_initialized;
  bool sht4x_last_read_ok;
  uint8_t sht4x_i2c_address;
  bool bmp280_enabled;
  bool bmp280_initialized;
  bool bmp280_last_read_ok;
  uint8_t bmp280_i2c_address;
  uint32_t sample_period_ms;
};

struct OtisEnvSample {
  bool valid;
  const char *source;
  const char *role;
  float temperature_c;
  bool has_humidity;
  float relative_humidity_pct;
  bool has_pressure;
  float pressure_pa;
};

bool otis_env_sensors_begin(void);
bool otis_env_sensors_read_sht4x(OtisEnvSample *out);
bool otis_env_sensors_read_bmp280(OtisEnvSample *out);
void otis_env_sensors_get_status(OtisEnvSensorStatus *out);

#endif
