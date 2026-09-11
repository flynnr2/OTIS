# Prospective acquisition frontier

The current adaptive-hybrid manifest freezes `acquisition_frontier` before
capture. Its policy is `otis_prospective_acquisition_frontier_v1`. This contract
defines the beginning of the recorder's independently reconstructable D14/D8
evidence; it does not redefine the beginning of physical capture or reset the
instrument when a host attaches.

## Preserved evidence and deterministic selection

Every received device byte remains in raw evidence and every successfully
parsed record remains in its complete canonical CSV. A recorder attaching to
an already running producer can receive a CNT whose opening SNP predates
attachment, or an EST whose source window includes observations not retained
by this recorder. Such rows remain explicit unqualified acquisition-prefix
evidence. They cannot establish a count, estimator result, or control authority
that depends on missing observations.

Select the earliest uniquely associated retained REF/SNP opening boundary
whose adjacent same-session SNP and CNT reproduce exactly. The choice is
recorded live as `reports/acquisition_frontier_v1.json`, once. It is a choice
of evidence coverage, not a search for a healthy or favourable aperture.
Correctly recorded invalid apertures remain required evidence. The recorder
must not advance the frontier to exclude a later fault, gap, or poor result.

The artifact binds the frozen manifest, independent source identities, record
positions, immutable timestamps and their domains, and source-row hashes.
`frontier_sha256` hashes the canonical JSON artifact excluding that digest
field; `source_manifest_sha256` hashes the full canonical manifest object.
Canonical JSON uses sorted keys, compact separators and rejects nonfinite
numbers. No runtime frontier digest is inserted back into the frozen manifest.

The live state at `reports/acquisition_frontier_live_state_v1.json` reports
readiness and retained discrepancies. It is distinct from the immutable
frontier and becomes retained evidence at closure.

The capture owner's raw host marker `acquisition_frontier_established` records
the immutable digest after the source pair has been retained and before new
authority depending on it. Offline verification checks this causal record;
an artifact created only during finalization is insufficient. Source positions
refer to device records, independently of host-marker insertion and serial
read batching.

## Sequence and timing semantics

REF event emission numbers, physical D14 source ordinals, SNP snapshot ordinals,
and source record positions are distinct identities. REF event numbers must
increase without wrapping within the declared capture segment. Gaps between
REF event numbers may reflect unrelated external events and are not a D14
validity veto. SNP/source adjacency follows its own unsigned 32-bit domain.
Native timestamp rollover is reconstructed only within its declared domain;
session changes never authorize differencing across sessions.

Preserve ordered occurrences when a native low 32-bit timestamp repeats.
Neither timestamp equality alone nor equality of independent sequence counters
establishes association. Ambiguous association remains a discrepancy.

## Authority gates

Transport readiness, recording-frontier readiness and a complete estimator
source are separate facts. An evidence-independent manual SETUP needs the
recorded opening anchor and complete first aperture; it need not wait an
artificial 600 seconds solely for that manual operation. Any decision depending
on the selected estimator additionally needs all 600 of its source intervals
retained and verified after the frontier, with exact source identities and
estimator identity. An EST received recently may still depend on observations
that predate attachment.

Missing or contradictory evidence inhibits new authority and causes a
diagnostic hold. It does not authorize host abort, serial-owner teardown, loss
of the last confirmed DAC code, or reset of valid measurement history. D10
evidence remains optional and outside every frontier and steering predicate.

This contract does not add an exemption for an arbitrary malformed first line.
Its bytes and disposition remain recorded; finding a later pair cannot erase
a parser discrepancy. Existing explicitly declared boot-fragment handling
retains its own narrow semantics.

## Offline verification

The analyzer must verify the previously recorded frontier against the complete
raw/CSV evidence and the frozen policy. It cannot create or relocate the
frontier at sealing time. It reports the unqualified prefix separately, then
passes the required post-frontier records to strict raw pair reconstruction.
Every required CNT needs its actual retained opening and closing observations;
every authority-bearing EST needs its complete source window. Interior gaps,
duplicates, unknown domains and contradictory identities remain failures of
the affected replay or authority claim.

This is a prospective contract for new runs. Historical packages remain
unchanged and use their recorded revision and original acceptance rules.

A selected EST whose closing SNP identity was never retained cannot be assigned
to the unqualified prefix merely by guessing its age. If such an EST reaches
the observer after frontier establishment, the current implementation retains
a diagnostic hold. A retained closing occurrence whose 600-interval opening
precedes the anchor is explicitly unqualified; an EST that leads raw queue
drainage stays pending until its exact source arrives. No backward projection
is invented to recover a missing closing identity.
