# OTIS Targeted Equilibrium Characterization V1

Status: attempt 6 completed the full prospectively frozen acquisition and its
authority is consumed. All 12 dwells, 21 identification supports, and 15
held-out supports passed their evidence gates. The frozen analyzer selected no
eligible model and reached the valid scientific terminal
`equilibrium_state_not_observable`. The corrected 115200-to-9600 GNSS
transition remained qualified through the terminal. No further physical
authority or automatic successor exists.

## Frozen campaign preparation

The authorized programme froze one firmware flash, one finite live run, twelve
predetermined open-loop DAC stimuli, no automatic retry or restore, and no
frequency, phase, or hybrid control authority. The exact programme is
`profiles/qualification/otis_targeted_equilibrium_characterization_v1.json`.

The exact firmware profile `cx319_range_map_part_a` compiled within its frozen
resource budget. Important identities are:

- bundle semantic SHA-256:
  `4d69a99cbd0483241035912974dca2476283dadf553f4a92df70d1be2ca69343`;
- bundle file SHA-256:
  `f66e4ffdaf9f9fc5dffd196d06035b89c99bb98d86b9217731bf928d2e94daa6`;
- build invocation:
  `11b02d72fd9fe14e046a3f3064306afb5582aee9d824cb1b35a49d62a235c43a`;
- firmware source SHA-256:
  `51da89840e679dc6421119a56e48b25d8f74df234447ca0a2206bbb0c809a825`;
- firmware configuration SHA-256:
  `ae9a63b75fe010c8e539108f0f902801aa7d824d5a548797f78a51811a053b74`;
  and
- UF2 SHA-256:
  `4e06efdaafd8e28b571c0b049c581b5dad12e61208dcf8e9f379efd7f65e1dab`.

The no-I/O structural preflight passed all checks. The exact operational-path
rehearsal also passed, including sole serial ownership, all twelve repeated
transactions and their first dependent consumers, normal-FIFO obstruction,
independent priority abort, same-PID logical rotation, the actual analyzer and
seal, and temporary evidence registration. Its result file SHA-256 is
`2e8e58448e4619a635d257929520b518a498a419677bc5f5d3a978fb4375d9ea`.

## Physical attempt 1 terminal

The runner activated bundle
`4d69a99cbd0483241035912974dca2476283dadf553f4a92df70d1be2ca69343`,
flashed the exact UF2 once, and established capture as the sole owner of board
serial `503533748A919118`. It remained at the prewrite gate for the frozen 720
seconds and stopped with:

```text
timed out waiting for exact firmware, GNSS, D14, D8, and partition prewrite gate
```

The terminal is a firmware defect under intended startup integration, not a
scientific rejection. No dwell started. `csv/dac_steps.csv` contains only its
header, so the campaign issued zero DAC stimuli. Capture parsed 18,661 records
with zero parser errors and zero reconnects. D14 PPS remained present, D8 count
validity remained valid, association remained clean, the dual-core partition
reported no fault, and telemetry dropped zero records. The independent
`ACTIVE ABORT` was accepted and physically sent before the sole capture owner
closed.

The raw acquisition, failed analysis, seal, and registry record are retained at
`runs/otis_targeted_equilibrium_characterization_v1/campaign_20260825T140134Z/live_attempt1_20260825T140809Z`.
The registered content SHA-256 is
`689b40df0c03a46dda41650d31580fb7a4d640e500fc3fcbf5e9f93cec4974a3`;
the snapshot digest is
`461b7544e39f1a0df4512aa93eba21500d04348b477328f83357e7e92aa9cbbc`;
and the immutable seal semantic SHA-256 is
`d822fc90d05e147353672a838484509dee78f5d245237be7a646ccb714aa287e`.

## Separate baud and output-configuration conclusions

The MT3339 PMTK command document defines `PMTK251` as a set-only NMEA-port
baud command. It defines no query/data pair for current UART baud. An
affirmative checksum-valid receiver response after the MCU changes its UART to
115200 is therefore the physical baud proof. `PMTK414` and `PMTK514` query and
report NMEA sentence output frequencies; they do not report baud.

The retained physical evidence establishes the 9600-to-115200 transition:

- target-first discovery rejected 115200 exactly once, then found the receiver
  at 9600;
