#include <assert.h>
#include <stdint.h>
#include <stdio.h>

#include <set>
#include <string>

namespace {

enum class RequestPhase {
  None,
  PrivateUnreleased,
  ReleasedPending,
  Accepted,
  Applied,
  FirstConsumed,
  ResponsePending,
};

enum class RequestOwner { None, Core1, Core0 };
enum class AppliedPath { Hybrid, FllOnly };

struct RequestIdentity {
  uint32_t request_sequence;
  uint32_t nonce;

  bool operator==(const RequestIdentity &other) const {
    return request_sequence == other.request_sequence && nonce == other.nonce;
  }
};

struct CanonicalSnapshot {
  std::string capture_session;
  uint32_t measurement_frontier;
  uint16_t applied_code;
  uint32_t dac_epoch;
  uint32_t metadata_sequence;
  RequestPhase request_phase;
  RequestOwner request_owner;
  bool metadata_hold;
  bool metadata_loss_pending;
  bool phase_degraded;
  bool phase_loss_pending;
  bool low_efficiency_inhibit;
  bool actuator_provenance_fail_static;

  bool operator==(const CanonicalSnapshot &other) const {
    return capture_session == other.capture_session &&
           measurement_frontier == other.measurement_frontier &&
           applied_code == other.applied_code && dac_epoch == other.dac_epoch &&
           metadata_sequence == other.metadata_sequence &&
           request_phase == other.request_phase &&
           request_owner == other.request_owner &&
           metadata_hold == other.metadata_hold &&
           metadata_loss_pending == other.metadata_loss_pending &&
           phase_degraded == other.phase_degraded &&
           phase_loss_pending == other.phase_loss_pending &&
           low_efficiency_inhibit == other.low_efficiency_inhibit &&
           actuator_provenance_fail_static ==
               other.actuator_provenance_fail_static;
  }
};

struct LowEfficiencyEpisode {
  std::string episode_id;
  std::string policy_id;
  std::string capture_session;
  AppliedPath applied_path;
  uint32_t application_sequence;
  uint32_t first_consumer_frontier;
  uint32_t response_frontier;
  uint32_t exposure_start_frontier;
  uint32_t exposure_end_frontier;
  uint16_t applied_code;
  uint32_t dac_epoch;
  bool actually_applied;
  bool first_consumer_observed;
  bool response_complete;
  bool exposure_complete;
  int frequency_only_integer_request;
  int combined_integer_request;
};

class NonEffectiveOperationalSemantics {
 public:
  static constexpr bool kEffectiveAuthority = false;

  NonEffectiveOperationalSemantics()
      : capture_session_("session-7"),
        measurement_frontier_(100u),
        applied_code_(0xA83Cu),
        dac_epoch_(4u),
        metadata_sequence_(20u),
        gnss_metadata_qualified_(true),
        metadata_hold_(false),
        metadata_loss_pending_(false),
        phase_degraded_(false),
        phase_loss_pending_(false),
        low_efficiency_inhibit_(false),
        actuator_provenance_fail_static_(false),
        current_phase_epoch_("phase-7"),
        retired_phase_epochs_(),
        phase_frontier_(100u),
        request_phase_(RequestPhase::None),
        request_owner_(RequestOwner::None),
        request_identity_{0u, 0u},
        application_sequence_(0u),
        first_consumer_sequence_(0u),
        response_sequence_(0u),
        first_consumer_evidence_frontier_(0u),
        response_evidence_frontier_(0u),
        last_completed_application_sequence_(0u),
        last_completed_first_consumer_frontier_(0u),
        last_completed_response_frontier_(0u),
        last_completed_request_identity_{0u, 0u},
        last_completed_outcome_("none"),
        completed_fll_episode_count_(0u),
        last_fll_exposure_end_(0u),
        d9_output_valid_(true),
        d9_reason_("valid"),
        d6_status_("healthy"),
        d10_status_("healthy"),
        shadow_status_("disabled") {}

  bool effective_actuation_permitted() const { return kEffectiveAuthority; }

  bool logical_rearm_eligible() const {
    return gnss_metadata_qualified_ && !metadata_hold_ &&
           !metadata_loss_pending_ && !phase_loss_pending_ &&
           !low_efficiency_inhibit_ &&
           !actuator_provenance_fail_static_ &&
           request_phase_ == RequestPhase::None;
  }

  bool delivered_output_trial_eligible() const { return d9_output_valid_; }

