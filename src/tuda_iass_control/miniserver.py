import math
import os
import sys
import threading
import time
from tpcomm import Controlserver, status_mini, name_mini
from logger import Logger
from tphardware import pump_controller, pump_config_mini

class minicontrol():
    def __init__(self, status_def, pump_config, statefile='ministate.dat', logfunc=None):
        if not logfunc:
            self.log = self.dummy
        else:
            self.log = logfunc
        self.status_def = status_def
        self.ready = 0
        self.flush = 0
        self.bypass = 0
        self.statefile = statefile
        self.maxsample = 8
        self.active_sample = -1
        self.pump = [0 for x in range(self.maxsample)]
        self.sampling_time = [0 for _ in range(self.maxsample)]
        self.last_sample = -1
        self.sampling = False
        self.sample_lock = threading.Lock()
        self.stop = False
        self.pumpcontrol = pump_controller(pump_config, logfunc=logfunc)
        self.pumpcontrol.switch() # turn off all small pumps
        if self.pumpcontrol.switch(9, True) == 0:  # turn on bypass
            self.bypass = 1
            self.log('INFO: Turning on bypass pump')
        else:
            self.log('ERROR: Could not turn on bypass pump')
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
            if self.last_sample >= self.maxsample - 1:
                self.ready = 4
                self.pumpcontrol.switch(9, False)
                self.bypass = 0
            else:
                self.ready = 1
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
        if self.pumpcontrol.switch(9, True) == 0:
            self.bypass = 1

    def write_statefile(self, force=False):
        if force or self.timepassed('statefile', 5): # write at most once every 5 seconds
            stateline = ','.join([f'{x:.1f}' for x in self.sampling_time]) + ',' + f'{self.active_sample}'
            with open(self.statefile,'w') as sf:
                sf.write(f'{stateline}\n')

    def next_sample(self, cmd):
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
            self.log(f'[Sampler control] Sample {sampleno} requested: start flushing')
            if self.pumpcontrol.switch(0, True) != 0:
                raise RuntimeError('could not start flushing pump')
            self.flush = True
            self.ready = 2
            self.timepassed('miniflush', 0)
            while (not self.timepassed('miniflush', 15)) and not self.stop:
                time.sleep(1)
            if self.stop:
                self.log(
                    f'[Sampler control] Sampling request aborted during '
                    f'flushing phase, stop flushing'
                )
                return False

            if self.pumpcontrol.switch(0, False) != 0:
                raise RuntimeError('could not stop flushing pump')
            self.log(f'[Sampler control] Sample {sampleno}: stop flushing')
            self.flush = False

            self.log(f'[Sampler control] Sample {sampleno}: start sampling')
            self.write_statefile(force=True)
            if self.pumpcontrol.switch(1 + sampleno, True) != 0:
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
            self.pumpcontrol.switch(0, False)
            self.pumpcontrol.switch(1 + sampleno, False)
            self.flush = False
            self.pump[sampleno] = 0

            if sampling_started:
                self.last_sample = sampleno

            self.active_sample = -1
            if self.last_sample < self.maxsample - 1:
                self.ready = 1
                self.bypass = 1
            else:
                self.ready = 4
                self.pumpcontrol.switch(9, False)  # turn off bypass
                self.bypass = 0

            with self.sample_lock:
                self.sampling = False

    def stop_sample(self, cmd):
        self.log(f'[Sampler control] Sample stop requested')
        self.stop = True

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

log = Logger('multimini.log')

mini = minicontrol(status_mini, pump_config_mini, logfunc=log.log)

commands = {'NEXT':mini.next_sample,
            'STOP':mini.stop_sample,
            'RESET':mini.reset,
            'STARTMANUAL':mini.manual_sample}
miniserver = Controlserver(name_mini, command_table=commands, logfunc=log.log)

while True:
    try:
        time.sleep(1.5)
        miniserver.send_status(mini.status())
        time.sleep(1.5)

    except KeyboardInterrupt:
        log.log('[Sampler control] Closing Controlserver')
        miniserver.stop()
        mini.reset()   # remove state file, if system is taken down by ctrl-C
        sys.exit()
