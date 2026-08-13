# CX319 Current Session-Absence Exact-Flash Qualification Pass

## Decision

The exact current lower-side firmware passed the frozen current-session
absence criterion. This closes the firmware-entry uncertainty that blocked Q4
and permits preparation of a fresh current-image Q4 candidate under the
unattended phase authority in document 32.

This result does not repeat or supersede the successful Q2/Q3 scientific and
topology results. It qualifies only the current firmware delta at reset and
post-attach active-state handling.

## Exact evidence

- Run: `session_absence_exact_flash_low_cadence_20260813T092834Z`.
- Current UF2 SHA-256:
  `e62cfb7c5df58a4471425a2045cc7d7fba03ed57d35eccb8cdd45ad34c7bf510`.
- Exact firmware-entry bundle:
  `4666041ff61ab23df2c0e4c10af5f4bf6afef526c5f3bb425ddd9d7856cd3dc9`.
- Frozen criterion bundle:
  `bfc5c11d8fc75787c15d6a9acd8d2ade54ec7e970a37bbde222e26f8d44c464c`.
- Flash record file SHA-256:
  `c79be2272ca0e0853262fe3ef11abaa33b6a416adf9c5b50d32600f06c59c46e`.
- Raw serial SHA-256:
  `1e28623ad308bebda53522cdceac5cb14ad86c145e2d5e4a30ee5de8a21b3a5a`.
- Result file SHA-256:
  `3458937be44ff0e35660d28612bfcf5db94c5522b071a65bbf61f6b926fa54c7`.
- Evidence-manifest file SHA-256:
  `ed2e89023b289c8febfa50036abf9396a8ddc54b136488a7dbc22c2763089a34`.
- Evidence snapshot identity:
  `1b8513ba36f0b6cf455318f7d841a6b8e43f898b6e2d1f5891c4d09436e98330`.
- Registered package identity:
  `f8e1abf9fc689d5eb9a4b894b53584ca44ee41ee6636ba82aba17bd9e44111e0`.

## Observed result

The exact same image was flashed once and capture became ready 254.913 ms
after upload completion. `CONFIG?` was sent 0.165 ms after carrier readiness.
The three requested snapshot sends were separated by 5.001222 s and
5.004889 s and completed inside the 30-second post-attach deadline.

Every snapshot retained the exact build, profile and run identities and
reported:

- `state=DISARMED` and `reason=initialized_disarmed`;
- `fail_static=false` and `manual_start_confirmed=false`;
- nonzero `session_id=1`; and
- correction count, cumulative movement and DAC epoch all zero.

The ordinary `telemetry_dropped` baseline remained `0` across its later
observation. Capture recorded exactly four commands, zero rejected commands,
zero reconnects and zero parser errors. Active-transaction and DAC-step row
counts were zero. Setup stimuli, DAC value writes, control arms and automatic
corrections were zero.

## Claims boundary

This is a current-image reset/session-absence qualification pass, not a
frequency, plant, control or Q4 live result. The next step is a candidate-
specific structural preflight and accelerated live-path rehearsal, followed by
the already authorized bounded physical Q4 run if those gates pass.
