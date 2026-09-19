// Production .ino row traversal, transport dispatch and Core 0 loop are
// extracted by the Python test. Only hardware/service dependencies are seams.
#include <algorithm>
#include <cassert>
#include <cstring>
#include <limits>
#include <string>
#include <vector>
#include "otis_config.h"
#include "otis_dual_core_partition.h"
#include "otis_emit.h"
#include "otis_frequency_regulation_live.h"
#include "otis_gnss_receiver.h"
#include "otis_phase_preview_live.h"
#include "otis_protocol.h"
#include "otis_runtime_state.h"
#include "otis_serial_frame_arbiter.h"
#include "otis_serial_command.h"
#include "otis_status_rows.h"
#include "otis_transport_liveness.h"

static uint32_t now_ms = 10000u;
static std::string wire;
static size_t available = 192u;
static unsigned writes, command_polls, observation_polls, input_only_polls;
static unsigned abort_requests, discard_polls, metadata_polls, gnss_polls;
static unsigned queue_gets, receiver_gets, phase_gets, frequency_gets;
static bool carrier = true, abort_input = false, diagnostic_reply = false;
static bool evidence_pending = false;
static size_t evidence_sent = 0;
static OtisDualCoreQueueStats source_queues{};
static OtisGnssReceiverSnapshot source_receiver{};
static OtisPhasePreviewLiveStatus source_phase{};
static OtisFrequencyRegulationStatus source_frequency{};
OtisRuntimeState runtime_state{};
OtisStatusFrame periodic_status_frame{};
uint16_t periodic_status_row = 0u;
bool periodic_status_active = false;
bool periodic_status_last_row = false;
uint32_t periodic_status_incomplete_generations = 0u;
uint32_t dual_core_pre_carrier_records_discarded = 0u;
uint32_t dual_core_periodic_service_deferred = 0u;
constexpr uint32_t kStatusPeriodMs = OTIS_PPS_GATE_STATUS_PERIOD_MS;
constexpr uint32_t kDualCoreTimingTracePeriodMs = 250u;
OtisSerialFrameArbiter dual_core_serial_frame_arbiter{};
OtisTransportLiveness dual_core_transport_liveness{};
bool dual_core_transport_abort_queued = false;

