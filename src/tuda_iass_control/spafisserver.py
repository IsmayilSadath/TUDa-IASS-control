import math
import os
import sys
import threading
import time
from tpcomm import Controlserver, status_spafis, name_spafis
from logger import Logger
from tphardware import (
    pump_controller,
    pump_config_spafis,
    pressure_config_spafis,
    spafis_pressure_reader,
)

class spafiscontrol():
    def __init__(
        self,
        status_def,
        pump_config,
        statefile='spafisstate.dat',
        logfunc=None,
        pressure_reader=None,
    ):
        if not logfunc:
            self.log = self.dummy
        else:
            self.log = logfunc
        self.status_def = status_def
        self.ready = 0
        self.statefile = statefile
        self.maxsample = 6
        self.active_sample = -1
        self.pump = [0 for x in range(self.maxsample)]
        self.common_pump = 0
        self.sampling_time = [0 for _ in range(self.maxsample)]
        self.last_sample = -1
        self.sampling = False
        self.sample_lock = threading.Lock()
        self.stop = False
        self.pressure_reader = pressure_reader
        self.pumpcontrol = pump_controller(pump_config, logfunc=logfunc)
        self.pumpcontrol.switch() # turn off all small pumps
        self.load_state()

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
        self.sampling_time = [0 for x in range(self.maxsample)]
        self.last_sample = -1
        self.active_sample = -1
        self.ready = 1
        self.common_pump = 0

    def write_statefile(self, force=False):
        if force or self.timepassed('statefile', 5): # write at most once every 5 seconds
            state_sample = self.active_sample if self.active_sample >= 0 else self.last_sample
            stateline = ','.join([f'{x:.1f}' for x in self.sampling_time]) + ',' + f'{state_sample}'
            temporary_statefile = f'{self.statefile}.tmp'
            try:
                with open(temporary_statefile, 'w') as sf:
                    sf.write(f'{stateline}\n')
                    sf.flush()
                    os.fsync(sf.fileno())
                os.replace(temporary_statefile, self.statefile)
            except Exception:
                try:
                    if os.path.isfile(temporary_statefile):
                        os.remove(temporary_statefile)
                except Exception:
                    pass
                raise

    def log_pressure(self, sampleno):
        pressure_reader = getattr(self, 'pressure_reader', None)
        if pressure_reader is None:
            return

        pressure = pressure_reader.read()
        unit = getattr(pressure_reader, 'unit', 'raw_counts')
        raw_counts = getattr(pressure_reader, 'last_raw_counts', '')
        self.log(
            f'[SPAFiS pressure] sample={sampleno} '
            f'elapsed={self.sampling_time[sampleno]:.1f} '
            f'value={pressure} unit={unit} raw_counts={raw_counts}'
        )

    def next_sample(self, cmd):
        # this function keeps simple track of the used samples and calls the sample function for the next one
        self.log(f'[Sampler control] Sampling of next sample requested')
        if self.last_sample < self.maxsample-1:
            sample_now = self.last_sample + 1
            self.sample(sample_now)
        else:
            self.log(f'[Sampler control] Could not proceed: all samples used')
            self.ready = 4

    def manual_sample(self, cmd):
        # start a certain sample manually, independent of previous state, syntax 'STARTMANUAL x'
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
        # this function starts the sampling process, i.e. turning on the pump and sampling
        if not isinstance(sampleno, int) or not 0 <= sampleno < self.maxsample:
            self.log(f'[Sampler control] Invalid sample number {sampleno}')
            return False

        with self.sample_lock:
            if self.sampling:
                self.log(f'[Sampler control] Could not proceed, system already sampling')
                return False
            self.stop = False
            self.sampling = True

        sample_completed = False
        self.active_sample = sampleno

        try:
            self.log(f'[Sampler control] Sample {sampleno}: start sampling')
            self.write_statefile(force=True)
            if self.pumpcontrol.switch(1 + sampleno, True) != 0:
                raise RuntimeError(f'could not open sample valve {sampleno}')
            if self.pumpcontrol.switch(0, True) != 0:
                raise RuntimeError('could not start SPAFiS pump')
            self.pump[sampleno] = 1
            self.common_pump = 1
            self.ready = 3

            tstart = time.monotonic() - self.sampling_time[sampleno]
            while not self.stop:
                self.sampling_time[sampleno] = time.monotonic() - tstart
                self.log_pressure(sampleno)
                self.write_statefile()
                time.sleep(1)

            self.log(f'[Sampler control] Sample {sampleno}: stop sampling')
            sample_completed = True
            return True
        except Exception as e:
            self.log(
                f'[Sampler control] ERROR: Sample {sampleno} failed with exception {e}'
            )
            return False
        finally:
            self.pumpcontrol.switch(0, False)  # switch off pump
            self.pumpcontrol.switch(1 + sampleno, False)  # close valve
            self.pump[sampleno] = 0
            self.common_pump = 0

            if sample_completed:
                self.last_sample = sampleno

            self.active_sample = -1
            self.ready = 1 if self.last_sample < self.maxsample - 1 else 4

            try:
                self.write_statefile(force=True)
            except Exception as e:
                self.log(f'[Sampler control] ERROR: Could not save final state: {e}')

            with self.sample_lock:
                self.sampling = False

    def stop_sample(self, cmd):
        self.log(f'[Sampler control] Sample stop requested')
        self.stop = True

    def shutdown(self):
        self.stop_sample('')
        self.pumpcontrol.switch()
        self.pump = [0 for _ in range(self.maxsample)]
        self.common_pump = 0
        try:
            self.write_statefile(force=True)
        except Exception as e:
            self.log(f'[Sampler control] ERROR: Could not save shutdown state: {e}')
        pressure_reader = getattr(self, 'pressure_reader', None)
        if pressure_reader is not None:
            pressure_reader.close()

    def dummy(self, *args):
        pass

    def timepassed(self,timer,since=0):
        test=time.monotonic()
        try:
            self.which[timer]
        except:
            try:
                self.which
            except:
                self.which={}
            self.which[timer]=time.monotonic()
        if since > 0:
            if time.monotonic()-self.which[timer] > since:
                self.which[timer]=time.monotonic()
                return True
            else:
                return False
        else:
            self.which[timer]=time.monotonic()
            return False

    def status(self):
        statx = []
        for var in self.status_def:
            try:
                statx.append(self.__dict__[var])
            except:
                statx.append('')
        return statx
        # Return values in the order declared in the status map.

log = Logger(logfile='spafis.log')

pressure = spafis_pressure_reader(pressure_config_spafis, logfunc=log.log)
spafis = spafiscontrol(
    status_spafis,
    pump_config_spafis,
    logfunc=log.log,
    pressure_reader=pressure,
)

commands = {'NEXT':spafis.next_sample,
            'STOP':spafis.stop_sample,
            'RESET':spafis.reset}

spafisserver = Controlserver(name_spafis, command_table=commands, logfunc=log.log)

while True:
    try:
        time.sleep(1.5)
        spafisserver.send_status(spafis.status())
        time.sleep(1.5)

    except KeyboardInterrupt:
        log.log('[Sampler control] Closing Controlserver')
        spafisserver.stop()
        spafis.shutdown()
        sys.exit()
