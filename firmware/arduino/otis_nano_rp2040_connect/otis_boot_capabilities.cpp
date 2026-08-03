#include "otis_boot_capabilities.h"

#include <stddef.h>

namespace {

constexpr uint8_t capability_index(OtisBootCapability capability) {
  return static_cast<uint8_t>(capability);
}

constexpr uint8_t kCapabilityCount =
    static_cast<uint8_t>(OtisBootCapability::Count);

bool outcome_allows_run_mode(const OtisBootCapabilityEntry &entry) {
  if (entry.requirement == OtisBootCapabilityRequirement::Disabled) {
    return true;
  }
  if (!entry.reported) {
    return false;
  }
  if (entry.requirement == OtisBootCapabilityRequirement::Required) {
    return entry.outcome == OtisBootCapabilityOutcome::Ready;
  }
  return entry.outcome == OtisBootCapabilityOutcome::Ready ||
         entry.outcome == OtisBootCapabilityOutcome::OptionalDegraded;
}

}  // namespace

void otis_boot_capability_tracker_init(OtisBootCapabilityTracker *tracker) {
  if (tracker == nullptr) {
    return;
  }
  for (uint8_t index = 0u; index < kCapabilityCount; ++index) {
    tracker->entries[index] = {
        OtisBootCapabilityRequirement::Disabled,
        OtisBootCapabilityOutcome::Ready,
        BootPhase::ResetEntry,
        false,
    };
  }
  tracker->active_phase = BootPhase::ResetEntry;
  tracker->ordering_sequence = 0u;
  tracker->phase_active = false;
  tracker->ordering_valid = true;
  tracker->run_mode_marked = false;
}

void otis_boot_capability_select(
    OtisBootCapabilityTracker *tracker, OtisBootCapability capability,
    OtisBootCapabilityRequirement requirement) {
  if (tracker == nullptr || capability == OtisBootCapability::Count) {
    return;
  }
  OtisBootCapabilityEntry &entry =
      tracker->entries[capability_index(capability)];
  entry.requirement = requirement;
  entry.outcome = OtisBootCapabilityOutcome::Ready;
  entry.outcome_phase = BootPhase::ResetEntry;
  entry.reported = false;
}

bool otis_boot_capability_begin_phase(OtisBootCapabilityTracker *tracker,
                                      BootPhase phase) {
  if (tracker == nullptr) {
    return false;
  }
  tracker->ordering_sequence++;
  if (tracker->phase_active || tracker->run_mode_marked) {
    tracker->ordering_valid = false;
    return false;
  }
  tracker->active_phase = phase;
  tracker->phase_active = true;
  return true;
}

bool otis_boot_capability_record(OtisBootCapabilityTracker *tracker,
                                 OtisBootCapability capability,
                                 OtisBootCapabilityOutcome outcome) {
  if (tracker == nullptr || capability == OtisBootCapability::Count) {
    return false;
  }
  tracker->ordering_sequence++;
  if (!tracker->phase_active || tracker->run_mode_marked) {
    tracker->ordering_valid = false;
    return false;
  }
  OtisBootCapabilityEntry &entry =
      tracker->entries[capability_index(capability)];
  if (entry.requirement == OtisBootCapabilityRequirement::Disabled) {
    tracker->ordering_valid = false;
    return false;
  }
  entry.outcome = outcome;
  entry.outcome_phase = tracker->active_phase;
  entry.reported = true;
  return true;
}

bool otis_boot_capability_complete_phase(OtisBootCapabilityTracker *tracker,
                                         BootPhase phase) {
  if (tracker == nullptr) {
    return false;
  }
  tracker->ordering_sequence++;
  if (!tracker->phase_active || tracker->active_phase != phase ||
      tracker->run_mode_marked) {
    tracker->ordering_valid = false;
    return false;
  }
  tracker->phase_active = false;
  return true;
}

bool otis_boot_capability_can_mark_run_mode(
    const OtisBootCapabilityTracker *tracker) {
  if (tracker == nullptr || !tracker->ordering_valid ||
      tracker->phase_active || tracker->run_mode_marked) {
    return false;
  }
  for (uint8_t index = 0u; index < kCapabilityCount; ++index) {
    if (!outcome_allows_run_mode(tracker->entries[index])) {
      return false;
    }
  }
  return true;
}

bool otis_boot_capability_mark_run_mode(OtisBootCapabilityTracker *tracker) {
  if (!otis_boot_capability_can_mark_run_mode(tracker)) {
    return false;
  }
  tracker->ordering_sequence++;
  tracker->run_mode_marked = true;
  return true;
}

bool otis_boot_capability_degraded(
    const OtisBootCapabilityTracker *tracker) {
  if (tracker == nullptr) {
    return false;
  }
  for (uint8_t index = 0u; index < kCapabilityCount; ++index) {
    const OtisBootCapabilityEntry &entry = tracker->entries[index];
    if (entry.requirement == OtisBootCapabilityRequirement::Optional &&
        entry.reported &&
        entry.outcome == OtisBootCapabilityOutcome::OptionalDegraded) {
      return true;
    }
  }
  return false;
}

