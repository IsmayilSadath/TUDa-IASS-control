import socket
import time
import threading
import atexit
import re

tpcomm_default_broadcast_port = 55120
tpcomm_default_broadcast_address = '255.255.255.255'
name_nanops = 'NanoPS'
name_spafis = 'SPAFiS'
name_mini = 'MultiMINI8'

status_nanops = ['ready', 'heater', 'pump', 'bypass', 'active_sample', 'sampling_time']
status_mini = ['ready', 'pump', 'flush', 'bypass', 'active_sample', 'sampling_time']
status_spafis = ['ready', 'pump', 'common_pump', 'active_sample', 'sampling_time']

class Broadcast_listener():
    def __init__(self, broadcast_port=tpcomm_default_broadcast_port, logfunc=None):
        if not logfunc:
            self.log = self.dummy
        else:
            self.log = logfunc
        self.kill = False
        self.running = False
        self.broadcast_port = broadcast_port
        # Dictionary to store known samplers and their addresses
        self.known_samplers = {}
        self.allowed_samplers = {name_nanops, name_spafis, name_mini}

    def start(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self.init, daemon=True).start()
            atexit.register(self.stop)

    def init(self):
        self.log('Initiate broadcast listener')
        self.bclient = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP
        self.bclient.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.bclient.bind(("", self.broadcast_port))
        while not self.kill:
            try:
                data, addr = self.bclient.recvfrom(1024)
                data = data.decode('utf-8')
                for sampler in self.allowed_samplers:
                    if data.startswith(sampler):
                        self.known_samplers[sampler] = (addr[0], int(data.split()[-1]))
                        self.log(f'Received broadcast from {sampler}: {addr[0]}:{data.split()[-1]}')
            except Exception as e:
                self.log(f'Error in broadcast listener: {e}')

    def get_info(self, sampler):
        try:
            return self.known_samplers[sampler]
        except KeyError:
            self.log(f'Broadcast listener: requested unknown sampler {sampler}')
            return None

    def dummy(self, *args):
        pass

    def stop(self):
        self.kill = True

class Controlclient():
    def __init__(self, name, status_def, logfunc=None, statfunc=None, delay=0) -> None:
        self.name = name
        self.status_def = status_def
        if not logfunc:
            self.log = self.dummy
        else:
            self.log = logfunc
        if not statfunc:
            self.stat = self.dummy
        else:
            self.stat = statfunc
        self.kill = False
        self.active = False
        self.send_lock = threading.Lock()
        time.sleep(delay)
        threading.Thread(target=self.init, daemon=True).start()
        atexit.register(self.stop)

    def init(self):
        self.log(f'[{self.name}] Initiate network control client')
        BL.start()
        while not self.kill:
            info = BL.get_info(self.name)
            if info:
                caddr, cport = info
                try:
                    self.cclient = socket.create_connection((caddr, cport))
                    self.cclient.settimeout(10)
                    self.active = True
                    self.sclient = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP
                    self.sclient.bind(("", 0))
                    self.sclient.settimeout(0.5)
                    sport = self.sclient.getsockname()[1]
                    self.send_command(f'STATUSPORT {sport}')
                    self.log(f'[{self.name}] Connected to {caddr}, control port {cport}, local status port {sport}')
                    while not self.kill and self.active and not self.is_socket_closed(self.cclient):
                        try:
                            data, addr = self.sclient.recvfrom(1024)
                            data = data.decode('utf-8')
                            self.log(f'[{self.name}] STATUS: {data}')
                            argstr = re.sub(r"[\(\[\{].*?[\)\]\}]", "", data).strip()
                            data = self.make_stat(self.status_def, argstr)
                            if data is not None:
                                self.stat(data)
                        except socket.timeout:
                            pass
                        except Exception as e:
                            self.log(f'[{self.name}] ERROR: Exception at status handling {e}')
                    self.active = False
                    self.stat(None)
                except Exception as e:
                    self.log(f'[{self.name}] ERROR: Exception at init {e}')
                    try:
                        self.sclient.close()
                    except Exception as e:
                        self.log(f'[{self.name}] ERROR: Exception at closing sclient {e}')
                    try:
                        self.cclient.close()
                    except Exception as e:
                        self.log(f'[{self.name}] ERROR: Exception at closing cclient {e}')
            time.sleep(1)

    def dummy(self, *args):
        pass

    def make_stat(self, vmap, argstring):
        statdict = {}
        svals = argstring.split(';')
        if len(svals) < len(vmap):
            self.log(
                f'[{self.name}] WARNING: Incomplete status packet: '
                f'expected {len(vmap)} values, received {len(svals)}'
            )
            return None
        for n in range(len(vmap)):
            if ',' in svals[n]:
                statdict[vmap[n]] = [float(x) for x in svals[n].split(',') if x]
            else:
                statdict[vmap[n]] = float(svals[n]) if svals[n] else None
        return statdict

    def send_command(self, command):
        if self.active:
            try:
                self.log(f'[{self.name}] CMD: {command}')
                command = str(command).rstrip('\r\n')
                cdata = (
                    f'({time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}) '
                    f'{command}\n'
                ).encode('utf-8')
                with self.send_lock:
                    self.cclient.sendall(cdata)
                return True
            except Exception as e:
                self.log(f'[{self.name}] ERROR: Exception {e}')
                self.active = False
                return False
        else:
            self.log(f'[{self.name}] ERROR: Connection not active, but command issued')
            return False

    def isactive(self):
        return self.active

    def stop(self):
        self.kill = True

    def is_socket_closed(self, sock: socket.socket) -> bool:
        original_timeout = sock.gettimeout()
        try:
            sock.setblocking(False)
            data = sock.recv(16, socket.MSG_PEEK)
            if len(data) == 0:
                return True
        except BlockingIOError:
            return False  # socket is open and reading from it would block
        except ConnectionResetError:
            return True  # socket was closed for some other reason
        except Exception as e:
            self.log(f'[{self.name}] ERROR: during testing of connection, an exception occurred: {e}')
            return False
        finally:
            try:
                sock.settimeout(original_timeout)
            except OSError as e:
                self.log(
                    f'[{self.name}] ERROR: could not restore socket timeout '
                    f'after connection check: {e}'
                )
        return False

