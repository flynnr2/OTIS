#include <assert.h>
#include <stdint.h>

#include <cstdio>
#include <string>

#include "otis_config.h"
#include "otis_gnss_receiver.h"

namespace {

constexpr uint32_t kBootstrapBauds[] = {
    9600u, 115200u,
};
constexpr size_t kBootstrapBaudCount =
    sizeof(kBootstrapBauds) / sizeof(kBootstrapBauds[0]);

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
  if (!otis_gnss_link_take_action(link, &action)) {
    std::fprintf(stderr,
                 "missing action expected=%u state=%u pending=%u in_progress=%u "
                 "index=%u attempts=%lu complete=%u failed=%u\n",
                 static_cast<unsigned>(expected),
                 static_cast<unsigned>(link->state), link->action_pending,
                 link->action_in_progress, link->candidate_index,
                 static_cast<unsigned long>(
                     link->operational_bootstrap_attempt_count),
                 link->operational_bootstrap_complete,
                 link->operational_bootstrap_failed);
    assert(false);
  }
  assert(action.kind == expected);
  return action;
}

void assert_no_action(OtisGnssLink *link) {
  OtisGnssLinkAction action = {};
  assert(!otis_gnss_link_take_action(link, &action));
}

OtisGnssLinkPolicy policy() {
  return {115200u, 1200u, 750u, 15000u, 10000u, 2500u};
}

const char *kConfiguredOutput =
    "PMTK514,0,1,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0";

struct FakeReceiver {
  uint32_t baud;
  uint32_t host_baud;
  uint32_t decoded_promotion_count;
};

struct ReplenishingHardwareRx {
  uint32_t available_calls;
  uint32_t discard_calls;
};

bool always_available(void *context) {
  ReplenishingHardwareRx *const rx =
      static_cast<ReplenishingHardwareRx *>(context);
  rx->available_calls++;
  return true;
}

void discard_replenished_byte(void *context) {
  ReplenishingHardwareRx *const rx =
      static_cast<ReplenishingHardwareRx *>(context);
  rx->discard_calls++;
}

uint32_t run_fixed_bootstrap(OtisGnssLink *link, FakeReceiver *receiver,
                             uint32_t start_ms = 0u) {
  uint32_t now_ms = start_ms;
  for (size_t index = 0u; index < kBootstrapBaudCount; ++index) {
    OtisGnssLinkAction action =
        take(link, OtisGnssLinkActionKind::SetUartBaud);
    assert(action.baud == kBootstrapBauds[index]);
    receiver->host_baud = action.baud;
    otis_gnss_link_complete_action(link, true, now_ms);

    action = take(link, OtisGnssLinkActionKind::TransmitTargetBaud);
    assert(std::string(action.bytes, action.length) ==
           "$PMTK251,115200*1F\r\n");
    const bool receiver_decodes_command =
        receiver->host_baud == receiver->baud;
    otis_gnss_link_complete_action(link, true, now_ms);
    assert(link->state == OtisGnssLinkState::OperationalBootstrapSettle);
    assert_no_action(link);

    otis_gnss_link_tick(
        link, now_ms + OTIS_GNSS_OPERATIONAL_PROMOTION_SETTLE_MS - 1u);
    assert_no_action(link);
    if (receiver_decodes_command) {
      receiver->baud = 115200u;
      receiver->decoded_promotion_count++;
    }
    now_ms += OTIS_GNSS_OPERATIONAL_PROMOTION_SETTLE_MS;
    otis_gnss_link_tick(link, now_ms);
  }

  assert(link->operational_bootstrap_complete);
  assert(!link->operational_bootstrap_failed);
  assert(link->operational_bootstrap_attempt_count == kBootstrapBaudCount);
  assert(link->operational_bootstrap_peripheral_complete_count ==
         kBootstrapBaudCount);
  assert(link->operational_bootstrap_completed_rate_mask == 0x3u);
  assert(link->operational_bootstrap_first_completed_baud == 9600u);
  assert(link->operational_bootstrap_second_completed_baud == 115200u);
  assert(link->target_baud_command_attempt_count == kBootstrapBaudCount);
  assert(link->post_bootstrap_target_baud_command_attempt_count == 0u);
  assert(receiver->host_baud == 115200u);
  assert(receiver->baud == 115200u);
  assert(receiver->decoded_promotion_count >= 1u);
  return now_ms;
}

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

