#include "otis_cx323_maintenance_format.h"

#include <limits.h>
#include <string.h>

namespace {

constexpr char kPolicyId[] =
    "CX323_PHASE_PRIORITY_PERSISTENT_MAINTENANCE_V1";
constexpr char kTimeDomain[] = "rp2040_timer0_extended";
constexpr int64_t kMaximumDebtPicocodes = 500000000000LL;
constexpr uint32_t kMinimumCode = 0xA800u;
constexpr uint32_t kMaximumCode = 0xAB00u;

constexpr char kHeader[] =
    "record_type,schema_version,maintenance_record_sequence,event,"
    "event_timestamp_ticks,time_domain,run_identity,build_identity,"
    "profile_identity,policy_id,active_policy_sha256,capture_session,"
    "source_first_sequence,source_last_sequence,frequency_estimator_sha256,"
    "phase_epoch,phase_observation_sequence,phase_valid,current_applied_code,"
    "current_dac_epoch,hybrid_record_sequence,hybrid_timing_record_sequence,"
    "decision_sequence,transaction_record_sequence,"
    "transaction_timing_record_sequence,transaction_event,request_sequence,"
    "application_sequence,actual_applied_code,actual_dac_epoch,"
    "downstream_epoch_exact,maintenance_state_before,maintenance_state_after,"
    "frontier_relation,interval_sign,persistence_count_before,"
    "persistence_count_after,raw_fll_demand_picocodes,"
    "raw_pll_demand_picocodes,candidate_total_demand_picocodes,safe_cap_codes,"
    "requested_delta_codes,requested_code,"
    "committed_fll_debt_before_picocodes,"
    "committed_pll_debt_before_picocodes,"
    "committed_fll_debt_after_picocodes,"
    "committed_pll_debt_after_picocodes,request_pending_before,"
    "request_pending_after,response_pending_before,response_pending_after,"
    "metadata_hold_before,metadata_hold_after,"
    "requalification_window_count_before,requalification_window_count_after,"
    "requalification_d14_d8_observation_sequence,"
    "evidence_burst_sequence,evidence_burst_record_ordinal,"
    "evidence_burst_record_count,reason,actionable\r\n";

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

