# Frequency-only Attempt 9 result and 72-hour readiness

## Verdict

Frequency-only Attempt 9 is a **successful engineering acquisition with a
host-side platform escape**. The physical acquisition, D14/D8 measurement,
frequency steering, D9 digital configuration/readback, D6 diagnostic capture,
GNSS metadata path and serial closure passed. The original supervisor terminal
remains preserved as
`frequency_only_d9_d6_digital_endurance_incomplete`; a separate registered
host-only replay supersedes that verdict with
`frequency_only_d9_d6_digital_endurance_passed`.

The replay changed no raw evidence, firmware behavior, command, DAC state,
criterion or waveform claim. It performed no hardware interaction and required
no physical rerun.

## Acquisition result

- Run: `runs/d9_adaptive_steering_integration_20260828/long_runs/frequency_only_24h_attempt9`
- End-to-end interval: `2026-08-29T00:39:23.205803Z` through
  `2026-08-30T03:21:59.071956Z`, or 26 h 42 min 35.866 s.
- Qualified D14/D8 duration: 86,400 s, including all four 21,600 s
  milestones.
- Capture closure: return code 0, zero reconnects, parser errors, malformed
  UTF-8 records, rejected commands or owner transfer.
- Setup: exactly one application at `0xA808`.
- Automatic steering: three complete request/application/first-consumer/
  response transactions, `+21`, `+21`, and `+14` codes, ending at `0xA840`.
  Total automatic movement was 56 codes; no authority ceiling bound the run.
- The selected 600-reference-interval estimator moved from approximately
  -0.015 Hz before correction to a final long stationary epoch mean of
  -0.003101852 Hz (-0.310 ppb), RMS 0.003209506 Hz. The final epoch retained
  144 qualified windows without another demanded correction.
- Final-epoch OLS drift was +0.0000278515 Hz/hour, approximately
  +0.0006684 Hz/day toward nominal. This is observational drift evidence, not
  a claim of a permanent equilibrium DAC code.
- Offline candidate-window comparison classifies 60, 120 and 300 reference
  intervals as too short; 600, 1,200 and 1,800 as appropriate under the
  predeclared noise/group-delay rule. Only the deployed 600-window estimator
  had runtime authority; no retuning follows from this report.
- D9 source/divider/GPIO/readback remained exact at analysis.
- D6 retained 96,146 valid, sequence-continuous snapshots. D6 remained a
  zero-authority local diagnostic throughout.
- Complete retained source reconstructs 96,146 canonical D14/D8 intervals:
  96,145 qualify and the first lacks its pre-run opening snapshot. D14 remains
  the sole timing reference and D8 the sole oscillator/control truth.
- No GNSS metadata hold occurred. The run therefore confirms healthy normal
  metadata operation but does not claim that a naturally occurring holdover
  episode was observed; no GNSS glitch was forced.
- This run was frequency-only. Hybrid/PLL authority was absent.
- The 1 kΩ D9-to-D6 link was digitally observed, but no oscilloscope or
  independently referenced waveform qualification occurred. Voltage margin,
  duty cycle, edges, ringing, load response, delay, jitter and delivered
  waveform frequency remain unresolved.

## Preserved host escape and correction

Two deterministic host defects were corrected.

1. The host saw zero-authority control previews before the independently
   flushed application records and permanently classified them
   `ineligible_not_authorized`. Replay binds the later exact application rows
   to the same control identities at decision sequences 4, 6 and 8 and
   transaction record sequences 4, 8 and 12. Corrected dispositions are three
   `applied`, four `cadence_hold`, 144 `no_demand`, one
   `settling_or_requalification_hold`, and one genuinely
   `ineligible_not_authorized`.
2. The live interval reader read REF/SNP support before the CNT commit frontier.
   A concurrent append could therefore be retained as a false missing-support
   interval. Complete-source replay recovers all 7,340 such exclusions. The
   original conservative accounting had already reached 86,400 qualified
   seconds, so recovery does not create the pass or move its criterion.

The same audit found and corrected an offline clock-domain defect: candidate
frequency was being divided by RP2040 timer ticks as though that timer were the
reference. D14 reference intervals now define D14-relative frequency; RP2040
ticks remain aperture diagnostics. Variable-duration regressions protect this
boundary.

The original failure is preserved and registered:

- original content SHA-256:
  `a303a80d8e81f09e0dc09122fc97fefbd506e47c418444ca3b9be23d9f94159c`;
- original seal SHA-256:
  `077fdf7fd37351238f041867613154659827ec9dfad23b130928b9af6a590579`;
- classification: `failed_qualification` with the unchanged incomplete
  terminal.

The separate successful product is:

- directory:
  `runs/d9_adaptive_steering_integration_20260828/long_runs/frequency_only_24h_attempt9_reanalysis_v1`;
- derived content SHA-256:
  `f93495719ce0a8648d115e25836b27e777b5f9c3593be58b3e9ea7360620d03e`;
- analysis file SHA-256:
  `41f15f70805df8c8c1f78b576a843380ea66742e5fc7a325e91aec162eaab956`;
- supersession SHA-256:
  `5723dec78f56f7a5b50dacb82b8388749c6c7bf3f4d5b1b8f35da26f99e9c076`;
