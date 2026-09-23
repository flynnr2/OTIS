#include <Arduino.h>
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pico/time.h>

#include "otis_config.h"

#include "OtisBootConfig.h"
#include "otis_board.h"
#include "otis_boot_capabilities.h"
#include "otis_boot_diag.h"
#include "otis_count_observation.h"
#include "otis_reference_acceptance_live.h"
#include "otis_reference_acceptance_format.h"
#include "otis_reference_acceptance_policy.generated.h"
#include "otis_adaptive_hybrid_regulation_live.h"
#include "otis_instrument_executor.h"
#include <pico/rand.h>
#include "otis_frequency_regulation_live.h"
#include "otis_phase_preview_live.h"
#include "otis_phase_preview_transport.h"
#include "otis_dac_ad5693r.h"
#include "otis_dual_core_partition.h"
#include "otis_dual_core_receiver_gate.h"
#include "otis_emit.h"
#include "otis_env_sensors.h"
#include "otis_forwarded_clock_output.h"
#include "otis_forwarded_clock_monitor.h"
#include "otis_gnss_receiver.h"
#include "otis_memory_budget.h"
#include "otis_pps_count_boundary.h"
#include "otis_pps_snapshot_backend.h"
#include "otis_reference_record.h"
#include "otis_protocol.h"
#include "otis_resource_registry.h"
#include "otis_runtime_state.h"
#include "otis_serial_frame_arbiter.h"
#include "otis_service_latency_live.h"
#include "otis_serial_command.h"
#include "otis_status_emit.h"
#include "otis_timebase.h"
#include "otis_monotonic_us_extension.h"
#include "otis_transport_serial.h"

// Arduino-Pico otherwise splits one 8 KiB stack between both cores.  The
// timing/estimator path has bounded local formatting buffers, so give Core 1
// its own full 8 KiB stack as supported by the pinned core.
bool core1_separate_stack = true;

namespace {

constexpr uint32_t kStatusPeriodMs = OTIS_PPS_GATE_STATUS_PERIOD_MS;
constexpr uint32_t kTcxoGatePeriodUs = OTIS_TCXO_GATE_PERIOD_US;
constexpr uint32_t kCountStartupInhibitMs = OTIS_COUNT_STARTUP_INHIBIT_MS;
constexpr uint32_t kCountControlReadyCleanWindows =
    OTIS_COUNT_CONTROL_READY_CLEAN_WINDOWS;

OtisRuntimeState runtime_state;
OtisReferenceAcceptanceLive reference_acceptance(OTIS_REFERENCE_ACCEPTANCE_POLICY);
OtisStatusEmitContext status_emit_context;
OtisSerialFrameCollector serial_command_collector;
bool deferred_serial_command_ready = false;
char deferred_serial_command[OTIS_SERIAL_COMMAND_BUFFER_SIZE] = {};
OtisSerialFrameEvent deferred_serial_error = OtisSerialFrameEvent::None;
bool deferred_serial_invalid = false;
OtisBootCapabilityTracker boot_capabilities;
bool resource_ownership_status_emitted = false;
bool boot_capability_status_emitted = false;
bool run_mode_status_emitted = false;
bool transport_started = false;
bool config_query_provenance_emitted = false;



constexpr uint32_t kDualCoreTimingTracePeriodMs = 250u;
bool dual_core_service_boot_ready = false;
bool dual_core_timing_boot_complete = false;
bool dual_core_timing_boot_in_progress = false;
bool dual_core_timing_loop_started = false;
constexpr uint32_t kDualCoreBootHandshakeTimeoutMs = 10000u;
uint32_t dual_core_service_sequence = 0u;
uint32_t dual_core_timing_telemetry_sequence = 0u;
uint32_t dual_core_diagnostic_snapshot_generation = 0u;
uint32_t dual_core_last_metadata_ms = 0u;
uint32_t dual_core_last_timing_status_ms = 0u;
bool dual_core_timing_trace_started = false;
uint32_t dual_core_last_timing_trace_ms = 0u;
OtisRegulationStaticCodeState dual_core_static_code = {};
OtisReceiverQualificationMessage dual_core_receiver = {};
// Association-loss publication runs on the bounded timing-core stack. Keep
// its full evidence-frame formatter in static storage; Core 1 is the only
// producer and the publication is synchronous.
OtisEvidenceFrameMessage dual_core_reference_evidence_scratch = {};
OtisEvidenceFrameMessage dual_core_evidence_transport = {};
uint16_t dual_core_evidence_transport_sent = 0u;
bool dual_core_evidence_transport_active = false;
OtisSerialFrameArbiter dual_core_serial_frame_arbiter = {
    OtisSerialFrameOwner::None,
    static_cast<uint8_t>(OtisSerialFrameOwner::DualCoreEvidence),
};
uint32_t dual_core_pre_carrier_records_discarded = 0u;
uint32_t dual_core_carrier_loss_frames_abandoned = 0u;
uint32_t dual_core_periodic_service_deferred = 0u;
OtisStatusEmitContext dual_core_timing_status_context = {};

class DiagnosticRows final : public Stream {
 public:
  int available() override { return 0; }
  int read() override { return -1; }
  int peek() override { return -1; }
  void flush() override {}
  size_t write(uint8_t byte) override { otis_transport_write_char(char(byte)); return 1; }
};
DiagnosticRows diagnostic_rows;
uint16_t core0_description_cursor=0;
uint32_t core0_description_generation=1;
bool core0_description_pending=true;
uint8_t core0_periodic_cursor=0;
bool core0_periodic_pending=false;
uint8_t resource_status_cursor=0;

bool queue_dual_core_active_control(OtisRunControlKind kind, uint32_t nonce = 0u) {
  OtisServiceMessage control = {};
  control.kind = OtisServiceMessageKind::RunControl;
  control.run_control.sequence = dual_core_service_sequence++;
  control.run_control.published_ticks = time_us_64();
  control.run_control.kind = kind;
  control.run_control.nonce = nonce;
  return otis_dual_core_publish_service(&control);
}

bool queue_instrument_mode(const OtisParsedSerialCommand &command) {
  uint64_t values[5] = {};
  if (!command.arguments_valid || !otis_serial_command_parse_decimal_u64_fields(command.text_argument, values, 5) ||
      !values[0] || !values[1] || values[1]>UINT32_MAX || values[2]>3 || values[3]>65535 || values[4]>604800) return false;
  OtisServiceMessage control = {};
  control.kind = OtisServiceMessageKind::RunControl;
  control.run_control.kind = OtisRunControlKind::Mode;
  control.run_control.instrument_command = {values[0],uint32_t(values[1]),static_cast<OtisInstrumentMode>(values[2]),uint16_t(values[3]),uint32_t(values[4])};
  return otis_dual_core_publish_service(&control);
}

void enter_boot_phase(BootPhase next_phase) {
  runtime_state.boot.phase = next_phase;
}

void begin_boot_phase(BootPhase next_phase) {
  enter_boot_phase(next_phase);
  otis_boot_capability_begin_phase(&boot_capabilities, next_phase);
}

void complete_boot_phase(BootPhase completed_phase) {
  otis_boot_capability_complete_phase(&boot_capabilities, completed_phase);
  otisBootBreadcrumbCompletePhase(completed_phase);
}

OtisBootCapabilityRequirement capability_requirement(
    OtisBootCapability capability) {
  const OtisBootCapabilityEntry *entry =
      otis_boot_capability_entry(&boot_capabilities, capability);
  return entry == nullptr ? OtisBootCapabilityRequirement::Disabled
                          : entry->requirement;
}

void record_capability_result(OtisBootCapability capability, bool ready) {
  otis_boot_capability_record(
      &boot_capabilities, capability,
      otis_boot_capability_result(capability_requirement(capability), ready));
}

bool capability_ready(OtisBootCapability capability) {
  const OtisBootCapabilityEntry *entry =
      otis_boot_capability_entry(&boot_capabilities, capability);
  return entry != nullptr && entry->reported &&
         entry->outcome == OtisBootCapabilityOutcome::Ready;
}

void configure_selected_capabilities(void) {
  otis_boot_capability_tracker_init(&boot_capabilities);
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::ResourceRegistry,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities, OtisBootCapability::Timebase,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::RingBuffers,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities, OtisBootCapability::Transport,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::HostConnection,
                              OtisBootCapabilityRequirement::Optional);

  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::PpsCapture,
                              OtisBootCapabilityRequirement::Required);

  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::OscillatorCount,
                              OtisBootCapabilityRequirement::Required);

  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::ForwardedOutput,
                              OtisBootCapabilityRequirement::Required);

  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::ForwardedMonitor,
                              OtisBootCapabilityRequirement::Optional);


  otis_boot_capability_select(&boot_capabilities, OtisBootCapability::Dac,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities, OtisBootCapability::Sensors,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::GnssReceiver,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::FrequencyRegulation,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::PhaseFrequencyEstimate,
                              OtisBootCapabilityRequirement::Required);
}

void update_adaptive_hybrid_regulation_health();
void emit_selected_capability_status();
void emit_resource_ownership_status();
void emit_protocol_banner_if_serial_ready();

void emit_boot_records_if_serial_ready(void) {
  if (runtime_state.boot.summary_emitted || !otis_transport_ready()) {
    return;
  }

  emitOtisBootSummary(diagnostic_rows, runtime_state.boot.phase);
  if (runtime_state.boot.serial_absent_warn_pending) {
    emitOtisBootWarnSerialAbsent(diagnostic_rows, kOtisSerialWaitMs);
    runtime_state.boot.serial_absent_warn_pending = false;
  }
  if (runtime_state.boot.safe_mode_warn_pending) {
    emitOtisBootWarnSafeMode(diagnostic_rows);
    runtime_state.boot.safe_mode_warn_pending = false;
  }
  runtime_state.boot.summary_emitted = true;
}

void wait_for_serial_or_timeout(void) {
  uint32_t serial_wait_start_ms = millis();
  while (!otis_transport_ready() &&
         (uint32_t)(millis() - serial_wait_start_ms) < kOtisSerialWaitMs) {
    delay(1);
  }
  runtime_state.boot.serial_ready = otis_transport_ready();
  runtime_state.boot.serial_absent_warn_pending =
      !runtime_state.boot.serial_ready;
}

void halt_boot(BootFatal fatal, BootPhase failed_phase) {
  enter_boot_phase(BootPhase::Fatal);
  otisBootBreadcrumbSetFatal(fatal);
  bool fatal_emitted = false;
  if (!transport_started) {
    transport_started = otis_transport_begin(kOtisSerialBaud);
    wait_for_serial_or_timeout();
  }
  if (otis_transport_ready()) {
    emit_protocol_banner_if_serial_ready();
    emit_selected_capability_status();
    emit_resource_ownership_status();
    emitOtisBootFatal(diagnostic_rows, fatal, failed_phase);
    fatal_emitted = true;
  }

  while (true) {
    if (otis_transport_ready() && !fatal_emitted) {
      emit_protocol_banner_if_serial_ready();
      emit_selected_capability_status();
      emit_resource_ownership_status();
      emitOtisBootFatal(diagnostic_rows, fatal, failed_phase);
      fatal_emitted = true;
    }
    delay(10);
  }
}

void enter_safe_mode(void) {
  runtime_state.boot.safe_mode_active = true;
  runtime_state.boot.safe_mode_warn_pending = true;
  enter_boot_phase(BootPhase::Fatal);
  otisBootBreadcrumbSetSafeModeFatal(BootFatal::RepeatedBootFailure);

  transport_started = otis_transport_begin(kOtisSerialBaud);
  wait_for_serial_or_timeout();
  emit_protocol_banner_if_serial_ready();
  emit_selected_capability_status();
  emit_resource_ownership_status();
}

const char *edge_string(char edge);
const char *osc_observation_domain(void);
OtisCountObservationConfig count_observation_config(void);

void emit_status(const char *component, const char *key, const char *value,
                 const char *severity, uint32_t flags) {
  if (__atomic_load_n(&dual_core_timing_boot_in_progress,
                      __ATOMIC_ACQUIRE)) {
    OtisTelemetryMessage message = {};
    message.timestamp_ticks = otis_monotonic_us32_now();
    message.flags = flags;
    snprintf(message.component, sizeof(message.component), "%s", component);
    snprintf(message.key, sizeof(message.key), "%s", key);
    snprintf(message.value, sizeof(message.value), "%s", value);
    snprintf(message.severity, sizeof(message.severity), "%s", severity);
    otis_dual_core_publish_boot_telemetry(&message);
    return;
  }
  otis_status_emit(&status_emit_context, component, key, value, severity,
                   flags);
}

void emit_status_direct(const char *component, const char *key,
                        const char *value, const char *severity,
                        uint32_t flags) {
  // Core 0 is the sole wire owner.  In particular, a record popped from the
  // Core 1 -> Core 0 telemetry queue must never be republished to that queue
  // while Core 1 boot publication is still active.
  otis_status_emit(&status_emit_context, component, key, value, severity,
                   flags);
}

void emit_status_u32(const char *component, const char *key, uint32_t value,
                     const char *severity, uint32_t flags) {
  char buffer[24];
  snprintf(buffer, sizeof(buffer), "%lu", static_cast<unsigned long>(value));
  emit_status(component, key, buffer, severity, flags);
}

void emit_status_i32(const char *component, const char *key, int32_t value,
                     const char *severity, uint32_t flags) {
  char buffer[12];
  snprintf(buffer, sizeof(buffer), "%ld", (long)value);
  emit_status(component, key, buffer, severity, flags);
}

