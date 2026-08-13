# CX319 Current-Image ASL Formatter Stop, Fix and Qualification

## Decision

The first live attempt using the current-image Q4 candidate stopped before
setup or any actuator write because capture observed one malformed UTF-8 frame.
The stop was correct. The retained raw bytes identify a firmware formatting
defect in the association-loss (`ASL`) evidence record, not a USB transport
failure.

The defect is repaired, guarded at source, built reproducibly, and the exact
repaired image has passed a focused physical no-write qualification. The
successful Q2/Q3 evidence remains canonical because neither its scientific
inputs nor topology changed. A fresh Q4 candidate may now be prepared from the
repaired image under the unattended phase authority in document 32.

## Prewrite live stop

- Run: `live_leg_a_current_image_20260813T093526Z`.
- Activation identity:
  `546944a7feac4462e5230c29a3709dbe13c74f0b1c5127a79c872318dfbdfe1f`.
- Run-manifest file SHA-256:
  `88242b303b4aef9b3922bc758f4014872386a8381cfcec6b2c3169ea43aeb30a`.
- Raw serial SHA-256:
  `49b61486557b50b1eaa11fe42d023bcda1f6de4893f29eb37f6b477530f24aeb`.
- Failure-record file SHA-256:
  `e9b57229e422383c3c10d62f7d3b15c8f6f9a73b6738aff157e7cd0bdee3bbce`.
- Registered package identity:
  `1fec3614e4c2ead73a62858834910c3a04b6e1c9241a05010c285f3aa9829815`.

The terminal reason was
`cx319_g2_supervisor_fault:capture transport counter malformed_utf8 is 1`.
Capture had sent `CONFIG?`, `DAC?`, `ACTIVE LEASE`, `ACTIVE SNAPSHOT`, and the
independent emergency abort. It recorded zero reconnects and zero parser
errors. Setup stimuli, DAC value writes, control arms and automatic
corrections were all zero, so this run contains no plant or Q4 scientific
result.

## Root cause and repair

The retained raw stream contains the beginning of an `ASL` record followed by
binary bytes where `core1_phase` should occur. The `snprintf` call supplied 32
variadic values to only 31 conversion specifiers. Consequently,
`core1_last_snapshot_sequence` was consumed as the `%s` argument for
`core1_phase`, producing an invalid pointer read and corrupting the frame.

Commit `21e8cf9de247ab53bad097c37dba3b12702dc5b4` adds the missing unsigned
integer conversion and a source guard that binds all 32 values to the 34-field
ASL contract, including the final four argument types. The focused association
loss, dual-core partition, and PPS boundary tests passed: 23 tests total.

The exact lower-side profile then built reproducibly:

- firmware source SHA-256:
  `57b4d15d40ccbe10f8628d0530e5ba2f8f803e2bc9dc2c34c1851e531dbdec71`;
- unchanged configuration SHA-256:
  `a88c491c2118c75620b63231ae4ffc301b94a999159eacfb001136f280caec16`;
- build-manifest file SHA-256:
  `7b0e04c3254756f2b57528a852a9fc47a1bd19a41bd7b7fed6fc87ce2af86f82`;
- UF2 SHA-256:
  `1f3563c244b3da47ea9d477b685e8edd91e13659cc3c33e6f0c1404fd1879d11`.

## Focused physical qualification

- Passing run: `asl_formatter_exact_flash_qualification_20260813T094505Z`.
- Exact firmware-entry bundle identity:
  `9ef250e21d371da4eb7ad1f9b7813e36b127321a2dbc03ed222ecdbd05026680`.
- Flash-record file SHA-256:
  `23fe8a99939c5dbb5f81a8633e6471a451bfd2e8359be0f9a4b7aa3e8171980f`.
- Raw serial SHA-256:
  `0ce0e42955f68e23b1d8ba37bfa0003617252f143a90efaad63aaded7ac677a0`.
- Result file SHA-256:
  `9f1f781308711b57dd28e1c44b8e7e79271bcd907870124793d646f43b8fe2be`.
- Evidence-manifest file SHA-256:
  `18831b38c192298049441adffeac8caff170064aaa3fc9c35847fb73971349b1`.
- Evidence snapshot identity:
  `32e855f49c6feeaf50ecd08bd4449420775ebe9bddc46d2f7c71f6bed265e553`.
- Registered package identity:
  `fb3c7bcb78003b77d0ffb01b260be97cf0c49614bde16ca85be4a161b5df9fb9`.

The exact repaired image was flashed once. The physical path then sent the
same prewrite command classes that preceded the stop: `CONFIG?`, `DAC?`, one
lease, and three nonce-bound snapshots. All snapshots reported the repaired
build identity, `DISARMED`, `initialized_disarmed`, session 1, and zero
correction, cumulative movement and DAC epoch. Snapshot sends were separated
by 5.002208 s and 5.000738 s. Ordinary telemetry drops remained zero.

Capture closed cleanly with six commands sent, zero rejected commands, zero
malformed UTF-8 frames, zero parser errors, zero reconnects, zero active
transactions and zero DAC steps. The ASL condition did not recur naturally in
this short run. The repaired formatter is therefore covered directly by the
source/contract regression and remains protected in the physical live path by
the absolute malformed-frame stop; the focused physical claim is limited to
the repaired image identity and clean prewrite transport path.

An earlier exact-flash attempt, retained locally as
`asl_formatter_exact_flash_qualification_20260813T094322Z`, expected an ASL
row to occur spontaneously and stopped when none appeared. It performed no
actuation. That was an inadequate stimulus assumption, not a firmware failure,
and was not promoted as qualification evidence.

## Supersession and next gate

The pass in document 33 remains valid evidence for its original firmware but
cannot qualify this changed UF2. This document's focused pass supersedes it
only as the current-image binding. It does not repeat or supersede Q2/Q3.

The next gate is a fresh candidate-specific structural preflight and
accelerated operational-path rehearsal, then the already authorized finite
physical Q4 lower-side run.
