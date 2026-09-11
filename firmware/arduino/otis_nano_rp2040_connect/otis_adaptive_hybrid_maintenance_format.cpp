#include "otis_adaptive_hybrid_maintenance_format.h"

#include <limits.h>
#include <string.h>

#include "otis_firmware_host_contract.generated.h"
#include "otis_adaptive_hybrid_regulation.h"

namespace {

constexpr char kPolicyId[] = "OTIS_ADAPTIVE_HYBRID_REGULATION_V1";
constexpr char kTimeDomain[] = "rp2040_monotonic_us64";
constexpr int64_t kMaximumDebtPicocodes = 500000000000LL;
constexpr uint32_t kMinimumCode = 0xA800u;
constexpr uint32_t kMaximumCode = 0xAB00u;

constexpr char kHeader[] =
    OTIS_CONTRACT_ACTIVE_HYBRID_MAINTENANCE_V2_HEADER "\r\n";

class BoundedWriter {
 public:
  BoundedWriter(char *output, size_t output_size)
      : output_(output), output_size_(output_size), used_(0u), ok_(true) {
    if (output_ == nullptr || output_size_ == 0u) {
      ok_ = false;
    } else {
      output_[0] = '\0';
    }
  }

  bool append(const char *text) {
    if (!ok_ || text == nullptr) return fail();
    const size_t length = strlen(text);
    if (length >= output_size_ - used_) return fail();
    memcpy(output_ + used_, text, length);
    used_ += length;
    output_[used_] = '\0';
    return true;
  }

  bool append_char(char value) {
    if (!ok_ || output_size_ - used_ <= 1u) return fail();
    output_[used_++] = value;
    output_[used_] = '\0';
    return true;
  }

  bool append_unsigned(uint64_t value) {
    char reversed[20] = {};
    size_t count = 0u;
    do {
      reversed[count++] = static_cast<char>('0' + value % 10u);
      value /= 10u;
    } while (value != 0u);
    while (count != 0u) {
      if (!append_char(reversed[--count])) return false;
    }
    return true;
  }

  bool append_signed64(int64_t value) {
    const bool negative = value < 0;
    const uint64_t magnitude =
        negative ? static_cast<uint64_t>(0) - static_cast<uint64_t>(value)
                 : static_cast<uint64_t>(value);
    return (!negative || append_char('-')) && append_unsigned(magnitude);
  }

  bool append_wide(OtisAdaptiveHybridWide value) {
    char decimal[OTIS_ADAPTIVE_HYBRID_WIDE_DECIMAL_CAPACITY] = {};
    if (!otis_adaptive_hybrid_wide_format_decimal(value, decimal, sizeof(decimal)))
      return fail();
    return append(decimal);
  }

  int finish() {
    if (!ok_ || used_ > static_cast<size_t>(INT_MAX)) {
      if (output_ != nullptr && output_size_ != 0u) output_[0] = '\0';
      return -1;
    }
    return static_cast<int>(used_);
  }

 private:
  bool fail() {
    ok_ = false;
    return false;
  }

