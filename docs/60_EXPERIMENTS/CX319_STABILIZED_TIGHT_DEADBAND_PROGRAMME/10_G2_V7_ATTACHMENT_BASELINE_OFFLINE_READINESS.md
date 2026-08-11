# CX319 G2 v7 Attachment-Baseline Offline Readiness

Date: 2026-08-11  
Gate: replacement G2 package after the v6 pre-write telemetry stop  
Result: passed offline; awaiting exact v7 authority and a fresh board restart

## Decision

The replacement G2 package is ready for an operator decision. It does not
grant serial access, a board reset, setup stimulus, DAC write, control arm or
automatic correction. The firmware and physical control envelope are
unchanged. The host/runtime health contract has changed materially and the v6
activation remains retired.

## Attachment health boundary

Ordinary cross-core telemetry is a lossy diagnostic stream with a cumulative
drop counter. Startup before the host attaches is outside the evidence-bearing
interval, so v7 does not require that lifetime counter to be zero. Instead the
actual supervisor:

1. attaches read-only and observes complete health emissions;
2. requires two consecutive emissions with the same cumulative
   `dual_core.telemetry_dropped` value;
3. freezes that value and its status sequence as the attachment baseline;
4. permits no setup or control action before the baseline is frozen; and
5. stops on any later increment.

The analyzer independently replays the complete retained counter history and
requires strictly increasing status sequences, convergence at the recorded
baseline and no post-attachment increment. Evidence, capture, PPS boundary,
preview, partition, critical, control and fail-static gates remain absolute.

## Exact v7 offline evidence

| Artifact | Identity |
|---|---|
| Source revision | `5582ea1aee3084d01f2a69184982e574b0f7f783` |
| Proposal bundle | `f92f41854306bba103afd8ef0fe1aa560360aa0da81c94547624165028b68dd4` |
| Proposal file | `5a58381efbdb4636df7f0ac59ae40a7280490b67bab65c90f363c487ffe9b416` |
| Structural preflight file | `7a82247d504f3c30bda3fa77b21e2fa8426b9746881e4ca186e06394521bffb4` |
| Operational rehearsal result file | `825c7677e88ada1f86644ab95503341ae7ab90d57d50f114087380014e00a612` |
| Operational rehearsal content | `549d93a5227482515a5824a044ff6b2e7a7530473074c42a0e33f6c52c179b43` |
| Operational rehearsal seal | `be8973fb35b33c2015887d8af81e2329bd8e3400c5266afbf3a148c92836ec0c` |
| Operational rehearsal seal file | `c8d2c371f1edd756a7ce90d29af87d29d096b6aa70ce184e957de0c49bf6b462` |
| Registration-path rehearsal file | `568c380aedc06fda9bfe09dbb91b034a93a11189bfdac226929eb8f92082aea5` |

The proposal is `proposed_not_authorized`. Structural preflight passed all
eight checks with zero hardware operations. The accelerated operational-path
rehearsal passed the actual supervisor, analyzer, seal and temporary external
registration path. It established a non-zero attachment baseline, exercised
the bounded setup/arm/evidence sequence, and proved that a later ordinary
telemetry increment is rejected. The repository suite passed 1,066 tests.

## Physical envelope

If separately authorized, v7 permits one finite Leg A run:

- one exact `DAC SET 0xA808` setup transaction;
- positive automatic direction only;
- at most four automatic corrections, 21 codes each and 84 codes cumulative;
- 1,800-second minimum applied cadence;
- 900-second settling exclusion and 600 seconds fresh support;
- 90-minute qualification deadline and four-hour maximum qualified duration;
- no retry, restore or firmware flash; and
- phase and hybrid preview continuously non-actionable.

The runner still requires a fresh firmware session with pre-write uptime no
greater than 120 seconds. This bounds the run; it does not reinterpret ordinary
pre-host startup drops as evidence loss.

## Operator boundary

The next step requires explicit authorization of this exact v7 package and the
unchanged physical envelope. The operator must then restart the board once and
confirm immediately so the exact runner can attach, freeze the health baseline
and proceed only if every pre-write gate passes.

If G2 passes, the prior conditional G3 decision remains subject to a fresh
upper-side bundle and operational-path rehearsal carrying this same attachment
health rule.
