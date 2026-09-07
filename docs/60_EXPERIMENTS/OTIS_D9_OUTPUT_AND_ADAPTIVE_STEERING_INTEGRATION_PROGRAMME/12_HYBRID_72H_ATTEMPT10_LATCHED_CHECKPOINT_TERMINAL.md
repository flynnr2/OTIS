# Hybrid 72-Hour Attempt 10 Latched-Checkpoint Terminal

## Verdict

Campaign19 Attempt 10 retained a valid but truncated physical acquisition
prefix. It is an interrupted campaign caused by a host platform
semantic-contract escape, not a scientific rejection of the CX323 controller
and not a D14/D8 capture failure. The authoritative retained package is
`runs/d9_adaptive_steering_integration_20260828/long_runs/hybrid_72h_attempt10`.

The run established its qualified origin at 2026-09-01T16:13:41Z, at D14
reference sequence 2,399, and passed the exact 86,400-qualified-aperture
milestone at reference sequence 88,799. The last supervisor-qualified frontier
was 89,710 of the required 259,200 apertures (34.610339506%), at reference
sequence 92,109. The canonical second-decision source window extended two
apertures farther, through reference sequence 92,111. This is expected
snapshot lag, not contradictory timing evidence. No 72-hour endpoint was
established.

Setup established `0xA84D` at DAC epoch 1. Two automatic phase-material
applications then each applied `-1` code:

- request 1 applied `0xA84D -> 0xA84C`, DAC epoch 2;
- request 2 applied `0xA84C -> 0xA84B`, DAC epoch 3.

The resulting physical-control count is two applications and two codes of
cumulative movement. The first transaction completed its response and released
later authority. The second application and its first downstream consumer are
present in canonical firmware evidence, but the host aborted before it
acknowledged and durably encapsulated the application phase or observed its
response.

## Exact chronology

| UTC or exact boundary | Milestone |
| --- | --- |
| 2026-09-01 15:33:42Z | Attempt 10 wall origin and run manifest were created. |
| 15:43:52--15:43:53Z | The sole setup transaction established `0xA84D`, epoch 1. |
| 16:13:41Z | Qualification established origin estimate `est:cx317:selected600:000541`, D14 reference sequence 2,399, and qualified-aperture origin 2,399. |
| 2026-09-02 about 16:13:41Z | Reference sequence 88,799 completed exactly 86,400 accepted D14 apertures from the qualified origin. The acceptance is defined by the integer aperture count; UTC is display context. |
| 16:33:47--16:34:00Z | Request 1, sourced from references 89,399--89,999 (87,600 apertures after origin), was created, accepted and applied. Exact application timestamp was 1,440,190,778,288 in `rp2040_timer0_extended`; code became `0xA84C`, epoch 2. |
| 16:58:57Z | Response 1 completed at timestamp 1,464,205,318,656. Its 24,014,540,368-unit application-to-response interval is 1,500.908773 seconds. It was classified `healthy_indeterminate_near_resolution`; the host durably observed the first observational checkpoint and released later authority. |
| 17:08:57--17:09:03Z | Request 2, sourced from references 91,511--92,111 (89,712 apertures after origin), was created and accepted for `-1`, targeting `0xA84B`. |
| immediately before the abort | Canonical AT2 record 8 and AHM record 153 record application timestamp 1,473,988,469,312, `0xA84B`, epoch 3, followed by the exact first-consumer commit. The two applications were 2,112.355689 seconds apart. |
| 17:09:03--17:09:04Z | The supervisor raised `CX320 later material authority preceded its checkpoint` and submitted the priority abort. The retained raw order is application, first-consumer commit, host `ACTIVE ABORT`, Core 1 abort acceptance, then `fail_static=true`. |
| 17:09:06--17:09:07Z | Capture closed cleanly and `COMPLETE` retained the interrupted terminal. |
| 17:09:34--17:11:33Z | Immutable snapshot, failed analysis/seal and external registration completed. |

The `rp2040_timer0` and `rp2040_timer0_extended` values above are retained
integer-domain evidence. Their physical source is the RP2040 1-microsecond
timer multiplied by 16, so their quantum is 16 stored units, or 1 microsecond;
they do not establish 62.5-nanosecond resolution or a D8-derived metrological
timebase. This does not affect the first response decision: its margin over the
frozen 1,500-second minimum is about 908.773 milliseconds.

