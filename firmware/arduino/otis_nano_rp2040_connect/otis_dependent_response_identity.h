#ifndef OTIS_DEPENDENT_RESPONSE_IDENTITY_H
#define OTIS_DEPENDENT_RESPONSE_IDENTITY_H

#include <stdint.h>

#include "otis_active_hybrid_decision_format.h"

// One completed response must remain identifiable until the first later AHY
// decision has been serialized successfully. The controller may clear its
// transaction state before that decision, so this record is deliberately
// independent of the mutable transaction capsule.
struct OtisDependentResponseIdentity {
  bool pending;
  uint32_t request_sequence;
  uint32_t application_sequence;
  const char *response_class;
};

inline void otis_dependent_response_identity_reset(
    OtisDependentResponseIdentity *identity) {
  if (identity == nullptr) return;
  identity->pending = false;
  identity->request_sequence = 0u;
  identity->application_sequence = 0u;
  identity->response_class = "unavailable";
}

inline bool otis_dependent_response_identity_retain(
    OtisDependentResponseIdentity *identity, uint32_t request_sequence,
    uint32_t application_sequence, const char *response_class) {
  if (identity == nullptr || identity->pending || request_sequence == 0u ||
      application_sequence == 0u || response_class == nullptr)
    return false;
  identity->pending = true;
  identity->request_sequence = request_sequence;
  identity->application_sequence = application_sequence;
  identity->response_class = response_class;
  return true;
}

inline bool otis_dependent_response_identity_apply(
    const OtisDependentResponseIdentity *identity,
    OtisActiveHybridDecisionRecordContext *context) {
  if (identity == nullptr || context == nullptr || !identity->pending)
    return false;
  context->request_sequence = identity->request_sequence;
  context->acceptance_sequence = identity->request_sequence;
  context->application_sequence = identity->application_sequence;
  context->response_class = identity->response_class;
  return true;
}

inline bool otis_dependent_response_identity_consume(
    OtisDependentResponseIdentity *identity) {
  if (identity == nullptr || !identity->pending) return false;
  otis_dependent_response_identity_reset(identity);
  return true;
}

#endif