- the state machine sent the fixed `PMTK251,115200` packet and selected 115200;
- the target candidate then retained 5,740 checksum-valid frames with zero
  transmit failures and zero link losses;
- `candidate_rejection_count` remained exactly one while
  `configuration_failure_count` reached 717.

That last relationship is decision-bearing. In the frozen state machine, a
missing identity response during ordinary candidate discovery increments the
candidate-rejection counter and moves to another baud. A configuration failure
can be reached only after the transition target path or after a successful
identity response has advanced into output-query/configuration processing.
After every configuration failure, discovery restarts at 115200. The fixed
candidate-rejection count with hundreds of later configuration-stage failures
therefore proves repeated successful target-baud identity communication.

The one-time baud-change qualification is **passed**. It is reusable without a
special baud-transition gate while firmware transition semantics and
configuration, PA1616S/MT3339 receiver identity, wiring, and other
decision-relevant inputs remain unchanged. Future campaigns still require
their ordinary contemporaneous GNSS metadata and D14 health gates.

The distinct `PMTK414`/`PMTK514` output-configuration verification is
**failed**. The frozen implementation clears `confirmed_baud` when that later
stage restarts discovery, which caused the immutable campaign analyzer to
report the combined GNSS qualification as failed. That historical result is
preserved; it must not be rewritten as a successful campaign.

## Smallest corrective next step

Before another physical attempt, separate baud-transition evidence from
output-configuration evidence in firmware telemetry. Retain at least the last
successful identity-response baud, identity-response count, exact link-state
phase, output-response count, last PMTK response packet type, PMTK001 command
and flag, and the observed PMTK514 field count/values or a lossless bounded
equivalent. Add a deterministic regression through the first downstream
prewrite decision, then build and rehearse a new exact bundle.

The next live activity is a shortest physical qualification of the corrected
PMTK414/514 path followed by the finite characterization only if that ordinary
GNSS configuration gate passes. It requires separate new flash/run authority;
attempt 1's authority is consumed and automatic retry remains forbidden.

## Authorized corrective attempt 2 preparation

The operator separately authorized one next attempt on 2026-08-25. Its
prospective contract is
`profiles/qualification/otis_targeted_equilibrium_characterization_attempt2_v1.json`.
It preserves the attempt-1 terminal lineage, reuses the already-passed baud
qualification, retains one flash and one physical run with no retry or restore,
and changes only the output-configuration integration and its observability.

Attempt 2 accepts either an exact 19-field `PMTK514` response or, for receiver
firmware that does not answer `PMTK414`, the exact `PMTK314` command accepted by
`PMTK001,314,3` followed by a 2.5-second checksum-valid observation containing
RMC, GGA, and GSA and no other NMEA sentence type. The method, phase, last
identity-response baud, response and timeout counters, acknowledgement, field
signature, and observed masks are emitted as persistent status. This fallback
does not weaken the required output configuration; it establishes the same
configured result from direct receiver output when query/readback is absent.

## Physical attempt 2 terminal

Attempt 2 used campaign root
`runs/otis_targeted_equilibrium_characterization_v1/campaign_attempt2_20260825T150616Z`.
Release verification passed 1,072 current host/native tests, all ten supported
firmware profiles, and all eight expected-failure guards. The campaign-local
exact bundle semantic SHA-256 was
`400049eef178ff1399fa0b1a3bd4c97819cfd24b66f5c78f60265598bbbb5d5c`;
its exact UF2 SHA-256 was
`b79985b68157f55aca6de3ea01739f156d6281262dddfb1a142b35fdbd25baea`.
Structural preflight and the complete operational-path rehearsal passed. The
rehearsal result file SHA-256 was
`f5b3c09f823b58b222b2449edf454077b4ddfe210085fdd9844f72ef446382a4`.

The runner flashed once and stopped fail-static at the 720-second prewrite
deadline. It issued zero DAC stimuli and completed zero scientific dwells. It
captured 723 D14 events and D8 count intervals with no parser errors or serial
reconnects, then sent the independent priority abort before the sole serial
owner closed. Analysis, sealing, evidence snapshotting, and registration all
passed. The evidence content SHA-256 is
`b5b5e098e250522bc19bff14f76b7db40fa2f34df3bda733719591e3d36a4f85`;
the snapshot digest is
`af38182671db7445dc05f84915b295c033c9430a794ec980a1cb46440cb16f1f`;
and the seal semantic SHA-256 is
`d034d5d7974e6cd3c37edf7f4837a1b1e09640a8357df0298da478986268feab`.

