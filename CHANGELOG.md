# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-09-02

Initial production release.

- Includes production code for NanoPS, MultiMINI8, and SPAFiS.
- Replaces unsafe state and command parsing with validated numeric parsing.
- Adds input validation, TCP command framing, socket-timeout restoration, and incomplete-status handling.
- Queues GUI status updates on the Tkinter main thread.
- Adds command-send and sampling locks plus cleanup paths for interrupted operations.
- Uses verified SSH host keys, shell-quoted remote paths, and private external configuration.
- Includes the NanoPS GPIO pin configuration tested on the Raspberry Pi hardware.
- Adds SPAFiS SPI pressure logging with sensor-status validation and local recovery state.
- Configures SPAFiS pressure conversion for the Honeywell SSCDRRD010MDSA3 sensor (-10 to +10 mbar, or -1000 to +1000 Pa) while retaining raw SPI counts in the local log.
- Adds 17 regression tests.
