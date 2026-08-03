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

}  // namespace

int main() {
  test_valid_and_message_order_variation();
  test_checksum_failure_requires_a_fresh_pair();
  test_truncated_and_oversize_input();
  test_stale_and_short_fix_loss_return();
  test_invalid_utc_and_reconnect_identity_epoch();
  return 0;
}