- superseding seal SHA-256:
  `ea6fd21b8b1665d43e6a48218d1fe28f69dfed1cf63d8c79ad56baaec80c9ceb`;
- classification: `completed_campaign`.

## 72-hour joined readiness

The 72-hour programme is prepared but has **not** been launched. Its live
identity is now joined across programme status, engineering contract, firmware
profile and defines, emitted run/profile/build identities, host contracts,
bundle, proposal, rehearsal, activation, adapter and planned runner arguments.

- Programme: `OTIS_CX322_D9_D6_72H_INTEGRATED_ENGINEERING_V1`.
- Profile/run identity: `cx322_d9_d6_72h_sustained_engineering` /
  `cx322_d9_d6_72h_sustained_engineering:1`.
- Exact unchanged firmware source revision: `5ab1a24692749ac86cadc50cea342b8c7e2c15e7`.
- UF2 SHA-256:
  `27b8c73a1ac6b4a8df55920a4641f4303af78688de2fa2eff2f7aa781661bab6`.
- Active-hybrid bundle semantic SHA-256:
  `7d7851bad6fe9d3261e18a2242f5c16c24d878f4ac354f34d591a02c3af4e985`.
- 72-hour adapter bundle SHA-256:
  `3836a213643001650881ebbf6f65a7514beee63d5e342b2cdef906396099295f`.
- Fresh complete operational rehearsal semantic SHA-256:
  `dc65375b9226eb7085c4e567481a3f51e116a8bea93e94322cc7f16942025af8`;
  report file SHA-256:
  `2f566fe8f2abcbb3f63c97305b40b533bc218b33b0a54e6e2fba6867e883f65c`.
- The Campaign18 wrapper independently repeated the complete rehearsal with
  semantic SHA-256
  `ba2b26dfb419dde74eb7d0539ccc0356bd615ddf6fe3344e6abb4ef231bac076`.
- Effective active-hybrid activation semantic SHA-256:
  `bc6f746b6aa82b146266ffe56b238becde79979fe5a29be1d93d44d408d8b567`.
- Effective adapter activation semantic SHA-256:
  `ea5b56f62dc6108cce5422bf3b6452f11e81758e92e9caf40cca8596c6371bde`.
- Planned run:
  `runs/d9_adaptive_steering_integration_20260828/long_runs/hybrid_72h_attempt1`.
  The run and adapter-output directories do not yet exist and the one-shot
  activation reservation is absent.
- Serial contract is 115200 with fresh
  `capture_device --auto-detect` on every enumeration and no stored device or
  board path. The readiness observation found exactly
  `/dev/cu.usbmodem14401` with no serial owner; the live runner must and will
  repeat this dynamic check rather than trust that observation.
- The programme provides 259,200 qualified seconds, a 280,800-second wall
  ceiling, 144 cadence-derived non-target automatic-application authority,
  3,024 cumulative codes, 21 codes per step, one setup at `0xA83C`, no retry,
  no restoration and a 1,500-second endpoint admission reserve.
- All live duration, endpoint, milestone, application, movement, monitor and
  analyzer predicates are derived from this 72-hour contract. The parent
  policy's 4-application/84-code figures remain controller-law provenance
  only and cannot limit or terminate this programme.
- The adapter bundle content-binds the successful Attempt9 product, its
  unchanged source evidence, analysis, supersession and seal. The joined entry
  preflight rejects any mismatch among that predecessor, the firmware,
  active-hybrid activation and Campaign18 adapter activation.
- The fresh rehearsal exercised the production capture, supervisor, analyzer,
  finalizer and registration path; exact AT2/AH2 joins; repeated requests 1 and
  2 through acknowledgement, application and first dependent consumers; GNSS
  metadata hold/requalification; serial obstruction; priority abort delivery;
  logical rotation; and clean sealing.
- The rehearsal captured 9/9 exact AT2 transaction sidecars and 10/10 exact
  AH2 decision sidecars before analysis and sealing. It also exercised GNSS
  bootstrap from `in_progress` to the exact fixed-115200 completion contract,
  then a recoverable control-only metadata hold, causal requalification and
  the first zero-authority dependent decision after recovery.
- Two rehearsal-only defects were caught before activation: a deferred
  post-requalification consumer was awaited too early, and an accelerated
  2,400-second fixture advance could overwrite the intermediate RP2040 timer
  frontier. The fixture now requires each sub-half-wrap frontier to be retained
  by the live supervisor before advancing. Neither failure touched hardware.
- Current release verification: 1,448 passed and 63 historical tests were
  deselected. The historical tests require their exact old revisions and local
  ignored campaign evidence; they are not current-release tests.

At live entry the runner still must repeat the dynamic physical gates after its
single exact flash: fresh device enumeration, sole serial ownership, firmware
run/profile/build identity, GNSS bootstrap completion and fresh same-receiver
metadata at 115200, D14/D8 authority and continuity, D9 configuration/readback,
D6 presence or explicit fail-local degradation, exact setup acceptance and
code/epoch propagation, independent abort readiness and quiescent transaction
state. Failure before setup remains a no-write abort. The run must remain under
active authoritative-state and evidence-freshness monitoring through its
terminal, finalization and registration.

Terminal: `frequency_only_attempt9_passed_72h_exact_activation_ready_not_launched`.
