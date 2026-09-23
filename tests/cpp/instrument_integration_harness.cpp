#include "otis_adaptive_hybrid_regulation_live.h"
#include "otis_instrument_executor.h"
#include "otis_dual_core_partition.h"
#include "otis_serial_command.h"
#include "otis_emit.h"
#include <cassert>
#include <cstring>
#include <map>
#include <string>
#include <cstdio>
uint32_t otis_transport_row_dropped() { return 0; }
size_t otis_transport_write_char(char c) {std::putchar(c);return 1;}
size_t otis_transport_write_cstr(const char*s) {std::fputs(s,stdout);return std::strlen(s);}
size_t otis_transport_write_uint32(uint32_t value) {char b[16];snprintf(b,sizeof(b),"%lu",(unsigned long)value);return otis_transport_write_cstr(b);}
void otis_transport_flush_if_needed() {}
void wire_field(void *,const char*k,const char*v,const char*severity,uint32_t flags) {
 static uint32_t sequence=0;
 otis_emit_health(++sequence,1000,"rp2040_monotonic_us32","adaptive_hybrid",k,v,severity,flags);
}
std::map<std::string,std::string> status;
void field(void *,const char*k,const char*v,const char*,uint32_t) {status[k]=v;}
void snapshot() {status.clear();otis_adaptive_hybrid_regulation_live_visit_status(nullptr,field,0);}
void init() {otis_dual_core_partition_reset();assert(otis_adaptive_hybrid_regulation_live_begin(17,17,1));}
OtisInstrumentWrite release(uint64_t t) {otis_adaptive_hybrid_regulation_live_service(t);OtisInstrumentWrite w={};assert(otis_dual_core_take_instrument_write(&w));return w;}
void application(OtisInstrumentWrite w,uint64_t t) {
 OtisInstrumentApplication a={w,t,w.code,true,true};
 assert(otis_dual_core_publish_instrument_application(&a));
 OtisInstrumentApplication b={};assert(otis_dual_core_take_instrument_application(&b));
 assert(otis_adaptive_hybrid_regulation_live_application(b));
 // These are the identical values the sketch propagates to both real previews
 // before this commit; the native adapter test verifies this exact barrier.
 assert(otis_adaptive_hybrid_regulation_live_confirm_consumers(b.code,b.request.dac_epoch,b.ticks));
}
void boot_and_repeated() {
 init(); auto w=release(2);assert(w.code==0xA84D && w.dac_epoch==1 && !w.prior_known);
 application(w,100);snapshot();assert(status["applied_code"]=="43085");
 // Deliberately leave all output undrained: internal writes must keep working.
 for(uint32_t i=1;i<=30;++i) {
  const uint64_t t=i*1000;
  const uint16_t code=uint16_t(0xA84D+(i%2));
  OtisInstrumentCommand c={17,i,OtisInstrumentMode::Fixed,code,0};
  assert(otis_adaptive_hybrid_regulation_live_command(c,t)==OtisInstrumentReceipt::Accepted);
  w=release(t+1);assert(w.sequence==i+1 && w.dac_epoch==i+1);application(w,t+2);
  assert(otis_adaptive_hybrid_regulation_live_command(c,t+3)==OtisInstrumentReceipt::Duplicate);
 }
 snapshot();assert(status["total_applications"]=="31" && status["command_completed"]=="30");
 OtisDualCoreQueueStats q={};otis_dual_core_get_stats(&q);assert(q.evidence_dropped_frames>0 && !q.fail_static);
 OtisAppliedDacStateMessage old={};old.published_ticks=1;otis_adaptive_hybrid_regulation_live_applied_snapshot(old);
 snapshot();assert(status["fault"]=="none");old.published_ticks=40000;otis_adaptive_hybrid_regulation_live_applied_snapshot(old);
 snapshot();assert(status["fault"]=="fresh_dac_snapshot_contradiction");
}
void executor() {
 OtisInstrumentExecutor e={};OtisInstrumentExecutorState s={true,true,false,0,false};
 OtisInstrumentWrite w={};w.session=17;w.capture_session=17;w.sequence=1;w.dac_epoch=1;w.code=0xA84D;w.kind=OtisInstrumentWriteKind::Startup;w.deadline_ticks=2000;
 assert(otis_instrument_executor_admit(&e,w,s,1)==OtisInstrumentRejection::None);
 assert(otis_instrument_executor_admit(&e,w,s,2)==OtisInstrumentRejection::IdentityInvalid);
 w.sequence=2;w.dac_epoch=2;w.prior_known=true;w.prior_code=0xA84D;w.kind=OtisInstrumentWriteKind::Correction;
 s.code_known=true;s.applied_code=w.prior_code;
 assert(otis_instrument_executor_admit(&e,w,s,3)==OtisInstrumentRejection::QualificationLost);
 w.sequence=3;s.receiver_qualified=true;
 assert(otis_instrument_executor_admit(&e,w,s,2000)==OtisInstrumentRejection::DeadlineExpired);
 w.sequence=4;s.platform_healthy=false;
 assert(otis_instrument_executor_admit(&e,w,s,3)==OtisInstrumentRejection::PlatformFault);
}
void commands() {
 char line[]="ACTIVE MODE 17 42 0 0 604800";auto command=otis_serial_command_parse(line);assert(command.kind==OtisSerialCommandKind::ActiveMode);
 uint64_t values[5];assert(otis_serial_command_parse_decimal_u64_fields(command.text_argument,values,5));assert(values[4]==604800 && values[2]==0);
 for(const char *old:{"ACTIVE ARM 1 2 3","ACTIVE SETUP 1","ACTIVE LEASE 1","ACTIVE EVIDENCE 1 2","ACTIVE ABORT"}) {
  char b[80];snprintf(b,sizeof(b),"%s",old);assert(otis_serial_command_parse(b).kind==OtisSerialCommandKind::Unknown);
 }
 assert(!otis_serial_command_parse_decimal_u64_fields("17 2 0 0 18446744073709551616",values,5));
}
void wire_records() {
 init();auto w=release(2);application(w,100);
 assert(otis_adaptive_hybrid_regulation_live_command({17,1,OtisInstrumentMode::Hold,0,0},200)==OtisInstrumentReceipt::Accepted);
 assert(otis_adaptive_hybrid_regulation_live_command({17,2,OtisInstrumentMode::Auto,0,0},300)==OtisInstrumentReceipt::Accepted);
 OtisEvidenceFrameMessage frame={};
 while(otis_dual_core_take_evidence(&frame)) std::fputs(frame.data,stdout);
 for(unsigned i=1;i<=8;++i) {
  uint64_t t=uint64_t(i)*2000*1000000ull;
  OtisAdaptiveHybridRegulationLiveHealth h={};h.session_id=17;h.acceptance_epoch=1;h.accepted_boundary_ordinal=i*600;
  h.gnss_metadata_sequence=i;h.gnss_metadata_valid=h.gnss_identity_stable=h.gnss_3d_evidence=h.raw_pps_valid=h.reference_integrity_valid=h.count_valid=h.abort_path_live=h.accepted_anchor_current=true;
  otis_adaptive_hybrid_regulation_live_update_health_at_ticks(&h,0,t);
  snapshot();
  OtisAdaptiveHybridRegulationLiveDecision d={};d.capture_session=17;d.source_acceptance_epoch=1;
  d.source_opening_accepted_boundary_ordinal=(i-1)*600;d.source_closing_accepted_boundary_ordinal=i*600;
  d.dac_epoch=std::stoul(status["dac_epoch"]);d.current_applied_code=std::stoul(status["applied_code"]);
  d.accumulated_edge_error_counts=-8;d.frequency_error_hz=-8.0/600;d.measurement_valid=d.model_applicable=d.preview_available=true;
  OtisAdaptiveHybridRegulationLiveOutcome out={};otis_adaptive_hybrid_regulation_live_on_decision_at_ticks(&d,t,&out);
  otis_adaptive_hybrid_regulation_live_service(t+1);
  if(otis_dual_core_take_instrument_write(&w)) application(w,t+100);
  while(otis_dual_core_take_evidence(&frame)) std::fputs(frame.data,stdout);
 }
}
void snapshot_wire() {
 otis_dual_core_partition_reset();assert(otis_adaptive_hybrid_regulation_live_begin(18446744073709551601ull,17,1));
 auto w=release(2);application(w,100);
 assert(otis_adaptive_hybrid_regulation_live_command({18446744073709551601ull,1,OtisInstrumentMode::Hold,0,0},200)==OtisInstrumentReceipt::Accepted);
 otis_adaptive_hybrid_regulation_live_visit_status(nullptr,wire_field,0);
 OtisEvidenceFrameMessage frame={};while(otis_dual_core_take_evidence(&frame)) std::fputs(frame.data,stdout);
}
int main(int argc,char**argv) {assert(argc==2);if(!strcmp(argv[1],"boot_repeated"))boot_and_repeated();else if(!strcmp(argv[1],"executor"))executor();else if(!strcmp(argv[1],"commands"))commands();else if(!strcmp(argv[1],"wire"))wire_records();else if(!strcmp(argv[1],"snapshot_wire"))snapshot_wire();else return 1;}
