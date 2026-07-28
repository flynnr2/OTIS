#include "otis_i2c_bus.h"

#include <Wire.h>

namespace {

bool i2c_bus_initialized = false;

}  // namespace

bool otis_i2c_bus_begin(void) {
  if (!i2c_bus_initialized) {
    Wire.begin();
    i2c_bus_initialized = true;
  }
  return true;
}

bool otis_i2c_bus_initialized(void) {
  return i2c_bus_initialized;
}
