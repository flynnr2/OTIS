# Arduino Validation

Current validation targets the single fixed firmware image
`adaptive_hybrid_regulation`. Historical firmware programmes and negative
profile matrices are not part of current HEAD.

Run a no-hardware tier with:

```bash
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier fast
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier campaign
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier release
```

Each tier builds the same image through `tools/build_firmware.py`. Fast selects
the current architecture, policy, transaction, timing, channel-isolation, and
native parity checks. Campaign adds operational host-path checks. Release runs
every retained current test. `--list` prints the exact commands without running
them.

The fixed build manifest pins image identity, board, core, toolchain, source
provenance, required binary markers, and resource budgets. Build artifacts are
ignored local outputs and are not scientific evidence until bound into a
frozen run bundle.

See `END_TO_END_VALIDATION_PLAN.md` for the rehearsal and bench boundary.
