# Evidence and provenance engineering note

The immutable `run_spec.json` binds firmware, host tools, scientific contracts,
policy and campaign limits. The small `run_manifest.json` binds that exact
retained specification to one acquisition. Neither file is a scientific verdict.
The raw stream preserves the device's build and session declarations; analysis
checks their relationship to the declared experiment.

## Firmware identity

The fixed builder remains `tools/build_firmware.py`. Provenance version 2 binds
only inputs that can affect firmware bytes: firmware sources, configuration,
build definitions and provenance-generation code, together with the pinned
compiler and functional installed toolchain. The firmware audit revision is the
latest revision touching those inputs. Repository-wide revision and working-tree
state are separate context, not the binary identity. Uncommitted firmware inputs
remain a build error. A host-only or documentation commit does not require a new
firmware image.

The wire macro `OTIS_BUILD_GIT_COMMIT` carries that firmware audit revision;
`OTIS_BUILD_AUTHORITATIVE_INPUT_SET_SHA256` carries the firmware input-set hash.
These existing wire names do not mean that every host file is a firmware input.
The host toolset has its own exact content identity in the run specification.

The builder hashes installed functional code and tools, excluding package-manager
metadata, Finder metadata and generated Python caches. It compiles with a
session-bound generated header, verifies the resulting binary and resource use,
and checks inputs again after compilation. Independent reproduction retains the
recorded build session and verifies identical bytes. It is an explicit release
check, not a compiler invoked during ordinary acquisition.

A delivered build can live at a different absolute path. Physical entry validates
its actual files against the frozen semantic artifact identity and uploads the
validated delivered UF2. Recorded historical paths remain provenance strings;
they do not direct offline readers to another machine's filesystem.

## Closed evidence

`evidence_package_v1.json` inventories the package's regular files by relative
path, size and SHA-256. It binds the retained spec and run record. The closure
record must identify those exact manifest bytes and confirm that capture closed
and serial is no longer open before capture is classified as complete. A missing
closure is partial evidence, not an inferred success. Active capture cannot be
sealed.

Analysis and scientific outcome remain separate from byte integrity. A failed
analyzer produces a retained diagnostic; packaging may preserve that evidence
without calling the experiment a pass. Once sealed, subsequent analysis writes
outside the source package and records its source content identity. A location
registry is optional and cannot alter either result.

Digests establish integrity relative to a trusted copy, not authorship. Package
validation rejects changed or uncovered files, symbolic links, unsafe paths and
unknown special files. Declared inert runtime FIFOs are explicitly recorded as
omitted; transfer never recreates command endpoints. Historical package formats
use the reader at their recorded revision, without compatibility machinery in
the current acquisition path.

## Storage and promotion

Raw acquisitions and generated packages remain outside Git. `.gitignore` is the
storage boundary; do not force-add evidence. Keep the bench original and verify
transferred bytes against the sender's digest before independent analysis.

For a closed run, `python -m host.otis_tools package RUN_DIR` performs analysis
and sealing. `python -m host.otis_tools verify RUN_DIR` checks the resulting
package. A later analysis uses `analyse RUN_DIR --output EXTERNAL_REPORT`.
Promote only reviewed compact results, contracts, plant models or deliberately
small fixtures to tracked paths. Sealing alone establishes no calibration,
reference-quality or control-eligibility claim.
