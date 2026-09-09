# active_transactions_v2.csv

`ACT` schema version 2 is the sole current adaptive-hybrid transaction record.
Each row carries the complete transaction content and its exact
`event_timestamp_ticks` in `rp2040_monotonic_us64`; there is no separate timing
record or compatibility product.

The exact field order is `ACTIVE_TRANSACTION_V2_FIELDS` in
`host/otis_tools/contracts.py`. `transaction_record_sequence` is strictly
increasing. Several records intentionally share one `request_sequence` as the
transaction advances through:

1. `request_created` / `request_pending`;
2. `request_accepted` / `acceptance_pending`;
3. `application` or `application_fault` / `application_pending`; and
4. `response` / `response_pending`.

The sole host capture owner durably flushes the complete exact ACT row and its
immutable capsule before sending the matching `ACTIVE EVIDENCE` phase
acknowledgement. For phase 4 it also replays the retained AHY, ACT and AHM
evidence before acknowledging the response.

The retained `decision_timestamp_s`, acceptance timestamp and application
timestamp fields are explicit controller-domain inputs or display projections;
they do not replace the exact lifecycle event timestamp and must not be used for
decision-bearing elapsed-time comparisons.

Serialized ACT evidence is always `actionable=false`. Automatic authority
exists only in the private in-memory request-to-actuator handoff.
