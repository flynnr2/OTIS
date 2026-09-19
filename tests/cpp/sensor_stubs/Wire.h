#pragma once
#include "Arduino.h"
#include <array>
#include <vector>
#include <assert.h>

// Emulate only I2C peripheral responses; production drivers and BusIO execute.
class TwoWire {
 public:
  std::array<uint8_t, 256> registers{};
  std::array<uint8_t, 6> sht_bytes{0x66, 0x66, 0x93, 0x80, 0x00, 0xA2};
  bool sht_present = true, bmp_present = true, short_read = false;
  int fail_register = -1;
  unsigned read_count = 0, write_count = 0, timeout_ms = 0;
  void begin() {}
  void end() {}
  void setClock(uint32_t) {}
  void setTimeout(uint32_t ms) { timeout_ms = ms; }
  void beginTransmission(uint8_t address) { address_ = address; tx_.clear(); }
  size_t write(const uint8_t *data, size_t n) {
    tx_.insert(tx_.end(), data, data + n); return n;
  }
  size_t write(uint8_t byte) { tx_.push_back(byte); return 1; }
  uint8_t endTransmission(bool = true) {
    ++write_count;
    // No sensor operation may issue a DAC/general-call write or heater command.
    assert(address_ == 0x44 || address_ == 0x77);
    if (!(address_ == 0x44 ? sht_present : bmp_present)) return 2;
    if (tx_.empty()) return 0;
    reg_ = tx_[0];
    if (address_ == 0x44) { assert(reg_ == 0x94 || reg_ == 0xFD); return 0; }
    if (reg_ == fail_register) return 3;
    for (size_t i = 1; i < tx_.size(); ++i) registers[reg_ + i - 1] = tx_[i];
    return 0;
  }
  uint8_t requestFrom(uint8_t address, uint8_t count, uint8_t = 1) {
    ++read_count; rx_.clear(); pos_ = 0;
    if (!(address == 0x44 ? sht_present : bmp_present)) return 0;
    if (short_read && count) --count;
    for (uint8_t i = 0; i < count; ++i)
      rx_.push_back(address == 0x44 ? sht_bytes[i] : registers[reg_ + i]);
    return count;
  }
  int read() { return pos_ < rx_.size() ? rx_[pos_++] : -1; }
  int available() { return int(rx_.size() - pos_); }
 private:
  uint8_t address_ = 0, reg_ = 0;
  std::vector<uint8_t> tx_, rx_;
  size_t pos_ = 0;
};
inline TwoWire Wire;
