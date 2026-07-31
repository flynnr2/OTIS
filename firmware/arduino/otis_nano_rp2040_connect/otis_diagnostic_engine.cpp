#include "otis_diagnostic_engine.h"

#include <limits.h>
#include <string.h>

void otis_diagnostic_state_init(OtisDiagnosticState *state) {
  memset(state, 0, sizeof(*state));
}

OtisDiagnosticResult otis_diagnostic_observe(
    OtisDiagnosticState *state, const OtisDiagnosticRule *rule, bool active,
    uint64_t ticks, uint32_t evidence_token, const char *evidence_refs) {
  OtisDiagnosticResult result = {};
  if (evidence_token == state->last_token) return result;
  state->last_token = evidence_token;
  const char *refs = evidence_refs == nullptr ? "unavailable:evidence" :
                                                 evidence_refs;
  if (active) {
    state->clean_count = 0u;
    if (state->bad_count < UCHAR_MAX) state->bad_count++;
    if (!state->active && state->bad_count >= rule->raise_after) {
      state->active = true;
      state->episode++;
      state->occurrence_count = 1u;
      state->first_seen_ticks = ticks;
      state->last_seen_ticks = ticks;
      strncpy(state->first_evidence_refs, refs,
              OTIS_DIAGNOSTIC_EVIDENCE_REFS_CAPACITY - 1u);
      state->first_evidence_refs[
          OTIS_DIAGNOSTIC_EVIDENCE_REFS_CAPACITY - 1u] = '\0';
      strncpy(state->latest_evidence_refs, refs,
              OTIS_DIAGNOSTIC_EVIDENCE_REFS_CAPACITY - 1u);
      state->latest_evidence_refs[
          OTIS_DIAGNOSTIC_EVIDENCE_REFS_CAPACITY - 1u] = '\0';
      result.transition = OTIS_DIAGNOSTIC_RAISED;
    } else if (state->active) {
      if (state->occurrence_count < UINT32_MAX) state->occurrence_count++;
      state->last_seen_ticks = ticks;
      strncpy(state->latest_evidence_refs, refs,
              OTIS_DIAGNOSTIC_EVIDENCE_REFS_CAPACITY - 1u);
      state->latest_evidence_refs[
          OTIS_DIAGNOSTIC_EVIDENCE_REFS_CAPACITY - 1u] = '\0';
      if (rule->update_interval > 0u &&
          state->occurrence_count % rule->update_interval == 0u)
        result.transition = OTIS_DIAGNOSTIC_UPDATED;
    }
  } else {
    state->bad_count = 0u;
    if (state->active) {
      if (state->clean_count < UCHAR_MAX) state->clean_count++;
      if (state->clean_count >= rule->clear_after) {
        state->active = false;
        state->last_seen_ticks = ticks;
        strncpy(state->latest_evidence_refs, refs,
                OTIS_DIAGNOSTIC_EVIDENCE_REFS_CAPACITY - 1u);
        state->latest_evidence_refs[
            OTIS_DIAGNOSTIC_EVIDENCE_REFS_CAPACITY - 1u] = '\0';
        result.transition = OTIS_DIAGNOSTIC_CLEARED;
      }
    } else {
      state->clean_count = 0u;
    }
  }
  result.episode = state->episode;
  result.occurrence_count = state->occurrence_count;
  result.first_seen_ticks = state->first_seen_ticks;
  result.last_seen_ticks = state->last_seen_ticks;
  result.first_evidence_refs = state->first_evidence_refs;
  result.latest_evidence_refs = state->latest_evidence_refs;
  return result;
}

const char *otis_diagnostic_transition_name(
    OtisDiagnosticTransition transition) {
  switch (transition) {
    case OTIS_DIAGNOSTIC_RAISED: return "raised";
    case OTIS_DIAGNOSTIC_UPDATED: return "updated";
    case OTIS_DIAGNOSTIC_CLEARED: return "cleared";
    case OTIS_DIAGNOSTIC_NO_TRANSITION: return "unknown";
  }
  return "unknown";
}
