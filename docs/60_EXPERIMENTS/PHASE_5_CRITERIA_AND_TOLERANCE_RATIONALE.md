# Phase 5 criteria and tolerance rationale

## Decision

Phase 5 separates digital-architecture acceptance from oscillator and metrology
characterization. A numerical result is not an acceptance limit merely because
it can be computed precisely.

The installed ECS 16 MHz TCXO is the fixed, unsteered edge source used to
exercise this firmware backend. This campaign is not qualifying the ECS as a
frequency standard and it is not testing the later steered CX317 VCOCXO control
plant. ECS mean frequency and slow drift are nuisance observations for the
present decision, except where a gross change helps diagnose a broken input.

The following remain blocking architectural requirements:

- every accepted `CNT` is reconstructed exactly from two adjacent, clean,
  same-session cumulative `SNP` boundaries;
- the first snapshot is an anchor and produces no count;
- no valid count spans a malformed reference, a snapshot gap, a capture fault,
  or a reset/session boundary;
- a late snapshot is never paired retroactively;
- recovery requires two new clean snapshots;
- capture, parser, command FIFO, PIO FIFO, DMA, ring, and session-continuity
  counters remain at their required values; and
- declared test segments contain the planned minimum number of eligible
  windows.

Absolute bias and quiet/load mean shift are reported as characterization
quantities. Candidate population spread retains a blocking 1.5 Hz architecture
screen: it is a deliberately conservative detector for multi-edge capture
behaviour, not a claim that the ECS oscillator is specified to 1.5 Hz or that
firmware jitter has been independently measured at 1.5 Hz.

This disposition means that existing sealed evidence is reinterpreted; it is
not repeated solely to turn a historical threshold result from red to green.
The completed evidence set was reviewed and accepted on 2026-08-01 as
observe-only measurement-backend qualification with the documented
limitations; this decision does not authorize DAC actuation.

## Criterion classes

Every Phase 5 criterion must identify one of these bases:

1. **Exact contract invariant.** A digital relationship that can be checked
   without a tolerance, such as sequence continuity or exact SNP-to-CNT
   reconstruction.
2. **Published component limit.** A datasheet limit applied only to the named
   component and the datasheet's stated conditions.
3. **Measured statistical result.** An estimate reported with sample count,
   conditions, resolution, and an uncertainty or confidence method appropriate
   to the data.
4. **Engineering allocation or screen.** A deliberately chosen system budget
   or anomaly screen. It must be labelled as such and must cite the requirement
   or risk allocation it protects.
5. **Characterization reference.** A historical or comparative number that is
   useful for trending but is not an acceptance boundary.

An unexplained number is class 5, not class 1 through 4.

## What the available datasheets support

### Installed 16 MHz ECS TCXO

The installed part is recorded as `ECS-TXO-5032-160-TR`. The blank stability
suffix is the standard grade in the ECS ordering guide. The
[ECS-TXO-5032 datasheet](../datasheets/ECS-TXO-5032.pdf), page 1, specifies:

| Published parameter | Datasheet value | Equivalent at 16 MHz |
|---|---:|---:|
| Frequency tolerance at 25 degC +/-2 degC | +/-1.5 ppm | +/-24 Hz |
| Stability versus temperature, -30 to +85 degC | +/-2.5 ppm | +/-40 Hz |
| Stability versus a +/-5% supply change | +/-0.3 ppm | +/-4.8 Hz |
| Stability versus a +/-5% load change | +/-0.3 ppm | +/-4.8 Hz |
| Aging per year | +/-1.0 ppm | +/-16 Hz/year |
| Output symmetry at 50% VDD | 40% to 60% | component waveform limit |
| Rise/fall time, 10% to 90% VDD | 10 ns maximum | component waveform limit |
| Start-up time | 2 ms maximum | output-start specification, not thermal settling |

The hertz conversions are unit conversions, not a combined system error
budget. The datasheet does not specify one-second Allan deviation, short-term
frequency stability, warm-up frequency settling, thermal transient response,
or a maximum service-load-induced frequency step. It therefore cannot justify
a 0.05 Hz (0.003125 ppm, or 3.125 ppb) acceptance limit for this assembly.

### Later 10 MHz CX317 OCXO

