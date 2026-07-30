#include <iostream>

#include "otis_reference_quality.h"

namespace {

void emit(const char *scenario, const OtisReferenceEvidence &previous,
          const OtisReferenceEvidence &current, uint64_t now_ticks,
          const OtisReferenceMetadata *metadata) {
  const OtisReferenceQualityConfig config = {
      1000000u, 200000u, 1500000u, 3600000000ull, 4143u};
  const OtisReferenceQualityResult result = otis_assess_reference_quality(
      &previous, &current, now_ticks, metadata, &config);
  char reasons[384];
  otis_reference_quality_reasons(result.reason_mask, reasons, sizeof(reasons));
  std::cout << scenario << "," << result.cadence_state << ","
            << result.capture_path_state << ","
            << result.receiver_authority_state << ","
            << result.utc_traceability_state << ","
            << result.metadata_freshness << ","
            << result.qualification_state << "," << reasons << ","
            << kOtisReferenceQualityAlgorithmVersion << ","
            << kOtisReferenceQualityConfigHash << "\n";
}

}  // namespace

int main() {
  const OtisReferenceEvidence previous = {true, 1u, 0u, 0u};
  const OtisReferenceEvidence current = {true, 2u, 1000000u, 0u};
  const OtisReferenceMetadata qualified = {
      true, 1000000u, OTIS_REFERENCE_AUTHORITY_QUALIFIED,
      OTIS_REFERENCE_UTC_VALID, OTIS_REFERENCE_FIX_CURRENT,
      OTIS_REFERENCE_ANTENNA_OK};
  emit("good_missing_metadata", previous, current, 1000000u, nullptr);

  const OtisReferenceEvidence short_interval = {true, 2u, 600000u, 0u};
  const OtisReferenceMetadata qualified_at_short = {
      true, 600000u, OTIS_REFERENCE_AUTHORITY_QUALIFIED,
      OTIS_REFERENCE_UTC_VALID, OTIS_REFERENCE_FIX_CURRENT,
      OTIS_REFERENCE_ANTENNA_OK};
  emit("bad_cadence_healthy_receiver", previous, short_interval, 600000u,
       &qualified_at_short);

  const OtisReferenceMetadata stale = {
      true, 0u, OTIS_REFERENCE_AUTHORITY_QUALIFIED, OTIS_REFERENCE_UTC_VALID,
      OTIS_REFERENCE_FIX_CURRENT, OTIS_REFERENCE_ANTENNA_OK};
  emit("stale_metadata", previous, current, 4000000001ull, &stale);

  const OtisReferenceMetadata holdover = {
      true, 1000000u, OTIS_REFERENCE_AUTHORITY_HOLDOVER,
      OTIS_REFERENCE_UTC_VALID, OTIS_REFERENCE_FIX_HOLDOVER,
      OTIS_REFERENCE_ANTENNA_OK};
  emit("holdover", previous, current, 1000000u, &holdover);

  const OtisReferenceMetadata utc_invalid = {
      true, 1000000u, OTIS_REFERENCE_AUTHORITY_QUALIFIED,
      OTIS_REFERENCE_UTC_INVALID, OTIS_REFERENCE_FIX_CURRENT,
      OTIS_REFERENCE_ANTENNA_OK};
  emit("utc_invalid", previous, current, 1000000u, &utc_invalid);

  const OtisReferenceMetadata antenna_fault = {
      true, 1000000u, OTIS_REFERENCE_AUTHORITY_QUALIFIED,
      OTIS_REFERENCE_UTC_VALID, OTIS_REFERENCE_FIX_CURRENT,
      OTIS_REFERENCE_ANTENNA_FAULT};
  emit("antenna_fault", previous, current, 1000000u, &antenna_fault);

  const OtisReferenceEvidence sequence_regression = {
      true, 1u, 1000000u, 0u};
  emit("sequence_regression", previous, sequence_regression, 1000000u,
       nullptr);
  emit("qualified", previous, current, 1000000u, &qualified);
  return 0;
}
