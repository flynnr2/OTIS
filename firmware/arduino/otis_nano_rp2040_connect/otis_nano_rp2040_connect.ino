#include <Arduino.h>
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "otis_config.h"

#include "OtisBootConfig.h"
#include "otis_board.h"
#include "otis_boot_capabilities.h"
#include "otis_boot_diag.h"
#include "otis_capture_backend.h"
#include "otis_capture_irq.h"
#include "otis_capture_pio.h"
#include "otis_capture_ring.h"
#include "otis_count_observation.h"
#include "otis_cx317_active_actuator.h"
#include "otis_cx317_active_live.h"
#include "otis_cx317_dual_core_state.h"
#include "otis_cx317_preview_live.h"
#include "otis_phase_preview_live.h"
#include "otis_phase_preview_transport.h"
#include "otis_dac_ad5693r.h"
#include "otis_dual_core_partition.h"
#include "otis_dual_core_receiver_gate.h"
#include "otis_emit.h"
#include "otis_env_sensors.h"
#include "otis_gnss_receiver.h"
#include "otis_memory_budget.h"
#include "otis_modes.h"
#include "otis_observe_only_discipline_live.h"
#include "otis_pps_count_boundary_ring.h"
#include "otis_pps_dual_observer.h"
#include "otis_pps_snapshot_backend.h"
#include "otis_pseudo_pps.h"
#include "otis_protocol.h"
#include "otis_resource_registry.h"
#include "otis_runtime_state.h"
#include "otis_serial_frame_arbiter.h"
#include "otis_serial_command.h"
#include "otis_status_emit.h"
#include "otis_status_led.h"
#include "otis_timebase.h"
#include "otis_transport_serial.h"
#include "otis_transport_liveness.h"

#if OTIS_ENABLE_DUAL_CORE_PARTITION
// Arduino-Pico otherwise splits one 8 KiB stack between both cores.  The
// timing/estimator path has bounded local formatting buffers, so give Core 1
// its own full 8 KiB stack as supported by the pinned core.
bool core1_separate_stack = true;
#endif

#if OTIS_ENABLE_PPS_DUAL_OBSERVER && \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
#error "OTIS_ENABLE_PPS_DUAL_OBSERVER requires D10 as a PPS input; GPIO loopback drives/uses D10 incompatibly."
#endif

#if OTIS_ENABLE_PPS_DUAL_OBSERVER && \
    OTIS_CAPTURE_BACKEND != OTIS_CAPTURE_BACKEND_IRQ
#error "OTIS_ENABLE_PPS_DUAL_OBSERVER currently compares against D14 IRQ diagnostics; keep OTIS_CAPTURE_BACKEND_IRQ for this H1 witness run."
#endif

namespace {

#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
constexpr uint32_t kStatusPeriodMs = OTIS_PPS_GATE_STATUS_PERIOD_MS;
#else
constexpr uint32_t kStatusPeriodMs = OTIS_STATUS_PERIOD_MS;
#endif
constexpr uint32_t kLoopbackTogglePeriodMs = OTIS_LOOPBACK_TOGGLE_PERIOD_MS;
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE
constexpr uint32_t kTcxoGatePeriodUs = OTIS_H1_LONG_GATE_PERIOD_US;
#else
constexpr uint32_t kTcxoGatePeriodUs = OTIS_TCXO_GATE_PERIOD_US;
#endif
constexpr uint32_t kTcxoMeasurePeriodMs = OTIS_TCXO_MEASURE_PERIOD_MS;
constexpr uint32_t kFc0StartupInhibitMs = OTIS_FC0_STARTUP_INHIBIT_MS;
constexpr uint32_t kFc0ControlReadyCleanWindows =
    OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS;

OtisRuntimeState runtime_state;
OtisStatusEmitContext status_emit_context;
OtisSerialFrameCollector serial_command_collector;
bool deferred_serial_command_ready = false;
char deferred_serial_command[OTIS_SERIAL_COMMAND_BUFFER_SIZE] = {};
OtisSerialFrameEvent deferred_serial_error = OtisSerialFrameEvent::None;
bool deferred_serial_invalid = false;
bool deferred_abort_result_ready = false;
bool deferred_abort_queued = false;
OtisBootCapabilityTracker boot_capabilities;
bool resource_ownership_status_emitted = false;
bool boot_capability_status_emitted = false;
bool run_mode_status_emitted = false;
bool transport_started = false;
bool config_query_provenance_emitted = false;

#if OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP
bool cx318_stage4_premise_write_consumed = false;
#endif

#if OTIS_ENABLE_DUAL_CORE_PARTITION
constexpr uint32_t kDualCoreTimingTracePeriodMs = 250u;
bool dual_core_service_boot_ready = false;
bool dual_core_timing_boot_complete = false;
bool dual_core_timing_boot_in_progress = false;
constexpr uint32_t kDualCoreBootHandshakeTimeoutMs = 10000u;
uint32_t dual_core_service_sequence = 0u;
uint32_t dual_core_timing_telemetry_sequence = 0u;
uint32_t dual_core_diagnostic_snapshot_generation = 0u;
uint32_t dual_core_last_metadata_ms = 0u;
uint32_t dual_core_last_timing_status_ms = 0u;
uint32_t dual_core_receiver_invalidation_until_ms = 0u;
bool dual_core_receiver_fixture_invalid = false;
bool dual_core_timing_trace_started = false;
uint32_t dual_core_last_timing_trace_ms = 0u;
uint32_t dual_core_association_loss_decision_sequence = 0u;
OtisCx317StaticCodeState dual_core_static_code = {};
OtisReceiverQualificationMessage dual_core_receiver = {};
// Association-loss publication runs on the bounded timing-core stack. Keep
// its full evidence-frame formatter in static storage; Core 1 is the only
// producer and the publication is synchronous.
OtisEvidenceFrameMessage dual_core_association_loss_scratch = {};
OtisEvidenceFrameMessage dual_core_evidence_transport = {};
uint16_t dual_core_evidence_transport_sent = 0u;
bool dual_core_evidence_transport_active = false;
OtisSerialFrameArbiter dual_core_serial_frame_arbiter = {
    OtisSerialFrameOwner::None,
    static_cast<uint8_t>(OtisSerialFrameOwner::DualCoreEvidence),
};
OtisTransportLiveness dual_core_transport_liveness = {};
bool dual_core_transport_abort_queued = false;
bool dual_core_serial_carrier_seen = false;
uint32_t dual_core_pre_carrier_records_discarded = 0u;
OtisStatusEmitContext dual_core_timing_status_context = {};
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
OtisActuatorTransactionGuard dual_core_service_actuator_guard = {};
OtisSetupAuthorityGuard dual_core_timing_setup_guard = {};
OtisSetupExecutionGuard dual_core_service_setup_guard = {};
bool dual_core_manual_start_consumed = false;
#endif
#endif

bool parse_active_u32_fields(char *text, uint32_t *values, uint8_t count) {
  if (text == nullptr || values == nullptr || count == 0u) return false;
  char *cursor = text;
  for (uint8_t index = 0u; index < count; ++index) {
    while (*cursor != '\0' && isspace(static_cast<unsigned char>(*cursor)))
      cursor++;
    if (!isdigit(static_cast<unsigned char>(*cursor))) return false;
    errno = 0;
    char *end = nullptr;
    unsigned long value = strtoul(cursor, &end, 0);
    if (end == cursor || errno == ERANGE || value > UINT32_MAX) return false;
    values[index] = static_cast<uint32_t>(value);
    cursor = end;
  }
  while (*cursor != '\0' && isspace(static_cast<unsigned char>(*cursor)))
    cursor++;
  return *cursor == '\0';
}

#if OTIS_ENABLE_DUAL_CORE_PARTITION
bool queue_dual_core_active_control(OtisRunControlKind kind,
                                    uint32_t first = 0u,
                                    uint32_t second = 0u,
                                    uint32_t third = 0u) {
  OtisServiceMessage control = {};
  control.kind = OtisServiceMessageKind::RunControl;
  control.run_control.sequence = dual_core_service_sequence++;
  control.run_control.published_ticks = otis_capture_ticks_now();
  control.run_control.kind = kind;
  control.run_control.asserted = true;
  if (kind == OtisRunControlKind::CaptureLease)
    control.run_control.capture_lease_sequence = first;
  else if (kind == OtisRunControlKind::Arm) {
    control.run_control.authorization_sequence = first;
    control.run_control.nonce = second;
    control.run_control.expires_s = third;
  } else if (kind == OtisRunControlKind::EvidenceRelease) {
    control.run_control.request_sequence = first;
    control.run_control.evidence_phase = second;
  } else if (kind == OtisRunControlKind::DiagnosticConfigQuery ||
             kind == OtisRunControlKind::DiagnosticRuntimeQuery) {
    control.run_control.nonce = first;
  } else if (kind == OtisRunControlKind::StatusQuery) {
    control.run_control.nonce = first;
  }
  return otis_dual_core_publish_service(&control);
}


bool queue_dual_core_setup_authorization(
    OtisSetupAuthorityRequest &request) {
  OtisServiceMessage control = {};
  control.kind = OtisServiceMessageKind::RunControl;
  control.run_control.sequence = ++dual_core_service_sequence;
  if (control.run_control.sequence == 0u)
    control.run_control.sequence = ++dual_core_service_sequence;
  control.run_control.published_ticks = otis_capture_ticks_now();
  control.run_control.kind = OtisRunControlKind::SetupAuthorize;
  control.run_control.asserted = true;
  control.run_control.setup_request = request;
  control.run_control.setup_request.command_sequence =
      control.run_control.sequence;
  const bool published = otis_dual_core_publish_service(&control);
  if (published) request.command_sequence = control.run_control.sequence;
  return published;
}
#endif

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

#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::SparseCapture,
                              OtisBootCapabilityRequirement::Required);
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPS_PPS || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::SparseCapture,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::PpsCapture,
                              OtisBootCapabilityRequirement::Required);
#if OTIS_ENABLE_PPS_DUAL_OBSERVER
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::PpsWitness,
                              OtisBootCapabilityRequirement::Optional);
#endif
#endif

#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::CountBackend,
                              OtisBootCapabilityRequirement::Required);
#endif

#if OTIS_ENABLE_PSEUDO_PPS_GENERATOR
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::PseudoPpsGenerator,
                              OtisBootCapabilityRequirement::Required);
#endif

#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE && \
    OTIS_ENABLE_DAC_AD5693R
  otis_boot_capability_select(&boot_capabilities, OtisBootCapability::Dac,
                              OtisBootCapabilityRequirement::Required);
#endif
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE && \
    OTIS_ENABLE_ENV_SENSORS && \
    (OTIS_ENABLE_ENV_SHT4X || OTIS_ENABLE_ENV_BMP280)
  otis_boot_capability_select(&boot_capabilities, OtisBootCapability::Sensors,
#if OTIS_ENABLE_PHASE_FREQUENCY_PREVIEW
                              OtisBootCapabilityRequirement::Required);
#else
                              OtisBootCapabilityRequirement::Optional);
#endif
#endif
#if OTIS_ENABLE_GNSS_RECEIVER
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::GnssReceiver,
                              OtisBootCapabilityRequirement::Required);
#endif
#if OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW || OTIS_ENABLE_CX317_I_ONLY_PREVIEW
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::Phase4Preview,
                              OtisBootCapabilityRequirement::Required);
#endif
#if OTIS_ENABLE_PHASE_FREQUENCY_PREVIEW
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::PhasePreview,
                              OtisBootCapabilityRequirement::Required);
#endif
}

void emit_selected_capability_status();
void emit_resource_ownership_status();
void emit_protocol_banner_if_serial_ready();

void emit_boot_records_if_serial_ready(void) {
  if (runtime_state.boot.summary_emitted || !otis_transport_ready()) {
    return;
  }

  emitOtisBootSummary(Serial, runtime_state.boot.phase);
  if (runtime_state.boot.serial_absent_warn_pending) {
    emitOtisBootWarnSerialAbsent(Serial, kOtisSerialWaitMs);
    runtime_state.boot.serial_absent_warn_pending = false;
  }
  if (runtime_state.boot.safe_mode_warn_pending) {
    emitOtisBootWarnSafeMode(Serial);
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
  otis_status_led_set(OTIS_SYSTEM_STATE_FATAL_CONFIG_FAULT);

  bool fatal_emitted = false;
  if (!transport_started) {
    transport_started = otis_transport_begin(kOtisSerialBaud);
    wait_for_serial_or_timeout();
  }
  if (otis_transport_ready()) {
    emit_protocol_banner_if_serial_ready();
    emit_selected_capability_status();
    emit_resource_ownership_status();
    otis_pseudo_pps_service();
    emitOtisBootFatal(Serial, fatal, failed_phase);
    fatal_emitted = true;
  }

  while (true) {
    if (otis_transport_ready() && !fatal_emitted) {
      emit_protocol_banner_if_serial_ready();
      emit_selected_capability_status();
      emit_resource_ownership_status();
      otis_pseudo_pps_service();
      emitOtisBootFatal(Serial, fatal, failed_phase);
      fatal_emitted = true;
    }
    otis_status_led_poll(millis());
    delay(10);
  }
}

void enter_safe_mode(void) {
  runtime_state.boot.safe_mode_active = true;
  runtime_state.boot.safe_mode_warn_pending = true;
  enter_boot_phase(BootPhase::Fatal);
  otisBootBreadcrumbSetSafeModeFatal(BootFatal::RepeatedBootFailure);

  otis_status_led_begin();
  transport_started = otis_transport_begin(kOtisSerialBaud);
  wait_for_serial_or_timeout();
  otis_status_led_set(OTIS_SYSTEM_STATE_FATAL_CONFIG_FAULT);
  emit_protocol_banner_if_serial_ready();
  emit_selected_capability_status();
  emit_resource_ownership_status();
}

const char *edge_string(char edge);
const char *osc_observation_domain(void);
OtisCountObservationConfig count_observation_config(void);
#if OTIS_ENABLE_H1_DAC_SWEEP && \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
void emit_h1_dac_sweep_fc0_window(void);
#endif

void emit_status(const char *component, const char *key, const char *value,
                 const char *severity, uint32_t flags) {
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  if (__atomic_load_n(&dual_core_timing_boot_in_progress,
                      __ATOMIC_ACQUIRE)) {
    OtisTelemetryMessage message = {};
    message.timestamp_ticks = otis_capture_ticks_now();
    message.flags = flags;
    snprintf(message.component, sizeof(message.component), "%s", component);
    snprintf(message.key, sizeof(message.key), "%s", key);
    snprintf(message.value, sizeof(message.value), "%s", value);
    snprintf(message.severity, sizeof(message.severity), "%s", severity);
    otis_dual_core_publish_boot_telemetry(&message);
    return;
  }
#endif
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

#if OTIS_ENABLE_DUAL_CORE_PARTITION
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
      &dual_core_receiver, otis_capture_ticks_now(),
      OTIS_GNSS_METADATA_MAX_AGE_MS);
}

