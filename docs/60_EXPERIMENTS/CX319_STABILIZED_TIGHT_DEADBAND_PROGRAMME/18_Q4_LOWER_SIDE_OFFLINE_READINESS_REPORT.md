# CX319 Q4 Lower-Side Offline Readiness Report

## Result

The selected result is
`q4_offline_ready_for_separate_live_authority_decision`.

This is an offline-readiness result, not a physical qualification or live
result. It grants no serial, flash, reset, setup, arm, DAC-write, automatic-
correction, phase, or hybrid authority. `profiles/programme_status_v2.json`
continues to allow only `offline_preparation`.

The exact non-authorizing candidate is local ignored evidence at
`runs/cx319_stabilized_tight_deadband/q4/q4_offline_preparation_20260813T072443Z`.
Its source revision is
`2f46e1f01da75a17c69b259626d282df4ca1bcdc`, proposal file SHA-256 is
`4c83e4736af8ab1a5ef07840c28a6b98841932fcbf3402a0ae329c554cbf9a40`,
and canonical proposal-bundle identity is
`f08c9a581ec92271828f9c7c0ff87b5e0d1ce04e6015c92d4100c75f7882bbfe`.

## Observed entry facts

- The candidate was frozen from a clean repository with the active programme
  set to `cx319_stabilized_tight_deadband` and only offline preparation
  allowed.
- Q1 remains bound to seal `0d8c4863...7639df` and registered content
  `9e3506c8...ba1e67`.
- Inhibited Q2 remains bound to seal `86eafb3c...7fb66` and registered content
  `1990abe0...4233`; it recorded one physical setup write, zero physical
  automatic writes, and no possible oscillator movement.
- Physical no-write Q3 remains bound to seal `4d074701...fa8c35`, registered
  content `989170aa...641e7`, bundle `28a4d0f0...52a7ab`, and UF2
  `50f863a2...522083`. The package retained 2,706 seconds of capture, one
  selected 600-second estimate, zero setup/DAC/arm/automatic activity, zero
  serial reconnects and parser errors, and passing priority-abort and
  same-owner-rotation results.
- The Q3 package validated read-only under `CX319_EVIDENCE_EPOCH_1`. Six
  optional products were header-only and produced warnings; every declared
  contract passed and the original Q3 verdict was unchanged.
- No retained post-Q3 evidence changes the last qualified board serial,
  firmware image, policy, or connected oscillator-control topology. The
  board's present installed image and applied DAC code were not observed by
  this offline work and remain provenance unknowns.
- No Q4/G2 live authority is effective.

## Q3-to-Q4 transfer audit

| Surface | Q3-to-candidate comparison | Classification | Decision evidence |
|---|---|---|---|
| Firmware and UF2 | Candidate selects the exact Q3 firmware source, generated configuration `ab22c9a7...bd711`, build manifest `c5af898f...e3d87`, and UF2 `50f863a2...522083`. The later current firmware build is not silently substituted. | Identical selected operational input | Q1/Q3 seals, candidate firmware binding, no-flash entry rule |
| Toolchain and target | Q3 build provenance is carried explicitly: Arduino CLI 1.4.1, RP2040 core 6.0.0, GCC 16.1.0, and the recorded installed hashes. | Provenance-only transfer | Bound build manifest and candidate copy of complete provenance |
| Policy, estimators, model and previews | Candidate retains policy `936d92a1...e1698` and its exact frequency estimator, relative-phase estimator, hybrid preview, plant model, response policy, and active-status bindings. | Identical selected semantics | Candidate policy bindings and Release parity tests |
| Current source tree versus selected Q3 image | Current firmware source contains later diagnostic and pristine pre-setup session-rebinding work, but that binary is not selected. The retained Q3 image remains more conservative and fail-static on an unexpected session change. | No candidate-binary change; fail-closed entry limitation | Exact UF2 binding; future entry stops on any identity or readiness mismatch |
| Host module organization | Compatibility reset removed historical readers and renamed reusable abort/replay surfaces. The Q4 proposal now reads the Q1--Q3 sequence ledger instead of the superseded G1-only ledger. | Deterministically covered | 723-test Release pass; read-only Q3 validation; focused provenance regression |
| Command grammar and acknowledgements | Q3 used the no-write query/lease surface. Q4 adds one exact setup, one-shot arm/evidence phases, and bounded automatic transactions; emergency grammar remains only `ACTIVE ABORT`. | Intentional Q4 operational surface, deterministically covered | Setup authority C++ guards, transaction/replay tests, accelerated transcript |
| Serial owner, FIFO, obstruction and abort | Same continuous-owner and independent-abort invariants; Q4 uses the current reusable transport components. | Deterministically covered | Accelerated obstruction/abort/rotation pass and Q3 physical transport result |
| Timing and scientific envelope | Lower stimulus `0xA808`, 600-second estimates, 900-second settling, 1,800-second cadence, 90-minute deadline, four-hour endpoint, and movement bounds are unchanged. | Identical programme semantics | Preflight, outcome-contract tests and accelerated boundary replay |
| Phase and hybrid authority | Observable and replayable, but zero authority before and after transfer. | Identical authority boundary | Release source guards, parity/replay tests and rehearsal verdict |
| Analyzer, sealing and evidence layout | Current epoch finalization and registration replace historical layout while preserving Q3 through read-only validation. | Deterministically covered | Actual current analyzer/seal plus completed/interrupted temporary-index registration |
| Physical entry state | Q3 last confirmed the board and image; present installed image, device path and DAC code were not queried. | Provenance unknown, not evidence of danger | Proposed entry verifies board/image without flash; setup establishes a new DAC epoch; mismatch stops |