void emit_status_u16_hex(const char *component, const char *key, uint16_t value,
                         const char *severity, uint32_t flags) {
  char buffer[7];
  snprintf(buffer, sizeof(buffer), "0x%04X", value);
  emit_status(component, key, buffer, severity, flags);
}

void emit_status_u64_decimal(const char *component, const char *key,
                             uint64_t value, const char *severity,
                             uint32_t flags) {
  char buffer[21];
  snprintf(buffer, sizeof(buffer), "%llu",
           static_cast<unsigned long long>(value));
  emit_status(component, key, buffer, severity, flags);
}

bool dual_core_timing_trace_due(uint32_t now_ms) {
  if (!dual_core_timing_trace_started ||
      (uint32_t)(now_ms - dual_core_last_timing_trace_ms) >=
          kDualCoreTimingTracePeriodMs) {
    dual_core_timing_trace_started = true;
    dual_core_last_timing_trace_ms = now_ms;
    return true;
  }
  return false;
}

uint16_t dual_core_hdop_hundredths(const char *text) {
  if (text == nullptr || *text == '\0') return 0u;
  const double parsed = strtod(text, nullptr);
  if (parsed <= 0.0) return 0u;
  const double scaled = parsed * 100.0;
  return scaled >= 65535.0 ? 65535u : static_cast<uint16_t>(scaled + 0.5);
}

bool dual_core_receiver_qualified_for_control(void) {
  return otis_dual_core_receiver_qualified_for_control_at(
      &dual_core_receiver, otis_monotonic_us32_now(),
      OTIS_GNSS_METADATA_MAX_AGE_MS);
}

void publish_dual_core_timing_status(const char *component, const char *key,
                                     const char *value,
                                     const char *severity, uint32_t flags) {
  OtisTelemetryMessage message = {};
  message.sequence = ++dual_core_timing_telemetry_sequence;
  message.timestamp_ticks = otis_monotonic_us32_now();
  message.flags = flags;
  snprintf(message.component, sizeof(message.component), "%s", component);
  snprintf(message.key, sizeof(message.key), "%s", key);
  snprintf(message.value, sizeof(message.value), "%s", value);
  snprintf(message.severity, sizeof(message.severity), "%s", severity);
  otis_dual_core_publish_telemetry(&message);
}

void publish_dual_core_timing_status_sink(
    void *, const char *component, const char *key, const char *value,
    const char *severity, uint32_t flags) {
  publish_dual_core_timing_status(component, key, value, severity, flags);
}

void publish_dual_core_timing_status_u32(const char *component,
                                         const char *key, uint32_t value,
                                         const char *severity,
                                         uint32_t flags);

void publish_forwarded_clock_monitor_status(void) {
  OtisForwardedClockMonitorStats monitor = {};
  otis_forwarded_clock_monitor_get_stats(&monitor);
  const char *severity = monitor.fault_latched ? OTIS_SEVERITY_WARN
                                               : OTIS_SEVERITY_INFO;
  const uint32_t flags = monitor.fault_latched
                             ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                             : OTIS_FLAG_NONE;
  publish_dual_core_timing_status(
      "forwarded_clock_monitor", "state",
      monitor.fault_latched
          ? "monitor_invalid_or_unavailable"
          : (monitor.running ? "monitoring_unqualified" : "disabled"),
      severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "configured", monitor.configured,
      severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "running", monitor.running, severity,
      flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "session", monitor.session, severity,
      flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "reference_service_count",
      monitor.reference_service_count, severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "snapshot_count", monitor.snapshot_count,
      severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "no_snapshot_count",
      monitor.no_snapshot_count, severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "fifo_backlog_count",
      monitor.fifo_backlog_count, severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "pio_rxstall_count",
      monitor.pio_rxstall_count, severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "fault_flags", monitor.fault_flags,
      severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "state_machine", monitor.state_machine,
      severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "program_offset", monitor.program_offset,
      severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "program_length", monitor.program_length,
      severity, flags);
}

