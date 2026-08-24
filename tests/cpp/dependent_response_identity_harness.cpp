#include <assert.h>
#include <stdio.h>

#include "otis_active_hybrid_decision_format.h"
#include "otis_active_hybrid_policy_engine.h"
#include "otis_cx317_active_live.h"
#include "otis_dependent_response_identity.h"

int main() {
  OtisDependentResponseIdentity retained = {};
  otis_dependent_response_identity_reset(&retained);

  for (uint32_t sequence = 1u; sequence <= 4u; ++sequence) {
    const uint16_t code = static_cast<uint16_t>(43064u - sequence);
    const uint32_t epoch = sequence + 1u;
    const char *classification =
        sequence == 3u ? "inside_deadband"
                       : "healthy_indeterminate_near_resolution";
    assert(otis_dependent_response_identity_retain(
        &retained, sequence, sequence + 10u, classification));
    assert(!otis_dependent_response_identity_retain(
        &retained, sequence + 100u, sequence + 110u, "wrong_sign"));

    const OtisCx317ActiveLiveDecision source = {
        1u, 1799u, 2399u, 2401u + sequence, code, 0, code,
        0.00166666694, true, true, true, true, 1u,
        static_cast<int32_t>(sequence), "OUTSIDE", epoch, 1u, sequence, 4,
        epoch, code, true, true, false, true,
    };
    const OtisActiveHybridDecision decision = {
        sequence,
        2401u + sequence,
        OtisActiveHybridState::HybridTracking,
        OtisActiveHybridState::HybridTracking,
        "first_dependent_response_consumer",
        -0.00166666694,
        0.0,
        -0.00166666694,
        0.0,
        0,
        code,
        0,
        false,
        false,
        false,
        false,
        false,
        false,
        static_cast<uint16_t>(sequence),
        static_cast<uint16_t>(sequence),
    };
    OtisActiveHybridDecisionRecordContext context = {
        sequence,
        "otis_sustained_hybrid_regulation_v1:repair",
        "source_sha256:config_sha256",
        "otis_sustained_hybrid_regulation_v1",
        "frequency_estimator_sha256",
        "phase_estimator_sha256",
        "ARMED",
        0u,
        0u,
        0u,
        "unavailable",
        true,
        "active_policy_sha256",
        "response_policy_sha256",
        false,
    };

    assert(otis_dependent_response_identity_apply(&retained, &context));
    assert(context.request_sequence == sequence);
    assert(context.acceptance_sequence == sequence);
    assert(context.application_sequence == sequence + 10u);
    assert(context.response_class == classification);

    // A failed queue attempt must leave the identity available for the next
    // successful serialization.
    OtisActiveHybridDecisionRecordContext retry = context;
    retry.request_sequence = 0u;
    retry.acceptance_sequence = 0u;
    retry.application_sequence = 0u;
    retry.response_class = "unavailable";
    assert(otis_dependent_response_identity_apply(&retained, &retry));

    char output[1536] = "";
    const int used = otis_format_active_hybrid_decision_v1(
        output, sizeof(output), &source, &decision, &retry);
    assert(used > 0 && static_cast<size_t>(used) < sizeof(output));
    fputs(output, stdout);
    assert(otis_dependent_response_identity_consume(&retained));
    assert(!retained.pending);
  }
  return 0;
}
