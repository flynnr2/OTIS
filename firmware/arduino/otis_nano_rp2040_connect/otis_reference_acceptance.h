#ifndef OTIS_REFERENCE_ACCEPTANCE_H
#define OTIS_REFERENCE_ACCEPTANCE_H

#include <stdint.h>

// Pure reference selection. The caller supplies the frozen policy; this
// module performs no capture, I/O, or actuator operation.
struct OtisReferenceAcceptancePolicy {
  uint32_t nominal_interval_ticks;
  uint32_t tolerance_ticks;
  uint32_t acquisition_intervals;
  uint32_t maximum_edge_rate_hz;
  uint32_t allowed_reference_flags;
  uint32_t maximum_excluded_candidates_per_span;
  uint32_t maximum_count_span_ticks;
};

// A *paired* D14 / cumulative D8 observation, after physical association.
// Timestamp domain: rp2040_monotonic_us32, 1 MHz, modular uint32.
// SNP and D14 source ordinals: independent modular uint32 (not REF event_seq).
// D8: cumulative PIO uint32 downcounter. No raw CNT validity is substituted for
// reconstruction: a short adjacent raw aperture may be inside a valid span.
struct OtisReferenceAcceptanceObservation {
  uint32_t capture_session;
  uint32_t snapshot_sequence;
  uint32_t reference_sequence;
  uint32_t reference_timestamp_ticks;
  uint32_t cumulative_down_counter;
  uint32_t snapshot_status;
  uint32_t reference_flags;
};

// A producer/association frontier, not a CPU-service timestamp. The caller
// proves there is no unconsumed D14/SNP at or before drained_through_ticks.
// The consumed ordinals must match the kernel's most recent observation.
struct OtisReferenceAcceptanceDrainFrontier {
  uint32_t capture_session;
  uint32_t snapshot_sequence;
  uint32_t reference_sequence;
  uint32_t drained_through_ticks;
  bool complete;
};

enum class OtisReferenceAcceptanceDisposition {
  Seeded, Acquiring, TrackingEstablished, EarlyExcluded, AcceptedSpan,
  QualificationLost, ExpiryPending, FrontierRejected, NotTracking,
  InvalidPolicy
};

enum class OtisReferenceAcceptanceReason {
  None, AcquisitionRestart, UnknownSession, SessionChanged, CaptureIntegrity,
  RawSequence, RawTimestamp, RawCount, LateBoundary, MissingBoundary,
  IncompleteFrontier, StaleFrontier, ContradictoryFrontier,
  ExclusionBudgetExhausted, EpochExhausted, ObservationAgeAmbiguous, Policy
};

struct OtisReferenceAcceptanceOutcome {
  OtisReferenceAcceptanceDisposition disposition;
  OtisReferenceAcceptanceReason reason;
  bool tracking;
  bool has_span;
  uint32_t acquisition_progress;
  // Epoch is nonwrapping; accepted ordinal is modular. Neither is a raw ordinal.
  uint32_t acceptance_epoch;
  uint32_t accepted_boundary_ordinal;
  uint32_t expiry_timestamp_ticks;
  OtisReferenceAcceptanceObservation candidate;
  OtisReferenceAcceptanceObservation opening;
  OtisReferenceAcceptanceObservation closing;
  uint32_t interval_ticks;
  uint32_t counted_edges;
  uint32_t excluded_candidate_count;
};

class OtisReferenceAcceptance {
 public:
  explicit OtisReferenceAcceptance(const OtisReferenceAcceptancePolicy &policy)
      : policy_(policy) {}

  OtisReferenceAcceptanceOutcome observe(
      const OtisReferenceAcceptanceObservation &candidate) {
    OtisReferenceAcceptanceOutcome result = observe_candidate(candidate);
    result.candidate = candidate;
    return result;
  }

