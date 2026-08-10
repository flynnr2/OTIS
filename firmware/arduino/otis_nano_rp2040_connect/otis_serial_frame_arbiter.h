#ifndef OTIS_SERIAL_FRAME_ARBITER_H
#define OTIS_SERIAL_FRAME_ARBITER_H

#include <stdint.h>

// Core-0 ownership for chunked records sharing the USB serial byte stream.
// The caller claims one ready producer, services only that producer until its
// complete record group closes, then releases it.  Direct/atomic writers run
// only while this arbiter has no owner and no chunked producer is pending.
enum class OtisSerialFrameOwner : uint8_t {
  None = 0u,
  DualCoreEvidence = 1u,
  Phase4Preview = 2u,
  Cx317Preview = 3u,
  Cx318Preview = 4u,
};

struct OtisSerialFrameReadiness {
  bool dual_core_evidence;
  bool phase4_preview;
  bool cx317_preview;
  bool cx318_preview;
};

struct OtisSerialFrameArbiter {
  OtisSerialFrameOwner owner;
  uint8_t next_priority;
};

void otis_serial_frame_arbiter_reset(OtisSerialFrameArbiter *arbiter);
OtisSerialFrameOwner otis_serial_frame_arbiter_claim(
    OtisSerialFrameArbiter *arbiter,
    const OtisSerialFrameReadiness &readiness);
bool otis_serial_frame_arbiter_release(OtisSerialFrameArbiter *arbiter,
                                      OtisSerialFrameOwner owner);
OtisSerialFrameOwner otis_serial_frame_arbiter_owner(
    const OtisSerialFrameArbiter *arbiter);

#endif
