#include <assert.h>
#include <stdint.h>

#include <cstdio>
#include <string>

#include "otis_config.h"
#include "otis_gnss_receiver.h"

static_assert(OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS == 2000u);
static_assert(OTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT == 57600u);
static_assert(
    OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD == 1);

namespace {

const char *kValidRmc =
    "GPRMC,091626.000,A,2236.2791,N,12017.2818,E,0.32,172.25,160418,,,A";
const char *kValidGga =
    "GPGGA,091626.000,2236.2791,N,12017.2818,E,1,10,1.00,8.8,M,18.7,M,,";
const char *kValidGsa =
    "GPGSA,A,3,04,05,09,12,24,25,29,31,,,,,1.8,1.0,1.5";
const char *kExpectedOutput =
    "PMTK514,0,1,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0";

std::string sentence(const std::string &body) {
  uint8_t checksum = 0u;
  for (char byte : body) checksum ^= static_cast<uint8_t>(byte);
  char suffix[8];
  std::snprintf(suffix, sizeof(suffix), "*%02X\r\n", checksum);
  return "$" + body + suffix;
}

void feed(OtisGnssLink *link, const std::string &text, uint32_t now_ms) {
  for (char byte : text) otis_gnss_link_feed(link, byte, now_ms);
}

void feed(OtisGnssReceiver *receiver, const std::string &text,
          uint32_t now_ms) {
  for (char byte : text) otis_gnss_receiver_feed(receiver, byte, now_ms);
}

OtisGnssLinkAction take(OtisGnssLink *link,
                        OtisGnssLinkActionKind expected) {
  OtisGnssLinkAction action = {};
  assert(otis_gnss_link_take_action(link, &action));
  assert(action.kind == expected);
  return action;
}

void test_exact_request_parsing() {
  OtisGnssBaudTransitionRequest baud = {};
#if OTIS_GNSS_BAUD_CHARACTERIZATION_RESUME
  assert(otis_gnss_parse_baud_transition_request(
      "OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1 1 S01 115200 1 115200",
      &baud));
#else
  assert(otis_gnss_parse_baud_transition_request(
      "OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1 1 S01 57600 1 57600",
      &baud));
#endif
  assert(baud.request_sequence == 1u && baud.segment_ordinal == 1u);
  assert(!otis_gnss_parse_baud_transition_request(
      "OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1 1  S01 57600 1 57600",
      &baud));
  assert(!otis_gnss_parse_baud_transition_request(
      "OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1 2 S02 57600 1 19200",
      &baud));
  OtisGnssStatusChallengeRequest challenge = {};
  assert(otis_gnss_parse_status_challenge_request(
      "OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1 9 S11 12",
      &challenge));
  assert(challenge.challenge_sequence == 9u &&
         challenge.segment_ordinal == 11u && challenge.baud_epoch == 12u);
}

void test_stale_pre_marker_identity_cannot_confirm_target() {
  const OtisGnssLinkPolicy policy = {
      19200u, 10u, 100u, 1000u, 1000u, 100u,
  };
  OtisGnssLink link = {};
  link.service_initialized = true;
  link.policy = policy;
  link.state = OtisGnssLinkState::TransmitTargetBaud;
  link.configuration_confirmed = false;
  link.receiver_identity_available = true;
  link.confirmed_baud = 9600u;
  link.candidate_baud = 9600u;
  link.identity_response_count = 1u;
  link.last_identity_response_baud = 9600u;
  link.characterization_targeting = true;
  link.characterization_target_started_ms = 0u;
  link.pending_action = OtisGnssLinkActionKind::TransmitTargetBaud;
  link.action_pending = true;
  OtisGnssLinkAction action =
      take(&link, OtisGnssLinkActionKind::TransmitTargetBaud);
  assert(std::string(action.bytes, action.length) ==
         "$PMTK251,19200*22\r\n");
  otis_gnss_link_complete_action(&link, true, 2122u);
  action = take(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 19200u);
  otis_gnss_link_complete_action(&link, true, 2123u);
  assert(link.state == OtisGnssLinkState::AwaitTargetBaudEpochBoundary);

  // This complete, checksum-valid identity represents a stale old-rate ring
  // entry retained before the physical UART epoch marker. It must be ignored.
  feed(&link, sentence("PMTK705,STALE_OLD_RATE,BUILD_1"), 2124u);
  assert(link.identity_response_count == 1u);
  assert(!link.action_pending);

  otis_gnss_link_note_baud_epoch_boundary(&link);
  take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 2125u);
  assert(link.state == OtisGnssLinkState::AwaitTargetIdentityResponse);
  feed(&link, sentence("PMTK705,AXN_5.10_3339,BUILD_1"), 2126u);
  assert(link.identity_response_count == 2u);
  assert(link.last_identity_response_baud == 19200u);
}

