# Attempt 4 phase-4 attestation and scientific terminal

## Result

Attempt 4 has two distinct, retained outcomes.

First, it is formally a failed physical qualification because the live host
path did not retain the required response-replay attestation before any of the
eleven phase-4 acknowledgements. The physical seal therefore correctly records
`measurement_authority_or_platform_fault` and
`response_pre_acknowledgement_attestations_exact=false`. This missing source
evidence cannot be reconstructed retrospectively into a qualification pass.

Second, the unchanged physical controller reached the prospectively frozen
scientific terminal `prospective_low_efficiency_path`. The retained AHY and ACT
histories, exact DAC epochs, eleven response records, and every first later
dependent consumer replay exactly. The offline analyzer independently replayed
all eleven response horizons successfully. The missing contemporaneous
attestation files did not change a command, application, response,
acknowledgement, authority release, or controller decision. The low-efficiency
rejection therefore remains causal and answers the programme decision: the
unchanged controller is not a candidate for another identical sustained run.

No Attempt 5 is authorized or scientifically warranted. The host platform
escape is repaired and rehearsed for future work, but repeating the unchanged
controller would only repeat a decision already reached against a frozen
criterion.

## Physical timeline

All times are UTC.

| Time | Milestone or action | Retained evidence |
| --- | --- | --- |
| 2026-08-23 21:50:43 | Physical wall origin established after exact flash and board identity. | Run manifest and firmware-entry report. |
| 22:00:59 | Setup bound prewrite status generation 122 and completed at `0xA83C`, DAC epoch 1. | Setup-authority input, raw status, ACT, and supervisor evidence. |
| 22:30:44 | Qualified origin established at estimate `est:cx317:selected600:000541`, device tick `38419417504`, capture session 1. | Supervisor state and selected estimate. |
| 23:20:40–23:55:43 | Request 1 completed: delta -6, code `0xA836`, DAC epoch 2, response retained, first checkpoint passed, and later authority released. | ACT records 2–5 and the first dependent AHY consumer. |
| 2026-08-24 04:16:04–04:41:08 | Request 8 applied the first natural opposite direction: delta +5, code `0xA830`, DAC epoch 9; its response completed exactly. | ACT records 30–33 and retained AHY identity. |
| 07:56:10–08:21:14 | Request 10 completed: delta -5, code `0xA830`, DAC epoch 11. | ACT records 38–41 and later consumer. |
| 08:51:13–09:16:18 | Request 11 completed: delta +5, code `0xA835`, DAC epoch 12. | ACT records 42–45 and later consumer. |
| 09:46:21 | AHY decision 52 entered `FAIL_STATIC` with `prospective_low_efficiency_path`; the supervisor submitted one priority abort. | AHY row 52 and supervisor terminal. |
| 09:46:21–09:46:24 | The sole capture owner delivered `ACTIVE ABORT`, retained fail-static state, and closed cleanly. | Raw serial, capture state, closure, and `COMPLETE`. |
| 09:47:13–09:47:18 | Analysis, failed physical seal, and external registration completed. | Physical seal and evidence index. |

The terminal static code is 43061 (`0xA835`). Eleven automatic physical
applications consumed 37 codes of cumulative movement; the deliberate
challenge was not needed because request 8 established a natural reversal.
The terminal decision considered the next five-code demand prospectively and
stopped before it could turn a 37-code path with only seven codes net movement
from setup into the frozen low-efficiency condition.

The repaired Attempt 3 command-ingress boundary also passed physically:
12,671 normal supervisor submissions have matching capture `host_written`
records, maximum observed lag was two seconds, and none exceeded the frozen
deadline. Capture sent 12,672 commands including the one priority abort, with
zero rejected commands, parser errors, reconnects, or malformed UTF-8.

## Exact Attempt 4 evidence

