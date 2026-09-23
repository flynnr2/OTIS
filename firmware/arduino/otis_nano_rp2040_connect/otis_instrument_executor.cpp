#include "otis_instrument_executor.h"
OtisInstrumentRejection otis_instrument_executor_admit(OtisInstrumentExecutor *executor,
    const OtisInstrumentWrite &r,const OtisInstrumentExecutorState &s,uint64_t ticks) {
  if (!executor || !r.session || !r.sequence || (executor->session && r.session!=executor->session) ||
      r.sequence<=executor->last_sequence || !r.dac_epoch || r.code<0xA800u || r.code>0xAB00u ||
      (r.prior_known && (!s.code_known || r.prior_code!=s.applied_code)))
    return OtisInstrumentRejection::IdentityInvalid;
  executor->session=r.session; executor->last_sequence=r.sequence;
  if (!s.platform_healthy) return OtisInstrumentRejection::PlatformFault;
  if (!s.device_ready) return OtisInstrumentRejection::DeviceUnavailable;
  if (ticks>=r.deadline_ticks) return OtisInstrumentRejection::DeadlineExpired;
  if (r.kind==OtisInstrumentWriteKind::Correction && !s.receiver_qualified)
    return OtisInstrumentRejection::QualificationLost;
  return OtisInstrumentRejection::None;
}
