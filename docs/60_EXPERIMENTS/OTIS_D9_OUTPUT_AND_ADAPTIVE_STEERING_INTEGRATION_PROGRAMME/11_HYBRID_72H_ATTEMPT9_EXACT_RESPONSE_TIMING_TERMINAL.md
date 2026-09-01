# Hybrid 72-Hour Attempt 9 Exact-Response-Timing Terminal

## Verdict

Campaign19 Attempt 9 retained a useful but incomplete physical acquisition
prefix and failed the formal acquisition, offline-finalization and CX323
qualification gates. The retained package is
`runs/d9_adaptive_steering_integration_20260828/long_runs/hybrid_72h_attempt9`.
It established its qualified origin at 2026-09-01T08:00:15Z and retained
15,851.376625 exact counter-domain qualified seconds before the independent
abort. It did not establish the 72-hour endpoint.

The setup established `0xA84D` at DAC epoch 1. Twenty-four 600-second
maintenance decisions then produced one automatic request. The exact
request/acceptance/application chain applied +5 codes once, moving `0xA84D`
to `0xA852` and advancing to DAC epoch 2. The raw demand was
5.475213574925 codes; the committed residual debt was 0.475213574925 code,
split into 0.417260699934 FLL code and 0.057952874991 PLL code.

The response record reported a change from -0.001666667 Hz to 0 Hz and was
classified `healthy_indeterminate_near_resolution`. That observation remains
retained physical evidence, but it does not satisfy the frozen response
checkpoint. Application occurred at exact extended tick 259,311,385,072 and
response completion at 283,310,422,736. The elapsed 23,999,037,664 ticks are
1,499.939854 seconds: 962,336 ticks, or 60.146 milliseconds, short of the
required 24,000,000,000-tick/1,500-second minimum.

## Timeline

| UTC | Milestone |
| --- | --- |
| 2026-09-01 07:20:05--07:20:16 | The frozen Attempt 9 UF2 was flashed with fresh `--auto-detect`; board serial `503533748A919118` reappeared on `/dev/cu.usbmodem14401`. |
| 07:30:28 | One exact setup established `0xA84D`, DAC epoch 1. |
| 08:00:15 | Qualified origin established at tick 38,415,972,608 from selected-600 estimate `est:cx317:selected600:000541`. |
| 11:50:17--11:50:27 | Request 1 was created, accepted and applied; the code became `0xA852`, epoch 2. |
| 12:15:26 | The host acknowledged response record 5. Exact replay later proved the firmware completion was 60.146 ms early. |
| 12:24:26 | The independent priority path sent `ACTIVE ABORT`; Core 1 accepted it before fail-static asserted. |
| 12:24:29 | The sole serial owner closed capture cleanly. |
| 12:25:15--12:25:19 | The original failed seal and external registration were completed and preserved. |
| 12:41:21--12:41:46 | Corrected offline replay produced and registered the superseding failed seal over unchanged raw acquisition evidence. |

The final supervisory ARM was written before the priority abort was submitted.
It produced no second request or application. The transaction history remains
five records with exactly one automatic application and one response. The last
confirmed static code is `0xA852`.

## Oscillator and capture evidence

The 18,253 retained D8 one-second count intervals contained 16,609 intervals
at exactly 10,000,000 edges, 824 at 9,999,999, and 820 at 10,000,001. The 25
non-overlapping selected-600 estimates contained fifteen zero-error windows,
seven -1-cycle windows and three +1-cycle windows; no selected window exceeded
one cycle in magnitude. Qualified raw relative phase remained between 0 and
-5 cycles and ended at -4 cycles.

This is stable, quantization-scale D14-referenced D8 evidence for the retained
prefix. It is not an absolute-frequency, UTC, waveform, load or traceability
claim. D9 source/divider/GPIO/readback remained exact; D6 remained diagnostic
and zero authority.

Capture retained 100,595,635 bytes, 835,162 parsed lines, zero parser errors,
zero reconnects, zero rejected commands, one serial owner and one independently
delivered abort. The original external registered package content SHA-256 is
`8c27faa4cf74f45af5deff93ea1896a2c5744bbf3c288fe72fc0f1144948aa69`.

## Cause and bounded repair