  char *output_;
  size_t output_size_;
  size_t used_;
  bool ok_;
};

const char *event_name(OtisAdaptiveHybridMaintenanceEvent value) {
  switch (value) {
    case OtisAdaptiveHybridMaintenanceEvent::PolicyActivation:
      return "policy_activation";
    case OtisAdaptiveHybridMaintenanceEvent::Decision:
      return "decision";
    case OtisAdaptiveHybridMaintenanceEvent::RequestRejectedOrExpired:
      return "request_rejected_or_expired";
    case OtisAdaptiveHybridMaintenanceEvent::ApplicationFirstConsumer:
      return "application_first_consumer";
    case OtisAdaptiveHybridMaintenanceEvent::ResponseComplete:
      return "response_complete";
    case OtisAdaptiveHybridMaintenanceEvent::GnssMetadataHoldEnter:
      return "gnss_metadata_hold_enter";
    case OtisAdaptiveHybridMaintenanceEvent::GnssMetadataRequalified:
      return "gnss_metadata_requalified";
    case OtisAdaptiveHybridMaintenanceEvent::FailStatic:
      return "fail_static";
  }
  return nullptr;
}

const char *state_name(OtisAdaptiveHybridMaintenanceState value) {
  switch (value) {
    case OtisAdaptiveHybridMaintenanceState::PolicyInactive:
      return "POLICY_INACTIVE";
    case OtisAdaptiveHybridMaintenanceState::Ready:
      return "READY";
    case OtisAdaptiveHybridMaintenanceState::PersistenceHold:
      return "PERSISTENCE_HOLD";
    case OtisAdaptiveHybridMaintenanceState::RequestPending:
      return "REQUEST_PENDING";
    case OtisAdaptiveHybridMaintenanceState::ResponsePending:
      return "RESPONSE_PENDING";
    case OtisAdaptiveHybridMaintenanceState::MetadataHold:
      return "METADATA_HOLD";
    case OtisAdaptiveHybridMaintenanceState::FailStatic:
      return "FAIL_STATIC";
  }
  return nullptr;
}

const char *frontier_name(OtisAdaptiveHybridFrontierRelation value) {
  switch (value) {
    case OtisAdaptiveHybridFrontierRelation::NotApplicable:
      return "not_applicable";
    case OtisAdaptiveHybridFrontierRelation::First:
      return "first";
    case OtisAdaptiveHybridFrontierRelation::Contiguous:
      return "contiguous";
    case OtisAdaptiveHybridFrontierRelation::Overlap:
      return "overlap";
    case OtisAdaptiveHybridFrontierRelation::Gap:
      return "gap";
  }
  return nullptr;
}

const char *transaction_name(OtisAdaptiveHybridMaintenanceTransactionEvent value) {
  switch (value) {
    case OtisAdaptiveHybridMaintenanceTransactionEvent::None:
      return "none";
    case OtisAdaptiveHybridMaintenanceTransactionEvent::RequestCreated:
      return "request_created";
    case OtisAdaptiveHybridMaintenanceTransactionEvent::RequestWithdrawn:
      return "request_withdrawn";
    case OtisAdaptiveHybridMaintenanceTransactionEvent::Application:
      return "application";
    case OtisAdaptiveHybridMaintenanceTransactionEvent::ApplicationFault:
      return "application_fault";
    case OtisAdaptiveHybridMaintenanceTransactionEvent::Response:
      return "response";
  }
  return nullptr;
}

bool valid_csv_atom(const char *text) {
  if (text == nullptr || *text == '\0') return false;
  for (const char *cursor = text; *cursor != '\0'; ++cursor) {
    if (*cursor == ',' || *cursor == '\r' || *cursor == '\n') return false;
  }
  return true;
}

bool valid_sha256(const char *text) {
  if (text == nullptr) return false;
  for (size_t index = 0u; index < 64u; ++index) {
    const char value = text[index];
    if (!((value >= '0' && value <= '9') ||
          (value >= 'a' && value <= 'f')))
      return false;
  }
  return text[64] == '\0';
}

bool valid_code(uint32_t value) {
  return value == 0u || (value >= kMinimumCode && value <= kMaximumCode);
}

bool nonzero_hybrid_join(const OtisAdaptiveHybridMaintenanceRecord &record) {
  return record.hybrid_record_sequence != 0u &&
         record.decision_sequence != 0u &&
         record.source_acceptance_epoch != 0u &&
         otis_exact_selected_accepted_span(
             record.source_opening_accepted_boundary_ordinal,
             record.source_closing_accepted_boundary_ordinal);
}

bool zero_hybrid_join(const OtisAdaptiveHybridMaintenanceRecord &record) {
  return record.hybrid_record_sequence == 0u &&
         record.decision_sequence == 0u &&
         record.source_acceptance_epoch == 0u &&
         record.source_opening_accepted_boundary_ordinal == 0u &&
         record.source_closing_accepted_boundary_ordinal == 0u;
}

bool nonzero_transaction_join(const OtisAdaptiveHybridMaintenanceRecord &record) {
  return record.transaction_record_sequence != 0u &&
         record.request_sequence != 0u;
}

bool zero_transaction_join(const OtisAdaptiveHybridMaintenanceRecord &record) {
  return record.transaction_record_sequence == 0u &&
         record.request_sequence == 0u;
}

bool debt_tags_bounded(const OtisAdaptiveHybridMaintenanceRecord &record) {
  const int64_t values[] = {
      record.committed_fll_debt_before_picocodes,
      record.committed_pll_debt_before_picocodes,
      record.committed_fll_debt_after_picocodes,
      record.committed_pll_debt_after_picocodes,
  };
  for (const int64_t value : values) {
    if (value < -kMaximumDebtPicocodes || value > kMaximumDebtPicocodes)
      return false;
  }
  const int64_t before = values[0] + values[1];
  const int64_t after = values[2] + values[3];
  return before >= -kMaximumDebtPicocodes &&
         before <= kMaximumDebtPicocodes &&
         after >= -kMaximumDebtPicocodes &&
         after <= kMaximumDebtPicocodes;
}

bool debt_preserved(const OtisAdaptiveHybridMaintenanceRecord &record) {
  return record.committed_fll_debt_before_picocodes ==
             record.committed_fll_debt_after_picocodes &&
         record.committed_pll_debt_before_picocodes ==
             record.committed_pll_debt_after_picocodes;
}

bool validate_record(const OtisAdaptiveHybridMaintenanceRecord &record) {
  const char *event = event_name(record.event);
  const char *before = state_name(record.maintenance_state_before);
  const char *after = state_name(record.maintenance_state_after);
  const char *frontier = frontier_name(record.frontier_relation);
  const char *transaction = transaction_name(record.transaction_event);
  if (event == nullptr || before == nullptr || after == nullptr ||
      frontier == nullptr || transaction == nullptr)
    return false;
  if (!valid_csv_atom(record.run_identity) ||
      !valid_csv_atom(record.build_identity) ||
      !valid_csv_atom(record.image_identity) ||
      !valid_csv_atom(record.reason) ||
      !valid_sha256(record.active_policy_sha256) ||
      !valid_sha256(record.frequency_estimator_sha256))
    return false;
  if (record.maintenance_record_sequence == 0u ||
      record.persistence_count_before > 2u ||
      record.persistence_count_after > 2u ||
      record.requalification_window_count_before > 2u ||
      record.requalification_window_count_after > 2u ||
      record.safe_cap_codes > 21u || record.requested_delta_codes < -21 ||
      record.requested_delta_codes > 21 || record.interval_sign < -1 ||
      record.interval_sign > 1 || !valid_code(record.current_applied_code) ||
      !valid_code(record.requested_code) ||
      !valid_code(record.actual_applied_code) ||
      !debt_tags_bounded(record))
    return false;
  if (record.source_acceptance_epoch != 0u &&
      !otis_exact_selected_accepted_span(
          record.source_opening_accepted_boundary_ordinal,
          record.source_closing_accepted_boundary_ordinal))
    return false;
  if (record.current_applied_code != 0u &&
      static_cast<int64_t>(record.requested_code) !=
          static_cast<int64_t>(record.current_applied_code) +
              record.requested_delta_codes)
    return false;
  if (record.evidence_burst_sequence == 0u ||
      record.evidence_burst_record_ordinal == 0u ||
      record.evidence_burst_record_count == 0u ||
      record.evidence_burst_record_ordinal > record.evidence_burst_record_count)
    return false;
  if (record.event != OtisAdaptiveHybridMaintenanceEvent::GnssMetadataRequalified &&
      record.requalification_accepted_boundary_ordinal != 0u)
    return false;

  if (record.maintenance_state_after ==
          OtisAdaptiveHybridMaintenanceState::RequestPending &&
      !record.request_pending_after)
    return false;
  if (record.maintenance_state_after ==
          OtisAdaptiveHybridMaintenanceState::ResponsePending &&
      !record.response_pending_after)
    return false;
  if (record.maintenance_state_after ==
          OtisAdaptiveHybridMaintenanceState::MetadataHold &&
      !record.metadata_hold_after)
    return false;

  switch (record.event) {
    case OtisAdaptiveHybridMaintenanceEvent::PolicyActivation:
      return zero_hybrid_join(record) && zero_transaction_join(record) &&
             record.transaction_event ==
                 OtisAdaptiveHybridMaintenanceTransactionEvent::None &&
             record.maintenance_state_before ==
                 OtisAdaptiveHybridMaintenanceState::PolicyInactive &&
             record.maintenance_state_after ==
                 OtisAdaptiveHybridMaintenanceState::Ready &&
             record.committed_fll_debt_after_picocodes == 0 &&
             record.committed_pll_debt_after_picocodes == 0;

    case OtisAdaptiveHybridMaintenanceEvent::Decision: {
      if (!nonzero_hybrid_join(record) ||
          record.evidence_burst_record_count < 2u)
        return false;
      const bool request_created = !record.request_pending_before &&
                                   record.request_pending_after;
      if (request_created) {
        if (!nonzero_transaction_join(record) ||
            record.transaction_event !=
                OtisAdaptiveHybridMaintenanceTransactionEvent::RequestCreated ||
            record.evidence_burst_record_count != 3u)
          return false;
      } else if (!zero_transaction_join(record) ||
                 record.transaction_event !=
                     OtisAdaptiveHybridMaintenanceTransactionEvent::None ||
                 record.evidence_burst_record_count != 2u) {
        return false;
      }
      if (record.metadata_hold_before) {
        if (record.metadata_hold_after) {
          const bool frozen =
              record.requalification_window_count_before ==
                  record.requalification_window_count_after &&
              record.requalification_window_count_after < 2u;
          const bool first =
              record.requalification_window_count_before == 0u &&
              record.requalification_window_count_after == 1u;
          if ((!frozen && !first) || record.request_pending_after) return false;
        } else if (!(record.requalification_window_count_before == 1u &&
                     record.requalification_window_count_after == 2u)) {
          return false;
        }
      }
      return true;
    }

    case OtisAdaptiveHybridMaintenanceEvent::RequestRejectedOrExpired:
      return nonzero_hybrid_join(record) &&
             nonzero_transaction_join(record) &&
             record.transaction_event ==
                 OtisAdaptiveHybridMaintenanceTransactionEvent::RequestWithdrawn &&
             record.evidence_burst_record_count == 2u && debt_preserved(record) &&
             record.request_pending_before && !record.request_pending_after &&
             !record.response_pending_before && !record.response_pending_after;

    case OtisAdaptiveHybridMaintenanceEvent::ApplicationFirstConsumer:
      return nonzero_hybrid_join(record) &&
             nonzero_transaction_join(record) &&
             record.transaction_event ==
                 OtisAdaptiveHybridMaintenanceTransactionEvent::Application &&
             record.evidence_burst_record_count == 2u &&
             record.request_pending_before && !record.request_pending_after &&
             !record.response_pending_before && record.response_pending_after &&
             record.downstream_epoch_exact && record.application_sequence != 0u &&
             record.actual_applied_code != 0u && record.actual_dac_epoch != 0u &&
             record.actual_applied_code == record.requested_code &&
             record.actual_dac_epoch == record.current_dac_epoch + 1u &&
             record.maintenance_state_after ==
                 OtisAdaptiveHybridMaintenanceState::ResponsePending;

    case OtisAdaptiveHybridMaintenanceEvent::ResponseComplete:
      return nonzero_hybrid_join(record) &&
             nonzero_transaction_join(record) &&
             record.transaction_event ==
                 OtisAdaptiveHybridMaintenanceTransactionEvent::Response &&
             record.evidence_burst_record_count == 2u && debt_preserved(record) &&
             record.response_pending_before && !record.response_pending_after;

    case OtisAdaptiveHybridMaintenanceEvent::GnssMetadataHoldEnter:
      return zero_transaction_join(record) &&
             (record.transaction_event ==
                  OtisAdaptiveHybridMaintenanceTransactionEvent::None ||
              record.transaction_event ==
                  OtisAdaptiveHybridMaintenanceTransactionEvent::ApplicationFault) &&
             (zero_hybrid_join(record) || nonzero_hybrid_join(record)) &&
             debt_preserved(record) && !record.metadata_hold_before &&
             record.metadata_hold_after &&
             record.maintenance_state_after ==
                 OtisAdaptiveHybridMaintenanceState::MetadataHold &&
             record.persistence_count_after == 0u;

    case OtisAdaptiveHybridMaintenanceEvent::GnssMetadataRequalified:
      return zero_transaction_join(record) &&
             (record.transaction_event ==
                  OtisAdaptiveHybridMaintenanceTransactionEvent::None ||
              record.transaction_event ==
                  OtisAdaptiveHybridMaintenanceTransactionEvent::ApplicationFault) &&
             (zero_hybrid_join(record) || nonzero_hybrid_join(record)) &&
             debt_preserved(record) && record.metadata_hold_before &&
             record.metadata_hold_after &&
             record.requalification_window_count_after == 0u;

    case OtisAdaptiveHybridMaintenanceEvent::FailStatic: {
      if (!debt_preserved(record) ||
          record.maintenance_state_after !=
              OtisAdaptiveHybridMaintenanceState::FailStatic)
        return false;
      if (record.transaction_event ==
          OtisAdaptiveHybridMaintenanceTransactionEvent::ApplicationFault) {
        return nonzero_hybrid_join(record) &&
               nonzero_transaction_join(record) &&
               record.evidence_burst_record_count == 2u;
      }
      return zero_transaction_join(record) &&
             record.transaction_event ==
                 OtisAdaptiveHybridMaintenanceTransactionEvent::None &&
             (zero_hybrid_join(record) || nonzero_hybrid_join(record));
    }
  }
  return false;
}

bool append_separator(BoundedWriter *writer) {
  return writer != nullptr && writer->append_char(',');
}

bool append_bool(BoundedWriter *writer, bool value) {
  return writer != nullptr && writer->append(value ? "true" : "false");
}

bool append_u64(BoundedWriter *writer, uint64_t value) {
  return writer != nullptr && writer->append_unsigned(value);
}

bool append_i64(BoundedWriter *writer, int64_t value) {
  return writer != nullptr && writer->append_signed64(value);
}

}  // namespace