 private:
  OtisReferenceAcceptanceOutcome observe_candidate(
      const OtisReferenceAcceptanceObservation &candidate) {
    if (!valid_policy()) return outcome(Disposition::InvalidPolicy, Reason::Policy);
    if (candidate.capture_session == 0u) return lose(Reason::UnknownSession);
    if (candidate.snapshot_status != 0u ||
        (candidate.reference_flags & ~policy_.allowed_reference_flags) != 0u)
      return lose(Reason::CaptureIntegrity);
    if (!have_raw_) {
      if (!seed(candidate)) return lose(Reason::EpochExhausted);
      return outcome(Disposition::Seeded);
    }
    if (candidate.capture_session != last_raw_.capture_session) {
      if (!seed(candidate)) return lose(Reason::EpochExhausted);
      return outcome(Disposition::QualificationLost, Reason::SessionChanged);
    }
    if (candidate.snapshot_sequence != uint32_t(last_raw_.snapshot_sequence + 1u) ||
        candidate.reference_sequence != uint32_t(last_raw_.reference_sequence + 1u))
      return lose(Reason::RawSequence);
    const uint32_t raw_ticks = candidate.reference_timestamp_ticks -
                               last_raw_.reference_timestamp_ticks;
    if (raw_ticks == 0u || raw_ticks >= kHalfRange)
      return lose(Reason::RawTimestamp);
    const uint32_t accepted_ticks = candidate.reference_timestamp_ticks -
                                    anchor_.reference_timestamp_ticks;
    // A late candidate starts acquisition; it never becomes a putative
    // multi-second measurement whose counter residue we attempt to validate.
    if (tracking_ && accepted_ticks > upper_ticks()) {
      if (!seed(candidate)) return lose(Reason::EpochExhausted);
      return outcome(Disposition::QualificationLost, Reason::LateBoundary);
    }
    if (!tracking_ && (raw_ticks < lower_ticks() || raw_ticks > upper_ticks())) {
      if (!seed(candidate)) return lose(Reason::EpochExhausted);
      return outcome(Disposition::Seeded, Reason::AcquisitionRestart);
    }
    const uint32_t raw_edges = last_raw_.cumulative_down_counter -
                               candidate.cumulative_down_counter;
    // This is the frozen gross count bound, not an inference of exact physical
    // gate duration from short IRQ/local-timer intervals. Zero is a legitimate
    // residue between closely spaced raw candidates with no intervening D8 edge.
    if (raw_edges > maximum_edges() || (!tracking_ && raw_edges == 0u))
      return lose(Reason::RawCount);
    last_raw_ = candidate;
    if (!tracking_) {
      ++progress_;
      if (progress_ == policy_.acquisition_intervals) {
        tracking_ = true;
        anchor_ = candidate;
        accepted_ordinal_ = 0u;
        return outcome(Disposition::TrackingEstablished);
      }
      return outcome(Disposition::Acquiring);
    }
    span_edges_ += raw_edges;
    if (span_edges_ > maximum_edges()) return lose(Reason::RawCount);
    if (accepted_ticks < lower_ticks()) {
      if (excluded_ == policy_.maximum_excluded_candidates_per_span)
        return lose(Reason::ExclusionBudgetExhausted);
      ++excluded_;
      return outcome(Disposition::EarlyExcluded);
    }
    const uint32_t endpoint_edges = anchor_.cumulative_down_counter -
                                    candidate.cumulative_down_counter;
    // Compact excluded-source proof: the separately emitted EarlyExcluded
    // outcomes name each raw candidate, and this range binds precisely those
    // contiguous rows without copying an array into every accepted result.
    if (uint32_t(candidate.snapshot_sequence - anchor_.snapshot_sequence) != excluded_ + 1u ||
        uint32_t(candidate.reference_sequence - anchor_.reference_sequence) != excluded_ + 1u)
      return lose(Reason::RawSequence);
    if (endpoint_edges == 0u || span_edges_ != endpoint_edges)
      return lose(Reason::RawCount);
    OtisReferenceAcceptanceOutcome result = outcome(Disposition::AcceptedSpan);
    result.has_span = true;
    result.opening = anchor_;
    result.closing = candidate;
    result.interval_ticks = accepted_ticks;
    result.counted_edges = endpoint_edges;
    result.excluded_candidate_count = excluded_;
    result.accepted_boundary_ordinal = ++accepted_ordinal_;
    anchor_ = candidate;
    span_edges_ = 0u;
    excluded_ = 0u;
    result.expiry_timestamp_ticks = anchor_.reference_timestamp_ticks + upper_ticks();
    return result;
  }

 public:
  // An independently established association/coordinate defect withdraws this
  // model's qualification. It does not modify the canonical observation or
  // assert that a physical reference edge was absent.
  OtisReferenceAcceptanceOutcome invalidate(OtisReferenceAcceptanceReason reason) {
    return lose(reason);
  }