void test_completed_peak_retained_across_retry_until_next_challenge() {
  OtisGnssCompletedPeakRetention retention = {};

  assert(otis_gnss_completed_peak_prepare_next(&retention, 0u, 1u));
  assert(otis_gnss_completed_peak_publish(&retention, 1u));
  assert(retention.available && retention.challenge_sequence == 1u);

  // Retrying challenge N does not acknowledge it and cannot clear or replace
  // the completed peak. The live command path classifies this as Duplicate
  // before calling prepare_next().
  assert(!otis_gnss_completed_peak_prepare_next(&retention, 1u, 1u));
  assert(!otis_gnss_completed_peak_publish(&retention, 1u));
  assert(retention.available && retention.challenge_sequence == 1u);

  // Only the first accepted N+1 request acknowledges N. N+1 then publishes a
  // distinct retained peak which is subject to the same rule.
  assert(otis_gnss_completed_peak_prepare_next(&retention, 1u, 2u));
  assert(!retention.available && retention.challenge_sequence == 0u);
  assert(otis_gnss_completed_peak_publish(&retention, 2u));
  assert(retention.available && retention.challenge_sequence == 2u);
  assert(!otis_gnss_completed_peak_prepare_next(&retention, 2u, 4u));
  assert(retention.available && retention.challenge_sequence == 2u);
}

void test_hint_identity_output_and_metadata_attach_online_without_pmtk251() {
  const OtisGnssLinkPolicy policy = {
      9600u,
      10u,
      OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS,
      10000u,
      1000u,
      100u,
  };
  OtisGnssLink link = {};
  uint32_t now_ms = 0u;
  otis_gnss_link_reset(&link, &policy, now_ms);
  OtisGnssLinkAction action =
      take(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 57600u);
  otis_gnss_link_complete_action(&link, true, now_ms);
  assert(link.candidate_baud == 57600u);
  const uint32_t rejection_count = link.candidate_rejection_count;
  now_ms += 10u;
  otis_gnss_link_tick(&link, now_ms);
  take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, now_ms);

  // The PA1616S may return PMTK705 on the next one-hertz receiver epoch. A
  // response later than the old 750 ms bound must remain candidate-causal.
  otis_gnss_link_tick(&link, now_ms + 751u);
  assert(link.state == OtisGnssLinkState::AwaitIdentityResponse);
  assert(link.candidate_baud == 57600u);
  assert(link.candidate_rejection_count == rejection_count);
  feed(&link, sentence("PMTK705,AXN_5.1.6_3333_18041700"), now_ms + 1000u);
  assert(link.identity_response_count == 1u);
  assert(link.last_identity_response_baud == 57600u);
  assert(link.startup_hint_identity_outcome ==
         OtisGnssStartupHintIdentityOutcome::Confirmed);
  assert(link.initial_discovery_outcome ==
         OtisGnssInitialDiscoveryOutcome::HintConfirmed);
  assert(!link.startup_fallback_entered);
  assert(link.policy.target_baud == 57600u);
  assert(link.state == OtisGnssLinkState::TransmitOutputQuery);
  action = take(&link, OtisGnssLinkActionKind::TransmitOutputQuery);
  assert(std::string(action.bytes, action.length) == "$PMTK414*33\r\n");
  otis_gnss_link_complete_action(&link, true, now_ms + 1001u);
  feed(&link, sentence(kExpectedOutput), now_ms + 1002u);
  assert(otis_gnss_link_online(&link));
  assert(otis_gnss_link_runtime_rx_only(&link));
  assert(link.confirmed_baud == 57600u);
  assert(link.transmit_failure_count == 0u);
  assert(!link.action_pending && !link.action_in_progress);

  // The retained-baud attachment is not decision-ready on identity/output
  // alone. The independent metadata consumer still requires a fresh causal
  // RMC/GGA/GSA set after the output path has opened.
  OtisGnssReceiver receiver = {};
  otis_gnss_receiver_reset(&receiver, now_ms + 1002u);
  feed(&receiver, sentence(kValidRmc), now_ms + 1003u);
  feed(&receiver, sentence(kValidGga), now_ms + 1004u);
  feed(&receiver, sentence(kValidGsa), now_ms + 1005u);
  OtisGnssReceiverSnapshot metadata = {};
  otis_gnss_receiver_snapshot(&receiver, now_ms + 1005u, 3000u, &metadata);
  assert(metadata.metadata_fresh);
  assert(metadata.checksum_requalified);
  assert(metadata.gsa_fresh);
  assert(metadata.gsa_checksum_requalified);
}

