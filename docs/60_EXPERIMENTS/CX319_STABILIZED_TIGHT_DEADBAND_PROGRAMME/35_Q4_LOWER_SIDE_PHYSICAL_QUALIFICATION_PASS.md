# Q4 Lower-Side Physical Qualification Pass

## Decision

The CX319 Q4/G2 lower-side finite live qualification passed on 2026-08-13.
The physical run applied one exact `0xA808` setup stimulus, made one bounded
positive automatic correction, demonstrated a healthy response in the
required direction, and then established the frozen two-estimate tight entry.

This is lower-side frequency-only evidence. D14 remained the sole PPS, D8 the
sole oscillator input, and D10 the input-only external-event source. Phase and
hybrid surfaces remained zero-authority. The result grants no G4 or active
phase/hybrid authority.

## Physical result

| Item | Result |
|---|---|
| Run | `timer_rollover_recovery_live_20260813T160000Z/live_leg_a` |
| Supervisor terminal | `healthy_stop: required_direction_and_two_estimate_tight_entry` |
| Terminal UTC / BST | `2026-08-13T16:58:49Z` / `17:58:49 BST` |
| Setup | `0xA808` / 43016, exactly once |
| Automatic correction | `+21` codes to `0xA81D` / 43037 |
| Response | `healthy_detected`, observed `+0.003333332 Hz` |
| Tight entry | two consecutive `-2` count 600-second estimates |
| Transport faults | zero parser, malformed UTF-8, reconnect and command-rejection events |
| Acquisition content SHA-256 | `d3ac46223bf8a09ed5cc9f3ae38c597a0a56279466f7ee6a9a9743650ea54df4` |

Capture closed physically with one continuous owner and an exact closure
certificate. The acquisition snapshot validates without failures or warnings.

## Offline analyzer supersession

The first finalizer retained a failed seal after the successful acquisition.
Three deterministic analyzer assumptions were wrong:

1. it required selected estimates to be exactly 600 seconds apart instead of
   accepting deliberate non-overlapping gaps after a DAC-epoch reset;
2. it treated the legitimate startup `fresh_estimator_support` transition,
   which precedes the first complete selected estimate, as invalid reference
   evidence; and
3. generic contract validation compared TDB rows with a module-global policy
   hash instead of the policy hash frozen in the run manifest.

The repaired analyzer changed no command, capture, timestamp, transaction,
plant behavior, acceptance criterion, or raw artifact. Exact replay of the
immutable acquisition passes every contract, measurement, controller,
transaction, response, tight-deadband, limit, closure and terminal gate.

| Supersession item | Identity |
|---|---|
| Retained failed seal file SHA-256 | `05d41b080bb94b676d9727beafede965b3cafb152b2e6f8d3f23d4e836c4f542` |
| Passing superseding seal SHA-256 | `2f70587ac61e744401cf1159af4cafba006f70ebb605613a8ffe729533d8d09e` |
| Passing analyzer SHA-256 | `51de6e9136f0627ce886d199b9cfc3f0f7ce06db31bb03b40b54e9697dbffdf4` |
| Registered superseding package | `0f1c250c348c56446217b38981c3d0e0e649eea40f67b929a791390cca0d4843` |
| Physical rerun | no |

The original failed seal remains preserved and the passing seal names its
identity and reason for supersession.

## Next gate

The conditional G3 authority is now eligible for its remaining prerequisites:
build and bind the exact `cx319_tight_upper` image, run structural preflight and
a fresh complete accelerated operational-path rehearsal, then execute the
matched upper-side finite leg with setup `0xA848` and required negative
automatic response.

Do not accelerate cadence, settling, estimator support, or actuation between
the lower and upper legs. After both matched directions complete, evaluate two
separate improvements:

- make rollover validation derive automatically from the declared time domain,
  eliminating caller opt-in while retaining strict checks for non-wrapping
  domains; and
- reduce activation and actuation latency where evidence shows the frozen waits
  are operational overhead rather than scientific requirements.
