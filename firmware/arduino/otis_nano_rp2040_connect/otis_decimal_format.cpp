#include "otis_decimal_format.h"

#include <math.h>
#include <stdint.h>

namespace {

constexpr uint64_t kPowersOfTen[] = {
    1ull,
    10ull,
    100ull,
    1000ull,
    10000ull,
    100000ull,
    1000000ull,
    10000000ull,
    100000000ull,
    1000000000ull,
    10000000000ull,
    100000000000ull,
    1000000000000ull,
    10000000000000ull,
    100000000000000ull,
    1000000000000000ull,
};

size_t unsigned_decimal_digits(uint64_t value) {
  size_t digits = 1u;
  while (value >= 10u) {
    value /= 10u;
    ++digits;
  }
  return digits;
}

void write_unsigned(uint64_t value, char *output, size_t digits) {
  for (size_t index = digits; index > 0u; --index) {
    output[index - 1u] = static_cast<char>('0' + value % 10u);
    value /= 10u;
  }
}

}  // namespace

bool otis_format_fixed(double value, uint8_t decimal_places, char *output,
                       size_t output_size) {
  if (output == nullptr || output_size == 0u || decimal_places > 15u ||
      !isfinite(value))
    return false;

  const bool negative = signbit(value);
  const double magnitude = fabs(value);
  double integer_part_double = 0.0;
  const double fractional = modf(magnitude, &integer_part_double);
  if (integer_part_double > static_cast<double>(UINT64_MAX)) return false;

  uint64_t integer_part = static_cast<uint64_t>(integer_part_double);
  const uint64_t scale = kPowersOfTen[decimal_places];
  uint64_t fractional_part = 0u;
  if (decimal_places > 0u) {
    fractional_part =
        static_cast<uint64_t>(floor(fractional * scale + 0.5));
    if (fractional_part >= scale) {
      if (integer_part == UINT64_MAX) return false;
      ++integer_part;
      fractional_part = 0u;
    }
  }

  const size_t integer_digits = unsigned_decimal_digits(integer_part);
  const size_t required = (negative ? 1u : 0u) + integer_digits +
                          (decimal_places > 0u ? 1u + decimal_places : 0u) +
                          1u;
  if (required > output_size) return false;

  size_t cursor = 0u;
  if (negative) output[cursor++] = '-';
  write_unsigned(integer_part, output + cursor, integer_digits);
  cursor += integer_digits;
  if (decimal_places > 0u) {
    output[cursor++] = '.';
    write_unsigned(fractional_part, output + cursor, decimal_places);
    cursor += decimal_places;
  }
  output[cursor] = '\0';
  return true;
}
