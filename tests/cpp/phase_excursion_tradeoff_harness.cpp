// Finite offline model. No device, serial, firmware activation or authority.
#include "otis_adaptive_hybrid_regulation.h"
#include "otis_integer_count_tight_deadband.h"
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <numeric>
#include <sstream>
#include <string>

struct Projection { int64_t count; bool localized=false,model=false; };
int64_t rounded(double x) {return x>=0?int64_t(std::floor(x+.5)):int64_t(std::ceil(x-.5));}
Projection project(const std::array<int,600>& counts,int policy) {
  const int64_t total=std::accumulate(counts.begin(),counts.end(),int64_t(0));
  int large=0,impulse=0;
  for(int v:counts) if(std::abs(v)>=2) {++large;impulse=v;}
  const bool local=large==1 && std::abs(total-impulse)<=1;
  if(policy==2 && local) return {total-impulse,true,true};
  if(policy!=4 && policy!=5) return {total,local,false};
  // y_i is cumulative integer count residual. No raw datum is overwritten.
  std::array<double,601> y={},prefix={};
  for(unsigned i=1;i<=600;++i)y[i]=y[i-1]+counts[i-1];
  double sy=0,sxy0=0,syy0=0;
  for(unsigned i=0;i<=600;++i) {sy+=y[i];sxy0+=i*y[i];syy0+=y[i]*y[i];prefix[i]=sy;}
  constexpr double n=601,sx=180300,sxx0=72180100;
  const double sxx=sxx0-sx*sx/n,sxy=sxy0-sx*sy/n,syy=syy0-sy*sy/n;
  const double linear_sse=std::max(0.0,syy-sxy*sxy/sxx);
  double best_sse=linear_sse,best_b=sxy/sxx,best_step=0;
  for(unsigned p=60;p<=540;++p) {
    const double nh=601-p,sxh0=sx-(p-1)*double(p)/2;
    const double shh=nh-nh*nh/n,sxh=sxh0-sx*nh/n,syh=sy-prefix[p-1]-sy*nh/n;
    const double determinant=sxx*shh-sxh*sxh;
    assert(determinant>0);
    const double b=(sxy*shh-syh*sxh)/determinant,c=(syh*sxx-sxy*sxh)/determinant;
    const double sse=std::max(0.0,syy-b*sxy-c*syh);
    if(sse<best_sse) {best_sse=sse;best_b=b;best_step=c;}
  }
  if(std::abs(best_step)>=2 && linear_sse-best_sse>=36)
    return {rounded(best_b*600),local,true};
  return {total,local,false};
}

// Reconstruct one recorded ordinary-path checkpoint for projection comparisons.
void project_records() {
  std::string line;
  while(std::getline(std::cin,line)) {
    std::istringstream in(line);std::string id;uint64_t ticks,prior,accept,open,close,dac,phase_epoch;
    int code,tight;int64_t phase;
    if(!(in>>id>>ticks>>prior>>accept>>open>>close>>dac>>code>>phase_epoch>>phase>>tight))return;
    std::array<int,600> counts={};for(auto&v:counts) {in>>v;assert(in);}
    for(int p=0;p<6;++p) {
      auto projected=project(counts,p);
      OtisAdaptiveHybridObservation o={};o.timestamp_ticks=ticks;o.timestamp_s=ticks/1000000;
      o.capture_session=1;o.source_acceptance_epoch=accept;o.source_opening_accepted_boundary_ordinal=open;o.source_closing_accepted_boundary_ordinal=close;
      o.dac_epoch=dac;o.applied_code=code;o.accumulated_edge_error_counts=projected.count;
      o.phase_epoch=phase_epoch;o.relative_phase_cycles=phase;o.tight_inside=tight;
      o.phase_valid=o.authority_valid=o.settled=o.cadence_eligible=o.metadata_qualified=true;o.selected_estimator_identity=1;
      auto policy=otis_adaptive_hybrid_default_policy();policy.maximum_applications=policy.maximum_cumulative_movement_codes=0;
      OtisAdaptiveHybridEngine engine={};assert(otis_adaptive_hybrid_engine_init(&engine,&policy,code,dac));
      assert(otis_adaptive_hybrid_engine_bind_exact_setup_application(&engine,prior));
      OtisAdaptiveHybridDecision decision={};assert(otis_adaptive_hybrid_engine_decide(&engine,&o,&decision));
      // Confirmation candidates have no preceding same-identity source here:
      // report pending, not a guessed completed counterfactual application.
      bool wait=(p==1 && projected.count!=0)||(p==3 && projected.localized)||(p==5 && projected.localized&&!projected.model);
      std::cout<<id<<","<<p<<","<<projected.count<<","<<(wait?0:decision.requested_delta_codes)<<","<<wait<<","<<projected.model<<"\n";
    }
  }
}

