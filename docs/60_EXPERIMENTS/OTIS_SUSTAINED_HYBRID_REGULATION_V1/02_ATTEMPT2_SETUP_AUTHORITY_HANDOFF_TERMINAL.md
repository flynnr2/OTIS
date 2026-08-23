# Attempt 2 setup-authority handoff terminal

## Result

Attempt 2 is a failed qualification due to a firmware defect in the physical
setup-authority handoff. The host retained a complete, current setup snapshot
at status generation 122 and submitted the exact setup command. Before core 1
consumed it, a routine status publication advanced the observation generation
to 123. All decision-bearing setup authority fields remained current, but the
firmware incorrectly treated the observation-generation advance as an
authority change and entered fail-static before setup application.

This is an actual frozen platform/firmware integrity failure, not
characterization. Setup was not confirmed, no DAC-step or active-transaction
row was retained, and no qualified origin was established.

## Milestone timeline

All times are UTC on 2026-08-23.

| Time | Milestone or action | Retained evidence |
| --- | --- | --- |
| 15:59:00 | Physical wall origin established after the exact firmware flash and board re-identification. | Run manifest and firmware-entry report. |
| 16:09:15 | Solicited setup-authority snapshot generation 122 completed with nonce `3421213496`, session 1, all setup readiness fields true. | Raw serial status and retained setup-authority input. |
| 16:09:16 | Host submitted `ACTIVE SETUP` for code `43068` (`0xA83C`), generation 122. | Supervisor event and raw host command. |
| 16:09:16 | Routine status generation 123 began before core 1 consumed the setup request. | Raw serial status ordering. |
| 16:09:16 | Core 1 rejected the still-current request and firmware recorded `setup_current_authority_rejected`. | `cx317_setup` and `cx317_active` status records. |
| 16:09:26 | Supervisor observed `active_fail_static` and submitted one independent emergency abort. | Supervisor terminal and events. |
| 16:09:27 | Abort delivery was retained, then sole-owner capture closed cleanly and the run reached `COMPLETE`. | Capture state and `COMPLETE`. |
| 16:09:28 | Failed evidence was sealed and registered. | Physical seal and external evidence index. |

## Exact terminal evidence

- Run: `runs/otis_sustained_hybrid_regulation_v1/live_attempt2_20260823T1559Z`
- Activation SHA-256: `0363c73efdcbac28fbd512bf4a6cdad8bf0424dd7f4dab73d85365cd458a2c1c`
- Bundle SHA-256: `0607f0845fb5f27d31e23cd29bcf43704900e5cfcedae2f2f25452b36e81c227`
- Firmware build identity: `eed211ca7e3cc68b428ab77ee4c06ff937b3ef4eb58dd4908682b047801827cc:ad8feae0d5f99b5089a1777ca227e2791f8ee4379f181df004b5c95c2afd2d78`
- UF2 SHA-256: `aeea82c276d5c5f536e00b1246dee003d00e44673210112fe3e0af0228cc9e7c`
- Seal SHA-256: `74d37d1afa834806b00817acac8e56ef657ceb67b35069017eb225c7348d3836`
- Seal file SHA-256: `8be4963a5cf0e5766d6bf513cf68b993ae883d5f710cd8ec5f1ed75dbe6d91c5`
- Registered evidence content SHA-256: `72eba172056c71cfa3f602e772d10eee9dc1ee958b04884fa2bd87088a4b1b7e`
- Registered file count: 36

## Bounded repair

The retained snapshot generation remains part of the exact command identity.
Firmware now distinguishes that retained observation identity from the later
current observation frontier: a later generation is accepted only while the
exact nonce, session, setup code, configuration identity, device-time expiry,
capture lease, GNSS and reference eligibility, partition health, disarmed
state, and one-shot state remain current. A future or contradictory generation
still rejects.

The production setup-authority harness and the diagnostic multi-phase case
engine now exercise an intervening generation advance and confirm that the
original request generation survives through core-0 acceptance and execution
release. The change does not relax any safety, scientific, actuation, retry,
or restoration criterion.
