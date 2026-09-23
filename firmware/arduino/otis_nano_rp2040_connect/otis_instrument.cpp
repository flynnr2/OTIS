#include "otis_instrument.h"
#include <limits.h>
#include <math.h>
#include <string.h>

namespace {
bool code_valid(uint16_t code) { return code >= 0xA800u && code <= 0xAB00u; }
bool same_write(const OtisInstrumentWrite &a, const OtisInstrumentWrite &b) {
  return a.session == b.session && a.capture_session == b.capture_session &&
      a.sequence == b.sequence && a.dac_epoch == b.dac_epoch && a.prior_code == b.prior_code &&
      a.code == b.code && a.prior_known == b.prior_known &&
      a.kind == b.kind && a.deadline_ticks == b.deadline_ticks;
}
bool same_command(const OtisInstrumentCommand &a, const OtisInstrumentCommand &b) {
  return a.session == b.session && a.sequence == b.sequence &&
      a.mode == b.mode && a.code == b.code && a.dwell_s == b.dwell_s;
}
void add_counter(OtisInstrument *s, uint64_t *value, uint64_t delta) {
  if (UINT64_MAX - *value < delta) { *value = UINT64_MAX; s->counters_saturated = true; }
  else *value += delta;
}
bool advance(OtisInstrument *s, uint64_t ticks) {
  if (ticks < s->now_ticks) { otis_instrument_fault(s, "instrument_clock_backward"); return false; }
  s->now_ticks = ticks;
  return s->fault == nullptr;
}
void incomplete_response(OtisInstrument *s) {
  if (s->engine.response_pending) {
    s->response_incomplete = true;
    s->response_classifier = {};
    s->engine.response_pending = false; // explicit cancellation, never completion
  }
}
void ensure_metadata_hold(OtisInstrument *s) {
  if (s->metadata_hold && s->engine_ready && !s->engine.request_pending &&
      !s->engine.metadata_hold)
    otis_adaptive_hybrid_engine_enter_metadata_hold(&s->engine);
}
void cancel_private(OtisInstrument *s) {
  if (s->write_state != OtisInstrumentWriteState::Proposed) return;
  if (s->write.kind == OtisInstrumentWriteKind::Correction)
    otis_adaptive_hybrid_engine_reject_or_expire_request(&s->engine);
  s->write_state = OtisInstrumentWriteState::Idle;
}
bool propose(OtisInstrument *s, uint16_t code, OtisInstrumentWriteKind kind) {
  if (s->fault || s->write_state != OtisInstrumentWriteState::Idle || !code_valid(code)) return false;
  if (s->next_write_sequence == UINT32_MAX || s->dac_epoch == UINT32_MAX ||
      UINT64_MAX - s->now_ticks < OTIS_INSTRUMENT_WRITE_TIMEOUT_US) {
    otis_instrument_fault(s, "instrument_identity_exhausted"); return false;
  }
  s->write = {s->session, s->capture_session, ++s->next_write_sequence, s->dac_epoch + 1u,
      s->applied_code, code, s->code_known, kind,
      s->now_ticks + OTIS_INSTRUMENT_WRITE_TIMEOUT_US};
  s->write_state = OtisInstrumentWriteState::Proposed;
  s->reason = "write_proposed";
  return true;
}
void enter_requested_mode(OtisInstrument *s) {
  if (s->write_state != OtisInstrumentWriteState::Idle || s->fault) return;
  if (s->mode == s->requested_mode &&
      s->command_completed == s->last_command.sequence) return;
  const uint64_t duration =
      s->requested_mode == OtisInstrumentMode::Auto
          ? uint64_t(s->last_command.dwell_s) * 1000000ull : 0ull;
  if (duration && UINT64_MAX - s->now_ticks < duration) {
    otis_instrument_fault(s, "operating_deadline_overflow");
    return;
  }
  if (s->mode != s->requested_mode) incomplete_response(s);
  s->mode = s->requested_mode;
  s->operating_end_ticks = duration ? s->now_ticks + duration : 0;
  if (s->mode == OtisInstrumentMode::Hold || s->mode == OtisInstrumentMode::Auto) {
    s->characterize_end_ticks = 0;
    s->command_completed = s->last_command.sequence;
    s->reason = s->mode == OtisInstrumentMode::Hold ? "operator_hold" : "acquiring";
  }
}
}

