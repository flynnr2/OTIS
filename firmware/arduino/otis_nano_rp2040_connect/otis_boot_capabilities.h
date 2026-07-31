#ifndef OTIS_BOOT_CAPABILITIES_H
#define OTIS_BOOT_CAPABILITIES_H

#include <stdint.h>

#include "OtisBootConfig.h"

enum class OtisBootCapability : uint8_t {
  ResourceRegistry,
  Timebase,
  RingBuffers,
  SparseCapture,
  PpsCapture,
  PpsWitness,
  CountBackend,
  PseudoPpsGenerator,
  Dac,
  Sensors,
  Phase4Preview,
  Transport,
  HostConnection,
  Count,
};

enum class OtisBootCapabilityRequirement : uint8_t {
  Disabled,
  Optional,
  Required,
};

enum class OtisBootCapabilityOutcome : uint8_t {
  Ready,
  OptionalDegraded,
  RequiredUnavailable,
  FatalConflict,
};

struct OtisBootCapabilityEntry {
  OtisBootCapabilityRequirement requirement;
  OtisBootCapabilityOutcome outcome;
  BootPhase outcome_phase;
  bool reported;
};

struct OtisBootCapabilityTracker {
  OtisBootCapabilityEntry
      entries[static_cast<uint8_t>(OtisBootCapability::Count)];
  BootPhase active_phase;
  uint32_t ordering_sequence;
  bool phase_active;
  bool ordering_valid;
  bool run_mode_marked;
};

void otis_boot_capability_tracker_init(OtisBootCapabilityTracker *tracker);
void otis_boot_capability_select(
    OtisBootCapabilityTracker *tracker, OtisBootCapability capability,
    OtisBootCapabilityRequirement requirement);
bool otis_boot_capability_begin_phase(OtisBootCapabilityTracker *tracker,
                                      BootPhase phase);
bool otis_boot_capability_record(OtisBootCapabilityTracker *tracker,
                                 OtisBootCapability capability,
                                 OtisBootCapabilityOutcome outcome);
bool otis_boot_capability_complete_phase(OtisBootCapabilityTracker *tracker,
                                         BootPhase phase);
bool otis_boot_capability_can_mark_run_mode(
    const OtisBootCapabilityTracker *tracker);
bool otis_boot_capability_mark_run_mode(OtisBootCapabilityTracker *tracker);
bool otis_boot_capability_degraded(
    const OtisBootCapabilityTracker *tracker);
bool otis_boot_capability_has_fatal_conflict(
    const OtisBootCapabilityTracker *tracker);
OtisBootCapabilityOutcome otis_boot_capability_overall_outcome(
    const OtisBootCapabilityTracker *tracker);
const OtisBootCapabilityEntry *otis_boot_capability_entry(
    const OtisBootCapabilityTracker *tracker,
    OtisBootCapability capability);

OtisBootCapabilityOutcome otis_boot_capability_result(
    OtisBootCapabilityRequirement requirement, bool ready);
OtisBootCapabilityOutcome otis_boot_registry_outcome(bool valid,
                                                     bool complete);
const char *otis_boot_capability_name(OtisBootCapability capability);
const char *otis_boot_capability_requirement_name(
    OtisBootCapabilityRequirement requirement);
const char *otis_boot_capability_outcome_name(
    OtisBootCapabilityOutcome outcome);

#endif