Attempt 2 made the physical response mismatch explicit. The receiver accepted
the fixed PMTK314 command with `PMTK001,314,3` and repeatedly returned a
checksum-valid 22-field PMTK514 signature
`0101100000000000000000`. The attempt-2 decoder required 19 fields, recorded 64
configuration failures, and therefore correctly refused the campaign even
after the strict direct-observation fallback later reached online with observed
mask 7 and unexpected mask 0. The terminal retained confirmed baud 115200,
last identity-response baud 115200, zero transmit failures, and zero link
losses. This independently reaffirms the baud qualification and localizes the
remaining defect to PMTK514 response shape.

This was an avoidable verification escape. Structural preflight was correctly
no-I/O, but after attempt 1 localized uncertainty to the GNSS protocol, the
attempt-2 operational rehearsal should have exercised the actual
PA1616S/firmware transaction before the campaign bundle was frozen and
activated. Its PTY fixture encoded the same unproved 19-field assumption as the
firmware, so agreement between those two synthetic consumers was not receiver
compatibility evidence. Future work must use a short zero-DAC hardware-in-loop
GNSS entry rehearsal for a changed receiver protocol boundary, retain the real
response, and promote the same flashed firmware and sole-owner process into the
campaign only after that boundary passes.

The smallest offline correction accepts only the documented 19-field response
or the observed 22-field response with the exact common prefix and three zero
extension fields. It rejects any nonzero extension. A deterministic firmware
regression and the first host prewrite consumer now cover both acceptance and
rejection. Attempt 2 authority is consumed; another physical run requires new
operator authority and a newly frozen exact bundle and rehearsal.

The corrected `cx319_range_map_part_a` profile compiles within its resource
budget. This offline candidate has firmware source SHA-256
`640e8b81d2974bdef99e6e7d751f5eb36a45c1a49cbf5076cafebb7700f19d79`,
build invocation
`1f372e0ba39a22e7d29666596500fd055416200bad586386c6beb0c65c962a3f`,
and UF2 SHA-256
`d7203e8d5b4ce356c7124e67e08c57c5c234a65d7cc3541fd85cceba3c3386c6`.
It is not a live-authorized or frozen campaign bundle.

Post-correction release verification passed 1,073 current host/native tests,
all ten supported firmware profiles, and all eight expected-failure guards.
This does not authorize another flash or physical run. It establishes that the
narrow firmware correction is ready to enter the next exact hardware-in-loop
rehearsal when separately authorized.

The attempt-2 stop must not be generalized into treating host tooling as
scientific truth. It was a flashed-firmware state-machine failure at a frozen
prewrite gate, before any acquisition stimulus. If a future failure is confined
to a deterministic host analyzer, finalizer, or test harness after raw
acquisition is complete and sufficient, OTIS must retain that acquisition,
repair and replay the offline consumer, and avoid an unnecessary flash or
physical rerun.

## Physical attempt 3 terminal

Attempt 3 used campaign root
`runs/otis_targeted_equilibrium_characterization_v1/campaign_attempt3_20260825T155902Z`.
Its exact bundle semantic SHA-256 was
`4d4caf2b26607dcf550cd4a78251ba6c8ffed8ab64791da4ea72f86da6e977a1`;
the exact UF2 SHA-256 was
`d97bfa1bd3e0931af17c319468ede527bf3241ce34ad42823ff416045bc51abf`.
The structural preflight and complete host operational-path rehearsal passed,
but the rehearsal did not inject a transient receiver-qualification loss
through the actual live runner wait semantics.

The runner flashed once, established one continuous serial owner, and passed
the complete zero-DAC live prewrite gate. The real receiver reported identity
`AXN_5.1.6_3333_18041700`, confirmed and last-identity-response baud 115200,
`pmtk514_exact`, 22 configuration fields, and exact signature
`0101100000000000000000`, with zero configuration, transmit, or link failures.
This physically qualifies the corrected PA1616S output-configuration path and
reaffirms the already-reusable baud result. Neither is the scientific target
of another unchanged run.

