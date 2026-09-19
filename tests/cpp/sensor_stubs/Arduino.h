#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <math.h>
#include <algorithm>
using std::min;
using std::max;
using byte = uint8_t;
enum BitOrder { LSBFIRST, MSBFIRST };
constexpr int INPUT = 0, OUTPUT = 1, LOW = 0, HIGH = 1;
inline uint32_t fake_millis = 0;
inline uint32_t millis() { return fake_millis; }
inline void delay(uint32_t ms) { fake_millis += ms; }
inline void delayMicroseconds(uint32_t) {}
inline void pinMode(int, int) {}
inline void digitalWrite(int, int) {}
inline int digitalRead(int) { return 0; }
#define F(x) x
