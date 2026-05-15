# Anomalies

- First PPS interval after startup is approximately 32M `rp2040_timer0` ticks.
  Subsequent PPS intervals are approximately 16M ticks, so this is treated as a
  startup/capture artifact rather than a persistent reference failure.
- The connected CX317 control input tracked the DAC voltage commands, but the
  expected tuning shift over the conservative sweep window is below what the
  current short FC0 gate can resolve confidently.
- Do not claim ppm/V or settling-time readiness from this run alone.
