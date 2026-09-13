# Association-loss decisions v2

`ASL` freezes the decision-local state used when a PPS reference cannot be
associated with a PIO snapshot. It is emitted before the firmware records the
association loss, rearms the backend, or clears estimator state, so later
recovery cannot overwrite the evidence needed to distinguish a missing
snapshot from foreground delay or a latched backend fault.

The CSV header is the `ASSOCIATION_LOSS_DECISION_V2_FIELDS` sequence in
`host/otis_tools/contracts.py`. All counters and tick values are non-negative.
Boolean fields use lowercase `true`/`false`.

`classification` is one of:

- `backend_fault`
- `unread_snapshot_present_when_decision_made`
- `timeout_no_snapshot`
- `no_unread_snapshot_healthy_backend`

The record is diagnostic evidence only. It grants no DAC, active-control,
phase, hybrid, or GPS authority. The current programme requires zero `ASL` rows;
if a row exists, the run is preserved for diagnosis and cannot seal as a
healthy leg.

## Unassociated hardware evidence

Schema 2 adds a bounded diagnostic freeze before rearm clears the DMA ring.
The original `snapshot_*` fields and classification retain the decision's
pre-stop backend observation. The `frozen_*` fields are sampled after stopping
PIO and DMA, before rearm. These are different frontiers: DMA may advance
between them. `decision_ticks` is the RP2040 us32 CPU observation immediately
before freeze, not a hardware edge timestamp or a DMA completion timestamp.

`snapshot_frozen` distinguishes a stopped initialized backend from unavailable
state. `frozen_session`, producer/consumer ordinals, actual unread backlog, and
joined PIO RX FIFO depth describe that stopped state. Freeze does not consume a
snapshot. `unassociated_front_word_present` explicitly qualifies the value in
`unassociated_front_word`: a raw uint32 D8 cumulative down-counter at the frozen
consumer ordinal. A missing value is serialized as zero with presence false;
a genuine zero with presence true remains valid raw diagnostic evidence.

This is deliberately only the unread DMA front, not a complete loss dump.
Additional ring words and any FIFO contents are not serialized. Their depths
remain explicit. An overwritten or otherwise unreadable slot has no front
value. Hardware/DMA faults can leave only partial diagnostic evidence; presence
must not be interpreted as a healthy aperture or a known D14 association.
Neither equality of ordinals nor a plausible count delta establishes which REF
owns this word. It never enters SNP, CNT, APS, estimators, or control. The prior
complete SNP and this unassociated value may support offline hypotheses only.

Schema 2 replaces the current schema 1 reader and writer. Retained historical
packages remain unchanged and require their frozen schema 1 tools. No campaign
criterion or automatic resume/abort policy changes.
