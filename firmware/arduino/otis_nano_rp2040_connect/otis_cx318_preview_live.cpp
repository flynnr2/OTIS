#include "otis_cx318_preview_live.h"

#include <stddef.h>
#include <string.h>

#include "otis_config.h"
#include "otis_cx318_selected_preview_engine.h"
#include "otis_dual_core_partition.h"

namespace {

constexpr uint64_t kReferenceTicksPerSecond = 16000000ull;
constexpr uint64_t kReferenceTimestampModulus =
    kReferenceTicksPerSecond * (1ull << 32) / 1000000ull;
constexpr uint16_t kMinimumCharacterizedCode = 0xA800u;
constexpr uint16_t kMaximumCharacterizedCode = 0xAB00u;

OtisCx318SelectedPreviewEngine engine = {};
bool initialized = false;
bool have_reference_timestamp = false;
bool reset_pending = false;
uint64_t previous_reference_timestamp = 0u;
uint64_t unwrapped_reference_timestamp = 0u;
uint16_t static_code = 0u;
uint32_t static_dac_epoch = 0u;
uint32_t preview_sequence = 0u;
uint32_t published_records = 0u;
uint32_t last_phase_epoch = 0u;
uint32_t last_observation_sequence = 0u;
bool have_frequency_event_timestamp = false;
uint64_t last_frequency_event_timestamp = 0u;

template <typename T>
T atomic_load_acquire(const T *value) {
  return __atomic_load_n(value, __ATOMIC_ACQUIRE);
}

template <typename T>
void atomic_store_release(T *destination, T value) {
  __atomic_store_n(destination, value, __ATOMIC_RELEASE);
}

template <size_t Capacity>
void copy_text(char (&destination)[Capacity], const char *source) {
  if (Capacity == 0u) return;
  size_t length = 0u;
  if (source != nullptr) {
    while (length + 1u < Capacity && source[length] != '\0') ++length;
    if (length > 0u) memcpy(destination, source, length);
  }
  destination[length] = '\0';
}

uint64_t unwrap_reference_timestamp(uint64_t raw_ticks) {
  if (!have_reference_timestamp) {
    have_reference_timestamp = true;
    previous_reference_timestamp = raw_ticks;
    unwrapped_reference_timestamp = raw_ticks;
    return unwrapped_reference_timestamp;
  }
  const uint64_t delta =
      (raw_ticks + kReferenceTimestampModulus - previous_reference_timestamp) %
      kReferenceTimestampModulus;
  previous_reference_timestamp = raw_ticks;
  unwrapped_reference_timestamp += delta;
  return unwrapped_reference_timestamp;
}

}  // namespace

bool otis_cx318_preview_live_begin(uint16_t confirmed_static_code,
                                   uint32_t dac_epoch) {
#if OTIS_ENABLE_CX318_STAGE4_PREVIEW
  // Core 0 publishes status while Core 1 owns the preview engine.  Withdraw
  // readiness before changing the immutable binding and publish it only after
  // the complete state has been initialized.
  atomic_store_release(&initialized, false);
  if (confirmed_static_code < kMinimumCharacterizedCode ||
      confirmed_static_code > kMaximumCharacterizedCode)
    return false;
  engine = {};
  if (!otis_cx318_selected_preview_init(&engine, confirmed_static_code))
    return false;
  have_reference_timestamp = false;
  reset_pending = true;
  previous_reference_timestamp = 0u;
  unwrapped_reference_timestamp = 0u;
  static_code = confirmed_static_code;
  static_dac_epoch = dac_epoch;
  preview_sequence = 0u;
  have_frequency_event_timestamp = false;
  last_frequency_event_timestamp = 0u;
  atomic_store_release(&published_records, static_cast<uint32_t>(0));
  atomic_store_release(&last_phase_epoch, static_cast<uint32_t>(0));
  atomic_store_release(&last_observation_sequence, static_cast<uint32_t>(0));
  atomic_store_release(&initialized, true);
  return true;
#else
  (void)confirmed_static_code;
  (void)dac_epoch;
  return false;
#endif
}

