# Draft: CX319 Q4 Lower-Side Finite Live Authority

## Status: not effective

This document is a proposal for operator review. It grants no authority and
must not be used to open serial, create a command FIFO, reset or flash the
board, send setup or DAC commands, arm control, or begin a live run.

An effective decision, if later made, must be a new explicit record and must
add the exact `g2_live_leg` operation to programme status. Editing this draft,
the candidate, or an old activation is not an authority transition.

## Proposed finite decision

Authorize exactly one CX319 adversarial-review Q4 experiment, mapped to CX319
G2 lower-side frequency-only live qualification, using:

- candidate source revision
  `2f46e1f01da75a17c69b259626d282df4ca1bcdc`;
- proposal bundle
  `f08c9a581ec92271828f9c7c0ff87b5e0d1ce04e6015c92d4100c75f7882bbfe`;
- passing accelerated-rehearsal seal
  `4e6d20094a80e9a3ffcabc6db93302b49acfbf5d48a2da6faeaa70ebe1f65084`;
- expected board serial `503533748A919118`;
- exact Q3-qualified UF2
  `50f863a2150d1b1391504553a1d20e1cb951daae5b450a83c90628265a522083`;
- profile `cx319_tight_lower`; and
- policy `CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1`, SHA-256
  `936d92a1421b7a8f3db620cd0add2c1ecd1a73dbd9aad4581beb8d8c0b8e1698`.

The firmware-entry action is verify-only: do not flash. If the connected board
or installed image differs, stop before serial campaign entry and require the
shortest affected physical no-write requalification. A re-enumerated device
path is acceptable only when the exact board identity is preserved.

Before execution, confirm that the DAC analogue output is connected to the
oscillator EFC/Vctrl input. The initial applied code remains unknown until the
entry query and authorized setup transaction establish it; unknown is not
permission to infer the code.

## Proposed live envelope

- Send one exact lower-side setup stimulus at `0xA808`; this opens a new DAC
  epoch and is not automatic-controller direction evidence.
- Require the complete nonce-, generation-, session-, configuration-, and
  acknowledgement-bound setup chain before any arm or automatic authority.
- Require at least one healthy positive automatic transaction and two
  consecutive fresh 600-second estimates with absolute accumulated edge error
  at most two counts for tight entry.
- Permit at most four automatic corrections, 21 codes per correction, 84
  cumulative absolute automatic codes, and one request outstanding.
- Require at least 1,800 seconds between applied automatic corrections and,
  after each write, 900 seconds settling exclusion followed by 600 seconds
  fresh support.
- Keep every code within `0xA800..0xAB00`.
- Stop at the 90-minute qualification deadline or four-hour maximum qualified
  duration. Do not extend, retry, restore, change thresholds, or recover by
  automatic reboot.
- Keep all phase-derived and hybrid-derived actuator authority zero.

## Independent abort and stop conditions

`ACTIVE ABORT` must remain available independently of normal-command
backpressure and must be proven immediately before the live entry.

Stop before or during the run on any candidate, firmware, board, policy,
contract, tool, authority, session, generation, nonce, GNSS/PPS, serial-owner,
capture, queue, partition, acknowledgement, application, range, cadence,
budget, replay, abort, analyzer, seal, or registration mismatch. Missing,
partial, duplicated, reordered, failed, or ambiguous setup evidence is a stop,
not a retry condition.

A finite scientific non-pass is useful evidence and does not authorize a
retry. Any platform discovery retires the activation and returns to the
shortest affected offline or physical gate.

## Terminal physical-state obligations

At every terminal path, disarm control, issue and confirm the independent
abort, retain the last confirmed applied code and DAC epoch, do not
automatically restore a prior code, preserve continuous serial ownership until
the capture/finalization boundary, and run the exact analyzer, seal and
registration path. Record uncertainty explicitly if physical application is
ambiguous.

## Operator decision

No decision is recorded here. A later operator instruction must explicitly
accept or reject this exact proposal and create a separate effective authority
record. Until then, all current permissions remain false.

