# active_transactions_v1.csv

`ACT` schema version 1 is the non-droppable bounded CX317 transaction record.
It uses a strictly increasing `transaction_record_sequence`; several records
may intentionally share one `request_sequence`.

The exact fields are defined by `ACTIVE_TRANSACTION_V1_FIELDS` in
`host/otis_tools/contracts.py`. The event progression is:

1. `request_accepted` / `request_pending` before any automatic I2C attempt;
2. `application` or `application_fault` / `application_pending` after the one
   attempt and, for success, after estimator-history reset;
3. `response` / `response_pending` after fresh post-epoch qualification.

Each phase is flushed by the sole host capture owner before it sends the exact
`ACTIVE EVIDENCE <request_sequence> <phase_sequence>` acknowledgement. Phase
sequences are 1, 2, and 3 respectively. Repeated or out-of-order phase values
are rejected by the device.

Serialized evidence is never actionable. Automatic authority exists only in
the in-memory request handed once from the transaction layer to the actuator
owner after durable phase-1 acknowledgement.