- Run: `runs/otis_sustained_hybrid_regulation_v1/live_attempt4_20260823T2148Z`
- Programme run identity: `otis_sustained_hybrid_regulation_v1:1`
- Board serial: `503533748A919118`
- Activation SHA-256: `ac84beb3b6deef4a0bc8914ac3daacd3ed115f3c6ab39749e23fbeb80daaf64c`
- Activation file SHA-256: `e48257957c5766f15f24c6dfb168ae799388b7cb9267c3daff2b458ea1542a76`
- Bundle SHA-256: `d3edbab4f21f2bf9b4e65eff4410d98374ccc6f82caa8a32af8a4ec6ce0c4431`
- Bundle file SHA-256: `deb96fcdc2514c5aaad63f8b1e04fe5e7f0090909c7b7026715e5640d6f81243`
- Firmware build identity: `bfa206c69f2d5ebaa117fae466d93a13d4701ee91673943ba7e885a7aefe94d8:ad8feae0d5f99b5089a1777ca227e2791f8ee4379f181df004b5c95c2afd2d78`
- UF2 SHA-256: `abf037af3f2f438d3b0d53223f66a38e7009b348dcfa247f3735ce54a0d30717`
- Source revision: `da0f4f024dddd33c94da853a6d503ad97e3892eb`
- Attempt 3 predecessor seal SHA-256: `d5ebf5987f8fc3795319cc88bb733bbdb740449a10dc76af964d7ff95636db55`
- Attempt 4 physical seal SHA-256: `8078b24453e36d149fe05c85f37a7c73df314408923a44c763e90eb6ebe3b455`
- Attempt 4 seal file SHA-256: `e5d3a8bf4b7af336b2aceae9f1e6b7f7299b421e22652f409ac3a36b051e2c66`
- Registered evidence content SHA-256: `aa7ac41bb07192f4de5807547899d50b0e51b3c60bbcac4f8e9cadb6fc6a2a90`
- Registered package: 80 files, 409,352,510 bytes, registered at
  `2026-08-24T09:47:17.980475Z`

The acquisition gate passed. The offline finalization gate is deliberately
failed but replayable without a physical repeat. The only failed integrity
check is the absence of the contemporaneous pre-acknowledgement replay
attestations; all retained transaction, response, consumer, capture, command,
identity, setup, budget, raw measurement, estimator, and terminal-static checks
pass.

## Root cause and bounded repair

`ActiveTransactionSupervisor._preserve_and_acknowledge()` dispatched the
pre-phase-4 response replay guard only for the CX320, CX321, and CX322 profile
identities. It omitted `otis_sustained_hybrid_regulation_v1`, even though the
sustained profile uses the same four-phase response transaction. Consequently,
the supervisor preserved each response capsule and acknowledged firmware, but
never called `replay_response_before_acknowledgement()` or created
`record_*_response_replay_attestation.json`.

The narrow repair adds the sustained profile to that dispatch set. A
deterministic regression now proves the response replay attestation exists and
is durable before the phase-4 command boundary. No controller mathematics,
firmware response semantics, scientific threshold, command envelope, physical
budget, retry rule, restoration rule, or duration changed.

The complete operational rehearsal was also corrected where the newly active
guard exposed stale fixture shortcuts: it now models the real request frontier,
keeps long accelerated timer gaps unambiguous across RP2040 rollover, streams
each request only after the preceding phase-4 ACK, publishes the exact response
observation, and gives the four causal transactions a bounded duration.

## Verification and closeout

The affected exact firmware profile compiled cleanly from operational revision
`791fe8e349748c67ee215825f53bb4ab9b26585f`. The build identity remains
`bfa206c69f2d5ebaa117fae466d93a13d4701ee91673943ba7e885a7aefe94d8:ad8feae0d5f99b5089a1777ca227e2791f8ee4379f181df004b5c95c2afd2d78`;
the newly bound UF2 SHA-256 is
`6f9958d85e17907acf7562d3fed1f024fe55be7f45b0e9da975e0ce00ae30510`.

The final non-effective repair bundle has semantic SHA-256
`094317d7ea6c6dd4ec26c947064ae334b06e9b975a2cf3fc581cae670a760ebb`
and file SHA-256
`57393e218a5f28f25e4b3bf554157e2c012262b81bee51932cc95874930d7338`.
The non-effective proposal SHA-256 is
`5e0e7c9cbc42ded38e81c0f0ce2d66546bd125ae58c77ebb6af72e78f8a9815b`.

The full exact-path rehearsal passed with semantic rehearsal SHA-256
`ea0bdf6b216cc2897603756a2a0a108c067ac5ea0e245a61f837a79aa83ee7db`.
It retained four response replay attestations before four phase-4 submissions,
confirmed all 16 firmware-consumed acknowledgement phases, propagated the
challenge and opposite-direction recovery through decision 34, saturated the
normal FIFO, delivered the independent priority abort, preserved sole serial
ownership through logical rotation without reconnect, and completed real
analysis, sealing, and registration. Capture reported zero parser errors. The
rehearsal used a PTY and performed zero physical actions; it does not claim
RP2040 USB/cross-core, AD5693R, D14, D8, or plant qualification.

Focused verification passed 61 tests covering sustained transaction replay,
the live rehearsal, the active-hybrid programme, and active transactions. No
serial device was opened, no FIFO in the physical run was touched, and no
flash, reset, DAC write, restoration, retry, or new physical attempt occurred
during recovery.