  CanonicalSnapshot canonical() const {
    return {capture_session_,
            measurement_frontier_,
            applied_code_,
            dac_epoch_,
            metadata_sequence_,
            request_phase_,
            request_owner_,
            metadata_hold_,
            metadata_loss_pending_,
            phase_degraded_,
            phase_loss_pending_,
            low_efficiency_inhibit_,
            actuator_provenance_fail_static_};
  }

  bool begin_private_request(const RequestIdentity &identity) {
    if (!logical_rearm_eligible() ||
        identity.request_sequence == 0u || identity.nonce == 0u) {
      return false;
    }
    request_identity_ = identity;
    request_phase_ = RequestPhase::PrivateUnreleased;
    request_owner_ = RequestOwner::Core1;
    return true;
  }

  bool release_request(const RequestIdentity &identity) {
    if (!exact_request(identity) ||
        request_phase_ != RequestPhase::PrivateUnreleased ||
        request_owner_ != RequestOwner::Core1) {
      fail_static();
      return false;
    }
    request_phase_ = RequestPhase::ReleasedPending;
    request_owner_ = RequestOwner::Core0;
    return true;
  }

  void lose_metadata() {
    gnss_metadata_qualified_ = false;
    if (request_phase_ == RequestPhase::None) {
      metadata_hold_ = true;
      return;
    }
    if (request_phase_ == RequestPhase::PrivateUnreleased &&
        request_owner_ == RequestOwner::Core1) {
      clear_request();
      metadata_hold_ = true;
      return;
    }
    if (request_owner_ != RequestOwner::Core0) {
      fail_static();
      return;
    }
    metadata_loss_pending_ = true;
  }

  bool accept_request(const RequestIdentity &identity) {
    if (!exact_request(identity) ||
        request_phase_ != RequestPhase::ReleasedPending ||
        request_owner_ != RequestOwner::Core0) {
      fail_static();
      return false;
    }
    request_phase_ = RequestPhase::Accepted;
    return true;
  }

  bool apply_request(const RequestIdentity &identity, uint16_t code,
                     uint32_t dac_epoch, uint32_t application_sequence) {
    if (!exact_request(identity) || request_phase_ != RequestPhase::Accepted ||
        request_owner_ != RequestOwner::Core0 || code < 0xA800u ||
        code > 0xAB00u || dac_epoch <= dac_epoch_ ||
        application_sequence <= last_completed_application_sequence_) {
      fail_static();
      return false;
    }
    applied_code_ = code;
    dac_epoch_ = dac_epoch;
    application_sequence_ = application_sequence;
    request_phase_ = RequestPhase::Applied;
    return true;
  }

  bool observe_first_consumer(const RequestIdentity &identity, uint16_t code,
                              uint32_t dac_epoch,
                              uint32_t first_consumer_sequence,
                              uint32_t evidence_frontier) {
    if (!exact_request(identity) || request_phase_ != RequestPhase::Applied ||
        request_owner_ != RequestOwner::Core0 || code != applied_code_ ||
        dac_epoch != dac_epoch_ ||
        first_consumer_sequence <= application_sequence_ ||
        evidence_frontier <= measurement_frontier_) {
      fail_static();
      return false;
    }
    first_consumer_sequence_ = first_consumer_sequence;
    first_consumer_evidence_frontier_ = evidence_frontier;
    measurement_frontier_ = evidence_frontier;
    request_phase_ = RequestPhase::FirstConsumed;
    return true;
  }

  bool begin_response(const RequestIdentity &identity) {
    if (!exact_request(identity) ||
        request_phase_ != RequestPhase::FirstConsumed ||
        request_owner_ != RequestOwner::Core0) {
      fail_static();
      return false;
    }
    request_phase_ = RequestPhase::ResponsePending;
    return true;
  }

  bool complete_response(const RequestIdentity &identity,
                         uint32_t response_sequence,
                         uint32_t evidence_frontier) {
    if (!exact_request(identity) ||
        request_phase_ != RequestPhase::ResponsePending ||
        request_owner_ != RequestOwner::Core0 ||
        response_sequence <= first_consumer_sequence_ ||
        evidence_frontier <= measurement_frontier_) {
      fail_static();
      return false;
    }
    response_sequence_ = response_sequence;
    response_evidence_frontier_ = evidence_frontier;
    measurement_frontier_ = evidence_frontier;
    last_completed_application_sequence_ = application_sequence_;
    last_completed_first_consumer_frontier_ = first_consumer_evidence_frontier_;
    last_completed_response_frontier_ = response_evidence_frontier_;
    last_completed_request_identity_ = request_identity_;
    last_completed_outcome_ = "accepted_applied_response_complete";
    clear_request();
    if (metadata_loss_pending_) {
      metadata_loss_pending_ = false;
      metadata_hold_ = true;
    }
    resolve_phase_loss_if_possible();
    return true;
  }

