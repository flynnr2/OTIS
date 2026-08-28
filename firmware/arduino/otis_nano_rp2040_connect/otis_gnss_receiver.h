#ifndef OTIS_GNSS_RECEIVER_H
#define OTIS_GNSS_RECEIVER_H

#include <stddef.h>
#include <stdint.h>

#include "otis_gnss_uart_rx.h"

constexpr size_t kOtisGnssMaximumLineBytes = 96u;
constexpr size_t kOtisGnssDiscoveryMaximumLineBytes = 256u;
constexpr size_t kOtisGnssReleaseMaximumBytes = 40u;
constexpr size_t kOtisGnssOutputSignatureMaximumBytes = 32u;
constexpr size_t kOtisGnssLinkPhaseMaximumBytes = 40u;
constexpr size_t kOtisGnssConfirmationMethodMaximumBytes = 40u;
constexpr size_t kOtisGnssSegmentIdMaximumBytes = 5u;
constexpr char kOtisGnssBaudCharacterizationProgrammeId[] =
    "OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1";

enum class OtisGnssObservationPhase : uint8_t {
  Discovery = 0u,
  PlannedTransition = 1u,
  Recovery = 2u,
  OrdinaryOnline = 3u,
  PeakLoad = 4u,
};

enum class OtisGnssParserFaultClass : uint8_t {
  None = 0u,
  RawAcquisitionLoss = 1u,
  DelimiterBeforeNewline = 2u,
  LineShape = 3u,
  Checksum = 4u,
  FieldShape = 5u,
  Oversize = 6u,
};

struct OtisGnssParserFaultContext {
  uint8_t segment_ordinal;
  OtisGnssObservationPhase observation_phase;
  uint32_t baud;
  uint32_t baud_epoch;
  uint32_t hardware_overrun_delta;
  uint32_t hardware_framing_delta;
  uint32_t hardware_parity_delta;
  uint32_t hardware_break_delta;
  uint32_t raw_ring_depth;
  uint32_t raw_ring_high_water;
  uint32_t preceding_consumer_gap_ticks;
};

struct OtisGnssParserFaultCapsule {
  bool valid;
  uint8_t segment_ordinal;
  OtisGnssObservationPhase observation_phase;
  OtisGnssParserFaultClass fault_class;
  uint16_t partial_line_length;
  uint32_t baud;
  uint32_t baud_epoch;
  uint32_t hardware_overrun_delta;
  uint32_t hardware_framing_delta;
  uint32_t hardware_parity_delta;
  uint32_t hardware_break_delta;
  uint32_t raw_ring_depth;
  uint32_t raw_ring_high_water;
  uint32_t preceding_consumer_gap_ticks;
  uint32_t last_good_frame_sequence;
  char sentence_type[4];
};

enum class OtisGnssTransitionState : uint8_t {
  Idle = 0u,
  Targeting = 1u,
  AwaitFreshMetadata = 2u,
  Complete = 3u,
  RecoveryScanning = 4u,
  Recovered = 5u,
  Unrecoverable = 6u,
  PlatformFault = 7u,
};

enum class OtisGnssRequestDisposition : uint8_t {
  Accepted = 0u,
  Duplicate = 1u,
  RejectedDisabled = 2u,
  RejectedParse = 3u,
  RejectedIdentity = 4u,
  RejectedBusy = 5u,
  RejectedStale = 6u,
  RejectedSkipped = 7u,
  RejectedContradictory = 8u,
  RejectedSource = 9u,
  RejectedTarget = 10u,
  RejectedPhase = 11u,
};

struct OtisGnssBaudTransitionRequest {
  uint32_t request_sequence;
  uint8_t segment_ordinal;
  uint32_t source_baud;
  uint32_t source_baud_epoch;
  uint32_t target_baud;
};

struct OtisGnssStatusChallengeRequest {
  uint32_t challenge_sequence;
  uint8_t segment_ordinal;
  uint32_t baud_epoch;
};

// A completed peak remains available until the first accepted request for the
// immediately following challenge. Repeated delivery of the completed
// challenge is therefore a read-only retry and cannot erase or overwrite the
// decision-bearing peak evidence.
struct OtisGnssCompletedPeakRetention {
  bool available;
  uint32_t challenge_sequence;
};

