/*
 * Transport ownership boundary for SW1.
 *
 * The first implementation may write records directly to USB stdio. Once the
 * capture loop is real, this file should own buffering and back-pressure policy
 * so capture code never blocks on host I/O.
 */
