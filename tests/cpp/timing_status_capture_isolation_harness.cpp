#include "otis_adaptive_hybrid_regulation_live.h"
#include "otis_dual_core_partition.h"
#include "otis_forwarded_clock_monitor.h"
#include "otis_pps_fifo_drain.h"
#include "otis_reference_acceptance_policy.generated.h"
#include "otis_oscillator_snapshot_estimator.h"
#include "otis_protocol.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <deque>
#include <map>
#include <string>

// Hardware ports and a deterministic cost model, not a measured RP2040 WCET.
struct Port {
  uint64_t ticks = 9994000;
  std::deque<uint32_t> fifo;
  uint32_t reads = 0;
  bool empty() const { return fifo.empty(); }
  bool rxstall() const { return false; }
  uint64_t now() const { return ticks; }
  uint32_t read() { ++reads; auto v=fifo.front();fifo.pop_front();return v; }
  void stop() { assert(false); }
} port;
uint64_t lower_bound = 0;
bool refresh_enabled = false;
bool edge_seen = false;
uint32_t sequence = 9;
OtisPpsHardwareSnapshot captured = {};
void otis_pps_snapshot_backend_observe_empty() {
  const auto reads = port.reads;
  if (refresh_enabled) otis_pps_fifo_observe_empty(port, lower_bound);
  assert(port.reads == reads); // no capture consumption or state service
}
uint32_t otis_monotonic_us32_now() { return uint32_t(port.ticks); }
uint32_t otis_transport_row_dropped() { return 0; }
void advance_field() {
  constexpr uint64_t arrival = 10000000;
  const auto end = port.ticks + 80;
  if (!edge_seen && end >= arrival) {
    port.ticks = arrival;
    port.fifo.push_back(UINT32_MAX - 90000000u);
    const auto drained = otis_pps_fifo_drain(port,1,sequence,128,8,true,lower_bound);
    assert(drained.count==1 && !drained.faults && !drained.timestamp_ambiguous);
    captured=drained.records[0];edge_seen=true;
  }
  port.ticks=end;
}
bool publish_with_elapsed(const OtisTelemetryMessage *m) {
  advance_field();
  return otis_dual_core_publish_telemetry(m);
}
struct Runtime { struct { uint32_t emitted_event_count=10; } capture; } runtime_state;
struct StatusContext {} dual_core_timing_status_context;
uint32_t dual_core_timing_telemetry_sequence=0;
uint32_t dual_core_last_timing_status_ms=0;
constexpr uint32_t kStatusPeriodMs=10000;
void otis_pps_snapshot_backend_get_stats(OtisPpsSnapshotBackendStats *s) { *s={}; }
void otis_forwarded_clock_monitor_get_stats(OtisForwardedClockMonitorStats *s) { *s={}; }
void publish_dual_core_timing_status(const char *,const char *,const char *,const char *,uint32_t);
void otis_count_observation_emit_status(Runtime *,StatusContext *) {
  // A bounded deterministic port for the count-status producer. The real
  // periodic sketch body, monitor publisher, active visitor and queue run.
  for (unsigned i=0;i<50;++i)
    publish_dual_core_timing_status("pps_gate","native_field","qualified",OTIS_SEVERITY_INFO,0);
}
#define otis_dual_core_publish_telemetry publish_with_elapsed
#include "publication.inc"
#undef otis_dual_core_publish_telemetry

void run(bool refresh) {
  otis_dual_core_partition_reset();
  assert(otis_adaptive_hybrid_regulation_live_begin(17,1,1));
  otis_adaptive_hybrid_regulation_live_service(2);
  OtisInstrumentWrite w={};assert(otis_dual_core_take_instrument_write(&w));
  assert(otis_adaptive_hybrid_regulation_live_application({w,100,w.code,true,true}));
  assert(otis_adaptive_hybrid_regulation_live_confirm_consumers(w.code,w.dac_epoch,100));
  OtisReferenceAcceptance selector(OTIS_REFERENCE_ACCEPTANCE_POLICY);
  OtisOscillatorSnapshotEstimator estimator={};
  for(unsigned i=0;i<=8;++i) {
    OtisReferenceAcceptanceObservation o={1,i,i,1000000u+i*1000000u,UINT32_MAX-i*10000000u,0,16,50};
    const auto selected=selector.observe(o);
    OtisRegulationSpanEstimate unused={};
    otis_oscillator_snapshot_estimator_ingest(&estimator,&selected,&unused);
  }
  port={};lower_bound=port.ticks;refresh_enabled=refresh;edge_seen=false;sequence=9;
  dual_core_last_timing_status_ms=0;
  publish_dual_core_timing_health(10000);
  assert(edge_seen && captured.sequence==9 && port.reads==1);
  const OtisReferenceAcceptanceObservation o={1,9,9,captured.service_ticks,captured.cumulative_down_counter,captured.status,16,captured.timestamp_uncertainty_ticks};
  const auto selected=selector.observe(o);
  OtisRegulationSpanEstimate estimate={};
  otis_oscillator_snapshot_estimator_ingest(&estimator,&selected,&estimate);
  if(refresh) {
    assert(captured.timestamp_uncertainty_ticks<=81);
    assert(selected.has_span && selected.counted_edges==10000000);
    assert(estimate.source_continuous); // first downstream frequency consumer
  } else {
    assert(captured.timestamp_uncertainty_ticks==6001);
    assert(selected.reason==OtisReferenceAcceptanceReason::ObservationAgeAmbiguous);
    assert(!selected.has_span && !estimate.source_continuous);
  }
  std::map<std::string,std::string> fields;
  OtisTelemetryMessage message={};
  while(otis_dual_core_take_telemetry(&message))
    if(std::strcmp(message.component,OTIS_ADAPTIVE_HYBRID_STATUS_COMPONENT)==0)
      fields[message.key]=message.value;
  assert(fields.at("snapshot_generation_begin")==fields.at("snapshot_generation_complete"));
  assert(fields.at("applied_code")=="43085" && fields.at("dac_epoch")=="1");
  assert(fields.at("fault")=="none");
}
int main() {run(false);run(true);}
