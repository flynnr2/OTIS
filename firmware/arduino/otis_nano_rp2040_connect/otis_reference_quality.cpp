#include "otis_reference_quality.h"

#include <stdio.h>
#include <string.h>

const char kOtisReferenceQualityAlgorithmVersion[] = "reference_quality_v1";
const char kOtisReferenceQualityConfigHash[] =
    "3d6dcd06301ab9a0050db43a4201c330ee487cb28fa06f605568326ab8f22911";

namespace {

enum Reason : uint32_t {
  REASON_REFERENCE_UNAVAILABLE = 1u << 0,
  REASON_REFERENCE_MISSING = 1u << 1,
  REASON_CONTINUITY_UNAVAILABLE = 1u << 2,
  REASON_SEQUENCE_NONMONOTONIC = 1u << 3,
  REASON_FLAGGED_INVALID = 1u << 4,
  REASON_PPS_DUPLICATE = 1u << 5,
  REASON_PPS_SHORT = 1u << 6,
  REASON_PPS_LONG = 1u << 7,
  REASON_CADENCE_VALID = 1u << 8,
  REASON_METADATA_MISSING = 1u << 9,
  REASON_METADATA_STALE = 1u << 10,
  REASON_ANTENNA_FAULT = 1u << 11,
  REASON_HOLDOVER = 1u << 12,
  REASON_RECEIVER_QUALIFIED = 1u << 13,
  REASON_AUTHORITY_UNKNOWN = 1u << 14,
};

const char *authority_name(OtisReferenceAuthority value) {
  switch (value) {
    case OTIS_REFERENCE_AUTHORITY_QUALIFIED: return "qualified";
    case OTIS_REFERENCE_AUTHORITY_HOLDOVER: return "holdover";
    case OTIS_REFERENCE_AUTHORITY_FIX_UNAVAILABLE: return "fix_unavailable";
    case OTIS_REFERENCE_AUTHORITY_ANTENNA_FAULT: return "antenna_fault";
    case OTIS_REFERENCE_AUTHORITY_INVALID: return "invalid";
    case OTIS_REFERENCE_AUTHORITY_UNAVAILABLE: return "unavailable";
    case OTIS_REFERENCE_AUTHORITY_UNKNOWN: return "unknown";
  }
  return "unknown";
}

const char *utc_name(OtisReferenceUtc value) {
  switch (value) {
    case OTIS_REFERENCE_UTC_VALID: return "valid";
    case OTIS_REFERENCE_UTC_INVALID: return "invalid";
    case OTIS_REFERENCE_UTC_UNAVAILABLE: return "unavailable";
    case OTIS_REFERENCE_UTC_UNKNOWN: return "unknown";
  }
  return "unknown";
}

void append_reason(char *buffer, size_t capacity, const char *reason) {
  const size_t used = strlen(buffer);
  if (used >= capacity - 1u) return;
  snprintf(buffer + used, capacity - used, "%s%s", used == 0u ? "" : ";",
           reason);
}

}  // namespace

