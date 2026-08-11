# CX319 G2 and Conditional G3 Live Authority

## Operator decision

On 2026-08-11 the operator explicitly authorized the exact frozen CX319 G2
Leg A live envelope and, only if G2 is successful, conditionally authorized G3.

The effective G2 authority is bound to:

- proposal bundle
  `4650eef8485c412212c29885fd5407f6adf7de6f71d07babf96f72f8b9a65f34`;
- accelerated operational-rehearsal content
  `7fa6bd6987e29e16548df372ec9150540bffc0e2b55b3d32f3a5d34f71c4ee9a`;
- operational-rehearsal seal
  `5b5e79a3a81a700961b2d7084f929ae0683260d444e2f1cf2b1163eb5effef71`;
- the G1-qualified firmware identity retained by that proposal; and
- the exact device identity and no-flash authority recorded by the activation
  artifact created from those inputs.

## Effective G2 envelope

The authority permits one finite G2 Leg A execution:

- no firmware flash;
- one exact `DAC SET 0xA808` setup transaction;
- positive automatic corrections only;
- at most four automatic corrections, 21 codes per correction and 84 codes
  cumulative automatic movement;
- at least 1800 seconds between applied automatic corrections;
- 900 seconds settling exclusion and 600 seconds fresh support after a write;
- one outstanding request, no automatic retry and no automatic restoration;
- hard DAC range `0xA800..0xAB00`;
- 90-minute qualification deadline and four-hour maximum qualified duration;
- phase and hybrid preview continuously non-actionable; and
- fail-static stop at the last confirmed code on any identity, transaction,
  range, cadence, authority, health, replay, ownership or transport failure.

The activation, runner, analyzer, seal and external evidence registration are
mandatory parts of the same operation. A finite non-pass is retained evidence
and does not authorize a retry, extension or threshold change.

## Conditional G3 authority

The G3 authorization is not presently executable. It becomes usable only if:

1. G2 completes and its immutable live analysis and seal report `passed`;
2. programme status records that exact G2 result;
3. a new upper-leg bundle binds profile `cx319_tight_upper`, setup code
   `0xA848`, negative automatic direction and the same finite bounds;
4. the upper bundle passes structural preflight and a fresh accelerated
   complete operational-path rehearsal; and
5. the G3 activation binds the exact fresh bundle, rehearsal, device and
   passing G2 evidence before any physical action.

If G2 does not pass, G3 remains forbidden. This decision grants no G4,
phase-derived or hybrid-derived actuation authority.