  bool append_wide(OtisCx323Wide value) {
    char decimal[OTIS_CX323_WIDE_DECIMAL_CAPACITY] = {};
    if (!otis_cx323_wide_format_decimal(value, decimal, sizeof(decimal)))
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

const char *event_name(OtisCx323MaintenanceEvent value) {
  switch (value) {
    case OtisCx323MaintenanceEvent::PolicyActivation:
      return "policy_activation";
    case OtisCx323MaintenanceEvent::Decision:
      return "decision";
    case OtisCx323MaintenanceEvent::RequestRejectedOrExpired:
      return "request_rejected_or_expired";
    case OtisCx323MaintenanceEvent::ApplicationFirstConsumer:
      return "application_first_consumer";
    case OtisCx323MaintenanceEvent::ResponseComplete:
      return "response_complete";
    case OtisCx323MaintenanceEvent::GnssMetadataHoldEnter:
      return "gnss_metadata_hold_enter";
    case OtisCx323MaintenanceEvent::GnssMetadataRequalified:
      return "gnss_metadata_requalified";
    case OtisCx323MaintenanceEvent::FailStatic:
      return "fail_static";
  }
  return nullptr;
}

const char *state_name(OtisCx323MaintenanceState value) {
  switch (value) {
    case OtisCx323MaintenanceState::PolicyInactive:
      return "POLICY_INACTIVE";
    case OtisCx323MaintenanceState::Ready:
      return "READY";
    case OtisCx323MaintenanceState::PersistenceHold:
      return "PERSISTENCE_HOLD";
    case OtisCx323MaintenanceState::RequestPending:
      return "REQUEST_PENDING";
    case OtisCx323MaintenanceState::ResponsePending:
      return "RESPONSE_PENDING";
    case OtisCx323MaintenanceState::MetadataHold:
      return "METADATA_HOLD";
    case OtisCx323MaintenanceState::FailStatic:
      return "FAIL_STATIC";
  }
  return nullptr;
}

const char *frontier_name(OtisCx323FrontierRelation value) {
  switch (value) {
    case OtisCx323FrontierRelation::NotApplicable:
      return "not_applicable";
    case OtisCx323FrontierRelation::First:
      return "first";
    case OtisCx323FrontierRelation::Contiguous:
      return "contiguous";
    case OtisCx323FrontierRelation::Overlap:
      return "overlap";
    case OtisCx323FrontierRelation::Gap:
      return "gap";
  }
  return nullptr;
}

const char *transaction_name(OtisCx323MaintenanceTransactionEvent value) {
  switch (value) {
    case OtisCx323MaintenanceTransactionEvent::None:
      return "none";
    case OtisCx323MaintenanceTransactionEvent::RequestCreated:
      return "request_created";
    case OtisCx323MaintenanceTransactionEvent::RequestWithdrawn:
      return "request_withdrawn";
    case OtisCx323MaintenanceTransactionEvent::Application:
      return "application";
    case OtisCx323MaintenanceTransactionEvent::ApplicationFault:
      return "application_fault";
    case OtisCx323MaintenanceTransactionEvent::Response:
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

bool nonzero_hybrid_join(const OtisCx323MaintenanceRecord &record) {
  return record.hybrid_record_sequence != 0u &&
         record.hybrid_timing_record_sequence != 0u &&
         record.decision_sequence != 0u && record.source_first_sequence != 0u &&
         record.source_last_sequence != 0u;
}

bool zero_hybrid_join(const OtisCx323MaintenanceRecord &record) {
  return record.hybrid_record_sequence == 0u &&
         record.hybrid_timing_record_sequence == 0u &&
         record.decision_sequence == 0u && record.source_first_sequence == 0u &&
         record.source_last_sequence == 0u;
}

bool nonzero_transaction_join(const OtisCx323MaintenanceRecord &record) {
  return record.transaction_record_sequence != 0u &&
         record.transaction_timing_record_sequence != 0u &&
         record.request_sequence != 0u;
}

bool zero_transaction_join(const OtisCx323MaintenanceRecord &record) {
  return record.transaction_record_sequence == 0u &&
         record.transaction_timing_record_sequence == 0u &&
         record.request_sequence == 0u;
}

bool debt_tags_bounded(const OtisCx323MaintenanceRecord &record) {
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

bool debt_preserved(const OtisCx323MaintenanceRecord &record) {
  return record.committed_fll_debt_before_picocodes ==
             record.committed_fll_debt_after_picocodes &&
         record.committed_pll_debt_before_picocodes ==
             record.committed_pll_debt_after_picocodes;
}

bool validate_record(const OtisCx323MaintenanceRecord &record) {
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
      !valid_csv_atom(record.profile_identity) ||
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
  if (record.source_first_sequence != 0u &&
      record.source_last_sequence != 0u &&
      record.source_last_sequence <= record.source_first_sequence)
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
  if (record.event != OtisCx323MaintenanceEvent::GnssMetadataRequalified &&
      record.requalification_d14_d8_observation_sequence != 0u)
    return false;

  if (record.maintenance_state_after ==
          OtisCx323MaintenanceState::RequestPending &&
      !record.request_pending_after)
    return false;
  if (record.maintenance_state_after ==
          OtisCx323MaintenanceState::ResponsePending &&
      !record.response_pending_after)
    return false;
  if (record.maintenance_state_after ==
          OtisCx323MaintenanceState::MetadataHold &&
      !record.metadata_hold_after)
    return false;

  switch (record.event) {
    case OtisCx323MaintenanceEvent::PolicyActivation:
      return zero_hybrid_join(record) && zero_transaction_join(record) &&
             record.transaction_event ==
                 OtisCx323MaintenanceTransactionEvent::None &&
             record.maintenance_state_before ==
                 OtisCx323MaintenanceState::PolicyInactive &&
             record.maintenance_state_after ==
                 OtisCx323MaintenanceState::Ready &&
             record.committed_fll_debt_after_picocodes == 0 &&
             record.committed_pll_debt_after_picocodes == 0;

    case OtisCx323MaintenanceEvent::Decision: {
      if (!nonzero_hybrid_join(record) ||
          record.evidence_burst_record_count < 3u)
        return false;
      const bool request_created = !record.request_pending_before &&
                                   record.request_pending_after;
      if (request_created) {
        if (!nonzero_transaction_join(record) ||
            record.transaction_event !=
                OtisCx323MaintenanceTransactionEvent::RequestCreated ||
            record.evidence_burst_record_count < 5u)
          return false;
      } else if (!zero_transaction_join(record) ||
                 record.transaction_event !=
                     OtisCx323MaintenanceTransactionEvent::None) {
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

    case OtisCx323MaintenanceEvent::RequestRejectedOrExpired:
      return nonzero_hybrid_join(record) &&
             nonzero_transaction_join(record) &&
             record.transaction_event ==
                 OtisCx323MaintenanceTransactionEvent::RequestWithdrawn &&
             record.evidence_burst_record_count >= 3u && debt_preserved(record) &&
             record.request_pending_before && !record.request_pending_after &&
             !record.response_pending_before && !record.response_pending_after;

    case OtisCx323MaintenanceEvent::ApplicationFirstConsumer:
      return nonzero_hybrid_join(record) &&
             nonzero_transaction_join(record) &&
             record.transaction_event ==
                 OtisCx323MaintenanceTransactionEvent::Application &&
             record.evidence_burst_record_count >= 3u &&
             record.request_pending_before && !record.request_pending_after &&
             !record.response_pending_before && record.response_pending_after &&
             record.downstream_epoch_exact && record.application_sequence != 0u &&
             record.actual_applied_code != 0u && record.actual_dac_epoch != 0u &&
             record.actual_applied_code == record.requested_code &&
             record.actual_dac_epoch == record.current_dac_epoch + 1u &&
             record.maintenance_state_after ==
                 OtisCx323MaintenanceState::ResponsePending;

    case OtisCx323MaintenanceEvent::ResponseComplete:
      return nonzero_hybrid_join(record) &&
             nonzero_transaction_join(record) &&
             record.transaction_event ==
                 OtisCx323MaintenanceTransactionEvent::Response &&
             record.evidence_burst_record_count >= 3u && debt_preserved(record) &&
             record.response_pending_before && !record.response_pending_after;

    case OtisCx323MaintenanceEvent::GnssMetadataHoldEnter:
      return zero_transaction_join(record) &&
             (record.transaction_event ==
                  OtisCx323MaintenanceTransactionEvent::None ||
              record.transaction_event ==
                  OtisCx323MaintenanceTransactionEvent::ApplicationFault) &&
             (zero_hybrid_join(record) || nonzero_hybrid_join(record)) &&
             debt_preserved(record) && !record.metadata_hold_before &&
             record.metadata_hold_after &&
             record.maintenance_state_after ==
                 OtisCx323MaintenanceState::MetadataHold &&
             record.persistence_count_after == 0u;

    case OtisCx323MaintenanceEvent::GnssMetadataRequalified:
      return zero_transaction_join(record) &&
             (record.transaction_event ==
                  OtisCx323MaintenanceTransactionEvent::None ||
              record.transaction_event ==
                  OtisCx323MaintenanceTransactionEvent::ApplicationFault) &&
             (zero_hybrid_join(record) || nonzero_hybrid_join(record)) &&
             debt_preserved(record) && record.metadata_hold_before &&
             record.metadata_hold_after &&
             record.requalification_window_count_after == 0u &&
             record.requalification_d14_d8_observation_sequence != 0u;

    case OtisCx323MaintenanceEvent::FailStatic: {
      if (!debt_preserved(record) ||
          record.maintenance_state_after !=
              OtisCx323MaintenanceState::FailStatic)
        return false;
      if (record.transaction_event ==
          OtisCx323MaintenanceTransactionEvent::ApplicationFault) {
        return nonzero_hybrid_join(record) &&
               nonzero_transaction_join(record) &&
               record.evidence_burst_record_count >= 3u;
      }
      return zero_transaction_join(record) &&
             record.transaction_event ==
                 OtisCx323MaintenanceTransactionEvent::None &&
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

int otis_format_cx323_maintenance_v1_header(char *output,
                                             size_t output_size) {
  BoundedWriter writer(output, output_size);
  writer.append(kHeader);
  return writer.finish();
}

int otis_format_cx323_maintenance_v1(
    char *output, size_t output_size,
    const OtisCx323MaintenanceRecord *record) {
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
      OTIS_AHM_FIELD_TEXT("AHM") && OTIS_AHM_FIELD_U64(1u) &&
      OTIS_AHM_FIELD_U64(record->maintenance_record_sequence) &&
      OTIS_AHM_FIELD_TEXT(event_name(record->event)) &&
      OTIS_AHM_FIELD_U64(record->event_timestamp_ticks) &&
      OTIS_AHM_FIELD_TEXT(kTimeDomain) &&
      OTIS_AHM_FIELD_TEXT(record->run_identity) &&
      OTIS_AHM_FIELD_TEXT(record->build_identity) &&
      OTIS_AHM_FIELD_TEXT(record->profile_identity) &&
      OTIS_AHM_FIELD_TEXT(kPolicyId) &&
      OTIS_AHM_FIELD_TEXT(record->active_policy_sha256) &&
      OTIS_AHM_FIELD_U64(record->capture_session) &&
      OTIS_AHM_FIELD_U64(record->source_first_sequence) &&
      OTIS_AHM_FIELD_U64(record->source_last_sequence) &&
      OTIS_AHM_FIELD_TEXT(record->frequency_estimator_sha256) &&
      OTIS_AHM_FIELD_U64(record->phase_epoch) &&
      OTIS_AHM_FIELD_U64(record->phase_observation_sequence) &&
      OTIS_AHM_FIELD_BOOL(record->phase_valid) &&
      OTIS_AHM_FIELD_U64(record->current_applied_code) &&
      OTIS_AHM_FIELD_U64(record->current_dac_epoch) &&
      OTIS_AHM_FIELD_U64(record->hybrid_record_sequence) &&
      OTIS_AHM_FIELD_U64(record->hybrid_timing_record_sequence) &&
      OTIS_AHM_FIELD_U64(record->decision_sequence) &&
      OTIS_AHM_FIELD_U64(record->transaction_record_sequence) &&
      OTIS_AHM_FIELD_U64(record->transaction_timing_record_sequence) &&
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
          record->requalification_d14_d8_observation_sequence) &&
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
