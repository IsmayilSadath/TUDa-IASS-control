import ast
import importlib.util
import math
import os
import queue
import socket
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from unittest import mock


SOURCE_DIR = Path(__file__).resolve().parents[1] / "src" / "tuda_iass_control"
SSH_LAUNCHER_PATH = SOURCE_DIR / "ssh_launcher.py"


def load_module(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_class(filename, class_name):
    path = SOURCE_DIR / filename
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    namespace = {
        "math": math,
        "os": os,
        "queue": queue,
        "sys": sys,
        "threading": threading,
        "time": time,
    }
    class_module = ast.Module(body=[class_node], type_ignores=[])
    exec(compile(class_module, str(path), "exec"), namespace)
    return namespace[class_name], namespace


class FakeSwitchController:
    def __init__(self):
        self.calls = []

    def switch(self, number=-1, on=False):
        self.calls.append((number, bool(on)))
        return 0


class FakeCanvas:
    def __init__(self):
        self.updates = []

    def itemconfig(self, item, **kwargs):
        self.updates.append((item, kwargs))


class FakeGui:
    def __init__(self):
        self.after_calls = []

    def after(self, delay, callback):
        self.after_calls.append((delay, callback))


class RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tpcomm = load_module("tpcomm_under_test", SOURCE_DIR / "tpcomm.py")
        cls.controlgui, cls.control_namespace = load_class(
            "control.py",
            "controlgui",
        )
        cls.server_classes = {
            "nanoserver.py": load_class("nanoserver.py", "nanocontrol"),
            "miniserver.py": load_class("miniserver.py", "minicontrol"),
            "spafisserver.py": load_class("spafisserver.py", "spafiscontrol"),
        }
        cls.pressure_reader, cls.pressure_namespace = load_class(
            "tphardware.py",
            "spafis_pressure_reader",
        )
        if "paramiko" not in sys.modules:
            paramiko = types.ModuleType("paramiko")
            paramiko.AuthenticationException = type(
                "AuthenticationException",
                (Exception,),
                {},
            )
            paramiko.BadHostKeyException = type(
                "BadHostKeyException",
                (Exception,),
                {},
            )
            paramiko.SSHException = type("SSHException", (Exception,), {})
            paramiko.RejectPolicy = type("RejectPolicy", (), {})
            paramiko.SSHClient = type("SSHClient", (), {})
            sys.modules["paramiko"] = paramiko
        cls.ssh_launcher = load_module(
            "ssh_launcher_under_test",
            SSH_LAUNCHER_PATH,
        )

    def test_unsafe_eval_is_absent(self):
        for path in list(SOURCE_DIR.glob("*.py")) + [SSH_LAUNCHER_PATH]:
            if path.name == Path(__file__).name:
                continue
            self.assertNotIn("eval(", path.read_text(encoding="utf-8"), path.name)

    def test_state_parsers_accept_valid_values_and_reject_code(self):
        self.assertIn("bypass", self.tpcomm.status_mini)
        self.assertIn("common_pump", self.tpcomm.status_spafis)
        cases = [
            ("nanoserver.py", 6),
            ("miniserver.py", 8),
            ("spafisserver.py", 6),
        ]
        for filename, maxsample in cases:
            server_class, _ = self.server_classes[filename]
            server = server_class.__new__(server_class)
            server.maxsample = maxsample

            sampling_time, last_sample = server.parse_state(
                ["1.5"] * maxsample + ["-1"]
            )
            self.assertEqual(sampling_time, [1.5] * maxsample)
            self.assertEqual(last_sample, -1)

            with self.assertRaises(ValueError):
                server.parse_state(
                    ['__import__("os").system("false")']
                    + ["0"] * (maxsample - 1)
                    + ["-1"]
                )
            with self.assertRaises(ValueError):
                server.parse_state(["inf"] * maxsample + ["-1"])
            with self.assertRaises(ValueError):
                server.parse_state(["0"] * maxsample + [str(maxsample)])

            with TemporaryDirectory() as temp_dir:
                statefile = Path(temp_dir) / "state.dat"
                server.statefile = str(statefile)
                server.sampling_time = [1.5] * maxsample
                server.active_sample = 0
                server.write_statefile(force=True)
                self.assertTrue(statefile.is_file())

                loaded = server_class.__new__(server_class)
                loaded.maxsample = maxsample
                loaded.statefile = str(statefile)
                loaded.sampling_time = [0.0] * maxsample
                loaded.last_sample = -1
                loaded.active_sample = -1
                loaded.ready = 0
                loaded.log = lambda *args: None
                loaded.load_state()
                self.assertEqual(loaded.last_sample, 0)
                self.assertEqual(loaded.sampling_time, [1.5] * maxsample)
                self.assertTrue(statefile.is_file())

    def test_spafis_state_keeps_completed_position_and_uses_atomic_replace(self):
        server_class, _ = self.server_classes["spafisserver.py"]
        with TemporaryDirectory() as temp_dir:
            statefile = Path(temp_dir) / "spafisstate.dat"
            server = server_class.__new__(server_class)
            server.maxsample = 6
            server.statefile = str(statefile)
            server.sampling_time = [1.5] * server.maxsample
            server.active_sample = -1
            server.last_sample = 2
            server.write_statefile(force=True)

            self.assertEqual(statefile.read_text(encoding="utf-8").strip().split(",")[-1], "2")
            self.assertFalse(Path(f"{statefile}.tmp").exists())

            server.active_sample = 4
            server.write_statefile(force=True)
            self.assertEqual(statefile.read_text(encoding="utf-8").strip().split(",")[-1], "4")

    def test_spafis_pressure_reader_decodes_frame_and_rejects_sensor_status(self):
        pressure_reader = self.pressure_reader

        class FakeSpi:
            def __init__(self, frame):
                self.frame = frame
                self.requests = []

            def xfer2(self, request):
                self.requests.append(request)
                return self.frame

        spi = FakeSpi([0x20, 0x00, 0x00, 0x00])
        reader = pressure_reader(
            {
                "frame_length": 4,
                "output_min": 1638,
                "output_max": 14746,
                "pressure_min": -1000.0,
                "pressure_max": 1000.0,
                "unit": "Pa",
            },
            spi=spi,
        )
        value = reader.read()
        self.assertEqual(spi.requests, [[0, 0, 0, 0]])
        self.assertEqual(reader.last_raw_counts, 0x2000)
        self.assertAlmostEqual(value, 0.0, places=3)
        self.assertEqual(reader.unit, "Pa")

        invalid = pressure_reader(
            {"frame_length": 4},
            spi=FakeSpi([0x40, 0x00, 0x00, 0x00]),
        )
        with self.assertRaises(IOError):
            invalid.read()

    def test_manual_sample_rejects_code_and_out_of_range_values(self):
        cases = [
            ("nanoserver.py", 6),
            ("miniserver.py", 8),
            ("spafisserver.py", 6),
        ]
        for filename, maxsample in cases:
            server_class, _ = self.server_classes[filename]
            server = server_class.__new__(server_class)
            server.maxsample = maxsample
            server.log_messages = []
            server.log = server.log_messages.append
            server.sample_calls = []
            server.sample = server.sample_calls.append

            server.manual_sample('STARTMANUAL __import__("os").system("false")')
            server.manual_sample(f"STARTMANUAL {maxsample}")
            self.assertEqual(server.sample_calls, [])

            server.manual_sample("STARTMANUAL 0")
            self.assertEqual(server.sample_calls, [0])

    def test_send_command_adds_exactly_one_newline(self):
        class CapturingSocket:
            def __init__(self):
                self.sent = []

            def sendall(self, data):
                self.sent.append(data)

        client = self.tpcomm.Controlclient.__new__(self.tpcomm.Controlclient)
        client.active = True
        client.name = "SPAFiS"
        client.log = lambda *args: None
        client.cclient = CapturingSocket()
        client.send_lock = threading.Lock()

        self.assertTrue(client.send_command("NEXT\n"))
        payload = client.cclient.sent[0]
        self.assertTrue(payload.endswith(b"NEXT\n"))
        self.assertEqual(payload.count(b"\n"), 1)

    def test_socket_timeout_is_restored_after_peek(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        left.settimeout(7.5)

        client = self.tpcomm.Controlclient.__new__(self.tpcomm.Controlclient)
        client.name = "SPAFiS"
        client.log = lambda *args: None

        self.assertFalse(client.is_socket_closed(left))
        self.assertEqual(left.gettimeout(), 7.5)

    def test_truncated_status_packet_is_logged_and_skipped(self):
        messages = []
        client = self.tpcomm.Controlclient.__new__(self.tpcomm.Controlclient)
        client.name = "SPAFiS"
        client.log = messages.append

        result = client.make_stat(
            self.tpcomm.status_spafis,
            "1;0,0,0,0,0,0",
        )
        self.assertIsNone(result)
        self.assertTrue(any("Incomplete status packet" in msg for msg in messages))

    def test_tcp_framing_handles_partial_and_coalesced_commands(self):
        server = self.tpcomm.Controlserver
        buffer, commands = server.extract_commands(
            b"",
            b"(2026-07-25 12:00:00) STATUSPORT 5000\n"
            b"(2026-07-25 12:00:01) NE",
        )
        self.assertEqual(commands, ["STATUSPORT 5000"])

        buffer, commands = server.extract_commands(
            buffer,
            b"XT\n(2026-07-25 12:00:02) STOP\n",
        )
        self.assertEqual(buffer, b"")
        self.assertEqual(commands, ["NEXT", "STOP"])

    def test_none_led_status_is_rendered_as_error_without_type_error(self):
        gui = self.controlgui.__new__(self.controlgui)
        canvas = FakeCanvas()

        gui.set_led(canvas, "status-light", None)
        self.assertEqual(
            canvas.updates[-1],
            ("status-light", {"fill": "#ff0000"}),
        )

    def test_status_queue_runs_callbacks_from_queue_processor(self):
        gui = self.controlgui.__new__(self.controlgui)
        gui.status_queue = queue.Queue()
        gui.gui = FakeGui()
        received = []

        gui.queue_status(received.append, {"ready": 1})
        gui.process_status_queue()

        self.assertEqual(received, [{"ready": 1}])
        self.assertEqual(gui.gui.after_calls[0][0], 50)

    def test_miniserver_rejects_second_sample_during_flush(self):
        server_class, namespace = self.server_classes["miniserver.py"]
        entered_sleep = threading.Event()
        release_sleep = threading.Event()

        class BlockingTime:
            @staticmethod
            def monotonic():
                return 1.0

            @staticmethod
            def sleep(_):
                entered_sleep.set()
                release_sleep.wait(timeout=2)

        previous_time = namespace["time"]
        namespace["time"] = BlockingTime
        self.addCleanup(namespace.__setitem__, "time", previous_time)

        server = server_class.__new__(server_class)
        server.maxsample = 8
        server.sample_lock = threading.Lock()
        server.sampling = False
        server.stop = False
        server.active_sample = -1
        server.last_sample = -1
        server.pump = [0] * server.maxsample
        server.sampling_time = [0.0] * server.maxsample
        server.flush = False
        server.bypass = 1
        server.ready = 1
        server.status_def = self.tpcomm.status_mini
        server.pumpcontrol = FakeSwitchController()
        server.log = lambda *args: None
        server.write_statefile = lambda *args, **kwargs: None
        server.timepassed = lambda *args: False

        first_result = []
        first = threading.Thread(
            target=lambda: first_result.append(server.sample(0))
        )
        first.start()
        self.assertTrue(entered_sleep.wait(timeout=1))

        self.assertFalse(server.sample(0))
        server.stop = True
        release_sleep.set()
        first.join(timeout=2)

        self.assertEqual(first_result, [False])
        self.assertFalse(server.sampling)
        self.assertEqual(server.pump[0], 0)
        self.assertEqual(server.status()[3], 1)

    def test_nanops_preheat_abort_clears_heater_state_and_hardware(self):
        server_class, _ = self.server_classes["nanoserver.py"]
        server = server_class.__new__(server_class)
        server.maxsample = 6
        server.sample_lock = threading.Lock()
        server.sampling = False
        server.stop = False
        server.active_sample = -1
        server.last_sample = -1
        server.pump = [0] * server.maxsample
        server.heater = [0] * server.maxsample
        server.sampling_time = [0.0] * server.maxsample
        server.bypass = False
        server.ready = 1
        server.pumpcontrol = FakeSwitchController()
        server.heatercontrol = FakeSwitchController()
        server.log = lambda *args: None
        server.write_statefile = lambda: None

        def timepassed(timer, since=0):
            if since == 0:
                return False
            if timer in {"nanobypass", "nanopurge"}:
                return True
            if timer == "nanoheat":
                server.stop = True
                return False
            raise AssertionError(timer)

        server.timepassed = timepassed

        self.assertFalse(server.sample(0))
        self.assertIn((0, True), server.heatercontrol.calls)
        self.assertIn((0, False), server.heatercontrol.calls)
        self.assertEqual(server.heater[0], 0)
        self.assertEqual(server.pump[0], 0)
        self.assertFalse(server.bypass)
        self.assertFalse(server.sampling)
        self.assertEqual(server.active_sample, -1)

    def test_spafis_mocked_start_stop_cleans_pump_and_valve(self):
        server_class, namespace = self.server_classes["spafisserver.py"]

        class StopAfterFirstLoop:
            counter = 0

            @classmethod
            def monotonic(cls):
                cls.counter += 1
                return float(cls.counter)

            @staticmethod
            def sleep(_):
                server.stop = True

        previous_time = namespace["time"]
        namespace["time"] = StopAfterFirstLoop
        self.addCleanup(namespace.__setitem__, "time", previous_time)

        server = server_class.__new__(server_class)
        server.maxsample = 6
        server.sample_lock = threading.Lock()
        server.sampling = False
        server.stop = False
        server.active_sample = -1
        server.last_sample = -1
        server.pump = [0] * server.maxsample
        server.common_pump = 0
        server.sampling_time = [0.0] * server.maxsample
        server.ready = 1
        server.status_def = self.tpcomm.status_spafis
        server.pumpcontrol = FakeSwitchController()
        server.log = lambda *args: None
        server.write_statefile = lambda *args, **kwargs: None

        self.assertTrue(server.sample(0))
        self.assertIn((1, True), server.pumpcontrol.calls)
        self.assertIn((0, True), server.pumpcontrol.calls)
        self.assertIn((0, False), server.pumpcontrol.calls)
        self.assertIn((1, False), server.pumpcontrol.calls)
        self.assertEqual(server.pump[0], 0)
        self.assertEqual(server.common_pump, 0)
        self.assertFalse(server.sampling)
        self.assertEqual(server.active_sample, -1)
        self.assertEqual(server.last_sample, 0)

    def test_spafis_sampling_logs_pressure_values(self):
        server_class, namespace = self.server_classes["spafisserver.py"]

        class StopAfterFirstPressureRead:
            counter = 0

            @classmethod
            def monotonic(cls):
                cls.counter += 1
                return float(cls.counter)

            @staticmethod
            def sleep(_):
                server.stop = True

        class FakePressureReader:
            unit = "Pa"
            last_raw_counts = 321

            def __init__(self):
                self.read_count = 0

            def read(self):
                self.read_count += 1
                return 12.5

        previous_time = namespace["time"]
        namespace["time"] = StopAfterFirstPressureRead
        self.addCleanup(namespace.__setitem__, "time", previous_time)

        messages = []
        server = server_class.__new__(server_class)
        server.maxsample = 6
        server.sample_lock = threading.Lock()
        server.sampling = False
        server.stop = False
        server.active_sample = -1
        server.last_sample = -1
        server.pump = [0] * server.maxsample
        server.common_pump = 0
        server.sampling_time = [0.0] * server.maxsample
        server.ready = 1
        server.status_def = self.tpcomm.status_spafis
        server.pumpcontrol = FakeSwitchController()
        server.pressure_reader = FakePressureReader()
        server.log = messages.append
        server.write_statefile = lambda *args, **kwargs: None

        self.assertTrue(server.sample(0))
        self.assertEqual(server.pressure_reader.read_count, 1)
        self.assertTrue(any("[SPAFiS pressure]" in message for message in messages))
        self.assertTrue(any("value=12.5" in message for message in messages))

    def test_spafis_pressure_failure_does_not_consume_sample(self):
        server_class, _ = self.server_classes["spafisserver.py"]

        class FailedPressureReader:
            def read(self):
                raise IOError("sensor unavailable")

        server = server_class.__new__(server_class)
        server.maxsample = 6
        server.sample_lock = threading.Lock()
        server.sampling = False
        server.stop = False
        server.active_sample = -1
        server.last_sample = -1
        server.pump = [0] * server.maxsample
        server.common_pump = 0
        server.sampling_time = [0.0] * server.maxsample
        server.ready = 1
        server.pumpcontrol = FakeSwitchController()
        server.pressure_reader = FailedPressureReader()
        server.log = lambda *args: None
        server.write_statefile = lambda *args, **kwargs: None

        self.assertFalse(server.sample(0))
        self.assertEqual(server.last_sample, -1)
        self.assertEqual(server.pump[0], 0)
        self.assertEqual(server.common_pump, 0)

    def test_ssh_client_uses_reject_policy_and_known_hosts(self):
        class FakeSSHClient:
            def __init__(self):
                self.system_keys_loaded = False
                self.loaded_file = None
                self.policy = None
                self.connect_kwargs = None

            def load_system_host_keys(self):
                self.system_keys_loaded = True

            def load_host_keys(self, filename):
                self.loaded_file = filename

            def set_missing_host_key_policy(self, policy):
                self.policy = policy

            def connect(self, **kwargs):
                self.connect_kwargs = kwargs

        fake = FakeSSHClient()
        with mock.patch.object(
            self.ssh_launcher.paramiko,
            "SSHClient",
            return_value=fake,
        ), mock.patch.object(
            self.ssh_launcher,
            "get_password",
            return_value=None,
        ):
            result = self.ssh_launcher.create_ssh_client(
                "SPAFiS",
                {"host": "192.0.2.5", "username": "pi"},
            )

        self.assertIs(result, fake)
        self.assertTrue(fake.system_keys_loaded)
        self.assertIsInstance(
            fake.policy,
            self.ssh_launcher.paramiko.RejectPolicy,
        )
        self.assertEqual(fake.connect_kwargs["hostname"], "192.0.2.5")

        with NamedTemporaryFile() as known_hosts:
            dedicated = FakeSSHClient()
            with mock.patch.object(
                self.ssh_launcher.paramiko,
                "SSHClient",
                return_value=dedicated,
            ), mock.patch.object(
                self.ssh_launcher,
                "get_password",
                return_value=None,
            ):
                result = self.ssh_launcher.create_ssh_client(
                    "SPAFiS",
                    {
                        "host": "192.0.2.5",
                        "username": "pi",
                        "known_hosts_file": known_hosts.name,
                    },
                )
            self.assertIs(result, dedicated)
            self.assertEqual(dedicated.loaded_file, known_hosts.name)
            self.assertIsInstance(
                dedicated.policy,
                self.ssh_launcher.paramiko.RejectPolicy,
            )


if __name__ == "__main__":
    unittest.main()