Firmware propagated the exact application tick into AT2 and AHM evidence, but
the post-application estimator exclusion was scheduled from floored integer
`uptime_s`. CX323 completed `AWAITING_RESPONSE` at the first later selected-600
estimate. A fractional-second application could therefore admit one D14
interval whose opening edge preceded the exact 900-second settling deadline
and complete by almost one second early.

The repair now compares each interval's exact opening D14 boundary, in the same
extended `rp2040_timer0` domain and capture session, against
`application_ticks + 900 seconds`. It then requires 600 complete eligible D14
intervals. Integer-aligned applications may complete at exactly 1,500 seconds;
fractional applications complete at the first full eligible interval between
1,500 and 1,501 seconds.

The analyzer now applies the same 24,000,000,000-tick minimum. Literal Attempt
8 and Attempt 9 regressions reject their early response ticks, while the exact
boundary passes. CX323 replay also binds its inherited diagnostic TDB stream to
the frozen `352dae...` policy identity and no longer borrows CX322-only coarse
response-horizon facts.

The repaired commit is `243f735`. Two hundred forty affected tests passed. A
clean exact `cx323_d9_d6_72h_adaptive_hybrid` profile build passed with source
SHA-256 `252629b515b30426c365c0ccb2f3c64d7e196ca3408124fa8dd321c3036b2fe0`
and configuration SHA-256
`78f73ca54d9cb87f46a0511742487d8c81bc4867e876a403e0707196cd98f99b`.
These identities qualify the repair build only; they are not an activation for
another physical attempt.

## Superseding analysis, seal and registration

The original seal is preserved with semantic SHA-256
`bad0f6bfc74a7b66ca193b24c5ee48b89969c0f8ec519e464f941a50dea0163a`
and file SHA-256
`62e1807beaf0ae7d613702343408d0271d38460f8542a5f0dca3dc4cbc8d5b5a`.
The corrected analyzer has SHA-256
`566e50385fa3e39f7831116df43efeb7d528478a8e0e9b188925f74f6d18df32`.
It produced the separate superseding seal
`reports/cx323_d9_d6_72h_physical_seal_superseding_v2.json` with:

- semantic SHA-256
  `dd6b26129ab40276074fc84b9915c4400d291b00132c1eafb3d7b5dca7ccc052`;
- file SHA-256
  `6c7dd2b603f943f7203d2e1a191eff133f198a87fc3de9d7d7480021ab44fbcb`;
- registered package content SHA-256
  `ba6872640e0dc4ed984164c0638c8df3529670bad6ab036404b9e947fb01af6e`.

The retained-input, declared-CSV, TDB, raw-measurement, transaction,
classifier, maintenance, application, capture and abort source/identity
validations pass in the superseding replay. The seal still fails its exact
lifecycle timing join on the frozen response minimum, its static-terminal
check because `0xA852` remains applied, and its incomplete endpoint. Therefore
both the formal acquisition and offline-finalization gates remain failed. No
raw acquisition artifact or frozen acceptance threshold was changed.

The original Attempt 9, superseding Attempt 9 and superseding Attempt 8
registration records cited by these terminal reports are retained in the
external index at `$HOME/.local/share/otis/evidence_index_v1.json`; the two
current superseding package identities match their recorded storage locations.
Adding the superseding reports in place necessarily changed the
package-directory identities, so the index's older Attempt 8 and Attempt 9
registrations now report mismatches at those same locations. The old records
and original seals remain preserved, but using separate immutable supersession
directories is archival debt for the next finalization workflow.

## Remaining debt and next boundary

The active-run host findings were repaired without interrupting healthy
capture: expected pre-setup header-only AHM handling, the prospective
qualification deadline abort, the CX323 success endpoint identity, and the two
CX323-specific offline replay bindings now have deterministic coverage. The
scientifically material defect was the firmware exact-timing escape described
above.

Attempt 9's single-use activation is consumed and cannot be retried or extended.
No Attempt 10 is authorized by this report. Any later physical attempt requires
a fresh immutable bundle around the committed repair, a complete operational
path rehearsal including the fractional exact-tick boundary and abort/seal/
registration path, a fresh `--auto-detect` flash/readback, and exact live entry
qualification before a new 72-hour origin may be established.
