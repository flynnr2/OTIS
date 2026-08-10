# Association-loss decisions v1

`ASL` freezes the decision-local state used when a PPS reference cannot be
associated with a PIO snapshot. It is emitted before the firmware records the
association loss, rearms the backend, or clears estimator state, so later
recovery cannot overwrite the evidence needed to distinguish a missing
snapshot from foreground delay or a latched backend fault.

The CSV header is the `ASSOCIATION_LOSS_DECISION_V1_FIELDS` sequence in
`host/otis_tools/contracts.py`. All counters and tick values are non-negative.
Boolean fields use lowercase `true`/`false`.

`classification` is one of:

- `backend_fault`
- `unread_snapshot_present_when_decision_made`
- `timeout_no_snapshot`
- `no_unread_snapshot_healthy_backend`

The record is diagnostic evidence only. It grants no DAC, active-control,
phase, hybrid, or GPS authority. A Stage 5 candidate requires zero `ASL` rows;
if a row exists, the run is preserved for diagnosis and cannot seal as a
healthy leg.
