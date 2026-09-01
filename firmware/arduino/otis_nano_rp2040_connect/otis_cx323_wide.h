#ifndef OTIS_CX323_WIDE_H
#define OTIS_CX323_WIDE_H

#include <stddef.h>
#include <stdint.h>

// Target-portable signed magnitude with a symmetric
// [-(2^127-1), +(2^127-1)] domain.  The representation is intentionally
// explicit: RP2040 arm-none-eabi GCC does not provide a builtin 128-bit type.
struct OtisCx323Wide {
  uint64_t magnitude_high;
  uint64_t magnitude_low;
  bool negative;

  constexpr OtisCx323Wide()
      : magnitude_high(0u), magnitude_low(0u), negative(false) {}

  constexpr OtisCx323Wide(int64_t value)
      : magnitude_high(0u),
        magnitude_low(value < 0
                          ? static_cast<uint64_t>(0u) -
                                static_cast<uint64_t>(value)
                          : static_cast<uint64_t>(value)),
        negative(value < 0) {}

  constexpr OtisCx323Wide(uint64_t high, uint64_t low, bool is_negative)
      : magnitude_high(high),
        magnitude_low(low),
        negative(is_negative && (high != 0u || low != 0u)) {}
};

constexpr size_t OTIS_CX323_WIDE_DECIMAL_CAPACITY = 41u;

bool otis_cx323_wide_valid(OtisCx323Wide value);
bool otis_cx323_wide_is_zero(OtisCx323Wide value);
bool otis_cx323_wide_equal(OtisCx323Wide left, OtisCx323Wide right);
int otis_cx323_wide_compare(OtisCx323Wide left, OtisCx323Wide right);

bool otis_cx323_wide_from_i64(int64_t value, OtisCx323Wide *result);
bool otis_cx323_wide_from_u64(uint64_t value, OtisCx323Wide *result);
bool otis_cx323_wide_to_i64(OtisCx323Wide value, int64_t *result);
bool otis_cx323_wide_to_u64(OtisCx323Wide value, uint64_t *result);
bool otis_cx323_wide_absolute(OtisCx323Wide value, OtisCx323Wide *result);
bool otis_cx323_wide_negate(OtisCx323Wide value, OtisCx323Wide *result);

bool otis_cx323_wide_checked_add(OtisCx323Wide left, OtisCx323Wide right,
                                 OtisCx323Wide *result);
bool otis_cx323_wide_checked_subtract(OtisCx323Wide left,
                                      OtisCx323Wide right,
                                      OtisCx323Wide *result);
bool otis_cx323_wide_checked_multiply(OtisCx323Wide left,
                                      OtisCx323Wide right,
                                      OtisCx323Wide *result);

// Quotient truncates toward zero; remainder has the numerator's sign.
bool otis_cx323_wide_divide(OtisCx323Wide numerator,
                            OtisCx323Wide denominator,
                            OtisCx323Wide *quotient,
                            OtisCx323Wide *remainder);

bool otis_cx323_wide_parse_decimal(const char *text, OtisCx323Wide *result);
bool otis_cx323_wide_format_decimal(OtisCx323Wide value, char *output,
                                    size_t output_size);

inline bool operator==(OtisCx323Wide left, OtisCx323Wide right) {
  return otis_cx323_wide_equal(left, right);
}

inline bool operator!=(OtisCx323Wide left, OtisCx323Wide right) {
  return !otis_cx323_wide_equal(left, right);
}

inline bool operator<(OtisCx323Wide left, OtisCx323Wide right) {
  return otis_cx323_wide_compare(left, right) < 0;
}

inline bool operator>(OtisCx323Wide left, OtisCx323Wide right) {
  return otis_cx323_wide_compare(left, right) > 0;
}

inline bool operator<=(OtisCx323Wide left, OtisCx323Wide right) {
  return otis_cx323_wide_compare(left, right) <= 0;
}

inline bool operator>=(OtisCx323Wide left, OtisCx323Wide right) {
  return otis_cx323_wide_compare(left, right) >= 0;
}

#endif
