# CX320 Stage 5 Attempt 7 Response-Boundary Terminal and Attempt 8 Recovery

## Attempt 7 decision-bearing progress

Attempt 7 (`stage5_live_attempt7_20260820T1525Z`) crossed the complete setup,
qualification, host re-arm and first physical hybrid-application path. The
exact setup placed 43068 (`0xA83C`) at DAC epoch 1 with `i2c_ok=true`. Two
fresh authoritative 600-second estimates established `TIGHT_INSIDE`; after
the frozen 1,800-second phase-qualification residence, firmware created the
first phase-material combined request.

That decision used a frequency term of `-0.001666666940 Hz`, a phase term of
`-0.000370370370 Hz`, and a combined demand of `-0.002037037310 Hz`. With the
frozen controller gain the raw request was `-5.875839765254` codes and rounded
to `-6` codes. Removing only the phase term produced the frequency-only
counterfactual `-5`, so the phase contribution was materially influential by
the frozen definition. Request 1 was authorized, accepted and physically
applied from 43068 to 43062 at DAC epoch 2 with `i2c_ok=true`, no clamp and no
ambiguous application. This is the first observed firmware-driven physical
hybrid correction in the programme and is farther than any predecessor run.

Firmware later recorded an observed response of `-0.001666667 Hz`, zero
post-error at the serialized resolution, the predicted response sign and the
`healthy_indeterminate_near_resolution` class. The independent host guard
correctly withheld the phase-4 acknowledgement and the run delivered one
bounded priority abort. Firmware entered `FAIL_STATIC`; complete terminal
snapshot generation 1255 records `ABORTED`, evidence clear, no outstanding
authority, code 43062 and DAC epoch 2. Capture retained 40 files and about
55 MB under content SHA-256
`b2e5a38fcbe043777a17e02973a128a0a35ad9fcd8f87f1eddf92141e0fcc49e`.

The original physical seal is failed with primary decision
`measurement_authority_or_platform_fault`, semantic SHA-256
`ad6086afc15b3812e0f9cc75ea7fc9df6e55bbea89e51951192afc4971617c7b`
and file SHA-256
`57296d34c59608d4694b966c37527775291bff9d6371b3fbdaf19b372b329022`.
It remains an honest record of the tools frozen for attempt 7.

## Response-support defect

The applied transaction occurred at firmware uptime 4811, while the selected
response estimate closed at uptime 6310: only 1,499 fully elapsed seconds. The
frozen checkpoint requires 900 seconds of excluded settling followed by 600
complete fresh one-second intervals. Firmware admitted the interval closing
exactly at `settling_until_s`; that interval had begun one second earlier and
therefore straddled the excluded settling boundary. This is a firmware and
scientific response-window defect, not evidence for weakening the 1,500-second
criterion.

The estimator gate now excludes equality. A compiled-firmware regression
proves that the first selected response estimate for the new DAC epoch contains
600 accepted intervals, starts at the exact end of the 900-second exclusion,
and closes at application + 1,500 seconds. Attempt 7's response cannot pass the
checkpoint retrospectively; the affected firmware boundary requires one new
physical interval after exact rebuild and rehearsal.

## Host defects moved before physical entry

Two host defects did not change the firmware request, applied code, plant or
retained datastream:

- `AHY` serializes both the frequency input and raw code demand to 12 decimal
  places. Replaying the serialized frequency through the 2,884.5 codes/Hz gain
  differed from the separately serialized firmware raw demand by
  `4.20e-10` codes. The former generic `5e-12` absolute comparison incorrectly
  treated that representation effect as a decision mismatch. The guard now
  propagates the 12-decimal half-quantum through the frozen gain and adds the
  raw-code half-quantum, while retaining exact integer request, code,
  counterfactual, limiter, state and reason comparisons.
- Capture closed after complete terminal generation 1255 but while generation
  1256 had begun. The analyzer correctly refused to fall back across newer
  negative evidence. Capture shutdown now drains any already-started atomic
  ACTIVE status generation before closing; a bounded second signal still
  terminates a genuinely stuck burst without reclassifying it as complete.

The pre-entry audit also found that the 43,200-second qualified duration was
implemented using host UTC from when the supervisor observed the qualifying
row. The frozen origin is instead the first qualifying estimate itself. The
supervisor now persists that estimate's `rp2040_timer0` timestamp and capture
session, closes correction admission at device-time +41,400 seconds, and ends
qualification at device-time +43,200 seconds. Host UTC is retained only as
observation provenance; forward or backward host clock changes cannot move the
scientific boundaries.

## Attempt 8 gate

Attempt 7 consumed activation v7. At that terminal no physical authority
remained effective and no run was active. Attempt 8 could enter only after the response
window, serialization, terminal-generation and qualified-clock regressions
pass together; the complete post-response seam is accelerated through phase-4
acknowledgement, tight reacquisition, later re-arm, a second material
transaction, correction-admission close, qualified endpoint, analysis, seal
and registration; the affected exact firmware profile builds; and a new clean
bundle, structural preflight, full live-topology rehearsal and immutable
activation bind the new source and UF2 identities. Scientific thresholds,
duration, topology, setup code, actuator limits and progressive authority are
unchanged.

Those gates passed at source revision
`524c9d4e6fa4dd0aff4e787d3b5221f7b4390888`. The exact firmware source
semantic SHA-256 is
`1aa15e0a88c1090afb751d1418a381a6c2ce4b84542508572a436e0841ab42e2`,
the unchanged configuration SHA-256 is
`f800a4b7725992b01682e6d2c9e2be6fa15c956e23662622a928cdd4abe40990`,
and UF2 SHA-256 is
`cdb6c4f413dddf768b444126ea44646ff5d88f7b3073b0ac646ef4c8c7a095ac`.
All 878 current tests passed with 27 historical-revision tests excluded; all
seven supported profiles built and all six expected-failure profiles matched
their declared failures.

Bundle v16 has semantic SHA-256
`6c5380f7a2f6dfe20c64f0eb330ce06a6d068475db26de874ba7e9000bc822f4`;
proposal v16 has semantic SHA-256
`6f964af71fd9a99f0a7548110797c1fd194ae5d8d07cf6c1cf3e262279a2bfe8`;
and structural preflight v16 passed with semantic SHA-256
`320bfa516b019ef9ddada8b95dbab902068e0c8d0f7db905c043b05755edb1e0`.
The complete live-topology rehearsal passed with semantic SHA-256
`5448f46def92fdde0ac2339be967e031d48a7edf527c2be7f57e7a55495075d4`.
It additionally proves the device-domain 41,400/43,200-second boundaries
against forward and backward host UTC changes.

Attempt-8 activation v8 is effective with semantic SHA-256
`5bd6347234547a3e5e3c2cef29bea3055881e707c3c9a5f684c2d202fdecf788`.
It binds the attempt-7 terminal, bundle v16, the complete rehearsal, board
serial `503533748A919118`, `/dev/cu.usbmodem14601`, one flash, one exact setup
application, one finite live acquisition and the unchanged progressive
authority envelope. It is not an automatic retry and is consumed by the first
attempt-8 physical terminal.
