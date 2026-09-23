#include <cassert>

#include "otis_dual_core_partition.h"

int main() {
  otis_dual_core_partition_reset();

  OtisObservationMessage observation{};
  for (uint32_t i = 0; i < OTIS_OBSERVATION_QUEUE_DEPTH; ++i)
    assert(otis_dual_core_publish_observation(&observation));
  assert(!otis_dual_core_publish_observation(&observation));

  OtisPhasePreviewRecordMessage phase{};
  for (uint32_t i = 0; i < OTIS_PHASE_PREVIEW_QUEUE_DEPTH; ++i)
    assert(otis_dual_core_publish_phase_preview(&phase));
  assert(!otis_dual_core_publish_phase_preview(&phase));

  OtisCriticalRecordMessage critical{};
  for (uint32_t i = 0; i < OTIS_CRITICAL_QUEUE_DEPTH; ++i)
    assert(otis_dual_core_publish_critical(&critical));
  assert(!otis_dual_core_publish_critical(&critical));

  OtisEvidenceFrameMessage evidence{};
  evidence.length = 1u;
  evidence.data[0] = 'x';
  for (uint32_t i = 0; i < OTIS_EVIDENCE_QUEUE_DEPTH - 1u; ++i) {
    evidence.sequence = i + 1u;
    assert(otis_dual_core_publish_evidence(&evidence));
  }
  OtisEvidenceFrameMessage burst[2] = {evidence, evidence};
  burst[0].sequence = 100u;
  burst[1].sequence = 101u;
  assert(!otis_dual_core_publish_evidence_burst(burst, 2u));
  assert(!otis_dual_core_fail_static());

  OtisDualCoreQueueStats stats{};
  otis_dual_core_get_stats(&stats);
  assert(stats.observation_dropped == 1u);
  assert(stats.phase_preview_dropped == 1u);
  assert(stats.critical_dropped == 1u);
  assert(stats.evidence_dropped_frames == 2u);
  assert(stats.evidence_dropped_bursts == 1u);
  assert(stats.evidence_depth == OTIS_EVIDENCE_QUEUE_DEPTH - 1u);

  OtisEvidenceFrameMessage taken{};
  for (uint32_t i = 0; i < OTIS_EVIDENCE_QUEUE_DEPTH - 1u; ++i) {
    assert(otis_dual_core_take_evidence(&taken));
    assert(taken.sequence == i + 1u);
  }
  assert(!otis_dual_core_take_evidence(&taken));
  assert(otis_dual_core_publish_evidence_burst(burst, 2u));
  assert(otis_dual_core_take_evidence(&taken) && taken.sequence == 100u);
  assert(otis_dual_core_take_evidence(&taken) && taken.sequence == 101u);

  // Critical actuator handoffs are independent of full outbound queues.
  OtisInstrumentWrite write{};
  write.sequence = 7u;
  assert(otis_dual_core_publish_instrument_write(&write));
  OtisInstrumentWrite accepted{};
  assert(otis_dual_core_take_instrument_write(&accepted));
  assert(accepted.sequence == 7u);
  OtisInstrumentApplication application{};
  application.request = write;
  assert(otis_dual_core_publish_instrument_application(&application));
  OtisInstrumentApplication result{};
  assert(otis_dual_core_take_instrument_application(&result));
  assert(result.request.sequence == 7u);
  assert(!otis_dual_core_fail_static());

  OtisServiceMessage routine{};
  routine.kind = OtisServiceMessageKind::ReceiverQualification;
  for (uint32_t i = 0u; i < OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH; ++i)
    assert(otis_dual_core_publish_service(&routine));
  OtisServiceMessage hold{};
  hold.kind = OtisServiceMessageKind::RunControl;
  hold.run_control.kind = OtisRunControlKind::Mode;
  hold.run_control.instrument_command.mode = OtisInstrumentMode::Hold;
  assert(otis_dual_core_publish_service(&hold));
  OtisServiceMessage delivered{};
  assert(otis_dual_core_take_service(&delivered));
  assert(delivered.kind == OtisServiceMessageKind::RunControl);
  assert(delivered.run_control.instrument_command.mode == OtisInstrumentMode::Hold);
  assert(!otis_dual_core_fail_static());

  // Internal integrity failure retains its separate strict policy.
  assert(otis_dual_core_publish_instrument_write(&write));
  assert(!otis_dual_core_publish_instrument_write(&write));
  assert(otis_dual_core_fail_static());
}