During the capture-owned warmup, one status burst reported metadata age 2.688
seconds and `checksum_requalified=false`, causing
`metadata_control_eligible=false`; D14/raw-PPS qualification remained true.
The frozen host runner treated that single transient status as an immediate
terminal contradiction, submitted and delivered the priority abort, and
closed capture before any DAC stimulus. Earlier in the same retained stream,
the prewrite gate had correctly waited through two such false status bursts and
their subsequent requalification. The differing post-gate behavior was
therefore a host runtime-policy defect, not a firmware identity, baud,
configuration, D14, D8, plant, or scientific failure.

Attempt 3 is classified as a platform escape into a campaign. It captured 699
D14 events and 699 D8 count intervals, issued zero DAC stimuli, completed zero
scientific dwells, parsed 19,121 records with zero parser errors or reconnects,
and delivered the independent abort before the sole owner closed. Analysis,
sealing, snapshotting, and registration completed. The evidence content
SHA-256 is
`55187f88ab6d490a1f5339f70d668623ea403d1248d6e8ee866af31c4b9c2311`;
the snapshot digest is
`20234cf6f6b32e8e71bfb5cc7ed243872fab7d68cefde499fde398832c6915d3`;
and the seal semantic SHA-256 is
`f76f0976712f35b3f100b395bebdee22eaafc23518cfa2e18668977ed7b3de79`.

## Authorized corrective attempt 4 preparation

The operator separately authorized one attempt 4 on 2026-08-25. Its
prospective contract is
`profiles/qualification/otis_targeted_equilibrium_characterization_attempt4_v1.json`.
It retains the exact scientific question, dwell order, timing, identification
and held-out partitions, acceptance criteria, zero automatic control
authority, one flash, one physical run, and no automatic retry or restoration.

The narrow host correction classifies only
`metadata_control_eligible` and `raw_pps_control_eligible` as bounded hold
conditions after prewrite. Capture continues, but the current dependent
predicate cannot complete until the status requalifies. The existing frozen
operation timeout supplies the deadline. Receiver identity, 115200 baud,
configuration identity, output signature, link state and persistent failure
counters remain immediate invariant failures, as do capture, serial, queue,
partition, or evidence faults. Scientific support can never be accepted from
an unqualified snapshot.

The deterministic regression covers the exact attempt-3 false-to-true
transition and verifies that progress is held then resumed. The operational
rehearsal now injects that transition through the actual capture parser and
targeted runtime guard in addition to its complete 12-transaction, first-
consumer, obstruction, abort, rotation, analyzer, seal, and registration path.

## Physical attempt 4 terminal

Attempt 4 used campaign root
`runs/otis_targeted_equilibrium_characterization_v1/campaign_attempt4_20260825T164928Z`.
Its exact bundle semantic SHA-256 was
`bb37354de62121a597d9f876ea555ea79ac59f35488318996e1c5da8c8e3941a`;
the bundle file SHA-256 was
`a27f041ed65fd6c6ba5431208ce403c9fb76e8cb47773046805cb531c884239f`;
and the flashed UF2 SHA-256 was
`e808524a9fca56576bccd8c25a59280813c1534ebc7e73767ae2b266b3577258`.
Structural preflight and the exact operational-path rehearsal passed. The
rehearsal result file SHA-256 was
`db0fea284df66a5924312e8de4406fed68f403c6713ddc8b0f3e6cdb9719e8e9`.

The runner flashed once, established the sole serial owner, and passed the
complete zero-DAC prewrite gate. The receiver again reported 115200 baud,
`pmtk514_exact`, the qualified 22-field signature
`0101100000000000000000`, and zero configuration, transmission, or link
failures. This reuses the already-passed GNSS baud and output-configuration
qualification; neither was the scientific target.

After the 1,800-second warmup, the runner applied the first frozen centre code
`0xA83E` and observed exact DAC epoch 1 propagation. The physical dwell then
ran beyond its 2,700-second minimum. D14/D8 capture retained 4,625 valid
one-second count intervals with zero parser errors, reconnects, or command
rejections. After the 900-second settling exclusion, the retained canonical
counts contain three exact contiguous 600-interval windows:

- count sequences 2706..3305: 6,000,000,003 edges, or +3 edge counts;
- count sequences 3306..3905: 6,000,000,002 edges, or +2 edge counts; and
- count sequences 3906..4505: 6,000,000,001 edges, or +1 edge count.

