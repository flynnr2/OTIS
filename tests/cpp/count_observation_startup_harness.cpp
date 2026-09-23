#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
#include <string>

#include "otis_count_observation.h"
#include "otis_dual_core_partition.h"
#include "otis_emit.h"
#include "otis_frequency_regulation_live.h"
#include "otis_phase_preview_live.h"
#include "otis_reference_acceptance_format.h"
#include "otis_reference_acceptance_policy.generated.h"
#include "otis_reference_record.h"
#include "otis_service_latency.h"
#include "otis_timebase.h"
#include "otis_pps_snapshot_backend.h"
#include "otis_protocol.h"

unsigned int mock_core_num = 1;
uint32_t mock_ticks = 0;
uint32_t micros() { return mock_ticks; }
uint32_t millis() { return mock_ticks / 1000u; }

std::vector<OtisTelemetryMessage> telemetry;
std::vector<OtisObservationMessage> observations;
bool congested = false;
bool bridge_active = false;
std::vector<std::string> bridge_events;
void bridge_event(const char *event) {
  if (bridge_active && (bridge_events.empty() || bridge_events.back() != event))
    bridge_events.emplace_back(event);
}
bool otis_dual_core_timing_owner_active() { return true; }
bool otis_dual_core_publish_telemetry(const OtisTelemetryMessage *message) {
  bridge_event("status");
  telemetry.push_back(*message);
  // Deliberately slow sink: ordering is tested independently of native speed.
  mock_ticks += 100;
  return !congested;
}
bool otis_dual_core_publish_observation(const OtisObservationMessage *message) {
  bridge_event("CNT");
  observations.push_back(*message);
  return true;
}
bool otis_pps_snapshot_backend_begin() { return true; }
void otis_pps_snapshot_backend_get_stats(OtisPpsSnapshotBackendStats *out) {
  *out = {};
  out->initialized = out->running = true;
  out->session = 1;
  out->ring_capacity = 128;
  out->system_clock_hz = 133000000;
}
void otis_status_emit(OtisStatusEmitContext *, const char *, const char *,
                      const char *, const char *, uint32_t) { assert(false); }
void otis_status_emit_u32(OtisStatusEmitContext *, const char *, const char *,
                          uint32_t, const char *, uint32_t) { assert(false); }
void otis_emit_count_observation(uint32_t, uint32_t, uint64_t, uint64_t,
                                 const char *, uint64_t, const char *,
                                 const char *, uint32_t) { assert(false); }

// Execute the production .ino boundary function against the real count
// module. Only its surrounding services are doubles, so call-order checks
// observe the bridge itself rather than a second handwritten implementation.
OtisRuntimeState runtime_state = {};
OtisStatusEmitContext status_emit_context = {};
OtisReferenceAcceptanceLive reference_acceptance(OTIS_REFERENCE_ACCEPTANCE_POLICY);
OtisEvidenceFrameMessage dual_core_reference_evidence_scratch = {};
uint64_t time_us_64() { return mock_ticks; }
OtisCountObservationConfig count_observation_config() {
  return {1000000u, 0u, 0u, OTIS_DOMAIN_H1_OSCILLATOR_10MHZ};
}
OtisRegulationStaticCodeState regulation_static_code_state() { return {}; }
void note_reference_service_latency(uint32_t, uint32_t,
    OtisServiceLatencyStage stage, uint32_t start, uint32_t end) {
  if (stage == OTIS_LATENCY_READY_TO_FIRST_ESTIMATOR_CONSUMPTION)
    assert(end - start < 100u);  // The injected slow status sink has not run.
}
bool otis_dual_core_publish_evidence(const OtisEvidenceFrameMessage *) {
  bridge_event("APS");
  return true;
}
void otis_dual_core_latch_fault(OtisPartitionFault) { assert(false); }
void otis_dual_core_note_timing_count(uint32_t) {}
void otis_phase_preview_live_on_reference_selection(
    const OtisReferenceAcceptanceOutcome *, uint64_t, bool) {
  bridge_event("phase");
}
void update_adaptive_hybrid_regulation_health() {
  bridge_event("health");
  // The production health bridge refreshes this state unconditionally. It
  // must not be the accidental location of the deferred status emission.
  reference_acceptance.service(time_us_64());
  const size_t before = telemetry.size();
  otis_count_observation_update_reference_acceptance(reference_acceptance.status());
  assert(telemetry.size() == before);
}
void otis_frequency_regulation_live_on_reference_selection(
    const OtisReferenceAcceptanceOutcome *, uint64_t, uint32_t, uint64_t,
    const OtisRegulationStaticCodeState *,
    OtisAdaptiveHybridRegulationLiveOutcome *) {
  bridge_event("frequency");
}
void otis_emit_dac_step(uint32_t, uint32_t, int32_t, uint16_t, uint16_t, bool,
    const char *, const char *, uint32_t, const char *, uint32_t) { assert(false); }
