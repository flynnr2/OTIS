#include <assert.h>
#include <string.h>

#include "otis_decimal_format.h"

int main() {
  char value[64] = {};
  assert(otis_format_fixed(9999992.766666667536, 12u, value,
                           sizeof(value)));
  assert(strcmp(value, "9999992.766666667536") == 0);
  assert(otis_format_fixed(-7.233333332464, 12u, value, sizeof(value)));
  assert(strcmp(value, "-7.233333332464") == 0);
  assert(otis_format_fixed(1.9996, 3u, value, sizeof(value)));
  assert(strcmp(value, "2.000") == 0);
  assert(otis_format_fixed(-0.0, 3u, value, sizeof(value)));
  assert(strcmp(value, "-0.000") == 0);
  assert(!otis_format_fixed(1.0, 16u, value, sizeof(value)));
  char too_small[4] = {};
  assert(!otis_format_fixed(12.34, 2u, too_small, sizeof(too_small)));
  return 0;
}
