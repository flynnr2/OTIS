#pragma once
#include <stdint.h>
extern uint64_t mock_time_us;
inline uint64_t time_us_64() { return mock_time_us++; }
inline uint32_t time_us_32() { return static_cast<uint32_t>(time_us_64()); }
