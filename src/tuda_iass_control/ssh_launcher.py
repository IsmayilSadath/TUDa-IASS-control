#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SSH launcher for TUDa-IASS aerosol sampler control.

This module starts and stops instrument-specific server scripts on Raspberry Pi
devices. Network addresses, usernames, and script paths are read from a local
configuration file instead of being hard-coded in the source code.

Local configuration file:
    config/config.yaml

Example configuration file:
    config/config.example.yaml

Do not commit config/config.yaml to GitHub.
"""

import logging
import os
import shlex
import time
from pathlib import Path
from typing import Dict, Any, Optional

import paramiko
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

try:
    import yaml
except ImportError as exc:
    raise ImportError(
        "PyYAML is required. Install it with: pip install PyYAML"
    ) from exc


# Repository root:
# src/tuda_iass_control/ssh_launcher.py -> project root is two levels above src/
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config" / "config.example.yaml"

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE_PATH = LOG_DIR / "pi_initialization.log"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

file_handler = logging.FileHandler(LOG_FILE_PATH)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
)
logger.addHandler(file_handler)


def load_config() -> Dict[str, Any]:
    """
    Load Raspberry Pi connection settings from config/config.yaml.

    If config/config.yaml is missing, the example file is loaded only to show
    the expected structure. Real operation requires a private config/config.yaml.
    """
    if CONFIG_PATH.exists():
        config_file = CONFIG_PATH
    else:
        config_file = EXAMPLE_CONFIG_PATH
        logger.warning(
            "Private config file not found at %s. "
            "Using example configuration from %s.",
            CONFIG_PATH,
            EXAMPLE_CONFIG_PATH,
        )

    with open(config_file, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    if not config or "raspberry_pis" not in config:
        raise ValueError(
            "Configuration file must contain a 'raspberry_pis' section."
        )

    return config


def get_password(instrument_name: str, pi_info: Dict[str, Any]) -> Optional[str]:
    """
    Get the SSH password without storing it in the repository.

    Priority:
    1. Use SSH key if configured through key_filename.
    2. Use an environment variable if configured through password_env.
    3. Ask the operator through a password dialog.
    """
    if pi_info.get("key_filename"):
        return None

    password_env = pi_info.get("password_env")
    if password_env:
        password = os.environ.get(password_env)
        if password:
            return password

    return simpledialog.askstring(
        title=f"SSH password for {instrument_name}",
        prompt=f"Enter SSH password for {instrument_name}:",
        show="*",
    )


def create_ssh_client(
    instrument_name: str,
    pi_info: Dict[str, Any],
) -> Optional[paramiko.SSHClient]:
    """
    Create an SSH connection to a Raspberry Pi using verified host keys.

    By default, Paramiko reads the operator's standard known_hosts file. An
    instrument can instead set known_hosts_file in config.yaml to use a
    dedicated file. Unknown or changed host keys are rejected.
    """
    host = pi_info.get("host")
    username = pi_info.get("username")
    key_filename = pi_info.get("key_filename")
    known_hosts_file = pi_info.get("known_hosts_file")

    if not host or not username:
        logger.error(
            "Missing host or username for %s in configuration.",
            instrument_name,
        )
        return None

    password = get_password(instrument_name, pi_info)

    try:
        ssh = paramiko.SSHClient()

        if known_hosts_file:
            known_hosts_path = Path(
                os.path.expandvars(os.path.expanduser(str(known_hosts_file)))
            )
            if not known_hosts_path.is_file():
                logger.error(
                    "Configured known_hosts file for %s does not exist: %s",
                    instrument_name,
                    known_hosts_path,
                )
                return None
            ssh.load_host_keys(str(known_hosts_path))
        else:
            ssh.load_system_host_keys()

        ssh.set_missing_host_key_policy(paramiko.RejectPolicy())

        ssh.connect(
            hostname=host,
            username=username,
            password=password,
            key_filename=key_filename,
            timeout=10,
        )

        logger.info("Connected to %s at %s", instrument_name, host)
        return ssh

    except paramiko.BadHostKeyException as exc:
        logger.error(
            "SSH host key mismatch for %s at %s. Connection rejected: %s",
            instrument_name,
            host,
            exc,
        )
    except paramiko.AuthenticationException:
        logger.error("Authentication failed for %s at %s", instrument_name, host)
    except paramiko.SSHException as exc:
        logger.error(
            "SSH error for %s at %s: %s. Confirm that this host is present "
            "in the configured known_hosts file.",
            instrument_name,
            host,
            exc,
        )
    except Exception as exc:
        logger.error("Failed to connect to %s at %s: %s", instrument_name, host, exc)

    return None


def check_script_permissions(ssh: paramiko.SSHClient, script: str) -> bool:
    """
    Check whether the configured server script exists on the Raspberry Pi.
    """
    quoted_script = shlex.quote(script)
    command = f"test -f {quoted_script} && echo FOUND || echo MISSING"

    stdin, stdout, stderr = ssh.exec_command(command)
    output = stdout.read().decode().strip()
    error = stderr.read().decode().strip()

    if error:
        logger.error("Error checking script path %s: %s", script, error)
        return False

    if output != "FOUND":
        logger.error("Server script not found: %s", script)
        return False

    logger.info("Server script found: %s", script)
    return True


def initialize_pi(instrument_name: str, pi_info: Dict[str, Any]) -> None:
    """
    Start the instrument-specific server script on the Raspberry Pi.
    """
    script = pi_info.get("script")

    if not script:
        logger.error("Missing script path for %s in configuration.", instrument_name)
        return

    ssh = create_ssh_client(instrument_name, pi_info)
    if ssh is None:
        return

    try:
        if not check_script_permissions(ssh, script):
            return

        quoted_script = shlex.quote(script)
        remote_log = f"/tmp/{instrument_name.lower()}_server.log"

        command = (
            f"nohup python3 {quoted_script} "
            f"> {shlex.quote(remote_log)} 2>&1 & echo $!"
        )

        stdin, stdout, stderr = ssh.exec_command(command)

        process_id = stdout.read().decode().strip()
        error = stderr.read().decode().strip()

        if error:
            logger.error("Error starting %s server: %s", instrument_name, error)
        else:
            logger.info(
                "Started %s server with PID %s. Remote log: %s",
                instrument_name,
                process_id,
                remote_log,
            )

    except Exception as exc:
        logger.error("Failed to initialize %s: %s", instrument_name, exc)
    finally:
        ssh.close()
        logger.info("SSH connection closed for %s", instrument_name)


def stop_pi(instrument_name: str, pi_info: Dict[str, Any]) -> None:
    """
    Stop the instrument-specific server script on the Raspberry Pi.
    """
    script = pi_info.get("script")

    if not script:
        logger.error("Missing script path for %s in configuration.", instrument_name)
        return

    ssh = create_ssh_client(instrument_name, pi_info)
    if ssh is None:
        return

    try:
        script_name = Path(script).name
        quoted_script_name = shlex.quote(script_name)

        command = f"pkill -f {quoted_script_name}"

        stdin, stdout, stderr = ssh.exec_command(command)
        error = stderr.read().decode().strip()

        if error:
            logger.error("Error stopping %s server: %s", instrument_name, error)
        else:
            logger.info("Stopped %s server process matching %s", instrument_name, script_name)

    except Exception as exc:
        logger.error("Failed to stop %s server: %s", instrument_name, exc)
    finally:
        ssh.close()
        logger.info("SSH connection closed for %s", instrument_name)


def start_all(pis: Dict[str, Dict[str, Any]]) -> None:
    """
    Start all configured Raspberry Pi server scripts.
    """
    for instrument_name, pi_info in pis.items():
        logger.info("Initializing %s server...", instrument_name)
        initialize_pi(instrument_name, pi_info)
        time.sleep(2)

    messagebox.showinfo("Info", "All configured servers have been initialized.")


def create_gui() -> None:
    """
    Create the launcher GUI.
    """
    try:
        config = load_config()
        pis = config["raspberry_pis"]
    except Exception as exc:
        messagebox.showerror("Configuration error", str(exc))
        return

    root = tk.Tk()
    root.title("TUDa-IASS Raspberry Pi Server Control")

    mainframe = ttk.Frame(root, padding=10)
    mainframe.pack(fill="both", expand=True)

    title = ttk.Label(
        mainframe,
        text="TUDa-IASS Raspberry Pi Server Control",
        font=("Arial", 14, "bold"),
    )
    title.pack(pady=(0, 10))

    start_all_button = ttk.Button(
        mainframe,
        text="Start All Servers",
        command=lambda: start_all(pis),
    )
    start_all_button.pack(fill="x", pady=(0, 10))

    for instrument_name, pi_info in pis.items():
        frame = ttk.LabelFrame(mainframe, text=instrument_name, padding=10)
        frame.pack(fill="x", pady=5)

        host = pi_info.get("host", "not configured")
        script = pi_info.get("script", "not configured")

        info_label = ttk.Label(
            frame,
            text=f"Host: {host}\nScript: {script}",
        )
        info_label.pack(anchor="w", pady=(0, 5))

        button_frame = ttk.Frame(frame)
        button_frame.pack(fill="x")

        start_button = ttk.Button(
            button_frame,
            text="Start",
            command=lambda name=instrument_name, info=pi_info: initialize_pi(name, info),
        )
        start_button.pack(side="left", padx=(0, 5))

        stop_button = ttk.Button(
            button_frame,
            text="Stop",
            command=lambda name=instrument_name, info=pi_info: stop_pi(name, info),
        )
        stop_button.pack(side="left")

    close_button = ttk.Button(mainframe, text="Close", command=root.destroy)
    close_button.pack(fill="x", pady=(10, 0))

    root.mainloop()


if __name__ == "__main__":
    create_gui()