enum class OtisGnssLinkState : uint8_t {
  SelectCandidateBaud = 0u,
  PassiveListen = 1u,
  TransmitIdentityQuery = 2u,
  AwaitIdentityResponse = 3u,
  TransmitTargetBaud = 4u,
  SelectTargetBaud = 5u,
  TransmitTargetIdentityQuery = 6u,
  AwaitTargetIdentityResponse = 7u,
  TransmitOutputQuery = 8u,
  AwaitOutputResponse = 9u,
  TransmitOutputConfiguration = 10u,
  AwaitOutputConfigurationAck = 11u,
  TransmitOutputVerificationQuery = 12u,
  AwaitOutputVerificationResponse = 13u,
  Online = 14u,
  ObserveConfiguredOutput = 15u,
  AwaitTargetBaudEpochBoundary = 16u,
};

enum class OtisGnssOutputConfirmationMethod : uint8_t {
  None = 0u,
  Pmtk514Exact = 1u,
  Pmtk314AckObservedExact = 2u,
  RetainedBaudNmeaObservedExact = 3u,
};

enum class OtisGnssStartupHintIdentityOutcome : uint8_t {
  NotAttempted = 0u,
  Pending = 1u,
  Confirmed = 2u,
  TimedOut = 3u,
  TransmitFailed = 4u,
};

enum class OtisGnssInitialDiscoveryOutcome : uint8_t {
  Pending = 0u,
  HintConfirmed = 1u,
  FallbackConfirmed = 2u,
};

enum class OtisGnssLinkActionKind : uint8_t {
  None = 0u,
  SetUartBaud = 1u,
  TransmitIdentityQuery = 2u,
  TransmitTargetBaud = 3u,
  TransmitOutputQuery = 4u,
  TransmitOutputConfiguration = 5u,
};

struct OtisGnssLinkPolicy {
  uint32_t target_baud;
  uint32_t passive_dwell_ms;
  uint32_t response_timeout_ms;
  uint32_t degraded_after_ms;
  uint32_t link_loss_ms;
  uint32_t output_observation_ms;
};

struct OtisGnssLinkAction {
  OtisGnssLinkActionKind kind;
  uint32_t baud;
  const char *bytes;
  size_t length;
};

struct OtisGnssLink {
  char line[kOtisGnssDiscoveryMaximumLineBytes];
  char receiver_release[kOtisGnssReleaseMaximumBytes];
  uint16_t line_length;
  bool collecting;
  bool discarding_oversize;
  bool service_initialized;
  bool action_pending;
  bool action_in_progress;
  bool valid_frame_seen;
  bool receiver_identity_available;
  bool configuration_confirmed;
  bool output_configuration_command_acknowledged;
  bool characterization_targeting;
  bool characterization_target_failed;
  bool characterization_recovery_scan;
  bool characterization_recovery_scan_exhausted;
  bool startup_hint_active;
  bool startup_hint_attachment_active;
  bool nmea_observation_active;
  bool discovery_output_repair_active;
  bool startup_hint_attempted;
  bool startup_fallback_entered;
  OtisGnssStartupHintIdentityOutcome startup_hint_identity_outcome;
  OtisGnssInitialDiscoveryOutcome initial_discovery_outcome;
  OtisGnssLinkState state;
  OtisGnssLinkActionKind pending_action;
  OtisGnssOutputConfirmationMethod output_confirmation_method;
  OtisGnssLinkPolicy policy;
  uint8_t candidate_index;
  uint32_t candidate_baud;
  uint32_t confirmed_baud;
  uint32_t last_identity_response_baud;
  uint32_t pending_baud;
  uint32_t startup_hint_baud;
  uint32_t initial_discovery_identity_baud;
  uint32_t state_started_ms;
  uint32_t characterization_target_started_ms;
  uint32_t discovery_started_ms;
  uint32_t last_valid_frame_ms;
  uint32_t discovery_cycle;
  uint32_t checksum_valid_count;
  uint32_t checksum_failure_count;
  uint32_t oversize_count;
  uint32_t candidate_rejection_count;
  uint32_t configuration_failure_count;
  uint32_t transmit_failure_count;
  uint32_t link_loss_count;
  uint32_t raw_acquisition_loss_count;
  uint32_t identity_response_count;
  uint32_t output_response_count;
  uint32_t output_query_timeout_count;
  uint32_t output_configuration_ack_count;
  uint32_t output_observation_success_count;
  uint32_t output_observed_sentence_mask;
  uint32_t output_unexpected_sentence_mask;
  uint16_t last_command_ack_packet_type;
  uint8_t last_command_ack_flag;
  uint8_t output_configuration_field_count;
  char output_configuration_signature[kOtisGnssOutputSignatureMaximumBytes];
};

