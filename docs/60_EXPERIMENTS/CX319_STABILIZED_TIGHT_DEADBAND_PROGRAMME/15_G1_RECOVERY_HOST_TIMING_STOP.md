# CX319 G1 Recovery Host-Timing Stop

## Result

The one exact lower-profile flash authorized on 2026-08-11 succeeded on the
first and only attempt. The same board, serial `503533748A919118`, returned on
`/dev/cu.usbmodem14601` after automatic reset. The physical G1 no-write
requalification then stopped fail-static after about 30 seconds, before its
scientific qualification interval.

The retained run is
`runs/cx319_stabilized_tight_deadband/g1/no_write_recovery_leg_a_20260811T200913Z`.
Its registered evidence content SHA-256 is
`75c511fb39e4d4c53f907726a1abd5bdc1bad0eb510c690d397bf96c6304d246`.

## Exact bindings

- source revision: `af563d248d180897d891026007ba1073075fda3c`;
- frozen bundle SHA-256:
  `ef794c8f4b1907b46554d0e4c13a85ffea0d7ee5834bb8564c1c314f18162980`;
- build-manifest SHA-256:
  `0d5c8633a75c87705744e8abb36a0d0969246a32d2568fd661dfabbe9c68efe6`;
- flashed UF2 SHA-256:
  `f2a125aaf010bd4eed4c9cff35fbef80b8d88e453dbac7cda63529f3ac66b901`;
- flash-record file SHA-256:
  `40f884803177a671b969f0007d849c54f083c62199b943505d3882ebf96be065`;
  and
- failed-orchestration record file SHA-256:
  `f2935542f7d522885748a17aed6cbe2fa607651ecf388cd6a4c5434d15820ba1`.

The authority in `14_G1_RECOVERY_NO_WRITE_AUTHORITY.md` is consumed. It grants
no second flash or physical run.

## Cross-surface diagnosis

The firmware repair did what G1 needed to establish: GNSS metadata was healthy,
the receiver remained in identity epoch 1, and metadata control eligibility was
true. Raw PPS control eligibility remained false because this exact firmware
profile deliberately enforces a 600-second startup inhibit followed by clean
qualification windows. Retained passing G1 evidence places the first combined
raw-PPS control-eligible state at about 612 seconds.

The inherited host supervisor instead treated any incomplete pre-write state
at 30 seconds as terminal. That timeout is valid for the older CX318 predicate
but cannot validate the stronger CX319 GNSS/PPS predicate. This is a platform
defect caught by the physical no-write rehearsal, not a firmware or scientific
rejection.

The run issued no DAC value write, setup stimulus, control arm or automatic
correction. The capture closed with zero reconnects and zero parser errors;
the independent emergency abort was the only side-effecting command.

## Recovery boundary

Offline recovery must separate two clocks:

1. host attachment and continuous drainage must begin after a fresh restart
   within the frozen 120-second limit; and
2. the exact GNSS/PPS pre-write predicate may then take up to a separately
   bounded 660-second qualification deadline.

G1 and G2 must record and analyze both facts independently. A complete
operational-path rehearsal must exercise the long startup boundary, the actual
analyzer and sealing path, host-attachment failure, and GNSS/PPS qualification
failure. Because the exact firmware flash succeeded and firmware inputs are
unchanged, the next physical proposal should reuse that confirmed installed
firmware without flashing. It requires fresh operator authority for one
no-flash G1 run. G2 and G3 remain blocked.
