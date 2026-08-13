#include "otis_phase_preview_format.h"

#include <stdio.h>
#include <string.h>

#include "otis_decimal_format.h"

namespace {

constexpr char kPhaseEstimatorId[] =
    "CX318_RELATIVE_PHASE_RAW_PLUS_SELECTED600_V1";
constexpr char kPhaseConfigurationSha256[] =
    "449c828d2affeff858eb91535e81da0bc9c44840369d741dc1f917a8d662acb4";
constexpr char kFrequencyEstimatorId[] =
    "cx317_selected_600s_nonoverlap_v1";
constexpr char kFrequencyConfigurationSha256[] =
    "5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c";
constexpr char kCandidateId[] = "p21600_cap1_v2";
constexpr char kHybridConfigurationSha256[] =
    "3f0fe4ae2806ab0c9669d8b29b0ce62af897df5e14a56ea273057904de619e76";
constexpr char kSourceBackend[] = "pio_wait_cumulative_snapshot_dma_v1";
constexpr char kRawMethodId[] = "CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1";
constexpr char kTimeDomain[] = "rp2040_timer0";
constexpr char kLiveSourceIdentity[] = "live_stream_unsealed";

bool finish_format(int used, size_t output_size, size_t *length) {
  if (used <= 0 || static_cast<size_t>(used) >= output_size) return false;
  if (length != nullptr) *length = static_cast<size_t>(used);
  return true;
}

bool fixed(double value, char *output, size_t size) {
  return otis_format_fixed(value, 15u, output, size);
}

const char *boolean_text(bool value) { return value ? "true" : "false"; }

}  // namespace

const char *otis_phase_preview_rph_header(void) {
  return "record_type,schema_version,phase_epoch,observation_sequence,capture_session,opening_snapshot_sequence,closing_snapshot_sequence,opening_reference_sequence,closing_reference_sequence,dac_epoch,source_backend,source_file_sha256,method_id,configuration_sha256,interval_edges,edge_error_cycles,relative_phase_cycles,relative_phase_time_ns,qualification_state,observation_age_s,discontinuity_reason,calibrated_uncertainty_status\r\n";
}

const char *otis_phase_preview_phe_header(void) {
  return "record_type,schema_version,phase_epoch,observation_sequence,source_relative_phase_observation,raw_relative_phase_cycles,raw_relative_phase_time_ns,filtered_relative_phase_cycles,estimated_frequency_error_hz,estimator_id,configuration_sha256,estimate_age_s,qualification_state,uncertainty_status,reason_codes\r\n";
}

const char *otis_phase_preview_hpr_header(void) {
  return "record_type,schema_version,preview_sequence,candidate_id,candidate_configuration_sha256,phase_estimator_id,phase_estimator_configuration_sha256,frequency_estimator_id,frequency_estimator_configuration_sha256,configuration_sha256,phase_epoch,observation_sequence,dac_epoch,decision_timestamp_ticks,time_domain,source_phase_estimate,source_frequency_estimate,raw_relative_phase_cycles,modeled_relative_phase_cycles,observed_frequency_error_hz,modeled_frequency_error_hz,frequency_term_hz,phase_bias_hz,combined_frequency_error_hz,actual_applied_code,shadow_code_before,shadow_code_after,band_state_before,band_state_after,preview_state,decision_reason,frequency_observation_event,counterfactual_decision,counterfactual_correction,raw_counterfactual_delta_codes,counterfactual_delta_codes,counterfactual_code,step_limited,range_clamped,correction_count,cumulative_movement_codes,alternating_correction_count,modeled_not_observed_after_divergence,uncertainty_status,actionable,actuation_authorized,authorization_consumed\r\n";
}

bool otis_phase_preview_format_rph(const OtisPhasePreviewRecordMessage *message,
                           char *output, size_t output_size, size_t *length) {
  if (message == nullptr || output == nullptr || output_size == 0u)
    return false;
  char interval_edges[16] = "";
  char edge_error[24] = "";
  if (message->interval_available) {
    snprintf(interval_edges, sizeof(interval_edges), "%lu",
             static_cast<unsigned long>(message->interval_edges));
    snprintf(edge_error, sizeof(edge_error), "%lld",
             static_cast<long long>(message->edge_error_cycles));
  }
  const int used = snprintf(
      output, output_size,
      "RPH,1,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%s,%s,%s,%s,%s,%s,%lld,%lld,%s,0,%s,unavailable\r\n",
      static_cast<unsigned long>(message->phase_epoch),
      static_cast<unsigned long>(message->observation_sequence),
      static_cast<unsigned long>(message->capture_session),
      static_cast<unsigned long>(message->opening_snapshot_sequence),
      static_cast<unsigned long>(message->closing_snapshot_sequence),
      static_cast<unsigned long>(message->opening_reference_sequence),
      static_cast<unsigned long>(message->closing_reference_sequence),
      static_cast<unsigned long>(message->dac_epoch), kSourceBackend,
      kLiveSourceIdentity, kRawMethodId, kPhaseConfigurationSha256,
      interval_edges, edge_error,
      static_cast<long long>(message->relative_phase_cycles),
      static_cast<long long>(message->relative_phase_time_ns),
      message->phase_qualification_state, message->phase_reason);
  return finish_format(used, output_size, length);
}

