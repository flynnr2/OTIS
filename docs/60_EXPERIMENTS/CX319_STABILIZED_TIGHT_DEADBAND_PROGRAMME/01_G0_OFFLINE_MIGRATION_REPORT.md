# CX319 G0 Offline Migration Report

## Decision

**G0 passed on 2026-08-11.** The stabilized no-hardware vertical slice is
internally consistent and is ready to enter G1 bundle construction. This is
not bench, flash, DAC, control-arm or live-run authority.

The candidate was built from branch
`codex/cx319-stabilized-tight-deadband`, baseline commit
`1e35d7940dda785201b07fed6d7b3c7157a3cc5e`, with an intentionally dirty
source state containing the reviewed CX319 change set. The firmware build
manifests bind the effective source SHA-256
`f6a870f20f0f12d1db92040428ba9c4dfc85d6d3dae14403d7d9be9b3b90d4af`.
G1 must freeze a clean immutable bundle before any physical entry; these G0
builds must not be flashed merely because they compiled.

## What passed

- programme authority is scoped to `offline_preparation`; CX319 operational
  execution and all historical CX318 execution remain blocked;
- the new policy identity
  `CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1` is bound into the host
  and firmware at SHA-256
  `750a3e1daf552723c0e8eb59143248db6eff11d91feaaaea658430b6bd07158e`;
- exact lower `0xA808` and upper `0xA848` profiles compile within the current
  firmware resource budget, while a deliberately altered lower profile fails
  at compile time for the expected reason;
- the frozen relative-phase corpus replayed 39 valid sources and retained one
  deliberately inadequate source as explicitly unavailable;
- the bounded hybrid replay reproduced the same 39/1 classification and all
  151 sealed frequency-only decisions retained an exact zero phase
  contribution;
- the selected firmware engine and host implementations compared 353,394
  boundaries across the 40-member corpus with zero mismatches;
- structural guards confirm that relative-phase and hybrid outputs cannot
  influence the actual frequency decision, controller eligibility, actuator
  transaction or budget state;
- the tight hysteretic count-band replay was exact and had zero authority;
- the current Release matrix verified 35 current profiles: 20 supported
  configurations passed and 15 invalid configurations failed as expected;
- all 994 repository tests passed after the final G0 evidence integration;
  wire-validation and example-run checks also passed; and
- measurement-semantics inventory and whitespace checks passed.

## Evidence identities

| Evidence | SHA-256 |
|---|---|
| Release firmware matrix summary | `0c59eabae88774b76cafbe18db80a1e42caab4764d80c3dd18f694a8831a5346` |
| CX319 lower build manifest | `0583baaad3164b69d3971a55b9ca1f996ba7ed9f40f219b585cc5a5065417ce0` |
| CX319 upper build manifest | `452dcd604f21801f983073d269b1881fbce243a5514bde61d2abb5a0fd4f282d` |
| Fresh relative-phase replay | `a2f7b3b111235a5441170bf749ca313b8d30b2c6f84cb6ef95748798d3a24c07` |
| Fresh hybrid replay | `43fb7a679766b6f7cf2e23f49ccc6cd7c2714e4afc90949c8dfcff8771a5a920` |
| Fresh firmware/host parity replay | `607f14b5400f1aab0ffc51f23592d02bad7edb04580bfd574e6531552381db57` |
| Evidence-bound G0 report file | `30a001e3c008a723651cdd0eb7469ebcf0956362a5628bdd20b5a0c4fb0bec53` |
| Canonical G0 report content | `6374ddd3164283def15980db6db245f8afb054eb22a8607318f8175d9dcc0fe2` |

The generated evidence remains under ignored `build/` storage. This reviewed
summary records the decision-bearing results; it does not convert build output
or historical `runs/` material into committed authority.

## Hardware and physical state

The G0 path opened no serial device, created no command FIFO, flashed no
firmware, issued no command, wrote no DAC value and armed no controller. The
last historical `0xA828` acknowledgement remains provenance only. Current
physical applied-code state is still unknown.

## Next gate

Proceed offline with G1 bundle construction: assemble the exact leg workflow,
timeouts, no-write rehearsal mode, priority abort, logical evidence rotation,
analyzer, sealing and evidence registration into one reproducible bundle.

Before the first physical rehearsal, the operator must explicitly authorize
bench interaction. That transition must identify the exact frozen bundle and
permit only the required flash, serial and no-write rehearsal operations. It
must not authorize a setup stimulus, automatic DAC write, control arm or live
leg.