struct OtisGnssReceiver {
  char line[kOtisGnssMaximumLineBytes];
  uint8_t line_length;
  bool collecting;
  bool discarding_oversize;
  bool initialized;
  bool rx_only;
  bool disconnected;
  bool rmc_seen;
  bool gga_seen;
  bool gsa_seen;
  bool rmc_valid;
  bool rmc_utc_available;
  bool gga_utc_available;
  bool utc_available;
  bool date_available;
  uint8_t fix_quality;
  uint8_t fix_dimension;
  uint8_t satellites;
  char talker[3];
  char utc[11];
  char date[7];
  char hdop[9];
  uint32_t identity_epoch;
  uint32_t parser_fault_epoch;
  uint32_t rmc_repair_epoch;
  uint32_t gga_repair_epoch;
  uint32_t gsa_repair_epoch;
  uint32_t last_message_ms;
  uint32_t last_rmc_ms;
  uint32_t last_gga_ms;
  uint32_t last_gsa_ms;
  uint32_t checksum_valid_count;
  uint32_t checksum_failure_count;
  uint32_t parser_drop_count;
  uint32_t truncated_count;
  uint32_t oversize_count;
  uint32_t rmc_count;
  uint32_t gga_count;
  uint32_t gsa_count;
  uint32_t raw_acquisition_loss_count;
  uint32_t last_good_frame_sequence;
  uint16_t minimum_line_length;
  uint16_t maximum_line_length;
  uint32_t minimum_interframe_gap_ms;
  uint32_t maximum_interframe_gap_ms;
  uint32_t last_good_frame_ms;
  uint64_t minimum_interframe_gap_ticks;
  uint64_t maximum_interframe_gap_ticks;
  uint64_t last_good_frame_ticks;
  bool good_frame_seen;
  bool metadata_hold_active;
  uint32_t metadata_hold_count;
  uint32_t metadata_hold_started_ms;
  uint32_t metadata_hold_cumulative_ms;
  uint32_t metadata_hold_longest_ms;
  uint32_t metadata_recovery_latency_ms;
  uint64_t metadata_hold_started_ticks;
  uint64_t metadata_hold_cumulative_ticks;
  uint64_t metadata_hold_longest_ticks;
  uint64_t metadata_recovery_latency_ticks;
  OtisGnssParserFaultContext fault_context;
  OtisGnssParserFaultCapsule
      fault_capsules[kOtisGnssFaultCapsuleCapacity];
  uint8_t fault_capsule_count;
  uint32_t fault_capsule_dropped_count;
};