void test_retained_baud_nmea_cadence_fallback_without_pmtk_responses() {
  const OtisGnssLinkPolicy policy = {
      9600u,
      10u,
      OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS,
      10000u,
      1000u,
      2500u,
  };
  OtisGnssLink link = {};
  otis_gnss_link_reset(&link, &policy, 0u);
  OtisGnssLinkAction action =
      take(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 57600u);
  otis_gnss_link_complete_action(&link, true, 0u);
  otis_gnss_link_tick(&link, 10u);
  action = take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  assert(std::string(action.bytes, action.length) == "$PMTK605*31\r\n");
  otis_gnss_link_complete_action(&link, true, 10u);

  // PMTK705 is absent, but a complete checksum-valid required cadence proves
  // that UART decoding is coherent at the selected retained baud.
  feed(&link, sentence(kValidRmc), 1000u);
  feed(&link, sentence(kValidGga), 1001u);
  feed(&link, sentence(kValidGsa), 1002u);
  assert(link.identity_response_count == 0u);
  otis_gnss_link_tick(&link,
                      10u + OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS);
  assert(link.state == OtisGnssLinkState::ObserveConfiguredOutput);
  assert(link.identity_response_count == 1u);
  assert(link.last_identity_response_baud == 57600u);
  assert(std::string(link.receiver_release) == "NMEA_CADENCE_OBSERVED");
  assert(link.output_configuration_signature[0] == '\0');
  assert(!link.action_pending && !link.action_in_progress);

  // The discovery cadence is only the baud binding. Configuration becomes
  // authoritative after a separate full 2.5 s exact-output observation.
  feed(&link, sentence(kValidRmc), 2011u);
  feed(&link, sentence(kValidGga), 2012u);
  feed(&link, sentence(kValidGsa), 2013u);
  otis_gnss_link_tick(&link, 4509u);
  assert(!otis_gnss_link_online(&link));
  assert(link.output_configuration_signature[0] == '\0');
  otis_gnss_link_tick(&link, 4510u);
  assert(otis_gnss_link_online(&link));
  assert(otis_gnss_link_runtime_rx_only(&link));
  assert(link.confirmed_baud == 57600u);
  assert(std::string(link.output_configuration_signature) ==
         "0101100000000000000000");
  assert(link.output_confirmation_method ==
         OtisGnssOutputConfirmationMethod::
             RetainedBaudNmeaObservedExact);
  assert(std::string(otis_gnss_output_confirmation_method_name(&link)) ==
         "retained_baud_nmea_observed_exact");
}

