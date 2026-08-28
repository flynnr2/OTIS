#include <assert.h>
#include <stdint.h>

#include <cstdio>
#include <string>

#include "otis_gnss_receiver.h"

namespace {

std::string sentence(const std::string &body) {
  uint8_t checksum = 0u;
  for (char byte : body) checksum ^= static_cast<uint8_t>(byte);
  char suffix[8];
  std::snprintf(suffix, sizeof(suffix), "*%02X\r\n", checksum);
  return "$" + body + suffix;
}

void feed(OtisGnssReceiver *receiver, const std::string &text,
          uint32_t now_ms) {
  for (char byte : text) otis_gnss_receiver_feed(receiver, byte, now_ms);
}

OtisGnssReceiverSnapshot snapshot(const OtisGnssReceiver &receiver,
                                  uint32_t now_ms) {
  OtisGnssReceiverSnapshot value;
  otis_gnss_receiver_snapshot(&receiver, now_ms, 3000u, &value);
  return value;
}

const char *kValidRmc =
    "GPRMC,091626.000,A,2236.2791,N,12017.2818,E,0.32,172.25,160418,,,A";
const char *kValidGga =
    "GPGGA,091626.000,2236.2791,N,12017.2818,E,1,10,1.00,8.8,M,18.7,M,,";
const char *kValidGsa =
    "GPGSA,A,3,04,05,09,12,24,25,29,31,,,,,1.8,1.0,1.5";
const char *kExpectedOutput =
    "PMTK514,0,1,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0";
const char *kExpectedExtendedOutput =
    "PMTK514,0,1,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0";

OtisGnssLinkPolicy link_policy() {
  return {9600u, 1200u, 750u, 15000u, 10000u, 2500u};
}

OtisGnssLinkAction take_action(OtisGnssLink *link,
                               OtisGnssLinkActionKind expected) {
  OtisGnssLinkAction action;
  assert(otis_gnss_link_take_action(link, &action));
  assert(action.kind == expected);
  return action;
}

void feed_link(OtisGnssLink *link, const std::string &text,
               uint32_t now_ms) {
  for (char byte : text) otis_gnss_link_feed(link, byte, now_ms);
}

void retain_link_bytes(OtisGnssUartRxRing *ring, const std::string &text) {
  for (char byte : text) {
    const OtisGnssUartObservation observation = {
        static_cast<uint8_t>(byte), kOtisGnssUartObservationNone};
    assert(otis_gnss_uart_rx_ring_push_from_isr(ring, observation));
  }
}

uint32_t drain_link_bytes(OtisGnssUartRxRing *ring, OtisGnssLink *link,
                          uint32_t maximum, uint32_t now_ms) {
  uint32_t drained = 0u;
  OtisGnssUartObservation observation = {};
  while (drained < maximum &&
         otis_gnss_uart_rx_ring_pop(ring, &observation)) {
    otis_gnss_link_feed(link, static_cast<char>(observation.byte), now_ms);
    drained++;
  }
  return drained;
}

void establish_target_link(OtisGnssLink *link, uint32_t now_ms) {
  const OtisGnssLinkPolicy policy = link_policy();
  otis_gnss_link_reset(link, &policy, now_ms);
  OtisGnssLinkAction action =
      take_action(link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 9600u);
  otis_gnss_link_complete_action(link, true, now_ms);
  feed_link(link, sentence(kValidRmc), now_ms + 1u);
  action = take_action(link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  assert(std::string(action.bytes, action.length) == "$PMTK605*31\r\n");
  otis_gnss_link_complete_action(link, true, now_ms + 2u);
  feed_link(link, sentence("PMTK705,AXN_5.10_3339,BUILD_1"), now_ms + 3u);
  action = take_action(link, OtisGnssLinkActionKind::TransmitOutputQuery);
  assert(std::string(action.bytes, action.length) == "$PMTK414*33\r\n");
  otis_gnss_link_complete_action(link, true, now_ms + 4u);
  feed_link(link, sentence(kExpectedOutput), now_ms + 5u);
  assert(otis_gnss_link_online(link));
  assert(otis_gnss_link_runtime_rx_only(link));
}

void test_valid_and_message_order_variation() {
  OtisGnssReceiver receiver;
  otis_gnss_receiver_reset(&receiver, 0u);
  feed(&receiver, sentence(kValidGga), 100u);
  assert(!snapshot(receiver, 100u).control_eligible);
  feed(&receiver, sentence(kValidRmc), 200u);
  const OtisGnssReceiverSnapshot value = snapshot(receiver, 200u);
  assert(value.control_eligible);
  assert(value.metadata_fresh);
  assert(value.checksum_requalified);
  assert(value.identity_stable);
  assert(value.rmc_valid && value.fix_quality == 1u);
  assert(value.satellites == 10u);
  assert(std::string(value.hdop) == "1.00");
  assert(std::string(value.utc) == "091626.000");
  assert(std::string(value.date) == "160418");
  assert(std::string(value.talker) == "GP");
}

void test_checksum_failure_requires_a_fresh_pair() {
  OtisGnssReceiver receiver;
  otis_gnss_receiver_reset(&receiver, 0u);
  feed(&receiver, sentence(kValidRmc), 100u);
  feed(&receiver, sentence(kValidGga), 100u);
  assert(snapshot(receiver, 100u).control_eligible);
  feed(&receiver,
       "$GPRMC,091627.000,A,2236.2791,N,12017.2818,E,0,0,160418,,,A*00\r\n",
       200u);
  OtisGnssReceiverSnapshot value = snapshot(receiver, 200u);
  assert(value.checksum_failure_count == 1u);
  assert(!value.checksum_requalified && !value.control_eligible);
  feed(&receiver, sentence(kValidRmc), 300u);
  assert(!snapshot(receiver, 300u).control_eligible);
  feed(&receiver, sentence(kValidGga), 400u);
  assert(snapshot(receiver, 400u).control_eligible);
}

void test_truncated_and_oversize_input() {
  OtisGnssReceiver receiver;
  otis_gnss_receiver_reset(&receiver, 0u);
  feed(&receiver, "$GPRMC,123\r\n", 100u);
  feed(&receiver, "$GPRMC,123$GPGGA,456\r\n", 200u);
  std::string oversize = "$" + std::string(120u, 'X') + "\r\n";
  feed(&receiver, oversize, 300u);
  const OtisGnssReceiverSnapshot value = snapshot(receiver, 300u);
  assert(value.truncated_count >= 3u);
  assert(value.oversize_count == 1u);
  assert(value.parser_drop_count >= 4u);
  assert(!value.control_eligible);
}

void test_stale_and_short_fix_loss_return() {
  OtisGnssReceiver receiver;
  otis_gnss_receiver_reset(&receiver, 0u);
  feed(&receiver, sentence(kValidRmc), 100u);
  feed(&receiver, sentence(kValidGga), 100u);
  assert(snapshot(receiver, 3100u).control_eligible);
  assert(!snapshot(receiver, 3101u).control_eligible);

  feed(&receiver,
       sentence("GPRMC,091627.000,V,,,,,,,160418,,,N"), 4000u);
  feed(&receiver,
       sentence("GPGGA,091627.000,,,,,0,00,9.99,,,,,,"), 4000u);
  assert(!snapshot(receiver, 4000u).control_eligible);
  feed(&receiver, sentence(kValidRmc), 5000u);
  feed(&receiver, sentence(kValidGga), 5000u);
  assert(snapshot(receiver, 5000u).control_eligible);
  assert(snapshot(receiver, 5000u).identity_epoch == 1u);
}

void test_invalid_utc_and_reconnect_identity_epoch() {
  OtisGnssReceiver receiver;
  otis_gnss_receiver_reset(&receiver, 0u);
  feed(&receiver,
       sentence("GNRMC,,A,2236.2791,N,12017.2818,E,0,0,160418,,,A"), 100u);
  feed(&receiver, sentence(kValidGga), 100u);
  assert(!snapshot(receiver, 100u).control_eligible);

  feed(&receiver, sentence(kValidRmc), 200u);
  feed(&receiver, sentence(kValidGga), 200u);
  assert(snapshot(receiver, 200u).control_eligible);
  otis_gnss_receiver_note_time(&receiver, 10200u, 10000u);
  assert(snapshot(receiver, 10200u).disconnected);
  feed(&receiver, sentence(kValidGga), 10300u);
  feed(&receiver, sentence(kValidRmc), 10400u);
  const OtisGnssReceiverSnapshot value = snapshot(receiver, 10400u);
  assert(value.identity_epoch == 2u);
  assert(!value.identity_stable);
  assert(!value.control_eligible);
}

void test_gsa_dimension_is_separate_and_fresh_for_active_authority() {
  OtisGnssReceiver receiver;
  otis_gnss_receiver_reset(&receiver, 0u);
  feed(&receiver, sentence(kValidRmc), 100u);
  feed(&receiver, sentence(kValidGga), 100u);
  OtisGnssReceiverSnapshot value = snapshot(receiver, 100u);
  assert(value.control_eligible);
  assert(!value.gsa_seen && !value.gsa_3d);

  feed(&receiver, sentence(kValidGsa), 200u);
  value = snapshot(receiver, 200u);
  assert(value.gsa_seen && value.gsa_fresh && value.gsa_3d);
  assert(value.fix_dimension == 3u);
  assert(value.fix_quality == 1u);
  assert(value.gsa_checksum_requalified);
  assert(value.gsa_count == 1u);

  feed(&receiver, sentence("GPGSA,A,2,,,,,,,,,,,,,9.9,9.9,9.9"), 400u);
  value = snapshot(receiver, 400u);
  assert(value.gsa_fresh && !value.gsa_3d && value.fix_dimension == 2u);
  assert(value.control_eligible);
  assert(!snapshot(receiver, 3401u).gsa_fresh);
}

void test_passive_target_discovery_and_exact_configuration() {
  OtisGnssLink link;
  establish_target_link(&link, 100u);
  assert(link.confirmed_baud == 9600u);
  assert(link.configuration_confirmed);
  assert(link.receiver_identity_available);
  assert(std::string(link.receiver_release) == "AXN_5.10_3339");
  assert(link.identity_response_count == 1u);
  assert(link.output_response_count == 1u);
  assert(std::string(otis_gnss_link_state_name(&link, 200u)) == "online");
}

void test_unknown_baud_transition_and_output_reconfiguration() {
  OtisGnssLink link;
  const OtisGnssLinkPolicy policy = link_policy();
  otis_gnss_link_reset(&link, &policy, 0u);
  OtisGnssLinkAction action =
      take_action(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 9600u);
  otis_gnss_link_complete_action(&link, true, 0u);

  otis_gnss_link_tick(&link, 1200u);
  action = take_action(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 1200u);
  otis_gnss_link_tick(&link, 1950u);
  action = take_action(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 115200u);
  otis_gnss_link_complete_action(&link, true, 1950u);

  feed_link(&link, sentence("PMTK010,001"), 2000u);
  action = take_action(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 2001u);
  feed_link(&link, sentence("PMTK705,AXN_5.10_3339,BUILD_1"), 2002u);
  action = take_action(&link, OtisGnssLinkActionKind::TransmitTargetBaud);
  assert(std::string(action.bytes, action.length) ==
         "$PMTK251,9600*17\r\n");
  otis_gnss_link_complete_action(&link, true, 2003u);
  action = take_action(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 9600u);
  otis_gnss_link_complete_action(&link, true, 2004u);
  action = take_action(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 2005u);
  feed_link(&link, sentence("PMTK705,AXN_5.10_3339,BUILD_1"), 2006u);
  action = take_action(&link, OtisGnssLinkActionKind::TransmitOutputQuery);
  otis_gnss_link_complete_action(&link, true, 2007u);

  feed_link(
      &link,
      sentence("PMTK514,0,1,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0"),
      2008u);
  action =
      take_action(&link,
                  OtisGnssLinkActionKind::TransmitOutputConfiguration);
  assert(std::string(action.bytes, action.length) ==
         "$PMTK314,0,1,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0*29\r\n");
  otis_gnss_link_complete_action(&link, true, 2009u);
  feed_link(&link, sentence("PMTK001,314,3"), 2010u);
  action = take_action(&link, OtisGnssLinkActionKind::TransmitOutputQuery);
  otis_gnss_link_complete_action(&link, true, 2011u);
  feed_link(&link, sentence(kExpectedOutput), 2012u);

  assert(otis_gnss_link_online(&link));
  assert(link.confirmed_baud == 9600u);
  assert(link.candidate_rejection_count == 1u);
  assert(link.output_response_count == 2u);
}

void test_output_query_timeout_uses_acknowledged_observed_configuration() {
  OtisGnssLink link;
  const OtisGnssLinkPolicy policy = link_policy();
  otis_gnss_link_reset(&link, &policy, 0u);
  OtisGnssLinkAction action =
      take_action(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 9600u);
  otis_gnss_link_complete_action(&link, true, 0u);
  feed_link(&link, sentence(kValidRmc), 1u);
  action = take_action(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 2u);
  feed_link(&link, sentence("PMTK705,AXN_5.10_3339,BUILD_1"), 3u);
  assert(link.last_identity_response_baud == 9600u);
  action = take_action(&link, OtisGnssLinkActionKind::TransmitOutputQuery);
  otis_gnss_link_complete_action(&link, true, 4u);

  otis_gnss_link_tick(&link, 754u);
  assert(link.output_query_timeout_count == 1u);
  assert(link.configuration_failure_count == 0u);
  action =
      take_action(&link, OtisGnssLinkActionKind::TransmitOutputConfiguration);
  otis_gnss_link_complete_action(&link, true, 755u);
  feed_link(&link, sentence("PMTK001,314,3"), 756u);
  assert(link.output_configuration_ack_count == 1u);
  assert(link.last_command_ack_packet_type == 314u);
  assert(link.last_command_ack_flag == 3u);
  action = take_action(&link, OtisGnssLinkActionKind::TransmitOutputQuery);
  otis_gnss_link_complete_action(&link, true, 757u);
  otis_gnss_link_tick(&link, 1507u);
  assert(link.output_query_timeout_count == 2u);
  assert(link.state == OtisGnssLinkState::ObserveConfiguredOutput);

  feed_link(&link, sentence(kValidRmc), 1600u);
  feed_link(&link, sentence(kValidGga), 1700u);
  feed_link(&link, sentence(kValidGsa), 1800u);
  otis_gnss_link_tick(&link, 4006u);
  assert(!otis_gnss_link_online(&link));
  otis_gnss_link_tick(&link, 4007u);
  assert(otis_gnss_link_online(&link));
  assert(link.output_observation_success_count == 1u);
  assert(link.output_unexpected_sentence_mask == 0u);
  assert(otis_gnss_output_confirmation_method_name(&link) ==
         std::string("pmtk314_ack_observed_exact"));
}

void test_physical_receiver_extended_pmtk514_shape_is_exact() {
  OtisGnssLink link;
  const OtisGnssLinkPolicy policy = link_policy();
  otis_gnss_link_reset(&link, &policy, 0u);
  take_action(&link, OtisGnssLinkActionKind::SetUartBaud);
  otis_gnss_link_complete_action(&link, true, 0u);
  feed_link(&link, sentence(kValidRmc), 1u);
  take_action(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 2u);
  feed_link(&link, sentence("PMTK705,AXN_5.10_3339,BUILD_1"), 3u);
  take_action(&link, OtisGnssLinkActionKind::TransmitOutputQuery);
  otis_gnss_link_complete_action(&link, true, 4u);
  feed_link(&link, sentence(kExpectedExtendedOutput), 5u);

  assert(otis_gnss_link_online(&link));
  assert(link.configuration_failure_count == 0u);
  assert(link.output_configuration_field_count == 22u);
  assert(std::string(link.output_configuration_signature) ==
         "0101100000000000000000");
  assert(std::string(otis_gnss_output_confirmation_method_name(&link)) ==
         "pmtk514_exact");
}

void test_physical_receiver_extension_must_remain_disabled() {
  OtisGnssLink link;
  const OtisGnssLinkPolicy policy = link_policy();
  otis_gnss_link_reset(&link, &policy, 0u);
  take_action(&link, OtisGnssLinkActionKind::SetUartBaud);
  otis_gnss_link_complete_action(&link, true, 0u);
  feed_link(&link, sentence(kValidRmc), 1u);
  take_action(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 2u);
  feed_link(&link, sentence("PMTK705,AXN_5.10_3339,BUILD_1"), 3u);
  take_action(&link, OtisGnssLinkActionKind::TransmitOutputQuery);
  otis_gnss_link_complete_action(&link, true, 4u);
  feed_link(
      &link,
      sentence("PMTK514,0,1,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1"),
      5u);

  assert(!otis_gnss_link_online(&link));
  assert(link.state == OtisGnssLinkState::TransmitOutputConfiguration);
  assert(link.output_configuration_field_count == 22u);
}

void test_observed_configuration_rejects_an_unexpected_sentence() {
  OtisGnssLink link;
  const OtisGnssLinkPolicy policy = link_policy();
  otis_gnss_link_reset(&link, &policy, 0u);
  take_action(&link, OtisGnssLinkActionKind::SetUartBaud);
  otis_gnss_link_complete_action(&link, true, 0u);
  feed_link(&link, sentence(kValidRmc), 1u);
  take_action(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 2u);
  feed_link(&link, sentence("PMTK705,AXN_5.10_3339,BUILD_1"), 3u);
  take_action(&link, OtisGnssLinkActionKind::TransmitOutputQuery);
  otis_gnss_link_complete_action(&link, true, 4u);
  otis_gnss_link_tick(&link, 754u);
  take_action(&link, OtisGnssLinkActionKind::TransmitOutputConfiguration);
  otis_gnss_link_complete_action(&link, true, 755u);
  feed_link(&link, sentence("PMTK001,314,3"), 756u);
  take_action(&link, OtisGnssLinkActionKind::TransmitOutputQuery);
  otis_gnss_link_complete_action(&link, true, 757u);
  otis_gnss_link_tick(&link, 1507u);
  feed_link(&link, sentence("GPGSV,1,1,00"), 1600u);
  otis_gnss_link_tick(&link, 1600u);
  assert(!otis_gnss_link_online(&link));
  assert(link.configuration_failure_count == 1u);
  assert(link.output_unexpected_sentence_mask == 0u);
  assert(link.state == OtisGnssLinkState::SelectCandidateBaud);
  assert(link.last_identity_response_baud == 9600u);
}

void test_discovery_noise_degradation_and_online_loss() {
  OtisGnssLink link;
  const OtisGnssLinkPolicy policy = link_policy();
  otis_gnss_link_reset(&link, &policy, 0u);
  take_action(&link, OtisGnssLinkActionKind::SetUartBaud);
  otis_gnss_link_complete_action(&link, true, 0u);
  feed_link(&link, "$GPRMC,garbage*00\r\n", 10u);
  assert(link.checksum_failure_count == 1u);
  assert(!link.action_pending);
  assert(otis_gnss_link_discovery_degraded(&link, 15000u));
  assert(std::string(otis_gnss_link_state_name(&link, 15000u)) ==
         "degraded");

  establish_target_link(&link, 20000u);
  assert(link.last_valid_frame_ms == 20005u);
  otis_gnss_link_tick(&link, 30005u);
  assert(!otis_gnss_link_online(&link));
  assert(link.link_loss_count == 1u);
  assert(std::string(otis_gnss_link_state_name(&link, 30005u)) == "lost");
}

void test_retained_identity_response_is_causal_before_timeout_advance() {
  const OtisGnssLinkPolicy policy = {
      9600u, 1200u, 2000u, 15000u, 10000u, 2500u};
  OtisGnssLink link = {};
  OtisGnssUartRxRing ring = {};
  otis_gnss_uart_rx_ring_reset(&ring);
  otis_gnss_link_reset(&link, &policy, 0u);
  take_action(&link, OtisGnssLinkActionKind::SetUartBaud);
  otis_gnss_link_complete_action(&link, true, 0u);
  otis_gnss_link_tick(&link, 1200u);
  take_action(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);

  // A prompt response may already be ISR-retained while the UART hardware is
  // still reporting BUSY.  The live service must commit TX completion first.
  retain_link_bytes(&ring, sentence("PMTK705,AXN_5.10_3339,BUILD_1"));
  otis_gnss_link_complete_action(&link, true, 1201u);
  assert(link.state == OtisGnssLinkState::AwaitIdentityResponse);
  drain_link_bytes(&ring, &link, UINT32_MAX, 1202u);
  assert(link.identity_response_count == 1u);
  assert(link.candidate_rejection_count == 0u);
  assert(link.candidate_baud == 9600u);
  take_action(&link, OtisGnssLinkActionKind::TransmitOutputQuery);

  // At a wall deadline, bytes accepted for this candidate can sit behind more
  // than one bounded consumer batch.  Candidate advance remains inhibited
  // until the retained producer frontier is drained and parsed.
  otis_gnss_uart_rx_ring_reset(&ring);
  otis_gnss_link_reset(&link, &policy, 0u);
  take_action(&link, OtisGnssLinkActionKind::SetUartBaud);
  otis_gnss_link_complete_action(&link, true, 0u);
  otis_gnss_link_tick(&link, 1200u);
  take_action(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 1201u);
  retain_link_bytes(
      &ring,
      std::string(160u, 'x') + sentence("PMTK705,AXN_5.10_3339,BUILD_1"));
  assert(drain_link_bytes(&ring, &link, 128u, 3201u) == 128u);
  assert(otis_gnss_uart_rx_ring_depth(&ring) > 0u);
  if (otis_gnss_uart_rx_ring_depth(&ring) == 0u)
    otis_gnss_link_tick(&link, 3201u);
  assert(link.state == OtisGnssLinkState::AwaitIdentityResponse);
  assert(link.candidate_rejection_count == 0u);
  drain_link_bytes(&ring, &link, UINT32_MAX, 3201u);
  assert(link.identity_response_count == 1u);
  assert(link.candidate_rejection_count == 0u);
  assert(link.candidate_baud == 9600u);
}

void test_uart_ring_loss_markers_and_interleaved_high_water() {
  OtisGnssUartRxRing ring = {};
  otis_gnss_uart_rx_ring_reset(&ring);
  otis_gnss_uart_rx_ring_reset_phase_window(&ring);
  const OtisGnssUartObservation byte = {'A', kOtisGnssUartObservationNone};
  for (uint32_t index = 0u; index < 100u; ++index)
    assert(otis_gnss_uart_rx_ring_push_from_isr(&ring, byte));
  OtisGnssUartObservation retained = {};
  assert(otis_gnss_uart_rx_ring_pop(&ring, &retained));
  for (uint32_t index = 0u; index < 50u; ++index)
    assert(otis_gnss_uart_rx_ring_push_from_isr(&ring, byte));
  assert(otis_gnss_uart_rx_ring_pop(&ring, &retained));
  OtisGnssUartRxStats stats = {};
  otis_gnss_uart_rx_ring_snapshot(&ring, &stats);
  assert(stats.ring_high_water == 149u);
  assert(stats.phase_window_ring_high_water == 149u);

  while (otis_gnss_uart_rx_ring_pop(&ring, &retained)) {}
  for (uint32_t index = 0u; index < kOtisGnssUartRxRingCapacity; ++index)
    assert(otis_gnss_uart_rx_ring_push_from_isr(&ring, byte));
  assert(!otis_gnss_uart_rx_ring_push_from_isr(&ring, byte));
  assert(otis_gnss_uart_rx_ring_pop(&ring, &retained));
  assert(otis_gnss_uart_rx_ring_push_from_isr(&ring, byte));
  while (otis_gnss_uart_rx_ring_pop(&ring, &retained)) {
    if ((retained.flags & kOtisGnssUartObservationLossBefore) != 0u) break;
  }
  assert((retained.flags & kOtisGnssUartObservationLossBefore) != 0u);
  otis_gnss_uart_rx_ring_snapshot(&ring, &stats);
  assert(stats.uart_bytes_dropped_before_retention == 1u);
  assert(stats.ring_overflow_count == 1u);
}

void test_uart_phase_window_maxima_reset_without_lifetime_contamination() {
  OtisGnssUartRxRing ring = {};
  otis_gnss_uart_rx_ring_reset(&ring);
  otis_gnss_uart_rx_ring_reset_phase_window(&ring);
  otis_gnss_uart_rx_ring_note_interrupt_from_isr(&ring, 100u, 160u, 40u);
  otis_gnss_uart_rx_ring_note_interrupt_from_isr(&ring, 1100u, 1200u, 80u);
  otis_gnss_uart_rx_ring_note_consumer_start(&ring, 100u);
  otis_gnss_uart_rx_ring_note_consumer_start(&ring, 2100u);
  otis_gnss_uart_rx_ring_note_consumer_complete(&ring, 90u, false, false);
  OtisGnssUartRxStats high = {};
  otis_gnss_uart_rx_ring_snapshot(&ring, &high);
  assert(high.phase_window_maximum_bytes_drained_per_interrupt == 80u);
  assert(high.phase_window_maximum_interrupt_gap_ticks == 1000u);
  assert(high.phase_window_maximum_interrupt_residence_ticks == 100u);
  assert(high.phase_window_maximum_consumer_service_gap_ticks == 2000u);
  assert(high.phase_window_maximum_consumer_drain_batch == 90u);

  otis_gnss_uart_rx_ring_reset_phase_window(&ring);
  otis_gnss_uart_rx_ring_note_interrupt_from_isr(&ring, 3000u, 3010u, 4u);
  otis_gnss_uart_rx_ring_note_interrupt_from_isr(&ring, 3100u, 3110u, 5u);
  otis_gnss_uart_rx_ring_note_consumer_start(&ring, 3000u);
  otis_gnss_uart_rx_ring_note_consumer_start(&ring, 3030u);
  otis_gnss_uart_rx_ring_note_consumer_complete(&ring, 6u, false, false);
  OtisGnssUartRxStats low = {};
  otis_gnss_uart_rx_ring_snapshot(&ring, &low);
  assert(low.phase_window_sequence == high.phase_window_sequence + 1u);
  assert(low.phase_window_maximum_bytes_drained_per_interrupt == 5u);
  assert(low.phase_window_maximum_interrupt_gap_ticks == 100u);
  assert(low.phase_window_maximum_interrupt_residence_ticks == 10u);
  assert(low.phase_window_maximum_consumer_service_gap_ticks == 30u);
  assert(low.phase_window_maximum_consumer_drain_batch == 6u);
  assert(low.maximum_bytes_drained_per_interrupt == 80u);
  assert(low.maximum_consumer_service_gap_ticks == 2000u);
}

void test_uart_error_delivery_and_exact_preceding_gap_capsules() {
  OtisGnssUartRxRing ring = {};
  otis_gnss_uart_rx_ring_reset(&ring);
  const OtisGnssUartObservation errored =
      otis_gnss_uart_observation_from_dr(
          static_cast<uint32_t>('X') | (1u << 8u) | (1u << 11u));
  assert(otis_gnss_uart_rx_ring_push_from_isr(&ring, errored));
  otis_gnss_uart_rx_ring_note_consumer_start(&ring, 100u);
  otis_gnss_uart_rx_ring_note_consumer_start(&ring, 1100u);
  otis_gnss_uart_rx_ring_note_consumer_start(&ring, 1130u);
  OtisGnssUartRxStats stats = {};
  otis_gnss_uart_rx_ring_snapshot(&ring, &stats);
  assert(stats.hardware_framing_count == 1u);
  assert(stats.hardware_overrun_count == 1u);
  assert(stats.maximum_consumer_service_gap_ticks == 1000u);
  assert(stats.last_consumer_service_gap_ticks == 30u);
  OtisGnssUartObservation delivered = {};
  assert(otis_gnss_uart_rx_ring_pop(&ring, &delivered));
  assert(delivered.byte == 'X');
  assert((delivered.flags & kOtisGnssUartObservationFramingError) != 0u);
  assert((delivered.flags & kOtisGnssUartObservationOverrunError) != 0u);

  OtisGnssReceiver receiver = {};
  otis_gnss_receiver_reset(&receiver, 0u);
  for (uint8_t segment = 1u; segment <= 3u; ++segment) {
    const OtisGnssParserFaultContext context = {
        segment, OtisGnssObservationPhase::OrdinaryOnline, 9600u,
        static_cast<uint32_t>(segment), 1u, 2u, 3u, 4u, 7u, 11u,
        static_cast<uint32_t>(20u + segment),
    };
    otis_gnss_receiver_set_fault_context(&receiver, &context);
    otis_gnss_receiver_note_collector_loss_at_ticks(
        &receiver, segment * 10u, segment * 160000u,
        segment == 1u ? OtisGnssParserFaultClass::RawAcquisitionLoss
                      : (segment == 2u
                             ? OtisGnssParserFaultClass::DelimiterBeforeNewline
                             : OtisGnssParserFaultClass::Checksum));
  }
  const OtisGnssReceiverSnapshot receiver_stats = snapshot(receiver, 40u);
  assert(receiver_stats.fault_capsule_count == 3u);
  for (uint8_t index = 0u; index < 3u; ++index) {
    assert(receiver_stats.fault_capsules[index].valid);
    assert(receiver_stats.fault_capsules[index].segment_ordinal == index + 1u);
    assert(receiver_stats.fault_capsules[index].preceding_consumer_gap_ticks ==
           21u + index);
  }
}

}  // namespace

int main() {
  test_valid_and_message_order_variation();
  test_checksum_failure_requires_a_fresh_pair();
  test_truncated_and_oversize_input();
  test_stale_and_short_fix_loss_return();
  test_invalid_utc_and_reconnect_identity_epoch();
  test_gsa_dimension_is_separate_and_fresh_for_active_authority();
  test_passive_target_discovery_and_exact_configuration();
  test_unknown_baud_transition_and_output_reconfiguration();
  test_output_query_timeout_uses_acknowledged_observed_configuration();
  test_physical_receiver_extended_pmtk514_shape_is_exact();
  test_physical_receiver_extension_must_remain_disabled();
  test_observed_configuration_rejects_an_unexpected_sentence();
  test_discovery_noise_degradation_and_online_loss();
  test_retained_identity_response_is_causal_before_timeout_advance();
  test_uart_ring_loss_markers_and_interleaved_high_water();
  test_uart_phase_window_maxima_reset_without_lifetime_contamination();
  test_uart_error_delivery_and_exact_preceding_gap_capsules();
  return 0;
}
