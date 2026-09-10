# OTIS firmware/host contract v1

`otis_firmware_host_contract_v1.json` is the current machine-readable authority
for the serial boundary between the fixed `adaptive_hybrid_regulation` firmware
and the current host. It is exact-current-only; it is not a compatibility
reader for historical firmware.

## What it controls

The contract declares:

- the carrier framing and mismatch disposition;
- every current record tag, schema version, ordered field layout, sequence,
  timestamp, domain and session field, and first host consumer;
- every record field's canonical wire encoding, storage width, signedness,
  legal range, optionality, enum or fixed-format constraint;
- every current command form, argument representation and range,
  acknowledgement, and first firmware consumer;
- the atomic ACTIVE status vocabulary, envelope and value encodings;
- evidence, status, boot and concurrent-telemetry frontiers; and
- decision-bearing relations that cannot be validated from one field alone,
  including exact-tick projection, wrapped timestamp suffixes, causal identity
  and stateful response classification.

The individual `*.csv.md` files remain the human-readable definitions of field
meaning, units and detailed validity. The explicit semantic validators in
`host/otis_tools/contracts.py` remain production code, but their record tags,
versions, layouts, sequence fields, timestamp/domain fields and session fields
are checked at import against this authority. Both live record splitting and
offline CSV validation apply the contract-derived wire checks before a current
row can become interpreted evidence.

## Generated firmware projection

Run:

```sh
python tools/generate_firmware_host_contract.py
```

This deterministically produces
`firmware/arduino/otis_nano_rp2040_connect/otis_firmware_host_contract.generated.h`.
The fixed build refuses a stale generated header. Firmware formatters consume
the generated record headers; command parsing and queue-frontier assertions
consume generated prefixes, argument counts and capacities.

Use the non-writing check in preflight and continuous integration:

```sh
python tools/generate_firmware_host_contract.py --check
```

Never edit the generated header directly.

## Runtime binding

The fixed build manifest binds the JSON file. Its canonical SHA-256 digest and
contract ID are embedded in the binary and emitted in the `health_v1` stream as
`protocol.contract_id` and `protocol.contract_sha256`. They are emitted at boot
and in the first provenance-bearing `CONFIG?` response so attachment after the
boot banner is covered.

The host requires both values to match its local current contract before any
setup or arm authority is granted. A missing or different identity is not
translated and is not treated as an older compatible version.

## Mismatch handling

An unknown record tag, wrong version, wrong column count, mismatched header,
non-canonical or out-of-range field value, invalid ACTIVE generation, or failed
declared relation is a protocol discrepancy. The host must:

1. preserve the raw bytes and parsed attempt;
2. keep the sole capture owner and canonical acquisition running;
3. retain the last confirmed DAC code;
4. grant no new `ACTIVE SETUP` or `ACTIVE ARM` authority; and
5. surface a review-required diagnostic hold.

A host discrepancy has no automatic abort or teardown authority. Firmware's
independent bounded fail-static behavior and an explicit operator abort remain
separate.

## Required verification

The contract check is necessary but not sufficient. Current release evidence
must also compile the actual production firmware emitters, parsers and state
machines and compare them with production host behavior. The contract-derived
matrix exercises legal and illegal encodings for all 418 fields in all 16
current record contracts. Native producer checks pass representative minimum
and maximum values through the production raw emitters and pass derived records
through their production formatters. The current parity regressions also cover
legal and illegal command boundaries, ACTIVE status values and completeness,
contract identity admission, exact timestamp projection and wrapping, and the
stateful response-classifier cases that caused the 2026-09-09 retained-evidence
replay discrepancy.

The earlier 2026-09-10 baseline Release tier passed all 427 tests, including the
full current-process rehearsal, and its subsequent fixed-image build and
binary/resource audit passed. A changed contract digest or implementation
requires a fresh exact Release, build, bundle freeze and rehearsal before bench
entry; the earlier evidence is not rebound to changed bytes.

The complete Stage 0 claim additionally requires the fixed firmware build and
the genuine process/FIFO/command/acknowledgement/abort/analyzer/sealing
rehearsal. Native fixtures do not establish the physical serial, cross-core or
device-driver boundaries.
