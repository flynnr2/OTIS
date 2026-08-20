# CX320 Stage 5 Attempt 5 Serialization Terminal and Attempt 6 Recovery

## Attempt 5 terminal

Attempt 5 (`stage5_live_attempt5_20260820T1231Z`) flashed the exact attempt-5
image and crossed the previously missing firmware handoff. Startup qualification
completed, one setup request applied `0xA83C` at DAC epoch 1 with `i2c_ok=true`,
and the hybrid controller entered `FREQUENCY_ACQUIRE`. The selected 600-second
frequency estimate was bound to the live DAC epoch. The first firmware hybrid
decision was a zero-delta `minimum_applied_cadence_hold`; it requested and
applied no automatic correction.

The firmware wire formatter emitted 55 of the frozen 56 `AHY` fields, omitting
the final `actionable=false` field. Capture rejected that record rather than
silently changing its meaning. The supervisor detected one parser error and
submitted the independent priority abort, which firmware accepted on core 1
before capture closed. The applied code remained 43068. This is a platform
escape into the campaign, not a controller or scientific rejection.

The unchanged retained acquisition was replayed after two deterministic
analyzer binding corrections. The superseding seal has semantic SHA-256
`bacd6e65be6838515476fa833e6f6fb54888ec48335bbddfc189e36856abfbfa`
and file SHA-256
`e389c3fc561044e8812208f02a8e4e223963adca5a55f553111fe2a912b1a920`.
All declared CSV contracts validate, 546 selected and diagnostic estimates
replay exactly, tight-deadband replay is exact, setup/DAC epoch/budgets are
exact, and no automatic application occurred. The seal remains a failed
physical result because the parser fault closed capture before a complete
post-abort firmware snapshot; replay does not waive that acquisition gate.

## Bounded corrections

The production `AHY` path now uses one independently executable formatter. A
compiled C++ harness validates that the exact production formatter emits all
56 fields, including the final false `actionable` value. The analyzer accepts
the bundle's CX320 frequency-estimator binding and uses the frozen
tight-deadband predecessor policy binding. These changes repair serialization
and deterministic interpretation without changing controller mathematics or a
scientific criterion.

Firmware now publishes a complete active-status snapshot after core 1 accepts
an abort. The runner retains sole serial ownership until it observes the exact
post-abort state: `ABORTED`, fail-static, no outstanding request or evidence,
and the last confirmed applied code. The real-process PTY rehearsal now passes
an exact 56-field hybrid record through capture and carries that post-abort
snapshot through the first dependent runner decision before capture closes.

Sixty-eight focused serialization, analyzer, runner and live-topology tests
pass. The affected exact firmware profile builds successfully. No scientific
policy, threshold, acceptance criterion, duration, topology, setup code,
command envelope or progressive-authority limit changed.

## Attempt 6 offline identity

Attempt 6 is a separately identified successor under the operator's expanded
bounded-recovery authority. It is not an automatic controller retry or
restoration. Before a new physical run, the exact successor must pass its
structural preflight and complete operational-path rehearsal, then receive an
immutable activation bound to those results.

- firmware source/configuration identity:
  `5a97de4d0fd9681a7af5cd31ffd38c2cfcfc2fda45894640a5982df4c2072d7b:f800a4b7725992b01682e6d2c9e2be6fa15c956e23662622a928cdd4abe40990`;
- exact UF2 SHA-256:
  `78846b28c7d764d9a16574b35f7f6d1a5915f7076fcd04ab16a98d4887da12fb`;
- bundle semantic SHA-256:
  `a2e9bb091b335f7ec3c58db8db5265536d062fcc6134342c2b00e58659bd75b5`;
- successor proposal semantic SHA-256:
  `fca3f5d34c6572388dfeb493e7de2a810c1d3fc28a247eb1ebad5bedcbe043c0`.

The proposal remains non-effective and permits offline preparation only until
those exact gates pass.