void otis_instrument_fault(OtisInstrument *s, const char *reason) {
  if (s->fault == nullptr) s->fault = reason;
  s->reason = s->fault;
}
void otis_instrument_init(OtisInstrument *s, uint64_t session, uint32_t capture_session, uint64_t ticks) {
  *s = {};
  s->session = session;
  s->capture_session = capture_session;
  s->mode = s->requested_mode = OtisInstrumentMode::Auto;
  s->now_ticks = ticks;
  s->reason = "startup";
  if (!session || !capture_session || !ticks) { otis_instrument_fault(s, "startup_identity_invalid"); return; }
  propose(s, OTIS_INSTRUMENT_START_CODE, OtisInstrumentWriteKind::Startup);
}
void otis_instrument_health(OtisInstrument *s, const OtisInstrumentHealth &health, uint64_t ticks) {
  if (!advance(s, ticks)) return;
  if (health.capture_session != s->capture_session || !health.capture_integrity) {
    otis_instrument_fault(s, "capture_identity_or_integrity"); return;
  }
  const bool epoch_changed = s->health.acceptance_epoch != 0 &&
      s->health.acceptance_epoch != health.acceptance_epoch;
  s->health = health;
  if (!health.reference_qualified || epoch_changed) {
    s->reference_hold = true;
    if (s->write.kind == OtisInstrumentWriteKind::Correction) cancel_private(s);
    incomplete_response(s);
    if (s->engine_ready) {
      s->engine.debt.pll_picocodes = 0;
      s->engine.persistence_count = 0;
      s->engine.persistence_identity_available = false;
    }
    s->reason = "reference_hold";
  } else s->reference_hold = false;
  if (!health.metadata_qualified) {
    if (s->write.kind == OtisInstrumentWriteKind::Correction) cancel_private(s);
    // A response observed across an unqualified metadata interval cannot
    // close the prior correction's causal qualification window.
    incomplete_response(s);
    if (!s->metadata_hold) s->metadata_hold_sequence = health.metadata_sequence;
    s->metadata_hold = true;
    ensure_metadata_hold(s);
    s->reason = "metadata_hold";
  } else if (s->metadata_hold) {
    ensure_metadata_hold(s);
    if (s->engine_ready && !s->engine.request_pending &&
             !s->engine.response_pending && health.reference_qualified &&
             health.metadata_sequence != s->metadata_hold_sequence &&
             (!s->engine.metadata_requalified ||
              s->engine.requalification_acceptance_epoch != health.acceptance_epoch)) {
      otis_adaptive_hybrid_engine_requalify_metadata(&s->engine,
          health.acceptance_epoch, health.accepted_boundary);
    }
  }
}
void otis_instrument_service(OtisInstrument *s, uint64_t ticks) {
  if (!advance(s, ticks)) return;
  if (s->operating_end_ticks && ticks >= s->operating_end_ticks) {
    s->operating_end_ticks = 0;
    s->requested_mode = OtisInstrumentMode::Hold;
    cancel_private(s);
    incomplete_response(s);
  }
  if (s->write_state != OtisInstrumentWriteState::Idle && ticks >= s->write.deadline_ticks) {
    otis_instrument_fault(s, "actuator_or_consumer_deadline"); return;
  }
  if (s->write_state != OtisInstrumentWriteState::Idle) return;
  enter_requested_mode(s);
  if (s->mode == OtisInstrumentMode::Characterize && s->characterize_end_ticks &&
      ticks >= s->characterize_end_ticks) {
    s->requested_mode = OtisInstrumentMode::Hold;
    enter_requested_mode(s);
    s->reason = "characterization_complete";
  }
  if ((s->mode == OtisInstrumentMode::Fixed || s->mode == OtisInstrumentMode::Characterize) &&
      s->command_completed != s->last_command.sequence)
    propose(s, s->target_code, s->mode == OtisInstrumentMode::Fixed ?
        OtisInstrumentWriteKind::Fixed : OtisInstrumentWriteKind::Characterize);
}
OtisInstrumentReceipt otis_instrument_command(OtisInstrument *s, const OtisInstrumentCommand &c, uint64_t ticks) {
  if (!advance(s, ticks) || c.session != s->session || !c.sequence) return OtisInstrumentReceipt::Rejected;
  if (c.sequence == s->last_command.sequence)
    return same_command(c, s->last_command) ? OtisInstrumentReceipt::Duplicate : OtisInstrumentReceipt::Rejected;
  if (c.sequence < s->last_command.sequence || static_cast<unsigned>(c.mode) > 3u)
    return OtisInstrumentReceipt::Rejected;
  const bool writes = c.mode == OtisInstrumentMode::Fixed || c.mode == OtisInstrumentMode::Characterize;
  if ((!writes && c.code) || (writes && !code_valid(c.code)) ||
      ((c.mode == OtisInstrumentMode::Fixed || c.mode == OtisInstrumentMode::Hold) && c.dwell_s) ||
      (c.mode == OtisInstrumentMode::Auto && c.dwell_s > 604800u) ||
      UINT64_MAX - ticks < uint64_t(c.dwell_s)*1000000ull ||
      (c.mode == OtisInstrumentMode::Characterize &&
       (!s->code_known || c.dwell_s == 0 || uint64_t(c.dwell_s)*1000000ull > OTIS_INSTRUMENT_MAX_DWELL_US ||
        c.code > s->applied_code + 21 || c.code + 21 < s->applied_code)))
    return OtisInstrumentReceipt::Rejected;
  // Only HOLD may supersede an unfinished mode command. New mutations otherwise
  // wait for exact completion; this bounds command history to one retained receipt.
  if (s->command_completed != s->last_command.sequence && c.mode != OtisInstrumentMode::Hold)
    return OtisInstrumentReceipt::Rejected;
  s->last_command = c;
  s->requested_mode = c.mode;
  s->target_code = c.code;
  s->characterize_dwell_ticks = uint64_t(c.dwell_s)*1000000ull;
  s->characterize_end_ticks = 0;
  if (s->write.kind != OtisInstrumentWriteKind::Startup) cancel_private(s);
  if (c.mode != OtisInstrumentMode::Auto) incomplete_response(s);
  enter_requested_mode(s);
  s->reason = "mode_accepted";
  return OtisInstrumentReceipt::Accepted;
}
bool otis_instrument_release(OtisInstrument *s, OtisInstrumentWrite *out, uint64_t ticks) {
  otis_instrument_service(s, ticks);
  if (s->fault || !out || s->write_state != OtisInstrumentWriteState::Proposed) return false;
  if (s->write.kind == OtisInstrumentWriteKind::Correction &&
      (s->requested_mode != OtisInstrumentMode::Auto || !s->health.reference_qualified || !s->health.metadata_qualified)) {
    cancel_private(s); return false;
  }
  *out = s->write;
  s->write_state = OtisInstrumentWriteState::Released;
  s->reason = "write_released";
  return true;
}
bool otis_instrument_application(OtisInstrument *s, const OtisInstrumentApplication &a) {
  // Even after fault inhibition, an already released write's exact outcome is
  // a physical fact. Retain it without clearing the first fault.
  if (s->write_state != OtisInstrumentWriteState::Released || !same_write(s->write, a.request) ||
      a.ticks < s->write.deadline_ticks - OTIS_INSTRUMENT_WRITE_TIMEOUT_US) {
    otis_instrument_fault(s, "application_identity_or_deadline"); return false;
  }
  // A deadline violation inhibits future action, but cannot erase an exact
  // observed physical write. Propagate its code/epoch even when it was late.
  if (a.ticks >= s->write.deadline_ticks)
    otis_instrument_fault(s, "application_identity_or_deadline");
  if (a.ticks > s->now_ticks) s->now_ticks = a.ticks;
  if (!a.attempted && !a.ok && a.rejection == OtisInstrumentRejection::QualificationLost &&
      s->write.kind == OtisInstrumentWriteKind::Correction &&
      a.code == s->applied_code && s->code_known) {
    otis_adaptive_hybrid_engine_reject_or_expire_request(&s->engine);
    s->write_state = OtisInstrumentWriteState::Idle;
    ensure_metadata_hold(s);
    s->reason = "correction_rejected_before_write";
    return true;
  }
  if (!a.attempted || !a.ok || a.rejection != OtisInstrumentRejection::None || a.code != s->write.code) {
    s->code_known = false;
    otis_instrument_fault(s, "dac_application_unknown"); return false;
  }
  s->application = a;
  s->application_ticks = a.ticks;
  s->applied_code = a.code;
  s->code_known = true;
  s->dac_epoch = s->write.dac_epoch;
  s->write_state = OtisInstrumentWriteState::Consumers;
  s->reason = "application_awaiting_consumers";
  return true;
}
bool otis_instrument_confirm_consumers(OtisInstrument *s, uint16_t code, uint32_t epoch, uint64_t ticks) {
  if (s->write_state != OtisInstrumentWriteState::Consumers || code != s->applied_code ||
      epoch != s->dac_epoch || ticks != s->application_ticks) {
    otis_instrument_fault(s, "application_consumer_identity"); return false;
  }
  const bool correction = s->write.kind == OtisInstrumentWriteKind::Correction;
  if (correction) {
    if (!otis_adaptive_hybrid_engine_note_application_and_first_consumer(
        &s->engine, &s->decision, code, epoch, true)) {
      otis_instrument_fault(s, "controller_application_commit"); return false;
    }
    s->engine.last_application_ticks = ticks;
    s->engine.last_application_s = ticks / 1000000ull;
    s->response_epoch = s->health.acceptance_epoch;
    s->response_delta_codes = int32_t(code)-int32_t(s->write.prior_code);
    if (s->reference_hold || s->metadata_hold ||
        !s->health.metadata_qualified ||
        s->requested_mode != OtisInstrumentMode::Auto)
      incomplete_response(s);
  } else {
    auto policy = otis_adaptive_hybrid_default_policy();
    policy.maximum_applications = 0; // zero explicitly means no campaign budget
    policy.maximum_cumulative_movement_codes = 0;
    if (!otis_adaptive_hybrid_engine_init(&s->engine, &policy, code, epoch) ||
        !otis_adaptive_hybrid_engine_bind_exact_setup_application(&s->engine, ticks)) {
      otis_instrument_fault(s, "controller_initialization"); return false;
    }
    s->engine_ready = true;
    s->response_classifier = {};
  }
  ensure_metadata_hold(s);
  add_counter(s, &s->total_applications, 1);
  if (s->write.prior_known) add_counter(s, &s->cumulative_movement,
      code > s->write.prior_code ? code-s->write.prior_code : s->write.prior_code-code);
  if (s->write.kind == OtisInstrumentWriteKind::Fixed || s->write.kind == OtisInstrumentWriteKind::Characterize) {
    s->command_completed = s->last_command.sequence;
    if (s->write.kind == OtisInstrumentWriteKind::Characterize &&
        s->requested_mode == OtisInstrumentMode::Characterize) {
      if (UINT64_MAX-ticks < s->characterize_dwell_ticks) {
        otis_instrument_fault(s, "characterization_deadline_overflow"); return false;
      }
      s->characterize_end_ticks = ticks+s->characterize_dwell_ticks;
    }
  }
  s->write_state = OtisInstrumentWriteState::Idle;
  enter_requested_mode(s);
  s->reason = "application_committed";
  return true;
}
bool otis_instrument_decide(OtisInstrument *s, const OtisAdaptiveHybridObservation &input, OtisAdaptiveHybridDecision *out, double frequency_error_hz) {
  if (!out || s->fault || !s->engine_ready ||
      s->requested_mode != OtisInstrumentMode::Auto || s->write_state != OtisInstrumentWriteState::Idle)
    return false;
  if (input.timestamp_ticks == 0 || input.timestamp_ticks <= s->last_decision_ticks ||
      (s->now_ticks > input.timestamp_ticks &&
       s->now_ticks - input.timestamp_ticks > 60000000ull)) {
    otis_instrument_fault(s, "decision_clock_or_freshness"); return false;
  }
  s->last_decision_ticks = input.timestamp_ticks;
  if (input.timestamp_ticks > s->now_ticks) s->now_ticks = input.timestamp_ticks;
  auto observation = input;
  observation.authority_valid = input.authority_valid && s->health.capture_integrity &&
      s->health.reference_qualified && input.capture_session == s->capture_session &&
      input.source_acceptance_epoch == s->health.acceptance_epoch &&
      input.source_closing_accepted_boundary_ordinal == s->health.accepted_boundary;
  observation.metadata_qualified = s->health.metadata_qualified;
  observation.cadence_eligible = !s->reference_hold;
  if (s->engine.response_pending) {
    if (!observation.metadata_qualified) {
      incomplete_response(s);
      return false;
    }
    if (!observation.authority_valid || !input.settled ||
        input.timestamp_ticks < s->application_ticks ||
        input.timestamp_ticks - s->application_ticks < 1500000000ull ||
        input.dac_epoch != s->dac_epoch ||
        input.applied_code != s->applied_code) return false;
    if (s->response_epoch != input.source_acceptance_epoch) incomplete_response(s);
    else {
      s->response_result = otis_regulation_classify_response(&s->response_classifier,
          s->pre_error_hz, frequency_error_hz, s->response_delta_codes, true, true);
      if (s->response_result.classification == OtisRegulationResponseClass::MeasurementOrActuatorFault) {
        otis_instrument_fault(s, s->response_result.reason); return false;
      }
      add_counter(s, &s->response_sequence, 1);
      s->response_incomplete = false;
      otis_adaptive_hybrid_engine_complete_response(&s->engine, true);
      s->reason = "response_complete";
      return false; // no correction on the same response frontier
    }
  }
  if (!otis_adaptive_hybrid_engine_decide(&s->engine, &observation, out)) {
    otis_instrument_fault(s, "controller_decision_invalid"); return false;
  }
  s->decision = *out;
  s->reason = out->reason;
  if (s->engine.fail_static_reason) otis_instrument_fault(s, s->engine.fail_static_reason);
  if (s->metadata_hold && !s->engine.metadata_hold) s->metadata_hold = false;
  if (out->requested_delta_codes != 0) {
    if (!isfinite(frequency_error_hz)) {
      otis_instrument_fault(s, "nonfinite_source_error"); return false;
    }
    s->pre_error_hz = frequency_error_hz;
    propose(s, static_cast<uint16_t>(out->requested_code), OtisInstrumentWriteKind::Correction);
  }
  return true;
}
const char *otis_instrument_mode_name(OtisInstrumentMode mode) {
  switch (mode) {
    case OtisInstrumentMode::Auto: return "AUTO_DISCIPLINE";
    case OtisInstrumentMode::Hold: return "OBSERVE_HOLD";
    case OtisInstrumentMode::Fixed: return "FIXED_CODE";
    case OtisInstrumentMode::Characterize: return "CHARACTERIZE";
  }
  return "INVALID";
}
const char *otis_instrument_state_name(const OtisInstrument *s) {
  if (s->fault) return strcmp(s->fault,"prospective_repeated_alternation")==0
      ? "CONTROLLER_HOLD" : "INTEGRITY_FAULT";
  if (!s->code_known) return "STARTUP";
  if (s->write_state != OtisInstrumentWriteState::Idle) return "APPLICATION_PENDING";
  if (s->mode != OtisInstrumentMode::Auto) return otis_instrument_mode_name(s->mode);
  if (s->reference_hold) return "REFERENCE_HOLD";
  if (s->metadata_hold) return "METADATA_HOLD";
  if (s->engine.response_pending) return "RESPONSE_PENDING";
  return "ACQUIRING_OR_TRACKING";
}
