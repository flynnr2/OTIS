#pragma once

#include <stdint.h>

#define OTIS_DIAGNOSTIC_EVIDENCE_REFS_CAPACITY 192u

enum OtisDiagnosticTransition {
  OTIS_DIAGNOSTIC_NO_TRANSITION = 0,
  OTIS_DIAGNOSTIC_RAISED,
  OTIS_DIAGNOSTIC_UPDATED,
  OTIS_DIAGNOSTIC_CLEARED,
};

struct OtisDiagnosticRule {
  uint8_t raise_after;
  uint8_t clear_after;
  uint8_t update_interval;
};

struct OtisDiagnosticState {
  bool active;
  uint8_t bad_count;
  uint8_t clean_count;
  uint32_t episode;
  uint32_t occurrence_count;
  uint32_t last_token;
  uint64_t first_seen_ticks;
  uint64_t last_seen_ticks;
  char first_evidence_refs[OTIS_DIAGNOSTIC_EVIDENCE_REFS_CAPACITY];
  char latest_evidence_refs[OTIS_DIAGNOSTIC_EVIDENCE_REFS_CAPACITY];
};

struct OtisDiagnosticResult {
  OtisDiagnosticTransition transition;
  uint32_t episode;
  uint32_t occurrence_count;
  uint64_t first_seen_ticks;
  uint64_t last_seen_ticks;
  const char *first_evidence_refs;
  const char *latest_evidence_refs;
};

void otis_diagnostic_state_init(OtisDiagnosticState *state);
OtisDiagnosticResult otis_diagnostic_observe(
    OtisDiagnosticState *state, const OtisDiagnosticRule *rule, bool active,
    uint64_t ticks, uint32_t evidence_token, const char *evidence_refs);
const char *otis_diagnostic_transition_name(OtisDiagnosticTransition transition);
