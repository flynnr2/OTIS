#include "otis_env_sensors.h"

#if OTIS_ENABLE_ENV_SENSORS
#include <Arduino.h>
#include <Wire.h>
#endif

#include "otis_i2c_bus.h"

namespace {

constexpr uint8_t kSht4xAddress = static_cast<uint8_t>(OTIS_ENV_SHT4X_I2C_ADDRESS);
constexpr uint8_t kBmp280Address = static_cast<uint8_t>(OTIS_ENV_BMP280_I2C_ADDRESS);
constexpr uint32_t kSamplePeriodMs = OTIS_ENV_SAMPLE_PERIOD_MS;
constexpr uint8_t kBmp280ChipId = 0x58u;

bool sht4x_initialized = false;
bool sht4x_last_read_ok = false;
bool bmp280_initialized = false;
bool bmp280_last_read_ok = false;

struct Bmp280Calibration {
  uint16_t dig_t1;
  int16_t dig_t2;
  int16_t dig_t3;
  uint16_t dig_p1;
  int16_t dig_p2;
  int16_t dig_p3;
  int16_t dig_p4;
  int16_t dig_p5;
  int16_t dig_p6;
  int16_t dig_p7;
  int16_t dig_p8;
  int16_t dig_p9;
  int32_t t_fine;
  bool valid;
};

Bmp280Calibration bmp280_cal = {};

#if OTIS_ENABLE_ENV_SENSORS
bool i2c_probe(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0u;
}

uint8_t crc8_sht4x(const uint8_t *data, uint8_t len) {
  uint8_t crc = 0xFFu;
  for (uint8_t i = 0; i < len; ++i) {
    crc ^= data[i];
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc & 0x80u) ? static_cast<uint8_t>((crc << 1) ^ 0x31u)
                          : static_cast<uint8_t>(crc << 1);
    }
  }
  return crc;
}

bool read_registers(uint8_t address, uint8_t reg, uint8_t *buffer, uint8_t len) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0u) {
    return false;
  }
  uint8_t read_count = Wire.requestFrom(address, len);
  if (read_count != len) {
    while (Wire.available()) {
      (void)Wire.read();
    }
    return false;
  }
  for (uint8_t i = 0; i < len; ++i) {
    buffer[i] = static_cast<uint8_t>(Wire.read());
  }
  return true;
}

bool write_register8(uint8_t address, uint8_t reg, uint8_t value) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0u;
}

uint16_t u16_le(const uint8_t *buffer, uint8_t index) {
  return static_cast<uint16_t>(buffer[index]) |
         (static_cast<uint16_t>(buffer[index + 1]) << 8);
}

int16_t s16_le(const uint8_t *buffer, uint8_t index) {
  return static_cast<int16_t>(u16_le(buffer, index));
}

bool bmp280_read_calibration(void) {
  uint8_t cal[24];
  if (!read_registers(kBmp280Address, 0x88u, cal, sizeof(cal))) {
    return false;
  }
  bmp280_cal.dig_t1 = u16_le(cal, 0);
  bmp280_cal.dig_t2 = s16_le(cal, 2);
  bmp280_cal.dig_t3 = s16_le(cal, 4);
  bmp280_cal.dig_p1 = u16_le(cal, 6);
  bmp280_cal.dig_p2 = s16_le(cal, 8);
  bmp280_cal.dig_p3 = s16_le(cal, 10);
  bmp280_cal.dig_p4 = s16_le(cal, 12);
  bmp280_cal.dig_p5 = s16_le(cal, 14);
  bmp280_cal.dig_p6 = s16_le(cal, 16);
  bmp280_cal.dig_p7 = s16_le(cal, 18);
  bmp280_cal.dig_p8 = s16_le(cal, 20);
  bmp280_cal.dig_p9 = s16_le(cal, 22);
  bmp280_cal.valid = bmp280_cal.dig_t1 != 0u && bmp280_cal.dig_p1 != 0u;
  return bmp280_cal.valid;
}

