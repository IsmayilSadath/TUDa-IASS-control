#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NanoPS Raspberry Pi server."""

import time
import sys
import os
import math
import threading
from tpcomm import Controlserver, status_nanops, name_nanops
from logger import Logger
from tphardware import pump_controller, pump_config_nanops, heater_config_nano, temperature_reader

class nanocontrol():
    def __init__(self, status_def, pump_config, heater_config, statefile='nanostate.dat', logfunc=None):
        self.log = logfunc if logfunc else self.dummy
        self.status_def = status_def
        self.ready = 0
        self.bypass = 0
        self.statefile = statefile
        self.maxsample = 6
        self.active_sample = -1
        self.pump = [0 for _ in range(self.maxsample)]
        self.heater = [0 for _ in range(self.maxsample)]
        self.sampling = False
        self.sample_lock = threading.Lock()
        self.stop = False
        self.pumpcontrol = pump_controller(pump_config, logfunc=logfunc)
        self.pumpcontrol.switch()  # turn off all pumps
        self.heatercontrol = pump_controller(heater_config, logfunc=logfunc)
        self.heatercontrol.switch()  # turn off all heaters
        self.sampling_time = [0 for _ in range(self.maxsample)]
        self.last_sample = -1
        self.load_state()
        self.stop = False

        # Initialize temperature reader
        self.temp_reader = temperature_reader(logfunc=logfunc)
        self.start_temp_logging()

    def start_temp_logging(self):
        threading.Thread(target=self.log_temperatures, daemon=True).start()

    def log_temperatures(self):
        while not self.temp_reader.stop_temp:
            temperatures = self.temp_reader.read()
            self.log(f'Temperatures: {temperatures}')
            time.sleep(5)  # Log every 5 seconds

    def load_state(self):
        if not os.path.isfile(self.statefile):
            self.reset()
            return

        try:
            with open(self.statefile, 'r') as sf:
                stateline = sf.readline().strip().split(',')
            self.sampling_time, self.last_sample = self.parse_state(stateline)
            self.active_sample = -1
            self.ready = 4 if self.last_sample >= self.maxsample - 1 else 1
        except Exception as e:
            self.log(f'ERROR: Exception {e} while reading state file, resetting values')
            self.reset()

    def parse_state(self, stateline):
        if len(stateline) != self.maxsample + 1:
            raise ValueError(
                f'expected {self.maxsample + 1} state values, received {len(stateline)}'
            )

        sampling_time = [float(value) for value in stateline[:self.maxsample]]
        if any(not math.isfinite(value) or value < 0 for value in sampling_time):
            raise ValueError('sampling times must be finite, non-negative numbers')

        last_sample = int(stateline[-1])
        if not -1 <= last_sample < self.maxsample:
            raise ValueError(
                f'last sample must be between -1 and {self.maxsample - 1}'
            )

        return sampling_time, last_sample

    def reset(self, *args):
        try:
            if os.path.isfile(self.statefile):
                os.remove(self.statefile)
        except Exception as e:
            self.log(f'ERROR: Exception {e} while removing state file')
        self.stop_sample('')
        self.sampling_time = [0 for _ in range(self.maxsample)]
        self.last_sample = -1
        self.active_sample = -1
        self.ready = 1

    def write_statefile(self, force=False):
        if force or self.timepassed('statefile', 5):  # write at most once every 5 seconds
            stateline = ','.join([f'{x:.1f}'.rstrip('0').rstrip('.') for x in self.sampling_time]) + ',' + f'{self.active_sample}'
            with open(self.statefile, 'w') as sf:
                sf.write(f'{stateline}\n')

    def next_sample(self, cmd):
        self.log(f'[Sampler control] Sampling of next sample requested')
        if self.last_sample < self.maxsample - 1:
            sample_now = self.last_sample + 1
            self.sample(sample_now)
        else:
            self.log(f'[Sampler control] Could not proceed: all samples used')
            self.ready = 4

    def manual_sample(self, cmd):
        self.log(f'[Sampler control] Manual sampling request received')
        try:
            command = cmd.split()
            if len(command) != 2:
                raise ValueError('expected command syntax STARTMANUAL <sample_number>')
            sno = int(command[1])
            if not 0 <= sno < self.maxsample:
                raise ValueError(
                    f'sample number must be between 0 and {self.maxsample - 1}'
                )
            self.sample(sno)
        except Exception as e:
            self.log(f'ERROR: Exception {e} encountered')

    def sample(self, sampleno):
        if not isinstance(sampleno, int) or not 0 <= sampleno < self.maxsample:
            self.log(f'[Sampler control] Invalid sample number {sampleno}')
            return False

        with self.sample_lock:
            if self.sampling:
                self.log(f'[Sampler control] Could not proceed, system already sampling')
                return False
            self.stop = False
            self.sampling = True

        sampling_started = False
        self.active_sample = sampleno

        try:
            self.log(
                f'[Sampler control] Sample {sampleno} requested: '
                f'start heating / bypass'
            )
            if self.pumpcontrol.switch(6, True) != 0:
                raise RuntimeError('could not start bypass pump')
            self.bypass = True
            self.ready = 2
            self.timepassed('nanobypass', 0)  # bypass, wait 5 seconds
            while (not self.timepassed('nanobypass', 5)) and not self.stop:
                time.sleep(1)
            if self.stop:
                self.log(
                    f'[Sampler control] Sampling request aborted during '
                    f'bypass phase, stop bypass'
                )
                return False

            if self.pumpcontrol.switch(sampleno, True) != 0:
                raise RuntimeError(f'could not start purge pump {sampleno}')
            self.pump[sampleno] = 1
            self.timepassed('nanopurge', 0)  # purge sample chamber for 3 seconds
            while (not self.timepassed('nanopurge', 3)) and not self.stop:
                time.sleep(1)
            if self.stop:
                self.log(
                    f'[Sampler control] Sampling request aborted during '
                    f'purge phase, stop purge and bypass'
                )
                return False

            if self.pumpcontrol.switch(sampleno, False) != 0:
                raise RuntimeError(f'could not stop purge pump {sampleno}')
            self.pump[sampleno] = 0

            if self.heatercontrol.switch(sampleno, True) != 0:
                raise RuntimeError(f'could not start heater {sampleno}')
            self.heater[sampleno] = 1
            self.timepassed('nanoheat', 0)  # heat for 20 seconds
            while (not self.timepassed('nanoheat', 20)) and not self.stop:
                time.sleep(1)
            if self.stop:
                self.log(
                    f'[Sampler control] Sampling request aborted during '
                    f'pre-heat phase, stop heater and bypass'
                )
                return False

            self.log(f'[Sampler control] Sample {sampleno}: start sampling')
            self.write_statefile(force=True)
            if self.pumpcontrol.switch(sampleno, True) != 0:
                raise RuntimeError(f'could not start sample pump {sampleno}')
            self.pump[sampleno] = 1
            sampling_started = True
            self.ready = 3

            tstart = time.monotonic() - self.sampling_time[sampleno]
            while not self.stop:
                self.sampling_time[sampleno] = time.monotonic() - tstart
                self.write_statefile()
                time.sleep(1)

            self.log(f'[Sampler control] Sample {sampleno}: stop sampling')
            return True
        except Exception as e:
            self.log(
                f'[Sampler control] ERROR: Sample {sampleno} failed with exception {e}'
            )
            return False
        finally:
            self.pumpcontrol.switch(sampleno, False)
            self.pump[sampleno] = 0
            self.heatercontrol.switch(sampleno, False)
            self.heater[sampleno] = 0
            self.pumpcontrol.switch(6, False)
            self.bypass = False

            if sampling_started:
                self.last_sample = sampleno

            self.active_sample = -1
            self.ready = 1 if self.last_sample < self.maxsample - 1 else 4

            with self.sample_lock:
                self.sampling = False

    def stop_sample(self, cmd):
        self.log(f'[Sampler control] Sample stop requested')
        self.stop = True

    def dummy(self, *args):
        pass

    def timepassed(self, timer, since=0):
        test = time.monotonic()
        try:
            self.which[timer]
        except:
            try:
                self.which
            except:
                self.which = {}
            self.which[timer] = time.monotonic()
        if since > 0:
            if time.monotonic() - self.which[timer] > since:
                self.which[timer] = time.monotonic()
                return True
            else:
                return False
        else:
            self.which[timer] = time.monotonic()
            return False

    def status(self):
        statx = []
        for var in self.status_def:
            try:
                statx.append(self.__dict__[var])
            except:
                statx.append('')
        return statx

log = Logger('nanops.log')
nano = nanocontrol(status_nanops, pump_config_nanops, heater_config_nano, logfunc=log.log)

commands = {
    'NEXT': nano.next_sample,
    'STOP': nano.stop_sample,
    'RESET': nano.reset,
    'STARTMANUAL': nano.manual_sample
}

nanoserver = Controlserver(name_nanops, command_table=commands, logfunc=log.log)

try:
    while True:
        time.sleep(1.5)
        nanoserver.send_status(nano.status())
        time.sleep(1.5)
except KeyboardInterrupt:
    log.log('[Sampler control] Closing Controlserver')
    nanoserver.stop()
    nano.temp_reader.stop()
    nano.reset()
    sys.exit()
