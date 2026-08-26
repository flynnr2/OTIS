# Stage 5 plan source recovery

## Recovered identity

The exact missing Stage 5 plan was recovered on 2026-08-25 from the
user-owned local checkout at
`/Users/richardflynn/Documents/GitHub/OTIS/profiles/plant_campaigns/cx317_pps_gated_open_loop_v1.json`.
Its 3,459 bytes have SHA-256
`19609f35e285d8005054f7acdf59341675ae01c1fe986a44cea296a35f95d84d`,
exactly matching the path and digest recorded independently by the Stage 5
run manifest, plant-characterization report, and frozen feasibility contract.

The same bytes are Git blob
`bbfce71a3dd789c39458821dcdc0d84bba881812` at that path in local commit
`b4b3ca46019a740c77ea52267c8fb5e96998f00e` (`Add CX317 PPS-gated estimator
and control preview`, 2026-08-03 07:37:52 +0100). They were restored to the
current working tree at the originally recorded repository path without
normalization or semantic reconstruction.

## Provenance boundary

The Stage 5 run remains recorded at source commit
`0d52df61f189eb98c8e0e1e318e8ca706fcf6e52` with `source_state: dirty`.
That commit does not contain the plan path, and the later recovery commit is
not an ancestor of it. The source revision therefore does not by itself prove
the plan bytes. Identity rests on the run-time path plus SHA-256 recorded in
the immutable Stage 5 records and the independently recovered exact byte
match; no claim is made that the run used a clean tree.

This recovery changes no raw observation, plan field, model, nuisance,
partition, threshold, firmware, or physical authority. The original invalid
report remains immutable. The operator's subsequent `proceed` direction
authorizes a separately identified zero-I/O comparator attempt under the same
scientific contract.