No candidate difference requires a physical repeat before a separate live-
authority decision. If future entry finds a firmware-image mismatch, the
candidate forbids flashing and changes the outcome to the shortest affected
physical no-write requalification.

## Offline verification

| Gate | Result and exact identity |
|---|---|
| Release | Passed at source `2f46e1f...1bcdc`: 723 Python/native tests passed in 74.18 seconds; `cx319_tight_lower` and `cx319_tight_upper` passed; all five expected-failure profiles failed for their required reasons. |
| Replay and parity | Passed within Release: selected frequency, relative-phase, hybrid-preview, tight-band, transaction, response and fault suites; selected preview/corpus and frequency-control host/firmware parity; phase/hybrid zero-authority source guards. |
| Setup fault injection | Passed within Release: missing/interrupted setup phases, stale generation, wrong nonce, wrong session, expiry, wrong code/configuration, regressed health predicates, duplicate one-shot consumption, failed I2C acknowledgement, ambiguous acknowledgement rejection, and no retry. |
| Q3 read-only validation | Passed; original registered identity `989170aa...641e7` and verdict retained. |
| No-I/O preflight | Passed; file SHA-256 `444dc38d...f4068b`; all ten checks true and every hardware-operation counter zero. |
| Accelerated operational path | Passed; result file SHA-256 `95ec5a89...49584b`, content identity `2d45d94c...0d7c7`, analysis identity `7ae8e7cd...f336`, and seal `4e6d2009...65084`. |
| Finalization and registration | Passed current analyzer/seal path and actual temporary-index registration for both `completed_campaign` and `interrupted_campaign`; registration file SHA-256 `4f291dd7...6f016`. |

The accelerated path exercised the exact candidate capture, supervisor,
setup transaction, automatic transaction, obstruction, priority abort,
same-owner rotation, analyzer, evidence snapshot, seal, and registration
surfaces. It produced one setup transaction, one healthy positive automatic
transaction of 21 codes, and two-estimate tight entry in accelerated evidence.
Those are host-path checks only and are not physical plant evidence.

## Defects caught during preparation

Three offline defects were corrected without changing Q1--Q3 evidence:

1. the proposal builder consulted the superseded `completed_g1_evidence`
   ledger instead of the sealed Q1--Q3 sequence;
2. Release found three stale line numbers in the generated measurement-
   semantics inventory; and
3. the first passing proposal pointed to, but did not copy into the candidate,
   the required complete firmware configuration, target and toolchain
   provenance and no-flash entry expectations.

The earlier immutable attempts remain under the Q4 local run directory. No
sealed evidence was edited and no physical gate was repeated.

## Derived decision, assumptions and limitations

The evidence supports an operator review of one separately authorized finite
lower-side live qualification. It does not support starting that run now.

The decision assumes the future operator confirms that the DAC analogue output
is connected to oscillator EFC/Vctrl and that no unrecorded physical change has
invalidated the characterized `0xA800..0xAB00` envelope. The future entry must
verify board serial `503533748A919118` and the exact Q3 UF2 without flashing,
then establish the applied state with the single `0xA808` setup transaction.
Any mismatch stops before actuation.

The current Release build of `cx319_tight_lower` verifies current source, while
the proposed live image deliberately remains the older physically qualified
Q3 binary. That distinction is explicit and must not be collapsed. A future
decision may either use this exact candidate or choose a new firmware image;
choosing a new image requires a new bundle and the shortest affected physical
no-write qualification.

The non-effective machine proposal is
`profiles/qualification/cx319_q4_lower_live_authority_proposal_v1.json`; the
human draft decision is `19_Q4_LOWER_SIDE_FINITE_LIVE_AUTHORITY_DRAFT.md`.

