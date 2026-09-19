#pragma once
#include <stdint.h>
using uint = unsigned int;
constexpr int clk_sys = 0;
extern uint32_t mock_system_clock_hz;
inline uint32_t clock_get_hz(int) { return mock_system_clock_hz; }
