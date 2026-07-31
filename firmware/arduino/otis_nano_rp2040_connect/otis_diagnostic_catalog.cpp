#include "otis_diagnostic_catalog.h"

const char kOtisDiagnosticAlgorithmVersion[] =
    "diagnostic_transition_engine_v1";
const char kOtisDiagnosticConfigHash[] =
    "7f53f5cf150df70809420faafefba29b463ccac930c596ae7e1f184af5a0b0d7";

const OtisDiagnosticDefinition
    kOtisDiagnosticDefinitions[OTIS_DIAG_COUNT] = {
        {"diag.reference.cadence", "reference", "WARN",
         "reference_cadence_unqualified", "reference_cadence_requalified",
         "invalidate", "invalidate", "none", "inhibit", {1u, 1u, 10u}},
        {"diag.reference.authority", "reference", "WARN",
         "reference_authority_unqualified",
         "reference_authority_requalified", "none", "reduce_trust", "none",
         "inhibit", {1u, 1u, 10u}},
        {"diag.aperture.unqualified", "count_path", "WARN",
         "counter_aperture_unqualified", "counter_aperture_requalified",
         "mark_unavailable", "none", "none", "none", {1u, 1u, 10u}},
        {"diag.sequence.discontinuity", "count_path", "WARN",
         "sequence_discontinuity", "sequence_continuity_requalified",
         "invalidate", "none", "none", "inhibit", {1u, 1u, 10u}},
        {"diag.interpolation.support", "estimator", "WARN",
         "insufficient_interpolation_support",
         "interpolation_support_restored", "invalidate", "none", "none",
         "inhibit", {1u, 1u, 10u}},
        {"diag.count.window", "count_path", "FAULT",
         "invalid_or_saturated_count_window", "count_window_requalified",
         "invalidate", "none", "none", "inhibit", {1u, 3u, 10u}},
        {"diag.resource.failure", "service_plane", "FAULT",
         "resource_failure", "resource_recovered", "mark_unavailable", "none",
         "none", "inhibit", {1u, 1u, 10u}},
        {"diag.plant.inapplicable", "control", "WARN",
         "plant_model_inapplicable", "plant_model_applicable", "none", "none",
         "not_applicable", "inhibit", {1u, 1u, 10u}},
        {"diag.output.loss", "service_plane", "DEGRADED",
         "output_backpressure_loss", "output_path_recovered", "none", "none",
         "none", "none", {1u, 1u, 10u}},
        {"diag.estimator.identity", "estimator", "FAULT",
         "estimator_identity_mismatch",
         "estimator_identity_match_restored", "none", "none",
         "not_applicable", "inhibit", {1u, 1u, 10u}},
};
