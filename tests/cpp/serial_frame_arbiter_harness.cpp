#include <assert.h>

#include <algorithm>
#include <array>
#include <cstddef>
#include <string>
#include <vector>

#include "otis_serial_frame_arbiter.h"

namespace {

struct Producer {
  OtisSerialFrameOwner owner;
  std::vector<std::string> groups;
  size_t group = 0u;
  size_t sent = 0u;

  bool pending() const { return group < groups.size(); }
  bool active() const { return pending() && sent != 0u; }

  bool service(size_t available, std::string *wire) {
    assert(pending());
    const std::string &frame = groups[group];
    const size_t chunk = std::min(available, frame.size() - sent);
    wire->append(frame.data() + sent, chunk);
    sent += chunk;
    if (sent != frame.size()) return true;
    ++group;
    sent = 0u;
    return false;
  }
};

Producer *find(std::array<Producer, 3> *producers,
               OtisSerialFrameOwner owner) {
  for (Producer &producer : *producers)
    if (producer.owner == owner) return &producer;
  return nullptr;
}

OtisSerialFrameReadiness readiness(
    const std::array<Producer, 3> &producers) {
  return {
      producers[0].pending(),
      producers[1].pending(),
      producers[2].pending(),
  };
}

void test_partial_owner_is_exclusive_and_direct_output_waits() {
  const std::string evidence = "ACT," + std::string(410u, 'E') + "\r\n";
  const std::string regulation = "EST," + std::string(90u, 'I') + "\r\n";
  const std::string phase_preview = "RPH," + std::string(100u, 'R') + "\r\n" +
                            "PHE," + std::string(100u, 'H') + "\r\n";
  std::array<Producer, 3> producers = {{
      {OtisSerialFrameOwner::DualCoreEvidence, {evidence}},
      {OtisSerialFrameOwner::FrequencyRegulation, {regulation}},
      {OtisSerialFrameOwner::PhasePreview, {phase_preview}},
  }};
  const std::array<size_t, 6> capacities = {64u, 0u, 31u, 192u, 7u, 4096u};
  OtisSerialFrameArbiter arbiter = {};
  otis_serial_frame_arbiter_reset(&arbiter);
  std::string wire;
  bool direct_pending = false;
  bool direct_written = false;
  OtisSerialFrameOwner partial_owner = OtisSerialFrameOwner::None;

  for (size_t iteration = 0u; iteration < 200u; ++iteration) {
    if (iteration == 2u) direct_pending = true;
    OtisSerialFrameOwner owner =
        otis_serial_frame_arbiter_claim(&arbiter, readiness(producers));
    if (owner != OtisSerialFrameOwner::None) {
      if (partial_owner != OtisSerialFrameOwner::None)
        assert(owner == partial_owner);
      Producer *producer = find(&producers, owner);
      assert(producer != nullptr);
      const bool active =
          producer->service(capacities[iteration % capacities.size()], &wire);
      if (active) {
        partial_owner = owner;
      } else {
        partial_owner = OtisSerialFrameOwner::None;
        assert(otis_serial_frame_arbiter_release(&arbiter, owner));
      }
      continue;
    }
    if (direct_pending) {
      wire += "STS,1,direct\r\n";
      direct_pending = false;
      direct_written = true;
    }
    bool any_pending = false;
    for (const Producer &producer : producers) any_pending |= producer.pending();
    if (!any_pending && !direct_pending) break;
  }

  assert(direct_written);
  assert(wire == evidence + regulation + phase_preview +
                     "STS,1,direct\r\n");
  assert(otis_serial_frame_arbiter_owner(&arbiter) ==
         OtisSerialFrameOwner::None);
}

void test_round_robin_releases_between_complete_groups() {
  std::array<Producer, 3> producers = {{
      {OtisSerialFrameOwner::DualCoreEvidence, {"EST,first\r\n", "EST,second\r\n"}},
      {OtisSerialFrameOwner::FrequencyRegulation, {"CTL,one\r\n"}},
      {OtisSerialFrameOwner::PhasePreview, {"RPH,PHE\r\n"}},
  }};
  OtisSerialFrameArbiter arbiter = {};
  otis_serial_frame_arbiter_reset(&arbiter);
  std::string wire;
  for (size_t iteration = 0u; iteration < 10u; ++iteration) {
    const OtisSerialFrameOwner owner =
        otis_serial_frame_arbiter_claim(&arbiter, readiness(producers));
    if (owner == OtisSerialFrameOwner::None) break;
    Producer *producer = find(&producers, owner);
    assert(producer != nullptr);
    assert(!producer->service(4096u, &wire));
    assert(otis_serial_frame_arbiter_release(&arbiter, owner));
  }
  assert(wire == "EST,first\r\nCTL,one\r\nRPH,PHE\r\nEST,second\r\n");
}

}  // namespace

int main() {
  test_partial_owner_is_exclusive_and_direct_output_waits();
  test_round_robin_releases_between_complete_groups();
  return 0;
}