struct OtisGnssReceiverSnapshot {
  bool initialized;
  bool rx_only;
  bool link_online;
  bool configuration_confirmed;
  bool receiver_identity_available;
  bool discovery_degraded;
  bool disconnected;
  bool rmc_seen;
  bool gga_seen;
  bool gsa_seen;
  bool rmc_valid;
  bool utc_available;
  bool date_available;
  bool metadata_fresh;
  bool checksum_requalified;
  bool identity_stable;
  bool control_eligible;
  bool gsa_fresh;
  bool gsa_3d;
  bool gsa_checksum_requalified;
  bool startup_hint_attempted;
  bool startup_fallback_entered;
  bool pmtk605_last_peripheral_complete_ticks_available;
  uint8_t fix_quality;
  uint8_t fix_dimension;
  uint8_t satellites;
  OtisGnssLinkState link_state;
  char talker[3];
  char utc[11];
  char date[7];
  char hdop[9];
  char link_health_state[12];
  char link_phase[kOtisGnssLinkPhaseMaximumBytes];
  char output_confirmation_method
      [kOtisGnssConfirmationMethodMaximumBytes];
  char receiver_release[kOtisGnssReleaseMaximumBytes];
  char output_configuration_signature[kOtisGnssOutputSignatureMaximumBytes];
  uint32_t candidate_baud;
  uint32_t confirmed_baud;
  uint32_t last_identity_response_baud;
  uint32_t discovery_cycle;
  uint32_t link_last_valid_frame_age_ms;
  uint32_t link_checksum_valid_count;
  uint32_t link_checksum_failure_count;
  uint32_t link_oversize_count;
  uint32_t candidate_rejection_count;
  uint32_t configuration_failure_count;
  uint32_t transmit_failure_count;
  uint32_t link_loss_count;
  uint32_t identity_response_count;
  uint32_t startup_hint_baud;
  uint32_t initial_discovery_identity_baud;
  uint32_t pmtk605_peripheral_complete_count;
  uint64_t pmtk605_last_peripheral_complete_ticks;
  OtisGnssStartupHintIdentityOutcome startup_hint_identity_outcome;
  OtisGnssInitialDiscoveryOutcome initial_discovery_outcome;
  uint32_t output_response_count;
  uint32_t output_query_timeout_count;
  uint32_t output_configuration_ack_count;
  uint32_t output_observation_success_count;
  uint32_t output_observed_sentence_mask;
  uint32_t output_unexpected_sentence_mask;
  uint16_t last_command_ack_packet_type;
  uint8_t last_command_ack_flag;
  uint8_t output_configuration_field_count;
  uint32_t identity_epoch;
  uint32_t metadata_age_ms;
  uint32_t checksum_valid_count;
  uint32_t checksum_failure_count;
  uint32_t parser_drop_count;
  uint32_t truncated_count;
  uint32_t oversize_count;
  uint32_t rmc_count;
  uint32_t gga_count;
  uint32_t gsa_count;
  uint32_t link_raw_acquisition_loss_count;
  uint32_t raw_acquisition_loss_count;
  uint32_t last_good_frame_sequence;
  uint32_t minimum_line_length;
  uint32_t maximum_line_length;
  uint32_t minimum_interframe_gap_ms;
  uint32_t maximum_interframe_gap_ms;
  uint32_t metadata_hold_count;
  uint32_t metadata_hold_cumulative_ms;
  uint32_t metadata_hold_longest_ms;
  uint32_t metadata_recovery_latency_ms;
  uint64_t minimum_interframe_gap_ticks;
  uint64_t maximum_interframe_gap_ticks;
  uint64_t metadata_hold_cumulative_ticks;
  uint64_t metadata_hold_longest_ticks;
  uint64_t metadata_recovery_latency_ticks;
  uint32_t fault_capsule_count;
  uint32_t fault_capsule_dropped_count;
  OtisGnssParserFaultCapsule
      fault_capsules[kOtisGnssFaultCapsuleCapacity];
  OtisGnssParserFaultCapsule latest_fault_capsule;
  OtisGnssUartRxStats uart_rx;
  OtisGnssObservationPhase observation_phase;
  OtisGnssTransitionState transition_state;
  OtisGnssRequestDisposition last_request_disposition;
  uint8_t segment_ordinal;
  char segment_id[kOtisGnssSegmentIdMaximumBytes];
  uint32_t baud_epoch;
  uint32_t transition_request_sequence;
  uint32_t transition_source_baud;
  uint32_t transition_source_baud_epoch;
  uint32_t transition_target_baud;
  uint32_t transition_recovered_baud;
  uint32_t transition_accepted_count;
  uint32_t transition_duplicate_count;
  uint32_t transition_rejected_count;
  uint32_t transition_completed_count;
  uint32_t transition_recovered_count;
  uint32_t transition_unrecoverable_count;
  uint32_t transition_evidence_frontier;
  bool transition_target_command_transmit_complete;
  bool transition_target_identity_confirmed;
  bool transition_target_output_confirmed;
  uint32_t transition_target_command_transmit_elapsed_ms;
  uint32_t transition_target_identity_elapsed_ms;
  uint32_t transition_target_output_elapsed_ms;
  uint32_t transition_complete_elapsed_ms;
  uint32_t transition_recovery_started_elapsed_ms;
  uint32_t transition_recovery_terminal_elapsed_ms;
  bool transition_first_dependent_snapshot;
  bool transition_platform_fault;
  bool status_challenge_active;
  uint32_t status_challenge_sequence;
  uint32_t status_challenge_completed_count;
  OtisGnssRequestDisposition last_status_request_disposition;
  uint32_t last_status_request_sequence;
  uint8_t last_status_request_segment_ordinal;
  uint32_t last_status_request_baud_epoch;
  bool completed_peak_uart_available;
  uint32_t completed_peak_challenge_sequence;
  OtisGnssUartRxStats completed_peak_uart;
};

void otis_gnss_link_reset(OtisGnssLink *link,
                          const OtisGnssLinkPolicy *policy,
                          uint32_t now_ms);
void otis_gnss_link_tick(OtisGnssLink *link, uint32_t now_ms);
void otis_gnss_link_feed(OtisGnssLink *link, char byte, uint32_t now_ms);
bool otis_gnss_link_take_action(OtisGnssLink *link,
                                OtisGnssLinkAction *action);