uint32_t millis() { return now_ms; }
uint32_t otis_monotonic_us32_now() { return now_ms * 1000u; }
bool otis_transport_ready() { return carrier; }
uint64_t otis_transport_written_bytes() { return wire.size(); }
size_t otis_transport_write_char(char c) { wire += c; return 1; }
size_t otis_transport_write_cstr(const char *s) { wire += s; return std::strlen(s); }
size_t otis_transport_write_uint32(uint32_t value) {
  const auto text = std::to_string(value); wire += text; return text.size();
}
void otis_transport_flush_if_needed() {}
void otis_status_emit(OtisStatusEmitContext *context, const char *component,
    const char *key, const char *value, const char *severity, uint32_t flags) {
  assert(context);
  if (context->sink) context->sink(context->sink_context, component, key, value, severity, flags);
  else otis_emit_health((*context->status_seq)++, otis_monotonic_us32_now(),
    OTIS_DOMAIN_RP2040_MONOTONIC_US32, component, key, value, severity, flags);
}
size_t otis_transport_try_write_canonical(const uint8_t *data, size_t length) {
  ++writes;
  const size_t accepted = std::min({length, available, size_t(192)});
  wire.append(reinterpret_cast<const char *>(data), accepted);
  return accepted;
}
void otis_dual_core_get_stats(OtisDualCoreQueueStats *v) { ++queue_gets; *v = source_queues; }
void otis_gnss_receiver_get_snapshot(uint32_t, OtisGnssReceiverSnapshot *v) { ++receiver_gets; *v = source_receiver; }
void otis_phase_preview_live_get_status(OtisPhasePreviewLiveStatus *v) { ++phase_gets; *v = source_phase; }
void otis_frequency_regulation_live_get_status(OtisFrequencyRegulationStatus *v) { ++frequency_gets; *v = source_frequency; }
const char *otis_service_message_kind_name(OtisServiceMessageKind) { return "fixture_service"; }
const char *otis_timing_progress_phase_name(OtisTimingProgressPhase) { return "fixture_timing"; }
const char *otis_partition_fault_name(OtisPartitionFault) { return "fixture_fault"; }
void otis_gnss_receiver_service(uint32_t) { ++gnss_polls; }
void publish_dual_core_service_metadata(uint32_t) { ++metadata_polls; }
void otis_memory_budget_note_current_core() {}
void emit_boot_records_if_serial_ready() {}
void emit_protocol_banner_if_serial_ready() {}
void emit_run_mode_status_if_ready() {}
void emit_resource_ownership_status() {}
void service_environment_sensors() {}
void abandon_periodic_status();
void abandon_dual_core_serial_frames_on_carrier_loss() { abandon_periodic_status(); }
void discard_dual_core_outputs_before_first_carrier() { ++discard_polls; }
void discard_dual_core_outputs_after_transport_fault() { ++discard_polls; }
void otis_dual_core_latch_fault(OtisPartitionFault fault) { assert(fault == OtisPartitionFault::TransportObstructed); }
bool queue_dual_core_active_control(OtisRunControlKind kind) {
  assert(kind == OtisRunControlKind::Abort); ++abort_requests; return true;
}
void service_serial_commands(bool output_allowed = true) {
  ++command_polls;
  if (!output_allowed) ++input_only_polls;
  if (abort_input) { ++abort_requests; abort_input = false; }
  if (output_allowed && diagnostic_reply) {
    otis_emit_health(runtime_state.sequences.status_seq++, otis_monotonic_us32_now(),
      OTIS_DOMAIN_RP2040_MONOTONIC_US32, "fixture", "reply", "accepted", "INFO", 0);
    diagnostic_reply = false;
  }
}
void emit_status_u32(const char *component, const char *key, uint32_t value,
    const char *severity, uint32_t flags) {
  const auto text = std::to_string(value);
  otis_emit_health(runtime_state.sequences.status_seq++, otis_monotonic_us32_now(),
    OTIS_DOMAIN_RP2040_MONOTONIC_US32, component, key, text.c_str(), severity, flags);
}
void service_dual_core_outputs() { ++observation_polls; wire += "OBS\r\n"; }
bool dual_core_evidence_transport_pending() { return evidence_pending; }
bool dual_core_evidence_transport_busy() { return evidence_pending; }
void service_dual_core_evidence_transport() {
  constexpr char record[] = "EVIDENCE\r\n";
  evidence_sent += otis_transport_try_write_canonical(
    reinterpret_cast<const uint8_t *>(record) + evidence_sent, sizeof(record) - 1 - evidence_sent);
  if (evidence_sent == sizeof(record) - 1) { evidence_sent = 0; evidence_pending = false; }
}
bool otis_frequency_regulation_live_transport_pending() { return false; }
bool otis_frequency_regulation_live_transport_busy() { return false; }
void otis_frequency_regulation_live_service_transport() { assert(false); }
bool otis_phase_preview_transport_busy() { return false; }
bool otis_phase_preview_transport_frame_active() { return false; }
void otis_phase_preview_transport_service() { assert(false); }

// Definition of the exact view precedes global allocation; extracted function
// bodies refer to this external declaration.
struct OtisPeriodicStatusView;
extern OtisPeriodicStatusView periodic_status_view;
#include "periodic_production.inc"
OtisPeriodicStatusView periodic_status_view{};

static std::vector<std::vector<std::string>> status_records(const std::string &stream) {
  std::vector<std::vector<std::string>> result;
  size_t start = 0;
  while (start < stream.size()) {
    const size_t end = stream.find("\r\n", start);
    assert(end != std::string::npos);  // No prefix or interleaved row is admitted.
    const std::string row = stream.substr(start, end - start);
    start = end + 2;
    if (row == "OBS" || row == "EVIDENCE") continue;
    assert(row.rfind("STS,", 0) == 0);
    std::vector<std::string> fields;
    size_t field = 0, comma;
    while ((comma = row.find(',', field)) != std::string::npos) {
      fields.push_back(row.substr(field, comma - field)); field = comma + 1;
    }
    fields.push_back(row.substr(field));
    assert(fields.size() == 10);
    result.push_back(fields);
  }
  return result;
}

