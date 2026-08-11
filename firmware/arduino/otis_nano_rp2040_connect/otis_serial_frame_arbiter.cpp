#include "otis_serial_frame_arbiter.h"

namespace {

constexpr uint8_t kFirstOwner =
    static_cast<uint8_t>(OtisSerialFrameOwner::DualCoreEvidence);
constexpr uint8_t kLastOwner =
    static_cast<uint8_t>(OtisSerialFrameOwner::PhasePreview);

bool ready(OtisSerialFrameOwner owner,
           const OtisSerialFrameReadiness &readiness) {
  switch (owner) {
    case OtisSerialFrameOwner::DualCoreEvidence:
      return readiness.dual_core_evidence;
    case OtisSerialFrameOwner::Phase4Preview:
      return readiness.phase4_preview;
    case OtisSerialFrameOwner::Cx317Preview:
      return readiness.cx317_preview;
    case OtisSerialFrameOwner::PhasePreview:
      return readiness.phase_preview;
    case OtisSerialFrameOwner::None:
      return false;
  }
  return false;
}

uint8_t following(uint8_t owner) {
  return owner >= kLastOwner ? kFirstOwner : static_cast<uint8_t>(owner + 1u);
}

}  // namespace

void otis_serial_frame_arbiter_reset(OtisSerialFrameArbiter *arbiter) {
  if (arbiter == nullptr) return;
  arbiter->owner = OtisSerialFrameOwner::None;
  arbiter->next_priority = kFirstOwner;
}

OtisSerialFrameOwner otis_serial_frame_arbiter_claim(
    OtisSerialFrameArbiter *arbiter,
    const OtisSerialFrameReadiness &readiness) {
  if (arbiter == nullptr) return OtisSerialFrameOwner::None;
  if (arbiter->owner != OtisSerialFrameOwner::None) return arbiter->owner;

  uint8_t candidate = arbiter->next_priority;
  for (uint8_t checked = 0u; checked <= kLastOwner - kFirstOwner; ++checked) {
    OtisSerialFrameOwner owner =
        static_cast<OtisSerialFrameOwner>(candidate);
    if (ready(owner, readiness)) {
      arbiter->owner = owner;
      arbiter->next_priority = following(candidate);
      return owner;
    }
    candidate = following(candidate);
  }
  return OtisSerialFrameOwner::None;
}

bool otis_serial_frame_arbiter_release(OtisSerialFrameArbiter *arbiter,
                                      OtisSerialFrameOwner owner) {
  if (arbiter == nullptr || owner == OtisSerialFrameOwner::None ||
      arbiter->owner != owner)
    return false;
  arbiter->owner = OtisSerialFrameOwner::None;
  return true;
}

OtisSerialFrameOwner otis_serial_frame_arbiter_owner(
    const OtisSerialFrameArbiter *arbiter) {
  return arbiter == nullptr ? OtisSerialFrameOwner::None : arbiter->owner;
}