void test_default_or_retained_operational_start_reaches_permanent_115200() {
  constexpr uint32_t kRetainedStarts[] = {
      9600u, 115200u,
  };
  for (uint32_t retained_baud : kRetainedStarts) {
    OtisGnssLink link = {};
    const OtisGnssLinkPolicy selected = policy();
    otis_gnss_link_reset(&link, &selected, 0u);
    FakeReceiver receiver = {retained_baud, 0u, 0u};
    const uint32_t now_ms = run_fixed_bootstrap(&link, &receiver);

    OtisGnssLinkAction action =
        take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
    assert(std::string(action.bytes, action.length) == "$PMTK605*31\r\n");
    otis_gnss_link_complete_action(&link, true, now_ms);
    feed(&link, sentence("PMTK705,AXN_5.10_3339,BUILD_1"), now_ms + 1u);
    assert(link.state == OtisGnssLinkState::TransmitOutputQuery);
    finish_configuration(&link, now_ms + 2u);
  }
}

void test_settle_deadline_is_wrap_safe() {
  OtisGnssLink link = {};
  const OtisGnssLinkPolicy selected = policy();
  const uint32_t completion_ms = UINT32_MAX - 500u;
  otis_gnss_link_reset(&link, &selected, completion_ms);
  OtisGnssLinkAction action =
      take(&link, OtisGnssLinkActionKind::SetUartBaud);
  otis_gnss_link_complete_action(&link, true, completion_ms);
  action = take(&link, OtisGnssLinkActionKind::TransmitTargetBaud);
  otis_gnss_link_complete_action(&link, true, completion_ms);
  otis_gnss_link_tick(
      &link, completion_ms + OTIS_GNSS_OPERATIONAL_PROMOTION_SETTLE_MS - 1u);
  assert_no_action(&link);
  otis_gnss_link_tick(
      &link, completion_ms + OTIS_GNSS_OPERATIONAL_PROMOTION_SETTLE_MS);
  action = take(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 115200u);
}

void test_nonempty_rx_frontier_cannot_starve_operational_settle() {
  OtisGnssLink link = {};
  const OtisGnssLinkPolicy selected = policy();
  otis_gnss_link_reset(&link, &selected, 0u);
  OtisGnssLinkAction action =
      take(&link, OtisGnssLinkActionKind::SetUartBaud);
  otis_gnss_link_complete_action(&link, true, 0u);
  action = take(&link, OtisGnssLinkActionKind::TransmitTargetBaud);
  otis_gnss_link_complete_action(&link, true, 0u);

  // The live scheduler sees a nonempty ring here. The pure predicate is its
  // exact exception for the old-baud operational settle frontier.
  assert(otis_gnss_link_tick_may_advance_with_rx_backlog(&link));
  otis_gnss_link_tick(&link,
                      OTIS_GNSS_OPERATIONAL_PROMOTION_SETTLE_MS);
  action = take(&link, OtisGnssLinkActionKind::SetUartBaud);
  assert(action.baud == 115200u);
  assert(!otis_gnss_link_tick_may_advance_with_rx_backlog(&link));
}

void test_continuously_replenished_hardware_discard_is_bounded() {
  ReplenishingHardwareRx rx = {};
  const uint32_t discarded = otis_gnss_uart_rx_bounded_hardware_discard(
      always_available, discard_replenished_byte, &rx,
      kOtisGnssUartRxTransitionHardwareDiscardBudget);
  assert(discarded == kOtisGnssUartRxTransitionHardwareDiscardBudget);
  assert(rx.discard_calls == kOtisGnssUartRxTransitionHardwareDiscardBudget);
  assert(rx.available_calls == kOtisGnssUartRxTransitionHardwareDiscardBudget);
}

void test_post_bootstrap_identity_timeout_never_reconfigures_uart() {
  OtisGnssLink link = {};
  const OtisGnssLinkPolicy selected = policy();
  otis_gnss_link_reset(&link, &selected, 0u);
  FakeReceiver receiver = {9600u, 0u, 0u};
  uint32_t now_ms = run_fixed_bootstrap(&link, &receiver);
  OtisGnssLinkAction action =
      take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  assert(std::string(action.bytes, action.length) == "$PMTK605*31\r\n");
  otis_gnss_link_complete_action(&link, true, now_ms);

  now_ms += selected.response_timeout_ms;
  otis_gnss_link_tick(&link, now_ms);
  assert(link.state == OtisGnssLinkState::PassiveListen);
  assert(link.operational_bootstrap_attempt_count == kBootstrapBaudCount);
  assert(link.target_baud_command_attempt_count == kBootstrapBaudCount);
  assert(link.post_bootstrap_target_baud_command_attempt_count == 0u);
  assert_no_action(&link);

  otis_gnss_link_tick(&link, now_ms + selected.passive_dwell_ms - 1u);
  assert_no_action(&link);
  otis_gnss_link_tick(&link, now_ms + selected.passive_dwell_ms);
  action = take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  assert(action.baud == 0u);
  assert(link.state == OtisGnssLinkState::TransmitTargetIdentityQuery);
  assert(link.operational_bootstrap_attempt_count == kBootstrapBaudCount);
  assert(link.target_baud_command_attempt_count == kBootstrapBaudCount);
  assert(link.post_bootstrap_target_baud_command_attempt_count == 0u);
}