The [CX317 datasheet](../datasheets/cx317.pdf), pages 2 and 3, describes the
10 MHz `OH020-61003CV-010.0M`, not the ECS part used in the current run. It
specifies +/-10 ppb temperature stability, +/-0.5 ppb for a +/-5% supply or
load change, and ADEV at one second no greater than `1e-11`. It also states the
conditions that matter: calibration after 60 minutes at 25 degC, five-minute
warm-up meaning within +/-100 ppb of the 60-minute value, and airflow shielding
for the short-term stability measurement.

At 10 MHz, 0.05 Hz is 5 ppb. That scale is plausible for a controlled,
warmed-up CX317 experiment, but the CX317 limits cannot be transferred to the
ECS TCXO. The original 0.05 Hz Phase 5 number was introduced as an engineering
allocation below a previous CX317/DAC plant-response scale. It was not derived
from the ECS datasheet or a completed 16 MHz uncertainty budget.

### GPS PPS reference

The [CD-PA1616S datasheet](../datasheets/CD+PA1616S+Datasheet.v03.pdf), pages 5
and 12, specifies PPS timing accuracy as +/-20 ns RMS and a 2.8 V CMOS output.
Twenty nanoseconds corresponds to 0.32 of a 16 MHz oscillator period. RMS is a
statistical measure, not a maximum bound; it must not be used as though every
PPS edge lies within +/-20 ns. The document also does not establish independence
between consecutive PPS timing errors.

Consequently, integer variation in one-second captured counts is expected.
The PPS specification helps explain the observed distribution, but it does not
make 1.5 Hz a component limit. The limit is instead retained as a firmware
architecture screen, discussed below.

### RP2040 capture input and interface buffer

The [RP2040 datasheet](../datasheets/RP2040.datasheet.A700000007747462.pdf),
section 3.5.6.3 on printed page 340, states that every PIO GPIO input uses a
standard two-flip-flop synchronizer by default, adding two PIO cycles of
latency to protect against metastability. It warns that bypassing the
synchronizer can produce unpredictable state-machine behaviour. The OTIS
backend leaves synchronization enabled and proves a `-1/0/+1` edge boundary
envelope in the digital model. That digital proof is an architecture result;
it is not a pad-level phase-sweep measurement.

The checked-in PIO proof exercises oscillator phase and modeled duty, finds no
missed or double-counted synchronized edge, and confines reconstructed interval
error to `-1/0/+1` edge. At a one-second gate, the raw count resolution is one
edge or approximately 1 Hz. A 1.5 Hz population-standard-deviation screen is
therefore a conservative multi-edge anomaly detector when combined with the
GPS timing scale and the observed sub-1 Hz populations. It is intentionally
not presented as a calculated confidence boundary or an ECS stability limit.

The observed population spread is an end-to-end result containing the ECS
source, GPS PPS, input synchronizers, edge selection, and reconstruction. The
current fixture cannot decompose those contributions into a standalone
firmware-jitter number. Firmware-specific confidence instead comes from the
digital `-1/0/+1` proof, exact SNP/CNT parity, absence of loss/order faults, and
the absence of load-correlated spread broadening. A controlled phase source or
simultaneous external timing measurement would be required to isolate a
physical firmware/input contribution.

The engineering objective is nevertheless to make the firmware contribution
as small as the RP2040 permits, not merely to remain below the 1.5 Hz anomaly
screen. The fixed ECS source is useful because it exposes the repeatable floor
of the complete test path. Report one-second spread and also non-overlapping
clean multi-boundary differences. Exact count resolution becomes 1 Hz over one
second, 0.1 Hz over ten seconds, and approximately 0.0167 Hz over sixty seconds.
Those longer differences may never cross a malformed reference, snapshot gap,
or session boundary. They improve frequency resolution while the one-second
records retain fault localisation.

This creates two deliberately different decision layers. The exact invariants
and the 1.5 Hz gross-anomaly screen are minimum qualification gates; satisfying
them does not mean the acquisition path is "accurate enough" or that further
improvement should stop. The optimization objective has no invented numerical
floor: retain hardware ownership of the aperture, remove avoidable software
latency from that aperture, bound the remaining edge assignment, and use longer
clean cumulative spans where they provide demonstrably finer count-domain
resolution. Progress is judged against the prior implementation and the
RP2040's documented mechanisms, with an external timing fixture required for
claims below what this end-to-end ECS/GPS setup can separate.

