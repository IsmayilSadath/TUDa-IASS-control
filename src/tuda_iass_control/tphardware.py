#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GPIO, temperature, and pressure interfaces for the Raspberry Pi samplers."""

import math
import time
import board
import atexit
import RPi.GPIO as GPIO
import threading
import digitalio
from adafruit_max31865 import MAX31865

atexit.register(GPIO.cleanup)
GPIO.setmode(GPIO.BCM)

pump_config_nanops = {0: 1, 1: 0, 2: 25, 3: 24, 4: 23, 5: 22, 6: 27}
# pumps 0-5: samples, pump 6: bypass
heater_config_nano = {0:2, 1:3, 2:14, 3:21, 4:17, 5:18}

pump_config_mini = {0: 17, 1: 18, 2: 27, 3: 22, 4: 23, 5: 24, 6: 25, 7: 5, 8: 6, 9: 21}
pump_config_spafis = {0: 19, 1: 17, 2: 18, 3: 27, 4: 22, 5: 23, 6: 24}

# Honeywell SSCDRRD010MDSA3: differential, SPI, ±10 mbar (±1000 Pa).
# Honeywell's digital transfer function uses 10% and 90% of the 14-bit
# output-count range for the calibrated pressure limits.
pressure_config_spafis = {
    'bus': 0,
    'device': 0,
    'mode': 0,
    'max_speed_hz': 100000,
    'frame_length': 4,
    'output_min': 1638,
    'output_max': 14746,
    'pressure_min': -1000.0,
    'pressure_max': 1000.0,
    'unit': 'Pa',
}

class pump_controller():
    def __init__(self, pump_config, pump_limit=2, logfunc=None):
        self.log = logfunc if logfunc else self.dummy
        self.pump_config = pump_config
        self.pump_limit = pump_limit
        self.lock = threading.Lock()
        for pump in self.pump_config:
            GPIO.setup(self.pump_config[pump], GPIO.OUT, initial=GPIO.LOW)
        self.pump_status = [0 for _ in self.pump_config]

    def switch(self, pno=-1, on=False):
        with self.lock:
            if on in [1, True]:
                if sum(self.pump_status) < self.pump_limit:
                    try:
                        GPIO.output(self.pump_config[pno], GPIO.HIGH)
                        self.pump_status[pno] = 1
                        self.log(f'[Pump control] INFO: switch on pump {pno}')
                    except Exception as e:
                        self.log(f'[Pump control] ERROR: Exception {e} at pump {pno}')
                        return 3  # could not set pump 'on'
                else:
                    self.log(f'[Pump control] ERROR: Too many pumps already running')
                    return 2  # too many pumps running
            elif on in [0, False]:
                if pno < 0:
                    try:
                        for pump in self.pump_config:
                            GPIO.output(self.pump_config[pump], GPIO.LOW)
                            self.pump_status[pump] = 0
                            self.log(f'[Pump control] INFO: switch off pump {pump}')
                    except Exception as e:
                        self.log(f'[Pump control] ERROR: Exception {e} at pump {pump}')
                        return 5  # could not switch all pumps 'off'
                else:
                    try:
                        GPIO.output(self.pump_config[pno], GPIO.LOW)
                        self.pump_status[pno] = 0
                    except Exception as e:
                        self.log(f'[Pump control] ERROR: Exception {e} at pump {pno}')
                        return 4  # could not set pump 'off'
            else:
                self.log(f'[Pump control] ERROR: Invalid state supplied: {on}')
                return 1  # invalid state supplied
            return 0  # all ok

    def dummy(self, *args):
        pass