## Terminal, capture and immutable identities

The last confirmed physical applied code and fail-static code is `0xA84B`.
The raw order proves that application and its first consumer preceded the
independently delivered abort. The original seal nevertheless reports
`static_terminal_exact=false`: the host stopped before the second application
capsule, response and final disarmed/evidence-clear snapshot could complete.
This formal gate failure must not be rewritten as proof that the DAC reverted
or that the last confirmed code is unknown.

Capture retained 520,332,746 bytes, 4,231,163 parsed lines, zero parser errors,
zero reconnects, zero rejected commands, one serial owner and one independently
delivered abort. Capture closed at 2026-09-02T17:09:06Z; no capture or
supervisor process remains and the serial port is closed.

The immutable identities are:

- source revision `f5ccf1975c73a26983d5460e62f71d23cc876827`;
- source SHA-256
  `70ba83057537197f8659379548caeb3369d8d9782f423cc7128ce30ba6f587a4`;
- configuration SHA-256
  `78f73ca54d9cb87f46a0511742487d8c81bc4867e876a403e0707196cd98f99b`;
- exact bundle SHA-256
  `5a171f014d9a98a158394a64617017981ec0f72c685747005887a66e59c5b560`;
- UF2 SHA-256
  `0d5b17cec8b83fb17ba1763650562b96ea60622b2556c7fb5c50493b7b045ca8`;
- evidence snapshot digest
  `b72bcc46fc424aaa236fe07c459c05b42c0dddc8bb74a28aa2fb93a02a257daa`;
- seal semantic SHA-256
  `818ac40a202ed9081cbb84b3de64fbd359bc1964fa05bb30386c961086b743c1`;
- sealed report file SHA-256
  `c490fc55fa0f6ccd9474a07bc30f18fa8f08d6a2176570b7b3848310ef73d723`;
- analyzer identity
  `b117c2d866c201aae0337353aec067b61e340f9ac5308608ccac6b77d825a3ea`;
- registered package content SHA-256
  `3b87b04affb317a923e0da02558412ad7b71aa514b4243b6b9703b4dab1bea5e`.

The external evidence index at
`$HOME/.local/share/otis/evidence_index_v1.json` uses that package content
digest as its key, records 47 files and 1,098,574,851 bytes, classifies the
attempt as `interrupted_campaign`, and points to the retained Attempt 10
directory. Its `lifecycle_status=active` means retained and not mothballed; it
does not mean that acquisition is still running.

## Cause and bounded repair

Firmware correctly clears its current-transaction
`first_phase_checkpoint_passed` flag when a later material transaction starts.
The Attempt 10 host invariant incorrectly required that transient flag to
remain true whenever the cumulative material-application count exceeded one.
It therefore rejected the legitimate second transaction even though the host
had already durably latched `later_authority_released=true` at 16:58:57Z.

The bounded host repair gates later material authority on that durable latched
release, while retaining the negative invariant that a second material
application without a prior observed checkpoint is fatal. The regression must
cover both states and preserve the newly confirmed `0xA84B`/epoch-3 physical
state before any post-application accounting fault. The actual operational-path
rehearsal must exercise a full first transaction and checkpoint, a second
material request/application and first consumer, then the obstruction,
priority-abort, capture-close, analysis, seal and registration path.

This was a reusable host-platform semantic-contract escape into a physical
campaign. It does not require a firmware-controller change, but it does require
a fresh immutable bundle because the frozen supervisor, rehearsal and
activation tools change.

## Scientific boundary and Attempt 11 readiness

The first response is valid physical evidence and its observational checkpoint
passed. Offline phase replay over the available first post-application segment
reports an exact 1,800-observation comparison and 1.365874 cycles of matched
improvement. That is useful descriptive evidence only. Frequency performance
is incomplete, the second response is absent, and the required 259,200-aperture
endpoint does not exist. Attempt 10 therefore neither accepts nor scientifically
rejects the controller, and its missing 72-hour result cannot be repaired by
offline replay.

Before a possible Attempt 11, the narrow repair must pass its deterministic
regressions, the affected campaign verification and the complete repeated-
transaction operational rehearsal. Activation must bind this exact registered
Attempt 10 predecessor, freeze fresh tool and artifact identities, use a fresh
`--auto-detect` flash/readback, and repeat exact live entry qualification.

This terminal report does not authorize, flash or launch Attempt 11.
