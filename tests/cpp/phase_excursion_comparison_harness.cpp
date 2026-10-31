// Zero-I/O arithmetic projections and fresh-state local response comparisons.
#include "otis_adaptive_hybrid_regulation.h"
#include "otis_regulation_transaction.h"
#include <cassert>
#include <cstdlib>
#include <iostream>
#include <string>
int main(int argc,char **argv) {
  assert(argc>=2);
  if(std::string(argv[1])=="response") {
    assert(argc==5);
    OtisRegulationResponseClassifier state={};
    const auto r=otis_regulation_classify_response(&state,std::stod(argv[2]),std::stod(argv[3]),std::stoi(argv[4]),true,true);
    std::cout<<"{\"classification\":"<<unsigned(r.classification)<<",\"reason\":\""<<r.reason<<"\"}\n";
    return 0;
  }
  assert(std::string(argv[1])=="decision" && argc==15);
  OtisAdaptiveHybridObservation o={};
  o.timestamp_ticks=std::stoull(argv[2]);o.timestamp_s=o.timestamp_ticks/1000000;
  o.capture_session=std::stoull(argv[3]);o.source_acceptance_epoch=std::stoull(argv[4]);
  o.source_opening_accepted_boundary_ordinal=std::stoull(argv[5]);o.source_closing_accepted_boundary_ordinal=std::stoull(argv[6]);
  o.dac_epoch=std::stoull(argv[7]);o.applied_code=std::stoi(argv[8]);
  o.accumulated_edge_error_counts=std::stoll(argv[9]);o.phase_epoch=std::stoull(argv[10]);o.relative_phase_cycles=std::stoll(argv[11]);
  o.tight_inside=std::stoi(argv[12]);o.phase_valid=true;o.authority_valid=o.settled=o.cadence_eligible=o.metadata_qualified=true;
  o.selected_estimator_identity=std::stoull(argv[14]);
  auto policy=otis_adaptive_hybrid_default_policy();policy.maximum_applications=policy.maximum_cumulative_movement_codes=0;
  OtisAdaptiveHybridEngine engine={};assert(otis_adaptive_hybrid_engine_init(&engine,&policy,o.applied_code,o.dac_epoch));
  assert(otis_adaptive_hybrid_engine_bind_exact_setup_application(&engine,std::stoull(argv[13])));
  OtisAdaptiveHybridDecision decision={};assert(otis_adaptive_hybrid_engine_decide(&engine,&o,&decision));
  std::cout<<"{\"delta_codes\":"<<decision.requested_delta_codes<<",\"reason\":\""<<decision.reason<<"\"}\n";
}