  bool reject_or_expire_request(const RequestIdentity &identity) {
    if (!exact_request(identity) ||
        request_phase_ != RequestPhase::ReleasedPending ||
        request_owner_ != RequestOwner::Core0) {
      fail_static();
      return false;
    }
    last_completed_request_identity_ = request_identity_;
    last_completed_outcome_ = "rejected_or_expired";
    clear_request();
    if (metadata_loss_pending_) {
      metadata_loss_pending_ = false;
      metadata_hold_ = true;
    }
    resolve_phase_loss_if_possible();
    return true;
  }

  void lose_phase() {
    if (phase_degraded_) {
      return;
    }
    if (request_phase_ == RequestPhase::None) {
      enter_phase_degraded();
      return;
    }
    phase_loss_pending_ = true;
  }

  bool open_new_phase_epoch(const std::string &phase_epoch,
                            uint32_t phase_frontier) {
    if (absorbing() || !phase_degraded_ || phase_epoch.empty() ||
        retired_phase_epochs_.count(phase_epoch) != 0u ||
        phase_frontier <= measurement_frontier_) {
      return false;
    }
    current_phase_epoch_ = phase_epoch;
    phase_frontier_ = phase_frontier;
    measurement_frontier_ = phase_frontier;
    phase_degraded_ = false;
    return true;
  }

  bool requalify_metadata(uint32_t metadata_sequence,
                          uint32_t metadata_qualification_frontier,
                          uint32_t post_metadata_d14_d8_frontier,
                          const std::string &capture_session,
                          uint16_t applied_code, uint32_t dac_epoch) {
    if (absorbing() || !metadata_hold_) {
      return false;
    }
    if (dac_epoch < dac_epoch_) {
      return false;
    }
    if (capture_session != capture_session_ || dac_epoch != dac_epoch_ ||
        applied_code != applied_code_) {
      fail_static();
      return false;
    }
    if (metadata_sequence <= metadata_sequence_ ||
        metadata_qualification_frontier < measurement_frontier_ ||
        post_metadata_d14_d8_frontier <= metadata_qualification_frontier) {
      return false;
    }
    metadata_sequence_ = metadata_sequence;
    measurement_frontier_ = post_metadata_d14_d8_frontier;
    gnss_metadata_qualified_ = true;
    metadata_hold_ = false;
    return true;
  }

  bool record_fll_low_efficiency(const LowEfficiencyEpisode &episode) {
    if (absorbing() || episode.episode_id.empty() ||
        episode.policy_id != "CX322_BOUNDED_HYBRID_FACT_GATHERING_V1" ||
        episode.capture_session != capture_session_ ||
        episode.applied_path != AppliedPath::FllOnly ||
        episode.application_sequence != last_completed_application_sequence_ ||
        episode.first_consumer_frontier !=
            last_completed_first_consumer_frontier_ ||
        episode.response_frontier != last_completed_response_frontier_ ||
        episode.applied_code != applied_code_ || episode.dac_epoch != dac_epoch_ ||
        !episode.actually_applied || !episode.first_consumer_observed ||
        !episode.response_complete || !episode.exposure_complete ||
        episode.first_consumer_frontier >= episode.response_frontier ||
        episode.response_frontier < episode.exposure_start_frontier ||
        episode.response_frontier > episode.exposure_end_frontier ||
        episode.frequency_only_integer_request !=
            episode.combined_integer_request ||
        episode.exposure_start_frontier <= last_fll_exposure_end_ ||
        episode.exposure_end_frontier <= episode.exposure_start_frontier ||
        completed_episode_ids_.count(episode.episode_id) != 0u) {
      return false;
    }
    completed_episode_ids_.insert(episode.episode_id);
    last_fll_exposure_end_ = episode.exposure_end_frontier;
    ++completed_fll_episode_count_;
    if (completed_fll_episode_count_ >= 2u) {
      low_efficiency_inhibit_ = true;
    }
    return true;
  }

