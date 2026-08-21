# CX320 Stage 5 Authority and Physical Entry

## Effective operator authority

On 2026-08-20 the operator explicitly made Stage 5 effective for root bundle
`62ee48c2e8e20e78f30b5c77d7457b37f6f8495b0a536a6b349f59c777d50fae`
under root proposal
`153577ae94dce4faaf5942a80b4118cd51817e9e291f496b80d75e0a200d38f4`.
The same instruction authorized bounded diagnosis, correction, restart,
reflash and retest while preserving the frozen scientific boundary. The
immutable local authority record has file SHA-256
`d085d394df63698cfcbeeb1e7475beee259d302cfc7a4650c9db835c0b0001c8`.

That authority does not permit changing controller thresholds, acceptance
criteria or duration after seeing evidence. It does not enable automatic
controller retry, automatic restoration or a live extension. Correctable
offline consumers may replay unchanged retained evidence; a correction that
can affect commands, capture, firmware or the scientific result requires a new
identity and the shortest affected rehearsal.

## Pre-entry corrections and successor identity

Review before physical entry found two substantive platform defects in the
root bundle: the materiality counterfactual forced the frequency-only request
to zero whenever phase was authorized, and the bundle did not contain an
executable physical runner/analyzer topology. The materiality definition now
replays the final integer frequency-only request through the same step, range,
count, cumulative and chatter limits with only the phase term removed. The
host and firmware implementations pass parity checks. Corrected replay changed
reported materiality counts but did not change the selected controller or any
scientific threshold, criterion or duration.

The exact successor under the operator's expanded recovery authority is:

- bundle semantic SHA-256
  `de0b6a1d5894991ad3fcbb23773176ff515eae9ae04a3ad3bda0c5a682f3b2aa`
  (file SHA-256
  `cfe78cdc6634f479c6418f72adc7cf31df8ab10c2b83a68a4f4f02be0e2b570d`);
- successor proposal semantic SHA-256
  `35522a56a72a5015e43bf693f4697fe2e33b96a17d54a7d8866b1a095c1e7ed2`
  (file SHA-256
  `33845a25d8afc49416d64951ef1405690468364bae7d81c36121ebf8fdfb9a0b`);
- firmware source/configuration identity
  `7a8139daf68716962d9432f007a563484f9c81a863871a233080de7cc6882434:f800a4b7725992b01682e6d2c9e2be6fa15c956e23662622a928cdd4abe40990`;
- exact UF2 SHA-256
  `ad8aba51903e85a0237a7de2f6a7c037b3353ed236296a27650e26ceae4daab4`;
- corrected replay semantic SHA-256
  `4213b70888f8091a7a399f40c17c271813b545d2c6350e3997ecc6c694a8b824`.

The root bundle, root proposal, authorization record, corrected replay, clean
firmware build, successor proposal and successor bundle are all retained. The
successor proposal records that the scientific thresholds, criteria and
duration are unchanged and binds its authority back to the two root semantic
identities.

## Operational-path gate

The first live-topology rehearsal attempt failed before supervisor start
because its no-I/O guard recognized Linux PTY paths but not the macOS PTY slave
namespace. The retained attempt made no physical action. A focused regression
was added, the host tool was rebound, and the successor bundle was regenerated.

The rebound rehearsal passes with semantic SHA-256
`78be0e257fed3f70ad33834d470226f2effc1068f46b1fa1f597db1f71096ef3`
and file SHA-256
`e753c342fbd99e43394149e078e3b3fea73bb92a72067bed80841c7bb43e88a5`.
It used the real capture and live-supervisor processes over a PTY, proved one
serial owner before and after logical rotation, saturated the normal-command
FIFO, and delivered exactly one independent priority abort before capture
close. The accelerated boundary portion passed setup propagation, progressive
checkpoint, conditional release, response classification, phase-only
degradation, shared fail-static, analysis, sealing and registration. It made
zero physical actions and is not qualification evidence.

The remaining integration boundary is deliberately physical: RP2040 USB CDC
and cross-core runtime, one acknowledged AD5693R setup/application path and the
CX317 plant, plus authoritative D14 PPS and D8 oscillator capture.

## First physical attempt envelope

The next operation is one exact physical Stage 5 attempt on board serial
`503533748A919118`. It permits one firmware upload, one exact `0xA83C` setup,
one arm and one finite acquisition. The limits remain four total automatic
applications, 21 codes per step, 84 cumulative absolute codes, 1,800 seconds
minimum cadence, `0xA800..0xAB00`, 43,200 qualified seconds and 57,600 absolute
wall seconds. The first terminal consumes this activation. Any later attempt
must be separately identified with its reason under the operator's expanded
recovery authority; it is never an automatic controller retry or restoration.

At this record point no serial device has been opened, firmware flashed, board
reset, DAC code written or controller armed for the physical attempt.