bool otis_boot_capability_has_fatal_conflict(
    const OtisBootCapabilityTracker *tracker) {
  if (tracker == nullptr) {
    return false;
  }
  for (uint8_t index = 0u; index < kCapabilityCount; ++index) {
    if (tracker->entries[index].reported &&
        tracker->entries[index].outcome ==
            OtisBootCapabilityOutcome::FatalConflict) {
      return true;
    }
  }
  return false;
}

OtisBootCapabilityOutcome otis_boot_capability_overall_outcome(
    const OtisBootCapabilityTracker *tracker) {
  if (tracker == nullptr || !tracker->ordering_valid) {
    return OtisBootCapabilityOutcome::RequiredUnavailable;
  }
  bool degraded = false;
  for (uint8_t index = 0u; index < kCapabilityCount; ++index) {
    const OtisBootCapabilityEntry &entry = tracker->entries[index];
    if (entry.reported &&
        entry.outcome == OtisBootCapabilityOutcome::FatalConflict) {
      return OtisBootCapabilityOutcome::FatalConflict;
    }
    if (!outcome_allows_run_mode(entry)) {
      return OtisBootCapabilityOutcome::RequiredUnavailable;
    }
    degraded =
        degraded ||
        (entry.requirement == OtisBootCapabilityRequirement::Optional &&
         entry.reported &&
         entry.outcome == OtisBootCapabilityOutcome::OptionalDegraded);
  }
  return degraded ? OtisBootCapabilityOutcome::OptionalDegraded
                  : OtisBootCapabilityOutcome::Ready;
}

const OtisBootCapabilityEntry *otis_boot_capability_entry(
    const OtisBootCapabilityTracker *tracker,
    OtisBootCapability capability) {
  if (tracker == nullptr || capability == OtisBootCapability::Count) {
    return nullptr;
  }
  return &tracker->entries[capability_index(capability)];
}

OtisBootCapabilityOutcome otis_boot_capability_result(
    OtisBootCapabilityRequirement requirement, bool ready) {
  if (ready) {
    return OtisBootCapabilityOutcome::Ready;
  }
  if (requirement == OtisBootCapabilityRequirement::Optional) {
    return OtisBootCapabilityOutcome::OptionalDegraded;
  }
  return OtisBootCapabilityOutcome::RequiredUnavailable;
}

OtisBootCapabilityOutcome otis_boot_registry_outcome(bool valid,
                                                     bool complete) {
  if (!valid) {
    return OtisBootCapabilityOutcome::FatalConflict;
  }
  return complete ? OtisBootCapabilityOutcome::Ready
                  : OtisBootCapabilityOutcome::RequiredUnavailable;
}

const char *otis_boot_capability_name(OtisBootCapability capability) {
  switch (capability) {
    case OtisBootCapability::ResourceRegistry:
      return "resource_registry";
    case OtisBootCapability::Timebase:
      return "timebase";
    case OtisBootCapability::RingBuffers:
      return "ring_buffers";
    case OtisBootCapability::SparseCapture:
      return "sparse_capture";
    case OtisBootCapability::PpsCapture:
      return "pps_capture";
    case OtisBootCapability::PpsWitness:
      return "pps_witness";
    case OtisBootCapability::CountBackend:
      return "count_backend";
    case OtisBootCapability::PseudoPpsGenerator:
      return "pseudo_pps_generator";
    case OtisBootCapability::Dac:
      return "dac";
    case OtisBootCapability::Sensors:
      return "sensors";
    case OtisBootCapability::GnssReceiver:
      return "gnss_receiver";
    case OtisBootCapability::Phase4Preview:
      return "phase4_preview";
    case OtisBootCapability::Transport:
      return "transport";
    case OtisBootCapability::HostConnection:
      return "host_connection";
    case OtisBootCapability::Count:
      break;
  }
  return "unknown";
}

const char *otis_boot_capability_requirement_name(
    OtisBootCapabilityRequirement requirement) {
  switch (requirement) {
    case OtisBootCapabilityRequirement::Disabled:
      return "disabled";
    case OtisBootCapabilityRequirement::Optional:
      return "optional";
    case OtisBootCapabilityRequirement::Required:
      return "required";
  }
  return "disabled";
}

const char *otis_boot_capability_outcome_name(
    OtisBootCapabilityOutcome outcome) {
  switch (outcome) {
    case OtisBootCapabilityOutcome::Ready:
      return "Ready";
    case OtisBootCapabilityOutcome::OptionalDegraded:
      return "OptionalDegraded";
    case OtisBootCapabilityOutcome::RequiredUnavailable:
      return "RequiredUnavailable";
    case OtisBootCapabilityOutcome::FatalConflict:
      return "FatalConflict";
  }
  return "RequiredUnavailable";
}
