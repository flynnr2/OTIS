/*
 * Capture ownership boundary for SW1.
 *
 * Keep ISR/PIO capture code here, isolated from CSV emission and host-facing
 * semantics. Firmware should timestamp facts; profiles and interpretation stay
 * host-side unless a later stage explicitly moves them into firmware.
 */
