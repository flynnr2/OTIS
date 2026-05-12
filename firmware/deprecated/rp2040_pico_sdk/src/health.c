/*
 * Health/status ownership boundary for SW1.
 *
 * Emit explicit STS records for boot, buffer pressure, dropped records,
 * reference validity, and transport gaps. Prefer explicit flags over silent
 * assumptions in downstream analysis.
 */
