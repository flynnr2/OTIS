#ifndef OTIS_BUILD_PROFILE_CONFIG_H
#define OTIS_BUILD_PROFILE_CONFIG_H

// Make generated build selectors visible to every Arduino translation unit.
// Host-side numerical harnesses may instead define a selector explicitly.
#if defined(ARDUINO)
#if __has_include("otis_build_profile.generated.h")
#include "otis_build_profile.generated.h"
#else
#error "Generate an Arduino profile first: python3 tools/firmware_matrix.py --prepare-ide --profile <profile_id>"
#endif
#endif

#ifndef OTIS_SELECTED_HYBRID_EXTERNAL_DAC_EPOCH_RESEED
#define OTIS_SELECTED_HYBRID_EXTERNAL_DAC_EPOCH_RESEED 0
#endif

#endif
