#include <stdio.h>
#include <string.h>

#include "otis_active_timing_sidecar.h"

int main(int argc, char **argv) {
  if (argc != 2) return 2;
  char output[768] = {};
  int used = -1;
  if (strcmp(argv[1], "at2") == 0) {
    const OtisActiveTransactionTimingV2 record = {
        3u,
        2u,
        "application",
        57616000000ull,
        "d9_d6_frequency_only_endurance:1",
        "source_sha256:config_sha256",
        "d9_d6_frequency_only_lower",
        9u,
        1u,
        81u,
        100u,
        699u,
        4u,
        12345u,
        43023u,
        43023u,
        1u,
        2u,
        "applied_history_reset_response_required",
    };
    puts(otis_active_transaction_timing_v2_csv_header());
    used = otis_format_active_transaction_timing_v2(
        output, sizeof(output), &record);
  } else if (strcmp(argv[1], "ah2") == 0) {
    const OtisActiveHybridTimingV2 record = {
        2u,
        1u,
        81u,
        57600000000ull,
        "cx322_d9_d6_72h_sustained_hybrid:1",
        "source_sha256:config_sha256",
        "cx322_d9_d6_72h_sustained_engineering",
        9u,
        100u,
        699u,
        "phase_material_request_ready",
    };
    puts(otis_active_hybrid_timing_v2_csv_header());
    used = otis_format_active_hybrid_timing_v2(
        output, sizeof(output), &record);
  } else {
    return 3;
  }
  if (used <= 0 || static_cast<size_t>(used) >= sizeof(output)) return 4;
  fputs(output, stdout);
  return 0;
}
