# Startup census escape, 12 September 2026

The inhibited zero-write physical attempt at `539ff6a` flashed successfully,
then entered a host review hold before startup authority, SETUP or ARM. The
host selected complete ACTIVE generation 1, nonce 1312243200, before the first
PPS diagnostic block. The identity predicate also required those diagnostics
and reference tracking, so it froze a legitimate startup observation as an
incoherent census. This is a platform escape into physical entry, not evidence
of a D14/D8 failure or a rejected controller.

The diagnostic archive `startup-census-hold-539ff6a-20260912T074349Z.tar.gz`
was independently verified locally: 1,827,917 bytes, SHA-256
`e04bdb3d5bf6db1d87289a517b62a34b374a92383172982f8d91408f808e8ae6`.
All 18 manifest payload entries match their sizes and hashes; the manifest is
the nineteenth file, SHA-256
`1872a95667700308d2e52be98ca908183f7b7b742ff93a06c0eeb6e12f051880`.
It is a separately sampled diagnostic snapshot of an active acquisition,
not a seal or qualification result.

The first ACTIVE snapshot occupies health bytes 34980–40458, before any PPS
block. The first complete PPS diagnostic block subsequently reports accepted
ordinal/epoch/session 1/1/1, as does ACTIVE generation 2. The original census
had ACTIVE 0/1/1 and no PPS tuple: missing information, not numeric
contradiction. At export the reported capture parser/reconnect/rejection and
capture-drop counters were zero. The startup physical-aperture-incomplete
count of one remains evidence; this repair neither deletes nor reinterprets it.

The repair separates instrument identity from reference qualification. Census
uses the complete solicited ACTIVE identity, policy, session and controller
state. Reference and retained-source gates remain explicit at control,
qualification and terminal admission. No additional timer, startup sleep,
census retry or retained-supervisor adoption path is introduced.

The same predicate also compared independently emitted accepted ordinals for
exact equality. That comparison has no simultaneous producer guarantee and
is removed. Both views must qualify independently and agree on session and
policy. Before an origin is frozen, differing acquisition epochs defer origin
admission; after qualification, each view is checked against the retained
epoch. Raw observations and the uninterrupted qualification criterion remain
unchanged.

The escaped ordering is covered by a small byte-exact retained-health fixture
through the actual live reducer and first census/qualification consumers. The
process rehearsal also emits its first ACTIVE response without PPS diagnostics,
then supplies them in later observations. Separate cases retain identity and
session rejection, missing-reference control inhibition, acquisition handling
and independently advancing ordinals.

The running bench instance is unchanged. Its immutable rejected census cannot
be retroactively admitted by this repair. Capture remains the responsibility
of the bench instance; closing it requires explicit operator direction. Any
subsequent physical attempt needs the corrected frozen host bundle and its
rehearsal, with the original hold retained separately.

Development verification: 729 selected tests passed, including the real
activation/manifest preparation roundtrip; the captured replay's three cases
also passed after the final additions. The normal process rehearsal passed
through two progressive transactions, obstruction, priority abort, analysis,
sealing and recovered registration. Delayed-command and exact committed-image
rehearsal results are retained with the delivery, rather than inferred from
these fixture results. Firmware source, configuration and toolchain inputs are
unchanged; the current build contract nevertheless binds the corrected host
revision into new binary provenance.
