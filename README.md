# TUDa-IASS Aerosol Sampler Control

TUDa-IASS Aerosol Sampler Control is the hardware-control software for the Technical University of Darmstadt Integrated Aerosol Sampling System. It provides a desktop graphical interface and Raspberry Pi server programs for three aerosol samplers:

- NanoPS
- MultiMINI8
- SPAFiS

The operator computer discovers the Raspberry Pis on a local network, sends sampler commands, and displays pump, valve, heater, sample-position, and elapsed-time status.

> **Hardware safety:** This research software directly controls pumps, valves, and heaters. Verify the GPIO assignments, electrical protections, network configuration, and safe shutdown behaviour on the intended hardware before operation. Use it only on a supervised, trusted local network.

## Releases

- `v0.1.0` is the current production release.

## Repository layout

```text
.
├── config/
│   └── config.example.yaml
├── docs/
│   ├── known_limitations.md
│   └── operating_manual.md
├── src/tuda_iass_control/
│   ├── control.py
│   ├── logger.py
│   ├── miniserver.py
│   ├── nanoserver.py
│   ├── spafisserver.py
│   ├── ssh_launcher.py
│   ├── tpcomm.py
│   └── tphardware.py
├── tests/
│   └── test_regressions.py
├── CITATION.cff
├── LICENSE
├── requirements.txt
└── requirements-rpi.txt
```

## Requirements

The operator computer requires:

- Python 3
- Tkinter
- Paramiko
- PyYAML

Each Raspberry Pi additionally requires the GPIO, MAX31865, and SPI packages listed in `requirements-rpi.txt`.

Install the operator-computer dependencies in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On each Raspberry Pi, install the hardware dependencies:

```bash
python3 -m pip install -r requirements-rpi.txt
```

Tkinter is normally supplied by the operating system rather than `pip`. For example, Debian and Raspberry Pi OS provide it through the `python3-tk` package.

## SSH launcher configuration

The operator computer and Raspberry Pis must share a supervised local network. The launcher also requires SSH access to each Raspberry Pi and independently verified host keys.

Create a private local configuration file:

```bash
cp config/config.example.yaml config/config.yaml
```

Edit `config/config.yaml` with the real Raspberry Pi addresses, usernames, and remote script paths. The private file is ignored by Git. Do not commit passwords, private keys, or operational network details.

The launcher accepts an SSH key, a password stored in a named environment variable, or a password entered in the graphical prompt. Unknown or changed SSH host keys are rejected. Verify each Raspberry Pi fingerprint before adding it to `known_hosts`.

Start or stop the configured Raspberry Pi server programs with:

```bash
python src/tuda_iass_control/ssh_launcher.py
```

## Running the samplers

On the matching Raspberry Pi, run one server from the directory containing all eight source files:

```bash
cd src/tuda_iass_control
python nanoserver.py
# or: python miniserver.py
# or: python spafisserver.py
```

On the operator computer, start the control interface:

```bash
python src/tuda_iass_control/control.py
```

## SPAFiS pressure logging and recovery

During an active SPAFiS sample, the server reads one four-byte pressure frame over SPI each second and writes the value, raw sensor count, sample position, and elapsed time to `spafis.log`. Pressure is not included in UDP status packets. A sensor status error stops the active sequence and the cleanup code switches the pump and selected valve off.

The release is configured for the installed Honeywell `SSCDRRD010MDSA3` sensor: differential SPI output, a -10 to +10 mbar span, and calibrated logging in Pa (-1000 to +1000 Pa). Each log entry also retains the raw sensor count for diagnostics. The SPI bus, chip-select, frame format, output-count limits, and pressure span are defined in `tphardware.py` as `pressure_config_spafis`. If the installed sensor is changed, update that configuration from its datasheet and repeat the hardware verification before use.

SPAFiS writes its state before activating the valve and pump, replaces the state file atomically, and saves the completed position after cleanup. After a restart, **Start** selects the next unused position from that saved state. Do not use **Reset** when recovering an interrupted run.

The default UDP discovery port is `55120`. Discovery uses the IPv4 limited-broadcast address; see [known limitations](docs/known_limitations.md) before using a multi-interface host or a network with restricted broadcast routing.

## Operational notes

- Use **Stop** and confirm that the sampler is idle before using **Reset**.
- In NanoPS, the selected heater is enabled after the bypass and purge phases, preheats for 20 seconds, and remains fully enabled during sampling until **Stop** is processed.
- The production release does not implement closed-loop or PI temperature regulation.
- Runtime logs and state files are intentionally excluded from version control.

See the [operating manual](docs/operating_manual.md) for the normal startup and shutdown sequence.

## Validation

Run the focused regression suite from the repository root:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

The suite contains 17 regression tests. It uses mocks and does not energize GPIO outputs. See [VALIDATION.md](VALIDATION.md) for scope and limitations.

## Citation and authors

The software authors are:

- Sadath Ismayil
- Konrad Kandler

Citation metadata are provided in [`CITATION.cff`](CITATION.cff). GitHub will display a **Cite this repository** option after the file is committed to the default branch.

## Licence

This software is distributed under the GNU General Public License v3.0 only (`GPL-3.0-only`). See [`LICENSE`](LICENSE).
