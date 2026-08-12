# Firmware Validation

Current validation targets `CX319_EVIDENCE_EPOCH_1` only. The firmware matrix
contains `cx319_tight_lower`, `cx319_tight_upper`, and five current
expected-failure guards. Historical H0/SW1, Phase 4/5, CX317, and CX318 profiles
and golden-wire workflows are not executable from current HEAD.

```bash
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier fast
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier campaign
.venv/bin/python firmware/arduino/validation/scripts/run_no_hardware_checks.py --tier release
```

`fast` builds the lower profile; `campaign` builds both current profiles;
`release` builds both and proves all five expected-failure guards. These are
offline checks and perform no serial access or flashing.

For a historical reproduction, check out the exact source revision recorded by
the package or reviewed report and run that revision's validation instructions.
