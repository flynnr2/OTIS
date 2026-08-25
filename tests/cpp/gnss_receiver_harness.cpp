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

OtisGnssLinkPolicy link_policy() {
  return {115200u, 1200u, 750u, 15000u, 10000u};
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

void establish_target_link(OtisGnssLink *link, uint32_t now_ms) {
  const OtisGnssLinkPolicy policy = link_policy();
  otis_gnss_link_reset(link, &policy, now_ms);
  OtisGnssLinkAction action =
      take_action(link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 115200u);
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
  assert(link.confirmed_baud == 115200u);
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
  assert(action.baud == 115200u);
  otis_gnss_link_complete_action(&link, true, 0u);

  otis_gnss_link_tick(&link, 1200u);
  action = take_action(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 1200u);
  otis_gnss_link_tick(&link, 1950u);
  action = take_action(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 9600u);
  otis_gnss_link_complete_action(&link, true, 1950u);

  feed_link(&link, sentence("PMTK010,001"), 2000u);
  action = take_action(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 2001u);
  feed_link(&link, sentence("PMTK705,AXN_5.10_3339,BUILD_1"), 2002u);
  action = take_action(&link, OtisGnssLinkActionKind::TransmitTargetBaud);
  assert(std::string(action.bytes, action.length) ==
         "$PMTK251,115200*1F\r\n");
  otis_gnss_link_complete_action(&link, true, 2003u);
  action = take_action(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 115200u);
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
  assert(link.confirmed_baud == 115200u);
  assert(link.candidate_rejection_count == 1u);
  assert(link.output_response_count == 2u);
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
  test_discovery_noise_degradation_and_online_loss();
  return 0;
}