All three windows have the expected D8 source, flags, and continuous D14 gate
boundaries. They establish that the first dwell's requested scientific
measurement was physically present in the canonical evidence. They do not
complete the twelve-dwell programme or support an equilibrium-model verdict.

The frozen firmware nevertheless produced no selected-600/TDB row. There were
18 brief GNSS metadata dequalifications after the DAC application, with no gap
longer than 350.000002 seconds. The range-map preview passed the combined
serial-metadata receiver qualification into the selected estimator, so every
metadata dip reset its 600-second support even though D14/raw-PPS and D8 count
validity remained continuous. The attempt-4 host correction correctly held
rather than aborting on each transient, but it could not recover support that
the firmware had discarded. At the 2,820-second dwell deadline the runner
delivered the priority abort, closed capture, analyzed, sealed, snapshotted,
and registered the evidence.

This is a platform escape into a campaign, not a scientific rejection. The
rehearsal injected a transient through the host guard but supplied synthetic
TDB rows directly; it therefore failed to exercise the firmware producer reset
and the first downstream consumer together. The evidence content SHA-256 is
`7a224c973f5709e45f7fd449719d33580a8b7eb1e12bdd7a42d58d1cd47fe857`;
the snapshot digest is
`1beba88adeedc0ca20b9c6d5f3f142af081691d9ff2058276defaf54ccb00220`;
the analysis semantic SHA-256 is
`7149f34fd153120829ab82876ba53a0a4ac961de78078d7e29021d0928375878`;
and the seal semantic SHA-256 is
`7c4da17e6e871e78c255de590bb7afce1be176cfd2bc6d8b1331969484728b03`.

## Post-attempt-4 correction and next gate

For the non-actuating CX319 range-map profile only, selected-frequency preview
validity now follows the already-qualified D14/D8 interval. A transient GNSS
serial-metadata dequalification remains recorded and holds host progress until
requalification, but it no longer erases valid D14 timing support. Invalid D14
or D8 evidence still resets support. Profiles that can participate in control
retain the stricter combined receiver-metadata gate.

The direct firmware truth-table regression proves those profile boundaries.
The operational rehearsal now injects a metadata false/true transition inside
every one of the twelve dwells, verifies that TDB evidence remains retained,
and proves that host progress resumes only after requalification. The focused
campaign and firmware-boundary gate passed 45 tests. The affected
`cx319_range_map_part_a` build passed within its resource budget with candidate
source SHA-256
`d0ce486f75e4ef2d3d5e0fb6793a474ed92624cba03b523fa701e81ce800089e`,
build invocation
`03db1fe5ec5c1781ef79fc199541878a5f797ec7084635441c5bcd1b70fb39fe`,
and UF2 SHA-256
`8b47ee4e008526a62278cea2c384158e9d533747b4b94af88124961b782bdd2c`.
These are offline candidate identities, not an effective live bundle.

Post-correction release verification passed 1,076 current host/native tests,
all ten supported firmware profiles, and all eight expected-failure guards.
The release matrix SHA-256 is
`16d19917867d751780b450f7057479873f097db76ad15e5963fb237bb6d08d51`.

The next gate, only with separate operator authority, is a new attempt-5 exact
bundle, structural preflight, complete operational-path rehearsal, and one
finite live run. Attempt 4 cannot be retried and there is no current physical
authority.

## Authorized attempt 5 and 9600-baud return

The operator separately authorized attempt 5 on 2026-08-25 and directed the
campaign to return the PA1616S NMEA port to 9600 baud so the scientific
characterization would not depend on resolving the sparse 115200-baud frame
corruption first. Because the receiver could still be operating at 115200, the
prospective gate required discovery at either 9600 or 115200, the fixed
`PMTK251,9600*17` transition when needed, and fresh checksum-valid identity and
exact output-configuration evidence at 9600 before any DAC write.

The exact attempt-5 bundle semantic SHA-256 was
`cfa3bd680aef41db0d36e3b4d8b0de3d18afe1c8bf3986ec6647e6e8aadab255`;
its file SHA-256 was
`ee79f48b92c23e60d29b199faefeadeda47f58dd9947207f5f0030a1c4c3f001`;
and its UF2 SHA-256 was
`db16bc0d00c8f7e6a620491c689a4dd1ad235274c61776fa44be72bc82ea2ca9`.
The no-I/O structural preflight passed. The complete operational rehearsal
also passed all twelve repeated transactions, a metadata false/true transition
inside every dwell, retained selected-600 support through every transition,
obstruction and independent abort, rotation, analysis, sealing, and temporary
registration. Its result file SHA-256 was
`3029c9076f1e028f166836832be875922afc0382a72c123b494963e5de0b047f`.

