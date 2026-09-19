#include <assert.h>
#include <cstdio>
#include <string>
#include "otis_gnss_receiver.h"

std::string frame(const std::string &body) {
  uint8_t checksum = 0;
  for (char c : body) checksum ^= uint8_t(c);
  char trailer[8]; std::snprintf(trailer, sizeof(trailer), "*%02X\r\n", checksum);
  return "$" + body + trailer;
}
void feed(OtisGnssReceiver &receiver, const std::string &text, uint32_t ms) {
  for (char c : text) otis_gnss_receiver_feed_at_ticks(&receiver, c, ms, uint64_t(ms) * 1000);
}
int main() {
  OtisGnssReceiver receiver{};
  otis_gnss_receiver_reset(&receiver, 0);
  const auto rmc = frame("GNRMC,123519.00,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W");
  const auto gga = frame("GNGGA,123519.00,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,");
  const auto gsa = frame("GNGSA,A,3,04,05,,,,,,,,,,,1.8,1.0,1.5");
  feed(receiver, rmc, 100); feed(receiver, gga, 101); feed(receiver, gsa, 102);
  assert(receiver.rmc_valid && receiver.utc_available && receiver.date_available);
  assert(receiver.fix_quality == 1 && receiver.satellites == 8 && receiver.fix_dimension == 3);
  assert(receiver.parser_drop_count == 0);
  OtisGnssReceiverSnapshot snapshot{};
  otis_gnss_receiver_snapshot(&receiver, 102, 3000, &snapshot);
  assert(snapshot.control_eligible && snapshot.gsa_3d);
  assert(std::string(snapshot.talker) == "GN");
  assert(std::string(receiver.line) == gsa.substr(0, gsa.size() - 2)); // raw line preserved
  auto corrupt = rmc; corrupt[12] ^= 1;
  feed(receiver, corrupt, 200);
  assert(receiver.checksum_failure_count == 1 && receiver.metadata_hold_active);
  auto epoch = receiver.parser_fault_epoch;
  assert(receiver.rmc_repair_epoch != epoch);
  feed(receiver, rmc, 201);
  assert(receiver.rmc_repair_epoch == epoch && receiver.metadata_hold_active);
  otis_gnss_receiver_snapshot(&receiver, 201, 3000, &snapshot);
  assert(!snapshot.control_eligible && !snapshot.checksum_requalified);
  assert(receiver.gga_repair_epoch != epoch); // RMC cannot refresh cached GGA
  feed(receiver, gga, 202);
  assert(!receiver.metadata_hold_active && receiver.gga_repair_epoch == epoch);
  otis_gnss_receiver_snapshot(&receiver, 202, 3000, &snapshot);
  assert(snapshot.control_eligible && !snapshot.gsa_checksum_requalified);
  feed(receiver, gsa, 203);
  otis_gnss_receiver_snapshot(&receiver, 203, 3000, &snapshot);
  assert(snapshot.gsa_checksum_requalified);
  otis_gnss_receiver_snapshot(&receiver, 4000, 3000, &snapshot);
  assert(!snapshot.control_eligible && !snapshot.metadata_fresh);
  // Adafruit rejects malformed consumed fields even with a correct checksum.
  for (const char *body : {
      "GNRMC,996199,A,4807.038,N,01131.000,E,0,0,230394",
      "GNRMC,123519,A,4807.038,N,01131.000,E,0,0,991399",
      "GNGGA,123519,4807.038,N,01131.000,E,1,xx,0.9,545.4,M,46.9",
      "GNGGA,123519,4807.038,N,01131.000,E,1,08,0.9",
      "GNGSA,A,3"}) {
    const auto rmc_count = receiver.rmc_count, gga_count = receiver.gga_count;
    const auto old_epoch = receiver.parser_fault_epoch;
    feed(receiver, frame(body), 300);
    assert(receiver.parser_fault_epoch == old_epoch + 1);
    assert(receiver.rmc_count == rmc_count && receiver.gga_count == gga_count);
  }
  feed(receiver, frame("GNRMC,,V,,,,,,,"), 400);
  assert(!receiver.rmc_valid && !receiver.rmc_utc_available && !receiver.date_available);
  feed(receiver, gga, 401);
  assert(!receiver.utc_available); // empty RMC cannot reuse earlier time/date
  feed(receiver, rmc, 402);
  assert(receiver.utc_available);
  // A second receiver cannot inherit the first receiver's good fix.
  OtisGnssReceiver other{}; otis_gnss_receiver_reset(&other, 0);
  feed(other, gga, 403);
  assert(!other.rmc_seen && !other.utc_available);
}