double jitter(int t,double amplitude) {
  uint32_t x=uint32_t(t)*747796405u+2891336453u;
  x=((x>>((x>>28u)+4u))^x)*277803737u;x=(x>>22u)^x;
  return amplitude*(double(x)/4294967295.0*2-1);
}
struct Case {std::string id;int family;double gain,fraction;int position,drift,pulse,width;double noise;};
void simulate(const Case& c,int p) {
  constexpr int horizon=28800,open=7200,start_code=43085;
  const int onset=open+c.position;
  auto policy=otis_adaptive_hybrid_default_policy();policy.maximum_applications=policy.maximum_cumulative_movement_codes=0;
  OtisAdaptiveHybridEngine engine={};assert(otis_adaptive_hybrid_engine_init(&engine,&policy,start_code,1));
  assert(otis_adaptive_hybrid_engine_bind_exact_setup_application(&engine,1));
  OtisIntegerCountDeadbandTightDeadband band={};otis_integer_count_tight_deadband_init(&band);
  int code=start_code,last_app=0,ncount=0,previous_direction=0,applications=0,large=0,movement=0,reversals=0,max_step=0,model_selections=0;
  int first_app=-1,first_correct=-1,within_since=-1,reduced=-1;
  int64_t prev_fll=0;bool previous_available=false,local_pending=false;
  double phase=3,iae=0,peak=0;
  int64_t previous_observation=int64_t(std::floor(phase+c.fraction+jitter(0,c.noise)+1e-9));
  int64_t observed_phase=3;
  std::array<int,600> counts={};
  for(int t=1;t<=horizon;++t) {
    double external=0;
    if(t>=onset) {
      if(c.family==1||c.family==4)external=c.drift/600.0;
      if(c.family==2)external=c.drift/600.0*std::min(1.0,(t-onset+1)/3600.0);
    }
    const double actual_frequency=external+(code-start_code)*c.gain;
    phase+=actual_frequency;
    double offset=0;
    if(t>=onset && (c.family==3||c.family==4||c.family==6))offset=c.pulse*std::min(1.0,(t-onset+1)/double(c.width));
    if(c.family==5 && t==onset)offset=c.pulse;
    const int64_t measured=int64_t(std::floor(phase+c.fraction+offset+jitter(t,c.noise)+1e-9));
    const int residual=int(measured-previous_observation);previous_observation=measured;observed_phase+=residual;
    if(t>=onset) {
      iae+=std::abs(actual_frequency);peak=std::max(peak,std::abs(actual_frequency)*100);
      if(c.family==1 && std::abs(actual_frequency)<=std::abs(c.drift/600.0)*.75) {
        if(within_since<0)within_since=t;
        if(reduced<0 && t-within_since>=599)reduced=within_since-onset;
      } else within_since=-1;
    }
    const int measurement_after=last_app?last_app+900:1800;
    if(t<=measurement_after)continue;
    counts[ncount++]=residual;
    if(ncount!=600)continue;
    ncount=0;
    int64_t raw=std::accumulate(counts.begin(),counts.end(),int64_t(0));
    OtisIntegerCountDeadbandTightDeadbandInput bi={raw,true,true,1,engine.dac_epoch};
    OtisIntegerCountDeadbandTightDeadbandDecision bd={};assert(otis_integer_count_tight_deadband_observe(&band,&bi,&bd));
    if(engine.response_pending) {
      assert(t-last_app>=1500);assert(otis_adaptive_hybrid_engine_complete_response(&engine,true));
      continue;
    }
    auto projected=project(counts,p);
    if(projected.model)++model_selections;
    bool wait=false;
    if(p==1 && projected.count!=0)wait=!previous_available||(prev_fll>0)!=(projected.count>0)||prev_fll==0;
    const bool local_confirmation=(p==3)||(p==5&&!projected.model);
    if(local_confirmation && projected.localized && !local_pending) {wait=true;local_pending=true;}
    else if((p==3||p==5) && local_pending) {
      local_pending=false;
      if(projected.localized && !projected.model)projected=project(counts,2);
    }
    prev_fll=projected.count;previous_available=true;
    if(wait)continue;
    OtisAdaptiveHybridObservation o={};o.timestamp_ticks=uint64_t(t)*1000000+1;o.timestamp_s=t;
    o.capture_session=o.source_acceptance_epoch=o.phase_epoch=1;o.source_opening_accepted_boundary_ordinal=t-600;o.source_closing_accepted_boundary_ordinal=t;
    o.applied_code=code;o.dac_epoch=engine.dac_epoch;o.accumulated_edge_error_counts=projected.count;o.relative_phase_cycles=observed_phase;
    o.tight_inside=bd.state_after==OTIS_INTEGER_COUNT_DEADBAND_TIGHT_INSIDE;
    o.phase_valid=o.authority_valid=o.settled=o.cadence_eligible=o.metadata_qualified=true;o.selected_estimator_identity=1;
    OtisAdaptiveHybridDecision decision={};assert(otis_adaptive_hybrid_engine_decide(&engine,&o,&decision));assert(!engine.fail_static_reason);
    int delta=decision.requested_delta_codes;
    if(!delta)continue;
    assert(t-last_app>=1800);
    assert(std::abs(delta)<=21 && code+delta>=43008 && code+delta<=43776);
    if(t>=onset) {
      ++applications;movement+=std::abs(delta);max_step=std::max(max_step,std::abs(delta));large+=std::abs(delta)>=10;
      if(first_app<0)first_app=t-onset;
      if(c.drift && delta*c.drift<0 && first_correct<0)first_correct=t-onset;
      if(previous_direction && previous_direction!=(delta>0?1:-1))++reversals;
      previous_direction=delta>0?1:-1;
    }
    code+=delta;
    assert(otis_adaptive_hybrid_engine_note_application_and_first_consumer(&engine,&decision,code,engine.dac_epoch+1,true));
    last_app=t;previous_available=false;local_pending=false;
  }
  std::cout<<c.id<<","<<p<<","<<first_app<<","<<first_correct<<","<<max_step<<","<<large<<","<<applications<<","<<movement<<","<<reversals<<","<<iae<<","<<peak<<","<<reduced<<","<<model_selections<<","<<code<<"\n";
}
int main(int argc,char**argv) {
  assert(argc==2);
  if(std::string(argv[1])=="project") {project_records();return 0;}
  assert(std::string(argv[1])=="simulate");
  std::cout.precision(12);
  std::string line;
  while(std::getline(std::cin,line)) {
    std::istringstream in(line);Case c;
    in>>c.id>>c.family>>c.gain>>c.fraction>>c.position>>c.drift>>c.pulse>>c.width>>c.noise;assert(in);
    for(int p=0;p<6;++p)simulate(c,p);
  }
}
