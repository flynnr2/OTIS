# Attempt 1 response-identity propagation terminal

## Result

Attempt 1 is a failed qualification due to a platform escape into the physical
campaign. The exact response identity from each durable ACT response record
was not propagated through the first dependent AHY decision. The second escape
was decision-bearing: AHY decision 11 released the controller from
`FIRST_PHASE_TRANSACTION` into `HYBRID_TRACKING` while carrying request and
application sequence `0` and response class `unavailable`.

This is an actual frozen measurement/provenance-authority failure. It is not a
failure of the permitted characterization. Both physical response records were
classified `healthy_indeterminate_near_resolution`; the first transaction was
not phase-material and that descriptive result remains allowed.

## Milestone timeline

All times are UTC on 2026-08-23 unless stated otherwise.

| Time | Milestone or action | Retained evidence |
| --- | --- | --- |
| 12:15:07 | Physical wall origin established. | Run manifest and supervisor start event. |
| 12:25:22 | Setup code `43068` (`0xA83C`) confirmed at DAC epoch 1 through the setup path. | Supervisor state and setup-authority input. |
| 12:55:07 | Qualified origin established: `est:cx317:selected600:000541`, RP2040 timer0 tick `38417873056`, session 1, `live:CNT:2399`, `live:DAC:1`. | Supervisor event and state. |
| 13:15:07 | First eligible natural decision, AHY 3, requested zero codes. This is retained characterization with no actuation. | AHY decision 3. |
| 13:55:04–13:55:08 | Request 1 passed request, core-0 acceptance, and application phases; delta `-5`, code `43063` (`0xA837`), epoch 2. | ACT records 2–4. |
| 14:20:08 | Request 1 durable response ACK, ACT record 5: `healthy_indeterminate_near_resolution`. | ACT record 5 and supervisor event. |
| 14:30:11–14:30:15 | Request 2, the first phase-material transaction, passed request, core-0 acceptance, and application; delta `-1`, code `43062` (`0xA836`), epoch 3. | ACT records 6–8. |
| 14:55:15 | Request 2 durable response ACK, ACT record 9: `healthy_indeterminate_near_resolution`; first-phase checkpoint passed. | ACT record 9 and supervisor state. |
| 15:05:15 | Actual integrity fault became decision-bearing. AHY 11 released `HYBRID_TRACKING` with code/epoch `43062/3`, but request/application sequence `0/0` and response class `unavailable`. | AHY decision 11 and superseding replay comparison. |
| 15:12:29 | One independent host priority abort submitted and delivered. Firmware entered fail-static at code `43062`; no retry or restoration. | Supervisor event, terminal state, capture state. |
| 15:12:32–15:12:33 | Capture closed after abort delivery with the sole owner; run reached `COMPLETE`. Parser errors, reconnects, and rejected commands were all zero. | Capture state and `COMPLETE`. |
| 15:12:33 | Initial offline finalization rejected the sustained manifest as a CX319 package. The report explicitly records that no physical rerun was required. | `sustained_hybrid_active_hybrid_finalization_failure_v1.json`. |
| 15:15:03 | Offline finalization was recovered over unchanged retained evidence, producing the original seal. | `otis_sustained_hybrid_physical_seal_v1.json`. |
| 15:20:21 | The repaired analyzer produced the superseding failed seal with the exact downstream propagation check. | `otis_sustained_hybrid_physical_seal_superseding_v2.json`. |
| 15:20:50 | The superseding package was registered as `failed_qualification`. | External OTIS evidence index. |

## Exact terminal evidence

- Run: `runs/otis_sustained_hybrid_regulation_v1/live_attempt1_20260823T1214Z`
- Programme run identity: `otis_sustained_hybrid_regulation_v1:1`
- Activation SHA-256: `0b1762b9540045c92293cd3a1e2c6e05d90b848446dc6721ffb6d57abd86dc7a`
- Bundle SHA-256: `d09d72f5eb141d797ff9ce48e6e153d230247f521f0d93ea27188dc47d4e4f4e`
- Firmware build identity: `009574ea8f54d668f76f9ebbc485da09c44eb4e091c1c871f979bec34dcc034e:ad8feae0d5f99b5089a1777ca227e2791f8ee4379f181df004b5c95c2afd2d78`
- UF2 SHA-256: `b2f658d0e71c13533ce663fffec841be6116b1d6a7e1d7ae2c1b4c232cf358f0`
- Superseding seal SHA-256: `2b6e8c6a4f48eb483ce2c206e4d6d0210145163a3636e20f501aa151ed56258a`
- Superseding seal file SHA-256: `7499f9c413f82c5c223299eb986cb62cb871ede9bd3369b1ece961b48355f875`
- Superseding analyzer SHA-256: `0d53878e2d76e270eb9a69ace463f44fa93f1b3c06e06ee627f72ec052125d83`
- Registered evidence content SHA-256: `7fb8cfa407c2adfd6d69aeb1378e43ef666692af4b4f37440effc75fad9b60ee`
- Registered file count: 46

The superseding analysis preserves the original seal and initial finalization
failure. It corrects the terminal classification over unchanged raw evidence;
it does not revise any frozen acceptance criterion.

## Escaped defect and bounded repair

The firmware cleared the completed response transaction before serializing the
first later AHY decision. Applied code and DAC epoch remained visible through
the independent current-state fields, but request sequence, application
sequence, and response class fell back to their empty values. The previous
rehearsal generated coherent component records without asserting that exact
completed response identity through every first dependent decision.

The bounded repair retains the completed request sequence, application
sequence, and response class until the next AHY record is successfully queued.
The analyzer now makes this propagation a sustained acquisition-gate check.
The accelerated rehearsal covers four complete request/response sequences and
asserts the exact first consumer after every response, including the later
challenge, recovery, and post-recovery paths. A source guard verifies that the
firmware clears the retained identity only after decision serialization.

The separate offline finalizer escape was repaired by recognizing the exact
sustained evidence epoch, stage, and profile. Because acquisition evidence was
complete and unchanged, recovery correctly required no physical I/O and no
physical rerun.

No Attempt 2 was created. A future attempt must bind a new clean firmware
binary and actual host path, repeat the complete operational rehearsal, and
receive new explicit physical authority.