## Physical attempt 5 terminal

Attempt 5 used campaign root
`runs/otis_targeted_equilibrium_characterization_v1/campaign_attempt5_20260825T214537Z`
and run `live_attempt5_20260825T215009Z`. The runner flashed once, established
the sole serial owner, and retained the complete prewrite boundary. It found
the receiver repeatedly at 115200, reported `last_identity_response_baud=115200`,
entered `await_target_identity_response` at candidate 9600, and never received
the required target-baud identity response. At the 720-second prewrite
deadline, the runner delivered the priority abort and finalized normally.

The decisive compiled-artifact check showed why: the frozen ELF contained
`$PMTK251,115200*1F` and did not contain `$PMTK251,9600*17`. The selected baud
macro was visible to the sketch status path but `otis_gnss_receiver.cpp`
selected its command before including `otis_config.h`, so that separate
translation unit compiled the wrong conditional branch. Source-level tests
had supplied the macro directly and the build manifest recorded the intended
selector; neither proved the emitted command. This is a platform escape into a
campaign and an avoidable preflight defect.

No DAC stimulus was issued and no scientific dwell started. The retained run
contains 723 D14 events and 723 D8 count intervals, zero capture parser errors,
zero reconnects, zero command rejections, and one delivered emergency abort.
Its evidence-content SHA-256 is
`4ebfbee8c785d2e329e428f89f06bc3ae87091aae4103974e42467d4cc33021d`;
snapshot digest is
`1cf818258c0d7becea535ae9f2914bbf4760018892c8f8f742e919c4d9635e0a`;
analysis semantic SHA-256 is
`845f0c99c4aa19546fc38a99ec8305d9a695c6daefc038b2da2e9b5dced4834b`;
and seal semantic SHA-256 is
`e223be791036f9d04452f79aaa6c11f3af6418ab53ea85958fa33c448adfcb2f`.

## Post-attempt-5 correction and next gate

The GNSS translation unit now includes `otis_config.h` before selecting the
target command. The affected `cx319_range_map_part_a` candidate build passed
within budget with source SHA-256
`a4d0e855c81144912885f45d7151d570e8f3a30511e88288699ddf57780ce806`,
build invocation
`cde9c2f63dfee497f3549df59ea666996b470464468104d4742b61b3cd41dfd6`,
and UF2 SHA-256
`7b39c4f4147fb767b25106015816691d9a6fae005f0e396400aef5ce5979127a`.
Its manifest-bound ELF contains only the selected `$PMTK251,9600*17` target
command; the opposite 115200 target command is absent. Exact bundle creation
and preflight now bind and inspect that ELF fact rather than trusting source or
declared defines alone.

These are offline candidate results, not a live bundle or authority. The next
gate requires separate attempt-6 authority, a new exact bundle using the
corrected candidate identities, structural preflight, complete operational
rehearsal, and one finite live run. Attempt 5 cannot be retried.

## Authorized attempt 6 exact bundle

The operator separately authorized attempt 6 on 2026-08-26. Its layered
programme is
`profiles/qualification/otis_targeted_equilibrium_characterization_attempt6_v1.json`.
It retained the exact twelve-dwell science, one flash, one finite run, no
automatic retry or restore, and no frequency, phase, or hybrid actuation
authority. It bound attempt 5's terminal seal and required the compiled ELF,
not only source and declared selectors, to contain `$PMTK251,9600*17` and omit
the opposite 115200 target command.

The exact campaign root is
`runs/otis_targeted_equilibrium_characterization_v1/campaign_attempt6_20260826T061717Z`.
Important identities are:

- bundle semantic SHA-256:
  `8a1e06d438ca05c5caca8869ea3e5c8b2566b1d394523fd0edcc4436834d9b1a`;
- bundle file SHA-256:
  `396bb18c72845f506586338c6cf67b73b9d8be9ad9367cea47e15898defe0269`;
