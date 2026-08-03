# CX317 PPS-Gated Selected Estimator

`profiles/estimators/cx317_pps_gated_selected_v1.json` freezes the Stage 4
observe-only estimator policy. It uses `PPS_CUMULATIVE_SNAPSHOT_SPAN_V1` on the
accepted cumulative PIO/DMA snapshot backend.

The authoritative estimate is a 600 s non-overlapping result emitted once per
600 s epoch. A 60 s overlapping estimate may be emitted once per accepted
second for acquisition and diagnostic trend visibility, but it has no decision
authority and cannot bypass or reset the authoritative epoch. Every fault,
session/control-epoch boundary and declared settling exclusion discards current
support; recovery requires 60 or 600 fresh contiguous accepted seconds for the
respective output.

The selection is tied to the sealed 43,227 s fixed-code CX317 record. At 600 s,
the direct finite-run non-overlapping standard deviation was 0.000821677 Hz,
the range was 0.001666665 Hz, the count increment was 0.001666667 Hz and the
explicitly conservative range-plus-one-increment detection floor was
0.003333332 Hz. There were 72 independent outputs. The 600 s support midpoint
is 300 s behind the closing boundary, the rectangular-window -3 dB bandwidth
is 0.000738244 Hz and startup/full-support recovery both require 600 s.

The sealed Run 020 gain range gives a conditional historical comparison of 22
codes at its minimum gain. That is not a selected DAC step or a current
PPS-gated plant specification. Counter-aperture, GPS reference, calibration and
combined uncertainty remain unavailable. The profile is therefore suitable
for observe-only plant characterization and controller replay, but it is not
an actuation-capable firmware contract and provides no live-control authority.

The evidence trade study, rejected alternatives and complete tolerance
provenance are recorded in the Stage 4 campaign report.
