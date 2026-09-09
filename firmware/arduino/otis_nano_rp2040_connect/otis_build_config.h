#ifndef OTIS_BUILD_CONFIG_H
#define OTIS_BUILD_CONFIG_H

// Make fixed-image build provenance visible to every Arduino translation unit.
#if defined(ARDUINO)
#if __has_include("otis_build_manifest.generated.h")
#include "otis_build_manifest.generated.h"
#else
#error "Build the fixed firmware with tools/build_firmware.py"
#endif
#else
// Host C++ harnesses still exercise the same exact-SHA validation paths as the
// fixed Arduino image.  Supply a syntactically valid sentinel without
// pretending that the host executable is bound to a repository profile.
#define OTIS_HOST_TEST_SHA256_SENTINEL                                      \
  "00000000" "00000000" "00000000" "00000000"                           \
  "00000000" "00000000" "00000000" "00000000"
#define OTIS_BUILD_ADAPTIVE_POLICY_SHA256 OTIS_HOST_TEST_SHA256_SENTINEL
#define OTIS_BUILD_FREQUENCY_ESTIMATOR_SHA256 OTIS_HOST_TEST_SHA256_SENTINEL
#define OTIS_BUILD_PHASE_ESTIMATOR_SHA256 OTIS_HOST_TEST_SHA256_SENTINEL
#define OTIS_BUILD_PLANT_MODEL_SHA256 OTIS_HOST_TEST_SHA256_SENTINEL
#define OTIS_BUILD_RESPONSE_POLICY_SHA256 OTIS_HOST_TEST_SHA256_SENTINEL
#define OTIS_BUILD_PHASE_ESTIMATOR_ID "OTIS_RELATIVE_PHASE_ESTIMATOR_V1"
#define OTIS_BUILD_PHASE_RAW_METHOD_ID \
  "D14_REFERENCED_D8_RELATIVE_PHASE_ACCUMULATOR_V1"
#define OTIS_BUILD_FORWARDED_CLOCK_CONTRACT_ID "host_test_non_firmware"
#define OTIS_BUILD_FORWARDED_CLOCK_CONTRACT_SHA256 OTIS_HOST_TEST_SHA256_SENTINEL
#define OTIS_BUILD_FREQUENCY_ESTIMATOR_TAG_U64 0ULL
#endif

#endif
