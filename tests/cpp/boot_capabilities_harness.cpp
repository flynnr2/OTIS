#include <cassert>

#include "otis_boot_capabilities.h"

namespace {

void select_required(OtisBootCapabilityTracker *tracker,
                     OtisBootCapability capability) {
  otis_boot_capability_select(tracker, capability,
                              OtisBootCapabilityRequirement::Required);
}

void record_in_phase(OtisBootCapabilityTracker *tracker, BootPhase phase,
                     OtisBootCapability capability,
                     OtisBootCapabilityOutcome outcome) {
  assert(otis_boot_capability_begin_phase(tracker, phase));
  assert(otis_boot_capability_record(tracker, capability, outcome));
  assert(otis_boot_capability_complete_phase(tracker, phase));
}

OtisBootCapabilityTracker representative_profile(void) {
  OtisBootCapabilityTracker tracker;
  otis_boot_capability_tracker_init(&tracker);
  select_required(&tracker, OtisBootCapability::ResourceRegistry);
  select_required(&tracker, OtisBootCapability::SparseCapture);
  select_required(&tracker, OtisBootCapability::PpsCapture);
  select_required(&tracker, OtisBootCapability::CountBackend);
  select_required(&tracker, OtisBootCapability::Transport);
  otis_boot_capability_select(&tracker, OtisBootCapability::Sensors,
                              OtisBootCapabilityRequirement::Optional);
  return tracker;
}

void record_representative_ready(OtisBootCapabilityTracker *tracker) {
  record_in_phase(tracker, BootPhase::CapabilityAudit,
                  OtisBootCapability::ResourceRegistry,
                  OtisBootCapabilityOutcome::Ready);
  assert(otis_boot_capability_begin_phase(tracker, BootPhase::PpsInputInit));
  assert(otis_boot_capability_record(
      tracker, OtisBootCapability::SparseCapture,
      OtisBootCapabilityOutcome::Ready));
  assert(otis_boot_capability_record(
      tracker, OtisBootCapability::PpsCapture,
      OtisBootCapabilityOutcome::Ready));
  assert(otis_boot_capability_complete_phase(tracker,
                                             BootPhase::PpsInputInit));
  record_in_phase(tracker, BootPhase::TimerInit,
                  OtisBootCapability::CountBackend,
                  OtisBootCapabilityOutcome::Ready);
  record_in_phase(tracker, BootPhase::SerialInit,
                  OtisBootCapability::Transport,
                  OtisBootCapabilityOutcome::Ready);
  record_in_phase(tracker, BootPhase::PeripheralsInit,
                  OtisBootCapability::Sensors,
                  OtisBootCapabilityOutcome::Ready);
}

}  // namespace

