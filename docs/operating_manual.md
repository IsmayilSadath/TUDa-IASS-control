# Operating Manual

This document gives the basic sequence for trained operators. Local laboratory safety procedures and instrument-specific checks take precedence.

## Before startup

1. Confirm the Raspberry Pi, pump, valve, heater, and sensor wiring against the intended GPIO map in `tphardware.py`.
2. Confirm that the operator computer and Raspberry Pis are on the supervised instrument network.
3. Verify that the UDP discovery address and port match that network.
4. Confirm that all pumps, valves, and heaters are physically off before starting the server programs.
5. Confirm that each Raspberry Pi SSH host key has been independently verified.
6. On the SPAFiS Raspberry Pi, verify the SPI bus, chip-select, and the `SSCDRRD010MDSA3` pressure calibration settings in `tphardware.py`.

## Startup

1. Power the Raspberry Pis and instrument hardware according to the laboratory procedure.
2. Start the instrument-specific server on each Raspberry Pi, either locally or through `ssh_launcher.py`.
3. Start `control.py` on the operator computer.
4. Wait until each required instrument is connected and shown as ready.
5. Check the displayed pump, valve, heater, bypass/common-pump, and sample states before starting a sample.

## Sampling

1. Select **Start** for the intended instrument. The software advances to the next unused sample position.
2. Observe the preparation and active indicators.
3. Use **Stop** to finish or abort sampling.
4. Confirm that the active sample clears and that controlled outputs return to the expected off state.

NanoPS performs a 5-second bypass phase, a 3-second purge phase, and a 20-second heater preheat before sampling. The selected heater remains fully enabled during the sampling phase and is switched off during cleanup after **Stop**.

MultiMINI8 performs a 15-second flush before sampling. SPAFiS opens the selected valve and starts its pump without a timed preparation phase.

While SPAFiS is sampling, check `spafis.log` for entries containing the sample position, elapsed time, calibrated pressure in Pa, and raw sensor count. Pressure is recorded locally and is not sent in the GUI status packet. If the pressure reader reports an error, the active sample is stopped and the pump and valve are switched off; resolve the sensor or SPI problem before retrying.

If the SPAFiS server or Raspberry Pi restarts, leave the state file in place and select **Start** only after the hardware has been checked. The saved progress is used to select the next unused position. The state file is replaced atomically during operation and after cleanup.

## Reset

Do not use **Reset** while preparation or sampling is active. First select **Stop**, wait for the sampler to report an idle state, and verify that physical outputs are off. Reset clears recorded sample progress and removes the current state file.

## Shutdown

1. Stop every active sample and confirm idle status.
2. Close the operator interface.
3. Stop the Raspberry Pi server programs.
4. Verify physically that pumps, valves, and heaters are off.
5. Archive operational logs separately if required; do not commit logs or state files to GitHub.
