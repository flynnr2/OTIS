#pragma once

#include <stdint.h>

#include "otis_diagnostic_engine.h"

enum OtisDiagnosticIndex : uint8_t {
  OTIS_DIAG_REFERENCE_CADENCE = 0,
  OTIS_DIAG_REFERENCE_AUTHORITY,
  OTIS_DIAG_APERTURE_UNQUALIFIED,
  OTIS_DIAG_SEQUENCE,
  OTIS_DIAG_INTERPOLATION,
  OTIS_DIAG_COUNT_WINDOW,
  OTIS_DIAG_RESOURCE,
  OTIS_DIAG_MODEL,
  OTIS_DIAG_OUTPUT,
  OTIS_DIAG_ESTIMATOR_IDENTITY,
  OTIS_DIAG_COUNT,
};

struct OtisDiagnosticDefinition {
  const char *diagnostic_id;
  const char *subsystem;
  const char *severity;
  const char *reason;
  const char *clear_reason;
  const char *observation_effect;
  const char *reference_effect;
  const char *model_effect;
  const char *control_effect;
  OtisDiagnosticRule rule;
};

extern const char kOtisDiagnosticAlgorithmVersion[];
extern const char kOtisDiagnosticConfigHash[];
extern const OtisDiagnosticDefinition
    kOtisDiagnosticDefinitions[OTIS_DIAG_COUNT];
