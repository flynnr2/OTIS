# Activation preparation escape, 12 September 2026

The bench Mac verified the delivered `8c3b78a` candidate and its byte-identical
firmware reproduction, then attempted the authorized `inhibited_zero_write`
entry. `create_activation` raised `NameError: name 'inputs' is not defined` in
`_activation_unsigned`. No activation, reservation, flash, reset, physical
serial acquisition or campaign package was created. This is a host preparation
defect that escaped development verification, not a physical acquisition or
scientific failure.

The operator supplied the original invocation/log identity, SHA-256
`542ac98a711ceeff1680f96e27ea15b2466ec6763ad9a96b6743188fd00d2091`.
That log has not been independently read here; the source defect is directly
reproducible without it. Preserve the original bench log and earlier successful
rehearsal evidence unchanged.

The activation projection referenced a validated input object that it never
created. It now validates the authoritative inputs embedded in the frozen
bundle before deriving the reference-acceptance binding, as the run-manifest
producer already does. It does not infer policy from a mutable live profile or
change either physical purpose's authority.

The verification gap was broader than that missing initialization: the real
rehearsal report was validated, but activation creation and its subsequent
physical-manifest preparation were not exercised together. Verification now
executes those public functions for both supported purposes, through their
downstream consumer, without opening hardware. A narrow standard Ruff check
also rejects undefined names across current host tools and validation scripts;
it detects the original `inputs` defect even without reaching that branch.
The check is part of fast verification and the normal test suite; activation
preparation is part of campaign/release verification. Ruff is a development
dependency, not an instrument runtime dependency.

Publication binds a corrected committed host candidate, exact fixed image,
fresh operational rehearsal and explicit activation/manifest roundtrips. The
current firmware reproduction contract requires matching source revision, so
the rebuilt image receives new provenance even though firmware source and
configuration inputs are unchanged. Test activations are not bench authority
and are not delivered for physical use; the bench creates its own activation
under the existing operator-selected purpose.

The separately reported stale or missing historical index locations are not
causal to this NameError. They are not deleted or rewritten as part of this
repair. Existing structural index and exact new-package validation remain in
force. No physical attempt was consumed; the next action remains the authorized
two-hour inhibited/no-write entry with corrected frozen inputs.

Verification before publication: 726 selected release tests passed; the focused
end-to-end preparation regression passed in 84.66 seconds. It uses one genuine
PTY rehearsal for both purposes, doubles only the firmware build validation,
and executes the real activation, manifest, generic loader and runtime-context
functions. The production-image gate separately exercises those functions with
the exact fixed build and independent reproduction; its identities and outcome
belong to the publication record rather than a fixture claim.
