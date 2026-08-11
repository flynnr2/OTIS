# CX319 G1 Recovery No-Write Authority

## Operator decision

On 2026-08-11 the operator explicitly authorized:

> I authorize one exact cx319_tight_lower firmware flash and one physical G1
> no-write requalification on /dev/cu.usbmodem14601 under the frozen bundle.

This is a fresh authority for requalifying the firmware scheduling repair and
does not reuse or extend the consumed original G1 bench execution.

## Bound readiness

The authority follows these passing non-physical gates:

- source revision candidate `0dac01b7541dab2eefdb10ee609cd44537bb780d`;
- firmware source SHA-256
  `c428aee5443327d27055c3fc71f37205003bdff84133ea3da9336128e94f7710`;
- lower configuration SHA-256
  `dad1114d99ef7b724778a81615a667509cebc0717dab3cddda208c017fcee568`;
- candidate lower UF2 SHA-256
  `c4bb409f8ea8831a2a4691edb7600ec3c122c3418a1ff6e3b8cbc94aa68d82d9`;
- candidate bundle SHA-256
  `677767ca1d1469efe02b6c2cdabac83247ef062686b8e7e451f6b52c8a301d2b`;
- passing structural preflight file SHA-256
  `a94cfc47c2eef365e432b524f323bfe23e433f73199604e4e6c76dd4321e2618`;
- passing operational-path rehearsal file SHA-256
  `2c69c0f72ed6db92317c39c164cd1aca37e4c218ca90d1a2bb8b43da406d2bda`;
  and
- 1,074 passing repository tests.

The final executable bundle must be regenerated from a clean descendant
revision that records this authority. Firmware source and lower configuration
must remain identical to the values above. The final clean build manifest,
UF2 and bundle identities replace the candidate artifact identities solely
because the authority/status commit changes build provenance.

## Exact physical scope

The authority permits:

- at most one exact build-manifest-bound `cx319_tight_lower` upload to
  `/dev/cu.usbmodem14601`;
- automatic reset and USB re-enumeration following that upload;
- one 2,700-second G1 no-write capture with one continuously draining owner;
- read-only queries and capture leases;
- bounded normal-path obstruction, independent priority abort and same-owner
  logical evidence rotation; and
- actual analysis, snapshot, sealing and external evidence registration.

It permits zero DAC value writes, setup stimuli, control arms and automatic
corrections. It grants no G2 retry, G3 execution or phase/hybrid actuation.

If upload, board identity confirmation or automatic re-enumeration fails, the
operation stops and requests operator assistance. There is no second flash or
improvised manual reset under this authority. The authority is consumed by the
single upload attempt or the completed G1 run, whichever boundary is reached.
