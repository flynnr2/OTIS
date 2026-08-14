# Measurement Methodology

OTIS aims to encourage scientifically defensible timing experiments.

## Principles

Experiments should document:
- reference sources;
- environmental conditions;
- averaging methodology;
- preprocessing;
- filtering;
- calibration assumptions.

## Long-Run Characterization

Long unattended runs are strongly encouraged.

## Reproducibility

Published analyses should ideally permit:
- replay from raw logs;
- regeneration of derived results;
- inspection of preprocessing assumptions.

## Count Observations

`CNT` rows are raw gated/windowed count observations. They record gate
boundaries, gate domain, counted edges, source edge, source domain, and flags.

Frequency, PPS-gated ratio, ppm error, stability, and control-readiness are
derived analysis products. They must identify:

- the `CNT` rows used;
- any `REF` rows used for PPS or gate-domain calibration;
- skipped invalid or startup-suspect windows;
- manifest nominal frequencies and timing-domain assumptions;
- filtering, averaging, and warmup criteria.

Invalid count windows should remain in the raw artifact when a bounded gate
exists. Derived analyses may exclude them, but the exclusion rule must be
documented.

## Command and finalization provenance

For an actuation-bearing result, retain the exact coherent status generation,
post-attachment nonce, session, build/configuration identity, expiry, requested
code, ordinal, and every firmware transaction phase. `host_written` is a host
transport observation, not a firmware acknowledgement or applied result. An
analyzer must reconstruct authority from retained inputs and raw phase evidence.

Finalization failures do not rewrite the primary acquisition or analysis
verdict. Preserve the first failure, retain later cleanup failures separately,
and use the external finalization journal to register an unchanged valid sealed
package after interruption.
