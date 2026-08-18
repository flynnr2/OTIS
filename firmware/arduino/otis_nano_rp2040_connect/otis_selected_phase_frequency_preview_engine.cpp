#include "otis_selected_phase_frequency_preview_engine.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

#include "otis_build_profile_config.h"

namespace {

constexpr uint64_t kReferenceTicksPerSecond = 16000000ull;
constexpr uint64_t kReferenceTimestampModulus =
    kReferenceTicksPerSecond * (1ull << 32) / 1000000ull;
constexpr uint64_t kMinimumReferenceTicks = 12800000ull;
constexpr uint64_t kMaximumReferenceTicks = 19200000ull;
constexpr uint64_t kCounterModulus = 1ull << 32;
constexpr int64_t kNominalEdges = 10000000ll;
constexpr double kGainHzPerCode = 0.00017008467693813145;
constexpr double kIntegratorGain = 2884.5027706464516;
constexpr double kPullInS = 21600.0;
constexpr double kPhaseBiasCapHz = 1.0 / 600.0;
constexpr double kHistoricalV2ThresholdHz = 0.006249995628992717;
constexpr double kFrequencySupportS = 600.0;
constexpr double kDecisionCadenceS = 1800.0;
constexpr double kRequalificationS = 1500.0;
constexpr double kPhaseStepHoldS = 600.0;
constexpr int32_t kMaximumStep = 21;
constexpr uint16_t kMinimumCode = 0xA800u;
constexpr uint16_t kMaximumCode = 0xAB00u;
constexpr uint16_t kMaximumCorrections = 32u;
constexpr uint16_t kMaximumPathCodes = 672u;
#if OTIS_SELECTED_HYBRID_EXTERNAL_DAC_EPOCH_RESEED
constexpr bool kExternalDacEpochCandidateReseed = true;
#else
constexpr bool kExternalDacEpochCandidateReseed = false;
#endif

double clamp_double(double value, double lower, double upper) {
  return value < lower ? lower : (value > upper ? upper : value);
}

int32_t round_half_away(double value) {
  return value >= 0.0 ? static_cast<int32_t>(floor(value + 0.5))
                      : static_cast<int32_t>(ceil(value - 0.5));
}

const char *band_name(bool inside) { return inside ? "INSIDE" : "OUTSIDE"; }

void reset_frequency(OtisSelectedPhaseFrequencyPreviewEngine *engine) {
  engine->frequency_point_next = 0u;
  engine->frequency_point_count = 0u;
}

void reset_band_and_support(OtisSelectedPhaseFrequencyPreviewEngine *engine) {
  engine->band_inside = false;
  engine->integrator_codes = 0.0;
  engine->last_frequency_event_available = false;
  engine->last_frequency_event_s = 0.0;
  engine->last_observed_frequency_available = false;
  engine->last_observed_frequency_hz = 0.0;
  engine->last_decision_available = false;
  engine->last_decision_s = 0.0;
  engine->last_correction_available = false;
  engine->last_correction_s = 0.0;
}

void reset_candidate_lifetime(OtisSelectedPhaseFrequencyPreviewEngine *engine,
                              uint16_t actual_applied_code) {
  engine->start_code = actual_applied_code;
  engine->correction_count = 0u;
  engine->path_codes = 0u;
  memset(engine->directions, 0, sizeof(engine->directions));
  engine->direction_count = 0u;
  engine->terminal_reason = nullptr;
}

void add_frequency_point(OtisSelectedPhaseFrequencyPreviewEngine *engine,
                         uint32_t phase_epoch, uint32_t dac_epoch,
                         int64_t phase, bool *available, double *frequency) {
  *available = false;
  *frequency = 0.0;
  if (engine->frequency_point_count == 0u ||
      engine->frequency_phase_epoch != phase_epoch ||
      engine->frequency_dac_epoch != dac_epoch) {
    reset_frequency(engine);
    engine->frequency_phase_epoch = phase_epoch;
    engine->frequency_dac_epoch = dac_epoch;
  }
  const uint16_t capacity = OTIS_PHASE_FREQUENCY_PREVIEW_SUPPORT_INTERVALS + 1u;
  if (engine->frequency_point_count < capacity) {
    engine->frequency_phase_points[engine->frequency_point_next] = phase;
    engine->frequency_point_next =
        static_cast<uint16_t>((engine->frequency_point_next + 1u) % capacity);
    engine->frequency_point_count++;
  } else {
    engine->frequency_phase_points[engine->frequency_point_next] = phase;
    engine->frequency_point_next =
        static_cast<uint16_t>((engine->frequency_point_next + 1u) % capacity);
  }
  if (engine->frequency_point_count == capacity) {
    const int64_t first =
        engine->frequency_phase_points[engine->frequency_point_next];
    *frequency = static_cast<double>(phase - first) /
                 OTIS_PHASE_FREQUENCY_PREVIEW_SUPPORT_INTERVALS;
    *available = true;
  }
}

const char *preview_state(const OtisSelectedPhaseFrequencyPreviewEngine *engine,
                          bool frequency_available, double timestamp_s) {
  if (engine->terminal_reason != nullptr) return "FAULT_PREVIEW";
  if (engine->phase_hold_available && timestamp_s < engine->phase_hold_until_s)
    return "PHASE_STEP_HOLD_PREVIEW";
  if (!frequency_available)
    return engine->had_reference_loss ? "RECOVER_PREVIEW"
                                      : "RELATIVE_PHASE_ACQUIRE";
  return engine->band_inside ? "HYBRID_TRACKING_PREVIEW"
                             : "FREQUENCY_ACQUIRED_PREVIEW";
}

uint16_t alternating_count(const OtisSelectedPhaseFrequencyPreviewEngine *engine) {
  uint16_t count = 0u;
  for (uint8_t i = 1u; i < engine->direction_count; ++i)
    count += engine->directions[i - 1u] != engine->directions[i];
  return count;
}

const char *dither_reason(const OtisSelectedPhaseFrequencyPreviewEngine *engine,
                          int32_t delta) {
  const int8_t direction = delta > 0 ? 1 : -1;
  if (engine->direction_count >= 3u) {
    const uint8_t start = static_cast<uint8_t>(engine->direction_count - 3u);
    int reversals = 0;
    int8_t previous = engine->directions[start];
    for (uint8_t i = static_cast<uint8_t>(start + 1u);
         i < engine->direction_count; ++i) {
      reversals += previous != engine->directions[i];
      previous = engine->directions[i];
    }
    reversals += previous != direction;
    if (reversals >= 3) return "prospective_repeated_alternation";
  }
  const uint16_t path =
      static_cast<uint16_t>(engine->path_codes + (delta < 0 ? -delta : delta));
  const int32_t net = static_cast<int32_t>(engine->shadow_code) + delta -
                      static_cast<int32_t>(engine->start_code);
  if (path >= 168u && abs(net) <= 0.25 * path)
    return "prospective_low_net_excess_path";
  return nullptr;
}

void base_output(const OtisSelectedPhaseFrequencyPreviewEngine *engine,
                 OtisSelectedPhaseFrequencyPreviewOutput *output, uint32_t dac_epoch,
                 OtisReferenceRelativePhaseState phase_state, const char *phase_reason,
                 bool phase_accepted, bool interval_available,
                 uint32_t interval_edges, int64_t edge_error,
                 uint32_t capture_session, uint32_t opening_snapshot_sequence,
                 uint32_t closing_snapshot_sequence,
                 uint32_t opening_reference_sequence,
                 uint32_t closing_reference_sequence) {
  *output = {};
  output->phase_epoch = engine->phase_epoch;
  output->observation_sequence = engine->observation_sequence;
  output->capture_session = capture_session;
  output->opening_snapshot_sequence = opening_snapshot_sequence;
  output->closing_snapshot_sequence = closing_snapshot_sequence;
  output->opening_reference_sequence = opening_reference_sequence;
  output->closing_reference_sequence = closing_reference_sequence;
  output->dac_epoch = dac_epoch;
  output->interval_edges = interval_edges;
  output->edge_error_cycles = edge_error;
  output->relative_phase_cycles = engine->cumulative_phase;
  output->relative_phase_time_ns = engine->cumulative_phase * 100ll;
  output->phase_state = phase_state;
  output->phase_reason = phase_reason;
  output->phase_accepted = phase_accepted;
  output->interval_available = interval_available;
}

void complete_preview_output(const OtisSelectedPhaseFrequencyPreviewEngine *engine,
                             OtisSelectedPhaseFrequencyPreviewOutput *output,
                             uint16_t before_code, bool before_band,
                             double timestamp_s, bool frequency_available,
                             double observed_frequency,
                             bool modeled_frequency_available,
                             double modeled_frequency, double phase_bias,
                             const char *reason) {
  output->frequency_available = modeled_frequency_available;
  output->observed_frequency_error_hz = observed_frequency;
  output->modeled_relative_phase_cycles = engine->modeled_phase;
  output->modeled_frequency_error_hz = modeled_frequency;
  output->frequency_term_hz =
      modeled_frequency_available ? -modeled_frequency : 0.0;
  output->phase_bias_hz = phase_bias;
  output->combined_desired_frequency_change_hz =
      modeled_frequency_available ? -modeled_frequency + phase_bias : 0.0;
  output->actual_applied_code = engine->actual_code;
  output->shadow_code_before = before_code;
  output->shadow_code_after = engine->shadow_code;
  output->band_state_before = band_name(before_band);
  output->band_state_after = band_name(engine->band_inside);
  output->preview_state =
      preview_state(engine, frequency_available, timestamp_s);
  output->decision_reason = reason;
  output->correction_count = engine->correction_count;
  output->cumulative_movement_codes = engine->path_codes;
  output->alternating_correction_count = alternating_count(engine);
  output->modeled_not_observed_after_divergence =
      engine->shadow_code != engine->actual_code;
}

void invalidate_preview(OtisSelectedPhaseFrequencyPreviewEngine *engine,
                        OtisSelectedPhaseFrequencyPreviewOutput *output,
                        const OtisSelectedPhaseFrequencyPreviewInput *input,
                        const char *reason) {
  const uint16_t before_code = engine->shadow_code;
  const bool before_band = engine->band_inside;
  const bool new_dac_epoch = !engine->hybrid_dac_epoch_available ||
                             engine->hybrid_dac_epoch != input->dac_epoch;
  if (new_dac_epoch && kExternalDacEpochCandidateReseed)
    reset_candidate_lifetime(engine, input->actual_applied_code);
  engine->actual_code = input->actual_applied_code;
  engine->shadow_code = input->actual_applied_code;
  engine->hybrid_dac_epoch = input->dac_epoch;
  engine->hybrid_dac_epoch_available = true;
  engine->hybrid_phase_epoch_available = false;
  engine->previous_preview_time_available = false;
  engine->phase_hold_available = false;
  engine->had_reference_loss = true;
  reset_band_and_support(engine);
  complete_preview_output(engine, output, before_code, before_band,
                          input->timestamp_s, false, 0.0, false, 0.0, 0.0,
                          reason);
  output->preview_state = "REFERENCE_LOST_PREVIEW";
}

}  // namespace

