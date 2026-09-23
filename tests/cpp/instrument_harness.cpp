#include "otis_instrument.h"
#include <cassert>
#include <cstring>
#include <cstdio>

constexpr uint64_t S=1000000ull;
OtisInstrument fresh() {
  OtisInstrument s;
  otis_instrument_init(&s, 17, 17, 1);
  assert(!s.fault);
  OtisInstrumentWrite w;
  assert(otis_instrument_release(&s,&w,2));
  assert(w.code==0xA84D && !w.prior_known);
  otis_instrument_service(&s,200); // service can precede a delayed ack receipt
  assert(otis_instrument_application(&s,{w,100,w.code,true,true}));
  assert(s.now_ticks==200);
  assert(otis_instrument_confirm_consumers(&s,w.code,1,100));
  assert(s.code_known && s.dac_epoch==1 && s.total_applications==1);
  return s;
}
void health(OtisInstrument &s, uint64_t ticks, uint32_t boundary=600,
            bool ref=true,bool metadata=true,uint32_t epoch=1,uint32_t meta_seq=1) {
  otis_instrument_health(&s,{17,epoch,boundary,meta_seq,true,ref,metadata},ticks);
}
OtisAdaptiveHybridObservation observation(OtisInstrument &s,uint64_t ticks,uint32_t closing,int counts) {
  OtisAdaptiveHybridObservation o={};
  o.timestamp_ticks=ticks; o.timestamp_s=ticks/S;
  o.capture_session=17; o.source_acceptance_epoch=s.health.acceptance_epoch;
  o.source_opening_accepted_boundary_ordinal=closing-600u;
  o.source_closing_accepted_boundary_ordinal=closing;
  o.dac_epoch=s.dac_epoch; o.applied_code=s.applied_code;
  o.accumulated_edge_error_counts=counts;
  o.authority_valid=o.settled=o.cadence_eligible=o.metadata_qualified=true;
  o.selected_estimator_identity=1;
  return o;
}
bool decide(OtisInstrument &s,uint64_t ticks,uint32_t closing,int counts) {
  health(s,ticks+20,closing,true,true,s.health.acceptance_epoch?s.health.acceptance_epoch:1,2);
  auto o=observation(s,ticks,closing,counts);
  OtisAdaptiveHybridDecision d;
  return otis_instrument_decide(&s,o,&d,counts/600.0);
}
void apply(OtisInstrument &s) {
  OtisInstrumentWrite w;
  assert(otis_instrument_release(&s,&w,s.now_ticks+1));
  assert(otis_instrument_application(&s,{w,s.now_ticks+100,w.code,true,true}));
  assert(otis_instrument_confirm_consumers(&s,w.code,w.dac_epoch,s.application_ticks));
}
void boot_modes() {
  auto s=fresh();
  assert(s.mode==OtisInstrumentMode::Auto);
  OtisInstrumentCommand hold={17,1,OtisInstrumentMode::Hold,0,0};
  assert(otis_instrument_command(&s,hold,300)==OtisInstrumentReceipt::Accepted);
  assert(s.mode==OtisInstrumentMode::Hold && s.command_completed==1);
  assert(otis_instrument_command(&s,hold,400)==OtisInstrumentReceipt::Duplicate);
  hold.code=1;
  assert(otis_instrument_command(&s,hold,500)==OtisInstrumentReceipt::Rejected);
  hold.code=0;hold.session=18;
  assert(otis_instrument_command(&s,hold,600)==OtisInstrumentReceipt::Rejected);
  health(s,1000);
  assert(s.mode==OtisInstrumentMode::Hold);
  assert(!decide(s,2000*S,600,-8));
  auto restarted=fresh();
  assert(restarted.mode==OtisInstrumentMode::Auto && restarted.applied_code==0xA84D);
  otis_instrument_init(&restarted, 0xfedcba9876543210ull, 17, 1);
  assert(otis_instrument_command(&restarted,{17,1,OtisInstrumentMode::Hold,0,0},2)==OtisInstrumentReceipt::Rejected);
  assert(restarted.requested_mode==OtisInstrumentMode::Auto);
}
void fixed_characterize() {
  auto s=fresh();
  assert(otis_instrument_command(&s,{17,1,OtisInstrumentMode::Fixed,0xA850,0},300)==OtisInstrumentReceipt::Accepted);
  otis_instrument_service(&s,400);apply(s);
  assert(s.applied_code==0xA850 && s.dac_epoch==2 && s.command_completed==1);
  assert(otis_instrument_command(&s,{17,2,OtisInstrumentMode::Characterize,0xA855,2},1000)==OtisInstrumentReceipt::Accepted);
  otis_instrument_service(&s,1100);apply(s);
  auto end=s.characterize_end_ticks;
  assert(end==s.application_ticks+2*S);
  otis_instrument_service(&s,end-1);
  assert(s.mode==OtisInstrumentMode::Characterize);
  otis_instrument_service(&s,end);
  assert(s.mode==OtisInstrumentMode::Hold && s.applied_code==0xA855);
  assert(otis_instrument_command(&s,{17,3,OtisInstrumentMode::Fixed,0xA700,0},end+1)==OtisInstrumentReceipt::Rejected);
  assert(otis_instrument_command(&s,{17,3,OtisInstrumentMode::Characterize,0xA880,1},end+2)==OtisInstrumentReceipt::Rejected);
}
void repeated() {
  auto s=fresh();uint64_t t=2000*S;uint32_t ordinal=600;
  int direction=-1;
  for(int i=0;i<180;i++) {
    if(s.applied_code>0xAAE0)direction=1;
    if(s.applied_code<0xA820)direction=-1;
    assert(decide(s,t,ordinal,direction*8));
    assert(!s.fault && s.write_state==OtisInstrumentWriteState::Proposed);
    apply(s);
    assert(s.engine.response_pending);
    t+=1600*S;ordinal+=1600;
    assert(!decide(s,t,ordinal,0)); // response frontier never issues next write
    assert(!s.fault && !s.engine.response_pending && s.response_sequence==uint64_t(i+1));
    t+=600*S;ordinal+=600;
  }
  assert(s.total_applications==181 && s.cumulative_movement>3024);
  assert(s.engine.application_count==180 && !s.fault);
}
void pending_modes() {
  auto s=fresh();assert(decide(s,2000*S,600,-8));
  assert(otis_instrument_command(&s,{17,1,OtisInstrumentMode::Hold,0,0},s.now_ticks+1)==OtisInstrumentReceipt::Accepted);
  assert(s.write_state==OtisInstrumentWriteState::Idle && !s.engine.request_pending);
  assert(s.applied_code==0xA84D);
  assert(otis_instrument_command(&s,{17,2,OtisInstrumentMode::Auto,0,0},s.now_ticks+1)==OtisInstrumentReceipt::Accepted);
  assert(decide(s,4000*S,2600,-8));
  OtisInstrumentWrite w;assert(otis_instrument_release(&s,&w,s.now_ticks+1));
  assert(otis_instrument_command(&s,{17,3,OtisInstrumentMode::Hold,0,0},s.now_ticks+1)==OtisInstrumentReceipt::Accepted);
  assert(s.mode==OtisInstrumentMode::Auto && s.requested_mode==OtisInstrumentMode::Hold);
  assert(otis_instrument_application(&s,{w,s.now_ticks+1,w.code,true,true}));
  assert(otis_instrument_confirm_consumers(&s,w.code,w.dac_epoch,s.application_ticks));
  assert(s.mode==OtisInstrumentMode::Hold && s.command_completed==3);
  assert(!s.engine.response_pending && s.response_incomplete);
}
void reference_recovery() {
  auto s=fresh();assert(decide(s,2000*S,600,-8));apply(s);
  assert(s.engine.response_pending);
  health(s,2100*S,700,false,true,2);
  assert(s.response_incomplete && !s.engine.response_pending && !s.fault);
  health(s,2200*S,800,true,true,2);
  assert(decide(s,4000*S,2600,-8));
  assert(s.write_state==OtisInstrumentWriteState::Proposed && !s.fault);
  health(s,4000*S+30,2600,false,true,3);
  assert(!s.engine.request_pending && s.write_state==OtisInstrumentWriteState::Idle);
}
void metadata_recovery() {
  auto s=fresh();health(s,1000,100,false,false,1,1);
  assert(s.metadata_hold && s.engine.metadata_hold);
  health(s,2000,200,true,true,1,2);
  auto first=observation(s,2000*S,800,0);first.tight_inside=true;first.phase_valid=true;first.phase_epoch=1;
  health(s,2000*S+20,800,true,true,1,2);
  OtisAdaptiveHybridDecision d;
  assert(otis_instrument_decide(&s,first,&d,0));
  assert(s.metadata_hold && d.requested_delta_codes==0);
  auto second=first;second.timestamp_ticks=2600*S;second.timestamp_s=2600;
  second.source_opening_accepted_boundary_ordinal=800;second.source_closing_accepted_boundary_ordinal=1400;
  health(s,2600*S+20,1400,true,true,1,2);
  assert(otis_instrument_decide(&s,second,&d,0));
  assert(!s.metadata_hold && !s.engine.metadata_hold && !s.fault);
}
void metadata_response_interruption() {
  auto s=fresh();assert(decide(s,2000*S,600,-8));apply(s);
  assert(s.engine.response_pending);
  health(s,2100*S,700,true,false,1,3);
  assert(s.response_incomplete && !s.engine.response_pending);
  assert(s.metadata_hold && s.engine.metadata_hold && !s.fault);
  assert(s.response_sequence==0);
  health(s,2200*S,800,true,true,1,4);
  assert(s.engine.metadata_requalified && !s.fault);
}
void metadata_released_application() {
  auto s=fresh();assert(decide(s,2000*S,600,-8));
  OtisInstrumentWrite w;assert(otis_instrument_release(&s,&w,s.now_ticks+1));
  health(s,s.now_ticks+1,601,true,false,1,3);
  assert(s.metadata_hold && s.engine.request_pending && !s.engine.metadata_hold);
  assert(otis_instrument_application(&s,{w,s.now_ticks+1,w.code,true,true}));
  assert(otis_instrument_confirm_consumers(&s,w.code,w.dac_epoch,s.application_ticks));
  assert(s.response_incomplete && !s.engine.response_pending);
  assert(s.metadata_hold && s.engine.metadata_hold && !s.fault);
  health(s,s.now_ticks+10,602,true,true,1,4);
  assert(s.engine.metadata_requalified && !s.fault);
}
void metadata_during_startup() {
  OtisInstrument s;
  otis_instrument_init(&s,17,17,1);
  health(s,2,1,true,false,1,3);
  OtisInstrumentWrite w;
  assert(otis_instrument_release(&s,&w,3));
  assert(otis_instrument_application(&s,{w,100,w.code,true,true}));
  assert(otis_instrument_confirm_consumers(&s,w.code,w.dac_epoch,s.application_ticks));
  assert(s.engine_ready && s.metadata_hold && s.engine.metadata_hold && !s.fault);
  health(s,200,2,true,true,1,4);
  assert(s.engine.metadata_requalified && !s.fault);
}
void timed_auto_delayed_overflow() {
  const uint64_t near_max=UINT64_MAX-3000000ull;
  OtisInstrument s;
  otis_instrument_init(&s,17,17,near_max);
  assert(!s.fault);
  OtisInstrumentWrite w;
  assert(otis_instrument_release(&s,&w,near_max+1));
  assert(otis_instrument_command(&s,{17,1,OtisInstrumentMode::Auto,0,2},near_max+2)==OtisInstrumentReceipt::Accepted);
  assert(otis_instrument_application(&s,{w,near_max+1500000ull,w.code,true,true}));
  assert(otis_instrument_confirm_consumers(&s,w.code,w.dac_epoch,s.application_ticks));
  assert(s.fault && strcmp(s.fault,"operating_deadline_overflow")==0);
  assert(s.applied_code==w.code && s.dac_epoch==w.dac_epoch);
}
void timed_auto() {
  auto s=fresh();
  assert(otis_instrument_command(&s,{17,1,OtisInstrumentMode::Auto,0,2000},300)==OtisInstrumentReceipt::Accepted);
  const auto end=s.operating_end_ticks;
  assert(end==2000*S+300);
  assert(decide(s,2000*S,600,-8));
  OtisInstrumentWrite w;
  assert(otis_instrument_release(&s,&w,s.now_ticks+1));
  otis_instrument_service(&s,end);
  assert(s.requested_mode==OtisInstrumentMode::Hold);
  assert(otis_instrument_application(&s,{w,end+1,w.code,true,true}));
  assert(otis_instrument_confirm_consumers(&s,w.code,w.dac_epoch,s.application_ticks));
  assert(s.mode==OtisInstrumentMode::Hold && !s.engine.response_pending && !s.fault);
}
void failure_identity() {
  auto s=fresh();assert(decide(s,2000*S,600,-8));
  OtisInstrumentWrite w;assert(otis_instrument_release(&s,&w,s.now_ticks+1));
  auto wrong=w;wrong.sequence++;
  assert(!otis_instrument_application(&s,{wrong,s.now_ticks+1,w.code,true,true}));
  assert(s.fault && s.applied_code==0xA84D);
  assert(otis_instrument_command(&s,{17,1,OtisInstrumentMode::Auto,0,0},s.now_ticks+2)==OtisInstrumentReceipt::Rejected);
  // An exact physical outcome arriving after unrelated fault inhibition is still retained.
  assert(otis_instrument_application(&s,{w,s.now_ticks+3,w.code,true,true}));
  assert(otis_instrument_confirm_consumers(&s,w.code,w.dac_epoch,s.application_ticks));
  assert(s.fault && s.applied_code==w.code);
  s=fresh();assert(decide(s,2000*S,600,-8));
  assert(otis_instrument_release(&s,&w,s.now_ticks+1));
  assert(!otis_instrument_application(&s,{w,s.now_ticks+1,w.prior_code,true,false}));
  assert(s.fault && !s.code_known);
}
void timeout_rejection() {
  auto s=fresh();assert(decide(s,2000*S,600,-8));
  OtisInstrumentWrite w;assert(otis_instrument_release(&s,&w,s.now_ticks+1));
  assert(otis_instrument_application(&s,{w,s.now_ticks+1,w.prior_code,false,false,OtisInstrumentRejection::QualificationLost}));
  assert(!s.fault && !s.engine.request_pending && s.applied_code==w.prior_code);
  assert(decide(s,4000*S,2600,-8));
  assert(otis_instrument_release(&s,&w,s.now_ticks+1));
  otis_instrument_service(&s,w.deadline_ticks);
  assert(s.fault);
  assert(otis_instrument_application(&s,{w,w.deadline_ticks+1,w.code,true,true}));
  assert(otis_instrument_confirm_consumers(&s,w.code,w.dac_epoch,s.application_ticks));
  assert(s.fault && s.code_known && s.applied_code==w.code);
}
int main(int argc,char **argv) {
  assert(argc==2);
  const char *name=argv[1];
  if(!strcmp(name,"boot_modes"))boot_modes();
  else if(!strcmp(name,"fixed_characterize"))fixed_characterize();
  else if(!strcmp(name,"repeated"))repeated();
  else if(!strcmp(name,"pending_modes"))pending_modes();
  else if(!strcmp(name,"reference_recovery"))reference_recovery();
  else if(!strcmp(name,"metadata_recovery"))metadata_recovery();
  else if(!strcmp(name,"metadata_response_interruption"))metadata_response_interruption();
  else if(!strcmp(name,"metadata_released_application"))metadata_released_application();
  else if(!strcmp(name,"metadata_during_startup"))metadata_during_startup();
  else if(!strcmp(name,"timed_auto_delayed_overflow"))timed_auto_delayed_overflow();
  else if(!strcmp(name,"timed_auto"))timed_auto();
  else if(!strcmp(name,"failure_identity"))failure_identity();
  else if(!strcmp(name,"timeout_rejection"))timeout_rejection();
  else return 2;
  puts(name);
}
