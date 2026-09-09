# Current OTIS schemas

This directory contains only schemas consumed by the current OTIS instrument.
Historical artifacts are validated from the recorded Git revision that created
them; current HEAD does not carry compatibility readers for retired campaigns.

The selected production controller is `OTIS_ADAPTIVE_HYBRID_REGULATION_V1`.
D14 is its sole reference input, D8 is its oscillator-count input, and D10 is
optional external-event evidence with no reference, health-veto, control, or
terminal authority.
