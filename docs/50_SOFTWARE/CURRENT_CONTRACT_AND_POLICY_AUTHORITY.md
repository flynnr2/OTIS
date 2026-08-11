# Current Contract and Policy Authority

## Status

Normative during platform stabilization. OTIS has no external contract
consumer and does not accept compatibility aliases as current inputs.

## Wire contracts

`host/otis_tools/contracts.py` is the single executable authority for current
CSV wire-contract names, ordered fields, record types, schema versions,
sequence semantics, domains, and row validation. Documents in
`data_contracts/` explain those contracts but do not create additional
accepted versions.

The current diagnostic contract is `diagnostics_v1`; draft v0 is unsupported.
Current H1 count observations use source domain
`h1_cx317_ocxo_10mhz`. Current count readiness uses component `count_path`.
No reader substitutes the retired H1 domain or `fc0` status aliases.

Command-bearing active status additionally obeys
`cx317_active_status_snapshot_v1`: only one complete generation may contribute
to a decision.

## Active policy

`profiles/discipline/cx317_bounded_active_v2.json` is the single current active
policy root. Its SHA-256 is the `active_policy_sha256` identity in firmware,
host supervision, manifests, status, and transaction evidence. It binds the
selected estimator, plant model, numerical preview policy, response policy,
measurement backend, and snapshot backend by exact path and SHA-256.

The component hashes remain explicit provenance; they are not independent
policy authorities. `host.otis_tools.cx317_bounded_active.load_policy` accepts
only `CX317_BOUNDED_ACTIVE_I_ONLY_V2`. Older policy files may remain as
historical evidence but are not current runtime inputs.

Stage-specific rehearsal or suspended-programme policies have no authority to
replace this root. A future policy change requires a new identified root,
updated firmware constants, host bindings, manifests, and parity tests in one
change.
