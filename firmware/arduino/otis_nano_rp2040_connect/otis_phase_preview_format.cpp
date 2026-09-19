#include "otis_phase_preview_format.h"

#include <stdio.h>
#include <string.h>

#include "otis_build_config.h"
#include "otis_decimal_format.h"

namespace {

constexpr char kPhaseEstimatorId[] = OTIS_BUILD_PHASE_ESTIMATOR_ID;
constexpr char kPhaseConfigurationSha256[] =
    OTIS_BUILD_PHASE_ESTIMATOR_SHA256;
constexpr char kSourceBackend[] = "pio_wait_cumulative_snapshot_fifo_irq_v2";
constexpr char kRawMethodId[] = OTIS_BUILD_PHASE_RAW_METHOD_ID;
constexpr char kLiveSourceIdentity[] = "live_stream_unsealed";

bool finish_format(int used, size_t output_size, size_t *length) {
  if (used <= 0 || static_cast<size_t>(used) >= output_size) return false;
  if (length != nullptr) *length = static_cast<size_t>(used);
  return true;
}

bool fixed(double value, char *output, size_t size) {
  return otis_format_fixed(value, 15u, output, size);
}

}  // namespace

const char *otis_phase_preview_rph_header(void) {
  return OTIS_CONTRACT_RELATIVE_PHASE_OBSERVATIONS_V2_HEADER "\r\n";
}

const char *otis_phase_preview_phe_header(void) {
  return OTIS_CONTRACT_PHASE_ESTIMATOR_OUTPUTS_V2_HEADER "\r\n";
}

bool otis_phase_preview_format_rph(const OtisPhasePreviewRecordMessage *message,
                           char *output, size_t output_size, size_t *length) {
  if (message == nullptr || output == nullptr || output_size == 0u)
    return false;
  char interval_edges[16] = "";
  char edge_error[24] = "";
  char accepted_span_ref[80] = "";
  if (message->interval_available) {
    snprintf(accepted_span_ref, sizeof(accepted_span_ref), "live:APS:%lu:%lu:%lu",
             static_cast<unsigned long>(message->capture_session),
             static_cast<unsigned long>(message->acceptance_epoch),
             static_cast<unsigned long>(message->accepted_boundary_ordinal));
    snprintf(interval_edges, sizeof(interval_edges), "%lu",
             static_cast<unsigned long>(message->interval_edges));
    snprintf(edge_error, sizeof(edge_error), "%lld",
             static_cast<long long>(message->edge_error_cycles));
  }
  const int used = snprintf(
      output, output_size,
      "RPH,2,%lu,%lu,%lu,%lu,%lu,%s,%lu,%lu,%lu,%lu,%lu,%s,%s,%s,%s,%s,%s,%lld,%lld,%s,0,%s,unavailable\r\n",
      static_cast<unsigned long>(message->phase_epoch),
      static_cast<unsigned long>(message->observation_sequence),
      static_cast<unsigned long>(message->capture_session),
      static_cast<unsigned long>(message->acceptance_epoch),
      static_cast<unsigned long>(message->accepted_boundary_ordinal),
      accepted_span_ref,
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
  if (message->frequency_available &&
      (!fixed(message->frequency_error_hz, frequency,
              sizeof(frequency)) ||
       !fixed(message->frequency_estimate_age_s, estimate_age,
              sizeof(estimate_age))))
    return false;
  const char *qualification =
      strcmp(message->phase_qualification_state, "invalid") == 0
          ? "invalid"
          : (message->frequency_available ? "qualified" : "initializing");
  const char *reason =
      strcmp(message->phase_qualification_state, "invalid") == 0
          ? message->phase_reason
          : (message->frequency_available
                 ? (message->frequency_observation_event
                        ? "frequency_estimate_fresh"
                        : "frequency_estimate_retained")
                 : "frequency_estimate_initializing");
  const int used = snprintf(
      output, output_size,
      "PHE,2,%lu,%lu,%lu,%lu,%lu,RPH:%lu:%lu,%lld,%lld,%lld,%s,%s,%s,%s,%s,unavailable,%s\r\n",
      static_cast<unsigned long>(message->phase_epoch),
      static_cast<unsigned long>(message->observation_sequence),
      static_cast<unsigned long>(message->capture_session),
      static_cast<unsigned long>(message->acceptance_epoch),
      static_cast<unsigned long>(message->accepted_boundary_ordinal),
      static_cast<unsigned long>(message->phase_epoch),
      static_cast<unsigned long>(message->observation_sequence),
      static_cast<long long>(message->relative_phase_cycles),
      static_cast<long long>(message->relative_phase_time_ns),
      static_cast<long long>(message->relative_phase_cycles), frequency,
      kPhaseEstimatorId, kPhaseConfigurationSha256, estimate_age,
      qualification, reason);
  return finish_format(used, output_size, length);
}