  bool retain_completed_transaction_for_replay(
      uint32_t application_sequence, uint32_t first_consumer_frontier,
      uint32_t response_frontier, uint16_t applied_code, uint32_t dac_epoch) {
    if (absorbing() || request_phase_ != RequestPhase::None ||
        application_sequence <= last_completed_application_sequence_ ||
        first_consumer_frontier >= response_frontier ||
        applied_code != applied_code_ || dac_epoch != dac_epoch_) {
      return false;
    }
    last_completed_application_sequence_ = application_sequence;
    last_completed_first_consumer_frontier_ = first_consumer_frontier;
    last_completed_response_frontier_ = response_frontier;
    return true;
  }

  void set_d9_output_status(bool valid, const std::string &reason) {
    d9_output_valid_ = valid;
    d9_reason_ = reason;
  }
  void set_d6_status(const std::string &status) { d6_status_ = status; }
  void set_d10_status(const std::string &status) { d10_status_ = status; }
  void set_shadow_status(const std::string &status) {
    shadow_status_ = status;
  }

  RequestPhase request_phase() const { return request_phase_; }
  RequestOwner request_owner() const { return request_owner_; }
  bool metadata_hold() const { return metadata_hold_; }
  bool metadata_loss_pending() const { return metadata_loss_pending_; }
  bool phase_degraded() const { return phase_degraded_; }
  bool phase_loss_pending() const { return phase_loss_pending_; }
  bool low_efficiency_inhibit() const { return low_efficiency_inhibit_; }
  bool fail_static_latched() const {
    return actuator_provenance_fail_static_;
  }
  uint16_t applied_code() const { return applied_code_; }
  uint32_t dac_epoch() const { return dac_epoch_; }
  uint32_t completed_fll_episode_count() const {
    return completed_fll_episode_count_;
  }
  RequestIdentity last_completed_request_identity() const {
    return last_completed_request_identity_;
  }
  const std::string &last_completed_outcome() const {
    return last_completed_outcome_;
  }

 private:
  bool absorbing() const {
    return low_efficiency_inhibit_ || actuator_provenance_fail_static_;
  }

  bool exact_request(const RequestIdentity &identity) const {
    return request_phase_ != RequestPhase::None &&
           request_identity_ == identity;
  }

  void clear_request() {
    request_phase_ = RequestPhase::None;
    request_owner_ = RequestOwner::None;
    request_identity_ = {0u, 0u};
    application_sequence_ = 0u;
    first_consumer_sequence_ = 0u;
  }

  void fail_static() {
    actuator_provenance_fail_static_ = true;
  }

  void enter_phase_degraded() {
    retired_phase_epochs_.insert(current_phase_epoch_);
    current_phase_epoch_.clear();
    phase_frontier_ = 0u;
    phase_loss_pending_ = false;
    phase_degraded_ = true;
  }

  void resolve_phase_loss_if_possible() {
    if (phase_loss_pending_ && request_phase_ == RequestPhase::None) {
      enter_phase_degraded();
    }
  }

