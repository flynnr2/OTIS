# Current Contract and Policy Authority

Current code supports one `adaptive_hybrid_regulation` image with one firmware
operating owner. The host is an optional recorder and explicit command client.
Historical programmes use their recorded revisions; no compatibility reader,
lease, campaign supervisor or host actuation acknowledgement is retained.

## Bound identities

- Firmware: `OTIS_AUTONOMOUS_INSTRUMENT_V2`.
- Instrument status: `OTIS_INSTRUMENT_STATUS_V2`.
- Wire contract: `OTIS_FIRMWARE_HOST_CONTRACT_V2`.
- Numerical hybrid policy: `OTIS_ADAPTIVE_HYBRID_REGULATION_V1`.
- Frequency estimator: `OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1`.
- Relative-phase estimator: `OTIS_RELATIVE_PHASE_ESTIMATOR_V1`.
- Plant model: `OTIS_PPS_GATED_OSCILLATOR_PLANT_V1`.

`data_contracts/otis_firmware_host_contract_v1.json` is the canonical wire
source despite its retained filename. The generated firmware header is checked
against it. Numerical profiles and schemas remain explicit sources; the fixed
build and resource contract is `firmware/arduino/firmware_build_manifest.json`.
The firmware publishes its protocol digest. Unknown or malformed output is
retained as evidence and reported, never silently interpreted as a clean state.

## Ownership and modes

Each firmware start selects AUTO_DISCIPLINE and writes `0xA84D` through the
same bounded executor as subsequent applications. The physical result must be
confirmed and propagated to both measurement consumers. Qualification precedes
corrections. The range is `0xA800..0xAB00`, correction limit 21 codes, minimum
applied cadence 1,800 seconds. Lifetime application/movement budgets are zero
(disabled); their counters remain diagnostic evidence.

Explicit serial commands select AUTO_DISCIPLINE, OBSERVE_HOLD, FIXED_CODE or
CHARACTERIZE. HOLD cancels an unreleased proposal and resolves an already
released write within its original deadline. Characterization is one bounded
step and finite dwell, ending in HOLD. Optional timed AUTO also ends in HOLD
under the firmware timer. A recorder duration never requests that transition.
Disconnect preserves mode; restart reapplies boot policy.

Command identity uses a random 64-bit boot session distinct from the capture
session. This prevents ordinary stale-command reuse across restarts without
claiming mathematically collision-free persistent identity. Sequence and payload
must match for a duplicate receipt; stale/conflicting requests have no effect.
Core 0 matches the immutable request, prior DAC state, deadline and latest GNSS
qualification before correction. An exact physical application remains recorded
even if service later detects a deadline fault. Core 1 confirms both downstream
consumers before admitting another decision.

## Timing and evidence

D14 alone supplies reference timing; D8 alone supplies oscillator counts.
Same-receiver serial metadata qualifies D14 without replacing it. Recoverable
metadata loss freezes correction debt and holds writes while valid capture and
phase history continue; fresh metadata and causal support requalify control.
D10 and D6 remain optional isolated diagnostics.

Canonical measurement coordinates are unchanged. Instrument lifecycle events
use `rp2040_timer_us64`, the hardware extended microsecond timer independent
of accepted PPS progression. Never substitute it for a hardware D14 timestamp
or compare unrelated domains without their explicit relation. Decision evidence
retains its source identity separately from its service/decision coordinate.

ICM records command outcomes, IWR released writes, IAP physical outcomes, IDC
controller decisions, IRS response diagnostics and IST state changes. Their
ordered fields, identity joins and record sequence are defined by the canonical
contract. Periodic status reports current mode, holds, faults and output loss.
Raw observations are not rewritten by any controller result.

Outbound USB loss never vetoes qualified internal control. Strict receiver/DAC
service and actuator mailboxes remain integrity boundaries. Missing, partial or
dropped records cannot support a continuous replay claim. There is no onboard
durable spool. A recorder failure has no automatic stop or reset authority.

## Verification boundary

See [the proposal](HOST_CONTROL_REPLACEMENT_PROPOSAL.md) and the detailed
[fault mapping](AUTONOMOUS_INSTRUMENT_FAULT_MAPPING.md). The operator reserved
long-term approval of that mapping. Offline/native tests and a compiled image
do not qualify the real DAC, USB/UART, cross-core scheduling or physical plant.
The next physical gate is a separately authorized short exact-image integration
followed by the agreed 72-hour observation; a week is optional.
