# CX319 G1 No-Write Bench Authority

## Operator decision

On 2026-08-11 the operator authorized continuation through the physical G1
no-write bench rehearsal after construction and verification of its exact
bundle.

This authority is deliberately narrower than live frequency-control authority.
It permits only:

- one exact, build-manifest-bound CX319 firmware flash;
- one continuously draining owner of the expected serial device;
- bounded normal, emergency and host-abort command paths;
- read-only queries and active capture-lease renewal;
- bounded normal-path obstruction and the independent priority abort;
- same-owner logical evidence rotation; and
- the actual validation, analysis, sealing and evidence-registration path.

It does not permit:

- `DAC SET` or any other setup stimulus;
- `ACTIVE ARM` or an automatic-controller authorization;
- a DAC register value write;
- automatic correction;
- rehearsal-to-live promotion;
- G2 execution; or
- any phase- or hybrid-derived actuator authority.

The active firmware may contain the future bounded actuation implementation so
that rehearsal and live use the same operationally significant firmware. Its
boot path may probe the DAC I2C address, but it must not issue a DAC register
value write. Host command ingress for G1 must fail closed to an exact allowlist
that excludes `DAC SET`, `ACTIVE ARM`, sweep and pseudo-reference commands.

The machine-readable authority is `profiles/programme_status_v2.json`. A
passing G1 seal is necessary but not sufficient for G2: live-leg authority
requires a later explicit operator decision and a new status transition.
