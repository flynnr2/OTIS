#include "otis_adaptive_hybrid_regulation_live.h"
#include "otis_dual_core_partition.h"
#include "otis_forwarded_clock_monitor.h"
#include "otis_pps_fifo_drain.h"
#include "otis_count_observation.h"
#include "otis_timebase.h"
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
bool model_elapsed = false;
unsigned modeled_fields = 0;
unsigned int mock_core_num = 1;
uint32_t sequence = 9;
OtisPpsHardwareSnapshot captured = {};
void otis_pps_snapshot_backend_observe_empty() {
  const auto reads = port.reads;
  if (refresh_enabled) otis_pps_fifo_observe_empty(port, lower_bound);
  assert(port.reads == reads); // no capture consumption or state service
}
uint32_t micros() { return uint32_t(port.ticks); }
uint32_t millis() { return uint32_t(port.ticks / 1000); }
uint64_t time_us_64() { return port.ticks; }
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
  if (model_elapsed) { advance_field(); ++modeled_fields; }
  return otis_dual_core_publish_telemetry(m);
}
OtisRuntimeState runtime_state = {};
OtisStatusEmitContext dual_core_timing_status_context = {};
uint32_t dual_core_timing_telemetry_sequence=0;
uint32_t dual_core_last_timing_status_ms=0;
constexpr uint32_t kStatusPeriodMs=10000;
bool otis_pps_snapshot_backend_begin() { return true; }
void otis_pps_snapshot_backend_get_stats(OtisPpsSnapshotBackendStats *s) {
  *s={};s->initialized=s->running=true;s->session=1;s->ring_capacity=128;
}
void otis_forwarded_clock_monitor_get_stats(OtisForwardedClockMonitorStats *s) { *s={}; }
void publish_dual_core_timing_status(const char *,const char *,const char *,const char *,uint32_t);
void otis_emit_health(uint32_t, uint64_t, const char *, const char *, const char *,
                       const char *, const char *, uint32_t) { assert(false); }
void otis_gnss_receiver_service(uint32_t) { assert(false); }
void otis_emit_count_observation(uint32_t, uint32_t, uint64_t, uint64_t,
    const char *, uint64_t, const char *, const char *, uint32_t) { assert(false); }
#define otis_dual_core_publish_telemetry publish_with_elapsed
#include "publication.inc"
#undef otis_dual_core_publish_telemetry

unsigned run(bool refresh, uint64_t offset = 3000, bool verbose = false) {
  otis_dual_core_partition_reset();
  model_elapsed = false;
  otis_dual_core_set_timing_owner_active(true);
  otis_status_emit_init_with_sink(&dual_core_timing_status_context, nullptr,
                                  publish_dual_core_timing_status_sink);
  const OtisCountObservationConfig config = {1000000, 0, 0, "native"};
  assert(otis_count_observation_begin(&runtime_state,
                                    &dual_core_timing_status_context, &config));
  // Initial count configuration is outside the collision stimulus.
  OtisTelemetryMessage discarded = {};
  while (otis_dual_core_take_telemetry(&discarded)) {}
  // Exercise the populated periodic capsule, including fields conditional on
  // a previous raw boundary, rather than only the startup/unavailable shape.
  for (unsigned i = 0; i < 2; ++i) {
    OtisPpsCountBoundaryObservation boundary = {};
    boundary.session = 1;
    boundary.sequence = boundary.reference_sequence = 7+i;
    boundary.pps_timestamp_ticks = 8000000+i*1000000;
    boundary.cumulative_down_counter = UINT32_MAX-(7+i)*10000000;
    boundary.capture_flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
    port.ticks = boundary.pps_timestamp_ticks;
    otis_count_observation_on_pps_boundary(&runtime_state,
        &dual_core_timing_status_context, &config, &boundary);
    otis_count_observation_emit_pending_boundary_status();
    while (otis_dual_core_take_telemetry(&discarded)) {}
  }
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
  OtisAcceptedReferenceStatus accepted = {};
  accepted.state = "tracking";
  accepted.last_loss_reason = "none";
  accepted.capture_session = 1;
  accepted.acceptance_epoch = 1;
  accepted.anchor_current = true;
  accepted.tracking = true;
  otis_count_observation_update_reference_acceptance(accepted);
  port={};port.ticks=10000000-offset;lower_bound=port.ticks;
  refresh_enabled=refresh;edge_seen=false;sequence=9;model_elapsed=true;
  modeled_fields=0;
  dual_core_last_timing_status_ms=0;
  publish_dual_core_timing_health(10000);
  assert(edge_seen && captured.sequence==9 && port.reads==1);
  const OtisReferenceAcceptanceObservation o={1,9,9,captured.service_ticks,captured.cumulative_down_counter,captured.status,16,captured.timestamp_uncertainty_ticks};
  const auto selected=selector.observe(o);
  OtisRegulationSpanEstimate estimate={};
  otis_oscillator_snapshot_estimator_ingest(&estimator,&selected,&estimate);
  if (verbose) {
    std::printf("refresh=%u uncertainty_us=%u\n", refresh,
                captured.timestamp_uncertainty_ticks);
    std::fflush(stdout);
  }
  if(refresh) {
    assert(captured.timestamp_uncertainty_ticks<=81);
    assert(selected.has_span && selected.counted_edges==10000000);
    assert(estimate.source_continuous); // first downstream frequency consumer
  } else {
    assert(captured.timestamp_uncertainty_ticks==offset+1);
    assert(selected.reason==OtisReferenceAcceptanceReason::ObservationAgeAmbiguous);
    assert(!selected.has_span && !estimate.source_continuous);
  }
  std::map<std::string,std::string> fields;
  OtisTelemetryMessage message={};
  unsigned count_fields = 0;
  bool have_boundary_sequence = false;
  while(otis_dual_core_take_telemetry(&message))
    if(std::strcmp(message.component,OTIS_ADAPTIVE_HYBRID_STATUS_COMPONENT)==0) {
      fields[message.key]=message.value;
    } else if (std::strcmp(message.component,"pps_gate")==0) {
      ++count_fields;
      if (std::strcmp(message.key,"boundary_sequence")==0)
        have_boundary_sequence = true;
    }
  assert(count_fields > 40); // Actual count module, not a publisher substitute.
  assert(have_boundary_sequence);
  assert(fields.at("snapshot_generation_begin")==fields.at("snapshot_generation_complete"));
  assert(fields.at("applied_code")=="43085" && fields.at("dac_epoch")=="1");
  assert(fields.at("fault")=="none");
  if (verbose)
    std::printf("refresh=%u uncertainty_us=%u count_fields=%u total_fields=%u\n",
                refresh, captured.timestamp_uncertainty_ticks, count_fields,
                modeled_fields);
  return modeled_fields;
}
int main() {
  run(false, 3000, true);
  const auto fields = run(true, 3000, true);
  // Force a PPS in the beginning, middle and end of every actual field's
  // modeled work. This includes the formerly bypassing count-status fields.
  for (unsigned field = 0; field < fields; ++field)
    for (const auto phase : {1u, 40u, 79u})
      assert(run(true, field*80 + phase) == fields);
  std::printf("phase_sweep_cases=%u maximum_qualified_uncertainty_us=81\n",
              fields*3);
}