int main() {
  // Good boot: all selected required and optional work completed in phases.
  OtisBootCapabilityTracker good = representative_profile();
  record_representative_ready(&good);
  assert(otis_boot_capability_can_mark_run_mode(&good));
  assert(otis_boot_capability_mark_run_mode(&good));
  assert(good.run_mode_marked);
  assert(otis_boot_capability_overall_outcome(&good) ==
         OtisBootCapabilityOutcome::Ready);

  // PIO/sparse-capture allocation failure blocks RunMode.
  OtisBootCapabilityTracker pio_failure = representative_profile();
  record_representative_ready(&pio_failure);
  assert(otis_boot_capability_begin_phase(&pio_failure,
                                          BootPhase::PpsInputInit));
  assert(otis_boot_capability_record(
      &pio_failure, OtisBootCapability::SparseCapture,
      OtisBootCapabilityOutcome::RequiredUnavailable));
  assert(otis_boot_capability_complete_phase(&pio_failure,
                                             BootPhase::PpsInputInit));
  assert(!otis_boot_capability_mark_run_mode(&pio_failure));

  // A selected count backend is part of the required measurement path.
  OtisBootCapabilityTracker count_failure = representative_profile();
  record_representative_ready(&count_failure);
  assert(otis_boot_capability_begin_phase(&count_failure,
                                          BootPhase::TimerInit));
  assert(otis_boot_capability_record(
      &count_failure, OtisBootCapability::CountBackend,
      OtisBootCapabilityOutcome::RequiredUnavailable));
  assert(otis_boot_capability_complete_phase(&count_failure,
                                             BootPhase::TimerInit));
  assert(!otis_boot_capability_can_mark_run_mode(&count_failure));

  // Every other enabled required path, including DAC and Phase 4 preview,
  // follows the same blocking rule.
  const OtisBootCapability required_failures[] = {
      OtisBootCapability::PpsCapture,
      OtisBootCapability::Dac,
      OtisBootCapability::Phase4Preview,
      OtisBootCapability::Transport,
  };
  const BootPhase required_failure_phases[] = {
      BootPhase::PpsInputInit,
      BootPhase::PeripheralsInit,
      BootPhase::PreviewInit,
      BootPhase::SerialInit,
  };
  for (uint8_t index = 0u;
       index < sizeof(required_failures) / sizeof(required_failures[0]);
       ++index) {
    OtisBootCapabilityTracker required_failure;
    otis_boot_capability_tracker_init(&required_failure);
    select_required(&required_failure, required_failures[index]);
    record_in_phase(&required_failure, required_failure_phases[index],
                    required_failures[index],
                    OtisBootCapabilityOutcome::RequiredUnavailable);
    assert(!otis_boot_capability_can_mark_run_mode(&required_failure));
    assert(!otis_boot_capability_mark_run_mode(&required_failure));
  }

  // Optional sensor failure is explicit degradation, not false readiness.
  OtisBootCapabilityTracker sensor_failure = representative_profile();
  record_representative_ready(&sensor_failure);
  assert(otis_boot_capability_begin_phase(&sensor_failure,
                                          BootPhase::PeripheralsInit));
  assert(otis_boot_capability_record(
      &sensor_failure, OtisBootCapability::Sensors,
      OtisBootCapabilityOutcome::OptionalDegraded));
  assert(otis_boot_capability_complete_phase(&sensor_failure,
                                             BootPhase::PeripheralsInit));
  assert(otis_boot_capability_degraded(&sensor_failure));
  assert(otis_boot_capability_overall_outcome(&sensor_failure) ==
         OtisBootCapabilityOutcome::OptionalDegraded);
  assert(otis_boot_capability_mark_run_mode(&sensor_failure));

  // A disabled subsystem is neither attempted nor a blocker.
  OtisBootCapabilityTracker disabled;
  otis_boot_capability_tracker_init(&disabled);
  select_required(&disabled, OtisBootCapability::Transport);
  record_in_phase(&disabled, BootPhase::SerialInit,
                  OtisBootCapability::Transport,
                  OtisBootCapabilityOutcome::Ready);
  const OtisBootCapabilityEntry *disabled_dac =
      otis_boot_capability_entry(&disabled, OtisBootCapability::Dac);
  assert(disabled_dac != nullptr);
  assert(disabled_dac->requirement ==
         OtisBootCapabilityRequirement::Disabled);
  assert(!disabled_dac->reported);
  assert(otis_boot_capability_mark_run_mode(&disabled));

  // Registry validity and completeness remain distinct decisions.
  assert(otis_boot_registry_outcome(false, false) ==
         OtisBootCapabilityOutcome::FatalConflict);
  assert(otis_boot_registry_outcome(true, false) ==
         OtisBootCapabilityOutcome::RequiredUnavailable);
  assert(otis_boot_registry_outcome(true, true) ==
         OtisBootCapabilityOutcome::Ready);

  OtisBootCapabilityTracker invalid_registry;
  otis_boot_capability_tracker_init(&invalid_registry);
  select_required(&invalid_registry, OtisBootCapability::ResourceRegistry);
  record_in_phase(&invalid_registry, BootPhase::CapabilityAudit,
                  OtisBootCapability::ResourceRegistry,
                  OtisBootCapabilityOutcome::FatalConflict);
  assert(otis_boot_capability_has_fatal_conflict(&invalid_registry));
  assert(!otis_boot_capability_mark_run_mode(&invalid_registry));

  OtisBootCapabilityTracker incomplete_registry;
  otis_boot_capability_tracker_init(&incomplete_registry);
  select_required(&incomplete_registry,
                  OtisBootCapability::ResourceRegistry);
  record_in_phase(&incomplete_registry, BootPhase::CapabilityAudit,
                  OtisBootCapability::ResourceRegistry,
                  OtisBootCapabilityOutcome::RequiredUnavailable);
  assert(!otis_boot_capability_has_fatal_conflict(&incomplete_registry));
  assert(!otis_boot_capability_mark_run_mode(&incomplete_registry));

  // Breadcrumb/work ordering is checked independently of hardware.
  OtisBootCapabilityTracker bad_order;
  otis_boot_capability_tracker_init(&bad_order);
  select_required(&bad_order, OtisBootCapability::CountBackend);
  assert(!otis_boot_capability_record(
      &bad_order, OtisBootCapability::CountBackend,
      OtisBootCapabilityOutcome::Ready));
  assert(!bad_order.ordering_valid);
  assert(!otis_boot_capability_mark_run_mode(&bad_order));

  OtisBootCapabilityTracker bracketed;
  otis_boot_capability_tracker_init(&bracketed);
  select_required(&bracketed, OtisBootCapability::CountBackend);
  record_in_phase(&bracketed, BootPhase::TimerInit,
                  OtisBootCapability::CountBackend,
                  OtisBootCapabilityOutcome::Ready);
  const OtisBootCapabilityEntry *count =
      otis_boot_capability_entry(&bracketed,
                                 OtisBootCapability::CountBackend);
  assert(count != nullptr && count->reported);
  assert(count->outcome_phase == BootPhase::TimerInit);
  assert(otis_boot_capability_mark_run_mode(&bracketed));

  return 0;
}