void publish_dual_core_timing_status(const char *component, const char *key,
                                     const char *value,
                                     const char *severity, uint32_t flags) {
  OtisTelemetryMessage message = {};
  message.sequence = ++dual_core_timing_telemetry_sequence;
  message.timestamp_ticks = otis_capture_ticks_now();
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

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
void publish_dual_core_active_status_field(void *, const char *key,
                                           const char *value,
                                           const char *severity,
                                           uint32_t flags) {
  publish_dual_core_timing_status("cx317_active", key, value, severity, flags);
}

void publish_dual_core_active_status(uint32_t now_ms) {
  otis_cx317_active_live_visit_status(
      nullptr, publish_dual_core_active_status_field, now_ms / 1000u);
}

OtisSetupAuthorityContext current_dual_core_setup_authority_context(
    uint32_t now_s) {
  OtisCx317ActiveLiveStatus active = {};
  otis_cx317_active_live_get_status(&active, now_s);
  return {
      now_s,
      otis_cx317_active_live_status_snapshot_generation(),
      active.query_nonce,
      active.session_id,
      active.expected_setup_code,
      OTIS_BUILD_CONFIG_SHA256,
      active.capture_lease_live,
      active.setup_gnss_eligible && dual_core_receiver_qualified_for_control() &&
          dual_core_receiver.identity_stable && dual_core_receiver.gsa_3d,
      active.setup_reference_eligible,
      active.setup_partition_healthy,
      active.state != nullptr && strcmp(active.state, "DISARMED") == 0,
      !active.manual_start_confirmed,
  };
}

OtisSetupExecutionContext current_dual_core_setup_execution_context(
    uint32_t now_s) {
  OtisDacAd5693rStatus dac = {};
  otis_dac_ad5693r_get_status(&dac);
  return {
      now_s,
      static_cast<uint16_t>(OTIS_CX317_ACTIVE_START_CODE),
      OTIS_BUILD_CONFIG_SHA256,
      !otis_dual_core_fail_static(),
      dac.enabled && dac.initialized,
  };
}

void publish_dual_core_setup_phase(const char *phase,
                                   const OtisSetupAuthorityRequest &request,
                                   const char *severity) {
  publish_dual_core_timing_status("cx317_setup", "phase", phase, severity,
                                  OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "cx317_setup", "command_sequence", request.command_sequence, severity,
      OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "cx317_setup", "authorization_sequence",
      request.authorization_sequence, severity, OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "cx317_setup", "status_generation", request.status_generation,
      severity, OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "cx317_setup", "query_nonce", request.query_nonce, severity,
      OTIS_FLAG_NONE);
}
#endif

void publish_dual_core_timing_health(uint32_t now_ms) {
  if ((uint32_t)(now_ms - dual_core_last_timing_status_ms) < kStatusPeriodMs)
    return;
  dual_core_last_timing_status_ms = now_ms;

  const uint32_t capture_dropped = otis_capture_ring_dropped_count();
  const uint32_t boundary_dropped =
      otis_pps_count_boundary_ring_dropped_count();
  const uint32_t drop_flags = capture_dropped || boundary_dropped
                                  ? OTIS_FLAG_CAPTURE_RING_OVERRUN
                                  : OTIS_FLAG_NONE;
  publish_dual_core_timing_status_u32(
      "capture", "event_count", runtime_state.capture.emitted_event_count,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "capture", "dropped_count", capture_dropped,
      capture_dropped ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO, drop_flags);
  publish_dual_core_timing_status_u32(
      "capture", "pps_count_boundary_dropped_count", boundary_dropped,
      boundary_dropped ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
      drop_flags);
  publish_dual_core_timing_status_u32(
      "capture", "error_flags", drop_flags,
      drop_flags ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO, drop_flags);

  otis_count_observation_emit_status(&runtime_state,
                                     &dual_core_timing_status_context);

  OtisCaptureIrqReferenceStats d14;
  otis_capture_irq_get_reference_stats(&d14);
  publish_dual_core_timing_status_u32(
      "pps_d14", "raw_edge_count", d14.d14_raw_edge_count,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "pps_d14", "accepted_pps_count", d14.d14_accepted_pps_count,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "pps_d14", "rejected_short_count", d14.d14_rejected_short_count,
      d14.d14_rejected_short_count ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
      d14.d14_rejected_short_count ? OTIS_FLAG_PULSE_TOO_NARROW
                                   : OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "pps_d14", "rejected_long_count", d14.d14_rejected_long_count,
      d14.d14_rejected_long_count ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
      d14.d14_rejected_long_count ? OTIS_FLAG_PULSE_TOO_WIDE
                                  : OTIS_FLAG_NONE);

  OtisPpsDualObserverStats d10;
  otis_pps_dual_observer_get_stats(&d10);
  publish_dual_core_timing_status_u32(
      "pps_d10", "raw_edge_count", d10.d10_raw_edge_count,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "pps_d10", "short_interval_count", d10.d10_short_interval_count,
      d10.d10_short_interval_count ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
      d10.d10_short_interval_count ? OTIS_FLAG_PULSE_TOO_NARROW
                                   : OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "pps_d10", "buffer_overflow_count", d10.d10_buffer_overflow_count,
      d10.d10_buffer_overflow_count ? OTIS_SEVERITY_WARN
                                    : OTIS_SEVERITY_INFO,
      d10.d10_buffer_overflow_count ? OTIS_FLAG_CAPTURE_RING_OVERRUN
                                    : OTIS_FLAG_NONE);
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  publish_dual_core_active_status(now_ms);
#endif
}

void publish_dual_core_service_metadata(uint32_t now_ms) {
  if ((uint32_t)(now_ms - dual_core_last_metadata_ms) < 1000u) return;
  dual_core_last_metadata_ms = now_ms;

#if OTIS_ENABLE_GNSS_RECEIVER
  OtisGnssReceiverSnapshot gnss;
  otis_gnss_receiver_get_snapshot(now_ms, &gnss);
  OtisServiceMessage receiver = {};
  receiver.kind = OtisServiceMessageKind::ReceiverQualification;
  receiver.receiver.sequence = dual_core_service_sequence++;
  receiver.receiver.published_ticks = otis_capture_ticks_now();
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
#endif

  OtisDacAd5693rStatus dac;
  otis_dac_ad5693r_get_status(&dac);
  OtisServiceMessage applied = {};
  applied.kind = OtisServiceMessageKind::AppliedDacState;
  applied.dac.sequence = dual_core_service_sequence++;
  applied.dac.published_ticks = otis_capture_ticks_now();
  applied.dac.requested_code = dac.last_requested_code;
  applied.dac.applied_code = dac.last_applied_code;
  applied.dac.initialized = dac.initialized;
  applied.dac.i2c_ok = dac.last_write_ok;
  applied.dac.requested_applied_match =
      dac.applied_code_known && dac.last_write_ok &&
      dac.last_requested_code == dac.last_applied_code;
  otis_dual_core_publish_service(&applied);
}

void service_dual_core_timing_inputs(void) {
  OtisServiceMessage message;
  for (uint32_t consumed = 0u;
       consumed < OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH; ++consumed) {
    if (!otis_dual_core_take_service(&message)) break;
    if (message.kind == OtisServiceMessageKind::ReceiverQualification) {
      dual_core_receiver = message.receiver;
      const uint32_t now_ms = millis();
      if (dual_core_receiver_fixture_invalid &&
          (int32_t)(dual_core_receiver_invalidation_until_ms - now_ms) > 0) {
        dual_core_receiver.control_eligible = false;
        dual_core_receiver.gsa_3d = false;
      } else if (dual_core_receiver_fixture_invalid) {
        dual_core_receiver_fixture_invalid = false;
        OtisCriticalRecordMessage transition = {};
        transition.kind = OtisCriticalMessageKind::StateTransition;
        transition.sequence = message.receiver.sequence;
        transition.timestamp_ticks = message.receiver.published_ticks;
        snprintf(transition.component, sizeof(transition.component), "%s",
                 "gnss_qualification");
        snprintf(transition.reason, sizeof(transition.reason), "%s",
                 dual_core_receiver.control_eligible
                     ? "receiver_metadata_requalified"
                     : "receiver_metadata_remains_unqualified");
        otis_dual_core_publish_critical(&transition);
      }
      continue;
    }
    if (message.kind == OtisServiceMessageKind::Environment) {
      otis_cx317_preview_live_on_temperature(
          message.environment.temperature_valid,
          message.environment.temperature_c,
          millis() / 1000u);
      continue;
    }
    if (message.kind == OtisServiceMessageKind::AppliedDacState) {
      const bool changed =
          otis_cx317_dual_core_static_state_on_periodic(
              &dual_core_static_code, &message.dac);
      if (changed) {
#if !OTIS_ENABLE_CX317_BOUNDED_ACTIVE
        otis_cx317_preview_live_on_dac_applied(
            dual_core_static_code.applied_code, millis() / 1000u);
#endif
      }
      continue;
    }
    if (message.kind ==
        OtisServiceMessageKind::ActuatorAcknowledgement) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
      const bool transaction_acknowledged =
          otis_cx317_active_live_on_cross_core_ack(
              &message.actuator_acknowledgement, millis() / 1000u);
      if (message.actuator_acknowledgement.kind ==
              OtisActuatorAckKind::Applied &&
          !otis_cx317_dual_core_static_state_on_applied_ack(
              &dual_core_static_code, &message.actuator_acknowledgement,
              transaction_acknowledged))
        otis_dual_core_latch_fault(
            OtisPartitionFault::ActuatorAcknowledgementMismatch);
#endif
      continue;
    }
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
    if (message.kind ==
        OtisServiceMessageKind::SetupApplicationAcknowledgement) {
      const OtisSetupApplicationAck &ack = message.setup_acknowledgement;
      const bool acknowledged = otis_setup_authority_acknowledge(
          &dual_core_timing_setup_guard, &ack);
      if (ack.kind == OtisSetupApplicationAck::Kind::Core0Accepted &&
          acknowledged) {
        OtisSetupAuthorization released = {};
        const OtisSetupAuthorityContext current =
            current_dual_core_setup_authority_context(millis() / 1000u);
        if (otis_setup_authority_release_execution(
                &dual_core_timing_setup_guard, &current, &released)) {
          OtisCriticalRecordMessage execute = {};
          execute.kind = OtisCriticalMessageKind::SetupExecute;
          execute.sequence = released.request.command_sequence;
          execute.timestamp_ticks = otis_capture_ticks_now();
          execute.setup_authorization = released;
          snprintf(execute.component, sizeof(execute.component), "%s",
                   "cx317_setup");
          snprintf(execute.reason, sizeof(execute.reason), "%s",
                   "core1_execution_released_after_current_recheck");
          publish_dual_core_setup_phase("core1_execution_released",
                                        released.request,
                                        OTIS_SEVERITY_INFO);
          if (!otis_dual_core_publish_critical(&execute))
            otis_cx317_active_live_abort(
                "setup_execution_release_queue_fault");
        } else {
          publish_dual_core_setup_phase(
              "core1_rejected_authority_regression",
              dual_core_timing_setup_guard.pending.request,
              OTIS_SEVERITY_ERROR);
          otis_cx317_active_live_abort(
              "setup_authority_regressed_before_execution");
        }
      } else if (ack.kind == OtisSetupApplicationAck::Kind::Applied &&
                 acknowledged) {
        publish_dual_core_setup_phase(
            "applied", dual_core_timing_setup_guard.pending.request,
            OTIS_SEVERITY_INFO);
        otis_cx317_active_live_note_manual_start(
            ack.applied_code, true, millis() / 1000u);
      } else {
        publish_dual_core_setup_phase(
            ack.kind == OtisSetupApplicationAck::Kind::Failed
                ? "failed"
                : "core1_rejected",
            dual_core_timing_setup_guard.pending.request,
            OTIS_SEVERITY_ERROR);
        otis_cx317_active_live_note_manual_start(
            ack.requested_code, false, millis() / 1000u);
        if (!acknowledged &&
            strcmp(dual_core_timing_setup_guard.reason,
                   "setup_application_acknowledgement_mismatch") == 0)
          otis_dual_core_latch_fault(
              OtisPartitionFault::ActuatorAcknowledgementMismatch);
      }
      continue;
    }
#endif
    if (message.kind == OtisServiceMessageKind::RunControl) {
      OtisCriticalRecordMessage transition = {};
      transition.kind = OtisCriticalMessageKind::StateTransition;
      transition.sequence = message.run_control.sequence;
      transition.timestamp_ticks = message.run_control.published_ticks;
      if (message.run_control.kind ==
          OtisRunControlKind::SyntheticReceiverInvalidation) {
        dual_core_receiver.control_eligible = false;
        dual_core_receiver.gsa_3d = false;
        dual_core_receiver_fixture_invalid = true;
        dual_core_receiver_invalidation_until_ms =
            millis() + message.run_control.duration_ms;
        snprintf(transition.component, sizeof(transition.component), "%s",
                 "gnss_qualification");
        snprintf(transition.reason, sizeof(transition.reason), "%s",
                 "controlled_fixture_invalidation");
        otis_dual_core_publish_critical(&transition);
      } else if (message.run_control.kind == OtisRunControlKind::Recover) {
        const bool accepted =
            dual_core_receiver_qualified_for_control() &&
            otis_cx317_preview_live_request_recovery();
        snprintf(transition.component, sizeof(transition.component), "%s",
                 "cx317_preview");
        snprintf(transition.reason, sizeof(transition.reason), "%s",
                 accepted ? "explicit_recovery_accepted_fresh_support_required"
                          : "explicit_recovery_rejected_not_qualified_or_not_faulted");
        otis_dual_core_publish_critical(&transition);
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
      } else if (message.run_control.kind ==
                 OtisRunControlKind::CaptureLease) {
        const bool accepted = otis_cx317_active_live_capture_lease(
            message.run_control.capture_lease_sequence,
            millis() / 1000u);
        snprintf(transition.component, sizeof(transition.component), "%s",
                 "cx317_active");
        snprintf(transition.reason, sizeof(transition.reason), "%s",
                 accepted ? "capture_lease_accepted_on_core1"
                          : "capture_lease_rejected_on_core1");
        otis_dual_core_publish_critical(&transition);
      } else if (message.run_control.kind == OtisRunControlKind::Arm) {
        const bool accepted = otis_cx317_active_live_arm(
            message.run_control.authorization_sequence,
            message.run_control.nonce, message.run_control.expires_s,
            millis() / 1000u);
        snprintf(transition.component, sizeof(transition.component), "%s",
                 "cx317_active");
        snprintf(transition.reason, sizeof(transition.reason), "%s",
                 accepted ? "arm_accepted_on_core1"
                          : "arm_rejected_on_core1");
        otis_dual_core_publish_critical(&transition);
      } else if (message.run_control.kind ==
                 OtisRunControlKind::SetupAuthorize) {
        OtisSetupAuthorization authorization = {};
        const OtisSetupAuthorityContext current =
            current_dual_core_setup_authority_context(millis() / 1000u);
        const bool accepted = otis_setup_authorize(
            &dual_core_timing_setup_guard,
            &message.run_control.setup_request, &current, &authorization);
        publish_dual_core_setup_phase(
            accepted ? "core1_authorized" : "core1_rejected",
            message.run_control.setup_request,
            accepted ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR);
        if (accepted) {
          OtisCriticalRecordMessage setup = {};
          setup.kind = OtisCriticalMessageKind::SetupAuthorization;
          setup.sequence = authorization.request.command_sequence;
          setup.timestamp_ticks = otis_capture_ticks_now();
          setup.setup_authorization = authorization;
          snprintf(setup.component, sizeof(setup.component), "%s",
                   "cx317_setup");
          snprintf(setup.reason, sizeof(setup.reason), "%s",
                   "core1_current_setup_authority_accepted");
          if (!otis_dual_core_publish_critical(&setup))
            otis_cx317_active_live_abort(
                "setup_authorization_queue_fault");
        } else {
          otis_cx317_active_live_abort(
              "setup_current_authority_rejected");
        }
      } else if (message.run_control.kind == OtisRunControlKind::Abort) {
        otis_cx317_active_live_abort("device_abort_command_via_core0");
        snprintf(transition.component, sizeof(transition.component), "%s",
                 "cx317_active");
        snprintf(transition.reason, sizeof(transition.reason), "%s",
                 "abort_accepted_on_core1");
        otis_dual_core_publish_critical(&transition);
      } else if (message.run_control.kind ==
                 OtisRunControlKind::EvidenceRelease) {
        const bool accepted = otis_cx317_active_live_acknowledge_evidence(
            message.run_control.request_sequence,
            message.run_control.evidence_phase, millis() / 1000u);
        snprintf(transition.component, sizeof(transition.component), "%s",
                 "cx317_active");
        snprintf(transition.reason, sizeof(transition.reason), "%s",
                 accepted ? "evidence_release_accepted_on_core1"
                          : "evidence_release_rejected_on_core1");
        otis_dual_core_publish_critical(&transition);
      } else if (message.run_control.kind ==
                 OtisRunControlKind::StatusQuery) {
        otis_cx317_active_live_set_status_query_nonce(
            message.run_control.nonce);
        snprintf(transition.component, sizeof(transition.component), "%s",
                 "cx317_active");
        snprintf(transition.reason, sizeof(transition.reason), "%s",
                 "status_query_received_on_core1");
        otis_dual_core_publish_critical(&transition);
        publish_dual_core_active_status(millis());
#endif
      } else if (message.run_control.kind ==
                     OtisRunControlKind::DiagnosticConfigQuery ||
                 message.run_control.kind ==
                     OtisRunControlKind::DiagnosticRuntimeQuery) {
        publish_dual_core_diagnostic_snapshot(
            message.run_control.kind, message.run_control.sequence,
            message.run_control.nonce);
      }
    }
  }
}

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
bool publish_dual_core_actuator_ack(const OtisCrossCoreActuatorAck &ack) {
  OtisServiceMessage service = {};
  service.kind = OtisServiceMessageKind::ActuatorAcknowledgement;
  service.actuator_acknowledgement = ack;
  return otis_dual_core_publish_service(&service);
}

void service_dual_core_actuator_request(
    const OtisCriticalRecordMessage &critical) {
  const OtisCrossCoreActuatorRequest &request = critical.request;
  OtisCrossCoreActuatorAck acknowledgement = {};
  acknowledgement.request_sequence = request.request_sequence;
  acknowledgement.decision_sequence = request.decision_sequence;
  acknowledgement.authorization_sequence = request.authorization_sequence;
  acknowledgement.nonce = request.nonce;
  acknowledgement.acknowledgement_ticks = otis_capture_ticks_now();
  acknowledgement.requested_code = request.requested_code;

  if (critical.kind == OtisCriticalMessageKind::ActuatorRequest) {
    const bool accepted = !otis_dual_core_fail_static() &&
                          otis_actuator_guard_start(
                              &dual_core_service_actuator_guard, &request,
                              millis() / 1000u);
    acknowledgement.kind = accepted ? OtisActuatorAckKind::Accepted
                                    : OtisActuatorAckKind::Rejected;
    acknowledgement.accepted_code =
        accepted ? request.requested_code : request.current_applied_code;
    if (accepted && !otis_actuator_guard_acknowledge(
                        &dual_core_service_actuator_guard,
                        &acknowledgement)) {
      acknowledgement.kind = OtisActuatorAckKind::Rejected;
      acknowledgement.accepted_code = request.current_applied_code;
    }
    publish_dual_core_actuator_ack(acknowledgement);
    return;
  }

  if (critical.kind != OtisCriticalMessageKind::ActuatorExecute ||
      otis_dual_core_fail_static() ||
      dual_core_service_actuator_guard.state !=
          OtisActuatorGuardState::AwaitingApplication ||
      !otis_actuator_guard_check_deadline(&dual_core_service_actuator_guard,
                                          millis() / 1000u)) {
    acknowledgement.kind = OtisActuatorAckKind::Rejected;
    acknowledgement.accepted_code = request.current_applied_code;
    publish_dual_core_actuator_ack(acknowledgement);
    return;
  }

  const OtisCrossCoreActuatorRequest &pending =
      dual_core_service_actuator_guard.pending;
  const bool exact_release =
      request.request_sequence == pending.request_sequence &&
      request.decision_sequence == pending.decision_sequence &&
      request.authorization_sequence == pending.authorization_sequence &&
      request.nonce == pending.nonce &&
      request.requested_code == pending.requested_code &&
      request.current_applied_code == pending.current_applied_code &&
      request.correction_ordinal == pending.correction_ordinal;
  if (!exact_release) {
    acknowledgement.kind = OtisActuatorAckKind::Rejected;
    acknowledgement.accepted_code = pending.current_applied_code;
    publish_dual_core_actuator_ack(acknowledgement);
    otis_dual_core_latch_fault(
        OtisPartitionFault::ActuatorAcknowledgementMismatch);
    return;
  }

  const OtisCx317ActionableRequest actionable = {
      pending.request_sequence,
      pending.authorization_sequence,
      pending.nonce,
      pending.session_id,
      pending.decision_sequence,
      pending.source_first_sequence,
      pending.source_last_sequence,
      static_cast<uint32_t>(pending.decision_reference_ticks / 16000000ull),
      pending.current_applied_code,
      pending.requested_delta_codes,
      pending.requested_code,
      0.0,
      pending.correction_ordinal,
      0u,
      true,
  };
  const OtisCx317AcceptedRequest accepted = {
      pending.request_sequence,
      pending.authorization_sequence,
      pending.nonce,
      pending.requested_code,
      static_cast<uint32_t>(acknowledgement.acknowledgement_ticks /
                            16000000ull),
      false,
  };
  const OtisCx317AppliedAck applied = otis_cx317_active_actuator_apply_once(
      &actionable, &accepted, pending.correction_ordinal,
      static_cast<uint32_t>(acknowledgement.acknowledgement_ticks /
                            16000000ull));
  acknowledgement.kind = OtisActuatorAckKind::Applied;
  acknowledgement.accepted_code = applied.accepted_code;
  acknowledgement.applied_code = applied.applied_code;
  acknowledgement.i2c_ok = applied.i2c_ok;
  acknowledgement.clamped = applied.clamped;
  acknowledgement.ambiguous = applied.ambiguous;
  otis_actuator_guard_acknowledge(&dual_core_service_actuator_guard,
                                  &acknowledgement);
  otis_emit_dac_step(
      runtime_state.sequences.dac_seq++, millis(),
      static_cast<int32_t>(pending.request_sequence), pending.requested_code,
      applied.applied_code, applied.clamped, "", "", 0u,
      applied.i2c_ok && !applied.ambiguous ? "active_apply"
                                          : "active_write_failed",
      applied.i2c_ok && !applied.ambiguous
          ? OTIS_FLAG_NONE
          : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  publish_dual_core_actuator_ack(acknowledgement);
}

bool publish_dual_core_setup_ack(const OtisSetupApplicationAck &ack) {
  OtisServiceMessage service = {};
  service.kind = OtisServiceMessageKind::SetupApplicationAcknowledgement;
  service.setup_acknowledgement = ack;
  return otis_dual_core_publish_service(&service);
}

void emit_dual_core_setup_phase_direct(
    const char *phase, const OtisSetupAuthorityRequest &request,
    const char *severity) {
  emit_status_direct("cx317_setup", "phase", phase, severity,
                     OTIS_FLAG_NONE);
  char value[24];
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(request.command_sequence));
  emit_status_direct("cx317_setup", "command_sequence", value, severity,
                     OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(request.authorization_sequence));
  emit_status_direct("cx317_setup", "authorization_sequence", value,
                     severity, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(request.status_generation));
  emit_status_direct("cx317_setup", "status_generation", value, severity,
                     OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(request.query_nonce));
  emit_status_direct("cx317_setup", "query_nonce", value, severity,
                     OTIS_FLAG_NONE);
}