float bmp280_compensate_temperature(int32_t adc_t) {
  int32_t var1 = ((((adc_t >> 3) - (static_cast<int32_t>(bmp280_cal.dig_t1) << 1))) *
                  static_cast<int32_t>(bmp280_cal.dig_t2)) >>
                 11;
  int32_t var2 = (((((adc_t >> 4) - static_cast<int32_t>(bmp280_cal.dig_t1)) *
                    ((adc_t >> 4) - static_cast<int32_t>(bmp280_cal.dig_t1))) >>
                   12) *
                  static_cast<int32_t>(bmp280_cal.dig_t3)) >>
                 14;
  bmp280_cal.t_fine = var1 + var2;
  int32_t temp = (bmp280_cal.t_fine * 5 + 128) >> 8;
  return static_cast<float>(temp) / 100.0f;
}

float bmp280_compensate_pressure(int32_t adc_p) {
  int64_t var1 = static_cast<int64_t>(bmp280_cal.t_fine) - 128000;
  int64_t var2 = var1 * var1 * static_cast<int64_t>(bmp280_cal.dig_p6);
  var2 = var2 + ((var1 * static_cast<int64_t>(bmp280_cal.dig_p5)) << 17);
  var2 = var2 + (static_cast<int64_t>(bmp280_cal.dig_p4) << 35);
  var1 = ((var1 * var1 * static_cast<int64_t>(bmp280_cal.dig_p3)) >> 8) +
         ((var1 * static_cast<int64_t>(bmp280_cal.dig_p2)) << 12);
  var1 = (((static_cast<int64_t>(1) << 47) + var1) *
          static_cast<int64_t>(bmp280_cal.dig_p1)) >>
         33;
  if (var1 == 0) {
    return 0.0f;
  }
  int64_t p = 1048576 - adc_p;
  p = (((p << 31) - var2) * 3125) / var1;
  var1 = (static_cast<int64_t>(bmp280_cal.dig_p9) * (p >> 13) * (p >> 13)) >> 25;
  var2 = (static_cast<int64_t>(bmp280_cal.dig_p8) * p) >> 19;
  p = ((p + var1 + var2) >> 8) + (static_cast<int64_t>(bmp280_cal.dig_p7) << 4);
  return static_cast<float>(p) / 256.0f;
}
#endif

void fill_status(OtisEnvSensorStatus *out) {
  if (out == nullptr) {
    return;
  }
  out->sht4x_enabled = OTIS_ENABLE_ENV_SHT4X != 0;
  out->sht4x_initialized = sht4x_initialized;
  out->sht4x_last_read_ok = sht4x_last_read_ok;
  out->sht4x_i2c_address = kSht4xAddress;
  out->bmp280_enabled = OTIS_ENABLE_ENV_BMP280 != 0;
  out->bmp280_initialized = bmp280_initialized;
  out->bmp280_last_read_ok = bmp280_last_read_ok;
  out->bmp280_i2c_address = kBmp280Address;
  out->sample_period_ms = kSamplePeriodMs;
}

}  // namespace

bool otis_env_sensors_begin(void) {
#if OTIS_ENABLE_ENV_SENSORS
  if (!otis_i2c_bus_begin()) {
    return false;
  }
#if OTIS_ENABLE_ENV_SHT4X
  sht4x_initialized = i2c_probe(kSht4xAddress);
  sht4x_last_read_ok = sht4x_initialized;
#else
  sht4x_initialized = false;
  sht4x_last_read_ok = false;
#endif

#if OTIS_ENABLE_ENV_BMP280
  uint8_t chip_id = 0;
  bmp280_initialized = i2c_probe(kBmp280Address) &&
                       read_registers(kBmp280Address, 0xD0u, &chip_id, 1) &&
                       chip_id == kBmp280ChipId &&
                       bmp280_read_calibration() &&
                       write_register8(kBmp280Address, 0xF4u, 0x27u) &&
                       write_register8(kBmp280Address, 0xF5u, 0xA0u);
  bmp280_last_read_ok = bmp280_initialized;
#else
  bmp280_initialized = false;
  bmp280_last_read_ok = false;
#endif
  // A selected sensor set is ready only when every selected member completed
  // initialization. The boot capability policy decides whether that complete
  // set is required or explicitly degraded.
  return (!OTIS_ENABLE_ENV_SHT4X || sht4x_initialized) &&
         (!OTIS_ENABLE_ENV_BMP280 || bmp280_initialized);
#else
  sht4x_initialized = false;
  sht4x_last_read_ok = false;
  bmp280_initialized = false;
  bmp280_last_read_ok = false;
  return false;
#endif
}

