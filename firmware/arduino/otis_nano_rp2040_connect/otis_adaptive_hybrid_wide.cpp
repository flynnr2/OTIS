#include "otis_adaptive_hybrid_wide.h"

#include <string.h>

namespace {

constexpr uint64_t kMaximumMagnitudeHigh = 0x7fffffffffffffffull;

int magnitude_compare(OtisAdaptiveHybridWide left, OtisAdaptiveHybridWide right) {
  if (left.magnitude_high != right.magnitude_high)
    return left.magnitude_high < right.magnitude_high ? -1 : 1;
  if (left.magnitude_low != right.magnitude_low)
    return left.magnitude_low < right.magnitude_low ? -1 : 1;
  return 0;
}

bool magnitude_add(OtisAdaptiveHybridWide left, OtisAdaptiveHybridWide right,
                   OtisAdaptiveHybridWide *result) {
  const uint64_t low = left.magnitude_low + right.magnitude_low;
  const uint64_t carry = low < left.magnitude_low ? 1u : 0u;
  const uint64_t high_without_carry =
      left.magnitude_high + right.magnitude_high;
  if (high_without_carry < left.magnitude_high) return false;
  const uint64_t high = high_without_carry + carry;
  if (high < high_without_carry || high > kMaximumMagnitudeHigh) return false;
  *result = OtisAdaptiveHybridWide(high, low, false);
  return true;
}

OtisAdaptiveHybridWide magnitude_subtract(OtisAdaptiveHybridWide left,
                                 OtisAdaptiveHybridWide right) {
  const uint64_t borrow = left.magnitude_low < right.magnitude_low ? 1u : 0u;
  return OtisAdaptiveHybridWide(left.magnitude_high - right.magnitude_high - borrow,
                      left.magnitude_low - right.magnitude_low, false);
}

bool magnitude_shift_left_one(OtisAdaptiveHybridWide *value) {
  if ((value->magnitude_high & 0x8000000000000000ull) != 0u) return false;
  value->magnitude_high =
      (value->magnitude_high << 1u) | (value->magnitude_low >> 63u);
  value->magnitude_low <<= 1u;
  return true;
}

void magnitude_shift_right_one(OtisAdaptiveHybridWide *value) {
  value->magnitude_low =
      (value->magnitude_low >> 1u) | (value->magnitude_high << 63u);
  value->magnitude_high >>= 1u;
}

bool magnitude_multiply(OtisAdaptiveHybridWide left, OtisAdaptiveHybridWide right,
                        OtisAdaptiveHybridWide *result) {
  OtisAdaptiveHybridWide product;
  OtisAdaptiveHybridWide multiplicand = left;
  OtisAdaptiveHybridWide remaining = right;
  while (!otis_adaptive_hybrid_wide_is_zero(remaining)) {
    if ((remaining.magnitude_low & 1u) != 0u) {
      if (!magnitude_add(product, multiplicand, &product)) return false;
    }
    magnitude_shift_right_one(&remaining);
    if (!otis_adaptive_hybrid_wide_is_zero(remaining) &&
        !magnitude_shift_left_one(&multiplicand))
      return false;
  }
  *result = product;
  return true;
}

bool magnitude_bit(OtisAdaptiveHybridWide value, unsigned bit) {
  return bit < 64u ? ((value.magnitude_low >> bit) & 1u) != 0u
                   : ((value.magnitude_high >> (bit - 64u)) & 1u) != 0u;
}

void magnitude_set_bit(OtisAdaptiveHybridWide *value, unsigned bit) {
  if (bit < 64u)
    value->magnitude_low |= static_cast<uint64_t>(1u) << bit;
  else
    value->magnitude_high |= static_cast<uint64_t>(1u) << (bit - 64u);
}

bool magnitude_divide(OtisAdaptiveHybridWide numerator, OtisAdaptiveHybridWide denominator,
                      OtisAdaptiveHybridWide *quotient, OtisAdaptiveHybridWide *remainder) {
  if (otis_adaptive_hybrid_wide_is_zero(denominator)) return false;
  OtisAdaptiveHybridWide result;
  OtisAdaptiveHybridWide rest;
  for (int bit = 127; bit >= 0; --bit) {
    // denominator <= 2^127-1 and rest < denominator, so the unsigned
    // shift cannot exceed the complete two-limb magnitude container.
    rest.magnitude_high =
        (rest.magnitude_high << 1u) | (rest.magnitude_low >> 63u);
    rest.magnitude_low =
        (rest.magnitude_low << 1u) |
        (magnitude_bit(numerator, static_cast<unsigned>(bit)) ? 1u : 0u);
    if (magnitude_compare(rest, denominator) >= 0) {
      rest = magnitude_subtract(rest, denominator);
      magnitude_set_bit(&result, static_cast<unsigned>(bit));
    }
  }
  *quotient = result;
  *remainder = rest;
  return true;
}

bool magnitude_multiply_small(OtisAdaptiveHybridWide value, uint32_t multiplier,
                              OtisAdaptiveHybridWide *result) {
  return magnitude_multiply(value,
                            OtisAdaptiveHybridWide(static_cast<int64_t>(multiplier)),
                            result);
}

bool magnitude_add_small(OtisAdaptiveHybridWide value, uint32_t addend,
                         OtisAdaptiveHybridWide *result) {
  return magnitude_add(value, OtisAdaptiveHybridWide(static_cast<int64_t>(addend)),
                       result);
}

}  // namespace

