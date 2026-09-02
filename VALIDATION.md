# Validation

## Production source

The source in `src/tuda_iass_control/` is the production code for the release. The NanoPS temperature-sensor GPIO configuration in `tphardware.py` matches the Raspberry Pi-tested wiring, and the physical evidence summarized in the manuscript is kept separate from the mocked regression checks below.

## Automated checks

The repository includes 17 regression tests covering:

- absence of `eval()` in production Python files
- safe state-file and manual-sample parsing
- newline-delimited TCP command framing
- command-send locking and socket-timeout restoration
- incomplete status-packet handling
- initial state-file persistence and state loading without deleting a valid file
- atomic SPAFiS state replacement and preservation of the completed position
- SPAFiS pressure-frame decoding and sensor-status rejection
- Tkinter main-thread status queuing
- MultiMINI8 bypass status reporting
- rejection of concurrent sampling requests
- NanoPS cleanup after a preheat interruption
- SPAFiS pump and valve cleanup after stop
- SPAFiS pressure logging during sampling
- pressure-read failure cleanup without consuming a sample
- strict SSH host-key verification

Run them with:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

The tests use mocks and do not import or energize Raspberry Pi GPIO hardware.

## Scope

These checks support software reproducibility and regression detection. They do not replace hardware-specific verification of wiring, pin assignments, SPI frame configuration, pressure calibration, heater limits, flow paths, electrical interlocks, or emergency shutdown.
