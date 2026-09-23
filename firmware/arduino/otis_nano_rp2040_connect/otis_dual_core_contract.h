#ifndef OTIS_DUAL_CORE_CONTRACT_H
#define OTIS_DUAL_CORE_CONTRACT_H

#include <stdint.h>

#include "otis_instrument.h"

// Every cross-core contract is a bounded, pointer-free value.  Character
// fields are fixed arrays rather than borrowed strings so the receiving core
// cannot observe later mutation by the publishing core.

enum class OtisServiceMessageKind : uint8_t { ReceiverQualification, Environment, AppliedDacState, RunControl };
enum class OtisRunControlKind : uint8_t { None, Mode, StatusQuery, DiagnosticConfigQuery, DiagnosticRuntimeQuery };

struct OtisReceiverQualificationMessage {
  uint32_t sequence;
  uint32_t metadata_sequence;
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
  uint32_t nonce;
  OtisRunControlKind kind;
  OtisInstrumentCommand instrument_command;
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
  uint32_t timestamp_uncertainty_ticks;
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
  // Diagnostic coordinates only: native wrapping rp2040_monotonic_us32.
  // Precommit is sampled after the queue slot copy and before release; the
  // second coordinate is sampled after the same message has been popped.
  // Their delta bounds publication-to-consumption from above, but does not
  // locate publication within that interval. Neither is a hardware edge latch.
  uint32_t queue_precommit_ticks;
  uint32_t queue_consumed_ticks;
  // Hardware timer high word is retained only to reject long/backwards
  // residence; exported endpoints remain the native low32 coordinates.
  uint32_t queue_precommit_high;
  bool queue_clock_valid;
  bool queue_clock_ambiguous;
  // For RawEdge as well as PpsSnapshot, snapshot.session/sequence carry the
  // originating capture identity; raw_edge.sequence remains presentation ID.
};

// D6 forwarded-output evidence has a separate lossy queue. It cannot consume
// the authoritative observation queue or make its exhaustion fail D14/D8.
enum class OtisMonitorObservationKind : uint8_t {
  Snapshot,
};

struct OtisMonitorObservationMessage {
  OtisMonitorObservationKind kind;
  uint32_t session;
  uint32_t reference_session;
  uint32_t sequence;
  uint32_t cumulative_down_counter;
  uint32_t reference_sequence;
  uint64_t reference_timestamp_ticks;
  uint32_t timestamp_uncertainty_ticks;
  uint32_t status;
  uint8_t channel_id;
};

enum class OtisCriticalMessageKind : uint8_t { Fault, StateTransition };
struct OtisCriticalRecordMessage {
  OtisCriticalMessageKind kind;
  uint32_t sequence;
  uint64_t timestamp_ticks;
  uint32_t flags;
  char component[24];
  char reason[64];
};

constexpr uint16_t OTIS_EVIDENCE_FRAME_CAPACITY = 1536u;

struct OtisEvidenceFrameMessage {
  uint32_t sequence;
  uint16_t length;
  char data[OTIS_EVIDENCE_FRAME_CAPACITY];
};

// A fixed-image build identity is two full SHA-256 digests separated by a colon:
// 64 + 1 + 64 characters, plus the terminating NUL.  Keep telemetry values
// large enough to carry that identity across cores without truncation.
constexpr uint16_t OTIS_TELEMETRY_VALUE_CAPACITY = 160u;
static_assert(OTIS_TELEMETRY_VALUE_CAPACITY >= 130u,
              "telemetry value must preserve a full build identity");
// The longest current health key is boundary_sequence_duplicate_count (33
// characters).  Preserve the complete semantic identity across cores.
constexpr uint16_t OTIS_TELEMETRY_KEY_CAPACITY = 40u;
static_assert(OTIS_TELEMETRY_KEY_CAPACITY >= 34u,
              "telemetry key must not truncate declared health identities");

struct OtisTelemetryMessage {
  uint32_t sequence;
  uint64_t timestamp_ticks;
  uint32_t flags;
  char component[24];
  char key[OTIS_TELEMETRY_KEY_CAPACITY];
  char value[OTIS_TELEMETRY_VALUE_CAPACITY];
  char severity[12];
};

// Core 1 publishes one immutable numerical result per observed PPS boundary;
// Core 0 alone turns it into RPH/PHE CSV. The record deliberately carries no
// callback, pointer, authority, actuator request, or DAC-driver state.
struct OtisPhasePreviewRecordMessage {
  uint32_t phase_epoch;
  uint32_t observation_sequence;
  uint32_t capture_session;
  uint32_t acceptance_epoch;
  uint32_t accepted_boundary_ordinal;
  uint32_t opening_snapshot_sequence;
  uint32_t closing_snapshot_sequence;
  uint32_t opening_reference_sequence;
  uint32_t closing_reference_sequence;
  uint32_t dac_epoch;
  uint32_t interval_edges;
  int64_t edge_error_cycles;
  int64_t relative_phase_cycles;
  int64_t relative_phase_time_ns;
  double frequency_error_hz;
  double frequency_estimate_age_s;
  bool phase_accepted;
  bool interval_available;
  bool frequency_available;
  bool frequency_observation_event;
  char phase_qualification_state[16];
  char phase_reason[64];
};

#endif
