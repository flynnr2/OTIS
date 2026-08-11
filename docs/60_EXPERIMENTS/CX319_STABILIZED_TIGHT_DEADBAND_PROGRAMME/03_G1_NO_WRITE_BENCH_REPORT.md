# CX319 G1 No-Write Bench Qualification Report

## Decision

**G1 passed on 2026-08-11.** The exact Leg A no-write bundle completed the
physical acquisition, runtime supervision, bounded normal-path obstruction,
independent priority abort, same-owner logical rotation, cross-segment
analysis, sealing, and external evidence registration path.

This is G1 operational evidence only. It is not frequency-control,
calibration, absolute-phase, UTC, lock, holdover, or G2 live authority. Current
programme authority has returned to offline preparation.

## Passing evidence

| Identity | Value |
|---|---|
| Run | `no_write_leg_a_20260811T133632Z` |
| Source revision | `4f60a02a2dd57f893cafe18ef037583174026273` |
| Bundle SHA-256 | `777e88c9978edb525f887c496b5badf2b5e2cdae09bdfaea0a4071932377db77` |
| Build-manifest SHA-256 | `76b4b5b3447abbe3a6374cd5f133aac83048c5570f9801ac69bec1698f64cb91` |
| UF2 SHA-256 | `e1b12c86476085e2e125ece141bddc66ba6891be98535d4e542ee228f03ff42e` |
| Analyzer SHA-256 | `c6ea40b0f5c07b89367a2e80fb86622642d2c7a7194d00f63d6705984497cde3` |
| Analysis SHA-256 | `0336bfa64938371713cfedcccd0e09b257c9d8ec49ba71b7f87be3f7f56a5690` |
| Seal SHA-256 | `a690bdfd16754ea90f8f40bc1fcdf8e6b6b5143b29ef8ad6e96c110f2eaac87b` |
| Registered content SHA-256 | `cd17f90587a321ed0ddd6c40db76c0beffc8981c68ef7afdd8e46bbc1549432d` |

All 15 analyzer gates passed. The primary capture lasted 2706 seconds and
contained 2707 count observations, PPS snapshots, relative-phase observations,
phase-estimator outputs, and zero-authority hybrid previews. The transition
segment added 175 records after same-owner logical rotation. All 34 declared
primary and transition contract validations passed.

The selected estimator produced one healthy contiguous 600-sample result:

- measured VCOCXO frequency: `9999992.755000000820 Hz`;
- nominal frequency: `10000000 Hz`;
- measured error: `-7.244999999180 Hz` (`-0.7245 ppm` approximately); and
- tight-deadband integer error: `-4347` counts, classified `OUTSIDE` with
  `outside_loose_evidence`.

The result was observe-only. The tight-deadband, phase, and hybrid records had
zero actuator authority. Both capture segments contained zero DAC-step rows and
zero active-transaction rows; the runner recorded zero DAC value writes and
zero control arms.

The transport check saturated 256 normal `CONFIG?` requests while the sole
capture owner was deliberately stopped. The independent priority abort was
then observed after resume. PID `21133` remained the sole owner, with no serial
reopen or reconnect. The final transition status was `ABORTED`, reason
`device_abort_command_via_core0`, with fail-static true.

Physical applied-code state remains unknown. G1 made no setup write and does
not convert the historical CX318 `0xA828` acknowledgement into a current
physical observation.

## Retained preceding attempts

Both preceding attempts produced valid physical acquisition evidence but
failed host verification. They are retained as
`platform_defect_caught_in_rehearsal`, not successful G1 results and not
campaign escapes.

| Attempt | Registered content | Failure | Physical-path result |
|---|---|---|---|
| `no_write_leg_a_20260811T113642Z` | `c1874b867d94669d6ad03c3641ea11891fb4d91b5115035c5a36d00c445fc4fa` | Shared host validation and replay expected the historical CX318 policy hash instead of the run-manifest CX319 hash. | Zero DAC/active rows; priority abort, fail-static close, and physical serial close succeeded. |
| `no_write_leg_a_20260811T123703Z` | `aaa6ad54ac7084e71de1f51d36b4fd20f48c4a78ca3f5bb506481508533f33a8` | Analyzer searched only the primary segment for the final abort state, although same-owner rotation correctly placed it in the transition segment. | All other gates passed; zero DAC/active rows; obstruction, abort, and rotation succeeded. |

The repaired analyzer replays the second retained acquisition successfully
across both segments. That establishes that its physical/firmware evidence was
not the cause of the failed verdict.

## Process correction

The two host defects should have been found before a long physical run. The G1
offline preflight proved structural and authority invariants but was not a
complete operational-path rehearsal.

For G2 onward, three gates are explicit:

1. no-I/O structural and identity **preflight**;
2. short accelerated **operational-path rehearsal** through commands,
   acknowledgements, obstruction, abort, rotation, analyzer, seal, and
   registration; and
3. real-duration **physical qualification** for firmware, plant, and scientific
   evidence.

A deterministic offline analyzer repair may supersede its earlier verdict by
replaying immutable sufficient raw evidence with explicit provenance. It does
not require repeating successful firmware acquisition unless the change can
affect commands, capture, timing, ownership, segmentation, safety, firmware
behavior, or the scientific result.

## Next gate

Proceed with offline-only G2 Leg A preparation. Before requesting live
authority, the exact G2 workflow must pass structural preflight and a short
complete operational-path rehearsal with no physical actuation. The eventual
G2 proposal must separately identify the exact `0xA808` setup write, positive
automatic direction, bounded controller limits, abort conditions, and evidence
path. No G2 hardware operation is presently authorized.