void otis_gnss_link_complete_action(OtisGnssLink *link, bool success,
                                    uint32_t now_ms);
bool otis_gnss_link_online(const OtisGnssLink *link);
bool otis_gnss_link_runtime_rx_only(const OtisGnssLink *link);
bool otis_gnss_link_discovery_degraded(const OtisGnssLink *link,
                                       uint32_t now_ms);
const char *otis_gnss_link_state_name(const OtisGnssLink *link,
                                      uint32_t now_ms);
const char *otis_gnss_link_phase_name(const OtisGnssLink *link);
const char *otis_gnss_output_confirmation_method_name(
    const OtisGnssLink *link);
const char *otis_gnss_startup_hint_identity_outcome_name(
    OtisGnssStartupHintIdentityOutcome outcome);
const char *otis_gnss_initial_discovery_outcome_name(
    OtisGnssInitialDiscoveryOutcome outcome);

void otis_gnss_receiver_reset(OtisGnssReceiver *receiver, uint32_t now_ms);
void otis_gnss_receiver_feed(OtisGnssReceiver *receiver, char byte,
                             uint32_t now_ms);
void otis_gnss_receiver_feed_at_ticks(OtisGnssReceiver *receiver, char byte,
                                      uint32_t now_ms,
                                      uint64_t service_extended_ticks);
void otis_gnss_receiver_note_time(OtisGnssReceiver *receiver, uint32_t now_ms,
                                  uint32_t reconnect_gap_ms);
void otis_gnss_receiver_note_time_at_ticks(
    OtisGnssReceiver *receiver, uint32_t now_ms,
    uint64_t service_extended_ticks, uint32_t reconnect_gap_ms);
void otis_gnss_link_note_collector_loss(OtisGnssLink *link);
void otis_gnss_link_note_baud_epoch_boundary(OtisGnssLink *link);
void otis_gnss_receiver_note_collector_loss(
    OtisGnssReceiver *receiver, uint32_t now_ms,
    OtisGnssParserFaultClass fault_class);
void otis_gnss_receiver_note_collector_loss_at_ticks(
    OtisGnssReceiver *receiver, uint32_t now_ms,
    uint64_t service_extended_ticks,
    OtisGnssParserFaultClass fault_class);
void otis_gnss_receiver_set_fault_context(
    OtisGnssReceiver *receiver,
    const OtisGnssParserFaultContext *context);
void otis_gnss_receiver_snapshot(const OtisGnssReceiver *receiver,
                                 uint32_t now_ms, uint32_t maximum_age_ms,
                                 OtisGnssReceiverSnapshot *snapshot);

#if !defined(OTIS_GNSS_HOST_TEST)
bool otis_gnss_receiver_begin(void);
void otis_gnss_receiver_service(uint32_t now_ms);
void otis_gnss_receiver_get_snapshot(uint32_t now_ms,
                                     OtisGnssReceiverSnapshot *snapshot);
OtisGnssRequestDisposition otis_gnss_receiver_request_baud_transition(
    const char *arguments, uint32_t now_ms);
OtisGnssRequestDisposition otis_gnss_receiver_begin_status_challenge(
    const char *arguments, uint32_t now_ms);
void otis_gnss_receiver_complete_status_challenge(uint32_t now_ms);
// Called only after the coherent status end marker is physically submitted.
// It causally closes the retained peak-load window and opens ordinary-online.
void otis_gnss_receiver_finish_status_snapshot(void);
#endif

bool otis_gnss_parse_baud_transition_request(
    const char *arguments, OtisGnssBaudTransitionRequest *request);
bool otis_gnss_parse_status_challenge_request(
    const char *arguments, OtisGnssStatusChallengeRequest *request);
bool otis_gnss_completed_peak_prepare_next(
    OtisGnssCompletedPeakRetention *retention,
    uint32_t current_challenge_sequence,
    uint32_t requested_challenge_sequence);
bool otis_gnss_completed_peak_publish(
    OtisGnssCompletedPeakRetention *retention,
    uint32_t completed_challenge_sequence);
const char *otis_gnss_observation_phase_name(OtisGnssObservationPhase phase);
const char *otis_gnss_transition_state_name(OtisGnssTransitionState state);
const char *otis_gnss_request_disposition_name(
    OtisGnssRequestDisposition disposition);
const char *otis_gnss_parser_fault_class_name(
    OtisGnssParserFaultClass fault_class);

#endif
