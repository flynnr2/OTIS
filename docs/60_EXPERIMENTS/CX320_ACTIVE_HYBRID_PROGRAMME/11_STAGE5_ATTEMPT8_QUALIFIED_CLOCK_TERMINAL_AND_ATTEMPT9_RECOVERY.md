# CX320 Stage 5 Attempt 8 Qualified-Clock Terminal and Attempt 9 Recovery

## Attempt 8 retained result

Attempt 8 (`stage5_live_attempt8_20260820T1746Z`) flashed the exact frozen
firmware and confirmed board serial `503533748A919118`. Setup applied 43068
(`0xA83C`) once at DAC epoch 1. Capture remained continuous through the
terminal with no reconnect, parser error, rejected command or serial-owner
gap. Firmware produced one valid selected 600-second estimate and one combined
controller decision, which correctly remained a cadence hold. No automatic
DAC correction was requested or applied.

At the prospective qualified-origin boundary the host supervisor rejected the
selected estimate as having an incoherent device clock. It submitted and
delivered one bounded priority abort before qualification or hybrid actuation.
Firmware entered `FAIL_STATIC` at the unchanged code 43068. The retained
snapshot contains 30 artifacts with content digest
`98db22b5fa91a9ba65e0c2f9e99009ab3cf88ac936b91123674426e16389ac4e`.
The failed physical seal has semantic SHA-256
`f358f754eb07e1459a4891c30e1f05499ea9156bb5433a196a1790d50dd9d302`
and file SHA-256
`04d7726d756a068a17924802ff40ff79aa1c16352566ef25003ca568a3e6b239`.
This is a platform escape before the decision-bearing physical experiment, not
a scientific rejection of hybrid control.

## Exact failure mechanism

The qualifying estimate retained an exact `rp2040_timer0` timestamp of
38,429,602,864 ticks at 16 MHz, or 2401.850179 seconds. The contemporaneous
active status exposed integer `uptime_s=2401`, whose product with 16 MHz is
38,416,000,000 ticks. `uptime_s` is `millis()/1000` and is therefore a
conservative one-second lower bound, while estimator timestamps retain the
fractional `micros()*16` coordinate. The estimate was legitimately 13,602,864
ticks (0.850179 seconds) above that lower bound and 2,397,136 ticks below the
next whole-second bound.

The attempt-8 supervisor incorrectly required the exact estimate timestamp to
be no greater than the floored uptime lower bound. Integer-aligned unit and
accelerated-rehearsal fixtures hid this live quantization seam. The firmware,
selected estimate, capture stream and timing domain were coherent; the host
predicate was not.

## Narrow recovery

Qualification now retains the exact estimator timestamp unchanged, but treats
integer uptime as a lower bound. If the origin lies above that lower bound but
within the bounded lead permitted by the complete-status freshness interval
plus uptime quantization, qualification waits for a later status snapshot. It
rejects an origin beyond that bounded coherent interval. Once the lower bound
reaches the exact origin, the supervisor binds the estimate ID, exact ticks and
capture session.

The 41,400-second correction-admission boundary and 43,200-second qualified
endpoint continue to subtract the exact origin from the integer device-time
lower bound. They can therefore close less than one second late but can never
close early. Host UTC remains observation provenance only and cannot move
either scientific boundary.

Regression coverage uses the exact attempt-8 values to prove deferral at
`uptime_s=2401`, establishment at `uptime_s=2402`, unchanged exact-origin
retention, same-session enforcement, and conservative fractional-origin
admission and endpoint boundaries. The operational rehearsal now exercises
qualification selection itself with a non-integer origin rather than directly
seeding an integer-aligned retained state.

## Attempt 9 gate

Attempt 8 consumed activation v8. A physical successor requires the narrow
host regression, all affected current checks, the release verification
required for the changed supervisor boundary, and the complete frozen
live-topology rehearsal to pass. A new bundle, proposal, preflight and
single-use activation must bind the corrected host tools and the attempt-8
terminal evidence. The firmware source, UF2, scientific thresholds, topology,
setup code, duration, actuator limits, response criterion and progressive
authority envelope are unchanged; their exact successful evidence may be
reused where the decision-relevant inputs did not change.

Those deterministic gates passed at host source revision
`301eeea0c81e173657e105cb1687380411f22120`. The focused fractional-origin
and live-rehearsal tests passed 27 checks; the affected current set passed 112;
and the complete current suite passed 880 checks with 27 historical-revision
tests excluded. All seven supported firmware profiles built and all six
expected-failure guards matched. The firmware input semantic, configuration
and reused exact UF2 remain respectively
`1aa15e0a88c1090afb751d1418a381a6c2ce4b84542508572a436e0841ab42e2`,
`f800a4b7725992b01682e6d2c9e2be6fa15c956e23662622a928cdd4abe40990`
and `cdb6c4f413dddf768b444126ea44646ff5d88f7b3073b0ac646ef4c8c7a095ac`.

Bundle v17 has semantic SHA-256
`824860d845855a378a7ca77ff238d13be63d41c983f3ba6796a844df6dd36c54`;
proposal v17 has semantic SHA-256
`e9bf9649612a2e2dedfd4067ceb205538f18924b2dc9a54d8f2698c71146dd7b`;
and structural preflight v17 passed with semantic SHA-256
`a206159271aca9425111a68682313249a58de47c21f991ecd2397810cdd87e64`.
The complete live-topology rehearsal passed with semantic SHA-256
`51ea2a7b4eb00ea8ff4a155f9f260c1ea5e5802f676991833388490bbcf41a39`.
It exercises the real capture and supervisor processes, all three FIFOs,
transport obstruction, abort-before-close, atomic terminal status, rotation,
analysis, sealing and registration. Its accelerated path establishes the exact
fractional origin only after the integer lower bound reaches it and proves the
conservative 41,400/43,200-second device-time boundaries across forward and
backward host UTC steps. No physical action was performed.