  std::string capture_session_;
  uint32_t measurement_frontier_;
  uint16_t applied_code_;
  uint32_t dac_epoch_;
  uint32_t metadata_sequence_;
  bool gnss_metadata_qualified_;
  bool metadata_hold_;
  bool metadata_loss_pending_;
  bool phase_degraded_;
  bool phase_loss_pending_;
  bool low_efficiency_inhibit_;
  bool actuator_provenance_fail_static_;
  std::string current_phase_epoch_;
  std::set<std::string> retired_phase_epochs_;
  uint32_t phase_frontier_;
  RequestPhase request_phase_;
  RequestOwner request_owner_;
  RequestIdentity request_identity_;
  uint32_t application_sequence_;
  uint32_t first_consumer_sequence_;
  uint32_t response_sequence_;
  uint32_t first_consumer_evidence_frontier_;
  uint32_t response_evidence_frontier_;
  uint32_t last_completed_application_sequence_;
  uint32_t last_completed_first_consumer_frontier_;
  uint32_t last_completed_response_frontier_;
  RequestIdentity last_completed_request_identity_;
  std::string last_completed_outcome_;
  uint32_t completed_fll_episode_count_;
  uint32_t last_fll_exposure_end_;
  std::set<std::string> completed_episode_ids_;
  bool d9_output_valid_;
  std::string d9_reason_;
  std::string d6_status_;
  std::string d10_status_;
  std::string shadow_status_;
};

void verify_metadata_acceptance_phase_latch_and_zero_authority() {
  NonEffectiveOperationalSemantics state;
  const RequestIdentity request = {31u, 0xC322u};
  assert(state.begin_private_request(request));
  assert(state.request_owner() == RequestOwner::Core1);
  assert(state.release_request(request));
  assert(state.request_owner() == RequestOwner::Core0);

  state.lose_metadata();
  state.lose_phase();
  assert(state.metadata_loss_pending());
  assert(state.phase_loss_pending());
  assert(!state.logical_rearm_eligible());
  assert(!state.effective_actuation_permitted());

  assert(state.accept_request(request));
  assert(state.apply_request(request, 0xA83Du, 5u, 40u));
  assert(state.applied_code() == 0xA83Du);
  assert(state.dac_epoch() == 5u);
  assert(state.observe_first_consumer(request, 0xA83Du, 5u, 41u, 101u));
  assert(state.begin_response(request));
  assert(state.complete_response(request, 42u, 102u));
  assert(state.request_phase() == RequestPhase::None);
  assert(state.request_owner() == RequestOwner::None);
  assert(state.metadata_hold());
  assert(state.phase_degraded());
  assert(!state.phase_loss_pending());
  assert(state.last_completed_request_identity() == request);
  assert(state.last_completed_outcome() == "accepted_applied_response_complete");
  assert(!state.effective_actuation_permitted());
  assert(!state.begin_private_request({99u, 0xC399u}));
  printf("parity_acceptance_response=mode=GNSS_METADATA_HOLD,code=0x%04X,"
         "dac_epoch=%u,measurement_frontier=102,phase_degraded=true,"
         "effective=false\n",
         state.applied_code(), state.dac_epoch());

  assert(!state.open_new_phase_epoch("phase-7", 103u));
  assert(state.requalify_metadata(21u, 103u, 104u, "session-7", 0xA83Du,
                                  5u));
  assert(state.logical_rearm_eligible());
  assert(state.open_new_phase_epoch("phase-8", 105u));
  assert(state.logical_rearm_eligible());
  assert(!state.effective_actuation_permitted());
  printf("parity_requalified=mode=ACTIVE,code=0x%04X,dac_epoch=%u,"
         "measurement_frontier=105,control_rearm=true,effective=false\n",
         state.applied_code(), state.dac_epoch());
}

void verify_private_withdrawal_and_absorbing_states() {
  NonEffectiveOperationalSemantics private_state;
  const RequestIdentity private_request = {32u, 0xC323u};
  assert(private_state.begin_private_request(private_request));
  private_state.lose_metadata();
  assert(private_state.request_phase() == RequestPhase::None);
  assert(private_state.request_owner() == RequestOwner::None);
  assert(private_state.metadata_hold());
  assert(!private_state.effective_actuation_permitted());

  NonEffectiveOperationalSemantics inhibited;
  assert(inhibited.retain_completed_transaction_for_replay(1u, 108u, 109u,
                                                            0xA83Cu, 4u));
  const LowEfficiencyEpisode first = {
      "fll-1", "CX322_BOUNDED_HYBRID_FACT_GATHERING_V1", "session-7",
      AppliedPath::FllOnly, 1u, 108u, 109u, 109u, 110u, 0xA83Cu, 4u,
      true, true, true, true, 2, 2};
  const LowEfficiencyEpisode overlap = {
      "fll-overlap", "CX322_BOUNDED_HYBRID_FACT_GATHERING_V1", "session-7",
      AppliedPath::FllOnly, 2u, 109u, 110u, 110u, 111u, 0xA83Cu, 4u,
      true, true, true, true, 2, 2};
  const LowEfficiencyEpisode hybrid = {
      "hybrid", "CX322_BOUNDED_HYBRID_FACT_GATHERING_V1", "session-7",
      AppliedPath::Hybrid, 2u, 109u, 110u, 110u, 120u, 0xA83Cu, 4u,
      true, true, true, true, 2, 2};
  const LowEfficiencyEpisode second = {
      "fll-2", "CX322_BOUNDED_HYBRID_FACT_GATHERING_V1", "session-7",
      AppliedPath::FllOnly, 3u, 119u, 120u, 120u, 121u, 0xA83Cu, 4u,
      true, true, true, true, 2, 2};
  assert(inhibited.record_fll_low_efficiency(first));
  assert(inhibited.retain_completed_transaction_for_replay(2u, 109u, 110u,
                                                            0xA83Cu, 4u));
  assert(!inhibited.record_fll_low_efficiency(overlap));
  assert(!inhibited.record_fll_low_efficiency(hybrid));
  assert(inhibited.retain_completed_transaction_for_replay(3u, 119u, 120u,
                                                            0xA83Cu, 4u));
  assert(inhibited.completed_fll_episode_count() == 1u);
  assert(inhibited.record_fll_low_efficiency(second));
  assert(inhibited.completed_fll_episode_count() == 2u);
  assert(inhibited.low_efficiency_inhibit());
  inhibited.lose_metadata();
  assert(!inhibited.requalify_metadata(21u, 101u, 102u, "session-7",
                                       0xA83Cu, 4u));
  assert(inhibited.low_efficiency_inhibit());
  assert(!inhibited.effective_actuation_permitted());

  NonEffectiveOperationalSemantics failed;
  const RequestIdentity exact = {33u, 0xC324u};
  const RequestIdentity contradictory = {33u, 0xC325u};
  assert(failed.begin_private_request(exact));
  assert(!failed.release_request(contradictory));
  assert(failed.fail_static_latched());
  failed.lose_metadata();
  assert(!failed.requalify_metadata(21u, 101u, 102u, "session-7", 0xA83Cu,
                                    4u));
  assert(failed.fail_static_latched());
  assert(!failed.effective_actuation_permitted());
}

void verify_delivered_output_and_optional_evidence_isolation() {
  NonEffectiveOperationalSemantics state;
  const CanonicalSnapshot before = state.canonical();
  const bool rearm_before = state.logical_rearm_eligible();

  state.set_d9_output_status(false, "waveform_evidence_incomplete");
  state.set_d6_status("overflow");
  state.set_d10_status("queue_failure");
  state.set_shadow_status("stalled_output_drop_model_infeasible");

  assert(state.canonical() == before);
  assert(state.logical_rearm_eligible() == rearm_before);
  assert(!state.delivered_output_trial_eligible());
  assert(!state.effective_actuation_permitted());
  state.lose_phase();
  assert(state.phase_degraded());
  assert(!state.open_new_phase_epoch("phase-7", 106u));
  assert(state.open_new_phase_epoch("phase-8", 106u));
  state.lose_phase();
  assert(state.phase_degraded());
  assert(!state.open_new_phase_epoch("phase-7", 107u));
  assert(!state.open_new_phase_epoch("phase-8", 107u));
  assert(state.open_new_phase_epoch("phase-9", 107u));
}

void verify_stale_applied_identity_is_not_a_contradiction() {
  NonEffectiveOperationalSemantics stale;
  stale.lose_metadata();
  assert(stale.metadata_hold());
  assert(!stale.requalify_metadata(21u, 101u, 102u, "session-7", 0xA83Cu,
                                   3u));
  assert(!stale.fail_static_latched());
  assert(!stale.requalify_metadata(21u, 101u, 102u, "session-7", 0xA83Du,
                                   4u));
  assert(stale.fail_static_latched());
}

void verify_native_application_guards() {
  NonEffectiveOperationalSemantics outside;
  const RequestIdentity outside_request = {40u, 0xC340u};
  assert(outside.begin_private_request(outside_request));
  assert(outside.release_request(outside_request));
  assert(outside.accept_request(outside_request));
  assert(!outside.apply_request(outside_request, 0xA700u, 5u, 1u));
  assert(outside.fail_static_latched());

  NonEffectiveOperationalSemantics backwards;
  assert(backwards.retain_completed_transaction_for_replay(5u, 101u, 102u,
                                                            0xA83Cu, 4u));
  const RequestIdentity backwards_request = {41u, 0xC341u};
  assert(backwards.begin_private_request(backwards_request));
  assert(backwards.release_request(backwards_request));
  assert(backwards.accept_request(backwards_request));
  assert(!backwards.apply_request(backwards_request, 0xA83Du, 5u, 5u));
  assert(backwards.fail_static_latched());
}

}  // namespace

int main() {
  verify_metadata_acceptance_phase_latch_and_zero_authority();
  verify_private_withdrawal_and_absorbing_states();
  verify_delivered_output_and_optional_evidence_isolation();
  verify_stale_applied_identity_is_not_a_contradiction();
  verify_native_application_guards();
  puts("terminal=non_effective_semantics_verified_promotion_blocked_by_d9_gate");
  puts("native_cases=metadata_acceptance_phase_latch,absorbing_states,fll_independence,optional_isolation,stale_identity,application_guards");
  return 0;
}