class spafis_pressure_reader():
    """Read and convert a four-byte digital pressure frame over SPI."""

    def __init__(self, config=None, logfunc=None, spi=None):
        self.log = logfunc if logfunc else self.dummy
        self.config = dict(config or pressure_config_spafis)
        self.spi = spi
        self.owns_spi = False
        self.last_raw_counts = None
        self.frame_length = int(self.config.get('frame_length', 4))
        if self.frame_length < 2:
            raise ValueError('pressure frame must contain at least two bytes')

        self.output_min = int(self.config.get('output_min', 1638))
        self.output_max = int(self.config.get('output_max', 14745))
        if self.output_max <= self.output_min:
            raise ValueError('pressure output maximum must exceed its minimum')

        self.pressure_min = self.config.get('pressure_min')
        self.pressure_max = self.config.get('pressure_max')
        if (self.pressure_min is None) != (self.pressure_max is None):
            raise ValueError('pressure minimum and maximum must be set together')
        if self.pressure_min is not None:
            self.pressure_min = float(self.pressure_min)
            self.pressure_max = float(self.pressure_max)
            if not all(math.isfinite(value) for value in (self.pressure_min, self.pressure_max)):
                raise ValueError('pressure calibration values must be finite')
            if self.pressure_max <= self.pressure_min:
                raise ValueError('pressure maximum must exceed its minimum')
            self.unit = str(self.config.get('unit', 'pressure_units'))
        else:
            self.unit = 'raw_counts'

    def _open(self):
        if self.spi is not None:
            return

        try:
            import spidev
        except ImportError as exc:
            raise RuntimeError('spidev is required for SPAFiS pressure logging') from exc

        self.spi = spidev.SpiDev()
        try:
            self.spi.open(
                int(self.config.get('bus', 0)),
                int(self.config.get('device', 0)),
            )
            self.spi.mode = int(self.config.get('mode', 0))
            self.spi.max_speed_hz = int(self.config.get('max_speed_hz', 100000))
            self.owns_spi = True
        except Exception:
            self.spi.close()
            self.spi = None
            raise

    def read(self):
        self._open()
        frame = self.spi.xfer2([0] * self.frame_length)
        if len(frame) != self.frame_length:
            raise IOError(
                f'pressure sensor returned {len(frame)} bytes; '
                f'expected {self.frame_length}'
            )

        first_byte = int(frame[0])
        status = (first_byte >> 6) & 0x03
        if status != 0:
            raise IOError(f'pressure sensor reported status {status}')

        raw_counts = ((first_byte & 0x3F) << 8) | int(frame[1])
        self.last_raw_counts = raw_counts
        if self.pressure_min is None:
            return float(raw_counts)

        fraction = (raw_counts - self.output_min) / (self.output_max - self.output_min)
        return self.pressure_min + fraction * (self.pressure_max - self.pressure_min)

    def close(self):
        if self.spi is not None and self.owns_spi:
            self.spi.close()
        self.spi = None
        self.owns_spi = False

    def dummy(self, *args):
        pass


class temperature_reader():
    def __init__(self, temp_config={0:5, 1:6, 2:12, 3:13, 4:19, 5:16, 6:26, 7:20}, logfunc=None, interval=1):
        self.log = logfunc if logfunc else self.dummy
        self.temp_config = temp_config
        self.spi = board.SPI()
        self.sensor = []
        self.temperature = []
        self.read_interval = interval
        self.stop_temp = False
        self.lock = threading.Lock()
        for temp in self.temp_config:
            self.sensor.append(MAX31865(self.spi,
                                        digitalio.DigitalInOut(getattr(board, f"D{self.temp_config[temp]}")),
                                        wires=4))
            self.temperature.append(float('NaN'))  # initialize temperatures as NaN
        threading.Thread(target=self.temp_reader, daemon=True).start()  # have temperature reader run in background

    def temp_reader(self):
        while not self.stop_temp:
            ts = []
            for temp in self.temp_config:
                ts.append(self.sensor[temp].temperature)
            with self.lock:
                self.temperature = ts
            self.log(', '.join(map(str, self.temperature)))
            time.sleep(self.read_interval)

    def stop(self):
        self.stop_temp = True

    def read(self, tno=-1):
        with self.lock:
            if tno >= 0:
                try:
                    return self.temperature[tno]  # return single temperature
                except:
                    return float('NaN')  # return NaN if something went wrong
            else:
                return self.temperature  # return list of all temperatures

    def dummy(self, *args):
        pass