bool otis_adaptive_hybrid_wide_valid(OtisAdaptiveHybridWide value) {
  return value.magnitude_high <= kMaximumMagnitudeHigh &&
         (!value.negative || !otis_adaptive_hybrid_wide_is_zero(value));
}

bool otis_adaptive_hybrid_wide_is_zero(OtisAdaptiveHybridWide value) {
  return value.magnitude_high == 0u && value.magnitude_low == 0u;
}

bool otis_adaptive_hybrid_wide_equal(OtisAdaptiveHybridWide left, OtisAdaptiveHybridWide right) {
  if (otis_adaptive_hybrid_wide_is_zero(left) && otis_adaptive_hybrid_wide_is_zero(right))
    return true;
  return left.negative == right.negative && magnitude_compare(left, right) == 0;
}

int otis_adaptive_hybrid_wide_compare(OtisAdaptiveHybridWide left, OtisAdaptiveHybridWide right) {
  if (otis_adaptive_hybrid_wide_equal(left, right)) return 0;
  if (left.negative != right.negative) return left.negative ? -1 : 1;
  const int comparison = magnitude_compare(left, right);
  return left.negative ? -comparison : comparison;
}

bool otis_adaptive_hybrid_wide_from_i64(int64_t value, OtisAdaptiveHybridWide *result) {
  if (result == nullptr) return false;
  *result = OtisAdaptiveHybridWide(value);
  return true;
}

bool otis_adaptive_hybrid_wide_from_u64(uint64_t value, OtisAdaptiveHybridWide *result) {
  if (result == nullptr) return false;
  *result = OtisAdaptiveHybridWide(0u, value, false);
  return true;
}

bool otis_adaptive_hybrid_wide_to_i64(OtisAdaptiveHybridWide value, int64_t *result) {
  if (result == nullptr || !otis_adaptive_hybrid_wide_valid(value) ||
      value.magnitude_high != 0u)
    return false;
  if (!value.negative) {
    if (value.magnitude_low > static_cast<uint64_t>(INT64_MAX)) return false;
    *result = static_cast<int64_t>(value.magnitude_low);
    return true;
  }
  const uint64_t minimum_magnitude = static_cast<uint64_t>(INT64_MAX) + 1u;
  if (value.magnitude_low > minimum_magnitude) return false;
  if (value.magnitude_low == minimum_magnitude) {
    *result = INT64_MIN;
    return true;
  }
  *result = -static_cast<int64_t>(value.magnitude_low);
  return true;
}

bool otis_adaptive_hybrid_wide_to_u64(OtisAdaptiveHybridWide value, uint64_t *result) {
  if (result == nullptr || !otis_adaptive_hybrid_wide_valid(value) || value.negative ||
      value.magnitude_high != 0u)
    return false;
  *result = value.magnitude_low;
  return true;
}

bool otis_adaptive_hybrid_wide_absolute(OtisAdaptiveHybridWide value, OtisAdaptiveHybridWide *result) {
  if (result == nullptr || !otis_adaptive_hybrid_wide_valid(value)) return false;
  *result = OtisAdaptiveHybridWide(value.magnitude_high, value.magnitude_low, false);
  return true;
}

bool otis_adaptive_hybrid_wide_negate(OtisAdaptiveHybridWide value, OtisAdaptiveHybridWide *result) {
  if (result == nullptr || !otis_adaptive_hybrid_wide_valid(value)) return false;
  *result = OtisAdaptiveHybridWide(value.magnitude_high, value.magnitude_low,
                         !value.negative);
  return true;
}

bool otis_adaptive_hybrid_wide_checked_add(OtisAdaptiveHybridWide left, OtisAdaptiveHybridWide right,
                                 OtisAdaptiveHybridWide *result) {
  if (result == nullptr || !otis_adaptive_hybrid_wide_valid(left) ||
      !otis_adaptive_hybrid_wide_valid(right))
    return false;
  if (left.negative == right.negative) {
    OtisAdaptiveHybridWide sum;
    if (!magnitude_add(left, right, &sum)) return false;
    *result = OtisAdaptiveHybridWide(sum.magnitude_high, sum.magnitude_low,
                           left.negative);
    return true;
  }
  const int comparison = magnitude_compare(left, right);
  if (comparison == 0) {
    *result = OtisAdaptiveHybridWide();
  } else if (comparison > 0) {
    const OtisAdaptiveHybridWide difference = magnitude_subtract(left, right);
    *result = OtisAdaptiveHybridWide(difference.magnitude_high,
                           difference.magnitude_low, left.negative);
  } else {
    const OtisAdaptiveHybridWide difference = magnitude_subtract(right, left);
    *result = OtisAdaptiveHybridWide(difference.magnitude_high,
                           difference.magnitude_low, right.negative);
  }
  return true;
}

