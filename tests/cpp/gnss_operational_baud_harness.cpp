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

void run_configuration_blind_115200_bootstrap(OtisGnssLink *link) {
  constexpr uint32_t kExpectedBootstrapBauds[] = {
      9600u, 19200u, 38400u, 57600u, 14400u, 4800u, 115200u,
  };
  uint32_t now_ms = 0u;
  for (uint32_t baud : kExpectedBootstrapBauds) {
    OtisGnssLinkAction action =
        take(link, OtisGnssLinkActionKind::SetUartBaud);
    assert(action.baud == baud);
    otis_gnss_link_complete_action(link, true, now_ms++);

    action = take(link, OtisGnssLinkActionKind::TransmitTargetBaud);
    assert(std::string(action.bytes, action.length) ==
           "$PMTK251,115200*1F\r\n");
    otis_gnss_link_complete_action(link, true, now_ms++);
  }

  OtisGnssLinkAction action =
      take(link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 115200u);
  otis_gnss_link_complete_action(link, true, now_ms++);
  action = take(link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(link, true, now_ms);
}

void test_operational_startup_promotes_from_every_supported_rate_then_stays_115200() {
  OtisGnssLink link = {};
  const OtisGnssLinkPolicy selected = policy();
  otis_gnss_link_reset(&link, &selected, 0u);
  run_configuration_blind_115200_bootstrap(&link);
  feed(&link, sentence("PMTK705,AXN_5.10_3339,BUILD_1"), 15u);

  assert(link.candidate_rejection_count == 0u);
  assert(link.candidate_baud == 115200u);
  assert(link.state == OtisGnssLinkState::TransmitOutputQuery);
  finish_configuration(&link, 16u);
}

void test_failed_115200_qualification_never_scans_another_baud() {
  OtisGnssLink link = {};
  const OtisGnssLinkPolicy selected = policy();
  otis_gnss_link_reset(&link, &selected, 0u);
  run_configuration_blind_115200_bootstrap(&link);
  otis_gnss_link_tick(&link, 765u);

  OtisGnssLinkAction action =
      take(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 115200u);
  otis_gnss_link_complete_action(&link, true, 766u);
  action = take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  otis_gnss_link_complete_action(&link, true, 767u);
  assert(link.candidate_baud == 115200u);
  assert(link.candidate_rejection_count == 0u);
  assert(link.discovery_cycle == 2u);
}

}  // namespace

int main() {
  test_operational_startup_promotes_from_every_supported_rate_then_stays_115200();
  test_failed_115200_qualification_never_scans_another_baud();
  return 0;
}
