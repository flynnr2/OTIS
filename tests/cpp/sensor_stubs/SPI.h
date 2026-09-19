#pragma once
#include "Arduino.h"
#define SPI_HAS_TRANSACTION
constexpr int SPI_MODE0 = 0, SPI_MODE1 = 1, SPI_MODE2 = 2, SPI_MODE3 = 3;
class SPISettings {
 public:
  SPISettings(uint32_t, BitOrder, uint8_t) {}
};
class SPIClass {
 public:
  void begin() {}
  void beginTransaction(SPISettings) {}
  void endTransaction() {}
  void transfer(uint8_t *, size_t) {}
  uint8_t transfer(uint8_t) { return 0; }
};
inline SPIClass SPI;
