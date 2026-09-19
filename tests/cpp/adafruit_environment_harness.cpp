#include <assert.h>
#include <cmath>
#include "Wire.h"
#include "otis_env_sensors.h"

void u16(unsigned reg, int value) {
  Wire.registers[reg] = uint16_t(value) & 255;
  Wire.registers[reg + 1] = uint16_t(value) >> 8;
}
void adc(unsigned reg, uint32_t value) {
  Wire.registers[reg] = value >> 12;
  Wire.registers[reg + 1] = value >> 4;
  Wire.registers[reg + 2] = value << 4;
}
void setup() {
  Wire.registers[0xD0] = 0x58;
  // Bosch datasheet compensation example: 25.08 C, 100653.25 Pa.
  const int calibration[] = {27504, 26435, -1000, 36477, -10685, 3024,
                            2855, 140, -7, 15500, -14600, 6000};
  for (unsigned i = 0; i < 12; ++i) u16(0x88 + i * 2, calibration[i]);
  adc(0xF7, 415148); adc(0xFA, 519888);
}
int main() {
  setup();
  assert(otis_env_sensors_begin());
  assert(Wire.timeout_ms == 10);
  assert(Wire.registers[0xF4] == 0x27);
  assert(Wire.registers[0xF5] == 0xA0);
  OtisEnvSensorStatus status{};
  otis_env_sensors_get_status(&status);
  assert(!status.sht4x_last_read_ok && !status.bmp280_last_read_ok);
  OtisEnvSample sample{};
  unsigned reads = Wire.read_count;
  assert(otis_env_sensors_read_bmp280(&sample));
  assert(Wire.read_count == reads + 1); // one coherent six-byte acquisition
  assert(std::abs(sample.temperature_c - 25.08f) < 0.01f);
  assert(std::abs(sample.pressure_pa - 100653.25f) < 0.1f);
  assert(otis_env_sensors_read_sht4x(&sample));
  assert(std::abs(sample.temperature_c - 25.0f) < 0.01f);
  assert(std::abs(sample.relative_humidity_pct - 56.501f) < 0.01f);
  Wire.sht_bytes[2] ^= 1;
  assert(!otis_env_sensors_read_sht4x(&sample) && !sample.valid);
  assert(otis_env_sensors_read_bmp280(&sample)); // SHT failure stays local
  Wire.sht_bytes[2] ^= 1;
  Wire.short_read = true;
  assert(!otis_env_sensors_read_bmp280(&sample) && !sample.valid);
  assert(!otis_env_sensors_read_sht4x(&sample) && !sample.valid);
  Wire.short_read = false;
  Wire.fail_register = 0xF7;
  assert(!otis_env_sensors_read_bmp280(&sample) && !sample.valid);
  Wire.fail_register = -1;
  assert(otis_env_sensors_read_bmp280(&sample)); // no cached failure/success
  adc(0xFA, 0x80000);
  assert(!otis_env_sensors_read_bmp280(&sample)); // skipped-channel sentinel
  setup();
  Wire.bmp_present = false;
  assert(!otis_env_sensors_read_bmp280(&sample));
  assert(otis_env_sensors_read_sht4x(&sample));
  Wire.bmp_present = true;
  // Every calibration/configuration transaction failure must prevent readiness.
  for (int reg : {0x88, 0x8A, 0x8C, 0x8E, 0x90, 0x92, 0x94,
                  0x96, 0x98, 0x9A, 0x9C, 0x9E, 0xF4, 0xF5}) {
    Wire.fail_register = reg;
    assert(!otis_env_sensors_begin());
    assert(!otis_env_sensors_read_bmp280(&sample));
  }
  Wire.fail_register = -1;
  assert(otis_env_sensors_begin());
  assert(otis_env_sensors_read_bmp280(&sample));
  Wire.registers[0xF3] = 0x08;
  const auto before_busy = millis();
  assert(!otis_env_sensors_begin());
  assert(millis() - before_busy <= 202u);
  assert(!otis_env_sensors_read_bmp280(&sample));
  assert(otis_env_sensors_read_sht4x(&sample));
  Wire.registers[0xF3] = 0;
  assert(otis_env_sensors_begin());
  Wire.sht_present = false;
  assert(!otis_env_sensors_read_sht4x(&sample));
  assert(otis_env_sensors_read_bmp280(&sample));
}
