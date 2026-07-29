# run_020 Notes

Run 019 established a monotonic broad response with R² 0.999920 and placed
the 10 MHz crossing near `0xAE00`, but its intended local pass ran around
`0x8000` because the Arduino IDE build used the prior header defaults.

Run 020 is deliberately focused on the missing evidence. All firmware
configuration is held directly in `otis_config.h`; no command-line compilation
or `-D` override is part of this run. A fail-closed preflight uses `CONFIG?`
and non-actuating `profile_step` telemetry to prove the uploaded configuration
and exact nine-step profile before starting it.
