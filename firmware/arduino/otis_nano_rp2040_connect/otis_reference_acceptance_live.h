#ifndef OTIS_REFERENCE_ACCEPTANCE_LIVE_H
#define OTIS_REFERENCE_ACCEPTANCE_LIVE_H

#include "otis_reference_acceptance.h"

inline const char *otis_reference_acceptance_reason_name(OtisReferenceAcceptanceReason reason) {
  using R = OtisReferenceAcceptanceReason;
  switch (reason) {
    case R::None: return "none";
    case R::AcquisitionRestart: return "acquisition_restart";
    case R::UnknownSession: return "unknown_session";
    case R::SessionChanged: return "session_changed";
    case R::CaptureIntegrity: return "capture_integrity";
    case R::RawSequence: return "raw_sequence";
    case R::RawTimestamp: return "raw_timestamp";
    case R::RawCount: return "raw_count";
    case R::LateBoundary: return "late_boundary";
    case R::MissingBoundary: return "missing_boundary";
    case R::IncompleteFrontier: return "incomplete_frontier";
    case R::StaleFrontier: return "stale_frontier";
    case R::ContradictoryFrontier: return "contradictory_frontier";
    case R::ExclusionBudgetExhausted: return "exclusion_budget_exhausted";
    case R::EpochExhausted: return "epoch_exhausted";
    case R::ObservationAgeAmbiguous: return "observation_age_ambiguous";
    case R::Policy: return "policy";
  }
  return "unknown_reason";
}

// Core 1 owns this state. Source coordinates are explicitly projected by the
// caller from the same RP2040 timer into its unsigned 64-bit domain. CPU age
// can withhold authority, but cannot prove physical reference absence.
struct OtisAcceptedReferenceStatus {
  uint32_t capture_session = 0u;
  uint32_t acceptance_epoch = 0u;
  uint32_t accepted_boundary_ordinal = 0u;
  uint32_t anchor_snapshot_sequence = 0u;
  uint32_t anchor_reference_sequence = 0u;
  uint32_t anchor_timestamp_ticks = 0u;
  uint32_t acquisition_progress = 0u;
  uint32_t excluded_candidate_count = 0u;
  uint32_t loss_count = 0u;
  const char *last_loss_reason = "none";
  bool tracking = false;
  bool anchor_current = false;
  const char *state = "unseeded";
};

class OtisReferenceAcceptanceLive {
 public:
  explicit OtisReferenceAcceptanceLive(const OtisReferenceAcceptancePolicy &policy)
      : selector_(policy), upper_ticks_(policy.nominal_interval_ticks + policy.tolerance_ticks) {}

  const OtisAcceptedReferenceStatus &status() const { return status_; }

  OtisReferenceAcceptanceOutcome observe(
      const OtisReferenceAcceptanceObservation &observation,
      uint64_t source_extended_ticks, uint64_t now_ticks,
      uint64_t maximum_observation_age_ticks) {
    const bool coordinate_exact =
        uint32_t(source_extended_ticks) == observation.reference_timestamp_ticks &&
        source_extended_ticks <= now_ticks &&
        now_ticks - source_extended_ticks <= maximum_observation_age_ticks;
    const bool same_session = have_source_ &&
        observation.capture_session == status_.capture_session;
    const bool order_exact = !same_session ||
        (source_extended_ticks > previous_source_ticks_ &&
         source_extended_ticks - previous_source_ticks_ < (uint64_t(1) << 31));
    OtisReferenceAcceptanceOutcome result;
    if (!coordinate_exact || !order_exact) {
      result = selector_.invalidate(
          OtisReferenceAcceptanceReason::ObservationAgeAmbiguous);
      result.candidate = observation;
    } else {
      result = selector_.observe(observation);
    }
    have_source_ = coordinate_exact;
    previous_source_ticks_ = source_extended_ticks;
    status_.capture_session = observation.capture_session;
    update(result, source_extended_ticks);
    service(now_ticks);
    return result;
  }

  OtisReferenceAcceptanceOutcome invalidate(OtisReferenceAcceptanceReason reason) {
    const OtisReferenceAcceptanceOutcome result = selector_.invalidate(reason);
    have_source_ = false;
    update(result, 0u);
    return result;
  }

  void service(uint64_t now_ticks) {
    if (!status_.tracking) return;
    // Once overdue, raw rogue traffic cannot extend this accepted anchor.
    // A later accepted hardware boundary supplies the only replacement.
    expiry_pending_ = expiry_pending_ || now_ticks < anchor_extended_ticks_ ||
        now_ticks - anchor_extended_ticks_ > upper_ticks_;
    status_.anchor_current = !expiry_pending_;
    status_.state = status_.anchor_current ? "tracking" : "expiry_pending";
  }

 private:
  OtisReferenceAcceptance selector_;
  const uint32_t upper_ticks_;
  OtisAcceptedReferenceStatus status_;
  bool have_source_ = false;
  uint64_t previous_source_ticks_ = 0u;
  uint64_t anchor_extended_ticks_ = 0u;
  bool expiry_pending_ = false;

  void update(const OtisReferenceAcceptanceOutcome &result, uint64_t source_ticks) {
    using D = OtisReferenceAcceptanceDisposition;
    status_.acceptance_epoch = result.acceptance_epoch;
    status_.accepted_boundary_ordinal = result.accepted_boundary_ordinal;
    status_.acquisition_progress = result.acquisition_progress;
    status_.excluded_candidate_count = result.excluded_candidate_count;
    status_.tracking = result.tracking;
    if (result.disposition == D::AcceptedSpan ||
        result.disposition == D::TrackingEstablished) {
      const auto &anchor = result.disposition == D::AcceptedSpan ? result.closing : result.candidate;
      status_.anchor_snapshot_sequence = anchor.snapshot_sequence;
      status_.anchor_reference_sequence = anchor.reference_sequence;
      status_.anchor_timestamp_ticks = anchor.reference_timestamp_ticks;
      status_.excluded_candidate_count = 0u;
      anchor_extended_ticks_ = source_ticks;
      expiry_pending_ = false;
    }
    if (result.disposition == D::QualificationLost) {
      if (status_.loss_count != UINT32_MAX) ++status_.loss_count;
      status_.last_loss_reason = otis_reference_acceptance_reason_name(result.reason);
      status_.state = "lost";
    } else if (result.disposition == D::InvalidPolicy) {
      status_.last_loss_reason = otis_reference_acceptance_reason_name(result.reason);
      status_.state = "fault";
    } else if (!result.tracking) {
      status_.state = "acquiring";
    }
    if (!status_.tracking) status_.anchor_current = false;
  }
};

#endif