The instruction-level sweep also checks every contiguous span available in
each modeled trace (one through seven PPS intervals). Across the full phase and
duty grid, total span error remains `-1/0/+1` oscillator edge; it does not grow
by one edge per included second. This follows from the cumulative-snapshot
architecture: intermediate boundary assignments cancel and only the two span
endpoints remain. Dividing that bounded endpoint result by a longer clean gate
is the firmware-supported route to lower frequency quantisation. It is not a
claim that source drift, PPS noise, or overall measurement uncertainty improve
by exactly the same factor.

This is analogous in objective, though not mechanism, to exploiting a hardware
event system on another MCU. RP2040 PIO is the autonomous capture fabric here.
The chosen state machine runs at the datasheet-limit 133 MHz, keeps the two-flop
input synchronizers enabled, and owns both oscillator counting and its own
cumulative snapshot. Increasing the clock beyond the qualified limit,
bypassing synchronization, or splitting count and snapshot ownership would not
be a justified accuracy improvement.

Firmware latency must also be assigned to the correct plane. PIO instruction
and input-synchronizer latency can affect which boundary-adjacent oscillator
edge is selected and is covered by the count-domain proof. DMA, ring, foreground,
USB, and report-emission latency occur after the immutable PIO snapshot and
must not change `CNT`; they are accepted through exact continuity and zero-loss
counters. The independently reconstructed GPIO-IRQ `REF` timestamp can have
software latency variation, but it is an observer and does not define the
oscillator-count aperture.

The firmware claims and their corresponding tests are therefore:

| Firmware dimension | What can affect | Evidence and disposition |
|---|---|---|
| PIO input synchronization and instruction timing | Selection of the oscillator edge adjacent to a PPS boundary | The instruction-level proof permits only `-1/0/+1` edge boundary error and no missed or double-counted synchronized edge. This is blocking digital evidence. Pad-level phase/duty coverage remains not tested on this fixture. |
| PIO snapshot-to-DMA latency | Delivery time, not the already captured cumulative value | Exact raw `SNP` continuity and modulo reconstruction of every accepted `CNT` are blocking. DMA stopped/error and PIO RX-stall counters must remain zero. |
| SRAM-ring and foreground latency | Backlog and possible data loss, not the physical aperture while capacity is preserved | Ring overwrite/drop and sequence-gap counters must remain zero. Backlog depth and high-water mark are reported; a nonzero bounded high-water mark is not itself an aperture error. |
| GPIO-IRQ `REF` timestamp latency | Observer timestamp and diagnostics | `REF` must remain sequence-continuous and timestamp-associated with the corresponding `SNP`. It is not used to create the raw oscillator count. Absolute IRQ latency is unavailable without an external timing measurement and is not assigned a fictitious bound. |
| Command parsing, USB serialization, and host scheduling latency | When status is requested and received | No parser loss, malformed frame, rejected command, capture drop, reconnect, or session break is allowed. Command arrival spacing is operational provenance, not a precision PPS aperture. |
| Repeated service load | Potential firmware starvation or timing-path interference | Digital continuity, unchanged bounded queue behaviour, and no load-correlated population-spread broadening are the firmware-focused checks. Mean frequency is nuisance characterization for this unsteered ECS stimulus and is not a control-plant result. |

This separation matters: a long or variable time between a hardware snapshot
and its serial record is acceptable only if the immutable value and its
sequence survive exactly. Conversely, a prompt-looking serial line cannot
compensate for a missing or ambiguously associated boundary.

The next limiting firmware layer is likely estimation rather than capture
latency. The current Phase 4 preview default is a five-sample rolling mean of
one-second frequency observations. For consecutive clean PPS-gated counts that
mean is algebraically the same endpoint difference over five seconds, but its
count-domain increment is still 0.2 Hz (20 ppb at the future 10 MHz CX317).
That is an exact digitisation statement, not a total-uncertainty claim. Before
closed-loop work, the estimator window and control bandwidth should be chosen
from measured source/reference noise and plant dynamics, with a longer
cumulative endpoint span or multi-rate spans considered where they improve
resolution. Any such estimator must reset at the same malformed-reference,
snapshot-gap, and session boundaries enforced by the one-second capture path.

