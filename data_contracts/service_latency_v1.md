# LAT v1: optional software service diagnostics

`LAT` is raw-only evidence registered in the current firmware/host contract.
It never supplies canonical measurements, control eligibility or terminal
predicates. Malformed or incomplete LAT is retained and rejected locally by
`host.otis_tools.service_latency`; it cannot become a canonical parser fault.
Historical evidence uses its recorded revision.

Every physical row is comma-separated `name=unsigned_decimal` fields in the
exact order declared by `otis_firmware_host_contract_v1.json`. `v=1` selects
this contract; `g` is the wrapping uint32 report generation, `c` is channel
(1=D14, 2=D8), `s` is stage and `p` is part. One immutable statistics snapshot
comprises seven parts in order. No part from another generation may fill a gap.
Generation is an export identity, never a capture/source sequence.

| Stage `s` | Start | End |
|---|---|---|
| 0 | Timer after PIO FIFO word read | Foreground ring pop returned |
| 1 | Foreground ring pop returned | Reference selector returned its outcome |
| 2 | Selector outcome ready | Immediately before first phase-estimator call |
| 3 | Copied output slot immediately before release commit | Same message pop returned |
| 4 | Same output precommit coordinate | Core 0 canonical formatter dispatch |

Stage 0 applies to normal FIFO IRQ reads and foreground fault-preservation
reads. Stages 3/4 use the snapshot identity carried in the message, including
REF's separately retained source identity. The REF presentation ordinal is not
that identity. Stage 3 is an upper bound on publication residence, since the
release instruction itself is not timestamped. Stage 4 is not USB acceptance
or transmission completion. A pre-carrier/quarantine discard has a valid
queue-consumption endpoint but a missing formatter endpoint (`end=0`, status 1).
D8 observations occur at D14 snapshots, not individual D8 cycles.

| Part `p` | Fields following identity | Meaning |
|---|---|---|
| 0 | `e,m,a,x,d,t,sat,hw` | Eligible, missing, ambiguous, threshold-exceeded, diagnostic drops, threshold us, counters saturated, hardware start available |
| 1 | `hv,b0,b1,b2,b3,b4,b5,b6,b7` | Histogram version1 and cumulative bin counts |
| 2 | `have,session,seq,start,end,u,status,domain` | Minimum eligible sample |
| 3 | same | Maximum eligible sample |
| 4 | same | Largest eligible tail sample |
| 5 | same | Second-largest eligible tail sample |
| 6 | same | Latest missing/ambiguous sample |

`session,seq` are original hardware snapshot identity. `start,end` preserve raw
RP2040 timer low words; `domain=1` means `rp2040_monotonic_us32`, `domain=0`
unavailable. `status=0/1/2` means eligible/missing/ambiguous. `have=0` explicitly
means the retained sample is absent, with status 1/domain 0. A zero coordinate
alone never means missing. `u` records additional endpoint uncertainty in us;
current software endpoints use0. Nonzero uncertainty is ambiguous and excluded
from point-valued extrema/histograms. The timer's one-microsecond quantization
still applies; zero additional uncertainty is not a physical accuracy claim.

Eligible deltas are `(end-start) mod 2^32` under an independently established
lifetime below `2^31` us. Full-width queue stamps detect whole-wrap aliases;
foreground absence bounds stage0, conservatively marking the first batch after
startup or a long absence ambiguous. Stages1/2 execute synchronously within one
bounded boundary-service call. Backward sessions, duplicate/backward source
sequences and half-range ambiguities do not enter eligible statistics. New
forward sessions retain earlier extrema with their original identities. Missing
counts refer to observed stage attempts with absent endpoints, not invented
counts of unseen hardware events or unobserved export intervals.

Histogram inclusive upper bounds are `1,4,16,64,256,1024,4096,2147483647` us.
`x` counts strict `delta>t`; `t=1000` us is observational only. Counts saturate
at UINT32_MAX, with `sat=1`. `d` includes rejected diagnostic samples and dropped
export rows; a drop appears in a subsequent snapshot. Equal extrema retain
the earlier identity. Statistics are cumulative for the firmware boot.

`hw=0` explicitly declares no hardware start marker: electrical-edge-to-service,
PIO-recognition-to-service and fractional D8-cycle measurements are unavailable.
No cross-domain conversion is implied.

Emission is at most one row per 250 ms, under 256 bytes including CRLF. Core0
formats a copied snapshot; the single Core1 mailbox never waits. USB admission
uses one mutex try-lock and whole-row FIFO capacity with 64 bytes reserved.
Unavailable capacity drops the complete row without a pending-frame owner.
Host interpretation requires all seven parts, validates identities/counts and
retains missing, reordered, duplicate and malformed evidence explicitly.

The [current PIO capture assessment](../docs/50_SOFTWARE/PPS_CAPTURE_CURRENT_ASSESSMENT_2026_09_19.md)
provides a conditional bound in PIO execution clocks from D14 presented to the
SM to the count copy. No per-event PIO clock coordinate or timer mapping is
recorded, and its D8 dwell assumptions are not measured by LAT. It is static
proof evidence only: `hw=0`, existing stages, `u`, and raw SNP uncertainty keep
their current meanings. No software-stage interval includes or estimates it.

The normal ready-to-first-estimator path now defers count-transition status
until after the first phase-consumer call. CNT/APS remain before it; faults flush
pending status before replacing its state. Endpoint meanings and schema are
unchanged. See the [startup review](../docs/50_SOFTWARE/STARTUP_ESTIMATOR_SERVICE_REVIEW.md).
The [periodic-output repair](../docs/50_SOFTWARE/PERIODIC_STATUS_SERVICE_REPAIR.md)
yields between complete retained status rows. Stages 3/4 still overlap at one
precommit; only exact matching samples permit their subtraction, and neither
establishes completed formatting or physical delivery.