static void reset() {
  now_ms = 10000;
  wire.clear(); available = 192; writes = command_polls = observation_polls = input_only_polls = 0;
  abort_requests = discard_polls = metadata_polls = gnss_polls = 0;
  queue_gets = receiver_gets = phase_gets = frequency_gets = 0;
  carrier = true; abort_input = diagnostic_reply = evidence_pending = false; evidence_sent = 0;
  source_queues = {}; source_receiver = {}; source_phase = {}; source_frequency = {};
  runtime_state = {}; periodic_status_view = {}; periodic_status_frame = {};
  periodic_status_row = 0; periodic_status_active = false; periodic_status_last_row = false; periodic_status_incomplete_generations = 0;
  dual_core_transport_abort_queued = false;
  otis_serial_frame_arbiter_reset(&dual_core_serial_frame_arbiter);
  otis_transport_liveness_reset(&dual_core_transport_liveness, now_ms, 0);
}

static void encoding_parity() {
  const char *texts[] = {"", "plain", "%,\"\r\n", "\xC2\xB5", nullptr};
  for (const char *value : texts) {
    wire.clear();
    otis_emit_health(UINT32_MAX, UINT32_MAX, OTIS_DOMAIN_RP2040_MONOTONIC_US32,
      "comp%,\"\r\n", "key", value, "WARN", UINT32_MAX);
    OtisStatusFrame frame{};
    OtisStatusRows rows(&frame, 0, UINT32_MAX, UINT32_MAX);
    rows.text("comp%,\"\r\n", "key", value, "WARN", UINT32_MAX);
    assert(rows.selected() && rows.valid());
    assert(std::string(frame.data, frame.length) == wire);
  }
  wire.clear();
  OtisStatusFrame frame{};
  OtisStatusRows numeric(&frame, 1, 123, 456);
  numeric.u32("fixture", "unselected", 42, "INFO", 0);
  numeric.u64("fixture", "maximum", UINT64_MAX, "INFO", 0);
  otis_emit_health(123, 456, OTIS_DOMAIN_RP2040_MONOTONIC_US32,
    "fixture", "maximum", "18446744073709551615", "INFO", 0);
  assert(numeric.selected() && numeric.valid());
  assert(std::string(frame.data, frame.length) == wire);
  const std::string oversized(200, '%');
  OtisStatusRows oversized_rows(&frame, 0, 1, 2);
  oversized_rows.text("fixture", "oversized", oversized.c_str(), "WARN", 0);
  assert(oversized_rows.selected() && !oversized_rows.valid());
  assert(frame.length == 0 && frame.sent == 0);
}