void test_fallback_scan_candidate_uses_nmea_cadence_attachment() {
  const OtisGnssLinkPolicy policy = {
      9600u, 1u, 100u, 10000u, 1000u, 10u,
  };
  OtisGnssLink link = {};
  otis_gnss_link_reset(&link, &policy, 0u);
  take(&link, OtisGnssLinkActionKind::SetUartBaud);
  otis_gnss_link_complete_action(&link, true, 0u);
  otis_gnss_link_tick(&link, 1u);
  take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 1u);
  otis_gnss_link_tick(&link, 101u);
  take(&link, OtisGnssLinkActionKind::TransmitOutputConfiguration);
  otis_gnss_link_complete_action(&link, true, 101u);
  otis_gnss_link_tick(&link, 201u);

  OtisGnssLinkAction action =
      take(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 9600u);
  otis_gnss_link_complete_action(&link, true, 201u);
  feed(&link, sentence(kValidRmc), 202u);
  take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 202u);
  feed(&link, sentence(kValidGga), 203u);
  feed(&link, sentence(kValidGsa), 204u);
  otis_gnss_link_tick(&link, 302u);

  assert(link.state == OtisGnssLinkState::ObserveConfiguredOutput);
  assert(link.startup_fallback_entered);
  assert(link.initial_discovery_outcome ==
         OtisGnssInitialDiscoveryOutcome::FallbackConfirmed);
  assert(link.initial_discovery_identity_baud == 9600u);
  assert(link.identity_response_count == 1u);
  assert(link.last_identity_response_baud == 9600u);
  assert(std::string(link.receiver_release) == "NMEA_CADENCE_OBSERVED");
  feed(&link, sentence(kValidRmc), 303u);
  feed(&link, sentence(kValidGga), 304u);
  feed(&link, sentence(kValidGsa), 305u);
  otis_gnss_link_tick(&link, 312u);
  assert(otis_gnss_link_online(&link));
  assert(link.confirmed_baud == 9600u);
  assert(std::string(link.output_configuration_signature) ==
         "0101100000000000000000");
}

void test_target_transition_uses_nmea_cadence_identity_fallback() {
  const OtisGnssLinkPolicy policy = {
      9600u, 1u, 100u, 10000u, 1000u, 10u,
  };
  OtisGnssLink link = {};
  link.service_initialized = true;
  link.policy = policy;
  link.state = OtisGnssLinkState::Online;
  link.configuration_confirmed = true;
  link.receiver_identity_available = true;
  link.confirmed_baud = 9600u;
  link.candidate_baud = 9600u;
  link.identity_response_count = 1u;
  link.last_identity_response_baud = 9600u;
  std::snprintf(link.receiver_release, sizeof(link.receiver_release),
                "%s", "NMEA_CADENCE_OBSERVED");
  std::snprintf(link.output_configuration_signature,
                sizeof(link.output_configuration_signature), "%s",
                "0101100000000000000000");

  link.policy.target_baud = 38400u;
  link.configuration_confirmed = false;
  link.characterization_targeting = true;
  link.characterization_target_started_ms = 0u;
  link.state = OtisGnssLinkState::TransmitTargetBaud;
  link.pending_action = OtisGnssLinkActionKind::TransmitTargetBaud;
  link.action_pending = true;
  OtisGnssLinkAction action =
      take(&link, OtisGnssLinkActionKind::TransmitTargetBaud);
  assert(std::string(action.bytes, action.length) ==
         "$PMTK251,38400*27\r\n");
  otis_gnss_link_complete_action(&link, true, 0u);
  action = take(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 38400u);
  otis_gnss_link_complete_action(&link, true, 1u);
  otis_gnss_link_note_baud_epoch_boundary(&link);
  take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 2u);
  feed(&link, sentence(kValidRmc), 3u);
  feed(&link, sentence(kValidGga), 4u);
  feed(&link, sentence(kValidGsa), 5u);
  otis_gnss_link_tick(&link, 102u);

  assert(link.state == OtisGnssLinkState::ObserveConfiguredOutput);
  assert(link.identity_response_count == 2u);
  assert(link.last_identity_response_baud == 38400u);
  assert(std::string(link.receiver_release) == "NMEA_CADENCE_OBSERVED");
  assert(link.output_configuration_signature[0] == '\0');
  feed(&link, sentence(kValidRmc), 103u);
  feed(&link, sentence(kValidGga), 104u);
  feed(&link, sentence(kValidGsa), 105u);
  otis_gnss_link_tick(&link, 112u);
  assert(otis_gnss_link_online(&link));
  assert(link.confirmed_baud == 38400u);
  assert(link.identity_response_count == 2u);
  assert(std::string(link.receiver_release) == "NMEA_CADENCE_OBSERVED");
  assert(std::string(link.output_configuration_signature) ==
         "0101100000000000000000");
}

