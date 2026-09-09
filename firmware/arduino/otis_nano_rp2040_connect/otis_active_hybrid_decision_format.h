#ifndef OTIS_ACTIVE_HYBRID_DECISION_FORMAT_H
#define OTIS_ACTIVE_HYBRID_DECISION_FORMAT_H

#include <stddef.h>
#include <stdint.h>

struct OtisActiveHybridDecision;
struct OtisAdaptiveHybridRegulationLiveDecision;

struct OtisActiveHybridDecisionRecordContext {
  uint32_t hybrid_record_sequence;
  uint64_t decision_timestamp_ticks;
  const char *run_identity;
  const char *build_identity;
  const char *image_identity;
  const char *frequency_estimator_sha256;
  const char *phase_estimator_sha256;
  const char *authority_state;
  uint32_t request_sequence;
  uint32_t acceptance_sequence;
  uint32_t application_sequence;
  const char *response_class;
  bool downstream_epoch_exact;
  const char *active_policy_sha256;
  const char *response_policy_sha256;
  bool actionable;
};

// Format the exact wire representation consumed by the host CSV splitter.
// Keeping this boundary independently executable prevents a declaration-only
// schema check from passing when the firmware formatter omits a field.
int otis_format_active_hybrid_decision_v2(
    char *output, size_t output_size,
    const OtisAdaptiveHybridRegulationLiveDecision *source,
    const OtisActiveHybridDecision *decision,
    const OtisActiveHybridDecisionRecordContext *context);

#endif
