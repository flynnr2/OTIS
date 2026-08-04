#ifndef OTIS_DUAL_CORE_CONTRACT_H
#define OTIS_DUAL_CORE_CONTRACT_H

#include <stdint.h>

// Every cross-core contract is a bounded, pointer-free value.  Character
// fields are fixed arrays rather than borrowed strings so the receiving core
// cannot observe later mutation by the publishing core.

enum class OtisServiceMessageKind : uint8_t {
  ReceiverQualification,
  Environment,
  AppliedDacState,
  RunControl,
};

enum class OtisRunControlKind : uint8_t {
  None,
  Mode,
  Arm,
  Recover,
  Abort,
  SyntheticReceiverInvalidation,
};

struct OtisReceiverQualificationMessage {
  uint32_t sequence;
  uint64_t published_ticks;
  uint32_t metadata_age_ms;
  uint16_t satellites;
  uint16_t hdop_centihundredths;
  uint8_t fix_quality;
  uint8_t fix_type;
  bool control_eligible;
  bool identity_stable;
  bool gsa_checksum_requalified;
  bool gsa_3d;
};

struct OtisEnvironmentMessage {
  uint32_t sequence;
  uint64_t timestamp_ticks;
  float temperature_c;
  float relative_humidity_pct;
  float pressure_pa;
  bool temperature_valid;
  bool humidity_valid;
  bool pressure_valid;
};

struct OtisAppliedDacStateMessage {
  uint32_t sequence;
  uint64_t published_ticks;
  uint16_t requested_code;
  uint16_t applied_code;
  bool initialized;
  bool i2c_ok;
  bool requested_applied_match;
};

struct OtisRunControlMessage {
  uint32_t sequence;
  uint64_t published_ticks;
  uint32_t authorization_sequence;
  uint32_t nonce;
  uint32_t duration_ms;
  OtisRunControlKind kind;
  bool asserted;
};

struct OtisServiceMessage {
  OtisServiceMessageKind kind;
  OtisReceiverQualificationMessage receiver;
  OtisEnvironmentMessage environment;
  OtisAppliedDacStateMessage dac;
  OtisRunControlMessage run_control;
};

enum class OtisObservationMessageKind : uint8_t {
  RawEdge,
  PpsSnapshot,
  CountObservation,
};

struct OtisRawEdgeMessage {
  uint32_t sequence;
  uint64_t timestamp_ticks;
  uint32_t flags;
  uint8_t channel_id;
  char edge;
  bool reference_record;
};

struct OtisPpsSnapshotMessage {
  uint32_t session;
  uint32_t sequence;
  uint32_t cumulative_down_counter;
  uint32_t reference_sequence;
  uint64_t reference_timestamp_ticks;
  uint32_t status;
};

struct OtisCountObservationMessage {
  uint32_t sequence;
  uint64_t gate_open_ticks;
  uint64_t gate_close_ticks;
  uint64_t counted_edges;
  uint32_t flags;
  uint8_t channel_id;
  char source_domain[32];
};

struct OtisObservationMessage {
  OtisObservationMessageKind kind;
  OtisRawEdgeMessage raw_edge;
  OtisPpsSnapshotMessage snapshot;
  OtisCountObservationMessage count;
};

enum class OtisCriticalMessageKind : uint8_t {
  ActuatorRequest,
  ActuatorAccepted,
  ActuatorRejected,
  ActuatorApplied,
  Fault,
  StateTransition,
};

struct OtisCrossCoreActuatorRequest {
  uint32_t request_sequence;
  uint32_t decision_sequence;
  uint32_t source_first_sequence;
  uint32_t source_last_sequence;
  uint64_t decision_reference_ticks;
  uint64_t deadline_ticks;
  uint32_t authorization_sequence;
  uint32_t nonce;
  uint16_t current_applied_code;
  uint16_t requested_code;
  bool actionable;
};

enum class OtisActuatorAckKind : uint8_t {
  Accepted,
  Rejected,
  Applied,
};

struct OtisCrossCoreActuatorAck {
  uint32_t request_sequence;
  uint32_t decision_sequence;
  uint32_t authorization_sequence;
  uint32_t nonce;
  uint64_t acknowledgement_ticks;
  uint16_t requested_code;
  uint16_t accepted_code;
  uint16_t applied_code;
  OtisActuatorAckKind kind;
  bool i2c_ok;
  bool clamped;
  bool ambiguous;
};

struct OtisCriticalRecordMessage {
  OtisCriticalMessageKind kind;
  uint32_t sequence;
  uint64_t timestamp_ticks;
  uint32_t flags;
  char component[24];
  char reason[64];
  OtisCrossCoreActuatorRequest request;
  OtisCrossCoreActuatorAck acknowledgement;
};

struct OtisTelemetryMessage {
  uint32_t sequence;
  uint64_t timestamp_ticks;
  uint32_t flags;
  char component[24];
  char key[32];
  char value[96];
  char severity[12];
};

enum class OtisActuatorGuardState : uint8_t {
  Idle,
  AwaitingAcceptance,
  AwaitingApplication,
  Applied,
  Fault,
};

struct OtisActuatorTransactionGuard {
  OtisActuatorGuardState state;
  OtisCrossCoreActuatorRequest pending;
  uint32_t last_request_sequence;
  uint32_t last_authorization_sequence;
  uint32_t rejected_acknowledgements;
  const char *reason;
};

void otis_actuator_guard_init(OtisActuatorTransactionGuard *guard);
bool otis_actuator_guard_start(OtisActuatorTransactionGuard *guard,
                               const OtisCrossCoreActuatorRequest *request,
                               uint64_t now_ticks);
bool otis_actuator_guard_acknowledge(
    OtisActuatorTransactionGuard *guard,
    const OtisCrossCoreActuatorAck *acknowledgement);
bool otis_actuator_guard_check_deadline(OtisActuatorTransactionGuard *guard,
                                        uint64_t now_ticks);

#endif
