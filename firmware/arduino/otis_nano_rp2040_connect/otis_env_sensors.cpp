#include "otis_env_sensors.h"

#include <Adafruit_BMP280.h>
#include <Adafruit_SHT4x.h>
#include <math.h>

#include "otis_i2c_bus.h"

namespace {
constexpr uint8_t kSht4xAddress = static_cast<uint8_t>(OTIS_ENV_SHT4X_I2C_ADDRESS);
constexpr uint8_t kBmp280Address = static_cast<uint8_t>(OTIS_ENV_BMP280_I2C_ADDRESS);
constexpr uint32_t kSamplePeriodMs = OTIS_ENV_SAMPLE_PERIOD_MS;
static_assert(kSht4xAddress == SHT4x_DEFAULT_ADDR,
              "Pinned Adafruit SHT4x driver supports the fitted 0x44 address");
Adafruit_SHT4x sht4x;
Adafruit_BMP280 bmp280;
bool sht4x_initialized = false;
bool sht4x_last_read_ok = false;
bool bmp280_initialized = false;
bool bmp280_last_read_ok = false;

void fill_status(OtisEnvSensorStatus *out) {
  if (out == nullptr) {
    return;
  }
  out->sht4x_enabled = true;
  out->sht4x_initialized = sht4x_initialized;
  out->sht4x_last_read_ok = sht4x_last_read_ok;
  out->sht4x_i2c_address = kSht4xAddress;
  out->bmp280_enabled = true;
  out->bmp280_initialized = bmp280_initialized;
  out->bmp280_last_read_ok = bmp280_last_read_ok;
  out->bmp280_i2c_address = kBmp280Address;
  out->sample_period_ms = kSamplePeriodMs;
}

}  // namespace

bool otis_env_sensors_begin(void) {
  if (!otis_i2c_bus_begin()) return false;
  sht4x_initialized = sht4x.begin(&Wire);
  sht4x.setPrecision(SHT4X_HIGH_PRECISION);
  sht4x.setHeater(SHT4X_NO_HEATER);
  sht4x_last_read_ok = false;

  bmp280_initialized = bmp280.begin(kBmp280Address);
  if (bmp280_initialized) {
    // Enter sleep before changing config; preserve x1 oversampling, no filter,
    // normal measurement mode and the existing 1000 ms standby interval.
    bmp280.clearIOStatus();
    bmp280.setSampling(Adafruit_BMP280::MODE_SLEEP);
    const uint32_t sleep_started_ms = millis();
    while (bmp280.ioOK() && (bmp280.getStatus() & 0x08u) != 0u) {
      if (static_cast<uint32_t>(millis() - sleep_started_ms) >= 100u) {
        bmp280_initialized = false;
        break;
      }
      delay(1);
    }
    if (bmp280_initialized && bmp280.ioOK())
      bmp280.setSampling(Adafruit_BMP280::MODE_NORMAL,
                      Adafruit_BMP280::SAMPLING_X1,
                      Adafruit_BMP280::SAMPLING_X1,
                      Adafruit_BMP280::FILTER_OFF,
                      Adafruit_BMP280::STANDBY_MS_1000);
    bmp280_initialized = bmp280_initialized && bmp280.ioOK();
  }
  bmp280_last_read_ok = false;
  return sht4x_initialized && bmp280_initialized;
}

bool otis_env_sensors_read_sht4x(OtisEnvSample *out) {
  if (out == nullptr) return false;
  *out = {};
  out->source = "sht4x";
  out->role = "vcocxo_near";
  out->has_humidity = true;
  sensors_event_t humidity = {}, temperature = {};
  // Use the combined API: its return carries read/CRC failure. The individual
  // Unified Sensor wrappers discard that result in the pinned library.
  out->valid = sht4x_initialized && sht4x.getEvent(&humidity, &temperature) &&
               isfinite(temperature.temperature) && isfinite(humidity.relative_humidity);
  if (out->valid) {
    out->temperature_c = temperature.temperature;
    out->relative_humidity_pct = humidity.relative_humidity;
  }
  sht4x_last_read_ok = out->valid;
  return out->valid;
}

bool otis_env_sensors_read_bmp280(OtisEnvSample *out) {
  if (out == nullptr) return false;
  *out = {};
  out->source = "bmp280";
  out->role = "pressure_reference";
  out->has_pressure = true;
  out->valid = bmp280_initialized &&
      bmp280.readSample(&out->temperature_c, &out->pressure_pa);
  bmp280_last_read_ok = out->valid;
  return out->valid;
}

void otis_env_sensors_get_status(OtisEnvSensorStatus *out) {
  fill_status(out);
}
