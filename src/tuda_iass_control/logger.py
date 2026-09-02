#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Asynchronous timestamped logging for sampler operation."""

import threading
import atexit
import inspect
import time
import os
import datetime
import re

class Logger(threading.Thread):
    def __init__(self, logfile=True, logpath='', maxretries=10, sleeptime=0.3, debuglevel=0):
        threading.Thread.__init__(self, daemon=True)
        self.messagelist = []
        self.reset(logfile, logpath)
        self.maxretries = maxretries
        self.sleeptime = sleeptime
        self.lock = threading.Lock()
        if debuglevel == 1:
            self.callstack = self._cs1
        elif debuglevel == 2:
            self.callstack = self._cs2
        else:
            self.callstack = self._cs0
        self.wait = False
        atexit.register(self.flush)
        self.start()

    def __call__(self, *args, **kwargs):
        self.log(*args, **kwargs)

    def _cs0(self):
        return []

    def _cs1(self):
        return ['{' + "|".join([st.function for st in inspect.stack()[1:]]) + '}']

    def _cs2(self):
        return ['{ ' + f'{" | ".join([f"{st.function}:{st.filename}:{st.lineno}" for st in inspect.stack()[1:]])}' + ' }']

    def run(self):
        timedelta = time.time() - time.monotonic()
        while True:
            adjust = time.time() - time.monotonic() - timedelta
            if adjust >= 0.5:
                self.log(f'[Logger] System time was step-adjusted by {adjust:.3f} s within the last second')
                timedelta = time.time() - time.monotonic()
            self.flush()
            time.sleep(1)

    def reset(self, logfile=None, logpath=''):
        if logfile is None:
            self.wlog = print
        else:
            if logpath:
                try:
                    os.makedirs(logpath, exist_ok=True)
                except Exception as e:
                    print(f"[Logger] Can't create path {logpath}: {e}")
                    logpath = ''
            if logfile == True:
                self.logfile = os.path.join(os.path.normpath(logpath), 'log_' + time.strftime('%Y%m%d_%H%M%S', time.gmtime()) + '.log')
                self.wlog = self.printfile
            else:
                self.logfile = os.path.join(os.path.normpath(logpath), str(logfile))
                self.wlog = self.printfile

    def to_file(self, loc_msglist):
        allwritten = True
        if loc_msglist:
            fullmsg = '\n'.join(sorted(loc_msglist))
            written = False
            retries = 0
            while (not written) and ((self.maxretries == 0) or (retries <= self.maxretries)):
                try:
                    self.wlog(fullmsg)
                    written = True
                except Exception as e:
                    self.log(f'[Logger] ERROR: Writing to log file failed with exception: {e}')
                    time.sleep(self.sleeptime)
                    retries += 1
            allwritten &= written
        return allwritten

    def flush(self):
        with self.lock:
            self.wait = True
            if not self.to_file(self.messagelist):
                self.reset(True)
                self.to_file(self.messagelist)
            self.messagelist = []
            self.wait = False

    def printfile(self, logstring):
        with open(self.logfile, 'a') as lf:
            lf.write(f'{logstring}\n')

    def putinlist(self, *args, **kwargs):
        logstring = f"{datetime.datetime.now().astimezone().strftime('%Y%m%d-%H%M%S.%f%z')} "
        try:
            logstring += f'[{kwargs["source"]}] '
        except KeyError:
            pass
        try:
            logstring += f'{kwargs["level"]}: '
        except KeyError:
            pass
        logstring += ' '.join([str(a) for a in args])
        logstring = re.sub(r'(?:\x1B[@-Z\\-_]|[\x80-\x9A\x9C-\x9F]|(?:\x1B\[|\x9B)[0-?]*[ -/]*[@-~])', '', logstring)  # remove ansi sequences
        with self.lock:
            self.messagelist.append(logstring)

    def log(self, *args, **kwargs):
        threading.Thread(target=self.putinlist, args=args, kwargs=kwargs).start()