void test_startup_hint_and_fallback_order_are_bounded_and_query_causal() {
  const OtisGnssLinkPolicy policy = {
      9600u,
      10u,
      OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS,
      10000u,
      1000u,
      100u,
  };
  constexpr uint32_t expected[] = {
      57600u, 9600u, 19200u, 38400u, 57600u, 115200u,
  };
  OtisGnssLink link = {};
  uint32_t now_ms = 0u;
  otis_gnss_link_reset(&link, &policy, now_ms);
  for (size_t index = 0u; index < sizeof(expected) / sizeof(expected[0]);
       ++index) {
    const uint32_t expected_baud = expected[index];
    OtisGnssLinkAction action =
        take(&link, OtisGnssLinkActionKind::SetUartBaud);
    assert(action.baud == expected_baud);
    assert(link.candidate_baud == expected_baud);
    otis_gnss_link_complete_action(&link, true, now_ms);
    assert(link.state == OtisGnssLinkState::PassiveListen);

    // A valid frame at the hinted/current rate causally queues the fixed
    // identity query before any candidate transition can occur.
    feed(&link, sentence("GPRMC,120000.00,A,,,,,,,010126,,,A"), now_ms + 1u);
    assert(link.state == OtisGnssLinkState::TransmitIdentityQuery);
    assert(link.candidate_baud == expected_baud);
    action = take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
    assert(std::string(action.bytes, action.length) == "$PMTK605*31\r\n");
    assert(link.candidate_baud == expected_baud);
    otis_gnss_link_complete_action(&link, true, now_ms + 1u);
    assert(link.state == OtisGnssLinkState::AwaitIdentityResponse);
    assert(link.candidate_baud == expected_baud);

    now_ms += 1u + OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS;
    otis_gnss_link_tick(&link, now_ms);
    action = take(&link, OtisGnssLinkActionKind::TransmitOutputConfiguration);
    otis_gnss_link_complete_action(&link, true, now_ms);
    now_ms += OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS;
    otis_gnss_link_tick(&link, now_ms);
    if (index == 0u) {
      assert(link.startup_hint_attempted);
      assert(link.startup_hint_baud == 57600u);
      assert(link.startup_hint_identity_outcome ==
             OtisGnssStartupHintIdentityOutcome::TimedOut);
      assert(link.startup_fallback_entered);
      assert(link.initial_discovery_outcome ==
             OtisGnssInitialDiscoveryOutcome::Pending);
    }
  }
  OtisGnssLinkAction action =
      take(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 9600u);
  assert(link.discovery_cycle == 2u);
  assert(link.candidate_rejection_count == 6u);
}

void test_hint_miss_fallback_can_attach_online_at_power_cycle_default() {
  const OtisGnssLinkPolicy policy = {
      9600u,
      10u,
      OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS,
      10000u,
      1000u,
      100u,
  };
  OtisGnssLink link = {};
  otis_gnss_link_reset(&link, &policy, 0u);
  OtisGnssLinkAction action =
      take(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 57600u);
  otis_gnss_link_complete_action(&link, true, 0u);
  otis_gnss_link_tick(&link, 10u);
  action = take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  assert(std::string(action.bytes, action.length) == "$PMTK605*31\r\n");
  otis_gnss_link_complete_action(&link, true, 10u);
  otis_gnss_link_tick(&link,
                      10u + OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS);
  action = take(&link, OtisGnssLinkActionKind::TransmitOutputConfiguration);
  otis_gnss_link_complete_action(
      &link, true, 10u + OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS);
  otis_gnss_link_tick(
      &link, 10u + 2u * OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS);

  action = take(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 9600u);
  otis_gnss_link_complete_action(
      &link, true, 10u + 2u * OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS);
  feed(&link, sentence(kValidRmc),
       11u + 2u * OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS);
  action = take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  assert(std::string(action.bytes, action.length) == "$PMTK605*31\r\n");
  otis_gnss_link_complete_action(
      &link, true, 12u + 2u * OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS);
  feed(&link, sentence("PMTK705,AXN_5.10_3339,BUILD_1"),
       13u + 2u * OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS);
  action = take(&link, OtisGnssLinkActionKind::TransmitOutputQuery);
  assert(std::string(action.bytes, action.length) == "$PMTK414*33\r\n");
  otis_gnss_link_complete_action(
      &link, true, 14u + 2u * OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS);
  feed(&link, sentence(kExpectedOutput),
       15u + 2u * OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS);

  assert(otis_gnss_link_online(&link));
  assert(link.confirmed_baud == 9600u);
  assert(link.startup_fallback_entered);
  assert(link.startup_hint_identity_outcome ==
         OtisGnssStartupHintIdentityOutcome::TimedOut);
  assert(link.initial_discovery_outcome ==
         OtisGnssInitialDiscoveryOutcome::FallbackConfirmed);
  assert(link.initial_discovery_identity_baud == 9600u);
}