class Controlserver():
    def __init__(self, name, broadcast_port=tpcomm_default_broadcast_port,
                 ltimeout=10, logfunc=None, command_table={}) -> None:
        self.name = name
        self.ltimeout = ltimeout
        self.ring = []
        self.kill = False
        self.connected = False
        self.status_active = False
        if not logfunc:
            self.log = self.dummy
        else:
            self.log = logfunc
        self.broadcast_port = broadcast_port
        self.command_table = command_table
        threading.Thread(target=self.init, daemon=True).start()
        atexit.register(self.stop)

    def init(self):
        self.log(f'[{self.name}] Initiate network control server')
        self.bserver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.bserver.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.bserver.settimeout(0.5)
        self.bserver.bind(('', 0))
        self.sserver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sserver.settimeout(0.5)
        self.sserver.bind(('', 0))
        self.cserver = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.cserver.bind(('', 0))
        self.listen_port = self.cserver.getsockname()[1]
        self.cserver.settimeout(self.ltimeout)
        message = f'{self.name} {self.listen_port}'.encode('utf-8')
        self.cserver.listen(1)
        while not self.kill:
            self.bserver.sendto(
                message,
                (tpcomm_default_broadcast_address, self.broadcast_port),
            )
            self.log(f'[{self.name}] Broadcast announcement sent')
            try:
                connection, client = self.cserver.accept()
                self.clientid = client[0]
                try:
                    self.log(f'[{self.name}] Connected to command client {client}')
                    self.connected = True
                    command_buffer = b''
                    while not self.kill:
                        data = connection.recv(1024)
                        if not data:
                            if command_buffer.strip():
                                self.log(
                                    f'[{self.name}] WARNING: Discarding incomplete '
                                    f'command at connection close'
                                )
                            break
                        command_buffer, commands = self.extract_commands(
                            command_buffer,
                            data,
                        )
                        for command in commands:
                            self.log(f'[{self.name}] CMD: {command}')
                            self.command_handler(command)
                except Exception as e:
                    self.log(f'[{self.name}] ERROR with exception {e}')
                    connection.close()
                    self.connected = False
                    self.status_active = False
                finally:
                    connection.close()
                    self.connected = False
                    self.status_active = False
            except socket.timeout:
                self.log(f'[{self.name}] No connection')

    def dummy(self, *args):
        pass

    @staticmethod
    def extract_commands(command_buffer, data):
        command_buffer += data
        commands = []

        while b'\n' in command_buffer:
            command_line, command_buffer = command_buffer.split(b'\n', 1)
            if not command_line.strip():
                continue
            command = command_line.decode('utf-8')
            command = re.sub(
                r"[\(\[\{].*?[\)\]\}]",
                "",
                command,
            ).strip()
            if command:
                commands.append(command)

        if len(command_buffer) > 4096:
            raise ValueError('command exceeds maximum length of 4096 bytes')

        return command_buffer, commands

    def command_handler(self, command):
        command = str(command)
        if command.startswith('STATUSPORT'):
            self.send_port = int(command.split()[-1])
            self.status_active = True
            self.log(f'[{self.name}] Sending status information to {self.clientid}, port {self.send_port}')
        else:
            try:
                cmd = command.split(maxsplit=1)[0]
                if cmd in self.command_table:
                    threading.Thread(target=self.command_table[cmd], args=[command], daemon=True).start()
                else:
                    self.log(f'[{self.name}] WARNING: unknown command {command}, ignoring it')
            except Exception as e:
                self.log(f'[{self.name}] ERROR handling command {command}, exception: {e}')

    def stat_encode(self, lst):
        def format_element(el):
            try:
                # Try to convert to float and format
                return f'{float(el):.1f}'.rstrip('0').rstrip('.')
            except ValueError:
                # If conversion fails, return the original element
                return el

        return ';'.join([','.join([format_element(k) for k in l])
                         if isinstance(l, list) else format_element(l) for l in lst])

    def send_status(self, lst):
        message = self.stat_encode(lst)
        if self.status_active:
            try:
                self.sserver.sendto(str(message).encode('utf-8'), (self.clientid, self.send_port))
                self.log(f'[{self.name}] STATUS: {message}')
            except Exception as e:
                self.log(f'[{self.name}] ERROR: Exception {e}')
        else:
            self.log(f'[{self.name}] Not connected for sending status information')

    def clear(self):
        self.ring = []

    def stop(self):
        self.kill = True

BL = Broadcast_listener()
atexit.register(BL.stop)
