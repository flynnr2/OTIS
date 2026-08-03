# CX317 Tolerance-Provenance Table Contract

`CX317_TOLERANCE_PROVENANCE_TABLE_V1` is the fail-closed source contract for
the tolerance tables in the CX317 estimator-selection, plant-characterization,
controller-preview and final-readiness reports.

Each row contains the ten operator-requested fields plus `source_hierarchy`.
The accepted hierarchy values are:

1. applicable manufacturer absolute-maximum or recommended-operating evidence;
2. direct measurement on the assembled rig;
3. sealed OTIS evidence applicable to the stated topology/backend/conditions;
4. a documented calculation from stronger evidence; and
5. an explicitly labelled conservative engineering assumption when stronger
   evidence is unavailable.

The only accepted dispositions are `hard safety limit`, `architecture screen`,
`characterization reference`, `model-applicability bound`, and
`proposed control-policy value`. The only accepted results are `pass`, `fail`,
`characterization-only`, `unavailable`, and `not tested`.

Validation checks structure and vocabulary; it does not promote a source to a
stronger hierarchy, establish physical applicability, or decide that a
threshold is adequate. A hierarchy-5 row must contain the literal label
`conservative engineering assumption`. Report review must still reject typical
values used as guarantees, absolute maxima used as operating targets, and
historical evidence used outside its recorded applicability.