The [SN74LVC1G17 datasheet](../datasheets/sn74lvc1g17.pdf), pages 6 and 7,
specifies Schmitt thresholds and propagation-delay limits. At 3.3 V and 15 pF,
the propagation delay is 1.5 ns minimum to 4.6 ns maximum over -40 to +85 degC.
A constant propagation delay cancels from a frequency interval; delay
variation and edge jitter would matter, but this datasheet does not provide a
complete assembly-level jitter budget.

### Power and environmental observation

The [Nano RP2040 Connect datasheet](../datasheets/ABX00053-datasheet.pdf), page
7, allows 3.25 V to 3.35 V on its user 3.3 V output and up to 800 mA including
on-board loads. It does not specify the fast rail transient or local
temperature change produced by repeated USB command handling.

The included Adafruit MPM3610 and Pololu D24V22F3 product PDFs state current,
efficiency, and switching-frequency information, but do not provide the
complete ripple and load-transient evidence required to translate command
activity into a TCXO frequency limit. The Murata ferrite-bead document specifies
impedance, current, and DC resistance for a family of parts; the exact fitted
suffix and the board-level impedance network must be known before using those
figures quantitatively.

The [SHT4x datasheet](../datasheets/Adafruit.Datasheet_SHT4x.pdf), page 6,
specifies typical SHT40 temperature accuracy of +/-0.2 degC, high-repeatability
noise of 0.04 degC, and a two-second 63% response time. It can support thermal
correlation when enabled and physically placed appropriately, but it cannot
resolve an instantaneous die or oscillator-package temperature step. The
BMP280's stated temperature accuracy is +/-1 degC and is still less suitable
for this purpose.

The remaining PDFs cover pinout, schematic, connector, adapter, breakout, or
usage information. They help establish topology and compatibility, but do not
supply an oscillator-frequency acceptance limit. In particular, the AD5693R
breakout guide is not the full converter electrical datasheet and cannot by
itself support DAC accuracy, noise, linearity, or settling claims.

## Disposition of the former numerical gates

| Quantity | Former number | Current disposition | Reason |
|---|---:|---|---|
| Candidate population standard deviation | 1.5 Hz | blocking firmware architecture screen on total observed spread | Conservative multi-edge detector supported by the `-1/0/+1` modeled interval envelope, 1 Hz count resolution, GPS timing scale, and observed sub-1 Hz populations. It is neither an oscillator specification nor an isolated firmware-jitter measurement. |
| Quiet/load mean shift | 0.05 Hz | historical characterization reference | Equals 3.125 ppb at 16 MHz; below the available ECS, power, thermal, and measurement support. The sequential quiet/load design is also confounded by drift. |
| Absolute bias against independent metrology | 0.05 Hz | provisional reference pending error budget | A defensible accuracy gate requires an authorised independent standard, calibration traceability, simultaneous comparison, and a complete uncertainty budget. |
| Minimum windows per quiet/load segment | 60 | protocol sufficiency requirement | This is a minimum amount of evidence, not a component performance tolerance. Ten-minute segments provide about 600 windows and comfortably exceed it. |

Machine-readable reports may retain more digits so results are reproducible.
Human conclusions must round according to measurement resolution and stated
uncertainty, and must not present computed digits as physical accuracy.

## Current Phase 5 decision rule

A short real-GPS or quiet/load campaign passes the architectural gate when its
declared segments contain sufficient eligible windows, candidate population
standard deviation is no more than the 1.5 Hz architecture screen, and all
exact boundary, fault-inhibition, recovery, capture-integrity, parser,
command-FIFO, and session requirements pass. Segment means and mean shifts are
reported with their sample counts and test conditions.

The current ECS hardware cannot perform a controlled PPS phase/duty sweep.
That item is recorded as **not tested: fixture/source capability unavailable**
and is non-blocking for progression. It is not reported as a pass.

The completed extended and overnight runs qualify sustained integrity of this
hardware and firmware configuration; they do not establish ppb-class
oscillator accuracy. In the 14-pair overnight comparison, load-minus-quiet
one-second spread changes divide evenly between positive and negative and have
a median of about -0.05 Hz. That observation does not identify an isolated
firmware-jitter value, but it provides no evidence of systematic command-load
broadening while every segment remains below the coarse architecture screen.