bool otis_selected_phase_frequency_preview_init(OtisSelectedPhaseFrequencyPreviewEngine *engine,
                                      uint16_t start_code) {
  if (engine == nullptr || start_code < kMinimumCode || start_code > kMaximumCode)
    return false;
  memset(engine, 0, sizeof(*engine));
  engine->pending_phase_reason = "initial_epoch";
  engine->actual_code = start_code;
  engine->shadow_code = start_code;
  engine->start_code = start_code;
  return true;
}

bool otis_selected_phase_frequency_preview_process(
    OtisSelectedPhaseFrequencyPreviewEngine *engine,
    const OtisSelectedPhaseFrequencyPreviewInput *input,
    OtisSelectedPhaseFrequencyPreviewOutput *output) {
  if (engine == nullptr || input == nullptr || output == nullptr ||
      input->actual_applied_code < kMinimumCode ||
      input->actual_applied_code > kMaximumCode || !isfinite(input->timestamp_s))
    return false;

  OtisReferenceRelativePhaseState phase_state = OtisReferenceRelativePhaseState::Invalid;
  const char *phase_reason = nullptr;
  bool accepted = false;
  bool interval_available = false;
  uint32_t interval_edges = 0u;
  int64_t edge_error = 0ll;
  const bool had_previous_snapshot =
      engine->have_previous_snapshot && !input->reset;
  const uint32_t previous_snapshot_sequence =
      engine->previous_snapshot_sequence;
  const uint32_t previous_reference_sequence =
      engine->previous_reference_sequence;

  if (input->reset) {
    engine->have_previous_snapshot = false;
    engine->pending_phase_reason = "reset";
  }

  const bool structurally_invalid = input->snapshot_status != 0u ||
                                    !input->reference_qualified;
  if (structurally_invalid) {
    phase_state = OtisReferenceRelativePhaseState::Invalid;
    phase_reason = input->snapshot_status != 0u ? "snapshot_status_invalid"
                                                : "reference_invalid_or_stale";
    engine->have_previous_snapshot = false;
    engine->pending_phase_reason = phase_reason;
    reset_frequency(engine);
  } else if (!engine->have_previous_snapshot) {
    engine->phase_epoch++;
    engine->observation_sequence = 0u;
    engine->cumulative_phase = 0ll;
    phase_state = OtisReferenceRelativePhaseState::EpochOpen;
    phase_reason = engine->pending_phase_reason;
    engine->pending_phase_reason = nullptr;
  } else if (input->capture_session != engine->previous_capture_session) {
    engine->phase_epoch++;
    engine->observation_sequence = 0u;
    engine->cumulative_phase = 0ll;
    phase_state = OtisReferenceRelativePhaseState::EpochOpen;
    phase_reason = "capture_session_change";
  } else if (input->snapshot_sequence <= engine->previous_snapshot_sequence) {
    phase_state = OtisReferenceRelativePhaseState::Invalid;
    phase_reason = "snapshot_reordered_or_duplicate";
    engine->have_previous_snapshot = false;
    engine->pending_phase_reason = phase_reason;
    reset_frequency(engine);
  } else if (input->reference_sequence <= engine->previous_reference_sequence) {
    phase_state = OtisReferenceRelativePhaseState::Invalid;
    phase_reason = "reference_reordered_or_duplicate";
    engine->have_previous_snapshot = false;
    engine->pending_phase_reason = phase_reason;
    reset_frequency(engine);
  } else if (input->snapshot_sequence != engine->previous_snapshot_sequence + 1u ||
             input->reference_sequence != engine->previous_reference_sequence + 1u) {
    engine->phase_epoch++;
    engine->observation_sequence = 0u;
    engine->cumulative_phase = 0ll;
    phase_state = OtisReferenceRelativePhaseState::EpochOpen;
    phase_reason = "snapshot_or_reference_sequence_gap";
  } else {
    uint64_t reference_delta = 0u;
    if (input->reference_timestamp_ticks > engine->previous_reference_ticks) {
      reference_delta =
          input->reference_timestamp_ticks - engine->previous_reference_ticks;
    } else {
      reference_delta =
          (input->reference_timestamp_ticks + kReferenceTimestampModulus -
           engine->previous_reference_ticks) %
          kReferenceTimestampModulus;
    }
    if (reference_delta == 0u) {
      phase_state = OtisReferenceRelativePhaseState::Invalid;
      phase_reason = "reference_timestamp_reordered";
      engine->have_previous_snapshot = false;
      engine->pending_phase_reason = phase_reason;
      reset_frequency(engine);
    } else if (reference_delta > kMaximumReferenceTicks) {
      engine->phase_epoch++;
      engine->observation_sequence = 0u;
      engine->cumulative_phase = 0ll;
      phase_state = OtisReferenceRelativePhaseState::EpochOpen;
      phase_reason = "reference_pps_long_interval";
    } else if (reference_delta < kMinimumReferenceTicks) {
      engine->phase_epoch++;
      engine->observation_sequence = 0u;
      engine->cumulative_phase = 0ll;
      phase_state = OtisReferenceRelativePhaseState::EpochOpen;
      phase_reason = "reference_pps_short_interval";
    } else {
      interval_edges = static_cast<uint32_t>(
          (static_cast<uint64_t>(engine->previous_counter) + kCounterModulus -
           input->cumulative_down_counter) %
          kCounterModulus);
      if (!input->counted_edges_available || input->counted_edges != interval_edges) {
        engine->phase_epoch++;
        engine->observation_sequence = 0u;
        engine->cumulative_phase = 0ll;
        phase_state = OtisReferenceRelativePhaseState::EpochOpen;
        phase_reason = "snapshot_count_association_mismatch";
      } else {
        edge_error = static_cast<int64_t>(interval_edges) - kNominalEdges;
        engine->cumulative_phase += edge_error;
        engine->observation_sequence++;
        phase_state = OtisReferenceRelativePhaseState::Qualified;
        accepted = true;
        interval_available = true;
      }
    }
  }

  if (phase_state != OtisReferenceRelativePhaseState::Invalid) {
    engine->have_previous_snapshot = true;
    engine->previous_capture_session = input->capture_session;
    engine->previous_snapshot_sequence = input->snapshot_sequence;
    engine->previous_counter = input->cumulative_down_counter;
    engine->previous_reference_sequence = input->reference_sequence;
    engine->previous_reference_ticks = input->reference_timestamp_ticks;
  }

  const bool opens_at_current =
      phase_state == OtisReferenceRelativePhaseState::EpochOpen || !had_previous_snapshot;
  base_output(
      engine, output, input->dac_epoch, phase_state, phase_reason, accepted,
      interval_available, interval_edges, edge_error, input->capture_session,
      opens_at_current ? input->snapshot_sequence : previous_snapshot_sequence,
      input->snapshot_sequence,
      opens_at_current ? input->reference_sequence
                       : previous_reference_sequence,
      input->reference_sequence);
  if (phase_state == OtisReferenceRelativePhaseState::Invalid) {
    invalidate_preview(engine, output, input,
                       phase_reason != nullptr ? phase_reason
                                               : "invalid_phase_input");
    return true;
  }

  bool raw_frequency_available = false;
  double raw_frequency = 0.0;
  add_frequency_point(engine, engine->phase_epoch, input->dac_epoch,
                      engine->cumulative_phase, &raw_frequency_available,
                      &raw_frequency);
  output->raw_frequency_available = raw_frequency_available;
  output->raw_frequency_error_hz = raw_frequency;

  const uint16_t before_code = engine->shadow_code;
  const bool before_band = engine->band_inside;
  const bool new_phase_epoch = !engine->hybrid_phase_epoch_available ||
                               engine->hybrid_phase_epoch != engine->phase_epoch;
  const bool new_dac_epoch = !engine->hybrid_dac_epoch_available ||
                             engine->hybrid_dac_epoch != input->dac_epoch;
  if (new_phase_epoch || new_dac_epoch) {
    if (new_dac_epoch && kExternalDacEpochCandidateReseed)
      reset_candidate_lifetime(engine, input->actual_applied_code);
    engine->hybrid_phase_epoch_available = true;
    engine->hybrid_phase_epoch = engine->phase_epoch;
    engine->hybrid_dac_epoch_available = true;
    engine->hybrid_dac_epoch = input->dac_epoch;
    engine->actual_code = input->actual_applied_code;
    engine->shadow_code = input->actual_applied_code;
    engine->modeled_phase = static_cast<double>(engine->cumulative_phase);
    engine->previous_raw_phase = engine->cumulative_phase;
    engine->previous_preview_time_available = true;
    engine->previous_preview_time_s = input->timestamp_s;
    engine->phase_hold_available = false;
    reset_band_and_support(engine);
    complete_preview_output(
        engine, output, before_code, before_band, input->timestamp_s, false, 0.0,
        false, 0.0, 0.0,
        new_phase_epoch
            ? "phase_epoch_reseed"
            : (kExternalDacEpochCandidateReseed
                   ? "dac_epoch_candidate_reseed"
                   : "dac_epoch_bumpless_reseed"));
    return true;
  }

  if (!engine->previous_preview_time_available ||
      input->timestamp_s <= engine->previous_preview_time_s) {
    engine->terminal_reason = "nonmonotonic_preview_time";
    complete_preview_output(engine, output, before_code, before_band,
                            input->timestamp_s, false, 0.0, false, 0.0, 0.0,
                            engine->terminal_reason);
    return true;
  }

  const double interval_s = input->timestamp_s - engine->previous_preview_time_s;
  const int64_t raw_increment =
      engine->cumulative_phase - engine->previous_raw_phase;
  engine->modeled_phase +=
      static_cast<double>(raw_increment) +
      kGainHzPerCode * (static_cast<int32_t>(engine->shadow_code) -
                        static_cast<int32_t>(input->actual_applied_code)) *
          interval_s;
  engine->actual_code = input->actual_applied_code;
  engine->previous_raw_phase = engine->cumulative_phase;
  engine->previous_preview_time_s = input->timestamp_s;

  if (input->phase_step_detected) {
    engine->phase_hold_available = true;
    engine->phase_hold_until_s = input->timestamp_s + kPhaseStepHoldS;
    reset_band_and_support(engine);
    complete_preview_output(engine, output, before_code, before_band,
                            input->timestamp_s, false, 0.0, false, 0.0, 0.0,
                            "phase_step_hold_started");
    return true;
  }

  const bool frequency_event =
      raw_frequency_available &&
      (!engine->phase_hold_available ||
       input->timestamp_s >= engine->phase_hold_until_s) &&
      (!engine->last_frequency_event_available ||
       input->timestamp_s - engine->last_frequency_event_s >=
           kFrequencySupportS);
  if (!frequency_event) {
    const bool modeled_available = engine->last_observed_frequency_available;
    const double modeled =
        modeled_available
            ? engine->last_observed_frequency_hz +
                  kGainHzPerCode *
                      (static_cast<int32_t>(engine->shadow_code) -
                       static_cast<int32_t>(engine->actual_code))
            : 0.0;
    const double phase_bias = modeled_available && engine->band_inside
                                  ? clamp_double(-engine->modeled_phase / kPullInS,
                                                 -kPhaseBiasCapHz,
                                                 kPhaseBiasCapHz)
                                  : 0.0;
    complete_preview_output(
        engine, output, before_code, before_band, input->timestamp_s,
        modeled_available, engine->last_observed_frequency_hz,
        modeled_available, modeled, phase_bias,
        "frequency_support_or_decision_cadence_hold");
    return true;
  }

  engine->last_frequency_event_available = true;
  engine->last_frequency_event_s = input->timestamp_s;
  engine->last_observed_frequency_available = true;
  engine->last_observed_frequency_hz = raw_frequency;
  const double modeled_frequency =
      raw_frequency +
      kGainHzPerCode * (static_cast<int32_t>(engine->shadow_code) -
                        static_cast<int32_t>(engine->actual_code));
  engine->band_inside = fabs(modeled_frequency) <= kHistoricalV2ThresholdHz;
  const double phase_bias =
      engine->band_inside
          ? clamp_double(-engine->modeled_phase / kPullInS, -kPhaseBiasCapHz,
                         kPhaseBiasCapHz)
          : 0.0;
  const double combined = -modeled_frequency + phase_bias;
  const char *reason = nullptr;

  if (engine->terminal_reason != nullptr) {
    reason = engine->terminal_reason;
  } else if (engine->last_correction_available &&
             input->timestamp_s - engine->last_correction_s <
                 kRequalificationS) {
    reason = "counterfactual_settling_and_fresh_support";
  } else if (engine->last_decision_available &&
             input->timestamp_s - engine->last_decision_s < kDecisionCadenceS) {
    reason = "counterfactual_decision_cadence_hold";
  } else {
    engine->last_decision_available = true;
    engine->last_decision_s = input->timestamp_s;
    output->counterfactual_decision = true;
    output->raw_delta_available = true;
    if (engine->band_inside && fabs(phase_bias) < 1e-15) {
      engine->integrator_codes = 0.0;
      output->raw_delta_codes = 0.0;
      output->limited_delta_codes = 0;
      reason = "inside_band_zero_phase_hold";
    } else {
      const double raw_delta = engine->integrator_codes + kIntegratorGain * combined;
      const double limited_float =
          clamp_double(raw_delta, -static_cast<double>(kMaximumStep),
                       static_cast<double>(kMaximumStep));
      output->raw_delta_codes = raw_delta;
      output->step_limited = fabs(raw_delta - limited_float) > 1e-12;
      const int32_t rounded = round_half_away(limited_float);
      const int32_t unclamped = static_cast<int32_t>(engine->shadow_code) + rounded;
      const int32_t proposed =
          unclamped < kMinimumCode
              ? kMinimumCode
              : (unclamped > kMaximumCode ? kMaximumCode : unclamped);
      output->range_clamped = proposed != unclamped;
      const int32_t delta = proposed - static_cast<int32_t>(engine->shadow_code);
      output->limited_delta_codes = delta;
      if (delta != 0 && engine->band_inside && fabs(phase_bias) >= 1e-15 &&
          delta * phase_bias < 0.0) {
        engine->integrator_codes = 0.0;
        output->limited_delta_codes = 0;
        reason = "phase_direction_coherence_hold";
      } else if (delta == 0) {
        engine->integrator_codes = 0.0;
        reason = "hard_range_or_zero_rounded_hold";
      } else if (engine->correction_count + 1u > kMaximumCorrections ||
                 engine->path_codes + static_cast<uint16_t>(abs(delta)) >
                     kMaximumPathCodes) {
        engine->terminal_reason = "counterfactual_budget_hold";
        engine->integrator_codes = 0.0;
        reason = engine->terminal_reason;
      } else {
        const char *dither = dither_reason(engine, delta);
        if (dither != nullptr) {
          engine->terminal_reason = dither;
          engine->integrator_codes = 0.0;
          reason = dither;
        } else {
          engine->shadow_code = static_cast<uint16_t>(proposed);
          engine->correction_count++;
          engine->path_codes = static_cast<uint16_t>(
              engine->path_codes + static_cast<uint16_t>(abs(delta)));
          if (engine->direction_count < OTIS_PHASE_FREQUENCY_PREVIEW_DIRECTION_HISTORY_CAPACITY)
            engine->directions[engine->direction_count++] = delta > 0 ? 1 : -1;
          engine->last_correction_available = true;
          engine->last_correction_s = input->timestamp_s;
          engine->integrator_codes = 0.0;
          output->counterfactual_correction = true;
          reason = "counterfactual_correction_modeled";
        }
      }
    }
  }

  output->frequency_observation_event = true;
  complete_preview_output(engine, output, before_code, before_band,
                          input->timestamp_s, true, raw_frequency, true,
                          modeled_frequency, phase_bias, reason);
  return true;
}

const char *otis_reference_relative_phase_state_name(OtisReferenceRelativePhaseState state) {
  switch (state) {
    case OtisReferenceRelativePhaseState::EpochOpen:
      return "epoch_open";
    case OtisReferenceRelativePhaseState::Qualified:
      return "qualified";
    case OtisReferenceRelativePhaseState::Invalid:
      return "invalid";
  }
  return "invalid";
}
