# Anomalies

- First PPS interval after startup is approximately 32M `rp2040_timer0` ticks.
  Subsequent PPS intervals are approximately 16M ticks, so this is treated as a
  startup/capture artifact rather than a persistent reference failure.
- Frequency characterization is limited by the current short FC0 gate window.
  This run verifies observe/DAC health, not ppm/V sensitivity.
