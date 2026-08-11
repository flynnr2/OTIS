# CX319 G2 v6 Live Authority

## Operator decision

On 2026-08-11 the operator explicitly authorized the exact CX319 G2 v6
recovery package and confirmed physical presence at the bench.

This authority is bound to:

- proposal bundle
  `8726590f586a3c1ff97adbaa02aa3d216e89cad61d155489e1988d07860e7df5`;
- accelerated operational-rehearsal content
  `558314ac16ee9d12a97c7d557e71e5c4a8401cabafeb30206710f111adfa6c54`;
- operational-rehearsal seal
  `e11e77d788407c873844ac236260921a335da11f4498839074f7f62b4efad25b`;
- recovery readiness record
  `docs/60_EXPERIMENTS/CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/07_G2_RECOVERY_OFFLINE_READINESS.md`
  at SHA-256
  `f43d17a3781d25531bc90237640f8731e956c638946b231ee0eed34a2f4c6572`;
- the unchanged G1-qualified firmware identity; and
- the exact expected board and device identity recorded by the new activation.

## Permitted operation

The authority permits:

1. one ordinary board restart, with no firmware flash;
2. immediate continuously drained capture;
3. pre-write proof of firmware uptime no greater than 120 seconds and every
   bound identity, queue, partition, telemetry and zero-write invariant;
4. one exact `DAC SET 0xA808` setup transaction only after that proof passes;
5. positive automatic corrections only, with at most four corrections, 21
   codes per correction and 84 codes cumulative; and
6. the frozen supervisor, analyzer, seal and evidence-registration path.

The prior cadence, settling, fresh-support, qualification, finite-duration,
range, one-request, no-retry, no-restore and phase/hybrid-zero-authority limits
remain exact. Any mismatch stops fail-static at the last confirmed code.

The retired v5 activation is not reusable. A failed or bounded-nonpass v6 run
does not authorize a retry. G3 remains conditional on a passing G2 v6 seal and
a fresh upper-side bundle and rehearsal. No G4 or phase/hybrid actuation is
authorized.
