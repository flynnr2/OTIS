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

void feed(OtisGnssLink *link, const std::string &text, uint32_t now_ms) {
  for (char byte : text) otis_gnss_link_feed(link, byte, now_ms);
}

OtisGnssLinkAction take(OtisGnssLink *link,
                        OtisGnssLinkActionKind expected) {
  OtisGnssLinkAction action = {};
  assert(otis_gnss_link_take_action(link, &action));
  assert(action.kind == expected);
  return action;
}

OtisGnssLinkPolicy policy() {
  return {115200u, 1200u, 750u, 15000u, 10000u, 2500u};
}

const char *kConfiguredOutput =
    "PMTK514,0,1,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0";

void finish_configuration(OtisGnssLink *link, uint32_t now_ms) {
  OtisGnssLinkAction action =
      take(link, OtisGnssLinkActionKind::TransmitOutputQuery);
  assert(std::string(action.bytes, action.length) == "$PMTK414*33\r\n");
  otis_gnss_link_complete_action(link, true, now_ms);
  feed(link, sentence(kConfiguredOutput), now_ms + 1u);
  assert(otis_gnss_link_online(link));
  assert(otis_gnss_link_runtime_rx_only(link));
  assert(link->confirmed_baud == 115200u);
  assert(link->last_identity_response_baud == 115200u);
}

void test_warm_flash_attaches_at_retained_115200_without_baud_command() {
  OtisGnssLink link = {};
  const OtisGnssLinkPolicy selected = policy();
  otis_gnss_link_reset(&link, &selected, 0u);

  OtisGnssLinkAction action =
      take(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 115200u);
  otis_gnss_link_complete_action(&link, true, 0u);
  feed(&link, sentence("GPRMC,000000.000,V,,,,,,,,,,N"), 1u);
  action = take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 2u);
  feed(&link, sentence("PMTK705,AXN_5.10_3339,BUILD_1"), 3u);

  assert(link.candidate_rejection_count == 0u);
  assert(link.candidate_baud == 115200u);
  assert(link.state == OtisGnssLinkState::TransmitOutputQuery);
  finish_configuration(&link, 4u);
}

void test_receiver_power_cycle_discovers_9600_then_promotes_to_115200() {
  OtisGnssLink link = {};
  const OtisGnssLinkPolicy selected = policy();
  otis_gnss_link_reset(&link, &selected, 0u);

  OtisGnssLinkAction action =
      take(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 115200u);
  otis_gnss_link_complete_action(&link, true, 0u);
  otis_gnss_link_tick(&link, 1200u);
  action = take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 1200u);
  otis_gnss_link_tick(&link, 1950u);

  action = take(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 9600u);
  otis_gnss_link_complete_action(&link, true, 1950u);
  feed(&link, sentence("GPRMC,000000.000,V,,,,,,,,,,N"), 1951u);
  action = take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 1952u);
  feed(&link, sentence("PMTK705,AXN_5.10_3339,BUILD_1"), 1953u);

  action = take(&link, OtisGnssLinkActionKind::TransmitTargetBaud);
  assert(std::string(action.bytes, action.length) ==
         "$PMTK251,115200*1F\r\n");
  otis_gnss_link_complete_action(&link, true, 1954u);
  action = take(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 115200u);
  otis_gnss_link_complete_action(&link, true, 1955u);
  action = take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 1956u);
  feed(&link, sentence("PMTK705,AXN_5.10_3339,BUILD_1"), 1957u);

  assert(link.candidate_rejection_count == 1u);
  finish_configuration(&link, 1958u);
}

}  // namespace

int main() {
  test_warm_flash_attaches_at_retained_115200_without_baud_command();
  test_receiver_power_cycle_discovers_9600_then_promotes_to_115200();
  return 0;
}