OtisReferenceQualityResult otis_assess_reference_quality(
    const OtisReferenceEvidence *previous,
    const OtisReferenceEvidence *current, uint64_t now_ticks,
    const OtisReferenceMetadata *metadata,
    const OtisReferenceQualityConfig *config) {
  OtisReferenceQualityResult result = {
      "unavailable", "unavailable", "unknown", "unknown", "missing",
      "unknown", 0u};
  if (current == nullptr || !current->present) {
    result.reason_mask |= REASON_REFERENCE_UNAVAILABLE;
  } else if (now_ticks >= current->ticks &&
             now_ticks - current->ticks > config->reference_max_age_ticks) {
    result.cadence_state = "missing";
    result.reason_mask |= REASON_REFERENCE_MISSING;
  } else if (previous == nullptr || !previous->present) {
    result.reason_mask |= REASON_CONTINUITY_UNAVAILABLE;
  } else if (current->seq <= previous->seq) {
    result.cadence_state = "invalid";
    result.capture_path_state = "sequence_gap";
    result.reason_mask |= REASON_SEQUENCE_NONMONOTONIC;
  } else if ((current->flags & config->invalid_flag_mask) != 0u) {
    result.cadence_state = "invalid";
    result.capture_path_state = "invalid";
    result.reason_mask |= REASON_FLAGGED_INVALID;
  } else {
    result.capture_path_state = "valid";
    const uint64_t minimum =
        config->nominal_interval_ticks - config->interval_tolerance_ticks;
    const uint64_t maximum =
        config->nominal_interval_ticks + config->interval_tolerance_ticks;
    if (current->ticks <= previous->ticks) {
      result.cadence_state = "duplicate";
      result.reason_mask |= REASON_PPS_DUPLICATE;
    } else {
      const uint64_t interval = current->ticks - previous->ticks;
      if (interval < minimum) {
        result.cadence_state = "short";
        result.reason_mask |= REASON_PPS_SHORT;
      } else if (interval > maximum) {
        result.cadence_state = "long";
        result.reason_mask |= REASON_PPS_LONG;
      } else {
        result.cadence_state = "valid";
        result.reason_mask |= REASON_CADENCE_VALID;
      }
    }
  }

  if (metadata == nullptr || !metadata->present) {
    result.reason_mask |= REASON_METADATA_MISSING;
  } else {
    result.receiver_authority_state = authority_name(metadata->authority);
    result.utc_traceability_state = utc_name(metadata->utc);
    if (metadata->ticks > now_ticks ||
        now_ticks - metadata->ticks > config->metadata_max_age_ticks) {
      result.metadata_freshness = "stale";
      result.reason_mask |= REASON_METADATA_STALE;
    } else {
      result.metadata_freshness = "current";
    }
  }

  if (strcmp(result.capture_path_state, "sequence_gap") == 0 ||
      strcmp(result.capture_path_state, "overflow") == 0 ||
      strcmp(result.capture_path_state, "resource_failure") == 0 ||
      strcmp(result.capture_path_state, "invalid") == 0) {
    result.qualification_state = "capture_path_invalid";
  } else if (strcmp(result.cadence_state, "valid") != 0) {
    result.qualification_state =
        strcmp(result.cadence_state, "unavailable") == 0 ? "unknown" :
                                                          "unqualified";
  } else if (strcmp(result.metadata_freshness, "current") != 0) {
    result.qualification_state =
        strcmp(result.metadata_freshness, "stale") == 0
            ? "metadata_stale"
            : "cadence_valid_authority_unknown";
  } else if (metadata->authority == OTIS_REFERENCE_AUTHORITY_ANTENNA_FAULT ||
             metadata->antenna_state == OTIS_REFERENCE_ANTENNA_FAULT) {
    result.qualification_state = "antenna_fault";
    result.reason_mask |= REASON_ANTENNA_FAULT;
  } else if (metadata->authority == OTIS_REFERENCE_AUTHORITY_HOLDOVER ||
             metadata->fix_state == OTIS_REFERENCE_FIX_HOLDOVER) {
    result.qualification_state = "holdover";
    result.reason_mask |= REASON_HOLDOVER;
  } else if (metadata->utc == OTIS_REFERENCE_UTC_INVALID) {
    result.qualification_state = "utc_invalid";
  } else if (metadata->authority == OTIS_REFERENCE_AUTHORITY_QUALIFIED &&
             metadata->utc == OTIS_REFERENCE_UTC_VALID) {
    result.qualification_state = "qualified";
    result.reason_mask |= REASON_RECEIVER_QUALIFIED;
  } else {
    result.qualification_state = "cadence_valid_authority_unknown";
    result.reason_mask |= REASON_AUTHORITY_UNKNOWN;
  }
  return result;
}

void otis_reference_quality_reasons(uint32_t reason_mask, char *buffer,
                                    size_t capacity) {
  if (capacity == 0u) return;
  buffer[0] = '\0';
  const struct {
    uint32_t mask;
    const char *name;
  } reasons[] = {
      {REASON_REFERENCE_UNAVAILABLE, "reference_unavailable"},
      {REASON_REFERENCE_MISSING, "reference_missing"},
      {REASON_CONTINUITY_UNAVAILABLE, "reference_continuity_unavailable"},
      {REASON_SEQUENCE_NONMONOTONIC, "reference_sequence_nonmonotonic"},
      {REASON_FLAGGED_INVALID, "reference_flagged_invalid"},
      {REASON_PPS_DUPLICATE, "reference_pps_duplicate"},
      {REASON_PPS_SHORT, "reference_pps_short_interval"},
      {REASON_PPS_LONG, "reference_pps_long_interval"},
      {REASON_CADENCE_VALID, "reference_cadence_valid"},
      {REASON_METADATA_MISSING, "reference_metadata_missing"},
      {REASON_METADATA_STALE, "reference_metadata_stale"},
      {REASON_ANTENNA_FAULT, "reference_antenna_fault"},
      {REASON_HOLDOVER, "reference_receiver_holdover"},
      {REASON_RECEIVER_QUALIFIED, "reference_receiver_qualified"},
      {REASON_AUTHORITY_UNKNOWN, "reference_authority_unknown"},
  };
  for (const auto &reason : reasons)
    if ((reason_mask & reason.mask) != 0u)
      append_reason(buffer, capacity, reason.name);
}
