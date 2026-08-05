# Stage 7 A2/B preflight audit

Status: software audit passed; hardware remains held until this exact source is
committed and the complete clean firmware matrix passes.

Protocol binding:

- Stage 7 prompt commit: `d11f62c`
- Stage 7 prompt SHA-256:
  `0ab20ab75c58583789fad512f0eb326ef58bfd467e73ebb35fa2281c94efc512`
- Part A1 is the already sealed A82A fixed-code stability subtest and must not
  be repeated.
- Part A2 alone starts at exact A800 and supplies the live four-phase
  transaction proof.
- Part B starts at the exact passed Part A2 final code and uses the updated
  finite 24-hour protocol.

## Stopped A2 diagnostic

The attempt `part_a2_20260805T065551Z` stopped before any automatic DAC write.
The private Core 1 request correctly remained actionable while awaiting Core 0,
but `request_created` incorrectly copied that private authority bit into the
serialized ACT evidence row. The frozen evidence contract requires every
serialized ACT row to remain non-actionable. The host therefore rejected the
row and aborted fail-static before phase 1.

The stopped prefix is preserved by partial evidence-manifest SHA-256
`86a15a6df64eb7f827de01a0e3abc1de79516fa4780c090fe27b377c0c202f38`
and diagnostic-report SHA-256
`f7621d187d26f53060c12422cb649a87481a0182f5c06a70b2bbdf48086ccd9b`.
A800 is the last confirmed code.

## Protocol-to-code findings and dispositions

| Area | Preflight finding | Disposition |
|---|---|---|
| Authority/evidence separation | The dual-core serializer leaked private request actionability into durable evidence. | The internal request remains actionable, but the ACT serializer now emits literal `false` in every phase. A source guard and CSV-contract scenario enforce the distinction. |
| Four-phase ordering | Per-row validation could not prove that later phases referred to the same immutable request. | Before any ACK, the host now validates the complete durable prefix, exact phase order, contiguous request/record/ordinal sequences, unchanged request identity, prior applied code and exact cumulative movement. |
| Four-phase command ingress | The generic host command parser still limited `ACTIVE EVIDENCE` to the original three phases, so it would have rejected Stage 7 response phase 4. | The closed command grammar now permits exactly phases 1--4 and still rejects phase 0, phase 5 and open-ended forms; the Stage 7 scenario asserts phase-4 transport. |
| Response evidence | Stage 7 analysis trusted serialized response classification. | Every response class, reason, observed response, cumulative response and indeterminate count is replayed sequentially from the frozen classifier. |
| Part A2 initial condition | Generic range validation did not enforce the declared A800 acquisition stimulus. | Part A2 specification and manifest creation require exact A800. The shadow V3 procedural amendment explicitly binds A1 A82A, A2 A800 and the B handoff without changing candidate numerics or authority. |
| Composite A gate | The older aggregate A1 report has top-level `fail` because it correctly lacks a transaction, despite its dedicated stability subtest passing. | Part B now requires the dedicated passed A1 stability gate plus a passed A2 transaction gate with one to four applications and exact response replay. Both documents and hashes are embedded in the B run manifest. |
| Part B start artifact | The matrix template contains a placeholder Part B start and previously required an ad-hoc edit after A2. | A dedicated derivation tool produces an immutable matrix from the passed A2 gate. Manifest creation proves the derived matrix, build source identity, firmware define and passed A2 final code are identical. |
| Part B zero-correction path | Analysis previously demanded nonzero critical actuator-queue high-water, contradicting the updated protocol's valid zero-write endurance outcome. | A zero-correction B run may pass with critical high-water zero; any B run with applications must show critical traffic. A2 supplies the required live transaction proof. |
| Part B service schedule | The supervisor could reach a healthy time/clear state while a required load burst was missing, leaving analysis to fail after 24 hours. | Healthy stop now requires all four scheduled 60-query bursts. A missing burst aborts diagnostic-only at the 24-hour boundary. |
| Finite endpoints | A1 originally lacked a finite successful no-crossing endpoint. | A1 is sealed and not repeated. A2 has 90 minutes to qualify and four qualified hours to pass. B has 90 minutes to qualify, exactly 24 qualified hours, and at most one clearance-only hour for an already outstanding transaction. |
| Evidence sealing | Stage 7 reports were expected but not included in the primary evidence snapshot. | New A2/B manifests declare supervisor state/events, authoritative/shadow reports and the exit gate as required evidence artifacts. |

## Exact terminal semantics

Part A2 passes only with one to four exact
`request_created -> core0_accepted -> application -> response` transactions,
the bounded 60-query service interval, a later healthy eligible decision, and
terminal `DISARMED/evidence_clear`. Zero transactions, timeout, hold, fault,
transport degradation or an incomplete phase is diagnostic-only and blocks B.

Part B inhibits new arming at the exact 24-hour qualified boundary. It passes
only after all four scheduled service bursts, exact replay of every transaction
(if any), respected movement/cadence/range/dither limits, clean health and
terminal `DISARMED/evidence_clear`. Zero corrections is a valid pass. If a
transaction is already outstanding at 24 hours, only its completion and clear
state may use the one-hour grace period; otherwise the run aborts fail-static.

## Offline verification

The exact A800 four-phase happy path, every incomplete prefix, cross-phase
mutation rejection, response replay, A1/A2/B handoff, derived B matrix, B
zero-write success, missing-service-burst failure, 24-hour clearance success
and clearance timeout are covered by the focused Stage 7 tests. The complete
repository suite passes: `738 passed, 2 skipped`.

No hardware run is authorized by this document alone. The remaining entry gate
is one clean commit containing this audit and its repairs, followed by the
complete pinned firmware matrix from that clean source. Part B must additionally
be re-reviewed against the prompt hash above after A2 passes and before its
derived artifact is flashed.
