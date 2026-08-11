# CX319 G2 v7 GNSS-Identity Qualification Stop

## Outcome

The authorized G2 v7 run reached the canonical 90-minute qualification
deadline at 2026-08-11T18:38:58Z without qualification starting. Its analyzer
status is `failed`; this is not a passing G2 result. The exact v7 activation is
retired, no G2 retry is authorized, and the conditional G3 upper-profile flash
and live execution remain dormant.

The retained package is
`runs/cx319_stabilized_tight_deadband/g2/live_leg_a_v7_20260811T170842Z`.
Its complete evidence snapshot has digest
`8e5ec0aeb28fd8a6dafcaf50849dd46c88409c2b901d1dbf6bd5e0542ff8f099`.
The failed seal has intrinsic SHA-256
`7d4a10f0d70d866d53bb9f95270e5369b235814fbefe3c5a4e9624943399670e`
and file SHA-256
`a90216aadf1d8e18f294112755c708df3d10697b9fb7431c48b49d979f3a394f`.
The package was registered as `interrupted_campaign` with content SHA-256
`530def1cdbc3353de48bfdd7f0fd4380ea55020bdca0fad0ea73252ccfe29980`.

## Containment and retained facts

The run applied the one authorized setup stimulus, `DAC SET 0xA808`, and no
other write. It never armed and applied no automatic correction. The
supervisor records `qualification_started_utc=null`, `tight_entry_seen=false`
and terminal reason `stage5_qualification_deadline_expired`.

The attachment-baseline repair behaved as rehearsed: ordinary telemetry loss
froze at the cumulative startup value 3 on status sequence 809 and never
increased during the evidence-bearing interval. The analyzer reports clean
runtime-health integrity. Capture closed its physical serial device with zero
transport reconnects and zero parser errors. The complete evidence snapshot
was finalized and externally registered.

## Cross-surface cause

The first retained GNSS health emission reported receiver identity epoch 2,
`identity_stable=false` and `control_eligible=false`. Those values remained
unchanged through the run. The single checksum failure was later
requalifiable, but identity epoch 2 was not: this firmware deliberately makes
only epoch 1 authoritative within a run after a receiver outage longer than
the reconnect gap. Consequently the firmware never produced a qualified
reference observation or control-eligible estimate.

The host pre-write contract reported ready and permitted the setup stimulus
without requiring the GNSS receiver to be identity-stable or control-eligible.
This is therefore a platform escape into the campaign across the firmware and
host gate surface, not evidence that the lower-side controller passed or
failed scientifically. Firmware contained the actuation risk by remaining
disarmed, but the host allowed a long run whose qualification prerequisite was
already permanently unsatisfied.

## Recovery gate

Offline work may now define and rehearse a cross-surface recovery. It must, at
minimum:

1. make the host pre-write gate reject an already non-authoritative GNSS
   identity before any setup write;
2. exercise the real GNSS startup/reconnect path in the operational rehearsal,
   including the epoch-2 condition and its bounded stop;
3. decide explicitly whether the observed startup gap should begin a fresh
   firmware identity epoch or whether it represents an invalid run requiring a
   fresh restart; and
4. bind any resulting firmware and host changes into a new exact bundle,
   preflight and complete operational-path rehearsal.

That offline result may support an operator decision, but it does not grant a
retry. G3 remains forbidden unless a future G2 run has a passing analysis and
seal.