bool otis_env_sensors_read_sht4x(OtisEnvSample *out) {
  if (out == nullptr) {
    return false;
  }
  out->valid = false;
  out->source = "sht4x";
  out->role = "vcocxo_near";
  out->has_humidity = true;
  out->has_pressure = false;
#if OTIS_ENABLE_ENV_SENSORS && OTIS_ENABLE_ENV_SHT4X
  if (!sht4x_initialized) {
    sht4x_last_read_ok = false;
    return false;
  }
  Wire.beginTransmission(kSht4xAddress);
  Wire.write(0xFDu);  // High precision measurement, no heater.
  if (Wire.endTransmission() != 0u) {
    sht4x_last_read_ok = false;
    return false;
  }
  delay(10);
  uint8_t read_count = Wire.requestFrom(kSht4xAddress, static_cast<uint8_t>(6));
  if (read_count != 6u) {
    while (Wire.available()) {
      (void)Wire.read();
    }
    sht4x_last_read_ok = false;
    return false;
  }
  uint8_t data[6];
  for (uint8_t i = 0; i < 6; ++i) {
    data[i] = static_cast<uint8_t>(Wire.read());
  }
  if (crc8_sht4x(data, 2) != data[2] || crc8_sht4x(data + 3, 2) != data[5]) {
    sht4x_last_read_ok = false;
    return false;
  }
  uint16_t raw_t = (static_cast<uint16_t>(data[0]) << 8) | data[1];
  uint16_t raw_rh = (static_cast<uint16_t>(data[3]) << 8) | data[4];
  out->temperature_c = -45.0f + 175.0f * static_cast<float>(raw_t) / 65535.0f;
  float humidity = -6.0f + 125.0f * static_cast<float>(raw_rh) / 65535.0f;
  if (humidity < 0.0f) {
    humidity = 0.0f;
  }
  if (humidity > 100.0f) {
    humidity = 100.0f;
  }
  out->relative_humidity_pct = humidity;
  out->pressure_pa = 0.0f;
  out->valid = true;
  sht4x_last_read_ok = true;
  return true;
#else
  sht4x_last_read_ok = false;
  return false;
#endif
}

bool otis_env_sensors_read_bmp280(OtisEnvSample *out) {
  if (out == nullptr) {
    return false;
  }
  out->valid = false;
  out->source = "bmp280";
  out->role = "pressure_reference";
  out->has_humidity = false;
  out->has_pressure = true;
#if OTIS_ENABLE_ENV_SENSORS && OTIS_ENABLE_ENV_BMP280
  if (!bmp280_initialized || !bmp280_cal.valid) {
    bmp280_last_read_ok = false;
    return false;
  }
  uint8_t data[6];
  if (!read_registers(kBmp280Address, 0xF7u, data, sizeof(data))) {
    bmp280_last_read_ok = false;
    return false;
  }
  int32_t adc_p = (static_cast<int32_t>(data[0]) << 12) |
                  (static_cast<int32_t>(data[1]) << 4) |
                  (static_cast<int32_t>(data[2]) >> 4);
  int32_t adc_t = (static_cast<int32_t>(data[3]) << 12) |
                  (static_cast<int32_t>(data[4]) << 4) |
                  (static_cast<int32_t>(data[5]) >> 4);
  out->temperature_c = bmp280_compensate_temperature(adc_t);
  out->relative_humidity_pct = 0.0f;
  out->pressure_pa = bmp280_compensate_pressure(adc_p);
  out->valid = out->pressure_pa > 0.0f;
  bmp280_last_read_ok = out->valid;
  return out->valid;
#else
  bmp280_last_read_ok = false;
  return false;
#endif
}

void otis_env_sensors_get_status(OtisEnvSensorStatus *out) {
  fill_status(out);
}