int otis_format_adaptive_hybrid_maintenance_v2_header(char *output,
                                             size_t output_size) {
  BoundedWriter writer(output, output_size);
  writer.append(kHeader);
  return writer.finish();
}

int otis_format_adaptive_hybrid_maintenance_v2(
    char *output, size_t output_size,
    const OtisAdaptiveHybridMaintenanceRecord *record) {
  if (output == nullptr || output_size == 0u || record == nullptr) return -1;
  output[0] = '\0';
  if (!validate_record(*record)) return -1;

  BoundedWriter writer(output, output_size);
#define OTIS_AHM_FIELD_TEXT(value) \
  (writer.append(value) && append_separator(&writer))
#define OTIS_AHM_FIELD_U64(value) \
  (append_u64(&writer, value) && append_separator(&writer))
#define OTIS_AHM_FIELD_I64(value) \
  (append_i64(&writer, value) && append_separator(&writer))
#define OTIS_AHM_FIELD_WIDE(value) \
  (writer.append_wide(value) && append_separator(&writer))
#define OTIS_AHM_FIELD_BOOL(value) \
  (append_bool(&writer, value) && append_separator(&writer))

  const bool ok =
      OTIS_AHM_FIELD_TEXT("AHM") && OTIS_AHM_FIELD_U64(2u) &&
      OTIS_AHM_FIELD_U64(record->maintenance_record_sequence) &&
      OTIS_AHM_FIELD_TEXT(event_name(record->event)) &&
      OTIS_AHM_FIELD_U64(record->event_timestamp_ticks) &&
      OTIS_AHM_FIELD_TEXT(kTimeDomain) &&
      OTIS_AHM_FIELD_TEXT(record->run_identity) &&
      OTIS_AHM_FIELD_TEXT(record->build_identity) &&
      OTIS_AHM_FIELD_TEXT(record->image_identity) &&
      OTIS_AHM_FIELD_TEXT(kPolicyId) &&
      OTIS_AHM_FIELD_TEXT(record->active_policy_sha256) &&
      OTIS_AHM_FIELD_U64(record->capture_session) &&
      OTIS_AHM_FIELD_U64(record->source_acceptance_epoch) &&
      OTIS_AHM_FIELD_U64(record->source_opening_accepted_boundary_ordinal) &&
      OTIS_AHM_FIELD_U64(record->source_closing_accepted_boundary_ordinal) &&
      OTIS_AHM_FIELD_TEXT(record->frequency_estimator_sha256) &&
      OTIS_AHM_FIELD_U64(record->phase_epoch) &&
      OTIS_AHM_FIELD_U64(record->phase_observation_sequence) &&
      OTIS_AHM_FIELD_BOOL(record->phase_valid) &&
      OTIS_AHM_FIELD_U64(record->current_applied_code) &&
      OTIS_AHM_FIELD_U64(record->current_dac_epoch) &&
      OTIS_AHM_FIELD_U64(record->hybrid_record_sequence) &&
      OTIS_AHM_FIELD_U64(record->decision_sequence) &&
      OTIS_AHM_FIELD_U64(record->transaction_record_sequence) &&
      OTIS_AHM_FIELD_TEXT(transaction_name(record->transaction_event)) &&
      OTIS_AHM_FIELD_U64(record->request_sequence) &&
      OTIS_AHM_FIELD_U64(record->application_sequence) &&
      OTIS_AHM_FIELD_U64(record->actual_applied_code) &&
      OTIS_AHM_FIELD_U64(record->actual_dac_epoch) &&
      OTIS_AHM_FIELD_BOOL(record->downstream_epoch_exact) &&
      OTIS_AHM_FIELD_TEXT(state_name(record->maintenance_state_before)) &&
      OTIS_AHM_FIELD_TEXT(state_name(record->maintenance_state_after)) &&
      OTIS_AHM_FIELD_TEXT(frontier_name(record->frontier_relation)) &&
      OTIS_AHM_FIELD_I64(record->interval_sign) &&
      OTIS_AHM_FIELD_U64(record->persistence_count_before) &&
      OTIS_AHM_FIELD_U64(record->persistence_count_after) &&
      OTIS_AHM_FIELD_WIDE(record->raw_fll_demand_picocodes) &&
      OTIS_AHM_FIELD_WIDE(record->raw_pll_demand_picocodes) &&
      OTIS_AHM_FIELD_WIDE(record->candidate_total_demand_picocodes) &&
      OTIS_AHM_FIELD_U64(record->safe_cap_codes) &&
      OTIS_AHM_FIELD_I64(record->requested_delta_codes) &&
      OTIS_AHM_FIELD_U64(record->requested_code) &&
      OTIS_AHM_FIELD_I64(record->committed_fll_debt_before_picocodes) &&
      OTIS_AHM_FIELD_I64(record->committed_pll_debt_before_picocodes) &&
      OTIS_AHM_FIELD_I64(record->committed_fll_debt_after_picocodes) &&
      OTIS_AHM_FIELD_I64(record->committed_pll_debt_after_picocodes) &&
      OTIS_AHM_FIELD_BOOL(record->request_pending_before) &&
      OTIS_AHM_FIELD_BOOL(record->request_pending_after) &&
      OTIS_AHM_FIELD_BOOL(record->response_pending_before) &&
      OTIS_AHM_FIELD_BOOL(record->response_pending_after) &&
      OTIS_AHM_FIELD_BOOL(record->metadata_hold_before) &&
      OTIS_AHM_FIELD_BOOL(record->metadata_hold_after) &&
      OTIS_AHM_FIELD_U64(record->requalification_window_count_before) &&
      OTIS_AHM_FIELD_U64(record->requalification_window_count_after) &&
      OTIS_AHM_FIELD_U64(
          record->requalification_accepted_boundary_ordinal) &&
      OTIS_AHM_FIELD_U64(record->evidence_burst_sequence) &&
      OTIS_AHM_FIELD_U64(record->evidence_burst_record_ordinal) &&
      OTIS_AHM_FIELD_U64(record->evidence_burst_record_count) &&
      OTIS_AHM_FIELD_TEXT(record->reason) && writer.append("false\r\n");

#undef OTIS_AHM_FIELD_TEXT
#undef OTIS_AHM_FIELD_U64
#undef OTIS_AHM_FIELD_I64
#undef OTIS_AHM_FIELD_WIDE
#undef OTIS_AHM_FIELD_BOOL

  if (!ok) return writer.finish();
  return writer.finish();
}
