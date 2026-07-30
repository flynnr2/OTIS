#pragma once

#include <stddef.h>
#include <stdint.h>

enum OtisReferenceAuthority : uint8_t {
  OTIS_REFERENCE_AUTHORITY_QUALIFIED = 0,
  OTIS_REFERENCE_AUTHORITY_HOLDOVER,
  OTIS_REFERENCE_AUTHORITY_FIX_UNAVAILABLE,
  OTIS_REFERENCE_AUTHORITY_ANTENNA_FAULT,
  OTIS_REFERENCE_AUTHORITY_INVALID,
  OTIS_REFERENCE_AUTHORITY_UNKNOWN,
  OTIS_REFERENCE_AUTHORITY_UNAVAILABLE,
};

enum OtisReferenceUtc : uint8_t {
  OTIS_REFERENCE_UTC_VALID = 0,
  OTIS_REFERENCE_UTC_INVALID,
  OTIS_REFERENCE_UTC_UNKNOWN,
  OTIS_REFERENCE_UTC_UNAVAILABLE,
};

enum OtisReferenceFixState : uint8_t {
  OTIS_REFERENCE_FIX_CURRENT = 0,
  OTIS_REFERENCE_FIX_HOLDOVER,
  OTIS_REFERENCE_FIX_UNKNOWN,
};

enum OtisReferenceAntennaState : uint8_t {
  OTIS_REFERENCE_ANTENNA_OK = 0,
  OTIS_REFERENCE_ANTENNA_FAULT,
  OTIS_REFERENCE_ANTENNA_UNKNOWN,
};

struct OtisReferenceQualityConfig {
  uint64_t nominal_interval_ticks;
  uint64_t interval_tolerance_ticks;
  uint64_t reference_max_age_ticks;
  uint64_t metadata_max_age_ticks;
  uint32_t invalid_flag_mask;
};

struct OtisReferenceEvidence {
  bool present;
  uint32_t seq;
  uint64_t ticks;
  uint32_t flags;
};

struct OtisReferenceMetadata {
  bool present;
  uint64_t ticks;
  OtisReferenceAuthority authority;
  OtisReferenceUtc utc;
  OtisReferenceFixState fix_state;
  OtisReferenceAntennaState antenna_state;
};

struct OtisReferenceQualityResult {
  const char *cadence_state;
  const char *capture_path_state;
  const char *receiver_authority_state;
  const char *utc_traceability_state;
  const char *metadata_freshness;
  const char *qualification_state;
  uint32_t reason_mask;
};

extern const char kOtisReferenceQualityAlgorithmVersion[];
extern const char kOtisReferenceQualityConfigHash[];

OtisReferenceQualityResult otis_assess_reference_quality(
    const OtisReferenceEvidence *previous,
    const OtisReferenceEvidence *current, uint64_t now_ticks,
    const OtisReferenceMetadata *metadata,
    const OtisReferenceQualityConfig *config);
void otis_reference_quality_reasons(uint32_t reason_mask, char *buffer,
                                    size_t capacity);
