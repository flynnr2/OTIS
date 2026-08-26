#ifndef OTIS_GNSS_RECEIVER_H
#define OTIS_GNSS_RECEIVER_H

#include <stddef.h>
#include <stdint.h>

constexpr size_t kOtisGnssMaximumLineBytes = 96u;
constexpr size_t kOtisGnssDiscoveryMaximumLineBytes = 256u;
constexpr size_t kOtisGnssReleaseMaximumBytes = 40u;
constexpr size_t kOtisGnssOutputSignatureMaximumBytes = 32u;
constexpr size_t kOtisGnssLinkPhaseMaximumBytes = 40u;
constexpr size_t kOtisGnssConfirmationMethodMaximumBytes = 40u;

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
};

enum class OtisGnssOutputConfirmationMethod : uint8_t {
  None = 0u,
  Pmtk514Exact = 1u,
  Pmtk314AckObservedExact = 2u,
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
  OtisGnssLinkState state;
  OtisGnssLinkActionKind pending_action;
  OtisGnssOutputConfirmationMethod output_confirmation_method;
  OtisGnssLinkPolicy policy;
  uint8_t candidate_index;
  uint32_t candidate_baud;
  uint32_t confirmed_baud;
  uint32_t last_identity_response_baud;
  uint32_t pending_baud;
  uint32_t state_started_ms;
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

void otis_gnss_receiver_reset(OtisGnssReceiver *receiver, uint32_t now_ms);
void otis_gnss_receiver_feed(OtisGnssReceiver *receiver, char byte,
                             uint32_t now_ms);
void otis_gnss_receiver_note_time(OtisGnssReceiver *receiver, uint32_t now_ms,
                                  uint32_t reconnect_gap_ms);
void otis_gnss_receiver_snapshot(const OtisGnssReceiver *receiver,
                                 uint32_t now_ms, uint32_t maximum_age_ms,
                                 OtisGnssReceiverSnapshot *snapshot);

#if !defined(OTIS_GNSS_HOST_TEST)
bool otis_gnss_receiver_begin(void);
void otis_gnss_receiver_service(uint32_t now_ms);
void otis_gnss_receiver_get_snapshot(uint32_t now_ms,
                                     OtisGnssReceiverSnapshot *snapshot);
#endif

#endif