static void repeated_reports() {
  reset();
  unsigned total_rows = 0;
  uint32_t prior_status_seq = 0;
  uint32_t prior_status_ticks = 0;
  bool first = true;
  for (unsigned generation = 1; generation <= 3; ++generation) {
    now_ms = generation * kStatusPeriodMs;
    source_queues.observation_depth = 17 * generation;
    source_queues.service_fault.valid = generation == 2;
    source_queues.service_activity.last_published_ticks = UINT64_MAX;
    source_receiver.satellites = 4 + generation;
    source_receiver.receiver_identity_available = true;
    std::strcpy(source_receiver.receiver_release, "receiver%,\"\r\n");
    source_phase.published_records = 29 * generation;
    source_frequency.queue_high_water = generation;
    const size_t start = wire.size();
    const unsigned before_obs = observation_polls;
    const unsigned before_commands = command_polls;
    loop();  // Freeze only; ownership may go to another producer first.
    assert(periodic_status_active);
    assert(queue_gets == generation && receiver_gets == generation &&
           phase_gets == generation && frequency_gets == generation);
    source_queues.observation_depth = 999;
    source_receiver.satellites = 99;
    std::strcpy(source_receiver.receiver_release, "changed after freeze");
    source_phase.published_records = 999;
    source_frequency.queue_high_water = 99;
    evidence_pending = true;
    diagnostic_reply = true;
    unsigned iterations = 0;
    while (periodic_status_active || periodic_status_frame.length) {
      const unsigned before_writes = writes;
      if (iterations % 7 == 0) { abort_input = true; }
      loop();
      assert(writes - before_writes <= 1);  // One bounded canonical attempt.
      assert(++iterations < 2000);
      ++now_ms;
    }
    const auto records = status_records(wire.substr(start));
    unsigned row_count = 0;
    bool begun = false, ended = false, snapshot = false, queues = false, receiver = false, phase = false, frequency = false;
    for (const auto &row : records) {
      const uint32_t sequence = std::stoul(row[2]);
      assert(first || sequence == prior_status_seq + 1);
      const uint32_t ticks = std::stoul(row[3]);
      assert(first || ticks >= prior_status_ticks);
      prior_status_ticks = ticks;
      first = false; prior_status_seq = sequence;
      if (row[5] == "fixture") continue;
      ++row_count;
      if (row[5] == "periodic_status" && row[6] == "snapshot_ticks") {
        snapshot = true; assert(row[7] == std::to_string(generation * kStatusPeriodMs * 1000u));
      }
      if (row[5] == "periodic_status" && row[6] == "generation_begin") {
        assert(!begun); begun = true; assert(row[7] == std::to_string(generation));
      }
      if (row[5] == "periodic_status" && row[6] == "generation_end") {
        assert(begun && !ended); ended = true; assert(row[7] == std::to_string(generation));
      }
      if (row[5] == "dual_core" && row[6] == "observation_depth") { queues = true; assert(row[7] == std::to_string(17 * generation)); }
      if (row[5] == "gnss_receiver" && row[6] == "receiver_identity") assert(row[7] == "receiver%25%2C%22%0D%0A");
      if (row[5] == "gnss_receiver" && row[6] == "satellite_count") { receiver = true; assert(row[7] == std::to_string(4 + generation)); }
      if (row[5] == "phase_frequency_estimate" && row[6] == "published_records") { phase = true; assert(row[7] == std::to_string(29 * generation)); }
      if (row[5] == "frequency_regulation" && row[6] == "queue_high_water") { frequency = true; assert(row[7] == std::to_string(generation)); }
    }
    assert(begun && ended && snapshot && queues && receiver && phase && frequency);
    assert(row_count > 100);
    assert(observation_polls - before_obs >= row_count);
    assert(command_polls - before_commands >= row_count);
    assert(queue_gets == generation && receiver_gets == generation && phase_gets == generation && frequency_gets == generation);
    total_rows += row_count;
  }
  assert(total_rows > 300 && abort_requests > 0);
  assert(discard_polls == 0);
}

static void partial_row_completion() {
  reset();
  loop();
  available = 7;
  loop();
  const auto prefix = wire;
  const unsigned before_observations = observation_polls;
  evidence_pending = diagnostic_reply = true;
  available = 0;
  ++now_ms;
  loop();
  assert(wire == prefix && observation_polls == before_observations);
  available = 17;
  unsigned iterations = 0;
  while (periodic_status_frame.length) {
    ++now_ms;
    const unsigned before_writes = writes;
    loop();
    assert(writes == before_writes + 1);
    assert(++iterations < 40);
  }
  assert(observation_polls == before_observations + 1);
  assert(!diagnostic_reply && evidence_pending);
  const auto records = status_records(wire);
  assert(records.size() == 2);
  assert(records[0][5] == "periodic_status" && records[0][6] == "generation_begin");
  assert(records[1][5] == "fixture" && records[1][6] == "reply");
  assert(std::stoul(records[1][2]) == std::stoul(records[0][2]) + 1);
  assert(std::stoul(records[1][3]) >= std::stoul(records[0][3]));
  assert(!otis_transport_liveness_faulted(&dual_core_transport_liveness));
}

