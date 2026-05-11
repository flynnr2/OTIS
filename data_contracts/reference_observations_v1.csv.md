# reference_observations_v1.csv

## Purpose

`reference_observations_v1.csv` stores interpreted or normalized reference observations derived from raw reference captures.

This contract exists because:

- raw `REF` captures are the primary scientific artifact;
- host tooling may later derive cleaner or normalized reference observations;
- PPS quality, survey state, sawtooth metadata, or reference validity may evolve independently from raw edge captures.

## Relationship to Raw Events

Raw PPS/reference edges belong in `raw_events_v1.csv` as `REF` records.

This contract is for higher-level interpreted reference products.

## Example Uses

- normalized PPS intervals;
- PPS quality classification;
- reference-domain continuity assessment;
- timing-GNSS metadata;
- reference-source substitution tracking.
