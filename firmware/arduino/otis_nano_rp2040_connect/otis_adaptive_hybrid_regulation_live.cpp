#include "otis_adaptive_hybrid_regulation_live.h"
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include "otis_config.h"
#include "otis_dual_core_partition.h"
#include "otis_protocol.h"
#include "otis_transport_serial.h"

namespace {
OtisInstrument instrument = {};
OtisAdaptiveHybridRegulationLiveHealth latest_health = {};
uint32_t record_sequence = 0, snapshot_generation = 0, query_nonce = 0;
OtisEvidenceFrameMessage frame = {};
void evidence(const char *format, ...) {
  if (record_sequence == UINT32_MAX) { instrument.counters_saturated = true; return; }
  frame = {};
  frame.sequence = ++record_sequence; // assign before possible delivery loss
  va_list args; va_start(args, format);
  const int used = vsnprintf(frame.data, sizeof(frame.data), format, args);
  va_end(args);
  if (used > 6 && used < int(sizeof(frame.data))-12) {
    char identity[16]; const int n=snprintf(identity,sizeof(identity),"%lu,",(unsigned long)frame.sequence);
    memmove(frame.data+6+n,frame.data+6,size_t(used-6)+1);
    memcpy(frame.data+6,identity,size_t(n));
    frame.length = uint16_t(used+n);
    otis_dual_core_publish_evidence(&frame); // optional delivery has no control authority
  }
}
void state_evidence() {
  static OtisInstrumentMode last_mode=OtisInstrumentMode::Characterize,last_requested=OtisInstrumentMode::Characterize;
  static const char *last_state=nullptr,*last_reason=nullptr;
  static uint64_t last_session=0;
  static bool last_incomplete=false;
  const char *state=otis_instrument_state_name(&instrument);
  if (last_session==instrument.session && last_mode==instrument.mode && last_requested==instrument.requested_mode &&
      last_state==state && last_reason==instrument.reason && last_incomplete==instrument.response_incomplete) return;
  last_session=instrument.session;
  last_mode=instrument.mode; last_requested=instrument.requested_mode; last_state=state;
  last_reason=instrument.reason; last_incomplete=instrument.response_incomplete;
  evidence("IST,2,%llu,%lu,%s,%s,%s,%s,%lu,%lu,%lu,%u,%u,%u,%u,%lu,%llu,rp2040_timer_us64\n",
    (unsigned long long)instrument.session,(unsigned long)instrument.capture_session,otis_instrument_mode_name(instrument.mode),otis_instrument_mode_name(instrument.requested_mode),
    state,instrument.reason,(unsigned long)instrument.health.acceptance_epoch,(unsigned long)instrument.health.accepted_boundary,
    (unsigned long)instrument.health.metadata_sequence,instrument.reference_hold,instrument.metadata_hold,instrument.response_incomplete,
    instrument.applied_code,(unsigned long)instrument.dac_epoch,(unsigned long long)instrument.now_ticks);
}
void field(void *c, OtisRegulationStatusVisitor v, const char *k, const char *s) {
  v(c,k,s ? s : "none", OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
}
void number(void *c, OtisRegulationStatusVisitor v, const char *k, uint64_t n) {
  char b[24]; snprintf(b,sizeof(b),"%llu",(unsigned long long)n); field(c,v,k,b);
}
}
bool otis_adaptive_hybrid_regulation_live_begin(uint64_t session, uint32_t capture_session, uint64_t ticks) {
  record_sequence = snapshot_generation = query_nonce = 0;
  otis_instrument_init(&instrument, session, capture_session, ticks);
  state_evidence();
  return instrument.fault == nullptr;
}
void otis_adaptive_hybrid_regulation_live_emit_headers(void) {}
void otis_adaptive_hybrid_regulation_live_set_status_query_nonce(uint32_t n) { query_nonce=n; }
void otis_adaptive_hybrid_regulation_live_visit_status(void *c, OtisRegulationStatusVisitor v, uint32_t) {
  if (!v || snapshot_generation == UINT32_MAX) return;
  const auto &s=instrument;
  number(c,v,"snapshot_generation_begin",++snapshot_generation);
  field(c,v,"snapshot_contract","OTIS_INSTRUMENT_STATUS_V2");
  number(c,v,"query_nonce",query_nonce);
  number(c,v,"session_id",s.session);
  number(c,v,"capture_session",s.capture_session);
  field(c,v,"mode",otis_instrument_mode_name(s.mode));
  field(c,v,"requested_mode",otis_instrument_mode_name(s.requested_mode));
  field(c,v,"state",otis_instrument_state_name(&s));
  field(c,v,"reason",s.reason);
  field(c,v,"fault",s.fault);
  number(c,v,"applied_code",s.applied_code);
  field(c,v,"confirmed_applied_code_known",s.code_known?"true":"false");
  number(c,v,"dac_epoch",s.dac_epoch);
  number(c,v,"command_sequence",s.last_command.sequence);
  number(c,v,"command_completed",s.command_completed);
  number(c,v,"operating_end_ticks",s.operating_end_ticks);
  number(c,v,"write_sequence",s.write.sequence);
  number(c,v,"write_state",static_cast<unsigned>(s.write_state));
  number(c,v,"total_applications",s.total_applications);
  number(c,v,"cumulative_movement",s.cumulative_movement);
  field(c,v,"counters_saturated",s.counters_saturated?"true":"false");
  number(c,v,"instrument_ticks",s.now_ticks);
  field(c,v,"instrument_ticks_domain","rp2040_timer_us64");
  number(c,v,"acceptance_epoch",s.health.acceptance_epoch);
  number(c,v,"accepted_boundary_ordinal",s.health.accepted_boundary);
  field(c,v,"reference_hold",s.reference_hold?"true":"false");
  field(c,v,"metadata_hold",s.metadata_hold?"true":"false");
  field(c,v,"response_incomplete",s.response_incomplete?"true":"false");
  field(c,v,"active_policy_sha256",OTIS_BUILD_ADAPTIVE_POLICY_SHA256);
  field(c,v,"model_sha256",OTIS_BUILD_PLANT_MODEL_SHA256);
  field(c,v,"build_identity",OTIS_BUILD_SOURCE_SHA256 ":" OTIS_BUILD_CONFIG_SHA256);
  OtisDualCoreQueueStats queues={}; otis_dual_core_get_stats(&queues);
  number(c,v,"observation_dropped",queues.observation_dropped);
  number(c,v,"evidence_dropped",queues.evidence_dropped_frames);
  number(c,v,"phase_preview_dropped",queues.phase_preview_dropped);
  number(c,v,"telemetry_dropped",queues.telemetry_dropped);
  number(c,v,"critical_dropped",queues.critical_dropped);
  number(c,v,"direct_rows_dropped",otis_transport_row_dropped());
  field(c,v,"delivery_coverage","host_retention_unconfirmed");
  number(c,v,"snapshot_generation_complete",snapshot_generation);
}
void otis_adaptive_hybrid_regulation_live_update_health_at_ticks(const OtisAdaptiveHybridRegulationLiveHealth *h,uint32_t,uint64_t ticks) {
  if (!h) return;
  latest_health=*h;
  const OtisInstrumentHealth health = {h->session_id,h->acceptance_epoch,h->accepted_boundary_ordinal,
    h->gnss_metadata_sequence,h->reference_integrity_valid && h->abort_path_live,
    h->raw_pps_valid && h->count_valid && h->accepted_anchor_current,
    h->gnss_metadata_valid && h->gnss_identity_stable && h->gnss_3d_evidence};
  otis_instrument_health(&instrument,health,ticks);
  state_evidence();
}
void otis_adaptive_hybrid_regulation_live_service(uint64_t ticks) {
  otis_instrument_service(&instrument,ticks);
  OtisInstrumentWrite write={};
  if (otis_instrument_release(&instrument,&write,ticks)) {
    if (!otis_dual_core_publish_instrument_write(&write)) otis_instrument_fault(&instrument,"internal_write_mailbox");
    evidence("IWR,2,%llu,%lu,%lu,%lu,%u,%u,%u,%u,%llu,%llu,%lu,rp2040_timer_us64\n",
      (unsigned long long)write.session,(unsigned long)write.capture_session,(unsigned long)write.sequence,(unsigned long)write.dac_epoch,
      write.prior_code,write.code,write.prior_known,unsigned(write.kind),(unsigned long long)write.deadline_ticks,
      (unsigned long long)(write.kind==OtisInstrumentWriteKind::Correction?instrument.decision.decision_sequence:0),
      (unsigned long)(write.kind==OtisInstrumentWriteKind::Fixed || write.kind==OtisInstrumentWriteKind::Characterize?instrument.last_command.sequence:0));
  }
}
OtisInstrumentReceipt otis_adaptive_hybrid_regulation_live_command(const OtisInstrumentCommand &c,uint64_t ticks) {
  const auto receipt=otis_instrument_command(&instrument,c,ticks);
  evidence("ICM,2,%llu,%lu,%u,%u,%lu,%s,%lu,%llu,rp2040_timer_us64\n",(unsigned long long)c.session,
    (unsigned long)c.sequence,unsigned(c.mode),c.code,(unsigned long)c.dwell_s,
    receipt==OtisInstrumentReceipt::Accepted?"ACCEPTED":receipt==OtisInstrumentReceipt::Duplicate?"DUPLICATE":"REJECTED",
    (unsigned long)instrument.command_completed,(unsigned long long)ticks);
  state_evidence();
  return receipt;
}
bool otis_adaptive_hybrid_regulation_live_application(const OtisInstrumentApplication &a) {
  const bool accepted=otis_instrument_application(&instrument,a);
  evidence("IAP,2,%llu,%lu,%lu,%lu,%u,%u,%u,%u,%u,%u,%llu,rp2040_timer_us64\n",(unsigned long long)a.request.session,(unsigned long)a.request.capture_session,
    (unsigned long)a.request.sequence,(unsigned long)a.request.dac_epoch,a.request.code,a.code,
    a.attempted,a.ok,accepted,unsigned(a.rejection),(unsigned long long)a.ticks);
  state_evidence();
  return accepted;
}
bool otis_adaptive_hybrid_regulation_live_confirm_consumers(uint16_t code,uint32_t epoch,uint64_t ticks) {
  const bool accepted=otis_instrument_confirm_consumers(&instrument,code,epoch,ticks);
  state_evidence();
  return accepted;
}
void otis_adaptive_hybrid_regulation_live_on_decision_at_ticks(const OtisAdaptiveHybridRegulationLiveDecision *d,uint64_t ticks,OtisAdaptiveHybridRegulationLiveOutcome *out) {
  if (!out) return; *out={}; if (!d) return;
  OtisAdaptiveHybridObservation o={};
  o.timestamp_ticks=ticks; o.timestamp_s=ticks/1000000ull;
  o.capture_session=d->capture_session; o.source_acceptance_epoch=d->source_acceptance_epoch;
  o.source_opening_accepted_boundary_ordinal=d->source_opening_accepted_boundary_ordinal;
  o.source_closing_accepted_boundary_ordinal=d->source_closing_accepted_boundary_ordinal;
  o.dac_epoch=d->dac_epoch; o.applied_code=d->current_applied_code;
  o.accumulated_edge_error_counts=d->accumulated_edge_error_counts;
  o.tight_inside=d->tight_state && strcmp(d->tight_state,"TIGHT_INSIDE")==0;
  o.phase_epoch=d->phase_epoch; o.relative_phase_cycles=d->relative_phase_cycles;
  o.selected_estimator_identity=OTIS_BUILD_FREQUENCY_ESTIMATOR_TAG_U64;
  o.phase_valid=d->phase_continuous && d->phase_current && !d->phase_step_detected &&
    d->phase_dac_epoch==d->dac_epoch && d->phase_applied_code==d->current_applied_code;
  o.authority_valid=d->measurement_valid && d->model_applicable && latest_health.count_valid;
  o.settled=d->preview_available;
  OtisAdaptiveHybridDecision decision={};
  const uint64_t response_before=instrument.response_sequence;
  if (otis_instrument_decide(&instrument,o,&decision,d->frequency_error_hz)) {
    char fll[OTIS_ADAPTIVE_HYBRID_WIDE_DECIMAL_CAPACITY],pll[OTIS_ADAPTIVE_HYBRID_WIDE_DECIMAL_CAPACITY];
    otis_adaptive_hybrid_wide_format_decimal(decision.raw_fll_picocodes,fll,sizeof(fll));
    otis_adaptive_hybrid_wide_format_decimal(decision.raw_pll_picocodes,pll,sizeof(pll));
    evidence("IDC,2,%llu,%lu,%llu,%llu,%lu,%lu,%lu,%lu,%u,%ld,%ld,%lld,%llu,%lld,%u,%u,%u,%u,%u,%s,%s,%lld,%lld,%s\n",
      (unsigned long long)instrument.session,(unsigned long)instrument.capture_session,(unsigned long long)decision.decision_sequence,(unsigned long long)ticks,
      (unsigned long)o.source_acceptance_epoch,(unsigned long)o.source_opening_accepted_boundary_ordinal,
      (unsigned long)o.source_closing_accepted_boundary_ordinal,(unsigned long)o.dac_epoch,unsigned(o.applied_code),
      (long)decision.requested_delta_codes,(long)decision.requested_code,(long long)o.accumulated_edge_error_counts,
      (unsigned long long)o.phase_epoch,(long long)o.relative_phase_cycles,o.phase_valid,o.tight_inside,o.authority_valid,o.settled,
      instrument.health.metadata_qualified,fll,pll,(long long)instrument.engine.debt.fll_picocodes,
      (long long)instrument.engine.debt.pll_picocodes,decision.reason);
  }
  if (instrument.response_sequence!=response_before)
    evidence("IRS,2,%llu,%lu,%llu,%lu,%ld,%u,%s,%llu,%lu,%lu,%lu,rp2040_timer_us64\n",(unsigned long long)instrument.session,(unsigned long)instrument.capture_session,
      (unsigned long long)instrument.response_sequence,(unsigned long)instrument.dac_epoch,(long)instrument.response_delta_codes,
      unsigned(instrument.response_result.classification),instrument.response_result.reason,(unsigned long long)ticks,
      (unsigned long)o.source_acceptance_epoch,(unsigned long)o.source_opening_accepted_boundary_ordinal,(unsigned long)o.source_closing_accepted_boundary_ordinal);
  state_evidence();
  out->faulted=instrument.fault!=nullptr; out->reason=instrument.reason;
}

void otis_adaptive_hybrid_regulation_live_applied_snapshot(const OtisAppliedDacStateMessage &snapshot) {
  if (instrument.code_known && snapshot.published_ticks>=instrument.application_ticks &&
      (!snapshot.initialized || !snapshot.i2c_ok || !snapshot.requested_applied_match || snapshot.applied_code!=instrument.applied_code)) {
    otis_instrument_fault(&instrument,"fresh_dac_snapshot_contradiction");
    state_evidence();
  }
}
