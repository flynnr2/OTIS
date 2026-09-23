#ifndef OTIS_INSTRUMENT_EXECUTOR_H
#define OTIS_INSTRUMENT_EXECUTOR_H
#include "otis_instrument.h"
struct OtisInstrumentExecutor { uint64_t session; uint32_t last_sequence; };
struct OtisInstrumentExecutorState {
  bool platform_healthy;
  bool device_ready;
  bool code_known;
  uint16_t applied_code;
  bool receiver_qualified;
};
// Admission consumes an identity before physical I/O. Repeated publication may
// never repeat a write, even when the previous I2C result was ambiguous.
OtisInstrumentRejection otis_instrument_executor_admit(OtisInstrumentExecutor *, const OtisInstrumentWrite &, const OtisInstrumentExecutorState &, uint64_t ticks);
#endif