bool otis_phase_preview_format_phe(const OtisPhasePreviewRecordMessage *message,
                           char *output, size_t output_size, size_t *length) {
  if (message == nullptr || output == nullptr || output_size == 0u)
    return false;
  char frequency[40] = "";
  char estimate_age[40] = "";
  if (message->modeled_frequency_available &&
      (!fixed(message->observed_frequency_error_hz, frequency,
              sizeof(frequency)) ||
       !fixed(message->frequency_estimate_age_s, estimate_age,
              sizeof(estimate_age))))
    return false;
  const char *qualification =
      strcmp(message->phase_qualification_state, "invalid") == 0
          ? "invalid"
          : (message->modeled_frequency_available ? "qualified"
                                                  : "initializing");
  const char *reason =
      strcmp(message->phase_qualification_state, "invalid") == 0
          ? message->phase_reason
          : (message->modeled_frequency_available
                 ? (message->frequency_observation_event
                        ? "selected_600_interval_frequency_fresh"
                        : "selected_600_interval_frequency_retained")
                 : "selected_600_interval_frequency_initializing");
  const int used = snprintf(
      output, output_size,
      "PHE,1,%lu,%lu,RPH:%lu:%lu,%lld,%lld,%lld,%s,%s,%s,%s,%s,unavailable,%s\r\n",
      static_cast<unsigned long>(message->phase_epoch),
      static_cast<unsigned long>(message->observation_sequence),
      static_cast<unsigned long>(message->phase_epoch),
      static_cast<unsigned long>(message->observation_sequence),
      static_cast<long long>(message->relative_phase_cycles),
      static_cast<long long>(message->relative_phase_time_ns),
      static_cast<long long>(message->relative_phase_cycles), frequency,
      kPhaseEstimatorId, kPhaseConfigurationSha256, estimate_age,
      qualification, reason);
  return finish_format(used, output_size, length);
}

bool otis_phase_preview_format_hpr(const OtisPhasePreviewRecordMessage *message,
                           char *output, size_t output_size, size_t *length) {
  if (message == nullptr || output == nullptr || output_size == 0u)
    return false;
  char modeled_phase[48] = "";
  char observed_frequency[40] = "";
  char modeled_frequency[40] = "";
  char frequency_term[40] = "";
  char phase_bias[40] = "";
  char combined[40] = "";
  char raw_delta[48] = "";
  char limited_delta[24] = "";
  if (!fixed(message->modeled_relative_phase_cycles, modeled_phase,
             sizeof(modeled_phase)) ||
      !fixed(message->phase_bias_hz, phase_bias, sizeof(phase_bias)))
    return false;
  if (message->modeled_frequency_available &&
      (!fixed(message->observed_frequency_error_hz, observed_frequency,
              sizeof(observed_frequency)) ||
       !fixed(message->modeled_frequency_error_hz, modeled_frequency,
              sizeof(modeled_frequency)) ||
       !fixed(message->frequency_term_hz, frequency_term,
              sizeof(frequency_term)) ||
       !fixed(message->combined_frequency_error_hz, combined,
              sizeof(combined))))
    return false;
  if (message->counterfactual_decision) {
    if (!message->raw_counterfactual_delta_available ||
        !fixed(message->raw_counterfactual_delta_codes, raw_delta,
               sizeof(raw_delta)))
      return false;
    snprintf(limited_delta, sizeof(limited_delta), "%ld",
             static_cast<long>(message->counterfactual_delta_codes));
  }
  char phase_source[40] = "";
  char frequency_source[40] = "unavailable";
  snprintf(phase_source, sizeof(phase_source), "PHE:%lu:%lu",
           static_cast<unsigned long>(message->phase_epoch),
           static_cast<unsigned long>(message->observation_sequence));
  if (message->modeled_frequency_available)
    snprintf(frequency_source, sizeof(frequency_source), "PHE:%lu:%lu",
             static_cast<unsigned long>(message->phase_epoch),
             static_cast<unsigned long>(message->observation_sequence));
  const int used = snprintf(
      output, output_size,
      "HPR,1,%lu,%s,%s,%s,%s,%s,%s,%s,%lu,%lu,%lu,%llu,%s,%s,%s,%lld,%s,%s,%s,%s,%s,%s,%u,%u,%u,%s,%s,%s,%s,%s,%s,%s,%s,%s,%u,%s,%s,%u,%u,%u,%s,unavailable,false,false,false\r\n",
      static_cast<unsigned long>(message->preview_sequence), kCandidateId,
      kHybridConfigurationSha256, kPhaseEstimatorId,
      kPhaseConfigurationSha256, kFrequencyEstimatorId,
      kFrequencyConfigurationSha256, kHybridConfigurationSha256,
      static_cast<unsigned long>(message->phase_epoch),
      static_cast<unsigned long>(message->observation_sequence),
      static_cast<unsigned long>(message->dac_epoch),
      static_cast<unsigned long long>(message->decision_timestamp_ticks),
      kTimeDomain, phase_source, frequency_source,
      static_cast<long long>(message->relative_phase_cycles), modeled_phase,
      observed_frequency, modeled_frequency, frequency_term, phase_bias,
      combined, message->actual_applied_code, message->shadow_code_before,
      message->shadow_code_after, message->band_state_before,
      message->band_state_after, message->preview_state,
      message->decision_reason,
      boolean_text(message->frequency_observation_event),
      boolean_text(message->counterfactual_decision),
      boolean_text(message->counterfactual_correction), raw_delta,
      limited_delta, message->shadow_code_after,
      boolean_text(message->step_limited), boolean_text(message->range_clamped),
      message->correction_count, message->cumulative_movement_codes,
      message->alternating_correction_count,
      boolean_text(message->modeled_not_observed_after_divergence));
  return finish_format(used, output_size, length);
}