void test_bootstrap_transmit_failure_is_finite_and_fail_static() {
  OtisGnssLink link = {};
  const OtisGnssLinkPolicy selected = policy();
  otis_gnss_link_reset(&link, &selected, 0u);
  OtisGnssLinkAction action =
      take(&link, OtisGnssLinkActionKind::SetUartBaud);
  otis_gnss_link_complete_action(&link, true, 0u);
  action = take(&link, OtisGnssLinkActionKind::TransmitTargetBaud);
  otis_gnss_link_complete_action(&link, false, 1u);
  assert(link.state == OtisGnssLinkState::OperationalBootstrapFailed);
  assert(link.operational_bootstrap_failed);
  assert(!link.operational_bootstrap_complete);
  assert(link.operational_bootstrap_attempt_count == 1u);
  assert(link.operational_bootstrap_peripheral_complete_count == 0u);
  assert(link.target_baud_command_attempt_count == 1u);
  otis_gnss_link_tick(&link, 100000u);
  assert_no_action(&link);
}

void test_any_post_bootstrap_promotion_attempt_is_counted() {
  OtisGnssLink link = {};
  const OtisGnssLinkPolicy selected = policy();
  otis_gnss_link_reset(&link, &selected, 0u);
  FakeReceiver receiver = {9600u, 0u, 0u};
  const uint32_t now_ms = run_fixed_bootstrap(&link, &receiver);

  link.state = OtisGnssLinkState::TransmitTargetBaud;
  link.pending_action = OtisGnssLinkActionKind::TransmitTargetBaud;
  link.action_pending = true;
  link.action_in_progress = false;
  const OtisGnssLinkAction action =
      take(&link, OtisGnssLinkActionKind::TransmitTargetBaud);
  assert(std::string(action.bytes, action.length) ==
         "$PMTK251,115200*1F\r\n");
  assert(link.operational_bootstrap_attempt_count == kBootstrapBaudCount);
  assert(link.target_baud_command_attempt_count == kBootstrapBaudCount + 1u);
  assert(link.post_bootstrap_target_baud_command_attempt_count == 1u);
  otis_gnss_link_complete_action(&link, false, now_ms + 1u);
}

void test_pre_boundary_identity_cannot_qualify_final_target() {
  OtisGnssLink link = {};
  const OtisGnssLinkPolicy selected = policy();
  otis_gnss_link_reset(&link, &selected, 0u);
  FakeReceiver receiver = {115200u, 0u, 0u};

  uint32_t now_ms = 0u;
  for (size_t index = 0u; index < kBootstrapBaudCount; ++index) {
    OtisGnssLinkAction action =
        take(&link, OtisGnssLinkActionKind::SetUartBaud);
    receiver.host_baud = action.baud;
    otis_gnss_link_complete_action(&link, true, now_ms);
    action = take(&link, OtisGnssLinkActionKind::TransmitTargetBaud);
    otis_gnss_link_complete_action(&link, true, now_ms);
    if (index + 1u == kBootstrapBaudCount) {
      feed(&link, sentence("PMTK705,STALE_PRE_BOUNDARY"), now_ms + 1u);
      assert(link.identity_response_count == 0u);
      assert(link.confirmed_baud == 0u);
    }
    now_ms += OTIS_GNSS_OPERATIONAL_PROMOTION_SETTLE_MS;
    otis_gnss_link_tick(&link, now_ms);
  }

  OtisGnssLinkAction action =
      take(&link, OtisGnssLinkActionKind::TransmitIdentityQuery);
  assert(std::string(action.bytes, action.length) == "$PMTK605*31\r\n");
  otis_gnss_link_complete_action(&link, true, now_ms);
  feed(&link, "$PMTK705,SPLIT", now_ms + 1u);
  otis_gnss_link_note_baud_epoch_boundary(&link);
  feed(&link, sentence("PMTK705,FRESH_POST_BOUNDARY"), now_ms + 2u);
  assert(link.identity_response_count == 1u);
  assert(link.confirmed_baud == 115200u);
  assert(link.state == OtisGnssLinkState::TransmitOutputQuery);
}

}  // namespace

int main() {
  test_default_or_retained_operational_start_reaches_permanent_115200();
  test_settle_deadline_is_wrap_safe();
  test_nonempty_rx_frontier_cannot_starve_operational_settle();
  test_continuously_replenished_hardware_discard_is_bounded();
  test_post_bootstrap_identity_timeout_never_reconfigures_uart();
  test_bootstrap_transmit_failure_is_finite_and_fail_static();
  test_any_post_bootstrap_promotion_attempt_is_counted();
  test_pre_boundary_identity_cannot_qualify_final_target();
  return 0;
}
