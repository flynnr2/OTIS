#ifndef OTIS_ADAPTIVE_HYBRID_WIDE_H
#define OTIS_ADAPTIVE_HYBRID_WIDE_H

#include <stddef.h>
#include <stdint.h>

// Target-portable signed magnitude with a symmetric
// [-(2^127-1), +(2^127-1)] domain.  The representation is intentionally
// explicit: RP2040 arm-none-eabi GCC does not provide a builtin 128-bit type.
struct OtisAdaptiveHybridWide {
  uint64_t magnitude_high;
  uint64_t magnitude_low;
  bool negative;

  constexpr OtisAdaptiveHybridWide()
      : magnitude_high(0u), magnitude_low(0u), negative(false) {}

  constexpr OtisAdaptiveHybridWide(int64_t value)
      : magnitude_high(0u),
        magnitude_low(value < 0
                          ? static_cast<uint64_t>(0u) -
                                static_cast<uint64_t>(value)
                          : static_cast<uint64_t>(value)),
        negative(value < 0) {}

  constexpr OtisAdaptiveHybridWide(uint64_t high, uint64_t low, bool is_negative)
      : magnitude_high(high),
        magnitude_low(low),
        negative(is_negative && (high != 0u || low != 0u)) {}
};

constexpr size_t OTIS_ADAPTIVE_HYBRID_WIDE_DECIMAL_CAPACITY = 41u;

bool otis_adaptive_hybrid_wide_valid(OtisAdaptiveHybridWide value);
bool otis_adaptive_hybrid_wide_is_zero(OtisAdaptiveHybridWide value);
bool otis_adaptive_hybrid_wide_equal(OtisAdaptiveHybridWide left, OtisAdaptiveHybridWide right);
int otis_adaptive_hybrid_wide_compare(OtisAdaptiveHybridWide left, OtisAdaptiveHybridWide right);

bool otis_adaptive_hybrid_wide_from_i64(int64_t value, OtisAdaptiveHybridWide *result);
bool otis_adaptive_hybrid_wide_from_u64(uint64_t value, OtisAdaptiveHybridWide *result);
bool otis_adaptive_hybrid_wide_to_i64(OtisAdaptiveHybridWide value, int64_t *result);
bool otis_adaptive_hybrid_wide_to_u64(OtisAdaptiveHybridWide value, uint64_t *result);
bool otis_adaptive_hybrid_wide_absolute(OtisAdaptiveHybridWide value, OtisAdaptiveHybridWide *result);
bool otis_adaptive_hybrid_wide_negate(OtisAdaptiveHybridWide value, OtisAdaptiveHybridWide *result);

bool otis_adaptive_hybrid_wide_checked_add(OtisAdaptiveHybridWide left, OtisAdaptiveHybridWide right,
                                 OtisAdaptiveHybridWide *result);
bool otis_adaptive_hybrid_wide_checked_subtract(OtisAdaptiveHybridWide left,
                                      OtisAdaptiveHybridWide right,
                                      OtisAdaptiveHybridWide *result);
bool otis_adaptive_hybrid_wide_checked_multiply(OtisAdaptiveHybridWide left,
                                      OtisAdaptiveHybridWide right,
                                      OtisAdaptiveHybridWide *result);

// Quotient truncates toward zero; remainder has the numerator's sign.
bool otis_adaptive_hybrid_wide_divide(OtisAdaptiveHybridWide numerator,
                            OtisAdaptiveHybridWide denominator,
                            OtisAdaptiveHybridWide *quotient,
                            OtisAdaptiveHybridWide *remainder);

bool otis_adaptive_hybrid_wide_parse_decimal(const char *text, OtisAdaptiveHybridWide *result);
bool otis_adaptive_hybrid_wide_format_decimal(OtisAdaptiveHybridWide value, char *output,
                                    size_t output_size);

inline bool operator==(OtisAdaptiveHybridWide left, OtisAdaptiveHybridWide right) {
  return otis_adaptive_hybrid_wide_equal(left, right);
}

inline bool operator!=(OtisAdaptiveHybridWide left, OtisAdaptiveHybridWide right) {
  return !otis_adaptive_hybrid_wide_equal(left, right);
}

inline bool operator<(OtisAdaptiveHybridWide left, OtisAdaptiveHybridWide right) {
  return otis_adaptive_hybrid_wide_compare(left, right) < 0;
}

inline bool operator>(OtisAdaptiveHybridWide left, OtisAdaptiveHybridWide right) {
  return otis_adaptive_hybrid_wide_compare(left, right) > 0;
}

inline bool operator<=(OtisAdaptiveHybridWide left, OtisAdaptiveHybridWide right) {
  return otis_adaptive_hybrid_wide_compare(left, right) <= 0;
}

inline bool operator>=(OtisAdaptiveHybridWide left, OtisAdaptiveHybridWide right) {
  return otis_adaptive_hybrid_wide_compare(left, right) >= 0;
}

#endif