void otis_cx318_preview_live_on_boundary(
    const OtisPpsCountBoundaryObservation *observation,
    uint32_t snapshot_status, uint32_t counted_edges,
    bool counted_edges_available, bool reference_qualified,
    bool phase_step_detected) {
#if OTIS_ENABLE_CX318_STAGE4_PREVIEW
  if (!atomic_load_acquire(&initialized) || observation == nullptr ||
      otis_dual_core_fail_static())
    return;
  const uint64_t unwrapped_ticks =
      unwrap_reference_timestamp(observation->pps_timestamp_ticks);
  const OtisCx318SelectedPreviewInput input = {
      observation->session,
      observation->sequence,
      observation->cumulative_down_counter,
      observation->reference_sequence,
      observation->pps_timestamp_ticks,
      snapshot_status,
      counted_edges,
      static_dac_epoch,
      static_cast<double>(unwrapped_ticks) /
          static_cast<double>(kReferenceTicksPerSecond),
      static_code,
      counted_edges_available,
      reference_qualified,
      reset_pending,
      phase_step_detected,
  };
  reset_pending = false;
  otis_dual_core_note_timing_progress(OtisTimingProgressPhase::Cx318Preview,
                                      unwrapped_ticks);
  OtisCx318SelectedPreviewOutput output = {};
  if (!otis_cx318_selected_preview_process(&engine, &input, &output)) {
    otis_dual_core_latch_fault(OtisPartitionFault::Cx318PreviewFault);
    return;
  }
  if (!output.frequency_available) {
    have_frequency_event_timestamp = false;
    last_frequency_event_timestamp = 0u;
  }
  if (output.frequency_observation_event) {
    have_frequency_event_timestamp = true;
    last_frequency_event_timestamp = unwrapped_ticks;
  }
  if (output.frequency_available && !have_frequency_event_timestamp) {
    otis_dual_core_latch_fault(OtisPartitionFault::Cx318PreviewFault);
    return;
  }

  OtisCx318PreviewRecordMessage message = {};
  message.preview_sequence = ++preview_sequence;
  message.decision_timestamp_ticks = unwrapped_ticks;
  message.phase_epoch = output.phase_epoch;
  message.observation_sequence = output.observation_sequence;
  message.capture_session = output.capture_session;
  message.opening_snapshot_sequence = output.opening_snapshot_sequence;
  message.closing_snapshot_sequence = output.closing_snapshot_sequence;
  message.opening_reference_sequence = output.opening_reference_sequence;
  message.closing_reference_sequence = output.closing_reference_sequence;
  message.dac_epoch = output.dac_epoch;
  message.interval_edges = output.interval_edges;
  message.edge_error_cycles = output.edge_error_cycles;
  message.relative_phase_cycles = output.relative_phase_cycles;
  message.relative_phase_time_ns = output.relative_phase_time_ns;
  message.raw_frequency_error_hz = output.raw_frequency_error_hz;
  message.observed_frequency_error_hz = output.observed_frequency_error_hz;
  message.frequency_estimate_age_s =
      output.frequency_available
          ? static_cast<double>(unwrapped_ticks -
                                last_frequency_event_timestamp) /
                static_cast<double>(kReferenceTicksPerSecond)
          : 0.0;
  message.modeled_relative_phase_cycles = output.modeled_relative_phase_cycles;
  message.modeled_frequency_error_hz = output.modeled_frequency_error_hz;
  message.frequency_term_hz = output.frequency_term_hz;
  message.phase_bias_hz = output.phase_bias_hz;
  message.combined_frequency_error_hz =
      output.combined_desired_frequency_change_hz;
  message.raw_counterfactual_delta_codes = output.raw_delta_codes;
  message.counterfactual_delta_codes = output.limited_delta_codes;
  message.actual_applied_code = output.actual_applied_code;
  message.shadow_code_before = output.shadow_code_before;
  message.shadow_code_after = output.shadow_code_after;
  message.correction_count = output.correction_count;
  message.cumulative_movement_codes = output.cumulative_movement_codes;
  message.alternating_correction_count = output.alternating_correction_count;
  message.phase_accepted = output.phase_accepted;
  message.interval_available = output.interval_available;
  message.raw_frequency_available = output.raw_frequency_available;
  message.modeled_frequency_available = output.frequency_available;
  message.frequency_observation_event = output.frequency_observation_event;
  message.counterfactual_decision = output.counterfactual_decision;
  message.counterfactual_correction = output.counterfactual_correction;
  message.raw_counterfactual_delta_available = output.raw_delta_available;
  message.step_limited = output.step_limited;
  message.range_clamped = output.range_clamped;
  message.modeled_not_observed_after_divergence =
      output.modeled_not_observed_after_divergence;
  copy_text(message.phase_qualification_state,
            otis_cx318_phase_state_name(output.phase_state));
  copy_text(message.phase_reason, output.phase_reason);
  copy_text(message.band_state_before, output.band_state_before);
  copy_text(message.band_state_after, output.band_state_after);
  copy_text(message.preview_state, output.preview_state);
  copy_text(message.decision_reason, output.decision_reason);
  if (!otis_dual_core_publish_cx318_preview(&message)) return;
  atomic_store_release(&last_phase_epoch, output.phase_epoch);
  atomic_store_release(&last_observation_sequence,
                       output.observation_sequence);
  __atomic_add_fetch(&published_records, 1u, __ATOMIC_RELEASE);
#else
  (void)observation;
  (void)snapshot_status;
  (void)counted_edges;
  (void)counted_edges_available;
  (void)reference_qualified;
  (void)phase_step_detected;
#endif
}

void otis_cx318_preview_live_note_reset(void) {
#if OTIS_ENABLE_CX318_STAGE4_PREVIEW
  reset_pending = true;
  have_reference_timestamp = false;
  have_frequency_event_timestamp = false;
  last_frequency_event_timestamp = 0u;
#endif
}

void otis_cx318_preview_live_get_status(OtisCx318PreviewLiveStatus *status) {
  if (status == nullptr) return;
  const bool ready = atomic_load_acquire(&initialized);
  *status = {};
  status->initialized = ready;
  status->static_code_bound = ready;
  if (ready) {
    status->static_code = static_code;
    status->dac_epoch = static_dac_epoch;
  }
  status->published_records = atomic_load_acquire(&published_records);
  status->last_phase_epoch = atomic_load_acquire(&last_phase_epoch);
  status->last_observation_sequence =
      atomic_load_acquire(&last_observation_sequence);
}