void service_dual_core_setup_transaction(
    const OtisCriticalRecordMessage &critical) {
  const OtisSetupAuthorization &authorization =
      critical.setup_authorization;
  const OtisSetupAuthorityRequest &request = authorization.request;
  OtisSetupApplicationAck acknowledgement = {};
  acknowledgement.command_sequence = request.command_sequence;
  acknowledgement.authorization_sequence = request.authorization_sequence;
  acknowledgement.status_generation = request.status_generation;
  acknowledgement.query_nonce = request.query_nonce;
  acknowledgement.session_id = request.session_id;
  acknowledgement.requested_code = request.requested_code;
  acknowledgement.one_shot_ordinal = request.one_shot_ordinal;

  const OtisSetupExecutionContext current =
      current_dual_core_setup_execution_context(millis() / 1000u);
  if (critical.kind == OtisCriticalMessageKind::SetupAuthorization) {
    const bool accepted = otis_setup_execution_accept(
        &dual_core_service_setup_guard, &authorization, &current);
    acknowledgement.kind =
        accepted ? OtisSetupApplicationAck::Kind::Core0Accepted
                 : OtisSetupApplicationAck::Kind::Core0Rejected;
    acknowledgement.i2c_ok = accepted;
    emit_dual_core_setup_phase_direct(
        accepted ? "core0_accepted" : "core0_rejected", request,
        accepted ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR);
    publish_dual_core_setup_ack(acknowledgement);
    return;
  }

  if (critical.kind != OtisCriticalMessageKind::SetupExecute ||
      !otis_setup_execution_consume(&dual_core_service_setup_guard,
                                    &authorization, &current)) {
    acknowledgement.kind = OtisSetupApplicationAck::Kind::Failed;
    acknowledgement.i2c_ok = false;
    emit_dual_core_setup_phase_direct("failed_before_i2c", request,
                                      OTIS_SEVERITY_ERROR);
    publish_dual_core_setup_ack(acknowledgement);
    return;
  }

  // The authority is consumed before the sole physical attempt. A failed or
  // ambiguous I2C call is terminal for this boot and is never retried.
  dual_core_manual_start_consumed = true;
  const bool ok = otis_dac_ad5693r_set_raw(request.requested_code);
  acknowledgement.kind = ok ? OtisSetupApplicationAck::Kind::Applied
                            : OtisSetupApplicationAck::Kind::Failed;
  acknowledgement.applied_code = ok ? request.requested_code : 0u;
  acknowledgement.i2c_ok = ok;
  if (ok)
    otis_observe_only_discipline_live_on_dac_applied(
        request.requested_code, otis_capture_ticks_now());
  otis_emit_dac_step(
      runtime_state.sequences.dac_seq++, millis(),
      static_cast<int32_t>(request.command_sequence), request.requested_code,
      request.requested_code, false, "", "", 0u,
      ok ? "manual_apply" : "manual_write_failed",
      ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_dual_core_setup_phase_direct(ok ? "applied" : "failed", request,
                                    ok ? OTIS_SEVERITY_INFO
                                       : OTIS_SEVERITY_ERROR);
  publish_dual_core_setup_ack(acknowledgement);
}
#endif

void service_dual_core_outputs(void) {
  OtisObservationMessage observation;
  uint8_t raw_budget = 24u;
  while (raw_budget-- > 0u &&
         otis_dual_core_take_observation(&observation)) {
    if (observation.kind == OtisObservationMessageKind::RawEdge) {
      const OtisRawEdgeMessage &edge = observation.raw_edge;
      otis_emit_raw_event(edge.reference_record ? OTIS_RECORD_REF
                                                : OTIS_RECORD_EVT,
                          edge.sequence, edge.channel_id,
                          edge_string(edge.edge), edge.timestamp_ticks,
                          OTIS_DOMAIN_RP2040_TIMER0, edge.flags);
    } else if (observation.kind ==
               OtisObservationMessageKind::PpsSnapshot) {
      const OtisPpsSnapshotMessage &snapshot = observation.snapshot;
      otis_emit_pps_snapshot(
          snapshot.session, snapshot.sequence,
          snapshot.cumulative_down_counter, snapshot.reference_sequence,
          snapshot.reference_timestamp_ticks, snapshot.status,
          "pio_wait_cumulative_snapshot_dma_v1");
    } else if (observation.kind ==
               OtisObservationMessageKind::CountObservation) {
      const OtisCountObservationMessage &count = observation.count;
      otis_emit_count_observation(
          count.sequence, count.channel_id, count.gate_open_ticks,
          count.gate_close_ticks, OTIS_DOMAIN_RP2040_TIMER0,
          count.counted_edges, OTIS_EDGE_RISING, count.source_domain,
          count.flags);
    }
  }

  OtisCriticalRecordMessage critical;
  uint8_t critical_budget = 8u;
  while (critical_budget-- > 0u &&
         otis_dual_core_take_critical(&critical)) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
    if (critical.kind == OtisCriticalMessageKind::ActuatorRequest ||
        critical.kind == OtisCriticalMessageKind::ActuatorExecute) {
      service_dual_core_actuator_request(critical);
    } else if (critical.kind ==
                   OtisCriticalMessageKind::SetupAuthorization ||
               critical.kind == OtisCriticalMessageKind::SetupExecute) {
      service_dual_core_setup_transaction(critical);
    }
#endif
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
  while (telemetry_budget-- > 0u &&
         otis_dual_core_take_telemetry(&telemetry)) {
    emit_status_direct(telemetry.component, telemetry.key, telemetry.value,
                       telemetry.severity, telemetry.flags);
#if OTIS_ENABLE_GNSS_RECEIVER
    if (__atomic_load_n(&dual_core_timing_boot_in_progress,
                        __ATOMIC_ACQUIRE)) {
      otis_gnss_receiver_service(millis());
    }
#endif
  }
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
      dual_core_evidence_transport_sent + otis_transport_write_bytes(
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
      otis_observe_only_discipline_live_transport_pending(),
      otis_cx317_preview_live_transport_pending(),
      otis_phase_preview_transport_busy(),
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
    case OtisSerialFrameOwner::Phase4Preview:
      otis_observe_only_discipline_live_service_transport();
      frame_active = otis_observe_only_discipline_live_transport_busy();
      break;
    case OtisSerialFrameOwner::Cx317Preview:
      otis_cx317_preview_live_service_transport();
      frame_active = otis_cx317_preview_live_transport_busy();
      break;
    case OtisSerialFrameOwner::PhasePreview:
      otis_phase_preview_transport_service();
      frame_active = otis_phase_preview_transport_frame_active();
      break;
    case OtisSerialFrameOwner::None:
      return false;
  }
  if (!frame_active)
    otis_serial_frame_arbiter_release(&dual_core_serial_frame_arbiter, owner);
  return frame_active;
}

void discard_dual_core_outputs_after_transport_fault(void) {
  // The byte stream is quarantined after a partial-frame timeout. Continue
  // bounded queue consumption without executing actuator requests or
  // pretending the discarded records are durable evidence. Reset/new session
  // is the only supported recovery.
  OtisObservationMessage observation;
  for (uint8_t budget = 24u;
       budget-- > 0u && otis_dual_core_take_observation(&observation);) {}
  OtisCriticalRecordMessage critical;
  for (uint8_t budget = 8u;
       budget-- > 0u && otis_dual_core_take_critical(&critical);) {}
  OtisTelemetryMessage telemetry;
  for (uint8_t budget = 12u;
       budget-- > 0u && otis_dual_core_take_telemetry(&telemetry);) {}
  OtisEvidenceFrameMessage evidence;
  (void)otis_dual_core_take_evidence(&evidence);
  OtisPhasePreviewRecordMessage phase_preview;
  (void)otis_dual_core_take_phase_preview(&phase_preview);
}

void note_pre_carrier_discard(void) {
  if (dual_core_pre_carrier_records_discarded != UINT32_MAX)
    dual_core_pre_carrier_records_discarded++;
}

void discard_dual_core_outputs_before_first_carrier(void) {
  OtisObservationMessage observation;
  for (uint8_t budget = 24u;
       budget-- > 0u && otis_dual_core_take_observation(&observation);)
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

void publish_dual_core_association_loss_decision(
    const char *reason, uint64_t decision_ticks,
    const OtisPpsCountBoundaryObservation &pending_reference,
    uint64_t pending_age_ticks, uint32_t boundary_depth,
    uint32_t boundary_dropped_count,
    const OtisPpsCountBoundaryObservation *next_reference,
    const OtisPpsSnapshotBackendStats &snapshot_stats) {
  OtisDualCoreQueueStats queue_stats = {};
  otis_dual_core_get_stats(&queue_stats);
  const bool unread_snapshot = snapshot_stats.backlog_depth != 0u;
  const char *classification =
      snapshot_stats.fault_latched
          ? "backend_fault"
          : (unread_snapshot
                 ? "unread_snapshot_present_when_decision_made"
                 : (reason != nullptr &&
                            strcmp(reason, "snapshot_association_timeout") == 0
                        ? "timeout_no_snapshot"
                        : "no_unread_snapshot_healthy_backend"));

  dual_core_association_loss_scratch = {};
  dual_core_association_loss_scratch.sequence =
      dual_core_association_loss_decision_sequence++;
  const int used = snprintf(
      dual_core_association_loss_scratch.data,
      sizeof(dual_core_association_loss_scratch.data),
      "ASL,1,%lu,%s,%s,%llu,%lu,%llu,%llu,%lu,%lu,%s,%lu,%llu,%s,%s,%s,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%s,%llu,%llu\r\n",
      static_cast<unsigned long>(dual_core_association_loss_scratch.sequence),
      reason == nullptr ? "association_loss_unspecified" : reason,
      classification, static_cast<unsigned long long>(decision_ticks),
      static_cast<unsigned long>(pending_reference.reference_sequence),
      static_cast<unsigned long long>(pending_reference.pps_timestamp_ticks),
      static_cast<unsigned long long>(pending_age_ticks),
      static_cast<unsigned long>(boundary_depth),
      static_cast<unsigned long>(boundary_dropped_count),
      next_reference == nullptr ? "false" : "true",
      static_cast<unsigned long>(next_reference == nullptr
                                     ? 0u
                                     : next_reference->reference_sequence),
      static_cast<unsigned long long>(
          next_reference == nullptr ? 0u : next_reference->pps_timestamp_ticks),
      snapshot_stats.initialized ? "true" : "false",
      snapshot_stats.running ? "true" : "false",
      snapshot_stats.fault_latched ? "true" : "false",
      static_cast<unsigned long>(snapshot_stats.fault_flags),
      static_cast<unsigned long>(snapshot_stats.session),
      static_cast<unsigned long>(snapshot_stats.producer_ordinal),
      static_cast<unsigned long>(snapshot_stats.consumer_ordinal),
      static_cast<unsigned long>(snapshot_stats.backlog_depth),
      static_cast<unsigned long>(snapshot_stats.backlog_high_water),
      static_cast<unsigned long>(snapshot_stats.overwrite_count),
      static_cast<unsigned long>(snapshot_stats.continuity_loss_count),
      static_cast<unsigned long>(snapshot_stats.pio_rxstall_count),
      static_cast<unsigned long>(snapshot_stats.dma_error_count),
      static_cast<unsigned long>(snapshot_stats.dma_stopped_count),
      static_cast<unsigned long>(queue_stats.timing_progress.loop_sequence),
      static_cast<unsigned long>(queue_stats.timing_progress.last_snapshot_session),
      static_cast<unsigned long>(queue_stats.timing_progress.last_snapshot_sequence),
      otis_timing_progress_phase_name(queue_stats.timing_progress.phase),
      static_cast<unsigned long long>(
          queue_stats.timing_progress.phase_enter_ticks),
      static_cast<unsigned long long>(
          queue_stats.timing_progress.last_progress_ticks));
  if (used <= 0 || static_cast<size_t>(used) >=
                       sizeof(dual_core_association_loss_scratch.data)) {
    otis_dual_core_latch_fault(OtisPartitionFault::EvidenceExhausted);
    return;
  }
  dual_core_association_loss_scratch.length = static_cast<uint16_t>(used);
  otis_dual_core_publish_evidence(&dual_core_association_loss_scratch);
}
#endif

void emit_captured_edge(const OtisCapturedEdge &record) {
  if (record.reference_record && record.edge == 'R') {
    otis_capture_irq_process_reference_foreground(record);
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
    const OtisPpsCountBoundaryObservation pending_reference = {
        0u,
        0u,
        record.source_sequence,
        record.timestamp_ticks,
        0u,
        0u,
        record.flags,
        OTIS_PPS_APERTURE_NONE,
    };
    otis_pps_count_boundary_ring_push_from_isr(pending_reference);
#endif
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    OtisObserveOnlyDisciplineLiveDacState phase4_dac = {
        dual_core_static_code.available &&
            dual_core_static_code.requested_applied_match &&
            dual_core_static_code.i2c_ok,
        dual_core_static_code.applied_code,
    };
#else
    OtisDacAd5693rStatus dac_status;
    otis_dac_ad5693r_get_status(&dac_status);
    OtisObserveOnlyDisciplineLiveDacState phase4_dac = {
        dac_status.applied_code_known && dac_status.last_write_ok &&
            dac_status.last_requested_code == dac_status.last_applied_code,
        dac_status.last_applied_code,
    };
#endif
    otis_observe_only_discipline_live_on_reference(
        runtime_state.sequences.event_seq, record.timestamp_ticks, record.flags,
        &runtime_state, &phase4_dac);
  }

#if OTIS_ENABLE_DUAL_CORE_PARTITION
  OtisObservationMessage message = {};
  message.kind = OtisObservationMessageKind::RawEdge;
  message.raw_edge.sequence = runtime_state.sequences.event_seq++;
  message.raw_edge.timestamp_ticks = record.timestamp_ticks;
  message.raw_edge.flags = record.flags;
  message.raw_edge.channel_id = record.channel_id;
  message.raw_edge.edge = record.edge;
  message.raw_edge.reference_record = record.reference_record;
  otis_dual_core_publish_observation(&message);
#else
  otis_emit_raw_event(record.reference_record ? OTIS_RECORD_REF
                                              : OTIS_RECORD_EVT,
                      runtime_state.sequences.event_seq++, record.channel_id,
                      edge_string(record.edge), record.timestamp_ticks,
                      OTIS_DOMAIN_RP2040_TIMER0, record.flags);
#endif
  runtime_state.capture.emitted_event_count++;
}

OtisCx317StaticCodeState cx317_static_code_state(void) {
#if OTIS_ENABLE_DUAL_CORE_PARTITION
#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
  // The no-write rehearsal consumes the Stage 4-sealed A828 premise as a
  // build-bound observation context only.  Active health remains unconfirmed
  // until the exact Stage 5 setup write creates real Core 0 DAC evidence.
  if (!dual_core_static_code.available)
    return {true, true, true, OTIS_TIGHT_DEADBAND_INITIAL_CODE};
#endif
  return dual_core_static_code;
#else
  OtisDacAd5693rStatus status;
  otis_dac_ad5693r_get_status(&status);
  const bool matches = status.applied_code_known && status.last_write_ok &&
                       status.last_requested_code == status.last_applied_code;
  return {
      matches,
      matches,
      status.initialized && status.last_write_ok,
      status.last_applied_code,
  };
#endif
}

void service_cx317_active_health(void) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  const uint32_t now_ms = millis();
#if !OTIS_ENABLE_DUAL_CORE_PARTITION
  OtisGnssReceiverSnapshot gnss;
  otis_gnss_receiver_get_snapshot(now_ms, &gnss);
#endif
  OtisPpsSnapshotBackendStats snapshot;
  otis_pps_snapshot_backend_get_stats(&snapshot);
  OtisCaptureIrqReferenceStats d14;
  otis_capture_irq_get_reference_stats(&d14);
  OtisPpsDualObserverStats d10;
  otis_pps_dual_observer_get_stats(&d10);
  const uint32_t edge_difference =
      d14.d14_raw_edge_count > d10.d10_raw_edge_count
          ? d14.d14_raw_edge_count - d10.d10_raw_edge_count
          : d10.d10_raw_edge_count - d14.d14_raw_edge_count;
  const bool raw_pps_valid =
      d14.d14_accepted_pps_count > 0u &&
      d14.d14_rejected_short_count == 0u &&
      d14.d14_rejected_long_count == 0u && d10.d10_raw_edge_count > 0u &&
      d10.d10_short_interval_count == 0u &&
      d10.d10_long_interval_count == 0u &&
      d10.d10_buffer_overflow_count == 0u && edge_difference <= 1u &&
      otis_capture_ring_dropped_count() == 0u &&
      otis_pps_count_boundary_ring_dropped_count() == 0u &&
      !snapshot.fault_latched && snapshot.continuity_loss_count == 0u;
  OtisCx317PreviewAuthorityState preview;
  otis_cx317_preview_live_get_authority_state(&preview);
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  const bool applied_confirmed =
      dual_core_static_code.available &&
      dual_core_static_code.requested_applied_match &&
      dual_core_static_code.i2c_ok;
#else
  OtisDacAd5693rStatus dac;
  otis_dac_ad5693r_get_status(&dac);
  const bool applied_confirmed =
      dac.initialized && dac.applied_code_known && dac.last_write_ok &&
      dac.last_requested_code == dac.last_applied_code;
#endif
  const OtisCx317ActiveLiveHealth health = {
      snapshot.session,
#if OTIS_ENABLE_DUAL_CORE_PARTITION
      dual_core_receiver_qualified_for_control(),
      dual_core_receiver.identity_stable,
      dual_core_receiver.gsa_3d,
#else
      gnss.control_eligible && gnss.gsa_checksum_requalified,
      gnss.identity_stable,
      gnss.gsa_3d,
#endif
      raw_pps_valid,
      runtime_state.tcxo.valid_for_control &&
          runtime_state.tcxo.last_observation_valid &&
          !runtime_state.tcxo.fault_after_startup,
      preview.estimator_valid,
      preview.model_applicable,
      preview.temperature_valid,
      applied_confirmed,
#if OTIS_ENABLE_DUAL_CORE_PARTITION
      dual_core_static_code.applied_code,
      !otis_dual_core_fail_static(),
#else
      dac.last_applied_code,
      otis_transport_ready(),
#endif
      preview.selected_interval_count,
  };
  otis_cx317_active_live_update_health(&health, now_ms / 1000u);
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  if (dual_core_static_code.available &&
      otis_cx317_active_live_manual_start_allowed(
          dual_core_static_code.applied_code)) {
    otis_cx317_active_live_note_manual_start(
        dual_core_static_code.applied_code, true, now_ms / 1000u);
#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
    OtisCx317ActiveLiveStatus active_status = {};
    otis_cx317_active_live_get_status(&active_status, now_ms / 1000u);
    otis_cx317_preview_live_on_dac_applied_epoch(
        dual_core_static_code.applied_code, active_status.dac_epoch,
        now_ms / 1000u);
    if (!otis_phase_preview_live_update_applied_code(
            dual_core_static_code.applied_code, active_status.dac_epoch))
      otis_dual_core_latch_fault(OtisPartitionFault::PhasePreviewFault);
#endif
  }
#endif
  otis_cx317_active_live_service(now_ms / 1000u);
#endif
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
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  return OTIS_DOMAIN_H1_CX317_OCXO_10MHZ;
#else
  return OTIS_DOMAIN_H0_TCXO_16MHZ;
#endif
}

OtisCountObservationConfig count_observation_config(void) {
  return {
      kTcxoGatePeriodUs,
      kTcxoMeasurePeriodMs,
      kFc0StartupInhibitMs,
      kFc0ControlReadyCleanWindows,
      osc_observation_domain(),
  };
}

void drain_capture_ring(void) {
  OtisCapturedEdge record;
  // A hostile/noisy input may continue refilling the ISR ring while Core 1
  // drains it. One full declared ring per pass bounds the phase and guarantees
  // later service/control phases receive CPU time.
  uint32_t budget = OTIS_CAPTURE_RING_SIZE - 1u;
  while (budget-- > 0u && otis_capture_ring_pop(&record)) {
    emit_captured_edge(record);
  }
}

void emit_pps_count_boundary(
    const OtisPpsCountBoundaryObservation &observation,
    uint32_t snapshot_status) {
  OtisCountObservationConfig count_config = count_observation_config();
  bool window_completed = otis_count_observation_on_pps_boundary(
      &runtime_state, &status_emit_context, &count_config, &observation);
  const OtisCx317StaticCodeState cx317_code = cx317_static_code_state();
  OtisCx317ActiveLiveOutcome active_outcome;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  const bool preview_receiver_valid =
      dual_core_receiver_qualified_for_control();
#else
  const bool preview_receiver_valid = true;
#endif
  otis_cx317_preview_live_on_boundary(
      &observation,
      static_cast<uint32_t>(runtime_state.tcxo.last_counted_edges),
      // The PPS-gated backend normally retains
      // OTIS_FLAG_TIMESTAMP_RECONSTRUCTED as provenance on a valid CNT row.
      // Use the backend's completed validity assessment instead of requiring
      // a numerically zero flag word.
      window_completed && runtime_state.tcxo.last_observation_valid &&
          preview_receiver_valid,
      millis() / 1000u, &cx317_code, &active_outcome);
#if OTIS_ENABLE_PHASE_FREQUENCY_PREVIEW
  otis_phase_preview_live_on_boundary(
      &observation, snapshot_status,
      static_cast<uint32_t>(runtime_state.tcxo.last_counted_edges),
      window_completed,
      window_completed && runtime_state.tcxo.last_observation_valid &&
          preview_receiver_valid,
      false);
#endif
  if (active_outcome.application_attempted) {
    otis_emit_dac_step(
        runtime_state.sequences.dac_seq++, millis(),
        static_cast<int32_t>(active_outcome.request_sequence),
        active_outcome.requested_code, active_outcome.applied_code, false, "",
        "", 0u,
        active_outcome.applied ? "active_apply" : "active_write_failed",
        active_outcome.applied ? OTIS_FLAG_NONE
                               : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  }
  if (window_completed) {
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    otis_dual_core_note_timing_count(runtime_state.sequences.count_seq - 1u);
#endif
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    OtisObserveOnlyDisciplineLiveDacState phase4_dac = {
        dual_core_static_code.available &&
            dual_core_static_code.requested_applied_match &&
            dual_core_static_code.i2c_ok,
        dual_core_static_code.applied_code,
    };
#else
    OtisDacAd5693rStatus dac_status;
    otis_dac_ad5693r_get_status(&dac_status);
    OtisObserveOnlyDisciplineLiveDacState phase4_dac = {
        dac_status.applied_code_known && dac_status.last_write_ok &&
            dac_status.last_requested_code == dac_status.last_applied_code,
        dac_status.last_applied_code,
    };
#endif
    otis_observe_only_discipline_live_on_count(
        runtime_state.sequences.count_seq - 1u, &runtime_state, &phase4_dac);
    otis_count_observation_note_control_consumer(observation.session,
                                                 observation.sequence);
#if OTIS_ENABLE_H1_DAC_SWEEP && \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
    emit_h1_dac_sweep_fc0_window();
#endif
  }
}

void service_cx317_active_application_outcome(void) {
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  OtisCx317ActiveLiveOutcome active_outcome;
  if (!otis_cx317_active_live_take_application_outcome(&active_outcome)) return;
#if !OTIS_ENABLE_DUAL_CORE_PARTITION
  otis_emit_dac_step(
      runtime_state.sequences.dac_seq++, millis(),
      static_cast<int32_t>(active_outcome.request_sequence),
      active_outcome.requested_code, active_outcome.applied_code, false, "", "",
      0u, active_outcome.applied ? "active_apply" : "active_write_failed",
      active_outcome.applied ? OTIS_FLAG_NONE
                             : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
#endif
  if (active_outcome.applied) {
#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
    otis_cx317_preview_live_on_dac_applied_epoch(
        active_outcome.applied_code, active_outcome.dac_epoch,
        millis() / 1000u);
    if (!otis_phase_preview_live_update_applied_code(
            active_outcome.applied_code, active_outcome.dac_epoch))
      otis_dual_core_latch_fault(OtisPartitionFault::PhasePreviewFault);
#else
    otis_cx317_preview_live_on_dac_applied(active_outcome.applied_code,
                                           millis() / 1000u);
#endif
  }
  otis_cx317_active_live_complete_application_evidence(
      active_outcome.request_sequence, active_outcome.applied,
      millis() / 1000u);
#endif
}

void drain_pps_count_boundary_ring(void) {
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
  static bool have_pending_reference = false;
  static OtisPpsCountBoundaryObservation pending_reference = {};

  if (!have_pending_reference) {
    have_pending_reference =
        otis_pps_count_boundary_ring_pop(&pending_reference);
  }
  if (!have_pending_reference) {
    return;
  }

  OtisPpsSnapshotBackendStats stats;
  otis_pps_snapshot_backend_get_stats(&stats);
  uint64_t pending_age_ticks = otis_timer0_interval_ticks(
      pending_reference.pps_timestamp_ticks, otis_capture_ticks_now());
  uint64_t association_timeout_ticks =
      static_cast<uint64_t>(OTIS_PPS_GATE_MAX_INTERVAL_US) *
      OTIS_RP2040_TIMER0_TICKS_PER_US;
  bool another_reference_waiting =
      otis_pps_count_boundary_ring_depth() != 0u;
  if (stats.fault_latched || another_reference_waiting ||
      pending_age_ticks > association_timeout_ticks) {
    // A second physical REF before the first association closes is immediate
    // association loss, even if a word has since appeared. Queue/foreground
    // delay cannot prove that word belongs to the older REF, so it is never
    // paired retroactively with it.
    const char *association_reason =
        stats.fault_latched
            ? "snapshot_backend_fault"
            : (another_reference_waiting ? "ref_without_snapshot"
                                         : "snapshot_association_timeout");
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    OtisPpsCountBoundaryObservation next_reference = {};
    const bool have_next_reference =
        otis_pps_count_boundary_ring_peek(&next_reference);
    publish_dual_core_association_loss_decision(
        association_reason, otis_capture_ticks_now(), pending_reference,
        pending_age_ticks, otis_pps_count_boundary_ring_depth(),
        otis_pps_count_boundary_ring_dropped_count(),
        have_next_reference ? &next_reference : nullptr, stats);
#endif
    otis_count_observation_note_association_loss(
        &runtime_state, &status_emit_context,
        pending_reference.reference_sequence, association_reason);
    const OtisCx317StaticCodeState cx317_code = cx317_static_code_state();
    otis_cx317_preview_live_on_capture_fault(
        association_reason, millis() / 1000u, &cx317_code);
    otis_phase_preview_live_note_reset();
    otis_pps_snapshot_backend_rearm();
    otis_pps_count_boundary_ring_reset();
    have_pending_reference = false;
    return;
  }

  OtisPpsHardwareSnapshot snapshot;
  if (!otis_pps_snapshot_backend_pop(&snapshot)) {
    return;
  }

  OtisPpsCountBoundaryObservation observation = pending_reference;
  observation.session = snapshot.session;
  observation.sequence = snapshot.sequence;
  observation.cumulative_down_counter = snapshot.cumulative_down_counter;
  if ((snapshot.status & OTIS_PPS_SNAPSHOT_STATUS_OVERWRITE_BEFORE) != 0u) {
    observation.aperture_flags |=
        OTIS_PPS_APERTURE_OBSERVATION_OVERFLOW |
        OTIS_PPS_APERTURE_PHYSICAL_APERTURE_INCOMPLETE;
  }
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  OtisObservationMessage snapshot_message = {};
  snapshot_message.kind = OtisObservationMessageKind::PpsSnapshot;
  snapshot_message.snapshot.session = observation.session;
  snapshot_message.snapshot.sequence = observation.sequence;
  snapshot_message.snapshot.cumulative_down_counter =
      observation.cumulative_down_counter;
  snapshot_message.snapshot.reference_sequence =
      observation.reference_sequence;
  snapshot_message.snapshot.reference_timestamp_ticks =
      observation.pps_timestamp_ticks;
  snapshot_message.snapshot.status = snapshot.status;
  otis_dual_core_note_timing_snapshot(observation.session,
                                      observation.sequence);
  otis_dual_core_publish_observation(&snapshot_message);
#else
  otis_emit_pps_snapshot(
      observation.session, observation.sequence,
      observation.cumulative_down_counter, observation.reference_sequence,
      observation.pps_timestamp_ticks, snapshot.status,
      "pio_wait_cumulative_snapshot_dma_v1");
#endif
  emit_pps_count_boundary(observation, snapshot.status);
  have_pending_reference = false;
#endif
}

void emit_build_provenance_status(void) {
  emit_status("build", "provenance_format", OTIS_BUILD_PROVENANCE_FORMAT,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "git_commit", OTIS_FIRMWARE_GIT_COMMIT,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "source_state", OTIS_BUILD_SOURCE_STATE,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "source_hash", OTIS_BUILD_SOURCE_SHA256,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "config_hash", OTIS_BUILD_CONFIG_SHA256,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "board", OTIS_TARGET_BOARD, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "board_name", OTIS_TARGET_BOARD_NAME,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "fqbn", OTIS_BUILD_FQBN, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "arduino_core_provider", OTIS_BUILD_CORE_PROVIDER,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "arduino_core_version", OTIS_BUILD_CORE_VERSION,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "arduino_core_installed_hash",
              OTIS_BUILD_CORE_INSTALLED_SHA256, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "profile_id", OTIS_BUILD_PROFILE_ID,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "toolchain", OTIS_BUILD_TOOLCHAIN,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "compiler", OTIS_BUILD_COMPILER, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "toolchain_installed_hash",
              OTIS_BUILD_TOOLCHAIN_INSTALLED_SHA256, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "arduino_cli_version",
              OTIS_BUILD_ARDUINO_CLI_VERSION, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "invocation_id", OTIS_BUILD_INVOCATION_ID,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
}

void emit_common_boot_status(void) {
  emit_build_provenance_status();
  emit_status("system", "boot", "true", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("protocol", "schema_version", OTIS_SCHEMA_VERSION_V1,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "name", OTIS_FIRMWARE_NAME, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "version", OTIS_FIRMWARE_VERSION, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "config_id", OTIS_FIRMWARE_CONFIG_ID,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "git_commit", OTIS_FIRMWARE_GIT_COMMIT,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "source_state", OTIS_BUILD_SOURCE_STATE,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "source_hash", OTIS_BUILD_SOURCE_SHA256,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "config_hash", OTIS_BUILD_CONFIG_SHA256,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "mode", otis_bringup_mode_name(), OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("capture", "mode", OTIS_CAPTURE_MODE, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  emit_status("capture", "timestamp_latch", "pio_edge_detect_cpu_timestamped",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status("capture", "limitation",
              "pio_detects_rising_edges_cpu_attaches_drain_timestamp_dma_deferred",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
#else
  emit_status("capture", "timestamp_latch", "irq_micros_reconstructed",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status("capture", "limitation",
              "bench_validation_not_final_pio_dma_metrology",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
#endif
  emit_status_u32("capture", "nominal_capture_clock_hz",
                  OTIS_NOMINAL_CAPTURE_CLOCK_HZ, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("reference", "nominal_pps_hz", OTIS_NOMINAL_PPS_HZ,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("reference", "nominal_tcxo_hz", OTIS_NOMINAL_TCXO_HZ,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("reference", "nominal_ocxo_hz", OTIS_NOMINAL_OCXO_HZ,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("capture", "fc0_measure_period_ms", kTcxoMeasurePeriodMs,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("capture", "counter_gate_period_us", kTcxoGatePeriodUs,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("capture", "measurement_mode",
              otis_count_observation_measurement_mode(),
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "arduino_core", OTIS_TARGET_ARDUINO_CORE,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "board", OTIS_TARGET_BOARD, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "board_name", OTIS_TARGET_BOARD_NAME,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "fqbn", OTIS_BUILD_FQBN, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "arduino_core_provider", OTIS_BUILD_CORE_PROVIDER,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "arduino_core_version", OTIS_BUILD_CORE_VERSION,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "arduino_core_installed_hash",
              OTIS_BUILD_CORE_INSTALLED_SHA256, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "profile_id", OTIS_BUILD_PROFILE_ID,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "toolchain", OTIS_BUILD_TOOLCHAIN,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "compiler", OTIS_BUILD_COMPILER, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "toolchain_installed_hash",
              OTIS_BUILD_TOOLCHAIN_INSTALLED_SHA256, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "arduino_cli_version",
              OTIS_BUILD_ARDUINO_CLI_VERSION, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "invocation_id", OTIS_BUILD_INVOCATION_ID,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_rp2040_boot_diag",
                  OTIS_ENABLE_RP2040_BOOT_DIAG, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_pps_dual_observer",
                  OTIS_ENABLE_PPS_DUAL_OBSERVER, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_status_led", OTIS_ENABLE_STATUS_LED,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "capture_backend", otis_capture_backend_name(),
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "tcxo_counter_backend",
              otis_tcxo_counter_backend_name(),
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_dac_ad5693r", OTIS_ENABLE_DAC_AD5693R,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_phase4_observe_preview",
                  OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_cx317_i_only_preview",
                  OTIS_ENABLE_CX317_I_ONLY_PREVIEW, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_cx318_stage4_preview",
                  OTIS_ENABLE_CX318_STAGE4_PREVIEW, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_cx318_stage5_preview",
                  OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW,
                  OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_cx318_stage4_premise_setup",
                  OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
#if OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP
  emit_status_u16_hex("cx318_premise", "allowed_code",
                      OTIS_CX318_STAGE4_PREMISE_SETUP_CODE,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("cx318_premise", "write_consumed",
              cx318_stage4_premise_write_consumed ? "true" : "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("cx318_premise", "actionable", "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("cx318_premise", "actuation_authorized", "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("cx318_premise", "automatic_authority", "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
#if OTIS_ENABLE_PHASE_FREQUENCY_PREVIEW
#if OTIS_ENABLE_CX318_STAGE4_PREVIEW
  emit_status_u16_hex("cx318_preview", "confirmed_static_code",
                      OTIS_CX318_STAGE4_STATIC_CODE, OTIS_SEVERITY_INFO,
                      OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("cx318_preview", "dac_epoch",
                  OTIS_CX318_STAGE4_DAC_EPOCH, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
#else
  emit_status_u16_hex("cx318_preview", "confirmed_initial_code",
                      OTIS_TIGHT_DEADBAND_INITIAL_CODE, OTIS_SEVERITY_INFO,
                      OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("cx318_preview", "initial_dac_epoch",
                  OTIS_TIGHT_DEADBAND_INITIAL_DAC_EPOCH, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
  emit_status("cx318_preview", "actionable", "false", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("cx318_preview", "actuation_authorized", "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("cx318_preview", "authorization_consumed", "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
  emit_status_u32("build", "enable_cx317_bounded_active",
                  OTIS_ENABLE_CX317_BOUNDED_ACTIVE, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("phase4_preview", "actuation_authorized", "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_h1_dac_sweep", OTIS_ENABLE_H1_DAC_SWEEP,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_env_sensors", OTIS_ENABLE_ENV_SENSORS,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_env_sht4x", OTIS_ENABLE_ENV_SHT4X,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_env_bmp280", OTIS_ENABLE_ENV_BMP280,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_gnss_receiver", OTIS_ENABLE_GNSS_RECEIVER,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("environment", "sample_period_ms", OTIS_ENV_SAMPLE_PERIOD_MS,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("environment", "sht4x_i2c_address",
                  OTIS_ENV_SHT4X_I2C_ADDRESS, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("environment", "bmp280_i2c_address",
                  OTIS_ENV_BMP280_I2C_ADDRESS, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("sweep", "default_dwell_ms",
                  OTIS_H1_DAC_SWEEP_DEFAULT_DWELL_MS, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("sweep", "slope_dwell_ms", OTIS_H1_DAC_SWEEP_SLOPE_DWELL_MS,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex("sweep", "tiny_step_codes",
                      OTIS_H1_DAC_SWEEP_TINY_STEP_CODES, OTIS_SEVERITY_INFO,
                      OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex("sweep", "center_code",
                      (uint16_t)(((uint32_t)OTIS_DAC_MIN_CODE +
                                  (uint32_t)OTIS_DAC_MAX_CODE) /
                                 2u),
                      OTIS_SEVERITY_INFO,
                      OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("dac", "i2c_address", OTIS_DAC_AD5693R_I2C_ADDRESS,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex("dac", "min_code", OTIS_DAC_MIN_CODE,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex("dac", "max_code", OTIS_DAC_MAX_CODE,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
#if OTIS_ENABLE_PPS_DUAL_OBSERVER
  emit_status("pps_dual_observer", "feature", "temporary_h1_diagnostic",
              OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pps_dual_observer", "d14_pps_pin", "D14",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pps_dual_observer", "d10_witness_pin", "D10",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pps_dual_observer", "d14_capture_backend",
              otis_capture_backend_name(), OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pps_dual_observer", "d10_observer_mechanism",
              "plain_gpio_irq_rising_dedicated_buffer", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pps_dual_observer", "d10_input_mode", "INPUT_no_pull",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pps_dual_observer", "requested_edge", "R",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u64_decimal("pps_dual_observer", "short_interval_ticks",
                          OTIS_PPS_DUAL_OBSERVER_SHORT_INTERVAL_TICKS,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u64_decimal("pps_dual_observer", "long_interval_ticks",
                          OTIS_PPS_DUAL_OBSERVER_LONG_INTERVAL_TICKS,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("pps_dual_observer", "burst_short_threshold",
                  OTIS_PPS_DUAL_OBSERVER_BURST_SHORT_THRESHOLD,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
}

void emit_env_sensor_status(void) {
  OtisEnvSensorStatus status;
  otis_env_sensors_get_status(&status);
  emit_status("environment", "sht4x_enabled",
              status.sht4x_enabled ? "true" : "false", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("environment", "sht4x_initialized",
              status.sht4x_initialized ? "true" : "false",
              status.sht4x_initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.sht4x_initialized ? OTIS_FLAG_NONE
                                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("environment", "bmp280_enabled",
              status.bmp280_enabled ? "true" : "false", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("environment", "bmp280_initialized",
              status.bmp280_initialized ? "true" : "false",
              status.bmp280_initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.bmp280_initialized ? OTIS_FLAG_NONE
                                        : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("environment", "primary_temperature_source", "sht4x",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("environment", "primary_temperature_role", "vcocxo_near",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
}

void emit_gnss_receiver_status(void) {
  // Status bursts deliberately service UART0 after every complete STS frame.
  // Take the freshness anchor here, after any preceding burst service, so a
  // newly parsed sentence cannot appear a few milliseconds in the future and
  // wrap its unsigned age to nearly UINT32_MAX.
  const uint32_t now_ms = millis();
  OtisGnssReceiverSnapshot status;
  otis_gnss_receiver_get_snapshot(now_ms, &status);
  bool raw_pps_control_eligible = false;
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_IRQ
  OtisCaptureIrqReferenceStats pps_status;
  otis_capture_irq_get_reference_stats(&pps_status);
  raw_pps_control_eligible =
      runtime_state.tcxo.valid_for_control &&
      pps_status.d14_accepted_pps_count > 0u &&
      pps_status.d14_rejected_short_count == 0u &&
      pps_status.d14_rejected_long_count == 0u &&
      otis_capture_ring_dropped_count() == 0u &&
      otis_pps_count_boundary_ring_dropped_count() == 0u;
#endif
  const bool combined_control_eligible =
      status.control_eligible && raw_pps_control_eligible;
  const uint32_t health_flags = status.control_eligible
                                    ? OTIS_FLAG_NONE
                                    : OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT;
  const char *health_severity =
      status.control_eligible ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN;
  emit_status("gnss_receiver", "enabled",
              OTIS_ENABLE_GNSS_RECEIVER ? "true" : "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("gnss_receiver", "initialized",
              status.initialized ? "true" : "false",
              status.initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.initialized ? OTIS_FLAG_NONE
                                 : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("gnss_receiver", "receiver_identity",
              "nmea_rmc_gga_model_unavailable", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("gnss_receiver", "uart_configuration", "uart0_9600_8n1",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("gnss_receiver", "rx_pin", "D0_GPIO1_UART0_RX",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("gnss_receiver", "tx_pin", "D1_GPIO0_high_impedance_input",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("gnss_receiver", "rx_only",
              status.rx_only ? "true" : "false",
              status.rx_only ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              status.rx_only ? OTIS_FLAG_NONE
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
  emit_status("gnss_receiver", "raw_pps_control_eligible",
              raw_pps_control_eligible ? "true" : "false",
              raw_pps_control_eligible ? OTIS_SEVERITY_INFO
                                       : OTIS_SEVERITY_WARN,
              raw_pps_control_eligible ? OTIS_FLAG_NONE
                                       : OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT);
  emit_status("gnss_receiver", "control_eligible",
              combined_control_eligible ? "true" : "false",
              combined_control_eligible ? OTIS_SEVERITY_INFO
                                        : OTIS_SEVERITY_WARN,
              combined_control_eligible ? OTIS_FLAG_NONE
                                        : OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT);
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
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pins", "ch1_pps_reference", "D14", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pins", "ch2_osc_observation", "D8_GPIO20_GPIN0",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
#if OTIS_ENABLE_PPS_DUAL_OBSERVER
  emit_status("pins", "d10_pps_witness", "D10_input_rising_no_pull",
              OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
}

void emit_selected_capability_status(void) {
  if (boot_capability_status_emitted || !otis_transport_ready()) {
    return;
  }

  const OtisBootCapabilityOutcome overall =
      otis_boot_capability_overall_outcome(&boot_capabilities);
  const bool run_mode_ready = boot_capabilities.run_mode_marked;
  const bool degraded = otis_boot_capability_degraded(&boot_capabilities);
  emit_status("boot_capabilities", "selected_profile",
              otis_bringup_mode_name(), OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("boot_capabilities", "overall",
              otis_boot_capability_outcome_name(overall),
              overall == OtisBootCapabilityOutcome::Ready
                  ? OTIS_SEVERITY_INFO
                  : (overall == OtisBootCapabilityOutcome::OptionalDegraded
                         ? OTIS_SEVERITY_WARN
                         : OTIS_SEVERITY_FATAL),
              overall == OtisBootCapabilityOutcome::Ready
                  ? OTIS_FLAG_PROFILE_ASSUMPTION
                  : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("boot_capabilities", "run_mode",
              run_mode_ready ? "Ready" : "blocked",
              run_mode_ready ? (degraded ? OTIS_SEVERITY_WARN
                                         : OTIS_SEVERITY_INFO)
                             : OTIS_SEVERITY_FATAL,
              run_mode_ready && !degraded ? OTIS_FLAG_PROFILE_ASSUMPTION
                                          : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("boot_capabilities", "degraded",
              degraded ? "true" : "false",
              degraded ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
              degraded ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                       : OTIS_FLAG_PROFILE_ASSUMPTION);

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
                    ? OTIS_FLAG_PROFILE_ASSUMPTION
                    : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  }
  emit_status_u32("boot_capabilities", "selected_count", selected_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  boot_capability_status_emitted = true;
}

void emit_resource_ownership_status(void) {
  if (resource_ownership_status_emitted || !otis_transport_ready()) {
    return;
  }

  bool valid = otis_resource_registry_valid();
  bool complete = otis_resource_registry_complete();
  uint32_t registry_flags =
      valid && complete ? OTIS_FLAG_PROFILE_ASSUMPTION
                        : OTIS_FLAG_SOURCE_HEALTH_SUSPECT;

  emit_status("resource_registry", "version", "1", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("resource_registry", "valid", valid ? "true" : "false",
              valid ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_FATAL,
              registry_flags);
  emit_status("resource_registry", "complete", complete ? "true" : "false",
              complete ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              registry_flags);
  emit_status_u32("resource_registry", "claim_count",
                  otis_resource_registry_claim_count(), OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("resource_registry", "conflict_count",
                  otis_resource_registry_conflict_count(),
                  valid ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_FATAL,
                  registry_flags);
  emit_status_u32("resource_registry", "binding_failure_count",
                  otis_resource_registry_binding_failure_count(),
                  otis_resource_registry_binding_failure_count() == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_ERROR,
                  registry_flags);
  emit_status_u32(
      "resource_registry", "gpio_claim_count",
      otis_resource_registry_claim_count(OtisResourceType::Gpio),
      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "irq_claim_count",
      otis_resource_registry_claim_count(OtisResourceType::GpioIrq),
      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "pio_sm_claim_count",
      otis_resource_registry_claim_count(OtisResourceType::PioStateMachine),
      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "pio_imem_claim_count",
      otis_resource_registry_claim_count(
          OtisResourceType::PioInstructionMemory),
      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "dma_claim_count",
      otis_resource_registry_claim_count(OtisResourceType::DmaChannel),
      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "timer_claim_count",
      otis_resource_registry_claim_count(OtisResourceType::Timer),
      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "clock_claim_count",
      otis_resource_registry_claim_count(OtisResourceType::Clock),
      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);

  uint8_t claim_count = otis_resource_registry_claim_count();
  for (uint8_t i = 0; i < claim_count; ++i) {
    const OtisResourceClaim *claim = otis_resource_registry_claim_at(i);
    if (claim == nullptr) {
      continue;
    }
    char key[16];
    char value[160];
    snprintf(key, sizeof(key), "claim_%02u", i);
    snprintf(value, sizeof(value), "%s:%u:%u:%u:%s:%s:%s",
             otis_resource_type_name(claim->type), claim->instance,
             claim->index, claim->span, claim->owner, claim->role,
             claim->bound ? "bound" : "pending");
    emit_status("resource_registry", key, value,
                claim->bound ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
                claim->bound ? OTIS_FLAG_PROFILE_ASSUMPTION
                             : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  }
  resource_ownership_status_emitted = true;
}

void emit_protocol_banner_if_serial_ready(void) {
  if (runtime_state.boot.protocol_banner_emitted ||
      !otis_transport_ready()) {
    return;
  }

  if (runtime_state.boot.serial_absent_warn_pending) {
    // Establish a fresh record boundary in case the USB core retained any
    // prefix from writes attempted before the late host opened the port.
    otis_transport_write_cstr("\r\n");
  }
  emit_boot_records_if_serial_ready();
#if OTIS_ENABLE_RP2040_BOOT_DIAG
  emitRp2040BootDiag(Serial);
#endif
  otis_emit_csv_headers();
  otis_observe_only_discipline_live_emit_headers();
  otis_cx317_preview_live_emit_headers();
  otis_cx317_active_live_emit_headers();
  otis_phase_preview_transport_emit_headers();
  runtime_state.boot.protocol_banner_emitted = true;
}

void emit_periodic_status(void) {
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - runtime_state.periodic.last_status_ms) <
      kStatusPeriodMs) {
    return;
  }
  runtime_state.periodic.last_status_ms = now_ms;

#if OTIS_ENABLE_DUAL_CORE_PARTITION
  emit_status_u32("system", "uptime_seconds", now_ms / 1000u,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  OtisDualCoreQueueStats queues;
  otis_dual_core_get_stats(&queues);
  emit_status_u32("dual_core", "service_to_timing_depth",
                  queues.service_to_timing_depth, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "service_to_timing_high_water",
                  queues.service_to_timing_high_water, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "observation_depth", queues.observation_depth,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "observation_high_water",
                  queues.observation_high_water, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "critical_depth", queues.critical_depth,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "critical_high_water",
                  queues.critical_high_water, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "evidence_depth", queues.evidence_depth,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "evidence_high_water",
                  queues.evidence_high_water, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "telemetry_depth", queues.telemetry_depth,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "telemetry_high_water",
                  queues.telemetry_high_water, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "cx318_preview_depth",
                  queues.phase_preview_depth, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "cx318_preview_high_water",
                  queues.phase_preview_high_water, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "telemetry_dropped",
                  queues.telemetry_dropped,
                  queues.telemetry_dropped ? OTIS_SEVERITY_WARN
                                           : OTIS_SEVERITY_INFO,
                  queues.telemetry_dropped
                      ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                      : OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "pre_carrier_records_discarded",
                  dual_core_pre_carrier_records_discarded,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "service_publish_attempts",
                  queues.service_activity.publish_attempts,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "service_publish_successes",
                  queues.service_activity.publish_successes,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32(
      "dual_core", "service_publish_failures",
      queues.service_activity.publish_failures,
      queues.service_activity.publish_failures ? OTIS_SEVERITY_ERROR
                                               : OTIS_SEVERITY_INFO,
      queues.service_activity.publish_failures
          ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
          : OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "service_take_successes",
                  queues.service_activity.take_successes,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("dual_core", "service_take_accounting", "successful_only",
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "service_drain_budget_per_loop",
                  OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("dual_core", "service_last_published_kind",
              otis_service_message_kind_name(
                  queues.service_activity.last_published_kind),
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "service_last_published_sequence",
                  queues.service_activity.last_published_sequence,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u64_decimal("dual_core", "service_last_published_ticks",
                          queues.service_activity.last_published_ticks,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("dual_core", "service_last_taken_kind",
              otis_service_message_kind_name(
                  queues.service_activity.last_taken_kind),
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "service_last_taken_sequence",
                  queues.service_activity.last_taken_sequence,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u64_decimal("dual_core", "service_last_taken_ticks",
                          queues.service_activity.last_taken_ticks,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("dual_core", "core1_trace_sampling", "bounded_coarse",
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "core1_trace_period_ms",
                  kDualCoreTimingTracePeriodMs,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "core1_trace_sequence",
                  queues.timing_progress.loop_sequence,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("dual_core", "core1_progress_phase",
              otis_timing_progress_phase_name(queues.timing_progress.phase),
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u64_decimal("dual_core", "core1_phase_enter_ticks",
                          queues.timing_progress.phase_enter_ticks,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "core1_last_snapshot_session",
                  queues.timing_progress.last_snapshot_session,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "core1_last_snapshot_sequence",
                  queues.timing_progress.last_snapshot_sequence,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "core1_last_count_sequence",
                  queues.timing_progress.last_count_sequence,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "core1_last_estimate_sequence",
                  queues.timing_progress.last_estimate_sequence,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("dual_core", "service_fault_capsule",
              queues.service_fault.valid ? "frozen" : "clear",
              queues.service_fault.valid ? OTIS_SEVERITY_ERROR
                                         : OTIS_SEVERITY_INFO,
              queues.service_fault.valid ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                                         : OTIS_FLAG_NONE);
  if (queues.service_fault.valid) {
    emit_status("dual_core", "fault_failing_service_kind",
                otis_service_message_kind_name(
                    queues.service_fault.failing_kind),
                OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_failing_service_sequence",
                    queues.service_fault.failing_sequence,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u64_decimal(
        "dual_core", "fault_failing_publish_ticks",
        queues.service_fault.failing_published_ticks,
        OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_service_queue_depth",
                    queues.service_fault.queue_depth,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status("dual_core", "fault_breadcrumb_coherent",
                queues.service_fault.breadcrumb_coherent ? "true" : "false",
                queues.service_fault.breadcrumb_coherent
                    ? OTIS_SEVERITY_ERROR
                    : OTIS_SEVERITY_WARN,
                OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_breadcrumb_generation",
                    queues.service_fault.breadcrumb_generation,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status("dual_core", "fault_last_taken_kind",
                otis_service_message_kind_name(
                    queues.service_fault.last_taken_kind),
                OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_last_taken_sequence",
                    queues.service_fault.last_taken_sequence,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u64_decimal("dual_core", "fault_last_taken_ticks",
                            queues.service_fault.last_taken_ticks,
                            OTIS_SEVERITY_ERROR,
                            OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status("dual_core", "fault_core1_progress_phase",
                otis_timing_progress_phase_name(
                    queues.service_fault.timing_phase),
                OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_core1_trace_sequence",
                    queues.service_fault.timing_loop_sequence,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u64_decimal(
        "dual_core", "fault_core1_last_progress_ticks",
        queues.service_fault.timing_last_progress_ticks,
        OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_last_snapshot_sequence",
                    queues.service_fault.last_snapshot_sequence,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_last_snapshot_session",
                    queues.service_fault.last_snapshot_session,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_last_count_sequence",
                    queues.service_fault.last_count_sequence,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_last_estimate_sequence",
                    queues.service_fault.last_estimate_sequence,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  }
  emit_status("dual_core", "partition_fault",
              otis_partition_fault_name(queues.fault),
              queues.fail_static ? OTIS_SEVERITY_ERROR : OTIS_SEVERITY_INFO,
              queues.fail_static ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                                 : OTIS_FLAG_NONE);
  emit_status("dual_core", "fail_static",
              queues.fail_static ? "true" : "false",
              queues.fail_static ? OTIS_SEVERITY_ERROR : OTIS_SEVERITY_INFO,
              queues.fail_static ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                                 : OTIS_FLAG_NONE);
  emit_status("dual_core", "core0_role",
              "service_io_actuator_execution", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("dual_core", "core1_role", "protected_timing_discipline",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  otis_cx317_preview_live_emit_status(&status_emit_context);
#if OTIS_ENABLE_GNSS_RECEIVER
  emit_gnss_receiver_status();
#endif
#if OTIS_ENABLE_PHASE_FREQUENCY_PREVIEW
  OtisPhasePreviewLiveStatus cx318 = {};
  otis_phase_preview_live_get_status(&cx318);
  emit_status("cx318_preview", "initialized",
              cx318.initialized ? "true" : "false",
              cx318.initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              cx318.initialized ? OTIS_FLAG_NONE
                                : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u16_hex("cx318_preview", "static_code", cx318.static_code,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex("cx318_preview", "applied_code", cx318.applied_code,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("cx318_preview", "dac_epoch", cx318.dac_epoch,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("cx318_preview", "published_records",
                  cx318.published_records, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("cx318_preview", "last_phase_epoch",
                  cx318.last_phase_epoch, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("cx318_preview", "last_observation_sequence",
                  cx318.last_observation_sequence, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
#endif
  return;
#endif

  uint32_t capture_dropped_count = otis_capture_ring_dropped_count();
  uint32_t boundary_dropped_count =
      otis_pps_count_boundary_ring_dropped_count();
  uint32_t drop_flag = OTIS_FLAG_NONE;
  if (capture_dropped_count || boundary_dropped_count) {
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
    drop_flag = OTIS_FLAG_CAPTURE_OVERFLOW_NEARBY;
#else
    drop_flag = OTIS_FLAG_CAPTURE_RING_OVERRUN;
#endif
  }

  emit_status_u32("system", "uptime_seconds", now_ms / 1000u,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("capture", "event_count",
                  runtime_state.capture.emitted_event_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("capture", "dropped_count", capture_dropped_count,
                  capture_dropped_count ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
                  drop_flag);
  emit_status_u32(
      "capture", "pps_count_boundary_dropped_count",
      boundary_dropped_count,
      boundary_dropped_count ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
      boundary_dropped_count ? OTIS_FLAG_CAPTURE_RING_OVERRUN
                             : OTIS_FLAG_NONE);
  emit_status_u32("capture", "error_flags", drop_flag,
                  capture_dropped_count || boundary_dropped_count
                      ? OTIS_SEVERITY_WARN
                      : OTIS_SEVERITY_INFO,
                  drop_flag);
  otis_count_observation_emit_status(&runtime_state, &status_emit_context);
  otis_observe_only_discipline_live_emit_status(&status_emit_context);
  otis_cx317_preview_live_emit_status(&status_emit_context);
#if !OTIS_ENABLE_DUAL_CORE_PARTITION
  otis_cx317_active_live_emit_status(&status_emit_context, now_ms / 1000u);
#endif
#if OTIS_ENABLE_GNSS_RECEIVER
  emit_gnss_receiver_status();
#endif
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_IRQ
  OtisCaptureIrqReferenceStats d14_stats;
  otis_capture_irq_get_reference_stats(&d14_stats);
  emit_status_u32("pps_d14", "raw_edge_count", d14_stats.d14_raw_edge_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("pps_d14", "accepted_pps_count",
                  d14_stats.d14_accepted_pps_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("pps_d14", "rejected_short_count",
                  d14_stats.d14_rejected_short_count,
                  d14_stats.d14_rejected_short_count ? OTIS_SEVERITY_WARN
                                                     : OTIS_SEVERITY_INFO,
                  d14_stats.d14_rejected_short_count ? OTIS_FLAG_PULSE_TOO_NARROW
                                                     : OTIS_FLAG_NONE);
  emit_status_u32("pps_d14", "rejected_long_count",
                  d14_stats.d14_rejected_long_count,
                  d14_stats.d14_rejected_long_count ? OTIS_SEVERITY_WARN
                                                    : OTIS_SEVERITY_INFO,
                  d14_stats.d14_rejected_long_count ? OTIS_FLAG_PULSE_TOO_WIDE
                                                    : OTIS_FLAG_NONE);
  emit_status_u64_decimal("pps_d14", "last_raw_timestamp",
                          d14_stats.d14_last_raw_timestamp, OTIS_SEVERITY_INFO,
                          OTIS_FLAG_NONE);
  emit_status_u64_decimal("pps_d14", "last_raw_interval",
                          d14_stats.d14_last_raw_interval, OTIS_SEVERITY_INFO,
                          OTIS_FLAG_NONE);
  emit_status_u64_decimal("pps_d14", "last_accepted_timestamp",
                          d14_stats.d14_last_accepted_timestamp,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("pps_d14", "sampled_high_count",
                  d14_stats.d14_sampled_high_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("pps_d14", "sampled_low_count",
                  d14_stats.d14_sampled_low_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
#endif
#if OTIS_ENABLE_PPS_DUAL_OBSERVER
  OtisPpsDualObserverStats d10_stats;
  otis_pps_dual_observer_get_stats(&d10_stats);
  int32_t raw_delta = (int32_t)d14_stats.d14_raw_edge_count -
                      (int32_t)d10_stats.d10_raw_edge_count;
  const char *agreement = "MATCHING";
  if (d14_stats.d14_raw_edge_count == 0u || d10_stats.d10_raw_edge_count == 0u) {
    agreement = "INSUFFICIENT_DATA";
  } else if (raw_delta > 1) {
    agreement = "D14_EXCESS";
  } else if (raw_delta < -1) {
    agreement = "D10_EXCESS";
  } else if (d14_stats.d14_rejected_short_count && d10_stats.d10_short_interval_count) {
    agreement = "BOTH_BURSTING";
  }
  emit_status_u32("pps_d10", "raw_edge_count", d10_stats.d10_raw_edge_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u64_decimal("pps_d10", "last_edge_timestamp",
                          d10_stats.d10_last_edge_timestamp, OTIS_SEVERITY_INFO,
                          OTIS_FLAG_NONE);
  emit_status_u64_decimal("pps_d10", "last_interval",
                          d10_stats.d10_last_interval, OTIS_SEVERITY_INFO,
                          OTIS_FLAG_NONE);
  emit_status_u32("pps_d10", "short_interval_count",
                  d10_stats.d10_short_interval_count,
                  d10_stats.d10_short_interval_count ? OTIS_SEVERITY_WARN
                                                     : OTIS_SEVERITY_INFO,
                  d10_stats.d10_short_interval_count ? OTIS_FLAG_PULSE_TOO_NARROW
                                                     : OTIS_FLAG_NONE);
  emit_status_u32("pps_d10", "sampled_high_count",
                  d10_stats.d10_sampled_high_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("pps_d10", "sampled_low_count",
                  d10_stats.d10_sampled_low_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("pps_d10", "buffer_overflow_count",
                  d10_stats.d10_buffer_overflow_count,
                  d10_stats.d10_buffer_overflow_count ? OTIS_SEVERITY_WARN
                                                      : OTIS_SEVERITY_INFO,
                  d10_stats.d10_buffer_overflow_count ? OTIS_FLAG_CAPTURE_RING_OVERRUN
                                                      : OTIS_FLAG_NONE);
  emit_status_i32("pps_dual_observer", "d14_raw_minus_d10_raw",
                  raw_delta, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("pps_dual_observer", "agreement_state", agreement,
              strcmp(agreement, "MATCHING") == 0 ? OTIS_SEVERITY_INFO
                                                 : OTIS_SEVERITY_WARN,
              strcmp(agreement, "MATCHING") == 0 ? OTIS_FLAG_NONE
                                                 : OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT);
  emit_status("pps_dual_observer", "burst_active",
              d10_stats.pps_burst_active ? "true" : "false",
              d10_stats.pps_burst_active ? OTIS_SEVERITY_WARN
                                         : OTIS_SEVERITY_INFO,
              d10_stats.pps_burst_active ? OTIS_FLAG_RATE_TOO_HIGH
                                         : OTIS_FLAG_NONE);
  emit_status_u32("pps_dual_observer", "burst_count",
                  d10_stats.pps_burst_count,
                  d10_stats.pps_burst_count ? OTIS_SEVERITY_WARN
                                            : OTIS_SEVERITY_INFO,
                  d10_stats.pps_burst_count ? OTIS_FLAG_RATE_TOO_HIGH
                                            : OTIS_FLAG_NONE);
#endif
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  OtisCaptureBackendStats backend_stats;
  otis_capture_backend_get_stats(&backend_stats);
  emit_status_u32("capture", "pio_fifo_drained_event_count",
                  backend_stats.pio_edges, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("capture", "pio_fifo_empty_count",
                  backend_stats.pio_fifo_empty_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("capture", "pio_fifo_overflow_drop_count",
                  backend_stats.backend_overflows,
                  backend_stats.backend_overflows ? OTIS_SEVERITY_WARN
                                                  : OTIS_SEVERITY_INFO,
                  backend_stats.backend_overflows
                      ? OTIS_FLAG_CAPTURE_OVERFLOW_NEARBY
                      : OTIS_FLAG_NONE);
  emit_status_u32("capture", "pio_fifo_max_drain_batch",
                  backend_stats.pio_fifo_max_drain_batch, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
#endif
}

bool begin_edge_capture_backend(uint32_t gpio, uint32_t channel_id,
                                bool reference_record, int interrupt_mode) {
  OtisCaptureBackendConfig config = {
      gpio,
      channel_id,
      reference_record,
      interrupt_mode,
      emit_captured_edge,
  };
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  return otis_capture_backend_begin(OtisCaptureBackendKind::PioEdgeQueue,
                                    config);
#else
  return otis_capture_backend_begin(OtisCaptureBackendKind::GpioIrq, config);
#endif
}

bool begin_pps_dual_observer_if_enabled(void) {
#if OTIS_ENABLE_PPS_DUAL_OBSERVER
  bool ok = otis_pps_dual_observer_begin(OTIS_PIN_GENERIC_EVENT);
  emit_status("pps_dual_observer", "init", ok ? "ok" : "failed",
              ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              ok ? OTIS_FLAG_PROFILE_ASSUMPTION : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  return ok;
#else
  return true;
#endif
}

void emit_synthetic_fixture(void) {
  otis_emit_raw_event(OTIS_RECORD_EVT, runtime_state.sequences.event_seq++,
                      OTIS_CHANNEL_GENERIC_EVENT, OTIS_EDGE_RISING,
                      1600001234ull, OTIS_DOMAIN_RP2040_TIMER0,
                      OTIS_FLAG_NONE);
  otis_emit_raw_event(OTIS_RECORD_EVT, runtime_state.sequences.event_seq++,
                      OTIS_CHANNEL_GENERIC_EVENT, OTIS_EDGE_FALLING,
                      1600001872ull, OTIS_DOMAIN_RP2040_TIMER0,
                      OTIS_FLAG_NONE);
  otis_emit_raw_event(OTIS_RECORD_REF, runtime_state.sequences.event_seq++,
                      OTIS_CHANNEL_PPS_REFERENCE, OTIS_EDGE_RISING,
                      1616000000ull, OTIS_DOMAIN_RP2040_TIMER0,
                      OTIS_FLAG_NONE);
  otis_emit_raw_event(OTIS_RECORD_REF, runtime_state.sequences.event_seq++,
                      OTIS_CHANNEL_PPS_REFERENCE, OTIS_EDGE_RISING,
                      1632000000ull, OTIS_DOMAIN_RP2040_TIMER0,
                      OTIS_FLAG_NONE);
  otis_emit_count_observation(runtime_state.sequences.count_seq++,
                              OTIS_CHANNEL_OSC_OBSERVATION, 1600000000ull,
                              1616000000ull, OTIS_DOMAIN_RP2040_TIMER0,
                              16000000ull, OTIS_EDGE_RISING,
                              OTIS_DOMAIN_H0_TCXO_16MHZ, OTIS_FLAG_NONE);
  runtime_state.capture.emitted_event_count = 4;
}

void configure_synthetic_usb_mode(void) {
  emit_synthetic_fixture();
}

void configure_gpio_loopback_mode(void) {
  emit_status("pins", "gpio_loopback_output", "D7", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("wiring", "gpio_loopback", "D7_to_D10", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  bool ok = capability_ready(OtisBootCapability::SparseCapture);
  emit_status("capture", "pio_init", ok ? "ok" : "failed",
              ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              ok ? OTIS_FLAG_PROFILE_ASSUMPTION : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("capture", "pio_gpio", OTIS_PIN_GENERIC_EVENT,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("capture", "pio_edge", "R", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  if (ok) {
    emit_status_u32("capture", "pio_block", 0u, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("capture", "pio_sm",
                    (uint32_t)otis_capture_pio_state_machine(),
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  }
#endif
}

void configure_gps_pps_mode(void) {
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  bool ok = capability_ready(OtisBootCapability::PpsCapture);
  emit_status("capture", "pio_init", ok ? "ok" : "failed",
              ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              ok ? OTIS_FLAG_PROFILE_ASSUMPTION : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("capture", "pio_gpio", OTIS_PIN_PPS_REFERENCE,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("capture", "pio_edge", "R", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  if (ok) {
    emit_status_u32("capture", "pio_block", 0u, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("capture", "pio_sm",
                    (uint32_t)otis_capture_pio_state_machine(),
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  }
#endif
}

void configure_tcxo_observe_mode(void) {
  // In TCXO observe mode the edge-capture backend, including PIO FIFO when
  // enabled, remains on sparse PPS input. Raw CXO input on D8 / GPIO20 is
  // handled by the selected count-observation backend, not FIFO records.
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  bool ok = capability_ready(OtisBootCapability::PpsCapture);
  emit_status("capture", "pio_init", ok ? "ok" : "failed",
              ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              ok ? OTIS_FLAG_PROFILE_ASSUMPTION : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("capture", "pio_gpio", OTIS_PIN_PPS_REFERENCE,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("capture", "pio_edge", "R", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  if (ok) {
    emit_status_u32("capture", "pio_block", 0u, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("capture", "pio_sm",
                    (uint32_t)otis_capture_pio_state_machine(),
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  }
#endif
}

void emit_dac_status(const char *component) {
  OtisDacAd5693rStatus status;
  otis_dac_ad5693r_get_status(&status);
  emit_status(component, "enabled", status.enabled ? "true" : "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(component, "initialized", status.initialized ? "true" : "false",
              status.initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.enabled ? OTIS_FLAG_NONE : OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(component, "last_write_ok", status.last_write_ok ? "true" : "false",
              status.last_write_ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              OTIS_FLAG_NONE);
  emit_status(component, "applied_code_known",
              status.applied_code_known ? "true" : "false",
              status.applied_code_known ? OTIS_SEVERITY_INFO
                                        : OTIS_SEVERITY_WARN,
              OTIS_FLAG_NONE);
  emit_status_u32(component, "i2c_address", status.i2c_address,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex(component, "min_code", status.min_code,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex(component, "max_code", status.max_code,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
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
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(component, "reference_mode", status.reference_mode,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
}

#if OTIS_ENABLE_H1_DAC_SWEEP
struct H1DacSweepStep {
  uint16_t code;
  uint32_t dwell_ms;
};

struct H1DacSweepState {
  H1DacSweepStep steps[OTIS_H1_DAC_SWEEP_MAX_STEPS];
  uint8_t step_count;
  uint8_t active_step;
  bool running;
  bool pending_start;
  bool dwell_active;
  uint32_t dwell_started_ms;
  uint16_t last_requested_code;
  uint16_t last_applied_code;
  uint32_t last_dwell_ms;
  const char *profile_name;
};

H1DacSweepState h1_dac_sweep = {
    {},
    0,
    0,
    false,
    false,
    false,
    0,
    0,
    0,
    0,
    "none",
};

uint16_t h1_dac_sweep_center_code(void) {
  return (uint16_t)(((uint32_t)OTIS_DAC_MIN_CODE +
                    (uint32_t)OTIS_DAC_MAX_CODE) /
                   2u);
}

bool h1_dac_sweep_clamps_configured(void) {
  return OTIS_DAC_MIN_CODE > 0u && OTIS_DAC_MAX_CODE < 0xFFFFu &&
         OTIS_DAC_MIN_CODE <= OTIS_DAC_MAX_CODE;
}

void emit_sweep_record(int32_t step_index, uint16_t requested_code,
                       uint16_t applied_code, bool clamped,
                       uint32_t dwell_ms, const char *event,
                       uint32_t flags) {
  otis_emit_dac_step(runtime_state.sequences.dac_seq++, millis(), step_index,
                     requested_code, applied_code, clamped, "", "", dwell_ms,
                     event, flags);
}

void emit_sweep_status(void) {
  emit_status("sweep", "enabled", "true", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("sweep", "running", h1_dac_sweep.running ? "true" : "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("sweep", "pending_start",
              h1_dac_sweep.pending_start ? "true" : "false",
              h1_dac_sweep.pending_start ? OTIS_SEVERITY_WARN
                                         : OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("sweep", "profile", h1_dac_sweep.profile_name,
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("sweep", "step_count", h1_dac_sweep.step_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("sweep", "active_step", h1_dac_sweep.active_step,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("sweep", "clamps_configured",
              h1_dac_sweep_clamps_configured() ? "true" : "false",
              h1_dac_sweep_clamps_configured() ? OTIS_SEVERITY_INFO
                                               : OTIS_SEVERITY_WARN,
              OTIS_FLAG_PROFILE_ASSUMPTION);
}

bool h1_dac_sweep_add_step(uint16_t code, uint32_t dwell_ms) {
  if (!h1_dac_sweep_clamps_configured()) {
    emit_status("sweep", "add", "rejected_clamps_not_configured",
                OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_sweep_record(-1, code, otis_dac_ad5693r_clamp_code(code), true,
                      dwell_ms, "safety_reject", OTIS_FLAG_PROFILE_ASSUMPTION);
    return false;
  }
  if (h1_dac_sweep.step_count >= OTIS_H1_DAC_SWEEP_MAX_STEPS) {
    emit_status("sweep", "add", "rejected_full", OTIS_SEVERITY_WARN,
                OTIS_FLAG_PROFILE_ASSUMPTION);
    return false;
  }
  if (otis_dac_ad5693r_clamp_code(code) != code) {
    emit_sweep_record(-1, code, otis_dac_ad5693r_clamp_code(code), true,
                      dwell_ms, "safety_reject", OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("sweep", "add", "rejected_outside_clamps",
                OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
    return false;
  }
  h1_dac_sweep.steps[h1_dac_sweep.step_count++] = {code, dwell_ms};
  h1_dac_sweep.profile_name = "custom";
  emit_sweep_record((int32_t)(h1_dac_sweep.step_count - 1u), code, code, false,
                    dwell_ms, "step_added", OTIS_FLAG_NONE);
  return true;
}

void h1_dac_sweep_clear(void) {
  h1_dac_sweep.running = false;
  h1_dac_sweep.pending_start = false;
  h1_dac_sweep.dwell_active = false;
  h1_dac_sweep.active_step = 0;
  h1_dac_sweep.step_count = 0;
  h1_dac_sweep.profile_name = "none";
  emit_sweep_record(-1, 0, 0, false, 0, "clear", OTIS_FLAG_NONE);
}

bool h1_dac_sweep_load_profile(const char *profile_name) {
  if (!h1_dac_sweep_clamps_configured()) {
    emit_status("sweep", "load", "rejected_clamps_not_configured",
                OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_sweep_record(-1, 0, 0, false, 0, "safety_reject",
                      OTIS_FLAG_PROFILE_ASSUMPTION);
    return false;
  }

  uint32_t candidate_codes[9];
  uint8_t count = 0;
  uint16_t center = h1_dac_sweep_center_code();
  uint32_t step = (uint32_t)OTIS_H1_DAC_SWEEP_TINY_STEP_CODES;
  const uint32_t dwell_ms = OTIS_H1_DAC_SWEEP_DEFAULT_DWELL_MS;
  uint32_t profile_dwell_ms = dwell_ms;
  const char *loaded_name = nullptr;

  if (strcmp(profile_name, "CENTER_ONLY") == 0) {
    candidate_codes[count++] = center;
    loaded_name = "center_only";
  } else if (strcmp(profile_name, "TINY_PLUS_MINUS_1") == 0) {
    candidate_codes[count++] = center;
    candidate_codes[count++] = (uint32_t)center + step;
    candidate_codes[count++] = center;
    candidate_codes[count++] = (uint32_t)center - step;
    candidate_codes[count++] = center;
    loaded_name = "tiny_plus_minus_1";
  } else if (strcmp(profile_name, "TINY_PLUS_MINUS_2") == 0) {
    candidate_codes[count++] = center;
    candidate_codes[count++] = (uint32_t)center + step;
    candidate_codes[count++] = center;
    candidate_codes[count++] = (uint32_t)center - step;
    candidate_codes[count++] = center;
    candidate_codes[count++] = (uint32_t)center + (2u * step);
    candidate_codes[count++] = center;
    candidate_codes[count++] = (uint32_t)center - (2u * step);
    candidate_codes[count++] = center;
    loaded_name = "tiny_plus_minus_2";
  } else if (strcmp(profile_name, "SLOPE_CENTER_EDGE_300S") == 0) {
    profile_dwell_ms = OTIS_H1_DAC_SWEEP_SLOPE_DWELL_MS;
    candidate_codes[count++] = center;
    candidate_codes[count++] = OTIS_DAC_MAX_CODE;
    candidate_codes[count++] = center;
    candidate_codes[count++] = OTIS_DAC_MIN_CODE;
    candidate_codes[count++] = center;
    loaded_name = "slope_center_edge_300s";
  } else if (strcmp(profile_name, "SLOPE_REPEAT_300S") == 0) {
    profile_dwell_ms = OTIS_H1_DAC_SWEEP_SLOPE_DWELL_MS;
    uint32_t half_high = (uint32_t)center + ((uint32_t)OTIS_DAC_MAX_CODE -
                                            (uint32_t)center) / 2u;
    uint32_t half_low = (uint32_t)center - ((uint32_t)center -
                                           (uint32_t)OTIS_DAC_MIN_CODE) / 2u;
    candidate_codes[count++] = center;
    candidate_codes[count++] = half_high;
    candidate_codes[count++] = center;
    candidate_codes[count++] = half_low;
    candidate_codes[count++] = center;
    candidate_codes[count++] = OTIS_DAC_MAX_CODE;
    candidate_codes[count++] = center;
    candidate_codes[count++] = OTIS_DAC_MIN_CODE;
    candidate_codes[count++] = center;
    loaded_name = "slope_repeat_300s";
  } else {
    emit_status("sweep", "load", "rejected_unknown_profile",
                OTIS_SEVERITY_WARN, OTIS_FLAG_NONE);
    return false;
  }

  for (uint8_t index = 0; index < count; ++index) {
    if (candidate_codes[index] > 0xFFFFu ||
        otis_dac_ad5693r_clamp_code((uint16_t)candidate_codes[index]) !=
            (uint16_t)candidate_codes[index]) {
      uint16_t requested = candidate_codes[index] > 0xFFFFu
                               ? 0xFFFFu
                               : (uint16_t)candidate_codes[index];
      emit_sweep_record(index, requested,
                        otis_dac_ad5693r_clamp_code(requested), true,
                        profile_dwell_ms, "safety_reject",
                        OTIS_FLAG_PROFILE_ASSUMPTION);
      emit_status("sweep", "load", "rejected_profile_exceeds_clamps",
                  OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
      return false;
    }
  }

  h1_dac_sweep_clear();
  for (uint8_t index = 0; index < count; ++index) {
    h1_dac_sweep.steps[index] = {(uint16_t)candidate_codes[index],
                                 profile_dwell_ms};
    emit_sweep_record(index, (uint16_t)candidate_codes[index],
                      (uint16_t)candidate_codes[index], false,
                      profile_dwell_ms, "profile_step", OTIS_FLAG_NONE);
  }
  h1_dac_sweep.step_count = count;
  h1_dac_sweep.profile_name = loaded_name;
  emit_status("sweep", "load", "ok", OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("sweep", "profile", loaded_name, OTIS_SEVERITY_INFO,
              OTIS_FLAG_NONE);
  emit_sweep_record(-1, center, center, false, profile_dwell_ms,
                    "profile_loaded", OTIS_FLAG_NONE);
  return true;
}

bool h1_dac_sweep_apply_active_step(const char *event_name) {
  if (h1_dac_sweep.active_step >= h1_dac_sweep.step_count) {
    emit_status("sweep", "step", "rejected_no_step", OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
    return false;
  }
  H1DacSweepStep step = h1_dac_sweep.steps[h1_dac_sweep.active_step];
  uint16_t clamped = otis_dac_ad5693r_clamp_code(step.code);
  if (clamped != step.code) {
    emit_sweep_record(h1_dac_sweep.active_step, step.code, clamped, true,
                      step.dwell_ms, "safety_reject",
                      OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("sweep", "step", "rejected_outside_clamps",
                OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
    h1_dac_sweep.running = false;
    h1_dac_sweep.dwell_active = false;
    return false;
  }
  if (!otis_dac_ad5693r_is_enabled()) {
    emit_sweep_record(h1_dac_sweep.active_step, step.code, clamped, false,
                      step.dwell_ms, "rejected_disabled",
                      OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    return false;
  }
  if (!otis_dac_ad5693r_is_initialized()) {
    emit_sweep_record(h1_dac_sweep.active_step, step.code, clamped, false,
                      step.dwell_ms, "rejected_not_initialized",
                      OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    return false;
  }

  bool ok = otis_dac_ad5693r_set_raw(step.code);
  if (ok) {
    otis_observe_only_discipline_live_on_dac_applied(
        clamped, otis_capture_ticks_now());
    otis_cx317_preview_live_on_dac_applied(clamped, millis() / 1000u);
  }
  h1_dac_sweep.last_requested_code = step.code;
  h1_dac_sweep.last_applied_code = ok ? clamped : h1_dac_sweep.last_applied_code;
  h1_dac_sweep.last_dwell_ms = step.dwell_ms;
  h1_dac_sweep.dwell_started_ms = millis();
  h1_dac_sweep.dwell_active = ok;
  emit_sweep_record(h1_dac_sweep.active_step, step.code, clamped, false,
                    step.dwell_ms, ok ? event_name : "write_failed",
                    ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  if (ok) {
    emit_sweep_record(h1_dac_sweep.active_step, step.code, clamped, false,
                      step.dwell_ms, "dwell_start", OTIS_FLAG_NONE);
  }
  return ok;
}

void h1_dac_sweep_start(void) {
  if (h1_dac_sweep.step_count == 0u) {
    emit_status("sweep", "start", "rejected_no_profile", OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
    return;
  }
  if (!runtime_state.tcxo.valid_for_control) {
    h1_dac_sweep.pending_start = true;
    h1_dac_sweep.running = false;
    h1_dac_sweep.dwell_active = false;
    h1_dac_sweep.active_step = 0;
    emit_sweep_record(-1, 0, 0, false, 0, "pending_control_eligible",
                      OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("sweep", "start", "pending_control_eligible",
                OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
    return;
  }
  h1_dac_sweep.pending_start = false;
  h1_dac_sweep.running = true;
  h1_dac_sweep.active_step = 0;
  h1_dac_sweep.dwell_active = false;
  emit_sweep_record(-1, 0, 0, false, 0, "start", OTIS_FLAG_NONE);
  if (!h1_dac_sweep_apply_active_step("step_apply")) {
    h1_dac_sweep.running = false;
  }
}

void h1_dac_sweep_stop(const char *event_name) {
  if (h1_dac_sweep.dwell_active) {
    emit_sweep_record(h1_dac_sweep.active_step, h1_dac_sweep.last_requested_code,
                      h1_dac_sweep.last_applied_code, false,
                      h1_dac_sweep.last_dwell_ms, "dwell_complete",
                      OTIS_FLAG_NONE);
  }
  h1_dac_sweep.running = false;
  h1_dac_sweep.pending_start = false;
  h1_dac_sweep.dwell_active = false;
  emit_sweep_record(-1, h1_dac_sweep.last_requested_code,
                    h1_dac_sweep.last_applied_code, false,
                    h1_dac_sweep.last_dwell_ms, event_name, OTIS_FLAG_NONE);
}

void h1_dac_sweep_manual_step(void) {
  if (h1_dac_sweep.step_count == 0u) {
    emit_status("sweep", "step", "rejected_no_profile", OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
    return;
  }
  if (h1_dac_sweep.dwell_active) {
    emit_sweep_record(h1_dac_sweep.active_step, h1_dac_sweep.last_requested_code,
                      h1_dac_sweep.last_applied_code, false,
                      h1_dac_sweep.last_dwell_ms, "dwell_complete",
                      OTIS_FLAG_NONE);
    h1_dac_sweep.active_step++;
    h1_dac_sweep.dwell_active = false;
  }
  if (h1_dac_sweep.active_step >= h1_dac_sweep.step_count) {
    h1_dac_sweep.active_step = 0;
  }
  h1_dac_sweep_apply_active_step("manual_step");
}

void service_h1_dac_sweep(void) {
  if (h1_dac_sweep.pending_start && runtime_state.tcxo.valid_for_control) {
    h1_dac_sweep.pending_start = false;
    h1_dac_sweep.running = true;
    h1_dac_sweep.active_step = 0;
    h1_dac_sweep.dwell_active = false;
    emit_sweep_record(-1, 0, 0, false, 0, "start_after_fc0_ready",
                      OTIS_FLAG_NONE);
    if (!h1_dac_sweep_apply_active_step("step_apply")) {
      h1_dac_sweep.running = false;
    }
    return;
  }
  if (!h1_dac_sweep.running || !h1_dac_sweep.dwell_active) {
    return;
  }
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - h1_dac_sweep.dwell_started_ms) <
      h1_dac_sweep.last_dwell_ms) {
    return;
  }

  emit_sweep_record(h1_dac_sweep.active_step, h1_dac_sweep.last_requested_code,
                    h1_dac_sweep.last_applied_code, false,
                    h1_dac_sweep.last_dwell_ms, "dwell_complete",
                    OTIS_FLAG_NONE);
  h1_dac_sweep.active_step++;
  h1_dac_sweep.dwell_active = false;
  if (h1_dac_sweep.active_step >= h1_dac_sweep.step_count) {
    h1_dac_sweep_stop("complete");
    return;
  }
  if (!h1_dac_sweep_apply_active_step("step_apply")) {
    h1_dac_sweep.running = false;
  }
}

void emit_h1_dac_sweep_fc0_window(void) {
  if (!h1_dac_sweep.running && !h1_dac_sweep.dwell_active) {
    return;
  }
  emit_sweep_record(h1_dac_sweep.active_step, h1_dac_sweep.last_requested_code,
                    h1_dac_sweep.last_applied_code, false,
                    h1_dac_sweep.last_dwell_ms, "fc0_window",
                    OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
}
#endif

void configure_h1_ocxo_observe_mode(void) {
  emit_status("system", "h1_open_loop", "true", OTIS_SEVERITY_WARN,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("control", "gpsdo_steering", "not_implemented",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  configure_tcxo_observe_mode();

#if OTIS_ENABLE_DAC_AD5693R
  bool ok = capability_ready(OtisBootCapability::Dac);
  emit_status("dac", "init", ok ? "ok" : "failed",
              ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
#else
  emit_status("dac", "init", "disabled", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
  emit_dac_status("dac");
#if OTIS_ENABLE_ENV_SENSORS
  bool env_ok = capability_ready(OtisBootCapability::Sensors);
  emit_status("environment", "init", env_ok ? "ok" : "failed",
              env_ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              env_ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
#else
  emit_status("environment", "init", "disabled", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
  emit_env_sensor_status();
#if OTIS_ENABLE_GNSS_RECEIVER
  emit_gnss_receiver_status();
#endif
#if OTIS_ENABLE_H1_DAC_SWEEP
  emit_sweep_status();
#endif
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
#if OTIS_ENABLE_DUAL_CORE_PARTITION
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
#else
    otis_observe_only_discipline_live_on_temperature(
        true, sample.temperature_c, timestamp_ticks);
    otis_cx317_preview_live_on_temperature(
        true, sample.temperature_c, millis() / 1000u);
#endif
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
                        timestamp_ticks, OTIS_DOMAIN_RP2040_TIMER0,
                        sample.source, sample.role, temperature, humidity,
                        pressure, OTIS_FLAG_NONE);
}

void service_environment_sensors(void) {
#if OTIS_ENABLE_ENV_SENSORS
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - runtime_state.periodic.last_env_sample_ms) <
      OTIS_ENV_SAMPLE_PERIOD_MS) {
    return;
  }
  runtime_state.periodic.last_env_sample_ms = now_ms;
  OtisEnvSample sample;
#if OTIS_ENABLE_ENV_SHT4X
  if (otis_env_sensors_read_sht4x(&sample)) {
    const uint64_t timestamp_ticks = otis_capture_ticks_now();
    emit_env_sample(sample, timestamp_ticks);
  } else {
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    OtisServiceMessage environment = {};
    environment.kind = OtisServiceMessageKind::Environment;
    environment.environment.sequence = dual_core_service_sequence++;
    environment.environment.timestamp_ticks = otis_capture_ticks_now();
    environment.environment.temperature_valid = false;
    otis_dual_core_publish_service(&environment);
#else
    otis_observe_only_discipline_live_on_temperature(
        false, 0.0f, otis_capture_ticks_now());
    otis_cx317_preview_live_on_temperature(false, 0.0f, millis() / 1000u);
#endif
  }
#endif
#if OTIS_ENABLE_ENV_BMP280
  if (otis_env_sensors_read_bmp280(&sample)) {
    emit_env_sample(sample, otis_capture_ticks_now());
  }
#endif
#endif
}

void setup_mode(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_SYNTHETIC_USB
  configure_synthetic_usb_mode();
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  configure_gpio_loopback_mode();
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPS_PPS
  configure_gps_pps_mode();
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE
  configure_tcxo_observe_mode();
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  configure_h1_ocxo_observe_mode();
#endif
}

void emit_run_mode_status_if_ready(void) {
  if (run_mode_status_emitted || !boot_capabilities.run_mode_marked ||
      !runtime_state.boot.protocol_banner_emitted ||
      !otis_transport_ready()) {
    return;
  }
  emit_common_boot_status();
  emit_h0_pin_status();
  setup_mode();
  emit_selected_capability_status();
  emit_resource_ownership_status();
  run_mode_status_emitted = true;
}

void boot_phase_reset_entry(void) {
  begin_boot_phase(BootPhase::ResetEntry);
#if OTIS_ENABLE_RP2040_BOOT_DIAG
  captureRp2040BootDiag();
#endif
  otisBootBreadcrumbBegin(BootPhase::ResetEntry);
  delay(kOtisBootInitialDelayMs);  // boring but useful during bring-up
  complete_boot_phase(BootPhase::ResetEntry);
}

void boot_phase_early_init(void) {
  begin_boot_phase(BootPhase::EarlyInit);
  const bool valid = otis_resource_registry_begin();
  if (!valid) {
#if OTIS_ENABLE_PSEUDO_PPS_GENERATOR
    otis_pseudo_pps_latch_resource_fault();
#endif
    otis_boot_capability_record(
        &boot_capabilities, OtisBootCapability::ResourceRegistry,
        OtisBootCapabilityOutcome::FatalConflict);
  }
  complete_boot_phase(BootPhase::EarlyInit);
}

void boot_phase_clocks_init(void) {
  begin_boot_phase(BootPhase::ClocksInit);
#if OTIS_FORCE_BOOT_FAIL_BEFORE_CLOCKS
  halt_boot(BootFatal::ForcedBeforeClocks, BootPhase::ClocksInit);
#endif
  record_capability_result(OtisBootCapability::Timebase,
                           otis_timebase_begin());
  complete_boot_phase(BootPhase::ClocksInit);
}

void boot_phase_gpio_init(void) {
  begin_boot_phase(BootPhase::GpioInit);
  otis_status_led_begin();
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  pinMode(OTIS_PIN_GPIO_LOOPBACK_OUTPUT, OUTPUT);
  digitalWrite(OTIS_PIN_GPIO_LOOPBACK_OUTPUT, LOW);
  pinMode(OTIS_PIN_GENERIC_EVENT, INPUT_PULLDOWN);
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPS_PPS || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  pinMode(OTIS_PIN_PPS_REFERENCE, INPUT_PULLDOWN);
#endif
#if OTIS_ENABLE_PSEUDO_PPS_GENERATOR
  pinMode(OTIS_PIN_PSEUDO_PPS_OUTPUT, INPUT);
#endif
  complete_boot_phase(BootPhase::GpioInit);
}

void boot_phase_capture_init(void) {
  begin_boot_phase(BootPhase::CaptureInit);
#if OTIS_FORCE_BOOT_FAIL_BEFORE_CAPTURE
  halt_boot(BootFatal::ForcedBeforeCapture, BootPhase::CaptureInit);
#endif
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  const bool ready =
      begin_edge_capture_backend(OTIS_PIN_GENERIC_EVENT,
                                 OTIS_CHANNEL_GENERIC_EVENT, false, CHANGE);
  record_capability_result(OtisBootCapability::SparseCapture, ready);
#endif
  complete_boot_phase(BootPhase::CaptureInit);
}

void boot_phase_timer_init(void) {
  begin_boot_phase(BootPhase::TimerInit);
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  runtime_state.tcxo.startup_inhibit_start_ms = millis();
  runtime_state.tcxo.startup_inhibit_active = true;
  runtime_state.tcxo.valid_for_control = false;
  runtime_state.tcxo.control_clean_window_count = 0;
  runtime_state.tcxo.fault_after_startup = false;
  OtisCountObservationConfig count_config = count_observation_config();
  const bool ready = otis_count_observation_begin(
      &runtime_state, &status_emit_context, &count_config);
  record_capability_result(OtisBootCapability::CountBackend, ready);
#endif
#if OTIS_ENABLE_PSEUDO_PPS_GENERATOR
  const bool pseudo_pps_ready = otis_pseudo_pps_begin();
  record_capability_result(OtisBootCapability::PseudoPpsGenerator,
                           pseudo_pps_ready);
#endif
  complete_boot_phase(BootPhase::TimerInit);
}

void boot_phase_pps_input_init(void) {
  begin_boot_phase(BootPhase::PpsInputInit);
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPS_PPS || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  const bool pps_ready =
      begin_edge_capture_backend(OTIS_PIN_PPS_REFERENCE,
                                 OTIS_CHANNEL_PPS_REFERENCE, true, RISING);
  record_capability_result(OtisBootCapability::SparseCapture, pps_ready);
  record_capability_result(OtisBootCapability::PpsCapture, pps_ready);
#if OTIS_ENABLE_PPS_DUAL_OBSERVER
  const bool witness_ready = begin_pps_dual_observer_if_enabled();
  record_capability_result(OtisBootCapability::PpsWitness, witness_ready);
#endif
#endif
  complete_boot_phase(BootPhase::PpsInputInit);
}

void boot_phase_ring_buffers_init(void) {
  begin_boot_phase(BootPhase::RingBuffersInit);
  otis_capture_ring_reset();
  otis_pps_count_boundary_ring_reset();
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

  otis_status_led_boot_test();
  otis_status_led_set(OTIS_SYSTEM_STATE_BOOT_STARTING);
  otis_status_led_poll(millis());
  complete_boot_phase(BootPhase::SerialInit);
}

void boot_phase_protocol_banner(void) {
  begin_boot_phase(BootPhase::ProtocolBanner);
  emit_protocol_banner_if_serial_ready();
  complete_boot_phase(BootPhase::ProtocolBanner);
}

void boot_phase_peripherals_init(void) {
  begin_boot_phase(BootPhase::PeripheralsInit);
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE && \
    OTIS_ENABLE_DAC_AD5693R
  const bool dac_ready = otis_dac_ad5693r_begin();
  record_capability_result(OtisBootCapability::Dac, dac_ready);
#endif
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE && \
    OTIS_ENABLE_ENV_SENSORS && \
    (OTIS_ENABLE_ENV_SHT4X || OTIS_ENABLE_ENV_BMP280)
  const bool sensors_ready = otis_env_sensors_begin();
  record_capability_result(OtisBootCapability::Sensors, sensors_ready);
#endif
#if OTIS_ENABLE_GNSS_RECEIVER
  const bool gnss_receiver_ready = otis_gnss_receiver_begin();
  record_capability_result(OtisBootCapability::GnssReceiver,
                           gnss_receiver_ready);
#endif
  complete_boot_phase(BootPhase::PeripheralsInit);
}

void boot_phase_preview_init(void) {
  begin_boot_phase(BootPhase::PreviewInit);
#if OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW
  const bool preview_ready =
      otis_observe_only_discipline_live_begin(otis_capture_ticks_now());
  record_capability_result(OtisBootCapability::Phase4Preview, preview_ready);
#elif OTIS_ENABLE_CX317_I_ONLY_PREVIEW
  const bool preview_ready =
      otis_cx317_preview_live_begin(millis() / 1000u) &&
      otis_cx317_active_live_begin();
  record_capability_result(OtisBootCapability::Phase4Preview, preview_ready);
#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
  const bool phase_preview_ready = otis_phase_preview_live_begin(
      OTIS_TIGHT_DEADBAND_INITIAL_CODE,
      OTIS_TIGHT_DEADBAND_INITIAL_DAC_EPOCH);
  record_capability_result(OtisBootCapability::PhasePreview,
                           phase_preview_ready);
#endif
#elif OTIS_ENABLE_CX318_STAGE4_PREVIEW
  const bool preview_ready = otis_phase_preview_live_begin(
      OTIS_CX318_STAGE4_STATIC_CODE, OTIS_CX318_STAGE4_DAC_EPOCH);
  record_capability_result(OtisBootCapability::PhasePreview, preview_ready);
#endif
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
#if OTIS_FORCE_BOOT_FAIL_BEFORE_RUN_MODE
  halt_boot(BootFatal::ForcedBeforeRunMode, BootPhase::RunMode);
#endif
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
  otis_status_led_set(OTIS_SYSTEM_STATE_USB_CONFIG_DEBUG);
  otisBootBreadcrumbMarkRunMode();
#if !OTIS_ENABLE_DUAL_CORE_PARTITION
  emit_run_mode_status_if_ready();
#endif
}

void service_loopback_output(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - runtime_state.loopback.last_toggle_ms) >=
      kLoopbackTogglePeriodMs) {
    runtime_state.loopback.last_toggle_ms = now_ms;
    runtime_state.loopback.output_high = !runtime_state.loopback.output_high;
    digitalWrite(OTIS_PIN_GPIO_LOOPBACK_OUTPUT,
                 runtime_state.loopback.output_high ? HIGH : LOW);
  }
#endif
}

void service_tcxo_gate(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  OtisCountObservationConfig count_config = count_observation_config();
  if (otis_count_observation_service(&runtime_state, &status_emit_context,
                                     &count_config)) {
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    OtisObserveOnlyDisciplineLiveDacState phase4_dac = {
        dual_core_static_code.available &&
            dual_core_static_code.requested_applied_match &&
            dual_core_static_code.i2c_ok,
        dual_core_static_code.applied_code,
    };
#else
    OtisDacAd5693rStatus dac_status;
    otis_dac_ad5693r_get_status(&dac_status);
    OtisObserveOnlyDisciplineLiveDacState phase4_dac = {
        dac_status.applied_code_known && dac_status.last_write_ok &&
            dac_status.last_requested_code == dac_status.last_applied_code,
        dac_status.last_applied_code,
    };
#endif
    otis_observe_only_discipline_live_on_count(
        runtime_state.sequences.count_seq - 1u, &runtime_state, &phase4_dac);
#if OTIS_ENABLE_H1_DAC_SWEEP && \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
    emit_h1_dac_sweep_fc0_window();
#endif
  }
#endif
}

void handle_dac_set(uint16_t requested_code) {
  emit_status_u16_hex("dac", "requested_code", requested_code,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && OTIS_ENABLE_DUAL_CORE_PARTITION
  // This profile accepts its initial physical write only through the
  // generation-, nonce-, session-, configuration-, and expiry-bound
  // ACTIVE SETUP transaction. The generic DAC surface is non-actuating.
  emit_status("dac", "set", "rejected_use_active_setup_transaction",
              OTIS_SEVERITY_ERROR, OTIS_FLAG_PROFILE_ASSUMPTION);
  return;
#endif
#if OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP
  if (requested_code != OTIS_CX318_STAGE4_PREMISE_SETUP_CODE ||
      cx318_stage4_premise_write_consumed) {
    emit_status("cx318_premise", "write_attempt",
                "rejected_not_exact_one_shot_a828", OTIS_SEVERITY_ERROR,
                OTIS_FLAG_PROFILE_ASSUMPTION);
    return;
  }
  // Consume before I2C so a failed application cannot be retried in this boot.
  cx318_stage4_premise_write_consumed = true;
  emit_status("cx318_premise", "write_consumed", "true",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  if (requested_code != OTIS_CX317_ACTIVE_START_CODE ||
      dual_core_manual_start_consumed) {
    OtisServiceMessage abort = {};
    abort.kind = OtisServiceMessageKind::RunControl;
    abort.run_control.sequence = dual_core_service_sequence++;
    abort.run_control.published_ticks = otis_capture_ticks_now();
    abort.run_control.kind = OtisRunControlKind::Abort;
    abort.run_control.asserted = true;
    otis_dual_core_publish_service(&abort);
    emit_status("dac", "set", "rejected_active_profile_start_only",
                OTIS_SEVERITY_ERROR, OTIS_FLAG_PROFILE_ASSUMPTION);
    return;
  }
#else
  if (!otis_cx317_active_live_manual_start_allowed(requested_code)) {
    otis_cx317_active_live_abort("nonprogramme_manual_dac_command");
    emit_status("dac", "set", "rejected_active_profile_start_only",
                OTIS_SEVERITY_ERROR, OTIS_FLAG_PROFILE_ASSUMPTION);
    return;
  }
#endif
#endif
  if (!otis_dac_ad5693r_is_enabled()) {
    emit_status("dac", "set", "rejected_disabled", OTIS_SEVERITY_WARN,
                OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    return;
  }
  if (!otis_dac_ad5693r_is_initialized()) {
    emit_status("dac", "set", "rejected_not_initialized", OTIS_SEVERITY_WARN,
                OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    return;
  }
  uint16_t clamped = otis_dac_ad5693r_clamp_code(requested_code);
  if (clamped != requested_code) {
    emit_status_u16_hex("dac", "rejected_code", requested_code,
                        OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("dac", "set", "rejected_outside_clamps", OTIS_SEVERITY_WARN,
                OTIS_FLAG_PROFILE_ASSUMPTION);
    return;
  }
  // Consume the one permitted manual-start opportunity before the physical
  // call so neither a failed write nor a repeated serial command can retry it.
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && OTIS_ENABLE_DUAL_CORE_PARTITION
  dual_core_manual_start_consumed = true;
#endif
  bool ok = otis_dac_ad5693r_set_raw(requested_code);
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
#if !OTIS_ENABLE_DUAL_CORE_PARTITION
  otis_cx317_active_live_note_manual_start(requested_code, ok,
                                           millis() / 1000u);
#endif
#endif
  if (ok) {
    otis_observe_only_discipline_live_on_dac_applied(
        requested_code, otis_capture_ticks_now());
#if !OTIS_ENABLE_DUAL_CORE_PARTITION
    otis_cx317_preview_live_on_dac_applied(requested_code, millis() / 1000u);
#endif
  }
  otis_emit_dac_step(
      runtime_state.sequences.dac_seq++, millis(), -1, requested_code,
      clamped, false, "", "", 0u,
      ok ? "manual_apply" : "manual_write_failed",
      ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u16_hex("dac", ok ? "accepted_code" : "failed_code",
                      requested_code,
                      ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                      ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
}

#if OTIS_ENABLE_H1_DAC_SWEEP
void handle_sweep_add(const OtisParsedSerialCommand &command) {
  if (!command.arguments_valid) {
    emit_status("sweep", "add", "rejected_parse_error", OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
    return;
  }
  h1_dac_sweep_add_step(command.code, command.dwell_ms);
}
#endif

void emit_pseudo_pps_status(void) {
  OtisPseudoPpsStatus status;
  otis_pseudo_pps_get_status(&status);
  emit_status("ppsgen", "state", otis_pseudo_pps_state_name(status.state),
              status.state == OtisPseudoPpsState::ResourceFault ||
                      status.state == OtisPseudoPpsState::UnderflowFault
                  ? OTIS_SEVERITY_ERROR
                  : OTIS_SEVERITY_INFO,
              status.state == OtisPseudoPpsState::ResourceFault ||
                      status.state == OtisPseudoPpsState::UnderflowFault
                  ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                  : OTIS_FLAG_NONE);
  emit_status("ppsgen", "profile", status.profile_id, OTIS_SEVERITY_INFO,
              OTIS_FLAG_NONE);
  emit_status_u32("ppsgen", "profile_version", status.profile_version,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("ppsgen", "session", status.session, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("ppsgen", "step_count", status.step_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("ppsgen", "truth_emitted", status.truth_emitted,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("ppsgen", "pin_sample_count", status.pin_sample_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("ppsgen", "output_high_sample_count",
                  status.output_high_sample_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("ppsgen", "reference_high_sample_count",
                  status.reference_high_sample_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("ppsgen", "output_gpio", OTIS_GPIO_PSEUDO_PPS_OUTPUT,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("ppsgen", "pio_clock_hz", status.pio_clock_hz,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
}

void emit_pseudo_pps_profiles(void) {
  for (size_t index = 0u; index < otis_pseudo_pps_profile_count(); ++index) {
    const OtisPseudoPpsProfile *profile = otis_pseudo_pps_profile_at(index);
    if (profile != nullptr) {
      char key[20];
      snprintf(key, sizeof(key), "profile_%02u", static_cast<unsigned>(index));
      emit_status("ppsgen", key, profile->id, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
    }
  }
}

void execute_serial_command(const OtisParsedSerialCommand &command) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  if (command.kind == OtisSerialCommandKind::Help) {
    emit_status("command", "h1_help",
                "CONFIG?_DUALCORE?_DAC?_DAC_LIMITS?_FC0?_ACTIVE?_ACTIVE_SNAPSHOT_nonce_ACTIVE_SETUP_authority_ACTIVE_LEASE_seq_ACTIVE_ARM_seq_nonce_expiry_ACTIVE_ABORT_ACTIVE_EVIDENCE_request_SWEEP?_PPSGEN?_HELP",
                OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  } else if (command.kind == OtisSerialCommandKind::ConfigQuery) {
    emit_status("command", "config_snapshot", "begin",
                OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    emit_status_u32("dual_core", "pre_carrier_records_discarded",
                    dual_core_pre_carrier_records_discarded,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
#endif
    // A capture opened after the boot banner still needs one complete
    // provenance block for evidence sealing.  Do not repeat the relatively
    // large block at CONFIG? service-load rates.
    if (!config_query_provenance_emitted) {
      emit_build_provenance_status();
      config_query_provenance_emitted = true;
    }
    emit_status("firmware", "version", OTIS_FIRMWARE_VERSION,
                OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("firmware", "config_id", OTIS_FIRMWARE_CONFIG_ID,
                OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("system", "mode", otis_bringup_mode_name(),
                OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("build", "capture_backend", otis_capture_backend_name(),
                OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("build", "tcxo_counter_backend",
                otis_tcxo_counter_backend_name(), OTIS_SEVERITY_INFO,
                OTIS_FLAG_PROFILE_ASSUMPTION);
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
    emit_status("pps_gate", "boundary_owner", "pio_state_machine",
                OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("pps_gate", "aperture_backend",
                "pio_wait_cumulative_snapshot_dma_v1", OTIS_SEVERITY_INFO,
                OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("pps_gate", "backend_qualified",
                OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED ? "true" : "false",
                OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED ? OTIS_SEVERITY_INFO
                                                    : OTIS_SEVERITY_WARN,
                OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("pps_gate", "boundary_ring_capacity",
                    otis_pps_count_boundary_ring_capacity(),
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
    emit_status_u32("capture", "counter_gate_period_us", kTcxoGatePeriodUs,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("build", "enable_pps_dual_observer",
                    OTIS_ENABLE_PPS_DUAL_OBSERVER, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("build", "enable_pseudo_pps_generator",
                    OTIS_ENABLE_PSEUDO_PPS_GENERATOR, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("build", "enable_dac_ad5693r",
                    OTIS_ENABLE_DAC_AD5693R, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("build", "enable_h1_dac_sweep",
                    OTIS_ENABLE_H1_DAC_SWEEP, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("build", "enable_env_sensors", OTIS_ENABLE_ENV_SENSORS,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("build", "enable_env_sht4x", OTIS_ENABLE_ENV_SHT4X,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("build", "enable_env_bmp280", OTIS_ENABLE_ENV_BMP280,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("build", "enable_gnss_receiver",
                    OTIS_ENABLE_GNSS_RECEIVER, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("build", "enable_cx317_bounded_active",
                    OTIS_ENABLE_CX317_BOUNDED_ACTIVE, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("build", "enable_dual_core_partition",
                    OTIS_ENABLE_DUAL_CORE_PARTITION, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    otis_memory_budget_emit_status(&status_emit_context);
    emit_status_u32("sweep", "default_dwell_ms",
                    OTIS_H1_DAC_SWEEP_DEFAULT_DWELL_MS, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("sweep", "slope_dwell_ms",
                    OTIS_H1_DAC_SWEEP_SLOPE_DWELL_MS, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u16_hex("sweep", "tiny_step_codes",
                        OTIS_H1_DAC_SWEEP_TINY_STEP_CODES,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u16_hex(
        "sweep", "center_code",
        (uint16_t)(((uint32_t)OTIS_DAC_MIN_CODE +
                    (uint32_t)OTIS_DAC_MAX_CODE) /
                   2u),
        OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u16_hex("dac", "min_code", OTIS_DAC_MIN_CODE,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u16_hex("dac", "max_code", OTIS_DAC_MAX_CODE,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("command", "config_snapshot", "end",
                OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    const uint32_t nonce = dual_core_service_sequence + 1u;
    const bool requested = queue_dual_core_active_control(
        OtisRunControlKind::DiagnosticConfigQuery, nonce);
    emit_status("command", "timing_config_snapshot",
                requested ? "queued_to_core1" : "rejected_queue_fault",
                requested ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                requested ? OTIS_FLAG_NONE
                          : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
#endif
  } else if (command.kind == OtisSerialCommandKind::DualCoreQuery) {
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    OtisDualCoreQueueStats queues;
    otis_dual_core_get_stats(&queues);
    emit_status_u32("dual_core", "service_to_timing_depth",
                    queues.service_to_timing_depth, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "observation_depth",
                    queues.observation_depth, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_NONE);
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
#else
    emit_status("dual_core", "command", "rejected_disabled",
                OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
  } else if (command.kind ==
             OtisSerialCommandKind::DualCoreInvalidateGnss) {
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    OtisServiceMessage invalidation = {};
    invalidation.kind = OtisServiceMessageKind::RunControl;
    invalidation.run_control.sequence = dual_core_service_sequence++;
    invalidation.run_control.published_ticks = otis_capture_ticks_now();
    invalidation.run_control.authorization_sequence =
        invalidation.run_control.sequence;
    invalidation.run_control.nonce =
        0xD6170000u ^ invalidation.run_control.sequence;
    invalidation.run_control.duration_ms = 5000u;
    invalidation.run_control.kind =
        OtisRunControlKind::SyntheticReceiverInvalidation;
    invalidation.run_control.asserted = true;
    const bool published = otis_dual_core_publish_service(&invalidation);
    emit_status("dual_core", "gnss_fixture_invalidation",
                published ? "accepted_5000ms" : "rejected_queue_fault",
                published ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                published ? OTIS_FLAG_PROFILE_ASSUMPTION
                          : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
#else
    emit_status("dual_core", "gnss_fixture_invalidation",
                "rejected_disabled", OTIS_SEVERITY_WARN,
                OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
  } else if (command.kind == OtisSerialCommandKind::DualCoreRecover) {
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    OtisServiceMessage recovery = {};
    recovery.kind = OtisServiceMessageKind::RunControl;
    recovery.run_control.sequence = dual_core_service_sequence++;
    recovery.run_control.published_ticks = otis_capture_ticks_now();
    recovery.run_control.authorization_sequence =
        recovery.run_control.sequence;
    recovery.run_control.nonce =
        0xD617A000u ^ recovery.run_control.sequence;
    recovery.run_control.kind = OtisRunControlKind::Recover;
    recovery.run_control.asserted = true;
    const bool published = otis_dual_core_publish_service(&recovery);
    emit_status("dual_core", "preview_recovery",
                published ? "queued" : "rejected_queue_fault",
                published ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                published ? OTIS_FLAG_PROFILE_ASSUMPTION
                          : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
#else
    emit_status("dual_core", "preview_recovery", "rejected_disabled",
                OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
  } else if (command.kind == OtisSerialCommandKind::DualCoreOther) {
    emit_status("dual_core", "command", "rejected_unknown",
                OTIS_SEVERITY_WARN, OTIS_FLAG_NONE);
  } else if (command.kind == OtisSerialCommandKind::DacQuery) {
    emit_dac_status("dac");
  } else if (command.kind == OtisSerialCommandKind::DacLimitsQuery) {
    emit_status_u16_hex("dac", "min_code", OTIS_DAC_MIN_CODE,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u16_hex("dac", "max_code", OTIS_DAC_MAX_CODE,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
#if OTIS_ENABLE_CX318_STAGE4_PREVIEW
  } else if (command.kind == OtisSerialCommandKind::DacMid ||
             command.kind == OtisSerialCommandKind::DacZero ||
             command.kind == OtisSerialCommandKind::DacSet) {
    emit_status("cx318_preview", "dac_command_attempt",
                "rejected_write_surface_compiled_out", OTIS_SEVERITY_ERROR,
                OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
#elif OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP
  } else if (command.kind == OtisSerialCommandKind::DacMid ||
             command.kind == OtisSerialCommandKind::DacZero) {
    emit_status("cx318_premise", "alternate_write_surface",
                "rejected_setup_accepts_explicit_dac_set_only",
                OTIS_SEVERITY_ERROR, OTIS_FLAG_PROFILE_ASSUMPTION);
  } else if (command.kind == OtisSerialCommandKind::DacSet) {
    if (command.arguments_valid) {
      handle_dac_set(command.code);
    } else {
      emit_status("dac", "set", "rejected_parse_error", OTIS_SEVERITY_WARN,
                  OTIS_FLAG_NONE);
    }
#else
  } else if (command.kind == OtisSerialCommandKind::DacMid) {
    uint16_t mid = (uint16_t)(((uint32_t)OTIS_DAC_MIN_CODE +
                              (uint32_t)OTIS_DAC_MAX_CODE) /
                             2u);
    handle_dac_set(mid);
  } else if (command.kind == OtisSerialCommandKind::DacZero) {
    handle_dac_set((uint16_t)OTIS_DAC_MIN_CODE);
  } else if (command.kind == OtisSerialCommandKind::DacSet) {
    if (command.arguments_valid) {
      handle_dac_set(command.code);
    } else {
      emit_status("dac", "set", "rejected_parse_error", OTIS_SEVERITY_WARN,
                  OTIS_FLAG_NONE);
    }
#endif
  } else if (command.kind == OtisSerialCommandKind::Fc0Query) {
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    const uint32_t nonce = dual_core_service_sequence + 1u;
    const bool requested = queue_dual_core_active_control(
        OtisRunControlKind::DiagnosticRuntimeQuery, nonce);
    emit_status("command", "timing_runtime_snapshot",
                requested ? "queued_to_core1" : "rejected_queue_fault",
                requested ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                requested ? OTIS_FLAG_NONE
                          : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
#else
    const OtisCountObservationConfig config = count_observation_config();
    otis_count_observation_emit_runtime_status(
        &runtime_state, &status_emit_context, &config);
    otis_count_observation_emit_status(&runtime_state,
                                       &status_emit_context);
#endif
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  } else if (command.kind == OtisSerialCommandKind::ActiveQuery) {
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    const bool accepted = queue_dual_core_active_control(
        OtisRunControlKind::StatusQuery);
    emit_status("cx317_active", "status_query",
                accepted ? "queued_to_core1" : "rejected_queue_fault",
                accepted ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                accepted ? OTIS_FLAG_NONE
                         : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
#else
    otis_cx317_active_live_emit_status(&status_emit_context,
                                       millis() / 1000u);
#endif
  } else if (command.kind == OtisSerialCommandKind::ActiveSnapshot) {
    uint32_t values[1];
    const bool parsed = command.arguments_valid &&
                        parse_active_u32_fields(command.text_argument, values,
                                                1u) &&
                        values[0] != 0u;
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    const bool accepted = parsed && queue_dual_core_active_control(
                                      OtisRunControlKind::StatusQuery,
                                      values[0]);
    emit_status("cx317_active", "snapshot_firmware_received",
                accepted ? "queued_to_core1" : "rejected",
                accepted ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                accepted ? OTIS_FLAG_NONE
                         : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
#else
    if (parsed) {
      otis_cx317_active_live_set_status_query_nonce(values[0]);
      otis_cx317_active_live_emit_status(&status_emit_context,
                                         millis() / 1000u);
    }
#endif
  } else if (command.kind == OtisSerialCommandKind::ActiveSetup) {
    OtisSetupAuthorityRequest request = {};
    const bool parsed = command.arguments_valid &&
                        otis_setup_authority_parse_request(
                            command.text_argument, &request);
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    const bool accepted = parsed &&
                          queue_dual_core_setup_authorization(request);
    emit_status("cx317_setup", "phase",
                accepted ? "firmware_received" : "firmware_rejected",
                accepted ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                accepted ? OTIS_FLAG_NONE
                         : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    if (accepted) {
      emit_status_u32("cx317_setup", "command_sequence",
                      request.command_sequence, OTIS_SEVERITY_INFO,
                      OTIS_FLAG_NONE);
      emit_status_u32("cx317_setup", "authorization_sequence",
                      request.authorization_sequence, OTIS_SEVERITY_INFO,
                      OTIS_FLAG_NONE);
      emit_status_u32("cx317_setup", "status_generation",
                      request.status_generation, OTIS_SEVERITY_INFO,
                      OTIS_FLAG_NONE);
      emit_status_u32("cx317_setup", "query_nonce", request.query_nonce,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    }
#else
    (void)parsed;
    emit_status("cx317_setup", "phase", "rejected_requires_dual_core",
                OTIS_SEVERITY_ERROR, OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
  } else if (command.kind == OtisSerialCommandKind::ActiveLease) {
    uint32_t values[1];
    const bool parsed = command.arguments_valid &&
                        parse_active_u32_fields(command.text_argument, values,
                                                1u);
    const bool accepted = parsed &&
#if OTIS_ENABLE_DUAL_CORE_PARTITION
                          queue_dual_core_active_control(
                              OtisRunControlKind::CaptureLease, values[0]);
#else
                          otis_cx317_active_live_capture_lease(
                              values[0], millis() / 1000u);
#endif
    emit_status("cx317_active", "capture_lease",
                accepted ? "accepted" : "rejected", accepted
                    ? OTIS_SEVERITY_INFO
                    : OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
  } else if (command.kind == OtisSerialCommandKind::ActiveArm) {
    uint32_t values[3];
    const bool parsed = command.arguments_valid &&
                        parse_active_u32_fields(command.text_argument, values,
                                                3u);
    const bool accepted = parsed &&
#if OTIS_ENABLE_DUAL_CORE_PARTITION
                          queue_dual_core_active_control(
                              OtisRunControlKind::Arm, values[0], values[1],
                              values[2]);
#else
                          otis_cx317_active_live_arm(
                              values[0], values[1], values[2],
                              millis() / 1000u);
#endif
    emit_status("cx317_active", "arm",
                accepted ? "accepted" : "rejected", accepted
                    ? OTIS_SEVERITY_INFO
                    : OTIS_SEVERITY_ERROR,
                OTIS_FLAG_NONE);
  } else if (command.kind == OtisSerialCommandKind::ActiveAbort) {
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    const bool accepted =
        queue_dual_core_active_control(OtisRunControlKind::Abort);
    emit_status("cx317_active", "abort",
                accepted ? "queued_to_core1" : "rejected_queue_fault",
                accepted ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_ERROR,
                accepted ? OTIS_FLAG_NONE
                         : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
#else
    otis_cx317_active_live_abort("device_abort_command");
    emit_status("cx317_active", "abort", "accepted", OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
#endif
  } else if (command.kind == OtisSerialCommandKind::ActiveEvidence) {
    uint32_t values[2];
    const bool parsed = command.arguments_valid &&
                        parse_active_u32_fields(command.text_argument, values,
                                                2u);
    const bool accepted = parsed &&
#if OTIS_ENABLE_DUAL_CORE_PARTITION
                          queue_dual_core_active_control(
                              OtisRunControlKind::EvidenceRelease, values[0],
                              values[1]);
#else
                          otis_cx317_active_live_acknowledge_evidence(
                              values[0], values[1], millis() / 1000u);
#endif
    emit_status("cx317_active", "evidence_ack",
                accepted ? "accepted" : "rejected", accepted
                    ? OTIS_SEVERITY_INFO
                    : OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
  } else if (command.kind == OtisSerialCommandKind::ActiveOther) {
    emit_status("cx317_active", "command", "rejected_unknown",
                OTIS_SEVERITY_WARN, OTIS_FLAG_NONE);
#else
  } else if (command.kind == OtisSerialCommandKind::ActiveQuery ||
             command.kind == OtisSerialCommandKind::ActiveSnapshot ||
             command.kind == OtisSerialCommandKind::ActiveSetup ||
             command.kind == OtisSerialCommandKind::ActiveLease ||
             command.kind == OtisSerialCommandKind::ActiveArm ||
             command.kind == OtisSerialCommandKind::ActiveAbort ||
             command.kind == OtisSerialCommandKind::ActiveEvidence ||
             command.kind == OtisSerialCommandKind::ActiveOther) {
    emit_status("cx317_active", "command", "rejected_disabled",
                OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
#if OTIS_ENABLE_PSEUDO_PPS_GENERATOR
  } else if (command.kind == OtisSerialCommandKind::PpsGenProfilesQuery) {
    emit_pseudo_pps_profiles();
  } else if (command.kind == OtisSerialCommandKind::PpsGenQuery) {
    emit_pseudo_pps_status();
  } else if (command.kind == OtisSerialCommandKind::PpsGenArm) {
    bool armed = command.arguments_valid &&
                 otis_pseudo_pps_arm(command.text_argument);
    emit_status("ppsgen", "arm", armed ? "accepted" : "rejected",
                armed ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
                armed ? OTIS_FLAG_NONE : OTIS_FLAG_PROFILE_ASSUMPTION);
  } else if (command.kind == OtisSerialCommandKind::PpsGenStart) {
    bool started = otis_pseudo_pps_start();
    emit_status("ppsgen", "start", started ? "accepted" : "rejected",
                started ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
                started ? OTIS_FLAG_NONE : OTIS_FLAG_PROFILE_ASSUMPTION);
  } else if (command.kind == OtisSerialCommandKind::PpsGenStop) {
    bool stopped = otis_pseudo_pps_stop();
    emit_status("ppsgen", "stop", stopped ? "accepted" : "rejected",
                stopped ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
                stopped ? OTIS_FLAG_NONE : OTIS_FLAG_PROFILE_ASSUMPTION);
  } else if (command.kind == OtisSerialCommandKind::PpsGenOther) {
    emit_status("ppsgen", "command", "rejected_unknown", OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
#else
  } else if (command.kind == OtisSerialCommandKind::PpsGenProfilesQuery ||
             command.kind == OtisSerialCommandKind::PpsGenQuery ||
             command.kind == OtisSerialCommandKind::PpsGenArm ||
             command.kind == OtisSerialCommandKind::PpsGenStart ||
             command.kind == OtisSerialCommandKind::PpsGenStop ||
             command.kind == OtisSerialCommandKind::PpsGenOther) {
    emit_status("ppsgen", "command", "rejected_disabled", OTIS_SEVERITY_WARN,
                OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
#if OTIS_ENABLE_H1_DAC_SWEEP
  } else if (command.kind == OtisSerialCommandKind::SweepQuery) {
    emit_sweep_status();
  } else if (command.kind == OtisSerialCommandKind::SweepLoad) {
    h1_dac_sweep_load_profile(command.text_argument);
  } else if (command.kind == OtisSerialCommandKind::SweepStart) {
    h1_dac_sweep_start();
  } else if (command.kind == OtisSerialCommandKind::SweepStop) {
    h1_dac_sweep_stop("stop");
  } else if (command.kind == OtisSerialCommandKind::SweepStep) {
    h1_dac_sweep_manual_step();
  } else if (command.kind == OtisSerialCommandKind::SweepClear) {
    h1_dac_sweep_clear();
  } else if (command.kind == OtisSerialCommandKind::SweepAdd) {
    handle_sweep_add(command);
#else
  } else if (command.kind == OtisSerialCommandKind::SweepQuery ||
             command.kind == OtisSerialCommandKind::SweepLoad ||
             command.kind == OtisSerialCommandKind::SweepStart ||
             command.kind == OtisSerialCommandKind::SweepStop ||
             command.kind == OtisSerialCommandKind::SweepStep ||
             command.kind == OtisSerialCommandKind::SweepClear ||
             command.kind == OtisSerialCommandKind::SweepAdd ||
             command.kind == OtisSerialCommandKind::SweepOther) {
    emit_status("sweep", "command", "rejected_disabled", OTIS_SEVERITY_WARN,
                OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
  } else if (command.kind != OtisSerialCommandKind::Empty) {
    emit_status("command", "unknown", "rejected_unknown", OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
  }
#else
  (void)command;
#endif
}

void service_serial_commands(bool output_allowed = true) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
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
  if (output_allowed && deferred_abort_result_ready) {
    const bool queued = deferred_abort_queued;
    deferred_abort_result_ready = false;
    deferred_abort_queued = false;
    emit_status("cx317_active", "abort_firmware_received",
                queued ? "queued_to_core1" : "rejected_queue_fault",
                queued ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_ERROR,
                queued ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
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
#if OTIS_ENABLE_DUAL_CORE_PARTITION && OTIS_ENABLE_CX317_BOUNDED_ACTIVE
      if (command.kind == OtisSerialCommandKind::ActiveAbort) {
        deferred_abort_queued = queue_dual_core_active_control(
            OtisRunControlKind::Abort);
        deferred_abort_result_ready = true;
        return;
      }
#endif
      snprintf(deferred_serial_command, sizeof(deferred_serial_command), "%s",
               complete_line);
      deferred_serial_command_ready = true;
      return;
    }
    execute_serial_command(command);
    return;
  }
#else
  (void)output_allowed;
#endif
}

}  // namespace

void setup() {
  otis_memory_budget_note_current_core();
  otis_runtime_state_init(&runtime_state);
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  otis_dual_core_partition_reset();
  otis_transport_liveness_reset(&dual_core_transport_liveness, millis(),
                                otis_transport_written_bytes());
  dual_core_transport_abort_queued = false;
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  otis_actuator_guard_init(&dual_core_service_actuator_guard);
  otis_setup_execution_guard_init(&dual_core_service_setup_guard);
  dual_core_manual_start_consumed = false;
#endif
#endif
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
#if OTIS_ENABLE_DUAL_CORE_PARTITION
    __atomic_store_n(&dual_core_timing_boot_complete, true,
                     __ATOMIC_RELEASE);
    __atomic_store_n(&dual_core_service_boot_ready, true,
                     __ATOMIC_RELEASE);
#endif
    return;
  }

  boot_phase_clocks_init();
  boot_phase_gpio_init();
  boot_phase_ring_buffers_init();
  boot_phase_serial_init();
  boot_phase_protocol_banner();
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  // The count boundary handler must exist before the primary PPS IRQ is armed.
#if !OTIS_ENABLE_DUAL_CORE_PARTITION
  boot_phase_timer_init();
#endif
#endif
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  boot_phase_capture_init();
#endif
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPS_PPS || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
#if !OTIS_ENABLE_DUAL_CORE_PARTITION
  boot_phase_pps_input_init();
#endif
#endif
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE && \
    (OTIS_ENABLE_DAC_AD5693R ||                                   \
     (OTIS_ENABLE_ENV_SENSORS &&                                 \
      (OTIS_ENABLE_ENV_SHT4X || OTIS_ENABLE_ENV_BMP280)) ||       \
     OTIS_ENABLE_GNSS_RECEIVER)
  boot_phase_peripherals_init();
#endif
#if OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW || OTIS_ENABLE_CX317_I_ONLY_PREVIEW
#if !OTIS_ENABLE_DUAL_CORE_PARTITION
  boot_phase_preview_init();
#endif
#endif
#if OTIS_ENABLE_DUAL_CORE_PARTITION
  __atomic_store_n(&dual_core_service_boot_ready, true, __ATOMIC_RELEASE);
  const uint32_t timing_boot_wait_started_ms = millis();
  while (!__atomic_load_n(&dual_core_timing_boot_complete,
                          __ATOMIC_ACQUIRE) &&
         (uint32_t)(millis() - timing_boot_wait_started_ms) <
             kDualCoreBootHandshakeTimeoutMs) {
#if OTIS_ENABLE_GNSS_RECEIVER
    // The receiver is already live at this point; drain its small UART FIFO
    // while Core 1 completes boot so startup cannot manufacture a truncated
    // NMEA frame or a false receiver-identity outage.
    otis_gnss_receiver_service(millis());
#endif
    if (otis_transport_ready()) {
      dual_core_serial_carrier_seen = true;
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
#else
  boot_phase_capability_audit();
  boot_phase_run_mode();
#endif
}

#if OTIS_ENABLE_DUAL_CORE_PARTITION
void setup1() {
  otis_memory_budget_note_current_core();
  otis_status_emit_init_with_sink(&dual_core_timing_status_context, nullptr,
                                  publish_dual_core_timing_status_sink);
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  otis_setup_authority_guard_init(&dual_core_timing_setup_guard);
#endif
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
  const uint32_t now_ms = millis();
  if (otis_transport_ready()) dual_core_serial_carrier_seen = true;
  if (!dual_core_serial_carrier_seen) {
    discard_dual_core_outputs_before_first_carrier();
    otis_transport_liveness_reset(&dual_core_transport_liveness, now_ms,
                                  otis_transport_written_bytes());
    otis_gnss_receiver_service(now_ms);
    otis_status_led_poll(now_ms);
    return;
  }
  // Progress instrumentation is deliberately bounded to four complete trace
  // samples per second.  The empty service-queue poll carries no diagnostic
  // atomic accounting, so the protected timing core's hot path stays lean.
  const bool trace_timing_loop = dual_core_timing_trace_due(now_ms);
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::LoopEnter,
                                        otis_capture_ticks_now());
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::ServiceInput,
                                        otis_capture_ticks_now());
  service_dual_core_timing_inputs();
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::PpsObserver,
                                        otis_capture_ticks_now());
  otis_pps_dual_observer_service();
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(
        OtisTimingProgressPhase::CaptureBackend, otis_capture_ticks_now());
  otis_capture_backend_service();
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::BoundaryDrain,
                                        otis_capture_ticks_now());
  drain_pps_count_boundary_ring();
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::CaptureDrain,
                                        otis_capture_ticks_now());
  drain_capture_ring();
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::GateService,
                                        otis_capture_ticks_now());
  service_tcxo_gate();
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
  service_cx317_active_health();
  service_cx317_active_application_outcome();
#endif
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::TimingHealth,
                                        otis_capture_ticks_now());
  publish_dual_core_timing_health(now_ms);
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::LoopIdle,
                                        otis_capture_ticks_now());
}
#endif

void loop() {
  otis_memory_budget_note_current_core();
  if (runtime_state.boot.safe_mode_active) {
    emit_boot_records_if_serial_ready();
    otis_status_led_poll(millis());
    return;
  }

#if OTIS_ENABLE_DUAL_CORE_PARTITION
  // The USB byte stream has one chunked-frame owner. A producer keeps
  // ownership through its complete frame, but ownership no longer suppresses
  // input-only command collection indefinitely. Total pending-frame time is
  // bounded by the carrier contract; timeout quarantines the partial stream,
  // inhibits actuation, and drains internal queues as explicitly lost until a
  // reset starts a new evidence session.
  const uint32_t now_ms = millis();
  otis_gnss_receiver_service(now_ms);
  bool frame_active = dual_core_transport_liveness.state ==
                      OtisTransportLivenessState::FrameObstructed;
  bool transport_live = otis_transport_liveness_observe(
      &dual_core_transport_liveness, now_ms, frame_active,
      otis_transport_written_bytes());
  // Once a frame is pending, enforce its total horizon before attempting any
  // further write. This prevents a final byte at the deadline from hiding a
  // carrier violation and prevents all writes after Faulted is latched.
  if (transport_live) {
    frame_active = service_dual_core_serial_frame_transport();
    transport_live = otis_transport_liveness_observe(
        &dual_core_transport_liveness, now_ms, frame_active,
        otis_transport_written_bytes());
  }
  if (!transport_live) {
    otis_dual_core_latch_fault(OtisPartitionFault::TransportObstructed);
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE
    if (!dual_core_transport_abort_queued) {
      dual_core_transport_abort_queued = queue_dual_core_active_control(
          OtisRunControlKind::Abort);
    }
#endif
    service_serial_commands(false);
    discard_dual_core_outputs_after_transport_fault();
    publish_dual_core_service_metadata(now_ms);
    otis_status_led_poll(now_ms);
    return;
  }
  if (frame_active) {
    // RX and explicit abort remain bounded even while no other writer may
    // interleave bytes with the active frame.
    service_serial_commands(false);
    otis_status_led_poll(now_ms);
    return;
  }
  service_dual_core_outputs();
  emit_protocol_banner_if_serial_ready();
  emit_run_mode_status_if_ready();
  emit_resource_ownership_status();
  service_serial_commands();
  service_environment_sensors();
  publish_dual_core_service_metadata(millis());
  emit_periodic_status();
  otis_status_led_poll(millis());
  return;
#endif

  // Capture service always runs first. While a queued EST/CTL pair is being
  // transmitted in bounded chunks, no other record producer may interleave
  // bytes into that CSV frame; IRQ/PIO capture continues into its own ring.
  otis_pps_dual_observer_service();
  otis_capture_backend_service();
  if (otis_cx317_active_live_transport_busy()) {
    otis_cx317_active_live_service_transport();
    otis_gnss_receiver_service(millis());
    otis_cx317_active_live_service(millis() / 1000u);
    otis_status_led_poll(millis());
    return;
  }
  if (otis_observe_only_discipline_live_transport_busy() ||
      otis_cx317_preview_live_transport_busy()) {
    otis_observe_only_discipline_live_service_transport();
    otis_cx317_preview_live_service_transport();
    otis_gnss_receiver_service(millis());
    otis_cx317_active_live_service(millis() / 1000u);
    otis_status_led_poll(millis());
    return;
  }

  emit_protocol_banner_if_serial_ready();
  emit_run_mode_status_if_ready();
  emit_resource_ownership_status();
  otis_pseudo_pps_service();
  drain_pps_count_boundary_ring();
  drain_capture_ring();
  otis_gnss_receiver_service(millis());
  service_tcxo_gate();
  service_cx317_active_health();
  service_serial_commands();
  service_cx317_active_application_outcome();
  service_loopback_output();
#if OTIS_ENABLE_H1_DAC_SWEEP && \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  service_h1_dac_sweep();
#endif
  OtisDacAd5693rStatus phase4_dac_status;
  otis_dac_ad5693r_get_status(&phase4_dac_status);
  OtisObserveOnlyDisciplineLiveDacState phase4_dac = {
      phase4_dac_status.applied_code_known &&
          phase4_dac_status.last_write_ok &&
          phase4_dac_status.last_requested_code ==
              phase4_dac_status.last_applied_code,
      phase4_dac_status.last_applied_code,
  };
  otis_observe_only_discipline_live_poll(otis_capture_ticks_now(), &runtime_state,
                                   &phase4_dac);
  service_environment_sensors();
  emit_periodic_status();
  otis_observe_only_discipline_live_service_transport();
  if (otis_cx317_active_live_transport_busy())
    otis_cx317_active_live_service_transport();
  else
    otis_cx317_preview_live_service_transport();
  otis_status_led_poll(millis());
}