static void generation_abandonment() {
 for (const auto kind : {OtisSerialCommandKind::ConfigQuery, OtisSerialCommandKind::DualCoreQuery}) {
  reset();
  loop();
  loop();
  assert(periodic_status_active && periodic_status_frame.length == 0);
  periodic_before_query({OtisSerialCommandKind::ActiveAbort, true, nullptr});
  assert(periodic_status_active && periodic_status_incomplete_generations == 0);
  periodic_before_query({kind, true, nullptr});
  assert(periodic_status_incomplete_generations == 1);
  assert(!periodic_status_active && periodic_status_frame.length == 0);
  // Repeated cleanup cannot count one abandoned generation more than once.
  abandon_periodic_status();
  assert(periodic_status_incomplete_generations == 1);
  now_ms += kStatusPeriodMs;
  loop();
  unsigned iterations = 0;
  while (periodic_status_active) { ++now_ms; loop(); assert(++iterations < 1000); }
  unsigned begin = 0, end = 0, cancelled = 0;
  for (const auto &row : status_records(wire)) {
    if (row[5] != "periodic_status") continue;
    if (row[6] == "generation_begin") { assert(row[7] == std::to_string(++begin)); }
    if (row[6] == "generation_cancel") { ++cancelled; assert(row[7] == "1"); }
    if (row[6] == "generation_end") { ++end; assert(row[7] == "2"); }
    if (row[6] == "incomplete_generations") assert(row[7] == "1");
  }
  assert(begin == 2 && end == 1 && cancelled == 1);
  assert(queue_gets == 2 && receiver_gets == 2 && phase_gets == 2 && frequency_gets == 2);
 }
}

static void partial_row_obstruction() {
  reset();
  loop();  // Generation frozen.
  available = 7;
  loop();  // Only a row prefix admitted, ownership retained.
  assert(periodic_status_frame.sent == 7);
  assert(otis_serial_frame_arbiter_owner(&dual_core_serial_frame_arbiter) == OtisSerialFrameOwner::PeriodicStatus);
  const auto prefix = wire;
  const unsigned before_observations = observation_polls;
  const uint32_t obstruction_start = dual_core_transport_liveness.obstruction_started_ms;
  available = 0;
  evidence_pending = true;
  diagnostic_reply = true;
  abort_input = true;
  for (unsigned i = 0; i != 5; ++i) {
    now_ms = obstruction_start + 100 * (i + 1);
    const unsigned before_writes = writes;
    loop();
    assert(writes == before_writes + 1);
    assert(wire == prefix && observation_polls == before_observations);
    assert(otis_serial_frame_arbiter_owner(&dual_core_serial_frame_arbiter) == OtisSerialFrameOwner::PeriodicStatus);
  }
  assert(abort_requests == 1 && input_only_polls >= 5);
  // Sparse progress cannot renew the 2-second total pending-frame horizon.
  available = 1;
  now_ms = obstruction_start + OTIS_MAXIMUM_SUPPORTED_TX_OBSTRUCTION_MS - 1;
  loop();
  assert(wire.size() == prefix.size() + 1);
  const unsigned before_writes = writes;
  now_ms = obstruction_start + OTIS_MAXIMUM_SUPPORTED_TX_OBSTRUCTION_MS;
  available = 192;
  loop();
  assert(writes == before_writes);
  assert(otis_transport_liveness_faulted(&dual_core_transport_liveness));
  assert(discard_polls == 1 && abort_requests == 2);
  assert(diagnostic_reply && evidence_pending);  // Neither interleaved output.
  loop();
  assert(writes == before_writes && discard_polls == 2 && abort_requests == 2);
}

int main() {
  encoding_parity();
  repeated_reports();
  partial_row_completion();
  generation_abandonment();
  partial_row_obstruction();
}