void publish_dual_core_diagnostic_snapshot(OtisRunControlKind kind,
                                           uint32_t query_sequence,
                                           uint32_t query_nonce) {
  const uint32_t generation = ++dual_core_diagnostic_snapshot_generation;
  publish_dual_core_timing_status_u32(
      "timing_diagnostic_snapshot", "snapshot_generation_begin", generation,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  publish_dual_core_timing_status(
      "timing_diagnostic_snapshot", "snapshot_contract",
      "core1_timing_diagnostic_snapshot_v1", OTIS_SEVERITY_INFO,
      OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "timing_diagnostic_snapshot", "query_sequence", query_sequence,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "timing_diagnostic_snapshot", "query_nonce", query_nonce,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  if (kind == OtisRunControlKind::DiagnosticConfigQuery) {
    publish_dual_core_timing_status(
        "timing_diagnostic_snapshot", "query_kind", "configuration",
        OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    otis_count_observation_emit_configuration_status(
        &dual_core_timing_status_context);
    publish_forwarded_clock_monitor_status();
  } else {
    publish_dual_core_timing_status(
        "timing_diagnostic_snapshot", "query_kind", "runtime",
        OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    const OtisCountObservationConfig config = count_observation_config();
    otis_count_observation_emit_runtime_status(
        &runtime_state, &dual_core_timing_status_context, &config);
    otis_count_observation_emit_status(&runtime_state,
                                       &dual_core_timing_status_context);
  }
  publish_dual_core_timing_status_u32(
      "timing_diagnostic_snapshot", "snapshot_generation_complete",
      generation, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
}

void publish_dual_core_timing_status_u32(const char *component,
                                         const char *key, uint32_t value,
                                         const char *severity,
                                         uint32_t flags) {
  char formatted[24];
  snprintf(formatted, sizeof(formatted), "%lu",
           static_cast<unsigned long>(value));
  publish_dual_core_timing_status(component, key, formatted, severity, flags);
}

void publish_dual_core_active_status_field(void *, const char *key,
                                           const char *value,
                                           const char *severity,
                                           uint32_t flags) {
  publish_dual_core_timing_status(OTIS_ADAPTIVE_HYBRID_STATUS_COMPONENT, key,
                                  value, severity, flags);
}

bool publish_dual_core_active_status(uint32_t now_ms) {
  // Every caller, including priority abort consumption, must either publish
  // the complete generation or defer it.  A partial active snapshot is not a
  // useful lossy summary because host decisions bind begin/complete identity.
  if (!otis_dual_core_telemetry_can_publish(
          OTIS_REGULATION_STATUS_TELEMETRY_BURST))
    return false;
  otis_adaptive_hybrid_regulation_live_visit_status(
      nullptr, publish_dual_core_active_status_field, now_ms / 1000u);
  return true;
}

void publish_dual_core_timing_health(uint32_t now_ms) {
  if ((uint32_t)(now_ms - dual_core_last_timing_status_ms) < kStatusPeriodMs)
    return;
  // Do not begin a complete-generation health capsule unless the queue can
  // retain every record. Retry from the same due boundary after Core 0 drains;
  // a missing completion marker is never a permissible lossy summary.
  if (!otis_dual_core_telemetry_can_publish(
          OTIS_TIMING_HEALTH_TELEMETRY_BURST))
    return;
  dual_core_last_timing_status_ms = now_ms;

  OtisPpsSnapshotBackendStats capture = {};
  otis_pps_snapshot_backend_get_stats(&capture);
  publish_dual_core_timing_status_u32(
      "capture", "event_count", runtime_state.capture.emitted_event_count,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "capture", "error_flags", capture.fault_flags,
      capture.fault_latched ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
      capture.fault_latched ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT : OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "capture", "snapshot_ring_full_count", capture.ring_full_count,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "capture", "irq_budget_exhausted_count", capture.irq_budget_exhausted_count,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);

  otis_count_observation_emit_status(&runtime_state,
                                     &dual_core_timing_status_context);
  publish_forwarded_clock_monitor_status();

  publish_dual_core_active_status(now_ms);
}

void publish_dual_core_service_metadata(uint32_t now_ms) {
  if (!__atomic_load_n(&dual_core_timing_loop_started, __ATOMIC_ACQUIRE))
    return;
  if ((uint32_t)(now_ms - dual_core_last_metadata_ms) < 1000u) return;
  dual_core_last_metadata_ms = now_ms;

  OtisDualCoreQueueStats service_queues = {};
  otis_dual_core_get_stats(&service_queues);
  if (service_queues.service_to_timing_depth >
      OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH - 2u) {
    if (dual_core_periodic_service_deferred <= UINT32_MAX - 2u)
      dual_core_periodic_service_deferred += 2u;
    else
      dual_core_periodic_service_deferred = UINT32_MAX;
    return;
  }

  OtisGnssReceiverSnapshot gnss;
  otis_gnss_receiver_get_snapshot(now_ms, &gnss);
  OtisServiceMessage receiver = {};
  receiver.kind = OtisServiceMessageKind::ReceiverQualification;
  receiver.receiver.sequence = dual_core_service_sequence++;
  receiver.receiver.metadata_sequence = gnss.last_good_frame_sequence;
  receiver.receiver.published_ticks = otis_monotonic_us32_now();
  receiver.receiver.metadata_age_ms = gnss.metadata_age_ms;
  receiver.receiver.satellites = gnss.satellites;
  receiver.receiver.hdop_centihundredths =
      dual_core_hdop_hundredths(gnss.hdop);
  receiver.receiver.fix_quality = gnss.fix_quality;
  receiver.receiver.fix_type = gnss.fix_dimension;
  receiver.receiver.control_eligible = gnss.control_eligible;
  receiver.receiver.identity_stable = gnss.identity_stable;
  receiver.receiver.gsa_checksum_requalified =
      gnss.gsa_checksum_requalified;
  receiver.receiver.gsa_3d = gnss.gsa_3d;
  otis_dual_core_publish_service(&receiver);

  OtisDacAd5693rStatus dac;
  otis_dac_ad5693r_get_status(&dac);
  OtisServiceMessage applied = {};
  applied.kind = OtisServiceMessageKind::AppliedDacState;
  applied.dac.sequence = dual_core_service_sequence++;
  applied.dac.published_ticks = time_us_64();
  applied.dac.requested_code = dac.last_requested_code;
  applied.dac.applied_code = dac.last_applied_code;
  applied.dac.initialized = dac.initialized;
  applied.dac.i2c_ok = dac.last_write_ok;
  applied.dac.requested_applied_match =
      dac.applied_code_known && dac.last_write_ok &&
      dac.last_requested_code == dac.last_applied_code;
  otis_dual_core_publish_service(&applied);
}

bool propagate_regulation_applied_epoch_to_previews_exact(
    uint16_t applied_code, uint32_t dac_epoch, uint32_t now_s,
    uint64_t application_ticks, uint32_t capture_session) {
  otis_frequency_regulation_live_on_dac_applied_epoch_exact(
      applied_code, dac_epoch, now_s, application_ticks, capture_session);
  const bool phase=otis_phase_preview_live_update_applied_code(applied_code,dac_epoch);
  return phase && otis_frequency_regulation_live_applied_epoch_exact(applied_code,dac_epoch);
}

void service_dual_core_timing_inputs(void) {
  // Exact actuator facts are consumed before any boundary can make a dependent decision.
  OtisInstrumentApplication application = {};
  if (otis_dual_core_take_instrument_application(&application)) {
    const bool accepted = otis_adaptive_hybrid_regulation_live_application(application);
    if (accepted && application.attempted && application.ok) {
      dual_core_static_code = {true,true,true,application.code};
      const bool consumers=propagate_regulation_applied_epoch_to_previews_exact(application.code,
        application.request.dac_epoch,uint32_t(application.ticks/1000000ull),
        application.ticks,application.request.capture_session);
      if (!consumers ||
          !otis_adaptive_hybrid_regulation_live_confirm_consumers(application.code,application.request.dac_epoch,application.ticks))
        otis_dual_core_latch_fault(OtisPartitionFault::InstrumentApplicationMismatch);
    } else if (!accepted || application.attempted) {
      dual_core_static_code.available = false;
    }
  }
  OtisServiceMessage message = {};
  for (uint32_t consumed=0;consumed<OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH;++consumed) {
    if (!otis_dual_core_take_service(&message)) break;
    if (message.kind==OtisServiceMessageKind::ReceiverQualification) dual_core_receiver=message.receiver;
    else if (message.kind==OtisServiceMessageKind::Environment)
      otis_frequency_regulation_live_on_temperature(message.environment.temperature_valid,message.environment.temperature_c,uint32_t(time_us_64()/1000000ull));
    else if (message.kind==OtisServiceMessageKind::AppliedDacState) {
      otis_adaptive_hybrid_regulation_live_applied_snapshot(message.dac);
    } else if (message.kind==OtisServiceMessageKind::RunControl) {
      const auto &command=message.run_control;
      if (command.kind==OtisRunControlKind::Mode) {
        otis_adaptive_hybrid_regulation_live_command(command.instrument_command,time_us_64());
        publish_dual_core_active_status(millis());
      } else if (command.kind==OtisRunControlKind::StatusQuery) {
        otis_adaptive_hybrid_regulation_live_set_status_query_nonce(command.nonce);
        publish_dual_core_active_status(millis());
      } else if (command.kind==OtisRunControlKind::DiagnosticConfigQuery || command.kind==OtisRunControlKind::DiagnosticRuntimeQuery)
        publish_dual_core_diagnostic_snapshot(command.kind,command.sequence,command.nonce);
    }
  }
}

void service_instrument_executor(void) {
  // This path runs before USB service and has one bounded physical write per identity.
  static OtisInstrumentExecutor executor={};
  OtisInstrumentWrite request = {};
  if (!otis_dual_core_take_instrument_write(&request)) return;
  OtisDacAd5693rStatus dac = {};
  otis_dac_ad5693r_get_status(&dac);
  OtisInstrumentApplication application = {};
  application.request=request;
  application.code=request.prior_code;
  OtisGnssReceiverSnapshot receiver={};
  otis_gnss_receiver_get_snapshot(millis(),&receiver);
  const OtisInstrumentExecutorState state={ !otis_dual_core_fail_static(),dac.initialized,
    dac.applied_code_known && dac.last_write_ok,dac.last_applied_code,
    receiver.control_eligible && receiver.identity_stable && receiver.gsa_3d };
  application.rejection=otis_instrument_executor_admit(&executor,request,state,time_us_64());
  if (application.rejection==OtisInstrumentRejection::None) {
    application.attempted=true;
    application.ok=otis_dac_ad5693r_set_raw(request.code);
    if (application.ok) application.code=request.code;
  }
  application.ticks=time_us_64();
  otis_dual_core_publish_instrument_application(&application);
}

void note_observation_queue_service(const OtisObservationMessage &observation,
                                    bool dispatch) {
  if (observation.kind == OtisObservationMessageKind::RawEdge ||
        observation.kind == OtisObservationMessageKind::PpsSnapshot) {
      const auto channel = observation.kind == OtisObservationMessageKind::RawEdge
          ? OTIS_LATENCY_D14 : OTIS_LATENCY_D8;
      const auto status = observation.queue_clock_valid
          ? (observation.queue_clock_ambiguous ? OTIS_LATENCY_AMBIGUOUS :
                                                 OTIS_LATENCY_ELIGIBLE)
          : OTIS_LATENCY_MISSING;
      otis_service_latency_live_note({observation.snapshot.session,
          observation.snapshot.sequence, observation.queue_precommit_ticks,
          observation.queue_consumed_ticks, 0u, channel,
          OTIS_LATENCY_QUEUE_PRECOMMIT_TO_CONSUMER_RETURN, status,
          OTIS_LATENCY_RP2040_TIMER_US32});
      otis_service_latency_live_note({observation.snapshot.session,
          observation.snapshot.sequence, observation.queue_precommit_ticks,
          dispatch ? uint32_t(otis_monotonic_us32_now()) : 0u, 0u, channel,
          OTIS_LATENCY_OUTPUT_PRECOMMIT_TO_FORMATTER_DISPATCH,
          dispatch ? status : OTIS_LATENCY_MISSING,
          OTIS_LATENCY_RP2040_TIMER_US32});
    }
}

void service_dual_core_outputs(void) {
  OtisObservationMessage observation;
  uint8_t raw_budget = 24u;
  while (raw_budget-- > 0u && otis_transport_row_free_slots()>0 &&
         otis_dual_core_take_observation(&observation)) {
    note_observation_queue_service(observation, true);
    if (observation.kind == OtisObservationMessageKind::RawEdge) {
      const OtisRawEdgeMessage &edge = observation.raw_edge;
      otis_emit_raw_event(edge.reference_record ? OTIS_RECORD_REF
                                                : OTIS_RECORD_EVT,
                          edge.sequence, edge.channel_id,
                          edge_string(edge.edge), edge.timestamp_ticks,
                          OTIS_DOMAIN_RP2040_MONOTONIC_US32, edge.flags);
    } else if (observation.kind ==
               OtisObservationMessageKind::PpsSnapshot) {
      const OtisPpsSnapshotMessage &snapshot = observation.snapshot;
      otis_emit_pps_snapshot(
          snapshot.session, snapshot.sequence,
          snapshot.cumulative_down_counter, snapshot.reference_sequence,
          snapshot.reference_timestamp_ticks, snapshot.timestamp_uncertainty_ticks,
          snapshot.status, "pio_wait_cumulative_snapshot_fifo_irq_v2");
    } else if (observation.kind ==
               OtisObservationMessageKind::CountObservation) {
      const OtisCountObservationMessage &count = observation.count;
      otis_emit_count_observation(
          count.sequence, count.channel_id, count.gate_open_ticks,
          count.gate_close_ticks, OTIS_DOMAIN_RP2040_MONOTONIC_US32,
          count.counted_edges, OTIS_EDGE_RISING, count.source_domain,
          count.flags);
    }
  }

  otis_service_latency_live_output_service(millis());

  OtisMonitorObservationMessage monitor_observation;
  uint8_t monitor_budget = 8u;
  while (monitor_budget-- > 0u && otis_transport_row_free_slots()>0 &&
         otis_dual_core_take_monitor_observation(&monitor_observation)) {
    otis_emit_forwarded_monitor_snapshot(
        monitor_observation.session, monitor_observation.reference_session,
        monitor_observation.sequence,
        monitor_observation.cumulative_down_counter,
        monitor_observation.reference_sequence,
        monitor_observation.reference_timestamp_ticks,
        monitor_observation.status,
        "pio_wait_cumulative_snapshot_cpu_v1",
        monitor_observation.channel_id);
  }

  OtisCriticalRecordMessage critical;
  uint8_t critical_budget = 8u;
  while (critical_budget-- > 0u && otis_transport_row_free_slots()>0 &&
         otis_dual_core_take_critical(&critical)) {
    emit_status_direct(critical.component[0] == '\0' ? "dual_core"
                                                      : critical.component,
                       "critical_record", critical.reason,
                       critical.kind == OtisCriticalMessageKind::Fault
                           ? OTIS_SEVERITY_ERROR
                           : OTIS_SEVERITY_INFO,
                       critical.flags);
  }

  OtisTelemetryMessage telemetry;
  uint8_t telemetry_budget = 12u;
  while (telemetry_budget-- > 0u && otis_transport_row_free_slots()>0 &&
         otis_dual_core_take_telemetry(&telemetry)) {
    emit_status_direct(telemetry.component, telemetry.key, telemetry.value,
                       telemetry.severity, telemetry.flags);
    if (__atomic_load_n(&dual_core_timing_boot_in_progress,
                        __ATOMIC_ACQUIRE)) {
      otis_gnss_receiver_service(millis());
    }
  }
}

void service_forwarded_clock_monitor_boundary(
    const OtisPpsCountBoundaryObservation &authoritative) {
  if (!otis_forwarded_clock_monitor_service(
          authoritative.session, authoritative.reference_sequence)) {
    return;
  }
  OtisForwardedClockMonitorSnapshot snapshot = {};
  if (!otis_forwarded_clock_monitor_read(&snapshot)) return;

  OtisMonitorObservationMessage raw = {};
  raw.kind = OtisMonitorObservationKind::Snapshot;
  raw.session = snapshot.session;
  raw.reference_session = snapshot.reference_session;
  raw.sequence = snapshot.sequence;
  raw.cumulative_down_counter = snapshot.cumulative_down_counter;
  raw.reference_sequence = snapshot.reference_sequence;
  raw.reference_timestamp_ticks = authoritative.pps_timestamp_ticks;
  raw.status = snapshot.status;
  raw.channel_id = OTIS_CHANNEL_FORWARDED_CLOCK_MONITOR;
  otis_dual_core_publish_monitor_observation(&raw);
}

bool dual_core_evidence_transport_busy(void) {
  return dual_core_evidence_transport_active;
}

bool dual_core_evidence_transport_pending(void) {
  if (dual_core_evidence_transport_active) return true;
  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  return stats.evidence_depth != 0u;
}

void service_dual_core_evidence_transport(void) {
  if (!dual_core_evidence_transport_active) {
    if (!otis_dual_core_take_evidence(&dual_core_evidence_transport)) return;
    dual_core_evidence_transport_sent = 0u;
    dual_core_evidence_transport_active = true;
  }
  size_t available = otis_transport_available_for_write();
  if (available == 0u) return;
  size_t remaining = static_cast<size_t>(
      dual_core_evidence_transport.length - dual_core_evidence_transport_sent);
  size_t chunk = remaining < available ? remaining : available;
  if (chunk > 192u) chunk = 192u;
  dual_core_evidence_transport_sent = static_cast<uint16_t>(
      dual_core_evidence_transport_sent + otis_transport_try_write_frame_chunk(
          reinterpret_cast<const uint8_t *>(dual_core_evidence_transport.data) +
              dual_core_evidence_transport_sent,
          chunk));
  if (dual_core_evidence_transport_sent ==
      dual_core_evidence_transport.length) {
    dual_core_evidence_transport = {};
    dual_core_evidence_transport_sent = 0u;
    dual_core_evidence_transport_active = false;
  }
}

bool service_dual_core_serial_frame_transport(void) {
  const OtisSerialFrameReadiness readiness = {
      dual_core_evidence_transport_pending(),
      otis_frequency_regulation_live_transport_pending(),
      otis_phase_preview_transport_busy(),
      otis_transport_row_pending(),
  };
  const OtisSerialFrameOwner owner = otis_serial_frame_arbiter_claim(
      &dual_core_serial_frame_arbiter, readiness);
  if (owner == OtisSerialFrameOwner::None) return false;

  bool frame_active = false;
  switch (owner) {
    case OtisSerialFrameOwner::DualCoreEvidence:
      service_dual_core_evidence_transport();
      frame_active = dual_core_evidence_transport_busy();
      break;
    case OtisSerialFrameOwner::FrequencyRegulation:
      otis_frequency_regulation_live_service_transport();
      frame_active = otis_frequency_regulation_live_transport_busy();
      break;
    case OtisSerialFrameOwner::PhasePreview:
      otis_phase_preview_transport_service();
      frame_active = otis_phase_preview_transport_frame_active();
      break;
    case OtisSerialFrameOwner::DirectRow:
      otis_transport_service_row();
      frame_active = otis_transport_row_active();
      break;
    case OtisSerialFrameOwner::None:
      return false;
  }
  if (!frame_active)
    otis_serial_frame_arbiter_release(&dual_core_serial_frame_arbiter, owner);
  return frame_active;
}

void note_pre_carrier_discard(void) {
  if (dual_core_pre_carrier_records_discarded != UINT32_MAX)
    dual_core_pre_carrier_records_discarded++;
}

void discard_dual_core_outputs_before_first_carrier(void) {
  // Core 0 owns every outbound SPSC consumer before and after attachment.
  // Core 1 continues producing; changing USB state never transfers ownership.
  OtisObservationMessage observation;
  for (uint8_t budget = 24u;
       budget-- > 0u && otis_dual_core_take_observation(&observation);) {
    note_observation_queue_service(observation, false);
    note_pre_carrier_discard();
  }
  OtisMonitorObservationMessage monitor_observation;
  for (uint8_t budget = 8u;
       budget-- > 0u &&
       otis_dual_core_take_monitor_observation(&monitor_observation);)
    note_pre_carrier_discard();
  OtisCriticalRecordMessage critical;
  for (uint8_t budget = 8u;
       budget-- > 0u && otis_dual_core_take_critical(&critical);)
    note_pre_carrier_discard();
  OtisTelemetryMessage telemetry;
  for (uint8_t budget = 24u;
       budget-- > 0u && otis_dual_core_take_telemetry(&telemetry);)
    note_pre_carrier_discard();
  OtisEvidenceFrameMessage evidence;
  if (otis_dual_core_take_evidence(&evidence)) note_pre_carrier_discard();
  OtisPhasePreviewRecordMessage phase_preview;
  if (otis_dual_core_take_phase_preview(&phase_preview))
    note_pre_carrier_discard();
}

void abandon_dual_core_serial_frames_on_carrier_loss(void) {
  otis_transport_discard_rows();
  uint32_t abandoned = 0u;
  if (dual_core_evidence_transport_active) {
    dual_core_evidence_transport = {};
    dual_core_evidence_transport_sent = 0u;
    dual_core_evidence_transport_active = false;
    abandoned++;
  }
  if (otis_phase_preview_transport_abandon_active_frame()) abandoned++;
  otis_serial_frame_arbiter_reset(&dual_core_serial_frame_arbiter);
  // CONFIG? must re-establish a complete build-provenance block for the next
  // evidence segment even though this firmware boot and DAC state continue.
  config_query_provenance_emitted = false;
  core0_description_cursor=0;core0_description_pending=true;
  const uint32_t remaining = UINT32_MAX -
                             dual_core_carrier_loss_frames_abandoned;
  dual_core_carrier_loss_frames_abandoned +=
      abandoned < remaining ? abandoned : remaining;
}

OtisRegulationStaticCodeState regulation_static_code_state(void) {
  return dual_core_static_code;
}

void note_reference_capture_fault(const OtisPpsSnapshotBackendStats &stats) {
  static bool fault_reported = false;
  if (stats.fault_latched && !fault_reported) {
    fault_reported = true;
    reference_acceptance.invalidate(OtisReferenceAcceptanceReason::CaptureIntegrity);
    otis_count_observation_update_reference_acceptance(reference_acceptance.status());
    otis_count_observation_note_capture_loss(
        &runtime_state, &status_emit_context, stats.consumer_ordinal,
        "snapshot_backend_fault");
    const auto code = regulation_static_code_state();
    otis_frequency_regulation_live_on_capture_fault(
        "snapshot_backend_fault", uint32_t(time_us_64()/1000000ull), &code);
    otis_phase_preview_live_note_reset();
    // No automatic rearm: preserve unread FIFO/ring evidence and session.
  }
}

void update_adaptive_hybrid_regulation_health(void) {
  const uint32_t now_ms = millis();
  OtisPpsSnapshotBackendStats snapshot;
  otis_pps_snapshot_backend_get_stats(&snapshot);
  note_reference_capture_fault(snapshot);
  // D14 is the sole PPS/reference authority and the PIO snapshot backend
  // counts only D8 oscillator edges at D14 boundaries. D10 is the independent
  // external-event input; this fixed image does not claim it and no D10 observation
  // may validate or veto this control-health predicate.
  // Raw aperture rejection remains diagnostic. Accepted-reference continuity
  // and freshness own measurement/control admission; receiver metadata is an
  // independent actuation gate and cannot erase the measurement histories.
  reference_acceptance.service(time_us_64());
  const auto &accepted = reference_acceptance.status();
  otis_count_observation_update_reference_acceptance(accepted);
  const bool raw_pps_valid = accepted.tracking && accepted.anchor_current;
  const bool reference_integrity_valid =
      snapshot.running && !snapshot.fault_latched;
  OtisFrequencyRegulationAuthorityState preview;
  otis_frequency_regulation_live_get_authority_state(&preview);
  const bool applied_confirmed =
      dual_core_static_code.available &&
      dual_core_static_code.requested_applied_match &&
      dual_core_static_code.i2c_ok;
  OtisAdaptiveHybridRegulationLiveHealth health = {};
  health.session_id = snapshot.session;
  health.acceptance_epoch = accepted.acceptance_epoch;
  health.accepted_boundary_ordinal = accepted.accepted_boundary_ordinal;
  health.reference_acceptance_policy_sha256 = OTIS_REFERENCE_ACCEPTANCE_POLICY_SHA256;
  health.reference_acceptance_state = accepted.state;
  health.accepted_anchor_current = accepted.anchor_current;
  health.gnss_metadata_sequence = dual_core_receiver.metadata_sequence;
  health.gnss_metadata_valid = dual_core_receiver_qualified_for_control();
  health.gnss_identity_stable = dual_core_receiver.identity_stable;
  health.gnss_3d_evidence = dual_core_receiver.gsa_3d;
  health.raw_pps_valid = raw_pps_valid;
  health.reference_integrity_valid = reference_integrity_valid;
  health.count_valid = accepted.tracking && accepted.anchor_current &&
      accepted.capture_session == snapshot.session &&
      time_us_64()-runtime_state.tcxo.startup_inhibit_start_ticks >= uint64_t(kCountStartupInhibitMs)*1000ull;
  health.estimator_valid = preview.estimator_valid;
  health.model_applicable = preview.model_applicable;
  health.temperature_valid = preview.temperature_valid;
  health.applied_code_confirmed = applied_confirmed;
  health.applied_code = dual_core_static_code.applied_code;
  health.abort_path_live = !otis_dual_core_fail_static();
  health.selected_interval_count = preview.selected_interval_count;
  otis_adaptive_hybrid_regulation_live_update_health_at_ticks(
      &health, now_ms / 1000u, time_us_64());
}

void service_adaptive_hybrid_regulation_health(void) {
  update_adaptive_hybrid_regulation_health();
  otis_adaptive_hybrid_regulation_live_service(time_us_64());
}

const char *edge_string(char edge) {
  if (edge == 'R') {
    return OTIS_EDGE_RISING;
  }
  if (edge == 'F') {
    return OTIS_EDGE_FALLING;
  }
  return OTIS_EDGE_BOTH_OR_UNSPECIFIED;
}

const char *osc_observation_domain(void) {
  return OTIS_DOMAIN_H1_OSCILLATOR_10MHZ;
}

OtisCountObservationConfig count_observation_config(void) {
  return {
      kTcxoGatePeriodUs,
      kCountStartupInhibitMs,
      kCountControlReadyCleanWindows,
      osc_observation_domain(),
  };
}

// Same immutable snapshot identifies both the D14 reference presentation and
// D8 boundary word; no equality of independent presentation counters is assumed.
void note_reference_service_latency(uint32_t session, uint32_t source_sequence,
    OtisServiceLatencyStage stage, uint32_t start, uint32_t end,
    OtisServiceLatencyStatus status = OTIS_LATENCY_ELIGIBLE) {
  for (uint8_t channel = 1; channel <= 2; ++channel) {
    otis_service_latency_live_note({session, source_sequence, start, end, 0u,
        static_cast<OtisServiceLatencyChannel>(channel), stage, status,
        OTIS_LATENCY_RP2040_TIMER_US32});
  }
}

void emit_pps_count_boundary(
    const OtisPpsCountBoundaryObservation &observation,
    uint32_t snapshot_status, uint32_t first_consumption_ticks) {
  // Project FIFO service into the same timer's 64-bit domain. Its retained
  // recognition-time uncertainty participates in selection and freshness;
  // this projection does not turn CPU service into a latched edge timestamp.
  const uint64_t now_ticks = time_us_64();
  const uint32_t capture_age = uint32_t(now_ticks) -
      uint32_t(observation.pps_timestamp_ticks);
  const uint64_t closing_extended_ticks =
      now_ticks >= capture_age ? now_ticks - capture_age : UINT64_MAX;
  const auto paired = otis_reference_candidate(observation, snapshot_status);
  OtisReferenceAcceptanceOutcome selection = reference_acceptance.observe(
      paired, closing_extended_ticks, now_ticks,
      OTIS_ESTIMATE_TO_DECISION_MAXIMUM_LAG_TICKS);
  const uint32_t observation_ready_ticks = otis_monotonic_us32_now();
  note_reference_service_latency(observation.session, observation.sequence,
      OTIS_LATENCY_FIRST_CONSUMPTION_TO_READY, first_consumption_ticks,
      observation_ready_ticks);
  otis_count_observation_update_reference_acceptance(reference_acceptance.status());

  // Canonical raw CNT production remains independent of accepted selection.
  // Its shorter rejected fragments are retained before derived APS evidence.
  OtisCountObservationConfig count_config = count_observation_config();
  const bool window_completed = otis_count_observation_on_pps_boundary(
      &runtime_state, &status_emit_context, &count_config, &observation);
  if (selection.has_span) {
    // Reuse the timing owner's existing sequential evidence scratch buffer.
    // The timing owner formats one accepted-span record at a time.
    auto &frame = dual_core_reference_evidence_scratch;
    frame = {};
    if (!otis_reference_acceptance_format_span(selection,
            OTIS_REFERENCE_ACCEPTANCE_POLICY_SHA256, frame.data,
            sizeof(frame.data), &frame.length) ||
        !otis_dual_core_publish_evidence(&frame)) {
      // Delivery loss is accounted by the outbound queue, never a capture invalidation.
    }
  }
  const OtisRegulationStaticCodeState regulation_code = regulation_static_code_state();
  OtisAdaptiveHybridRegulationLiveOutcome active_outcome = {};
  // Both consumers receive the identical immutable selection. Publishing phase
  // before the frequency decision binds its first dependent control consumer.
  const uint32_t first_estimator_ticks = otis_monotonic_us32_now();
  otis_phase_preview_live_on_reference_selection(
      &selection, closing_extended_ticks, false);
  note_reference_service_latency(observation.session, observation.sequence,
      OTIS_LATENCY_READY_TO_FIRST_ESTIMATOR_CONSUMPTION, observation_ready_ticks,
      first_estimator_ticks);
  update_adaptive_hybrid_regulation_health();
  otis_frequency_regulation_live_on_reference_selection(
      &selection, closing_extended_ticks, uint32_t(time_us_64()/1000000ull),
      time_us_64(), &regulation_code, &active_outcome);
  if (window_completed) {
    otis_dual_core_note_timing_count(runtime_state.sequences.count_seq - 1u);
    otis_count_observation_note_control_consumer(observation.session,
                                                 observation.sequence);
  }
}

void drain_reference_snapshots(void) {
  // The only replenishment of bounded IRQ service credit in each Core 1 loop.
  otis_pps_snapshot_backend_poll();
  // Long foreground absence makes modulo-us32 residence ambiguous even if
  // its low-word subtraction looks short after a complete timer wrap.
  static uint64_t previous_drain_ticks = 0;
  bool sampled_drain = false;
  bool residence_bounded = false;
  OtisPpsHardwareSnapshot snapshot;
  uint32_t budget = 128u;
  while (budget-- > 0u && otis_pps_snapshot_backend_pop(&snapshot)) {
    const uint32_t first_consumption_ticks = otis_monotonic_us32_now();
    if (!sampled_drain) {
      const uint64_t drain_ticks = time_us_64();
      residence_bounded = previous_drain_ticks != 0 &&
          drain_ticks >= previous_drain_ticks &&
          drain_ticks - previous_drain_ticks < OTIS_SERVICE_LATENCY_HALF_RANGE;
      previous_drain_ticks = drain_ticks;
      sampled_drain = true;
    }
    note_reference_service_latency(snapshot.session, snapshot.sequence,
        OTIS_LATENCY_FIFO_READ_TO_FOREGROUND, snapshot.service_ticks,
        first_consumption_ticks, residence_bounded ? OTIS_LATENCY_ELIGIBLE :
                                                   OTIS_LATENCY_AMBIGUOUS);
    const auto observation = otis_reference_boundary(snapshot);
    // REF is a presentation of this same record, never another capture owner.
    OtisObservationMessage message = {};
    message.kind = OtisObservationMessageKind::RawEdge;
    message.snapshot.session = snapshot.session;
    message.snapshot.sequence = snapshot.sequence;
    message.raw_edge.sequence = runtime_state.sequences.event_seq++;
    message.raw_edge.timestamp_ticks = snapshot.service_ticks;
    message.raw_edge.flags = OTIS_FLAG_TIMESTAMP_RECONSTRUCTED;
    message.raw_edge.channel_id = OTIS_CHANNEL_PPS_REFERENCE;
    message.raw_edge.edge = 'R';
    message.raw_edge.reference_record = true;
    otis_dual_core_publish_observation(&message);
    ++runtime_state.capture.emitted_event_count;
    message = {};
    message.kind = OtisObservationMessageKind::PpsSnapshot;
    message.snapshot = {snapshot.session, snapshot.sequence,
        snapshot.cumulative_down_counter, snapshot.sequence,
        snapshot.service_ticks, snapshot.timestamp_uncertainty_ticks,
        snapshot.status};
    otis_dual_core_note_timing_snapshot(snapshot.session, snapshot.sequence);
    otis_dual_core_publish_observation(&message);
    emit_pps_count_boundary(observation, snapshot.status, first_consumption_ticks);
    service_forwarded_clock_monitor_boundary(observation);
  }
  OtisPpsSnapshotBackendStats stats = {};
  otis_pps_snapshot_backend_get_stats(&stats);
  note_reference_capture_fault(stats);
}

void emit_build_provenance_status(void) {
  if (core0_description_pending) return;
  if (core0_description_generation!=UINT32_MAX) ++core0_description_generation;
  core0_description_cursor=0;
  core0_description_pending=true;
}

void service_core0_description(void) {
  if (!core0_description_pending || otis_transport_row_free_slots()==0) return;
  struct Field {const char *component;const char *key;const char *value;};
  static const Field fields[]={
    {"firmware","name",OTIS_FIRMWARE_NAME},
    {"firmware","version",OTIS_FIRMWARE_VERSION},
    {"protocol","contract_id",OTIS_BUILD_FIRMWARE_HOST_CONTRACT_ID},
    {"protocol","contract_sha256",OTIS_BUILD_FIRMWARE_HOST_CONTRACT_SHA256},
    {"build","image_id",OTIS_BUILD_IMAGE_ID},
    {"build","provenance_format",OTIS_BUILD_PROVENANCE_FORMAT},
    {"firmware","git_commit",OTIS_FIRMWARE_GIT_COMMIT},
    {"firmware","source_state",OTIS_BUILD_SOURCE_STATE},
    {"firmware","source_hash",OTIS_BUILD_SOURCE_SHA256},
    {"firmware","config_hash",OTIS_BUILD_CONFIG_SHA256},
    {"system","board",OTIS_TARGET_BOARD},
    {"system","board_name",OTIS_TARGET_BOARD_NAME},
    {"system","fqbn",OTIS_BUILD_FQBN},
    {"system","arduino_core_provider",OTIS_BUILD_CORE_PROVIDER},
    {"system","arduino_core_version",OTIS_BUILD_CORE_VERSION},
    {"system","arduino_core_installed_hash",OTIS_BUILD_CORE_INSTALLED_SHA256},
    {"build","toolchain",OTIS_BUILD_TOOLCHAIN},
    {"build","compiler",OTIS_BUILD_COMPILER},
    {"build","toolchain_installed_hash",OTIS_BUILD_TOOLCHAIN_INSTALLED_SHA256},
    {"build","arduino_cli_version",OTIS_BUILD_ARDUINO_CLI_VERSION},
    {"build","invocation_id",OTIS_BUILD_INVOCATION_ID},
    {"build","source_identity_hash",OTIS_BUILD_SOURCE_IDENTITY_SHA256},
    {"build","target_identity_hash",OTIS_BUILD_TARGET_IDENTITY_SHA256},
    {"build","toolchain_identity_hash",OTIS_BUILD_TOOLCHAIN_IDENTITY_SHA256},
    {"build","authoritative_input_set_hash",OTIS_BUILD_AUTHORITATIVE_INPUT_SET_SHA256},
    {"build","provenance_hash",OTIS_BUILD_PROVENANCE_SHA256},
    {"build","generated_header_identity_hash",OTIS_BUILD_GENERATED_HEADER_IDENTITY_SHA256},
    {"policy","adaptive_sha256",OTIS_BUILD_ADAPTIVE_POLICY_SHA256},
    {"policy","frequency_estimator_sha256",OTIS_BUILD_FREQUENCY_ESTIMATOR_SHA256},
    {"policy","phase_estimator_sha256",OTIS_BUILD_PHASE_ESTIMATOR_SHA256},
    {"policy","plant_model_sha256",OTIS_BUILD_PLANT_MODEL_SHA256},
    {"policy","response_sha256",OTIS_BUILD_RESPONSE_POLICY_SHA256},
    {"instrument","boot_mode","AUTO_DISCIPLINE"},
    {"instrument","mode_persistence","session_only"},
    {"pins","reference_authority","D14"},
    {"pins","oscillator_count","D8_GPIO20_GPIN0"},
    {"pins","forwarded_output","D9_GPIO21_GPOUT0"},
    {"external_event","capture_backend","not_implemented"},
  };
  constexpr uint16_t count=sizeof(fields)/sizeof(fields[0]);
  if (core0_description_cursor==0)
    emit_status_u32("configuration","generation_begin",core0_description_generation,OTIS_SEVERITY_INFO,OTIS_FLAG_NONE);
  else if (core0_description_cursor<=count) {
    const Field &field=fields[core0_description_cursor-1];
    emit_status_direct(field.component,field.key,field.value,OTIS_SEVERITY_INFO,OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  } else if (core0_description_cursor==count+1)
    emit_status_u32("boot","reset_reason",otisBootBreadcrumbSnapshot().current_reset_reason,OTIS_SEVERITY_INFO,OTIS_FLAG_NONE);
  else if (core0_description_cursor==count+2)
    emit_status_u32("instrument","startup_code",OTIS_INSTRUMENT_START_CODE,OTIS_SEVERITY_INFO,OTIS_FLAG_NONE);
  else {
    emit_status_u32("configuration","generation_complete",core0_description_generation,OTIS_SEVERITY_INFO,OTIS_FLAG_NONE);
    core0_description_pending=false;
  }
  ++core0_description_cursor;
}

void emit_common_boot_status(void) {
  emit_build_provenance_status();
  emit_status("system", "boot", "true", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("protocol", "schema_version", OTIS_SCHEMA_VERSION_V1,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("firmware", "name", OTIS_FIRMWARE_NAME, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("firmware", "version", OTIS_FIRMWARE_VERSION, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("system", "mode", OTIS_OPERATING_MODE_NAME, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("capture", "mode", OTIS_CAPTURE_MODE, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("capture", "timestamp_semantics", "fifo_service_coordinate_with_recognition_bound",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status("capture", "limitation",
              "pio_recognition_bound_not_electrical_edge_timestamp",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status("capture", "timestamp_domain",
              OTIS_DOMAIN_RP2040_MONOTONIC_US32, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("capture", "timestamp_coordinate_hz",
                  OTIS_RP2040_MONOTONIC_US_PER_SECOND, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("capture", "timestamp_source_counter_hz",
                  OTIS_RP2040_MONOTONIC_US_PER_SECOND, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status_u32("capture", "timestamp_quantum_us",
                  OTIS_RP2040_MONOTONIC_TIMESTAMP_QUANTUM_US,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status_u32("capture", "timestamp_quantum_ns",
                  OTIS_RP2040_MONOTONIC_TIMESTAMP_QUANTUM_NS,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status("capture", "timestamp_coordinate_semantics",
              "native_local_non_metrological", OTIS_SEVERITY_WARN,
              OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status("capture", "timestamp_provenance",
              "rp2040_timerawl_or_arduino_micros_1mhz_native_us",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status_u32("reference", "nominal_pps_hz", OTIS_NOMINAL_PPS_HZ,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("capture", "counter_gate_period_us", kTcxoGatePeriodUs,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("capture", "measurement_mode",
              otis_count_observation_measurement_mode(),
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("system", "arduino_core", OTIS_TARGET_ARDUINO_CORE,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("build", "capture_backend", "pio_wait_cumulative_snapshot_fifo_irq_v2",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("build", "tcxo_counter_backend", "d14_gated_d8_snapshot",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("external_event", "capture_status", "not_implemented",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("external_event", "control_authority", "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("environment", "sample_period_ms", OTIS_ENV_SAMPLE_PERIOD_MS,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("environment", "sht4x_i2c_address",
                  OTIS_ENV_SHT4X_I2C_ADDRESS, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("environment", "bmp280_i2c_address",
                  OTIS_ENV_BMP280_I2C_ADDRESS, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("dac", "i2c_address", OTIS_DAC_AD5693R_I2C_ADDRESS,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u16_hex("dac", "min_code", OTIS_DAC_MIN_CODE,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u16_hex("dac", "max_code", OTIS_DAC_MAX_CODE,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
}

void emit_env_sensor_status(void) {
  OtisEnvSensorStatus status;
  otis_env_sensors_get_status(&status);
  emit_status("environment", "sht4x_enabled",
              status.sht4x_enabled ? "true" : "false", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("environment", "sht4x_initialized",
              status.sht4x_initialized ? "true" : "false",
              status.sht4x_initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.sht4x_initialized ? OTIS_FLAG_NONE
                                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("environment", "bmp280_enabled",
              status.bmp280_enabled ? "true" : "false", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("environment", "bmp280_initialized",
              status.bmp280_initialized ? "true" : "false",
              status.bmp280_initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.bmp280_initialized ? OTIS_FLAG_NONE
                                        : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("environment", "primary_temperature_source", "sht4x",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("environment", "primary_temperature_role", "vcocxo_near",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
}


void emit_gnss_receiver_status(void) {
  // Status bursts deliberately service UART0 after every complete STS frame.
  // Take the freshness anchor here, after any preceding burst service, so a
  // newly parsed sentence cannot appear a few milliseconds in the future and
  // wrap its unsigned age to nearly UINT32_MAX.
  const uint32_t now_ms = millis();
  OtisGnssReceiverSnapshot status;
  otis_gnss_receiver_get_snapshot(now_ms, &status);
  const uint32_t health_flags = status.control_eligible
                                    ? OTIS_FLAG_NONE
                                    : OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT;
  const char *health_severity =
      status.control_eligible ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN;
  const char *link_severity =
      status.link_online || !status.discovery_degraded
          ? OTIS_SEVERITY_INFO
          : OTIS_SEVERITY_WARN;
  const uint32_t link_flags = status.link_online
                                  ? OTIS_FLAG_NONE
                                  : OTIS_FLAG_SOURCE_HEALTH_SUSPECT;
  emit_status("gnss_receiver", "enabled",
              "true",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("gnss_receiver", "initialized",
              status.initialized ? "true" : "false",
              status.initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.initialized ? OTIS_FLAG_NONE
                                 : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("gnss_receiver", "link_state",
              status.link_health_state[0] == '\0'
                  ? "disabled"
                  : status.link_health_state,
              link_severity, link_flags);
  emit_status("gnss_receiver", "link_phase",
              status.link_phase[0] == '\0' ? "disabled" : status.link_phase,
              link_severity, link_flags);
  emit_status("gnss_receiver", "link_online",
              status.link_online ? "true" : "false", link_severity,
              link_flags);
  emit_status("gnss_receiver", "receiver_identity",
              status.receiver_identity_available
                  ? status.receiver_release
                  : "unavailable",
              link_severity, link_flags);
  emit_status("gnss_receiver", "configuration_confirmed",
              status.configuration_confirmed ? "true" : "false",
              link_severity, link_flags);
  emit_status("gnss_receiver", "uart_configuration",
              "uart0_configuration_blind_default_or_retained_115200_v1",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("gnss_receiver", "operational_baud_policy",
              "configuration_blind_default_or_retained_115200_v1",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("gnss_receiver", "operational_bootstrap_state",
              status.operational_bootstrap_failed
                  ? "failed"
                  : (status.operational_bootstrap_complete ? "complete"
                                                           : "in_progress"),
              status.operational_bootstrap_failed ? OTIS_SEVERITY_ERROR
                                                  : OTIS_SEVERITY_INFO,
              status.operational_bootstrap_failed
                  ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                  : OTIS_FLAG_NONE);
  emit_status("gnss_receiver", "operational_bootstrap_ordered_source_bauds",
              "9600,115200",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("gnss_receiver", "operational_bootstrap_settle_ms",
                  OTIS_GNSS_OPERATIONAL_PROMOTION_SETTLE_MS,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("gnss_receiver", "operational_bootstrap_attempt_count",
                  status.operational_bootstrap_attempt_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "target_baud_command_attempt_count",
                  status.target_baud_command_attempt_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32(
      "gnss_receiver", "post_bootstrap_target_baud_command_attempt_count",
      status.post_bootstrap_target_baud_command_attempt_count,
      status.post_bootstrap_target_baud_command_attempt_count == 0u
          ? OTIS_SEVERITY_INFO
          : OTIS_SEVERITY_ERROR,
      status.post_bootstrap_target_baud_command_attempt_count == 0u
          ? OTIS_FLAG_NONE
          : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32(
      "gnss_receiver", "operational_bootstrap_peripheral_complete_count",
      status.operational_bootstrap_peripheral_complete_count,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "operational_bootstrap_completed_rate_mask",
                  status.operational_bootstrap_completed_rate_mask,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "operational_bootstrap_first_completed_baud",
                  status.operational_bootstrap_first_completed_baud,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "operational_bootstrap_second_completed_baud",
                  status.operational_bootstrap_second_completed_baud,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "local_uart_baud",
                  status.local_uart_baud, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "local_uart_baud_epoch",
                  status.local_uart_baud_epoch, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "post_bootstrap_baud_change_count",
                  status.post_bootstrap_baud_change_count,
                  status.post_bootstrap_baud_change_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_ERROR,
                  status.post_bootstrap_baud_change_count == 0u
                      ? OTIS_FLAG_NONE
                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("gnss_receiver", "operational_bootstrap_rx_discarded_count",
                  status.operational_bootstrap_rx_discarded_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver", "autodiscovery_enabled", "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("gnss_receiver", "candidate_baud", status.candidate_baud,
                  link_severity, link_flags);
  if (status.confirmed_baud == 0u) {
    emit_status("gnss_receiver", "confirmed_baud", "unavailable",
                link_severity, link_flags);
  } else {
    emit_status_u32("gnss_receiver", "confirmed_baud",
                    status.confirmed_baud, link_severity, link_flags);
  }
  if (status.last_identity_response_baud == 0u) {
    emit_status("gnss_receiver", "last_identity_response_baud",
                "unavailable", link_severity, link_flags);
  } else {
    emit_status_u32("gnss_receiver", "last_identity_response_baud",
                    status.last_identity_response_baud, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_NONE);
  }
  emit_status("gnss_receiver", "output_confirmation_method",
              status.output_confirmation_method[0] == '\0'
                  ? "none"
                  : status.output_confirmation_method,
              link_severity, link_flags);
  emit_status_u32("gnss_receiver", "identity_response_count",
                  status.identity_response_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "pmtk605_peripheral_complete_count",
                  status.pmtk605_peripheral_complete_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u64_decimal(
      "gnss_receiver", "pmtk605_last_peripheral_complete_ticks",
      status.pmtk605_last_peripheral_complete_ticks,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver",
              "pmtk605_last_peripheral_complete_ticks_available",
              status.pmtk605_last_peripheral_complete_ticks_available
                  ? "true"
                  : "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver",
              "pmtk605_last_peripheral_complete_ticks_domain",
              "rp2040_monotonic_us64", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("gnss_receiver", "output_response_count",
                  status.output_response_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "output_query_timeout_count",
                  status.output_query_timeout_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "output_configuration_ack_count",
                  status.output_configuration_ack_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "output_observation_success_count",
                  status.output_observation_success_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "output_observed_sentence_mask",
                  status.output_observed_sentence_mask,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "output_unexpected_sentence_mask",
                  status.output_unexpected_sentence_mask,
                  status.output_unexpected_sentence_mask == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  status.output_unexpected_sentence_mask == 0u
                      ? OTIS_FLAG_NONE
                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("gnss_receiver", "last_command_ack_packet_type",
                  status.last_command_ack_packet_type,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "last_command_ack_flag",
                  status.last_command_ack_flag,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "output_configuration_field_count",
                  status.output_configuration_field_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver", "output_configuration_signature",
              status.output_configuration_signature[0] == '\0'
                  ? "unavailable"
                  : status.output_configuration_signature,
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver", "rx_pin", "D0_GPIO1_UART0_RX",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("gnss_receiver", "tx_pin", "D1_GPIO0_UART0_TX",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("gnss_receiver", "tx_policy",
              "fixed_discovery_configuration_only",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("gnss_receiver", "rx_only",
              status.rx_only ? "true" : "false",
              link_severity, link_flags);
  emit_status_u32("gnss_receiver", "discovery_cycle",
                  status.discovery_cycle, link_severity, link_flags);
  if (status.link_last_valid_frame_age_ms == UINT32_MAX) {
    emit_status("gnss_receiver", "link_last_valid_frame_age_ms",
                "unavailable", link_severity, link_flags);
  } else {
    emit_status_u32("gnss_receiver", "link_last_valid_frame_age_ms",
                    status.link_last_valid_frame_age_ms, link_severity,
                    link_flags);
  }
  emit_status_u32("gnss_receiver", "link_checksum_valid_count",
                  status.link_checksum_valid_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "link_checksum_failure_count",
                  status.link_checksum_failure_count,
                  status.link_checksum_failure_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  status.link_checksum_failure_count == 0u
                      ? OTIS_FLAG_NONE
                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("gnss_receiver", "link_oversize_count",
                  status.link_oversize_count,
                  status.link_oversize_count == 0u ? OTIS_SEVERITY_INFO
                                                   : OTIS_SEVERITY_WARN,
                  status.link_oversize_count == 0u
                      ? OTIS_FLAG_NONE
                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("gnss_receiver", "configuration_failure_count",
                  status.configuration_failure_count,
                  status.configuration_failure_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  status.configuration_failure_count == 0u
                      ? OTIS_FLAG_NONE
                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("gnss_receiver", "transmit_failure_count",
                  status.transmit_failure_count,
                  status.transmit_failure_count == 0u ? OTIS_SEVERITY_INFO
                                                      : OTIS_SEVERITY_WARN,
                  status.transmit_failure_count == 0u
                      ? OTIS_FLAG_NONE
                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("gnss_receiver", "link_loss_count",
                  status.link_loss_count,
                  status.link_loss_count == 0u ? OTIS_SEVERITY_INFO
                                               : OTIS_SEVERITY_WARN,
                  status.link_loss_count == 0u
                      ? OTIS_FLAG_NONE
                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("gnss_receiver", "talker",
              status.talker[0] == '\0' ? "unavailable" : status.talker,
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver", "rmc_seen",
              status.rmc_seen ? "true" : "false", health_severity,
              health_flags);
  emit_status("gnss_receiver", "rmc_valid",
              status.rmc_valid ? "true" : "false", health_severity,
              health_flags);
  emit_status("gnss_receiver", "gga_seen",
              status.gga_seen ? "true" : "false", health_severity,
              health_flags);
  emit_status_u32("gnss_receiver", "gga_fix_quality", status.fix_quality,
                  health_severity, health_flags);
  emit_status_u32("gnss_receiver", "satellite_count", status.satellites,
                  health_severity, health_flags);
  emit_status("gnss_receiver", "gsa_seen",
              status.gsa_seen ? "true" : "false", OTIS_SEVERITY_INFO,
              OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "gsa_fix_dimension",
                  status.fix_dimension, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver", "gsa_3d_fresh",
              status.gsa_3d ? "true" : "false",
              status.gsa_3d ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.gsa_3d ? OTIS_FLAG_NONE
                            : OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT);
  emit_status("gnss_receiver", "gsa_checksum_requalified",
              status.gsa_checksum_requalified ? "true" : "false",
              status.gsa_checksum_requalified ? OTIS_SEVERITY_INFO
                                              : OTIS_SEVERITY_WARN,
              status.gsa_checksum_requalified
                  ? OTIS_FLAG_NONE
                  : OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT);
  emit_status("gnss_receiver", "hdop",
              status.hdop[0] == '\0' ? "unavailable" : status.hdop,
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver", "utc_available",
              status.utc_available ? "true" : "false", health_severity,
              health_flags);
  emit_status("gnss_receiver", "date_available",
              status.date_available ? "true" : "false", health_severity,
              health_flags);
  emit_status("gnss_receiver", "utc",
              status.utc[0] == '\0' ? "unavailable" : status.utc,
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver", "date",
              status.date[0] == '\0' ? "unavailable" : status.date,
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  if (status.metadata_age_ms == UINT32_MAX) {
    emit_status("gnss_receiver", "metadata_age_ms", "unavailable",
                health_severity, health_flags);
  } else {
    emit_status_u32("gnss_receiver", "metadata_age_ms",
                    status.metadata_age_ms, health_severity, health_flags);
  }
  emit_status("gnss_receiver", "metadata_fresh",
              status.metadata_fresh ? "true" : "false", health_severity,
              health_flags);
  emit_status("gnss_receiver", "checksum_requalified",
              status.checksum_requalified ? "true" : "false",
              health_severity, health_flags);
  emit_status("gnss_receiver", "identity_stable",
              status.identity_stable ? "true" : "false", health_severity,
              health_flags);
  emit_status("gnss_receiver", "disconnected",
              status.disconnected ? "true" : "false", health_severity,
              health_flags);
  emit_status("gnss_receiver", "metadata_control_eligible",
              status.control_eligible ? "true" : "false", health_severity,
              health_flags);
  // Receiver metadata is qualification only. The Core 1 ACTIVE/pps_gate
  // snapshots report complete control eligibility without a cross-core read
  // of mutable timing state.
  emit_status_u32("gnss_receiver", "identity_epoch", status.identity_epoch,
                  health_severity, health_flags);
  emit_status_u32("gnss_receiver", "checksum_valid_count",
                  status.checksum_valid_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "checksum_failure_count",
                  status.checksum_failure_count,
                  status.checksum_failure_count ? OTIS_SEVERITY_WARN
                                                : OTIS_SEVERITY_INFO,
                  status.checksum_failure_count ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                                                : OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "parser_drop_count",
                  status.parser_drop_count,
                  status.parser_drop_count ? OTIS_SEVERITY_WARN
                                           : OTIS_SEVERITY_INFO,
                  status.parser_drop_count ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                                           : OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "truncated_count", status.truncated_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "oversize_count", status.oversize_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "rmc_count", status.rmc_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "gga_count", status.gga_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "gsa_count", status.gsa_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
}

void emit_h0_pin_status(void) {
  emit_status("pins", "ch0_generic_event", "D10", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("pins", "ch1_pps_reference", "D14", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("pins", "ch2_osc_observation", "D8_GPIO20_GPIN0",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  OtisForwardedClockOutputStatus output = {};
  otis_forwarded_clock_output_get_status(&output);
  emit_status("forwarded_clock_output", "contract_id", output.contract_id,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("forwarded_clock_output", "contract_sha256",
              output.contract_sha256, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("forwarded_clock_output", "state", output.reason,
              output.valid ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              output.valid ? OTIS_FLAG_CONFIGURATION_ASSUMPTION
                           : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("forwarded_clock_output", "source", "D8_GPIO20_GPIN0",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("forwarded_clock_output", "destination", "D9_GPIO21_GPOUT0",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "integer_divider",
                  output.integer_divider, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "fractional_divider",
                  output.fractional_divider, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "applied_auxsrc",
                  output.applied_auxsrc, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "applied_integer_divider",
                  output.applied_integer_divider, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "applied_fractional_divider",
                  output.applied_fractional_divider, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "source_gpio_function",
                  output.source_gpio_function, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "destination_gpio_function",
                  output.destination_gpio_function, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "inversion",
                  output.inversion, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "drive_strength_ma",
                  output.drive_strength_ma, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("forwarded_clock_output", "slew_rate",
              output.slew_rate_fast ? "fast" : "slow",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "nominal_frequency_hz",
                  output.nominal_frequency_hz, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u64_decimal("forwarded_clock_output", "first_valid_ticks",
                          output.first_valid_ticks, OTIS_SEVERITY_INFO,
                          OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("forwarded_clock_output", "readback_valid",
              output.readback_valid ? "true" : "false",
              output.readback_valid ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              output.readback_valid ? OTIS_FLAG_CONFIGURATION_ASSUMPTION
                                    : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
}

void emit_selected_capability_status(void) {
  if (boot_capability_status_emitted || !otis_transport_ready()) {
    return;
  }

  const OtisBootCapabilityOutcome overall =
      otis_boot_capability_overall_outcome(&boot_capabilities);
  const bool run_mode_ready = boot_capabilities.run_mode_marked;
  const bool degraded = otis_boot_capability_degraded(&boot_capabilities);
  emit_status("boot_capabilities", "selected_image",
              OTIS_OPERATING_MODE_NAME, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("boot_capabilities", "overall",
              otis_boot_capability_outcome_name(overall),
              overall == OtisBootCapabilityOutcome::Ready
                  ? OTIS_SEVERITY_INFO
                  : (overall == OtisBootCapabilityOutcome::OptionalDegraded
                         ? OTIS_SEVERITY_WARN
                         : OTIS_SEVERITY_FATAL),
              overall == OtisBootCapabilityOutcome::Ready
                  ? OTIS_FLAG_CONFIGURATION_ASSUMPTION
                  : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("boot_capabilities", "run_mode",
              run_mode_ready ? "Ready" : "blocked",
              run_mode_ready ? (degraded ? OTIS_SEVERITY_WARN
                                         : OTIS_SEVERITY_INFO)
                             : OTIS_SEVERITY_FATAL,
              run_mode_ready && !degraded ? OTIS_FLAG_CONFIGURATION_ASSUMPTION
                                          : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("boot_capabilities", "degraded",
              degraded ? "true" : "false",
              degraded ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
              degraded ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                       : OTIS_FLAG_CONFIGURATION_ASSUMPTION);

  uint32_t selected_count = 0u;
  for (uint8_t index = 0u;
       index < static_cast<uint8_t>(OtisBootCapability::Count); ++index) {
    const OtisBootCapability capability =
        static_cast<OtisBootCapability>(index);
    const OtisBootCapabilityEntry *entry =
        otis_boot_capability_entry(&boot_capabilities, capability);
    if (entry == nullptr ||
        entry->requirement == OtisBootCapabilityRequirement::Disabled) {
      continue;
    }
    selected_count++;
    char value[48];
    snprintf(value, sizeof(value), "%s:%s",
             otis_boot_capability_requirement_name(entry->requirement),
             entry->reported
                 ? otis_boot_capability_outcome_name(entry->outcome)
                 : "pending");
    const bool capability_ready =
        entry->reported &&
        (entry->outcome == OtisBootCapabilityOutcome::Ready ||
         entry->outcome == OtisBootCapabilityOutcome::OptionalDegraded);
    emit_status("boot_capabilities",
                otis_boot_capability_name(capability), value,
                entry->outcome == OtisBootCapabilityOutcome::OptionalDegraded
                    ? OTIS_SEVERITY_WARN
                    : (capability_ready ? OTIS_SEVERITY_INFO
                                        : OTIS_SEVERITY_FATAL),
                capability_ready && entry->outcome ==
                                        OtisBootCapabilityOutcome::Ready
                    ? OTIS_FLAG_CONFIGURATION_ASSUMPTION
                    : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  }
  emit_status_u32("boot_capabilities", "selected_count", selected_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  boot_capability_status_emitted = true;
}

void emit_resource_ownership_status(void) {
  if(resource_ownership_status_emitted || !otis_transport_ready() || otis_transport_row_free_slots()==0) return;
  const char *key=""; uint32_t value=0;
  switch(resource_status_cursor++) {
    case 0:key="valid";value=otis_resource_registry_valid();break;
    case 1:key="complete";value=otis_resource_registry_complete();break;
    case 2:key="claim_count";value=otis_resource_registry_claim_count();break;
    case 3:key="conflict_count";value=otis_resource_registry_conflict_count();break;
    case 4:key="binding_failure_count";value=otis_resource_registry_binding_failure_count();break;
    case 5:key="gpio_claim_count";value=otis_resource_registry_claim_count(OtisResourceType::Gpio);break;
    case 6:key="irq_claim_count";value=otis_resource_registry_claim_count(OtisResourceType::GpioIrq);break;
    case 7:key="pio_sm_claim_count";value=otis_resource_registry_claim_count(OtisResourceType::PioStateMachine);break;
    case 8:key="pio_imem_claim_count";value=otis_resource_registry_claim_count(OtisResourceType::PioInstructionMemory);break;
    case 9:key="pio_irq_source_claim_count";value=otis_resource_registry_claim_count(OtisResourceType::PioIrqSource);break;
    case 10:key="timer_claim_count";value=otis_resource_registry_claim_count(OtisResourceType::Timer);break;
    case 11:key="clock_claim_count";value=otis_resource_registry_claim_count(OtisResourceType::Clock);break;
  }
  emit_status_u32("resource_registry",key,value,OTIS_SEVERITY_INFO,OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  if(resource_status_cursor==12)resource_ownership_status_emitted=true;
}

void emit_protocol_banner_if_serial_ready(void) {
  if (runtime_state.boot.protocol_banner_emitted || !otis_transport_ready() ||
      otis_transport_row_free_slots()==0) return;
  if (!runtime_state.boot.summary_emitted) {
    emitOtisBootSummary(diagnostic_rows,runtime_state.boot.phase);
    runtime_state.boot.summary_emitted=true;
    return;
  }
  emitRp2040BootDiag(diagnostic_rows);
  // Every data row carries its own record and schema version. The canonical
  // contract replaces a large best-effort startup burst of column headings.
  runtime_state.boot.protocol_banner_emitted=true;
}

void emit_periodic_status(void) {
  if (!otis_transport_ready() || otis_transport_row_free_slots()==0) return;
  const uint32_t now_ms=millis();
  if (!core0_periodic_pending) {
    if (uint32_t(now_ms-runtime_state.periodic.last_status_ms)<kStatusPeriodMs) return;
    core0_periodic_pending=true;core0_periodic_cursor=0;
  }
  switch(core0_periodic_cursor++) {
    case 0: emit_status_u32("system","uptime_seconds",now_ms/1000u,OTIS_SEVERITY_INFO,OTIS_FLAG_NONE);break;
    case 1: emit_status_u32("dual_core","pre_carrier_records_discarded",dual_core_pre_carrier_records_discarded,OTIS_SEVERITY_INFO,OTIS_FLAG_NONE);break;
    case 2: emit_status_u32("dual_core","carrier_loss_frames_abandoned",dual_core_carrier_loss_frames_abandoned,OTIS_SEVERITY_INFO,OTIS_FLAG_NONE);break;
    case 3: emit_status_u32("dual_core","periodic_service_deferred",dual_core_periodic_service_deferred,OTIS_SEVERITY_INFO,OTIS_FLAG_NONE);break;
    case 4: emit_status_u32("transport","direct_rows_dropped",otis_transport_row_dropped(),OTIS_SEVERITY_INFO,OTIS_FLAG_NONE);break;
    default:
      if(!otis_memory_budget_emit_status_field(&status_emit_context,core0_periodic_cursor-6)) {
        core0_periodic_pending=false;runtime_state.periodic.last_status_ms=now_ms;
      }
      break;
  }
}

void emit_dac_status(const char *component) {
  OtisDacAd5693rStatus status;
  otis_dac_ad5693r_get_status(&status);
  emit_status(component, "enabled", status.enabled ? "true" : "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(component, "initialized", status.initialized ? "true" : "false",
              status.initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.enabled ? OTIS_FLAG_NONE : OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(component, "last_write_ok", status.last_write_ok ? "true" : "false",
              status.last_write_ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              OTIS_FLAG_NONE);
  emit_status(component, "applied_code_known",
              status.applied_code_known ? "true" : "false",
              status.applied_code_known ? OTIS_SEVERITY_INFO
                                        : OTIS_SEVERITY_WARN,
              OTIS_FLAG_NONE);
  emit_status_u32(component, "i2c_address", status.i2c_address,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u16_hex(component, "min_code", status.min_code,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u16_hex(component, "max_code", status.max_code,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u16_hex(component, "last_requested_code",
                      status.last_requested_code, OTIS_SEVERITY_INFO,
                      OTIS_FLAG_NONE);
  if (status.applied_code_known) {
    emit_status_u16_hex(component, "last_applied_code", status.last_applied_code,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  } else {
    emit_status(component, "last_applied_code", "unavailable",
                OTIS_SEVERITY_WARN, OTIS_FLAG_NONE);
  }
  emit_status(component, "gain_mode", status.gain_mode, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(component, "reference_mode", status.reference_mode,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
}


void configure_adaptive_hybrid_regulation(void) {
  emit_status("control", "adaptive_hybrid_regulation", "configured",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  bool ok = capability_ready(OtisBootCapability::Dac);
  emit_status("dac", "init", ok ? "ok" : "failed",
              ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_dac_status("dac");
  bool env_ok = capability_ready(OtisBootCapability::Sensors);
  emit_status("environment", "init", env_ok ? "ok" : "failed",
              env_ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              env_ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_env_sensor_status();
  emit_gnss_receiver_status();
}

void format_env_float(float value, char *buffer, size_t buffer_size) {
  if (buffer == nullptr || buffer_size == 0) {
    return;
  }
  snprintf(buffer, buffer_size, "%.3f", static_cast<double>(value));
}

void emit_env_sample(const OtisEnvSample &sample,
                     uint64_t timestamp_ticks) {
  if (!sample.valid) {
    return;
  }
  if (strcmp(sample.role, "vcocxo_near") == 0) {
    OtisDualCoreQueueStats service_queues = {};
    otis_dual_core_get_stats(&service_queues);
    if (service_queues.service_to_timing_depth >=
        OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH) {
      if (dual_core_periodic_service_deferred != UINT32_MAX)
        dual_core_periodic_service_deferred++;
    } else {
    OtisServiceMessage environment = {};
    environment.kind = OtisServiceMessageKind::Environment;
    environment.environment.sequence = dual_core_service_sequence++;
    environment.environment.timestamp_ticks = timestamp_ticks;
    environment.environment.temperature_c = sample.temperature_c;
    environment.environment.relative_humidity_pct =
        sample.relative_humidity_pct;
    environment.environment.pressure_pa = sample.pressure_pa;
    environment.environment.temperature_valid = true;
    environment.environment.humidity_valid = sample.has_humidity;
    environment.environment.pressure_valid = sample.has_pressure;
    otis_dual_core_publish_service(&environment);
    }
  }
  char temperature[16];
  char humidity[16];
  char pressure[16];
  format_env_float(sample.temperature_c, temperature, sizeof(temperature));
  if (sample.has_humidity) {
    format_env_float(sample.relative_humidity_pct, humidity, sizeof(humidity));
  } else {
    humidity[0] = '\0';
  }
  if (sample.has_pressure) {
    format_env_float(sample.pressure_pa, pressure, sizeof(pressure));
  } else {
    pressure[0] = '\0';
  }
  otis_emit_environment(runtime_state.sequences.env_seq++,
                        timestamp_ticks, OTIS_DOMAIN_RP2040_MONOTONIC_US32,
                        sample.source, sample.role, temperature, humidity,
                        pressure, OTIS_FLAG_NONE);
}

void service_environment_sensors(void) {
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - runtime_state.periodic.last_env_sample_ms) <
      OTIS_ENV_SAMPLE_PERIOD_MS) {
    return;
  }
  runtime_state.periodic.last_env_sample_ms = now_ms;
  OtisEnvSample sample;
  if (otis_env_sensors_read_sht4x(&sample)) {
    const uint64_t timestamp_ticks = otis_monotonic_us32_now();
    emit_env_sample(sample, timestamp_ticks);
  } else {
    OtisDualCoreQueueStats service_queues = {};
    otis_dual_core_get_stats(&service_queues);
    if (service_queues.service_to_timing_depth >=
        OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH) {
      if (dual_core_periodic_service_deferred != UINT32_MAX)
        dual_core_periodic_service_deferred++;
    } else {
    OtisServiceMessage environment = {};
    environment.kind = OtisServiceMessageKind::Environment;
    environment.environment.sequence = dual_core_service_sequence++;
    environment.environment.timestamp_ticks = otis_monotonic_us32_now();
    environment.environment.temperature_valid = false;
    otis_dual_core_publish_service(&environment);
    }
  }
  if (otis_env_sensors_read_bmp280(&sample)) {
    emit_env_sample(sample, otis_monotonic_us32_now());
  }
}

void emit_run_mode_status_if_ready(void) {
  if (!run_mode_status_emitted && boot_capabilities.run_mode_marked && runtime_state.boot.protocol_banner_emitted) {
    emit_build_provenance_status();
    run_mode_status_emitted=true;
  }
}

void boot_phase_reset_entry(void) {
  begin_boot_phase(BootPhase::ResetEntry);
  captureRp2040BootDiag();
  otisBootBreadcrumbBegin(BootPhase::ResetEntry);
  delay(kOtisBootInitialDelayMs);
  complete_boot_phase(BootPhase::ResetEntry);
}

void boot_phase_early_init(void) {
  begin_boot_phase(BootPhase::EarlyInit);
  const bool valid = otis_resource_registry_begin();
  if (!valid) {
    otis_boot_capability_record(
        &boot_capabilities, OtisBootCapability::ResourceRegistry,
        OtisBootCapabilityOutcome::FatalConflict);
  }
  complete_boot_phase(BootPhase::EarlyInit);
}

void boot_phase_clocks_init(void) {
  begin_boot_phase(BootPhase::ClocksInit);
  record_capability_result(OtisBootCapability::Timebase,
                           otis_timebase_begin());
  complete_boot_phase(BootPhase::ClocksInit);
}

void boot_phase_gpio_init(void) {
  begin_boot_phase(BootPhase::GpioInit);
  // Preserve D10/CH0 as the optional external-event seam, but do not claim an
  // active capture backend. The current backend is a singleton owned by the
  // D14/CH1 reference observer; reusing it here would violate fail-local D10
  // isolation. A distinct backend, ring, and owner are required first.
  pinMode(OTIS_PIN_EXTERNAL_EVENT, INPUT);
  pinMode(OTIS_PIN_PPS_REFERENCE, INPUT_PULLDOWN);
  complete_boot_phase(BootPhase::GpioInit);
}

void boot_phase_capture_init(void) {
  begin_boot_phase(BootPhase::CaptureInit);
  complete_boot_phase(BootPhase::CaptureInit);
}

void boot_phase_timer_init(void) {
  begin_boot_phase(BootPhase::TimerInit);
  runtime_state.tcxo.startup_inhibit_start_ms = millis();
  runtime_state.tcxo.startup_inhibit_start_ticks = time_us_64();
  runtime_state.tcxo.startup_inhibit_active = true;
  runtime_state.tcxo.valid_for_control = false;
  runtime_state.tcxo.control_clean_window_count = 0;
  runtime_state.tcxo.fault_after_startup = false;
  OtisCountObservationConfig count_config = count_observation_config();
  const bool ready = otis_count_observation_begin(
      &runtime_state, &status_emit_context, &count_config);
  record_capability_result(OtisBootCapability::OscillatorCount, ready);
  complete_boot_phase(BootPhase::TimerInit);
}

void boot_phase_pps_input_init(void) {
  begin_boot_phase(BootPhase::PpsInputInit);
  OtisPpsSnapshotBackendStats snapshot = {};
  otis_pps_snapshot_backend_get_stats(&snapshot);
  const bool pps_ready = snapshot.initialized && snapshot.running;
  record_capability_result(OtisBootCapability::PpsCapture, pps_ready);
  complete_boot_phase(BootPhase::PpsInputInit);
}

void boot_phase_forwarded_output_init(void) {
  begin_boot_phase(BootPhase::ForwardedOutputInit);
  const bool ready = otis_forwarded_clock_output_begin();
  record_capability_result(OtisBootCapability::ForwardedOutput, ready);
  complete_boot_phase(BootPhase::ForwardedOutputInit);
}

void boot_phase_forwarded_monitor_init(void) {
  begin_boot_phase(BootPhase::ForwardedMonitorInit);
  const bool ready = otis_forwarded_clock_monitor_begin();
  record_capability_result(OtisBootCapability::ForwardedMonitor, ready);
  complete_boot_phase(BootPhase::ForwardedMonitorInit);
}

void boot_phase_ring_buffers_init(void) {
  begin_boot_phase(BootPhase::RingBuffersInit);
  otis_dual_core_partition_reset();
  otis_dual_core_set_observation_diagnostic_clock(time_us_64);
  record_capability_result(OtisBootCapability::RingBuffers, true);
  complete_boot_phase(BootPhase::RingBuffersInit);
}

void boot_phase_serial_init(void) {
  begin_boot_phase(BootPhase::SerialInit);
  transport_started = otis_transport_begin(kOtisSerialBaud);
  wait_for_serial_or_timeout();
  record_capability_result(OtisBootCapability::Transport, transport_started);
  record_capability_result(OtisBootCapability::HostConnection,
                           runtime_state.boot.serial_ready);

  complete_boot_phase(BootPhase::SerialInit);
}

void boot_phase_protocol_banner(void) {
  begin_boot_phase(BootPhase::ProtocolBanner);
  emit_protocol_banner_if_serial_ready();
  complete_boot_phase(BootPhase::ProtocolBanner);
}

void boot_phase_peripherals_init(void) {
  begin_boot_phase(BootPhase::PeripheralsInit);
  const bool dac_ready = otis_dac_ad5693r_begin();
  record_capability_result(OtisBootCapability::Dac, dac_ready);
  const bool sensors_ready = otis_env_sensors_begin();
  record_capability_result(OtisBootCapability::Sensors, sensors_ready);
  const bool gnss_receiver_ready = otis_gnss_receiver_begin();
  record_capability_result(OtisBootCapability::GnssReceiver,
                           gnss_receiver_ready);
  complete_boot_phase(BootPhase::PeripheralsInit);
}

void boot_phase_preview_init(void) {
  begin_boot_phase(BootPhase::PreviewInit);
  OtisPpsSnapshotBackendStats capture = {};
  otis_pps_snapshot_backend_get_stats(&capture);
  const bool preview_ready =
      otis_frequency_regulation_live_begin(uint32_t(time_us_64()/1000000ull)) &&
      otis_adaptive_hybrid_regulation_live_begin(get_rand_64(),capture.session,time_us_64());
  record_capability_result(OtisBootCapability::FrequencyRegulation,
                           preview_ready);
  const bool phase_preview_ready = otis_phase_preview_live_begin();
  record_capability_result(OtisBootCapability::PhaseFrequencyEstimate,
                           phase_preview_ready);
  complete_boot_phase(BootPhase::PreviewInit);
}

void boot_phase_capability_audit(void) {
  begin_boot_phase(BootPhase::CapabilityAudit);
  const bool registry_valid = otis_resource_registry_valid();
  const bool registry_complete = otis_resource_registry_complete();
  otis_boot_capability_record(
      &boot_capabilities, OtisBootCapability::ResourceRegistry,
      otis_boot_registry_outcome(registry_valid, registry_complete));
  complete_boot_phase(BootPhase::CapabilityAudit);
}

void boot_phase_run_mode(void) {
  if (!otis_boot_capability_mark_run_mode(&boot_capabilities)) {
    const BootFatal fatal =
        otis_boot_capability_has_fatal_conflict(&boot_capabilities)
            ? BootFatal::ResourceOwnershipConflict
            : BootFatal::RequiredCapabilityUnavailable;
    emit_selected_capability_status();
    emit_resource_ownership_status();
    halt_boot(fatal, BootPhase::CapabilityAudit);
  }
  enter_boot_phase(BootPhase::RunMode);
  runtime_state.boot.degraded =
      otis_boot_capability_degraded(&boot_capabilities);
  runtime_state.periodic.last_status_ms = millis();
  otisBootBreadcrumbMarkRunMode();
}

void service_tcxo_gate(void) {
  OtisCountObservationConfig count_config = count_observation_config();
  otis_count_observation_service(&runtime_state, &status_emit_context,
                                 &count_config);
}

void execute_serial_command(const OtisParsedSerialCommand &command) {
  if (command.kind == OtisSerialCommandKind::Help) {
    emit_status("command", "h1_help",
                "CONFIG?_DUALCORE?_DAC?_DAC_LIMITS?_COUNT?_ACTIVE?_ACTIVE_SNAPSHOT_nonce_ACTIVE_MODE_session_sequence_mode_code_dwell_s_HELP",
                OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  } else if (command.kind == OtisSerialCommandKind::ConfigQuery) {
    emit_build_provenance_status();
    resource_status_cursor=0;resource_ownership_status_emitted=false;
    queue_dual_core_active_control(OtisRunControlKind::StatusQuery);
  } else if (command.kind == OtisSerialCommandKind::DualCoreQuery) {
    OtisDualCoreQueueStats queues;
    otis_dual_core_get_stats(&queues);
    emit_status_u32("dual_core", "service_to_timing_depth",
                    queues.service_to_timing_depth, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "observation_depth",
                    queues.observation_depth, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "monitor_observation_depth",
                    queues.monitor_observation_depth, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "monitor_observation_high_water",
                    queues.monitor_observation_high_water,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    emit_status_u32(
        "dual_core", "monitor_observation_dropped",
        queues.monitor_observation_dropped,
        queues.monitor_observation_dropped ? OTIS_SEVERITY_WARN
                                           : OTIS_SEVERITY_INFO,
        queues.monitor_observation_dropped
            ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
            : OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "critical_depth", queues.critical_depth,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "evidence_depth", queues.evidence_depth,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "telemetry_depth", queues.telemetry_depth,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "telemetry_dropped",
                    queues.telemetry_dropped,
                    queues.telemetry_dropped ? OTIS_SEVERITY_WARN
                                             : OTIS_SEVERITY_INFO,
                    queues.telemetry_dropped
                        ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                        : OTIS_FLAG_NONE);
    emit_status("dual_core", "fail_static",
                queues.fail_static ? "true" : "false",
                queues.fail_static ? OTIS_SEVERITY_ERROR
                                   : OTIS_SEVERITY_INFO,
                queues.fail_static ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                                   : OTIS_FLAG_NONE);
  } else if (command.kind == OtisSerialCommandKind::DacQuery) {
    emit_dac_status("dac");
  } else if (command.kind == OtisSerialCommandKind::DacLimitsQuery) {
    emit_status_u16_hex("dac", "min_code", OTIS_DAC_MIN_CODE,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
    emit_status_u16_hex("dac", "max_code", OTIS_DAC_MAX_CODE,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  } else if (command.kind == OtisSerialCommandKind::CountQuery) {
    const uint32_t nonce = dual_core_service_sequence + 1u;
    const bool requested = queue_dual_core_active_control(
        OtisRunControlKind::DiagnosticRuntimeQuery, nonce);
    emit_status("command", "timing_runtime_snapshot",
                requested ? "queued_to_core1" : "rejected_queue_fault",
                requested ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                requested ? OTIS_FLAG_NONE
                          : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  } else if (command.kind == OtisSerialCommandKind::ActiveQuery) {
    const bool accepted = queue_dual_core_active_control(
        OtisRunControlKind::StatusQuery);
    emit_status("adaptive_hybrid_regulation", "status_query",
                accepted ? "queued_to_core1" : "rejected_queue_fault",
                accepted ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                accepted ? OTIS_FLAG_NONE
                         : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  } else if (command.kind == OtisSerialCommandKind::ActiveSnapshot) {
    uint32_t values[OTIS_COMMAND_ACTIVE_SNAPSHOT_ARGUMENT_COUNT];
    const bool parsed = command.arguments_valid &&
                        otis_serial_command_parse_nonzero_decimal_u32_fields(
                            command.text_argument, values,
                            OTIS_COMMAND_ACTIVE_SNAPSHOT_ARGUMENT_COUNT) &&
                        values[0] != 0u;
    const bool accepted = parsed && queue_dual_core_active_control(
                                      OtisRunControlKind::StatusQuery,
                                      values[0]);
    emit_status("adaptive_hybrid_regulation", "snapshot_firmware_received",
                accepted ? "queued_to_core1" : "rejected",
                accepted ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                accepted ? OTIS_FLAG_NONE
                         : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  } else if (command.kind == OtisSerialCommandKind::ActiveMode) {
    const bool queued=queue_instrument_mode(command);
    emit_status("instrument_command","delivery",queued?"queued_to_core1":"rejected",queued?OTIS_SEVERITY_INFO:OTIS_SEVERITY_WARN,OTIS_FLAG_NONE);
  } else if (command.kind != OtisSerialCommandKind::Empty) {
    emit_status("command", "unknown", "rejected_unknown", OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
  }
}

void service_serial_commands(bool output_allowed = true) {
  if (output_allowed && deferred_serial_error ==
                            OtisSerialFrameEvent::RejectedTooLong) {
    deferred_serial_error = OtisSerialFrameEvent::None;
    emit_status("command", "line", "rejected_too_long", OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
    return;
  }
  if (output_allowed && deferred_serial_invalid) {
    deferred_serial_invalid = false;
    emit_status("command", "line", "rejected_invalid_character",
                OTIS_SEVERITY_WARN, OTIS_FLAG_NONE);
    return;
  }
  if (output_allowed && deferred_serial_command_ready) {
    OtisParsedSerialCommand command =
        otis_serial_command_parse(deferred_serial_command);
    deferred_serial_command_ready = false;
    execute_serial_command(command);
    return;
  }
  // One complete non-abort command may wait behind the current wire frame.
  // Leave later bytes in the USB RX buffer until that command is executed.
  if (!output_allowed && deferred_serial_command_ready) return;

  uint8_t byte_budget = 32u;
  while (Serial.available() > 0 && byte_budget-- > 0u) {
    OtisSerialFrameEvent event = otis_serial_frame_collect(
        &serial_command_collector, (char)Serial.read());
    if (event == OtisSerialFrameEvent::RejectedTooLong) {
      if (output_allowed)
        emit_status("command", "line", "rejected_too_long",
                    OTIS_SEVERITY_WARN, OTIS_FLAG_NONE);
      else
        deferred_serial_error = OtisSerialFrameEvent::RejectedTooLong;
      return;
    }
    if (event != OtisSerialFrameEvent::Complete) {
      continue;
    }

    if (otis_serial_frame_validate(&serial_command_collector) !=
        OtisSerialFrameValidation::Valid) {
      otis_serial_frame_collector_init(&serial_command_collector);
      if (output_allowed)
        emit_status("command", "line", "rejected_invalid_character",
                    OTIS_SEVERITY_WARN, OTIS_FLAG_NONE);
      else
        deferred_serial_invalid = true;
      return;
    }

    char complete_line[OTIS_SERIAL_COMMAND_BUFFER_SIZE] = {};
    snprintf(complete_line, sizeof(complete_line), "%s",
             serial_command_collector.line);
    OtisParsedSerialCommand command =
        otis_serial_command_parse(serial_command_collector.line);
    otis_serial_frame_collector_init(&serial_command_collector);
    if (!output_allowed) {
      if (command.kind == OtisSerialCommandKind::ActiveMode) {
        // Reserved HOLD delivery remains available while a USB frame is obstructed.
        queue_instrument_mode(command);
        return;
      }
      snprintf(deferred_serial_command, sizeof(deferred_serial_command), "%s",
               complete_line);
      deferred_serial_command_ready = true;
      return;
    }
    execute_serial_command(command);
    return;
  }
}

}  // namespace

void setup() {
  otis_memory_budget_note_current_core();
  otis_runtime_state_init(&runtime_state);
  otis_serial_frame_collector_init(&serial_command_collector);
  otis_status_emit_init(&status_emit_context,
                        &runtime_state.sequences.status_seq);
  configure_selected_capabilities();
  boot_phase_reset_entry();
  boot_phase_early_init();
  if (otis_boot_capability_has_fatal_conflict(&boot_capabilities)) {
    halt_boot(BootFatal::ResourceOwnershipConflict, BootPhase::EarlyInit);
  }
  if (otisBootSafeModeRequested()) {
    enter_safe_mode();
    __atomic_store_n(&dual_core_timing_boot_complete, true,
                     __ATOMIC_RELEASE);
    __atomic_store_n(&dual_core_service_boot_ready, true,
                     __ATOMIC_RELEASE);
    return;
  }

  boot_phase_clocks_init();
  boot_phase_gpio_init();
  boot_phase_ring_buffers_init();
  boot_phase_serial_init();
  boot_phase_protocol_banner();
  // Core 1 starts the single PIO reference owner after service initialization.
  boot_phase_peripherals_init();
  __atomic_store_n(&dual_core_service_boot_ready, true, __ATOMIC_RELEASE);
  const uint32_t timing_boot_wait_started_ms = millis();
  while (!__atomic_load_n(&dual_core_timing_boot_complete,
                          __ATOMIC_ACQUIRE) &&
         (uint32_t)(millis() - timing_boot_wait_started_ms) <
             kDualCoreBootHandshakeTimeoutMs) {
    // The receiver is already live at this point; drain its small UART FIFO
    // while Core 1 completes boot so startup cannot manufacture a truncated
    // NMEA frame or a false receiver-identity outage.
    otis_gnss_receiver_service(millis());
    service_instrument_executor();
    if (otis_transport_ready()) {
      service_dual_core_outputs();
    } else {
      discard_dual_core_outputs_before_first_carrier();
    }
    delay(1);
  }
  if (!__atomic_load_n(&dual_core_timing_boot_complete,
                       __ATOMIC_ACQUIRE)) {
    otis_dual_core_latch_fault(OtisPartitionFault::BootHandshakeTimeout);
    halt_boot(BootFatal::DualCoreHandshakeTimeout,
              BootPhase::CapabilityAudit);
  }
}

void setup1() {
  otis_memory_budget_note_current_core();
  otis_status_emit_init_with_sink(&dual_core_timing_status_context, nullptr,
                                  publish_dual_core_timing_status_sink);
  const uint32_t service_boot_wait_started_ms = millis();
  while (!__atomic_load_n(&dual_core_service_boot_ready, __ATOMIC_ACQUIRE) &&
         (uint32_t)(millis() - service_boot_wait_started_ms) <
             kDualCoreBootHandshakeTimeoutMs) {
    delay(1);
  }
  if (!__atomic_load_n(&dual_core_service_boot_ready, __ATOMIC_ACQUIRE))
    return;
  if (runtime_state.boot.safe_mode_active) {
    __atomic_store_n(&dual_core_timing_boot_complete, true,
                     __ATOMIC_RELEASE);
    return;
  }
  __atomic_store_n(&dual_core_timing_boot_in_progress, true,
                   __ATOMIC_RELEASE);
  otis_dual_core_set_timing_owner_active(true);
  boot_phase_timer_init();
  boot_phase_forwarded_output_init();
  boot_phase_forwarded_monitor_init();
  boot_phase_pps_input_init();
  boot_phase_preview_init();
  boot_phase_capability_audit();
  boot_phase_run_mode();
  // Do not overlap the first large periodic timing-health burst with the
  // final bounded boot-status drain on Core 0.
  dual_core_last_timing_status_ms = millis();
  __atomic_store_n(&dual_core_timing_boot_in_progress, false,
                   __ATOMIC_RELEASE);
  __atomic_store_n(&dual_core_timing_boot_complete, true,
                   __ATOMIC_RELEASE);
}

void loop1() {
  otis_memory_budget_note_current_core();
  if (!__atomic_load_n(&dual_core_timing_boot_complete,
                       __ATOMIC_ACQUIRE) ||
      runtime_state.boot.safe_mode_active) {
    return;
  }
  __atomic_store_n(&dual_core_timing_loop_started, true,
                   __ATOMIC_RELEASE);
  const uint32_t now_ms = millis();
  // Host attachment controls only delivery of the timing plane's outbound
  // records. It must never gate capture, witness, boundary, estimator, or
  // health service: those producers are already live and their finite queues
  // must remain continuously drained even when USB attaches late.
  // Progress instrumentation is deliberately bounded to four complete trace
  // samples per second.  The empty service-queue poll carries no diagnostic
  // atomic accounting, so the protected timing core's hot path stays lean.
  const bool trace_timing_loop = dual_core_timing_trace_due(now_ms);
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::LoopEnter,
                                        otis_monotonic_us32_now());
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::ServiceInput,
                                        otis_monotonic_us32_now());
  service_dual_core_timing_inputs();
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::BoundaryDrain,
                                        otis_monotonic_us32_now());
  drain_reference_snapshots();
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::GateService,
                                        otis_monotonic_us32_now());
  service_tcxo_gate();
  service_adaptive_hybrid_regulation_health();
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::TimingHealth,
                                        otis_monotonic_us32_now());
  publish_dual_core_timing_health(now_ms);
  otis_service_latency_live_timing_service();
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::LoopIdle,
                                        otis_monotonic_us32_now());
}

void loop() {
  otis_memory_budget_note_current_core();
  if (runtime_state.boot.safe_mode_active) {
    emit_boot_records_if_serial_ready();
    return;
  }

  // Core 0 is the sole GNSS UART/link-state owner. Core 1 must never service
  // this mutable state, including before the first USB carrier attaches.
  // Core 0 remains live in the carrier-absent branch below, so attachment is
  // not required for bounded UART drainage or bootstrap progress.
  const uint32_t now_ms = millis();
  otis_gnss_receiver_service(now_ms);
  service_instrument_executor();
  publish_dual_core_service_metadata(now_ms);
  if (!otis_transport_ready()) {
    abandon_dual_core_serial_frames_on_carrier_loss();
    discard_dual_core_outputs_before_first_carrier();
    service_serial_commands(false);
    return;
  }
  // Keep the active whole frame until completed. A stalled reader can fill and
  // discard outbound queues, but never changes instrument mode or authority.
  const bool frame_active = service_dual_core_serial_frame_transport();
  if (frame_active) {
    // RX and explicit abort remain bounded even while no other writer may
    // interleave bytes with the active frame.
    service_serial_commands(false);
    return;
  }
  emit_protocol_banner_if_serial_ready();
  emit_run_mode_status_if_ready();
  service_core0_description();
  emit_resource_ownership_status();
  emit_periodic_status();
  service_dual_core_outputs();
  service_serial_commands();
  service_environment_sensors();
}
