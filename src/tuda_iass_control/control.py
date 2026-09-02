import queue
import re
import sys
import threading
import time
from tpcomm import Controlclient, status_nanops, status_mini, status_spafis, name_nanops, name_mini, name_spafis
from logger import Logger
import tkinter as tk
from tkinter import messagebox
import tkinter.ttk as ttk
import tkinter.font as font

class controlgui():
    def __init__(self, logfiles=[], infodict={}):
        self.gui = tk.Tk()
        self.status_queue = queue.Queue()
        self.mainframe = tk.Frame(self.gui, padx=5, pady=5)
        self.mainframe.pack()
        self.col_bg = '#99ccff'
        self.col_act = '#00aa00'
        self.col_stop = '#aa0000'
        self.col_run = '#00aa00'
        bFont = font.Font(size=13, weight="bold")
        font10 = font.Font(size=10, weight="bold")

        self.nanobg = "#ffcccc"
        self.nanoframe = tk.LabelFrame(self.mainframe, text='NanoPS', padx=3, pady=3, background=self.nanobg)
        self.nanoframe['font'] = font10
        self.nanoframe.pack(side='top', fill='both', expand='yes')
        self.nanobuttons = tk.Frame(self.nanoframe)
        self.nanobuttons.pack(side='left', padx=3, pady=3)
        self.nanostatframe = tk.Frame(self.nanoframe, background=self.nanobg)
        self.nanostatframe.pack(side='right', fill='both', expand='yes', padx=3, pady=3)
        self.nanopumpframe = tk.LabelFrame(self.nanostatframe, text='Pumps', background=self.nanobg)
        self.nanopumpframe.pack(side='bottom', fill='both', expand='yes', padx=3, pady=3)
        self.nanoheaterframe = tk.LabelFrame(self.nanostatframe, text='Heaters', background=self.nanobg)
        self.nanoheaterframe.pack(side='bottom', fill='both', expand='yes', padx=3, pady=3)
        self.nanosampleframe = tk.LabelFrame(self.nanostatframe, text='Samples', background=self.nanobg)
        self.nanosampleframe.pack(side='top', fill='both', expand='yes', padx=3, pady=3)
        self.nanostart = tk.Button(self.nanobuttons, text='Start',
                                   command=self.nano_start,
                                   bg=self.col_bg, activebackground=self.col_act)
        self.nanostart['font'] = bFont
        self.nanostart.pack(side='top', fill='x')
        self.nanostop = tk.Button(self.nanobuttons, text='Stop',
                                  command=self.nano_stop,
                                  bg=self.col_bg, activebackground=self.col_stop)
        self.nanostop['font'] = bFont
        self.nanostop['state'] = 'disabled'
        self.nanostop.pack(side='top', fill='x')
        self.nanoreset = tk.Button(self.nanobuttons, text='Reset',
                                   command=self.nano_reset,
                                   bg=self.col_bg, activebackground=self.col_stop)
        self.nanoreset['font'] = bFont
        self.nanoreset.pack(side='bottom', fill='x')
        self.nanopumpcanvas, self.nanopumpstatus = self.make_status_buttons(self.nanopumpframe,
                                                                            [str(x+1) for x in range(6)]+['bypass'],
                                                                            background=self.nanobg, width=240)
        self.nanoheatercanvas, self.nanoheaterstatus = self.make_status_buttons(self.nanoheaterframe,
                                                                            [str(x+1) for x in range(6)],
                                                                            background=self.nanobg, width=205)
        self.nanosamplecanvas, self.nanosamplestatus, self.nano_st = self.make_status_buttons(self.nanosampleframe,
                [str(x+1) for x in range(6)], shape='q', width=300, buttontext=['0' for x in range(6)],
                background=self.nanobg)
        self.nano_show_mode('inactive')

        self.minibg = "#ccff99"
        self.miniframe = tk.LabelFrame(self.mainframe, text='MultiMINI8', padx=3, pady=3, background=self.minibg)
        self.miniframe['font'] = font10
        self.miniframe.pack(side='top', fill='both', expand='yes')
        self.minibuttons = tk.Frame(self.miniframe, background=self.minibg)
        self.minibuttons.pack(side='left', padx=3, pady=3)
        self.ministatframe = tk.Frame(self.miniframe, background=self.minibg)
        self.ministatframe.pack(side='right', fill='both', expand='yes', padx=3, pady=3)
        self.minipumpframe = tk.LabelFrame(self.ministatframe, text='Pumps', background=self.minibg)
        self.minipumpframe.pack(side='bottom', fill='both', expand='yes', padx=3, pady=3)
        self.minisampleframe = tk.LabelFrame(self.ministatframe, text='Samples', background=self.minibg)
        self.minisampleframe.pack(side='top', fill='both', expand='yes', padx=3, pady=3)
        self.ministart = tk.Button(self.minibuttons, text='Start',
                                   command=self.mini_start,
                                   bg=self.col_bg, activebackground=self.col_act)
        self.ministart['font'] = bFont
        self.ministart.pack(side='top', fill='x')
        self.ministop = tk.Button(self.minibuttons, text='Stop',
                                  command=self.mini_stop,
                                  bg=self.col_bg, activebackground=self.col_stop)
        self.ministop['font'] = bFont
        self.ministop['state'] = 'disabled'
        self.ministop.pack(side='top', fill='x')
        self.minireset = tk.Button(self.minibuttons, text='Reset',
                                   command=self.mini_reset,
                                   bg=self.col_bg, activebackground=self.col_stop)
        self.minireset['font'] = bFont
        self.minireset.pack(side='top', fill='x')
        self.minipumpcanvas, self.minipumpstatus = self.make_status_buttons(self.minipumpframe,
                                                                            ['flush']+[str(x+1) for x in range(8)]+['bypass'],
                                                                            background=self.minibg, width=340)

        self.minisamplecanvas, self.minisamplestatus, self.mini_st = self.make_status_buttons(self.minisampleframe,
                [str(x+1) for x in range(8)], shape='q', width=400, buttontext=['0' for x in range(8)],
                background=self.minibg)
        self.mini_show_mode('inactive')

        self.spafisbg = "#ccccff"
        self.spafisframe = tk.LabelFrame(self.mainframe, text='SPAFiS', padx=3, pady=3, background=self.spafisbg)
        self.spafisframe['font'] = font10
        self.spafisframe.pack(side='top', fill='both', expand='yes')
        self.spafisbuttons = tk.Frame(self.spafisframe)
        self.spafisbuttons.pack(side='left', padx=3, pady=3)
        self.spafisstatframe = tk.Frame(self.spafisframe, background=self.spafisbg)
        self.spafisstatframe.pack(side='right', fill='both', expand='yes', padx=3, pady=3)
        self.spafisvalveframe = tk.LabelFrame(self.spafisstatframe, text='Valves / Pumps', background=self.spafisbg)
        self.spafisvalveframe.pack(side='bottom', fill='both', expand='yes', padx=3, pady=3)
        self.spafissampleframe = tk.LabelFrame(self.spafisstatframe, text='Samples', background=self.spafisbg)
        self.spafissampleframe.pack(side='top', fill='both', expand='yes', padx=3, pady=3)
        self.spafisstart = tk.Button(self.spafisbuttons, text='Start',
                                     command=self.spafis_start,
                                     bg=self.col_bg, activebackground=self.col_act)
        self.spafisstart['font'] = bFont
        self.spafisstart.pack(side='top', fill='x')
        self.spafisstop = tk.Button(self.spafisbuttons, text='Stop',
                                    command=self.spafis_stop,
                                    bg=self.col_bg, activebackground=self.col_stop)
        self.spafisstop['font'] = bFont
        self.spafisstop['state'] = 'disabled'
        self.spafisstop.pack(side='top', fill='x')
        self.spafisreset = tk.Button(self.spafisbuttons, text='Reset',
                                     command=self.spafis_reset,
                                     bg=self.col_bg, activebackground=self.col_stop)
        self.spafisreset['font'] = bFont
        self.spafisreset.pack(side='bottom', fill='x')

        self.spafisvalvecanvas, self.spafisvalvestatus = self.make_status_buttons(self.spafisvalveframe,
                ['common pump']+[str(x+1) for x in range(6)],
                background=self.spafisbg, width=240)

        self.spafissamplecanvas, self.spafissamplestatus, self.spafis_st = self.make_status_buttons(self.spafissampleframe,
                [str(x+1) for x in range(6)], shape='q', width=300, buttontext=['0' for x in range(6)],
                background=self.spafisbg)

        self.spafis_show_mode('inactive')
        self.gui.after(50, self.process_status_queue)

    def queue_status(self, callback, data):
        self.status_queue.put((callback, data))

    def process_status_queue(self):
        while True:
            try:
                callback, data = self.status_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback(data)
            except Exception as e:
                print(f'GUI status update failed: {e}')
        self.gui.after(50, self.process_status_queue)

    def nicetime(self, sec):
        try:
            if isinstance(sec, str):
                sec = float(sec)
            return f'{int(sec/60):.0f}:{sec % 60:02.0f}'
        except:
            return ''

    def make_status_buttons(self, frame, labels, width=250, height=50, shape='c', buttontext=None, background=None):
        if background:
            canvas = tk.Canvas(frame, width=width, height=height, background=background, highlightthickness=0)
        else:
            canvas = tk.Canvas(frame, width=width, height=height, highlightthickness=0)
        canvas.pack(side='right', fill='both', expand='yes')
        xper = width / len(labels)
        buttons = {}
        if buttontext:
            button_text = {}
        for b in range(len(labels)):
            xcent = xper * (b + 0.5)
            if shape == 'c':
                buttons[labels[b]] = canvas.create_oval(xcent-0.4*xper, 0.1*xper, xcent+0.4*xper, 0.9*xper)
            elif shape == 'q':
                buttons[labels[b]] = canvas.create_rectangle(xcent-0.4*xper, 0.1*xper, xcent+0.4*xper, 0.9*xper)
            canvas.create_text(xcent, xper*1.2, text=labels[b])
            if buttontext:
                button_text[labels[b]] = canvas.create_text(xcent, xper*0.5, text=buttontext[b])
        if buttontext:
            return canvas, buttons, button_text
        else:
            return canvas, buttons

    def set_led(self, canvas, button, status, buttontext=None, text=None):
        if status in [True, 'on']:
            canvas.itemconfig(button, fill='#00ff00')
        elif status in [False, 'off']:
            canvas.itemconfig(button, fill='#cccccc')
        elif status in ['active']:
            canvas.itemconfig(button, fill='#00ff00')
        elif status in ['preparing']:
            canvas.itemconfig(button, fill='#008000')
        elif status is None:
            canvas.itemconfig(button, fill='#ff0000')
        elif isinstance(status, (int, float)) and status > 0:
            canvas.itemconfig(button, fill='#996633')
        elif status == 0:
            canvas.itemconfig(button, fill='#008000')
        else:
            canvas.itemconfig(button, fill='#ff0000')
        if buttontext:
            canvas.itemconfig(buttontext, text=text)

    def threaded(self, command, *args):
        threading.Thread(target=command, args=args, daemon=True).start()

    ## NanoPS specific

    def nano_show_mode(self, which):
        if which == 'start':
            self.nanostop['state'] = 'disabled'
            self.nanostart.config(bg=self.col_bg)
            self.nanostart['state'] = 'normal'
            self.nanoreset['state'] = 'normal'
        elif which == 'stop':
            self.nanostop['state'] = 'normal'
            self.nanostart['state'] = 'disabled'
            self.nanostart.config(bg=self.col_run)
            self.nanoreset['state'] = 'normal'
        elif which == 'inactive':
            self.nanostop['state'] = 'disabled'
            self.nanostop.config(bg=self.col_bg)
            self.nanostart['state'] = 'disabled'
            self.nanostart.config(bg=self.col_bg)
            self.nanoreset['state'] = 'disabled'
        elif which == 'full':
            self.nanostop['state'] = 'disabled'
            self.nanostop.config(bg=self.col_bg)
            self.nanostart['state'] = 'disabled'
            self.nanostart.config(bg=self.col_bg)
            self.nanoreset['state'] = 'normal'

    def nano_start(self):
        self.nano_show_mode('stop')
        self.threaded(nanops_control.send_command, 'NEXT')

    def nano_stop(self):
        self.nano_show_mode('start')
        self.threaded(nanops_control.send_command, 'STOP')

    def nano_reset(self):
        assure = messagebox.askokcancel('Reset NanoPS', 'Are you sure to reset NanoPS?')
        if assure:
            self.threaded(nanops_control.send_command, 'RESET')

    def nano_stat(self, statdict):
        if statdict:
            self.nanostat = statdict
            if self.nanostat['ready'] == 0:
                self.nano_show_mode('inactive')
            elif self.nanostat['ready'] == 1:
                self.nano_show_mode('start')
            elif self.nanostat['ready'] in [2, 3]:
                self.nano_show_mode('stop')
            elif self.nanostat['ready'] in [4]:
                self.nano_show_mode('full')
            for p in range(len(self.nanostat['pump'])):
                self.set_led(self.nanopumpcanvas, self.nanopumpstatus[str(p+1)], bool(self.nanostat['pump'][p]))
            self.set_led(self.nanopumpcanvas, self.nanopumpstatus['bypass'], bool(self.nanostat['bypass']))
            for p in range(len(self.nanostat['heater'])):
                self.set_led(self.nanoheatercanvas, self.nanoheaterstatus[str(p+1)], bool(self.nanostat['heater'][p]))

            for p in range(len(self.nanostat['sampling_time'])):
                if p == self.nanostat['active_sample']:
                    if self.nanostat['ready'] == 2:
                        self.set_led(self.nanosamplecanvas, self.nanosamplestatus[str(p+1)], 'preparing',
                                        self.nano_st[str(p+1)], 'Prep.')
                    elif self.nanostat['ready'] == 3:
                        self.set_led(self.nanosamplecanvas, self.nanosamplestatus[str(p+1)], 'active',
                                self.nano_st[str(p+1)],
                                self.nicetime(self.nanostat['sampling_time'][p]))
                else:
                    self.set_led(self.nanosamplecanvas, self.nanosamplestatus[str(p+1)], self.nanostat['sampling_time'][p],
                                self.nano_st[str(p+1)],
                                self.nicetime(self.nanostat['sampling_time'][p]))
        else:
            self.nano_show_mode('inactive')

    ## MultiMINI8 specific

    def mini_start(self):
        self.mini_show_mode('stop')
        self.threaded(mini_control.send_command, 'NEXT')

    def mini_stop(self):
        self.mini_show_mode('start')
        self.threaded(mini_control.send_command, 'STOP')

    def mini_reset(self):
        assure = messagebox.askokcancel('Reset MultiMINI8', 'Are you sure to reset MultiMINI8?')
        if assure:
            self.threaded(mini_control.send_command, 'RESET')

    def mini_show_mode(self, which):
        if which == 'start':
            self.ministop['state'] = 'disabled'
            self.ministart.config(bg=self.col_bg)
            self.ministart['state'] = 'normal'
            self.minireset['state'] = 'normal'
        elif which == 'stop':
            self.ministop['state'] = 'normal'
            self.ministart['state'] = 'disabled'
            self.ministart.config(bg=self.col_run)
            self.minireset['state'] = 'normal'
        elif which == 'inactive':
            self.ministop['state'] = 'disabled'
            self.ministop.config(bg=self.col_bg)
            self.ministart['state'] = 'disabled'
            self.ministart.config(bg=self.col_bg)
            self.minireset['state'] = 'disabled'
        elif which == 'full':
            self.ministop['state'] = 'disabled'
            self.ministop.config(bg=self.col_bg)
            self.ministart['state'] = 'disabled'
            self.ministart.config(bg=self.col_bg)
            self.minireset['state'] = 'normal'

    def mini_stat(self, statdict):
        if statdict:
            self.ministat = statdict
            if self.ministat['ready'] == 0:
                self.mini_show_mode('inactive')
            elif self.ministat['ready'] in [1]:
                self.mini_show_mode('start')
            elif self.ministat['ready'] in [2, 3]:
                self.mini_show_mode('stop')
            elif self.ministat['ready'] in [4]:
                self.mini_show_mode('full')
            for p in range(len(self.ministat['pump'])):
                self.set_led(self.minipumpcanvas, self.minipumpstatus[str(p+1)], bool(self.ministat['pump'][p]))
            self.set_led(self.minipumpcanvas, self.minipumpstatus['flush'], bool(self.ministat['flush']))
            self.set_led(self.minipumpcanvas, self.minipumpstatus['bypass'], bool(self.ministat['bypass']))
            for p in range(len(self.ministat['sampling_time'])):
                if p == self.ministat['active_sample']:
                    if self.ministat['ready'] == 2:
                        self.set_led(self.minisamplecanvas, self.minisamplestatus[str(p+1)], 'preparing',
                                     self.mini_st[str(p+1)], 'Prep.')
                    elif self.ministat['ready'] == 3:
                        self.set_led(self.minisamplecanvas, self.minisamplestatus[str(p+1)], 'active',
                                self.mini_st[str(p+1)],
                                self.nicetime(self.ministat['sampling_time'][p]))
                else:
                    self.set_led(self.minisamplecanvas, self.minisamplestatus[str(p+1)], self.ministat['sampling_time'][p],
                                self.mini_st[str(p+1)],
                                self.nicetime(self.ministat['sampling_time'][p]))
        else:
            self.mini_show_mode('inactive')


    ## SPAFiS specific

    def spafis_show_mode(self, which):
        if which == 'start':
            self.spafisstop['state'] = 'disabled'
            self.spafisstart.config(bg=self.col_bg)
            self.spafisstart['state'] = 'normal'
            self.spafisreset['state'] = 'normal'
        elif which == 'stop':
            self.spafisstop['state'] = 'normal'
            self.spafisstart['state'] = 'disabled'
            self.spafisstart.config(bg=self.col_run)
            self.spafisreset['state'] = 'normal'
        elif which == 'inactive':
            self.spafisstop['state'] = 'disabled'
            self.spafisstop.config(bg=self.col_bg)
            self.spafisstart['state'] = 'disabled'
            self.spafisstart.config(bg=self.col_bg)
            self.spafisreset['state'] = 'disabled'
        elif which == 'full':
            self.spafisstop['state'] = 'disabled'
            self.spafisstop.config(bg=self.col_bg)
            self.spafisstart['state'] = 'disabled'
            self.spafisstart.config(bg=self.col_bg)
            self.spafisreset['state'] = 'normal'

    def spafis_start(self):
        self.spafis_show_mode('stop')
        self.threaded(spafis_control.send_command, 'NEXT')

    def spafis_stop(self):
        self.spafis_show_mode('start')
        self.threaded(spafis_control.send_command, 'STOP')

    def spafis_reset(self):
        assure = messagebox.askokcancel('Reset SPAFiS', 'Are you sure to reset SPAFiS?')
        if assure:
            self.threaded(spafis_control.send_command, 'RESET')

    def spafis_stat(self, statdict):
        if statdict:
            self.spafisstat = statdict
            if self.spafisstat['ready'] == 0:
                self.spafis_show_mode('inactive')
            elif self.spafisstat['ready'] == 1:
                self.spafis_show_mode('start')
            elif self.spafisstat['ready'] in [2, 3]:
                self.spafis_show_mode('stop')
            elif self.spafisstat['ready'] in [4]:
                self.spafis_show_mode('full')
            for p in range(len(self.spafisstat['pump'])):
                self.set_led(self.spafisvalvecanvas, self.spafisvalvestatus[str(p+1)], bool(self.spafisstat['pump'][p]))
            self.set_led(self.spafisvalvecanvas, self.spafisvalvestatus['common pump'], bool(self.spafisstat['common_pump']))
            for p in range(len(self.spafisstat['sampling_time'])):
                if p == self.spafisstat['active_sample']:
                    if self.spafisstat['ready'] == 2:
                        self.set_led(self.spafissamplecanvas, self.spafissamplestatus[str(p+1)], 'preparing',
                                     self.spafis_st[str(p+1)], 'Prep.')
                    elif self.spafisstat['ready'] == 3:
                        self.set_led(self.spafissamplecanvas, self.spafissamplestatus[str(p+1)], 'active',
                                self.spafis_st[str(p+1)],
                                self.nicetime(self.spafisstat['sampling_time'][p]))
                else:
                    self.set_led(self.spafissamplecanvas, self.spafissamplestatus[str(p+1)], self.spafisstat['sampling_time'][p],
                                self.spafis_st[str(p+1)],
                                self.nicetime(self.spafisstat['sampling_time'][p]))
        else:
            self.spafis_show_mode('inactive')


    def run(self):
        self.gui.title("TUDa-IASS Aerosol Sampler Control")
        self.gui.mainloop()

log = Logger(logfile='tuda_iass_control.log')

log.log('[TUDa-IASS] Starting')

root = controlgui()
nanops_control = Controlclient(
    name_nanops,
    status_nanops,
    logfunc=log.log,
    statfunc=lambda data: root.queue_status(root.nano_stat, data),
)
mini_control = Controlclient(
    name_mini,
    status_mini,
    logfunc=log.log,
    statfunc=lambda data: root.queue_status(root.mini_stat, data),
)
spafis_control = Controlclient(
    name_spafis,
    status_spafis,
    logfunc=log.log,
    statfunc=lambda data: root.queue_status(root.spafis_stat, data),
)

root.run()

log.log('[TUDa-IASS] Exiting')

sys.exit()
