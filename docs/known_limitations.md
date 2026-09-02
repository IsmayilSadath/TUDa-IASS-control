# Known Limitations

- The production network protocol is intended for an isolated, trusted local network. Sampler TCP commands and UDP status messages are not authenticated or encrypted.
- The server sockets listen on all local interfaces.
- Discovery announcements use the IPv4 limited-broadcast address `255.255.255.255`; deployments with multiple interfaces or restricted broadcast routing may require a deployment-specific change and renewed network testing.
- GPIO assignments are fixed in `tphardware.py` and are specific to the tested instrument wiring.
- Reset is available from the graphical interface during preparation and sampling. Operators must select **Stop**, confirm idle status, and verify outputs before reset.
- SPAFiS state is saved with a temporary-file replacement. NanoPS and MultiMINI8 state files remain in-place updates and should be backed up with the instrument logs.
- SPAFiS pressure conversion is configured for the installed Honeywell `SSCDRRD010MDSA3` sensor (-10 to +10 mbar, or -1000 to +1000 Pa). If the sensor or pressure range changes, update `tphardware.py` and repeat hardware verification; the regression suite cannot establish sensor calibration.
- The pressure reader expects a four-byte SPI frame with a two-bit status field and a 14-bit measurement field. Confirm that this frame matches the installed sensor before operation.
- NanoPS uses a 20-second preheat and then keeps the selected heater fully enabled while sampling. Production code does not implement closed-loop or PI temperature control.
- The automated regression suite uses mocks and cannot validate electrical behaviour, component limits, sensor accuracy, sampling flow, or physical fail-safe mechanisms.
