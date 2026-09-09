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

Current HEAD does not yet provide this rehearsal producer and therefore keeps
live activation fail-closed. Before bench entry, use the exact frozen current
bundle and exercise the real host process topology with deterministic or
accelerated evidence. Rehearsal
must cover progressive commands and acknowledgements, the first dependent
decision, transport obstruction, priority abort delivery, serial-owner
handoff, clean stop, analyzer replay, and evidence sealing.

The rehearsal does not prove physical capture, cross-core electrical behavior,
or plant response. Those remaining boundaries belong to a separately
authorized finite bench run.

## Historical evidence

Validate a historical package with the exact revision and instructions bound
by that package. Current HEAD deliberately contains no historical build or
execution surface.