- firmware source SHA-256:
  `a4d0e855c81144912885f45d7151d570e8f3a30511e88288699ddf57780ce806`;
- build invocation:
  `59825e34b8326577f4c63dd706ce8f665e3b7bba7923b68883039b11ebf52fc6`;
- ELF SHA-256:
  `f91b3955542f6a9d16200d74edd64cafdfc780dc6fdc8792a4907cafebba4d05`;
  and
- UF2 SHA-256:
  `efc1fb89b364b9f77f143173a064b8e171605b22edb80df435ed1a62dfe87b4c`.

Structural preflight passed all 13 checks, including the manifest-bound
compiled-command audit. The exact operational rehearsal passed all declared
real host boundaries, all twelve repeated transactions, twelve forced GNSS
hold/requalification cycles with retained D14/D8 support, obstruction and
priority abort, atomic rotation, analysis, sealing, and registration. Its
result semantic SHA-256 is
`08226797002d9ac9804f1641c64070bfe24cbb892cf1f2eb23d08f77e0906b5d`
and file SHA-256 is
`426134113ccfbcdf188a8f08a1d8312cde690e492c462052b9b24b804ba6f760`.

## Physical attempt 6 and scientific terminal

Run `live_attempt6_20260826T062115Z` flashed once and retained one continuous
serial owner. Discovery first rejected the 9600 candidate, found the receiver
at its retained 115200 baud, sent the compiled 9600 transition command, and
then recorded fresh checksum-valid identity at 9600. The prewrite gate passed
at 2026-08-26T06:31:37Z after the full ordinary D14/D8 startup qualification.
Terminal GNSS state remained online and configuration-confirmed with
`confirmed_baud=9600`, `last_identity_response_baud=9600`, the exact 22-field
PMTK514 signature, 137028 checksum-valid frames, and zero checksum, truncation,
oversize, configuration, transmit, or link-loss failures. This proves the
115200-to-9600 change for the frozen receiver, wiring, and firmware inputs; it
is not a special gate for unchanged future runs.

All twelve predetermined applications and all 36 selected 600-second supports
completed. The retained integer edge-error counts were:

| Dwell | Code | Partition | Counts |
|---:|---:|---|---|
| 1 | 43070 | identification | `1, 2, 2` |
| 2 | 43046 | identification | `-1, -1, -1` |
| 3 | 43070 | identification | `2, 2, 2` |
| 4 | 43094 | identification | `5, 4, 4` |
| 5 | 43070 | identification | `2, 2, 1` |
| 6 | 43046 | identification | `0, -1, 0` |
| 7 | 43070 | identification | `2, 1, 1` |
| 8 | 43094 | held out | `4, 5, 4` |
| 9 | 43070 | held out | `2, 2, 1` |
| 10 | 43046 | held out | `-1, -1, 0` |
| 11 | 43070 | held out | `1, 2, 2` |
| 12 | 43094 | held out | `4, 5, 4` |

The exact analyzer found all three frozen model families structurally
identifiable, but every minimum, nominal, and maximum gain case had an empty
complete identification interval. No model was eligible, so the terminal is
`equilibrium_state_not_observable`; it is not an evidence failure. Nearby SHT41
air temperature ranged from 26.010 to 31.767 degrees C and remains a covariate,
not CX317 internal temperature.

The run stopped healthily at 2026-08-26T15:52:33Z with no automatic restore.
Capture retained 34264 D14 events and 34264 D8 count intervals, 939680 parsed
records, zero host parser errors, zero reconnects, zero rejected commands, and
no emergency abort. Analysis semantic SHA-256 is
`29e19780ce3e32a4c568cb886f42d1504e0658a82b91c7f73b7629bc9f48301e`;
seal semantic SHA-256 is
`f1271d28add908db4d50053f2b0d33115dff437b78819aad33aa413f05972e96`;
snapshot digest is
`50c5e5e1fc3d17dcb5bb53bf3cb1a03d5cb27e2683fe42e24367f30c3b9370d5`;
and registered content SHA-256 is
`ab9d58a76de1340c15a271e0e124eb16b0e2665278e8046e9c146f3468922bbb`.

Attempt 6 closes this characterization decision. It grants no control
authority and does not select an equilibrium estimator. Any successor requires
a separate architectural decision and explicit authority; it is not attempt 7
or an automatic continuation of this campaign.