#include "count_boundary_bridge.inc"

std::vector<std::string> values(const char *key) {
  std::vector<std::string> result;
  for (const auto &row : telemetry)
    if (std::strcmp(row.key, key) == 0) result.emplace_back(row.value);
  return result;
}

int main() {
  OtisRuntimeState runtime = {};
  OtisStatusEmitContext context = {};
  const OtisCountObservationConfig config = {
      1000000u, 60000u, 0u, OTIS_DOMAIN_H1_OSCILLATOR_10MHZ};
  assert(otis_count_observation_begin(&runtime, &context, &config));
  telemetry.clear();
  auto accepted = OtisAcceptedReferenceStatus{};
  accepted.capture_session = 1;
  accepted.state = "acquiring";
  otis_count_observation_update_reference_acceptance(accepted);

  OtisPpsCountBoundaryObservation boundary = {};
  boundary.session = 1;
  boundary.cumulative_down_counter = UINT32_MAX;
  boundary.capture_flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
  for (uint32_t sequence = 0; sequence < 3; ++sequence) {
    boundary.sequence = boundary.reference_sequence = sequence;
    boundary.pps_timestamp_ticks = 1000000u + sequence * 1000000u;
    boundary.cumulative_down_counter = UINT32_MAX - sequence * 10000000u;
    mock_ticks = uint32_t(boundary.pps_timestamp_ticks) + 50;
    telemetry.clear();
    observations.clear();
    const uint32_t before = mock_ticks;
    const bool complete = otis_count_observation_on_pps_boundary(
        &runtime, &context, &config, &boundary);
    assert(complete == (sequence != 0));
    assert(telemetry.empty());
    assert(mock_ticks == before);
    // Canonical CNT is already available to consumers, without status cost.
    assert(observations.size() == (sequence == 0 ? 0u : 1u));
    if (sequence != 0) {
      const auto &count = observations.back().count;
      assert(count.sequence == sequence && count.counted_edges == 10000000u);
      assert(count.gate_open_ticks == sequence * 1000000u);
      assert(count.gate_close_ticks == boundary.pps_timestamp_ticks);
    }
    otis_count_observation_note_control_consumer(1, sequence);
    otis_count_observation_emit_pending_boundary_status();
    const size_t emitted = telemetry.size();
    std::printf("sequence=%u transition_rows=%zu\n", sequence, emitted);
    if (sequence < 2) {
      assert(emitted > 50);
      assert(values("snapshot") == std::vector<std::string>({"begin", "end"}));
      assert(values("boundary_sequence") == std::vector<std::string>({std::to_string(sequence)}));
    } else {
      assert(emitted == 0);
    }
    otis_count_observation_emit_pending_boundary_status();
    assert(telemetry.size() == emitted);  // Exactly once.
  }

  // A rejected raw pair still retains its status and canonical adjacent CNT.
  boundary.sequence = boundary.reference_sequence = 3;
  boundary.pps_timestamp_ticks += 1000000u;
  boundary.cumulative_down_counter -= 10000000u;
  boundary.aperture_flags = OTIS_PPS_APERTURE_COUNTER_SNAPSHOT_INVALID;
  telemetry.clear();
  observations.clear();
  assert(otis_count_observation_on_pps_boundary(&runtime, &context, &config, &boundary));
  assert(telemetry.empty() && observations.size() == 1);
  assert(observations.back().count.flags & OTIS_FLAG_SOURCE_HEALTH_SUSPECT);

  // A reference fault must flush that transition before replacing its state.
  accepted.state = "lost";
  otis_count_observation_update_reference_acceptance(accepted);
  assert(values("reference_acceptance_state") == std::vector<std::string>({"acquiring"}));
  assert(values("window_invalid_reason") == std::vector<std::string>({"counter_snapshot_invalid"}));
  const size_t rejected_rows = telemetry.size();
  otis_count_observation_note_capture_loss(&runtime, &context, 4, "test_capture_fault");
  assert(telemetry.size() > rejected_rows);
  assert(values("reference_acceptance_state") == std::vector<std::string>({"acquiring", "lost"}));
  otis_count_observation_emit_pending_boundary_status();
  assert(values("snapshot").size() == 4);

  // A new-session opener still reports exactly once with a congested sink;
  // failed diagnostic publication cannot change count/control state.
  ++boundary.session;
  boundary.sequence = boundary.reference_sequence = 0;
  boundary.aperture_flags = 0;
  telemetry.clear();
  assert(!otis_count_observation_on_pps_boundary(&runtime, &context, &config, &boundary));
  const auto before_drop = runtime.tcxo;
  congested = true;
  otis_count_observation_emit_pending_boundary_status();
  assert(before_drop.last_counted_edges == runtime.tcxo.last_counted_edges);
  assert(before_drop.last_window_flags == runtime.tcxo.last_window_flags);
  assert(before_drop.last_observation_valid == runtime.tcxo.last_observation_valid);
  assert(before_drop.valid_for_control == runtime.tcxo.valid_for_control);
  assert(values("snapshot") == std::vector<std::string>({"begin", "end"}));
  assert(values("boundary_sequence") == std::vector<std::string>({"0"}));

  // Defensive flush protects the preceding transition even if the next
  // boundary is entered without the normal integrated end-of-boundary call.
  congested = false;
  ++boundary.session;
  telemetry.clear();
  assert(!otis_count_observation_on_pps_boundary(&runtime, &context, &config, &boundary));
  boundary.sequence = boundary.reference_sequence = 1;
  boundary.pps_timestamp_ticks += 1000000u;
  boundary.cumulative_down_counter -= 10000000u;
  assert(otis_count_observation_on_pps_boundary(&runtime, &context, &config, &boundary));
  assert(values("boundary_sequence") == std::vector<std::string>({"0"}));
  // A direct capture fault flushes the first-window report before loss state.
  otis_count_observation_note_capture_loss(&runtime, &context, 2, "second_fault");
  assert(values("boundary_sequence") == std::vector<std::string>({"0", "1"}));
  assert(values("capture_state") == std::vector<std::string>({"lost", "lost", "lost"}));
  const auto final_size = telemetry.size();
  otis_count_observation_emit_pending_boundary_status();
  assert(telemetry.size() == final_size);

  const auto bridge_config = count_observation_config();
  assert(otis_count_observation_begin(&runtime_state, &status_emit_context, &bridge_config));
  bridge_active = true;
  for (uint32_t sequence = 0; sequence < 10; ++sequence) {
    boundary = {};
    boundary.session = 9;
    boundary.sequence = boundary.reference_sequence = sequence;
    boundary.pps_timestamp_ticks = 10000000u + sequence * 1000000u;
    boundary.cumulative_down_counter = UINT32_MAX - sequence * 10000000u;
    boundary.capture_flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
    mock_ticks = uint32_t(boundary.pps_timestamp_ticks) + 10;
    bridge_events.clear();
    telemetry.clear();
    emit_pps_count_boundary(boundary, 0u, mock_ticks);
    std::vector<std::string> expected;
    if (sequence != 0) expected.emplace_back("CNT");
    if (sequence >= 9) expected.emplace_back("APS");
    expected.emplace_back("phase");
    if (!telemetry.empty()) expected.emplace_back("status");
    expected.emplace_back("health");
    expected.emplace_back("frequency");
    assert(bridge_events == expected);
    if (sequence < 2) assert(!telemetry.empty());
  }
  return 0;
}
