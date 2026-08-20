# active_transactions_v1.csv

`ACT` schema version 1 is the non-droppable bounded CX317 transaction record.
It uses a strictly increasing `transaction_record_sequence`; several records
may intentionally share one `request_sequence`.

The exact fields are defined by `ACTIVE_TRANSACTION_V1_FIELDS` in
`host/otis_tools/contracts.py`. The event progression is:

1. `request_created` / `request_pending` before the cross-core handoff;
2. `core0_accepted` / `acceptance_pending` after the actuator owner accepts the
   exact request identity and before any automatic I2C attempt;
3. `application` or `application_fault` / `application_pending` after the one
   attempt and, for success, after estimator-history reset;
4. `response` / `response_pending` after fresh post-epoch qualification.

Each phase is flushed by the sole host capture owner before it sends the exact
`ACTIVE EVIDENCE <request_sequence> <phase_sequence>` acknowledgement. Phase
sequences are 1, 2, 3, and 4 respectively. Repeated or out-of-order phase values
are rejected by the device.

For profile `cx320_active_hybrid`, phase 4 has an additional prospective gate.
The host must first durably retain the matching `AHY` decision and `ACT`
transaction, independently replay the combined demand, limits, integer request,
frequency-only counterfactual, applied code, DAC epoch and response class, and
durably retain the replay attestation. Only then may it submit the phase-4
acknowledgement which can release later hybrid authority.

Serialized evidence is never actionable. Automatic authority exists only in
the in-memory request handed once from the transaction layer to the actuator
owner after durable phase-1 acknowledgement.

`REFERENCE_HOLD` is a nonterminal active-control state. It is entered when the
reference becomes suspect while no actuator request/application handoff is
unfinished. Firmware holds the last confirmed applied code, consumes any
unused short-lived arm, and emits no actionable request. After current PPS,
GNSS metadata, count, and estimator evidence requalify, the transaction returns
to `DISARMED` and requires a fresh exact authorization. If an application was
already acknowledged, response observation may resume after requalification.
Loss during an unfinished request/application handoff remains a terminal
integrity fault.