  OtisReferenceAcceptanceOutcome expire(
      uint32_t now_ticks, const OtisReferenceAcceptanceDrainFrontier &frontier) {
    if (!valid_policy()) return outcome(Disposition::InvalidPolicy, Reason::Policy);
    if (!tracking_) return outcome(Disposition::NotTracking);
    if (!frontier.complete)
      return outcome(Disposition::ExpiryPending, Reason::IncompleteFrontier);
    if (frontier.capture_session != last_raw_.capture_session)
      return outcome(Disposition::FrontierRejected, Reason::ContradictoryFrontier);
    const uint32_t snp_delta = frontier.snapshot_sequence - last_raw_.snapshot_sequence;
    const uint32_t ref_delta = frontier.reference_sequence - last_raw_.reference_sequence;
    if (snp_delta != 0u || ref_delta != 0u) {
      // A stale equally displaced pair proves no absence. A future, half-range
      // ambiguous, or differently displaced pair contradicts consumed identity.
      if (snp_delta == ref_delta && snp_delta > kHalfRange)
        return outcome(Disposition::ExpiryPending, Reason::StaleFrontier);
      return outcome(Disposition::FrontierRejected, Reason::ContradictoryFrontier);
    }
    const uint32_t now_since_raw = now_ticks - last_raw_.reference_timestamp_ticks;
    const uint32_t drain_since_raw = frontier.drained_through_ticks -
                                     last_raw_.reference_timestamp_ticks;
    if (now_since_raw >= kHalfRange)
      return outcome(Disposition::FrontierRejected, Reason::ContradictoryFrontier);
    if (drain_since_raw >= kHalfRange)
      return outcome(Disposition::ExpiryPending, Reason::StaleFrontier);
    if (drain_since_raw > now_since_raw)
      return outcome(Disposition::FrontierRejected, Reason::ContradictoryFrontier);
    const uint32_t drain_since_anchor = frontier.drained_through_ticks -
                                        anchor_.reference_timestamp_ticks;
    if (drain_since_anchor >= kHalfRange)
      return outcome(Disposition::FrontierRejected, Reason::ContradictoryFrontier);
    // Inclusive admission: the upper endpoint is still a legal captured edge.
    if (drain_since_anchor <= upper_ticks())
      return outcome(Disposition::ExpiryPending, Reason::StaleFrontier);
    return lose(Reason::MissingBoundary);
  }

 private:
  using Disposition = OtisReferenceAcceptanceDisposition;
  using Reason = OtisReferenceAcceptanceReason;
  static constexpr uint32_t kHalfRange = uint32_t(1) << 31;
  static constexpr uint64_t kCounterModulus = uint64_t(1) << 32;
  static constexpr uint32_t kTicksPerSecond = 1000000u;
  const OtisReferenceAcceptancePolicy policy_;
  bool have_raw_ = false;
  bool tracking_ = false;
  uint32_t progress_ = 0u;
  uint32_t epoch_ = 0u;
  uint32_t accepted_ordinal_ = 0u;
  uint64_t span_edges_ = 0u;
  uint32_t excluded_ = 0u;
  OtisReferenceAcceptanceObservation last_raw_ = {};
  OtisReferenceAcceptanceObservation anchor_ = {};

  uint32_t lower_ticks() const { return policy_.nominal_interval_ticks - policy_.tolerance_ticks; }
  uint32_t upper_ticks() const { return policy_.nominal_interval_ticks + policy_.tolerance_ticks; }
  uint64_t maximum_edges() const {
    return uint64_t(policy_.maximum_edge_rate_hz) * policy_.maximum_count_span_ticks / kTicksPerSecond;
  }
  bool valid_policy() const {
    return policy_.nominal_interval_ticks > policy_.tolerance_ticks &&
           uint64_t(policy_.nominal_interval_ticks) + policy_.tolerance_ticks < kHalfRange &&
           policy_.acquisition_intervals != 0u && policy_.maximum_edge_rate_hz != 0u &&
           policy_.maximum_count_span_ticks >= upper_ticks() &&
           maximum_edges() > 0u && maximum_edges() < kCounterModulus;
  }
  bool seed(const OtisReferenceAcceptanceObservation &candidate) {
    if (epoch_ == UINT32_MAX) return false;
    have_raw_ = true;
    tracking_ = false;
    progress_ = 0u;
    ++epoch_;
    accepted_ordinal_ = 0u;
    span_edges_ = 0u;
    excluded_ = 0u;
    last_raw_ = candidate;
    anchor_ = candidate;
    return true;
  }
  OtisReferenceAcceptanceOutcome lose(Reason reason) {
    have_raw_ = false;
    tracking_ = false;
    progress_ = 0u;
    span_edges_ = 0u;
    excluded_ = 0u;
    return outcome(Disposition::QualificationLost, reason);
  }
  OtisReferenceAcceptanceOutcome outcome(Disposition disposition, Reason reason = Reason::None) const {
    OtisReferenceAcceptanceOutcome result = {};
    result.disposition = disposition;
    result.reason = reason;
    result.tracking = tracking_;
    result.acquisition_progress = progress_;
    result.acceptance_epoch = epoch_;
    result.accepted_boundary_ordinal = accepted_ordinal_;
    result.expiry_timestamp_ticks = have_raw_ ? anchor_.reference_timestamp_ticks + upper_ticks() : 0u;
    result.opening = anchor_;
    result.closing = last_raw_;
    result.excluded_candidate_count = excluded_;
    return result;
  }
};

#endif