void test_hint_miss_fallback_retains_discovered_115200_without_pmtk251() {
  const OtisGnssLinkPolicy policy = {
      9600u,
      1u,
      10u,
      10000u,
      1000u,
      10u,
  };
  constexpr uint32_t rejected_candidates[] = {
      57600u, 9600u, 19200u, 38400u, 57600u,
  };
  OtisGnssLink link = {};
  uint32_t now_ms = 0u;
  otis_gnss_link_reset(&link, &policy, now_ms);

  for (uint32_t rejected_baud : rejected_candidates) {
    OtisGnssLinkAction action =
        take(&link, OtisGnssLinkActionKind::SetUartBaud);
    assert(action.baud == rejected_baud);
    otis_gnss_link_complete_action(&link, true, now_ms);
    now_ms++;
    otis_gnss_link_tick(&link, now_ms);
    action = take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
    assert(std::string(action.bytes, action.length) == "$PMTK605*31\r\n");
    otis_gnss_link_complete_action(&link, true, now_ms);
    now_ms += policy.response_timeout_ms;
    otis_gnss_link_tick(&link, now_ms);
    action =
        take(&link, OtisGnssLinkActionKind::TransmitOutputConfiguration);
    assert(action.kind != OtisGnssLinkActionKind::TransmitTargetBaud);
    otis_gnss_link_complete_action(&link, true, now_ms);
    now_ms += policy.response_timeout_ms;
    otis_gnss_link_tick(&link, now_ms);
  }

  OtisGnssLinkAction action =
      take(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 115200u);
  otis_gnss_link_complete_action(&link, true, now_ms);
  feed(&link, sentence(kValidRmc), ++now_ms);
  action = take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  assert(std::string(action.bytes, action.length) == "$PMTK605*31\r\n");
  otis_gnss_link_complete_action(&link, true, now_ms);
  feed(&link, sentence("PMTK705,AXN_5.10_3339,BUILD_1"), ++now_ms);

  assert(link.state == OtisGnssLinkState::TransmitOutputQuery);
  action = take(&link, OtisGnssLinkActionKind::TransmitOutputQuery);
  assert(std::string(action.bytes, action.length) == "$PMTK414*33\r\n");
  otis_gnss_link_complete_action(&link, true, ++now_ms);
  feed(&link, sentence(kExpectedOutput), ++now_ms);

  assert(otis_gnss_link_online(&link));
  assert(link.confirmed_baud == 115200u);
  assert(link.policy.target_baud == 115200u);
  assert(link.initial_discovery_outcome ==
         OtisGnssInitialDiscoveryOutcome::FallbackConfirmed);
  assert(link.initial_discovery_identity_baud == 115200u);
}

}  // namespace

int main() {
  test_exact_request_parsing();
  test_stale_pre_marker_identity_cannot_confirm_target();
  test_completed_peak_retained_across_retry_until_next_challenge();
  test_hint_identity_output_and_metadata_attach_online_without_pmtk251();
  test_retained_baud_nmea_cadence_fallback_without_pmtk_responses();
  test_fallback_scan_candidate_uses_nmea_cadence_attachment();
  test_target_transition_uses_nmea_cadence_identity_fallback();
  test_startup_hint_and_fallback_order_are_bounded_and_query_causal();
  test_hint_miss_fallback_can_attach_online_at_power_cycle_default();
  test_hint_miss_fallback_retains_discovered_115200_without_pmtk251();
  return 0;
}
