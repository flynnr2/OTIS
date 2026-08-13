# CX319 Current Session-Rebinding Focused No-Write Authority

## Operator decision

On 2026-08-13 the operator replied `authorized` to the proposed exact-current-
firmware flash and focused no-write session-rebinding check.

This authority is effective for one finite attempt. It is not Q4 live
authority and grants no setup, DAC value write, control arm, automatic
correction, phase action or hybrid action.

## Exact frozen inputs

- Board serial: `503533748A919118`.
- Serial device: `/dev/cu.usbmodem14601`.
- Firmware profile: `cx319_tight_lower`.
- Firmware source revision:
  `80363468e001a3970bdbf14fc48750cbc0ca7504`.
- Firmware source SHA-256:
  `11af38bcfe2fbe12a7fed15ea7fdaaddabbed5a4b5f67037194aee946fb8ed81`.
- Configuration SHA-256:
  `a88c491c2118c75620b63231ae4ffc301b94a999159eacfb001136f280caec16`.
- Build-manifest SHA-256:
  `e3c37b4dbc190a011aa68339d8305221ba641c05bb960be813ef2902fbea72b0`.
- UF2 SHA-256:
  `e62cfb7c5df58a4471425a2045cc7d7fba03ed57d35eccb8cdd45ad34c7bf510`.
- Canonical no-write bundle identity:
  `4666041ff61ab23df2c0e4c10af5f4bf6afef526c5f3bb425ddd9d7856cd3dc9`.
- Bundle file SHA-256:
  `70caab4c06bbf74e8e33e5865e4c87d238a041f65492a47854f53dbf969872e8`.
- Preflight file SHA-256:
  `b627b321762ffd0cff0fd69b9240274db517443c254b8b2313f42d3b4a4b09f4`.
- Operational-rehearsal result file SHA-256:
  `d211fce04796785b3234d79323c256aa41f065cbcc2b798369955d7e338f5dd2`.
- Operational-rehearsal seal:
  `54121cf7aea3090b59256f5d755e702cfcf7640fdf2f7030e441548843ecbbed`.

The focused firmware test, exact lower-profile build, structural preflight and
offline analyzer/seal/registration path all passed. The operational rehearsal
performed zero hardware operations.

## Finite physical envelope

The attempt may:

1. flash the exact bound UF2 once;
2. establish one continuously draining serial owner immediately after upload;
3. issue only `CONFIG?` and nonce-bound `ACTIVE SNAPSHOT` queries;
4. observe for at most 120 seconds after capture attachment; and
5. stop capture cleanly and preserve the raw transcript and derived report.

The attempt must not repeat Q2 or Q3, wait for a selected 600-second estimate,
inject transport obstruction, exercise owner rotation or perform any actuator
transaction. Those surfaces are unchanged and already qualified.

## Passing result

A pass requires the exact board, source, configuration and profile identities,
plus one complete nonce-bound generation recording all of:

- `cx317_active.state=DISARMED`;
- `cx317_active.reason=pre_setup_session_rebound`;
- `cx317_active.fail_static=false`;
- a nonzero rebound `session_id`;
- `manual_start_confirmed=false`;
- zero correction count, cumulative movement and DAC epoch; and
- zero setup, DAC value write, arm and automatic transaction activity.

No observed rebind within 120 seconds is inconclusive and stops the attempt.
Any identity mismatch, fault, incomplete generation, serial ownership loss,
parser error or forbidden activity fails closed. Neither outcome authorizes a
live run. A pass permits only construction and rehearsal of a new Q4 candidate
followed by a separate operator authority decision.

