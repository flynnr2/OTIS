# Attempt 3 command-ingress latency terminal

## Result

Attempt 3 is a failed qualification due to a host capture-path defect. The
setup-authority repair under test passed its physical integration boundary:
the host bound setup status generation 122 and the exact request identity
survived firmware receipt, core-1 authorization, core-0 acceptance, execution
release, application, and the first dependent consumer. The programme then
established a qualified origin and completed four natural physical
transactions with exact response identity through their first later dependent
decisions.

At 21:28:31 UTC the supervisor submitted fresh lease sequence 3185 while a
large solicited active-status batch was being captured. The capture path
recorded and split the serial stream but did not service the normal-command
FIFO before the frozen three-second acknowledgement deadline. The lease was
never written to the device. The independent emergency FIFO remained healthy,
and the runner performed the required fail-static abort.

This is an actual platform escape, not characterization and not a scientific
rejection. Zero-code decisions, phase materiality, and the four
`healthy_indeterminate_near_resolution` responses remained permitted
characterization. The fifth application was retained exactly but its response
horizon was right-censored by the platform terminal.

## Milestone timeline

All times are UTC on 2026-08-23.

| Time | Milestone or action | Retained evidence |
| --- | --- | --- |
| 16:56:45 | Physical wall origin established after the exact firmware flash and board re-identification. | Run manifest and firmware-entry report. |
| 17:06:57–17:06:59 | Setup bound generation 122 and propagated through firmware receipt, core-1 authorization, core-0 acceptance, execution release, application at `0xA83C`, DAC epoch 1, and its first dependent consumer. | Setup-authority input, raw status and supervisor evidence. |
| 17:36:43 | Qualified origin established at estimate `est:cx317:selected600:000541`, device tick `38416611536` in `rp2040_timer0`, session 1. | Supervisor state and selected-estimate evidence. |
| 17:56:43 | First eligible natural decision retained as a zero-code characterization with no DAC write. | AHY decision 3. |
| 18:26:42–19:01:52 | Request 1 completed: delta -6, code `0xA836`, application 1, DAC epoch 2, durable response and exact dependent consumer. First checkpoint passed and later authority released. | ACT records 2–5 and AHY decision 8. |
| 19:11:44–19:46:50 | Request 2 completed: delta -1, code `0xA835`, application 2, DAC epoch 3, durable response and exact dependent consumer. | ACT records 6–9 and AHY decision 11. |
| 19:56:47–20:31:51 | Request 3 completed: delta -1, code `0xA834`, application 3, DAC epoch 4, durable response and exact dependent consumer. | ACT records 10–13 and AHY decision 14. |
| 20:31:51–21:06:56 | Request 4 completed: delta -1, code `0xA833`, application 4, DAC epoch 5, durable response and exact dependent consumer. | ACT records 14–17 and AHY decision 16. |
| 21:06:56–21:07:01 | Request 5 reached application: delta -1, code `0xA832`, application 5, DAC epoch 6. | ACT records 18–20. |
| 21:28:31 | Supervisor submitted `ACTIVE LEASE 3185`; capture did not acknowledge it within three seconds. | Supervisor events; no corresponding raw host-command acceptance or send marker. |
| 21:28:34 | Supervisor froze the run as `measurement_authority_or_platform_fault` and submitted one priority abort. | Supervisor terminal and abort-submission event. |
| 21:28:34–21:28:37 | Sole capture owner delivered `ACTIVE ABORT`, retained firmware `FAIL_STATIC`, and closed cleanly with zero parser errors, reconnects or rejected commands. | Raw serial, capture state, closure and `COMPLETE`. |
| 21:28:58–21:29:00 | Offline analysis and failed seal completed; the immutable package was registered externally. | Physical seal and evidence index. |

## Exact terminal evidence

- Run: `runs/otis_sustained_hybrid_regulation_v1/live_attempt3_20260823T1657Z`
- Activation SHA-256: `acfba2e0a381fdce172489811170ef10e9dd93f8d70a86a1f2082dde825d8a93`
- Bundle SHA-256: `4afb7bc23ed63873b32f6d720a58f83dad4fb8180c6a06da287eb53af685b683`
- Bundle file SHA-256: `276ef6140d2ca4e5e9cdfc2ced1073c8baa6da9633281dd5d5675e321cf6a6e0`
- Firmware build identity: `bfa206c69f2d5ebaa117fae466d93a13d4701ee91673943ba7e885a7aefe94d8:ad8feae0d5f99b5089a1777ca227e2791f8ee4379f181df004b5c95c2afd2d78`
- UF2 SHA-256: `673c9296165e04480d149f1456088af34ec6220ea556e62b5650e384777bb1cb`
- Last confirmed code and epoch: `43058` (`0xA832`), DAC epoch 6
- Seal SHA-256: `d5ebf5987f8fc3795319cc88bb733bbdb740449a10dc76af964d7ff95636db55`
- Seal file SHA-256: `28e3066fa33927afdda3d316238be08f95adcb3726884f4a90912894e051ea0e`
- Registered evidence content SHA-256: `7cbfda0d1fca1b1e1be63607864cda313321d7b90af3dd4f6d7bdd10d42ab38f`
- Registered file count: 55

## Bounded repair

Normal command ingress is now serviced immediately after each serial read is
placed in canonical raw evidence and before the batch is passed to CSV and
live-status consumers. Emergency ingress remains first and can still revoke
normal ingress atomically. A deterministic regression queues a fresh lease
during serial read and requires the serial write to occur before the first
downstream record consumer runs.

This changes no command envelope, freshness limit, acknowledgement deadline,
firmware protocol, control law, safety criterion, retry rule, restoration rule,
or scientific acceptance predicate. A later physical attempt still requires
the exact affected profile build and the complete operational-path rehearsal.
