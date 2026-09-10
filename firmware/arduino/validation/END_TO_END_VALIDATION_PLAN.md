# Fixed-Image End-to-End Validation Plan

This plan covers the current `adaptive_hybrid_regulation` operating path only.
It does not provide compatibility validation for historical programmes.

## No-hardware release gate

Run:

```bash
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier release
```

The release gate must establish:

1. one fixed build manifest and one fixed-image builder;
2. no retired campaign identity, selector, executable, or host import path;
3. exact firmware, policy, estimator, status-contract, board, core, toolchain,
   source, binary, and resource identity;
4. D14 reference authority and D8 count/control authority;
5. GNSS qualification plus bounded recoverable metadata hold;
6. D9 forwarding and D6 fail-local diagnostics;
7. the reserved D10/channel 0 external-event contract, host ingest/storage/replay,
   and zero authority, without claiming an unimplemented isolated backend;
8. controller Python/native parity and exact transaction/evidence formats;
9. singular serial ownership, bounded command waits, independent abort delivery,
   and producer-to-first-consumer identity propagation; and
10. bundle, proposal, structural preflight, run-manifest, supervisor, analyzer,
    and evidence-sealing interoperability, plus rejection of activation without
    a genuine process-level rehearsal result.

## Operational-path rehearsal

The current rehearsal producer keeps live activation fail-closed unless the
activation binds a passing result from this exact current bundle. Before bench
entry, run it with the frozen bundle and exercise the real host process topology
with deterministic and accelerated evidence. The rehearsal must cover
progressive commands and acknowledgements, repeated requests, the first
dependent decision, transport obstruction, priority abort delivery,
serial-owner handoff without an ownerless interval, clean stop, analyzer replay,
and evidence sealing. It must begin with the documented late-attachment carrier
fragment and typed raw-only boot diagnostics so the strict unknown-tag hold is
exercised at the same pre-authority boundary seen on the physical carrier.

The rehearsal report must bind the exact source, firmware/host contract, fixed
binary, bundle and proposal identities used by the prospective run. A prior
rehearsal cannot be rebound after an operationally significant identity changes.

The rehearsal exercises the production host topology and actual process, FIFO,
command, acknowledgement, abort, analyzer and sealing paths with a deterministic
serial fixture. It does not prove physical capture, firmware cross-core/device
driver propagation, electrical behavior, or plant response. Deterministic
native firmware regressions cover the cheapest available producer and
first-consumer boundaries; the remaining boundaries belong to a separately
authorized finite bench run.

## Historical evidence

Validate a historical package with the exact revision and instructions bound
by that package. Current HEAD deliberately contains no historical build or
execution surface.
