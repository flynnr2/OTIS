#ifndef OTIS_INSTRUMENT_H
#define OTIS_INSTRUMENT_H

#include "otis_adaptive_hybrid_regulation.h"
#include "otis_regulation_transaction.h"

// One firmware owner. All times are extended RP2040 timer microseconds.
// No serial, host lease, allocator, callback, or device I/O occurs here.
enum class OtisInstrumentMode : uint8_t { Auto, Hold, Fixed, Characterize };
enum class OtisInstrumentWriteKind : uint8_t { Startup, Correction, Fixed, Characterize };
enum class OtisInstrumentWriteState : uint8_t { Idle, Proposed, Released, Consumers };
enum class OtisInstrumentRejection : uint8_t {
  None, QualificationLost, IdentityInvalid, DeadlineExpired, PlatformFault, DeviceUnavailable
};
enum class OtisInstrumentReceipt : uint8_t { Rejected, Accepted, Duplicate };

constexpr uint64_t OTIS_INSTRUMENT_WRITE_TIMEOUT_US = 2000000ull;
constexpr uint64_t OTIS_INSTRUMENT_MAX_DWELL_US = 86400000000ull;

struct OtisInstrumentCommand {
  uint64_t session;
  uint32_t sequence;
  OtisInstrumentMode mode;
  uint16_t code;       // zero except FIXED / CHARACTERIZE
  uint32_t dwell_s;    // CHARACTERIZE dwell; AUTO optional duration; then HOLD
};
struct OtisInstrumentWrite {
  uint64_t session;
  uint32_t capture_session;
  uint32_t sequence;
  uint32_t dac_epoch;
  uint16_t prior_code;
  uint16_t code;
  bool prior_known;
  OtisInstrumentWriteKind kind;
  uint64_t deadline_ticks;
};
struct OtisInstrumentApplication {
  OtisInstrumentWrite request;
  uint64_t ticks;
  uint16_t code;
  bool attempted;
  bool ok;
  OtisInstrumentRejection rejection = OtisInstrumentRejection::None;
};
struct OtisInstrumentHealth {
  uint32_t capture_session;
  uint32_t acceptance_epoch;
  uint32_t accepted_boundary;
  uint32_t metadata_sequence;
  bool capture_integrity;
  bool reference_qualified;
  bool metadata_qualified;
};
struct OtisInstrument {
  uint64_t session;
  uint32_t capture_session;
  OtisInstrumentMode mode;
  OtisInstrumentMode requested_mode;
  OtisInstrumentWriteState write_state;
  OtisInstrumentWrite write;
  OtisInstrumentApplication application;
  OtisInstrumentCommand last_command;
  OtisInstrumentHealth health;
  OtisAdaptiveHybridEngine engine;
  OtisAdaptiveHybridDecision decision;
  OtisRegulationResponseClassifier response_classifier;
  OtisRegulationResponseResult response_result;
  double pre_error_hz;
  int32_t response_delta_codes;
  uint64_t response_sequence;
  uint32_t next_write_sequence;
  uint32_t dac_epoch;
  uint32_t command_completed;
  uint32_t response_epoch;
  uint32_t metadata_hold_sequence;
  uint16_t applied_code;
  uint16_t target_code;
  uint64_t now_ticks;
  uint64_t application_ticks;
  uint64_t last_decision_ticks;
  uint64_t characterize_end_ticks;
  uint64_t operating_end_ticks;
  uint64_t characterize_dwell_ticks;
  uint64_t total_applications;
  uint64_t cumulative_movement;
  bool code_known;
  bool engine_ready;
  bool response_incomplete;
  bool metadata_hold;
  bool reference_hold;
  bool counters_saturated;
  const char *fault;
  const char *reason;
};

void otis_instrument_init(OtisInstrument *, uint64_t session, uint32_t capture_session, uint64_t ticks);
void otis_instrument_health(OtisInstrument *, const OtisInstrumentHealth &, uint64_t ticks);
void otis_instrument_service(OtisInstrument *, uint64_t ticks);
OtisInstrumentReceipt otis_instrument_command(OtisInstrument *, const OtisInstrumentCommand &, uint64_t ticks);
// Marks the point after which a mode change cannot retract a physical operation.
bool otis_instrument_release(OtisInstrument *, OtisInstrumentWrite *, uint64_t ticks);
bool otis_instrument_application(OtisInstrument *, const OtisInstrumentApplication &);
bool otis_instrument_confirm_consumers(OtisInstrument *, uint16_t code, uint32_t epoch, uint64_t ticks);
bool otis_instrument_decide(OtisInstrument *, const OtisAdaptiveHybridObservation &, OtisAdaptiveHybridDecision *, double frequency_error_hz);
void otis_instrument_fault(OtisInstrument *, const char *reason);
const char *otis_instrument_mode_name(OtisInstrumentMode);
const char *otis_instrument_state_name(const OtisInstrument *);
#endif
