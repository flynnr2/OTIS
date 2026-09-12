# phase_estimator_outputs_v2.csv

`PHE` version 2 is the current phase-estimator output. It preserves the capture
session, acceptance epoch, and accepted-boundary ordinal of its exact RPH
source. `source_relative_phase_observation` retains the exact
`RPH:<phase_epoch>:<observation_sequence>` identity. PHE is derived evidence
and carries no actuation authority.

The RPH and PHE qualification fields describe different stages. The current
producer emits these exact relations:

- `epoch_open` RPH -> `initializing` PHE;
- `qualified` RPH -> `initializing` PHE until frequency support is available,
  then `qualified` PHE;
- `invalid` RPH -> `invalid` PHE.

A qualified RPH therefore proves an accepted raw phase interval; it does not by
itself claim that the 600-point phase-frequency estimate is available. Replay requires every emitted PHE to have one unique exact RPH and preserves
the source session, acceptance epoch, accepted-boundary ordinal, and raw phase
values across the pair. Duplicate RPH or PHE identities are contradictory. An
unpaired final RPH is retained and reported because capture may close after its
complete frame and before the corresponding PHE frame; it does not by itself
turn otherwise exact phase evidence into a capture failure.
