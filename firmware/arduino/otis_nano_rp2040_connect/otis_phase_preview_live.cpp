#include "otis_phase_preview_live.h"

#include <stddef.h>
#include <string.h>

#include "otis_config.h"
#include "otis_selected_phase_frequency_preview_engine.h"
#include "otis_dual_core_partition.h"

namespace {

constexpr uint64_t kReferenceTicksPerSecond = 1000000ull;
constexpr uint64_t kReferenceTimestampModulus =
    kReferenceTicksPerSecond * (1ull << 32) / 1000000ull;
constexpr uint16_t kMinimumCharacterizedCode = 0xA800u;
constexpr uint16_t kMaximumCharacterizedCode = 0xAB00u;

OtisSelectedPhaseFrequencyPreviewEngine engine = {};
bool initialized = false;
bool applied_code_bound = false;
bool have_reference_timestamp = false;
bool reset_pending = false;
uint64_t previous_reference_timestamp = 0u;
uint64_t unwrapped_reference_timestamp = 0u;
// The timing owner is the sole writer after it consumes Core 0's confirmed
// application acknowledgement.  The generation still makes the separately
// atomic code and epoch one coherent boundary-time publication.
uint32_t applied_code_generation = 0u;
uint32_t published_applied_code = 0u;
uint32_t published_dac_epoch = 0u;
uint32_t published_records = 0u;
uint32_t last_phase_epoch = 0u;
uint32_t last_observation_sequence = 0u;
OtisPhasePreviewActiveSnapshot active_snapshot = {};

template <typename T>
T atomic_load_acquire(const T *value) {
  return __atomic_load_n(value, __ATOMIC_ACQUIRE);
}

template <typename T>
void atomic_store_release(T *destination, T value) {
  __atomic_store_n(destination, value, __ATOMIC_RELEASE);
}

template <typename T>
T atomic_load_seq_cst(const T *value) {
  return __atomic_load_n(value, __ATOMIC_SEQ_CST);
}

template <typename T>
void atomic_store_seq_cst(T *destination, T value) {
  __atomic_store_n(destination, value, __ATOMIC_SEQ_CST);
}

bool characterized_code(uint16_t code) {
  return code >= kMinimumCharacterizedCode &&
         code <= kMaximumCharacterizedCode;
}

void initialize_applied_code(uint16_t code, uint32_t dac_epoch) {
  // begin() has withdrawn initialized before reaching here, so Core 1 cannot
  // consume this state.  Reset the sequence for a fresh preview lifetime.
  atomic_store_release(&applied_code_generation, static_cast<uint32_t>(0));
  atomic_store_release(&published_applied_code,
                       static_cast<uint32_t>(code));
  atomic_store_release(&published_dac_epoch, dac_epoch);
}

void snapshot_applied_code(uint16_t *code, uint32_t *dac_epoch) {
  // Sequential consistency makes the generation checks bracket the code/epoch
  // reads in one cross-core order.  A boundary therefore observes either the
  // complete old pair or the complete new pair, never a mixed pair.
  for (;;) {
    const uint32_t before = atomic_load_seq_cst(&applied_code_generation);
    if ((before & 1u) != 0u) continue;
    const uint32_t published_code =
        atomic_load_seq_cst(&published_applied_code);
    const uint32_t published_epoch =
        atomic_load_seq_cst(&published_dac_epoch);
    const uint32_t after = atomic_load_seq_cst(&applied_code_generation);
    if (before == after && (after & 1u) == 0u) {
      *code = static_cast<uint16_t>(published_code);
      *dac_epoch = published_epoch;
      return;
    }
  }
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

bool otis_phase_preview_live_begin(void) {
  // Core 0 publishes status while Core 1 owns the preview engine.  Withdraw
  // readiness before resetting the service and publish it only after the
  // complete unbound state has been initialized.
  atomic_store_release(&initialized, false);
  atomic_store_release(&applied_code_bound, false);
  engine = {};
  have_reference_timestamp = false;
  reset_pending = true;
  previous_reference_timestamp = 0u;
  unwrapped_reference_timestamp = 0u;
  initialize_applied_code(0u, 0u);
  atomic_store_release(&published_records, static_cast<uint32_t>(0));
  atomic_store_release(&last_phase_epoch, static_cast<uint32_t>(0));
  atomic_store_release(&last_observation_sequence, static_cast<uint32_t>(0));
  active_snapshot = {};
  atomic_store_release(&initialized, true);
  return true;
}

bool otis_phase_preview_live_update_applied_code(
    uint16_t confirmed_applied_code, uint32_t dac_epoch) {
  if (!atomic_load_acquire(&initialized) ||
      dac_epoch == 0u || !characterized_code(confirmed_applied_code))
    return false;

  if (!atomic_load_acquire(&applied_code_bound)) {
    engine = {};
    if (!otis_selected_phase_frequency_preview_init(&engine))
      return false;
    initialize_applied_code(confirmed_applied_code, dac_epoch);
    atomic_store_release(&applied_code_bound, true);
    return true;
  }

  // The timing owner is the only writer, so the stable even generation gives
  // it the last pair without a compare/exchange or secondary ownership.
  const uint32_t generation =
      atomic_load_seq_cst(&applied_code_generation);
  if ((generation & 1u) != 0u) return false;
  const uint32_t current_epoch = atomic_load_seq_cst(&published_dac_epoch);
  const uint16_t current_code = static_cast<uint16_t>(
      atomic_load_seq_cst(&published_applied_code));
  if (dac_epoch < current_epoch ||
      (dac_epoch == current_epoch && confirmed_applied_code != current_code))
    return false;
  if (dac_epoch == current_epoch) return true;

  atomic_store_seq_cst(&applied_code_generation, generation + 1u);
  atomic_store_seq_cst(&published_applied_code,
                       static_cast<uint32_t>(confirmed_applied_code));
  atomic_store_seq_cst(&published_dac_epoch, dac_epoch);
  atomic_store_seq_cst(&applied_code_generation, generation + 2u);
  return true;
}

void otis_phase_preview_live_on_boundary(
    const OtisPpsCountBoundaryObservation *observation,
    uint32_t snapshot_status, uint32_t counted_edges,
    bool counted_edges_available, bool reference_qualified,
    bool phase_step_detected) {
  if (!atomic_load_acquire(&initialized) ||
      !atomic_load_acquire(&applied_code_bound) || observation == nullptr ||
      otis_dual_core_fail_static())
    return;
  uint16_t actual_applied_code = 0u;
  uint32_t dac_epoch = 0u;
  snapshot_applied_code(&actual_applied_code, &dac_epoch);
  const uint64_t unwrapped_ticks =
      unwrap_reference_timestamp(observation->pps_timestamp_ticks);
  const OtisSelectedPhaseFrequencyPreviewInput input = {
      observation->session,
      observation->sequence,
      observation->cumulative_down_counter,
      observation->reference_sequence,
      observation->pps_timestamp_ticks,
      unwrapped_ticks,
      snapshot_status,
      counted_edges,
      dac_epoch,
      counted_edges_available,
      reference_qualified,
      reset_pending,
  };
  reset_pending = false;
  otis_dual_core_note_timing_progress(OtisTimingProgressPhase::PhasePreview,
                                      unwrapped_ticks);
  OtisSelectedPhaseFrequencyPreviewOutput output = {};
  if (!otis_selected_phase_frequency_preview_process(&engine, &input, &output)) {
    otis_dual_core_latch_fault(OtisPartitionFault::PhasePreviewFault);
    return;
  }
  OtisPhasePreviewRecordMessage message = {};
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
  message.frequency_error_hz = output.frequency_error_hz;
  message.frequency_estimate_age_s =
      output.frequency_available
          ? static_cast<double>(output.frequency_estimate_age_ticks) /
                static_cast<double>(kReferenceTicksPerSecond)
          : 0.0;
  message.phase_accepted = output.phase_accepted;
  message.interval_available = output.interval_available;
  message.frequency_available = output.frequency_available;
  message.frequency_observation_event = output.frequency_observation_event;
  copy_text(message.phase_qualification_state,
            otis_reference_relative_phase_state_name(output.phase_state));
  copy_text(message.phase_reason, output.phase_reason);
  if (!otis_dual_core_publish_phase_preview(&message)) {
    active_snapshot = {};
    otis_dual_core_latch_fault(OtisPartitionFault::PhasePreviewFault);
    return;
  }
  active_snapshot.available = true;
  active_snapshot.recorder_published = true;
  active_snapshot.phase_continuous =
      output.phase_state == OtisReferenceRelativePhaseState::Qualified;
  active_snapshot.phase_current = output.phase_accepted;
  active_snapshot.phase_step_detected = phase_step_detected;
  active_snapshot.capture_session = output.capture_session;
  active_snapshot.phase_epoch = output.phase_epoch;
  active_snapshot.observation_sequence = output.observation_sequence;
  active_snapshot.relative_phase_cycles = output.relative_phase_cycles;
  active_snapshot.dac_epoch = output.dac_epoch;
  active_snapshot.applied_code = actual_applied_code;
  atomic_store_release(&last_phase_epoch, output.phase_epoch);
  atomic_store_release(&last_observation_sequence,
                       output.observation_sequence);
  __atomic_add_fetch(&published_records, 1u, __ATOMIC_RELEASE);
}

void otis_phase_preview_live_note_reset(void) {
  reset_pending = true;
  have_reference_timestamp = false;
  active_snapshot = {};
}

void otis_phase_preview_live_get_status(OtisPhasePreviewLiveStatus *status) {
  if (status == nullptr) return;
  const bool ready = atomic_load_acquire(&initialized);
  const bool code_bound = atomic_load_acquire(&applied_code_bound);
  *status = {};
  status->initialized = ready;
  status->applied_code_bound = ready && code_bound;
  if (status->applied_code_bound) {
    snapshot_applied_code(&status->applied_code, &status->dac_epoch);
  }
  status->published_records = atomic_load_acquire(&published_records);
  status->last_phase_epoch = atomic_load_acquire(&last_phase_epoch);
  status->last_observation_sequence =
      atomic_load_acquire(&last_observation_sequence);
}

bool otis_phase_preview_live_get_active_snapshot(
    OtisPhasePreviewActiveSnapshot *snapshot) {
  if (snapshot == nullptr) return false;
  *snapshot = {};
  if (!atomic_load_acquire(&initialized) ||
      !atomic_load_acquire(&applied_code_bound) || !active_snapshot.available)
    return false;
  *snapshot = active_snapshot;
  return true;
}