bool otis_adaptive_hybrid_wide_checked_subtract(OtisAdaptiveHybridWide left,
                                      OtisAdaptiveHybridWide right,
                                      OtisAdaptiveHybridWide *result) {
  OtisAdaptiveHybridWide negated;
  return otis_adaptive_hybrid_wide_negate(right, &negated) &&
         otis_adaptive_hybrid_wide_checked_add(left, negated, result);
}

bool otis_adaptive_hybrid_wide_checked_multiply(OtisAdaptiveHybridWide left,
                                      OtisAdaptiveHybridWide right,
                                      OtisAdaptiveHybridWide *result) {
  if (result == nullptr || !otis_adaptive_hybrid_wide_valid(left) ||
      !otis_adaptive_hybrid_wide_valid(right))
    return false;
  OtisAdaptiveHybridWide product;
  if (!magnitude_multiply(left, right, &product)) return false;
  *result = OtisAdaptiveHybridWide(product.magnitude_high, product.magnitude_low,
                         left.negative != right.negative);
  return true;
}

bool otis_adaptive_hybrid_wide_divide(OtisAdaptiveHybridWide numerator,
                            OtisAdaptiveHybridWide denominator,
                            OtisAdaptiveHybridWide *quotient,
                            OtisAdaptiveHybridWide *remainder) {
  if (quotient == nullptr || remainder == nullptr ||
      !otis_adaptive_hybrid_wide_valid(numerator) ||
      !otis_adaptive_hybrid_wide_valid(denominator) ||
      otis_adaptive_hybrid_wide_is_zero(denominator))
    return false;
  OtisAdaptiveHybridWide quotient_magnitude;
  OtisAdaptiveHybridWide remainder_magnitude;
  if (!magnitude_divide(numerator, denominator, &quotient_magnitude,
                        &remainder_magnitude))
    return false;
  *quotient = OtisAdaptiveHybridWide(
      quotient_magnitude.magnitude_high, quotient_magnitude.magnitude_low,
      numerator.negative != denominator.negative);
  *remainder = OtisAdaptiveHybridWide(
      remainder_magnitude.magnitude_high, remainder_magnitude.magnitude_low,
      numerator.negative);
  return true;
}

bool otis_adaptive_hybrid_wide_parse_decimal(const char *text, OtisAdaptiveHybridWide *result) {
  if (text == nullptr || result == nullptr || *text == '\0') return false;
  bool negative = false;
  if (*text == '-' || *text == '+') {
    negative = *text == '-';
    ++text;
  }
  if (*text == '\0') return false;
  OtisAdaptiveHybridWide magnitude;
  for (; *text != '\0'; ++text) {
    if (*text < '0' || *text > '9') return false;
    OtisAdaptiveHybridWide scaled;
    if (!magnitude_multiply_small(magnitude, 10u, &scaled) ||
        !magnitude_add_small(scaled, static_cast<uint32_t>(*text - '0'),
                             &magnitude))
      return false;
  }
  *result = OtisAdaptiveHybridWide(magnitude.magnitude_high, magnitude.magnitude_low,
                         negative);
  return true;
}

bool otis_adaptive_hybrid_wide_format_decimal(OtisAdaptiveHybridWide value, char *output,
                                    size_t output_size) {
  if (output == nullptr || output_size == 0u ||
      !otis_adaptive_hybrid_wide_valid(value))
    return false;
  if (otis_adaptive_hybrid_wide_is_zero(value)) {
    if (output_size < 2u) return false;
    memcpy(output, "0", 2u);
    return true;
  }
  char reversed[39] = {};
  size_t count = 0u;
  OtisAdaptiveHybridWide remaining(value.magnitude_high, value.magnitude_low, false);
  const OtisAdaptiveHybridWide ten(10);
  while (!otis_adaptive_hybrid_wide_is_zero(remaining)) {
    OtisAdaptiveHybridWide quotient;
    OtisAdaptiveHybridWide remainder;
    if (!magnitude_divide(remaining, ten, &quotient, &remainder) ||
        remainder.magnitude_high != 0u || remainder.magnitude_low > 9u ||
        count >= sizeof(reversed))
      return false;
    reversed[count++] =
        static_cast<char>('0' + static_cast<char>(remainder.magnitude_low));
    remaining = quotient;
  }
  const size_t required = count + (value.negative ? 1u : 0u) + 1u;
  if (output_size < required) return false;
  size_t cursor = 0u;
  if (value.negative) output[cursor++] = '-';
  while (count != 0u) output[cursor++] = reversed[--count];
  output[cursor] = '\0';
  return true;
}
