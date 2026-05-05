"""Cross-platform helpers — paths, defaults, process lookup.

All platform-specific knowledge lives here so the rest of the CLI can stay
oblivious to whether it's running on Windows, macOS, or Linux.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def config_dir() -> Path:
    """Per-user config directory for sdcli.

    Windows:  %APPDATA%\\sdcli
    macOS:    ~/Library/Application Support/sdcli
    Linux:    $XDG_CONFIG_HOME/sdcli  (or ~/.config/sdcli)
    """
    if IS_WINDOWS:
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "sdcli"
        return Path.home() / "AppData" / "Roaming" / "sdcli"
    if IS_MACOS:
        return Path.home() / "Library" / "Application Support" / "sdcli"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "sdcli"
    return Path.home() / ".config" / "sdcli"


def runtime_dir() -> Path:
    """Per-user runtime dir for PID files, server logs.

    Windows:  same as config_dir() (no good convention there)
    Linux/Mac: $XDG_RUNTIME_DIR or ~/.local/state/sdcli
    """
    if IS_WINDOWS:
        return config_dir()
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / "sdcli"
    return Path.home() / ".local" / "state" / "sdcli"


def default_install_dir() -> Path:
    """Best guess at where ComfyUI lives on a fresh machine."""
    if IS_WINDOWS:
        return Path("D:/comfyui-rocm")
    return Path.home() / "ComfyUI"


def default_python() -> str:
    """Best-effort default for the python interpreter that runs ComfyUI.

    On Windows we keep the comfyui-rocm portable env. On Unix we look for a
    venv inside the install dir, then fall back to ``python3`` on PATH.
    """
    if IS_WINDOWS:
        return str(default_install_dir() / "python_env" / "python.exe")
    venv_python = default_install_dir() / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    found = shutil.which("python3") or shutil.which("python")
    return found or "python3"


def default_launcher() -> Path:
    """Default launcher script path. Differs by platform."""
    if IS_WINDOWS:
        return default_install_dir() / "start-detached.ps1"
    return default_install_dir() / "start-detached.sh"


def default_log_path() -> Path:
    if IS_WINDOWS:
        return default_install_dir() / "server.log"
    return runtime_dir() / "comfyui.log"


def default_pid_path() -> Path:
    """Where a Unix-style start writes the server PID. Unused on Windows."""
    return runtime_dir() / "comfyui.pid"


def find_listening_pids(port: int) -> list[int]:
    """Return PIDs of processes listening on ``port``.

    Uses PowerShell on Windows, ``lsof`` on macOS/Linux (with an ``ss``
    fallback for Linux containers that lack lsof).
    """
    if IS_WINDOWS:
        return _find_listening_pids_windows(port)
    return _find_listening_pids_unix(port)


def _find_listening_pids_windows(port: int) -> list[int]:
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-Command",
        f"Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue "
        "| Select-Object -ExpandProperty OwningProcess",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return []
    if proc.returncode != 0:
        return []
    return [int(x) for x in proc.stdout.split() if x.strip().isdigit()]


def _find_listening_pids_unix(port: int) -> list[int]:
    if shutil.which("lsof"):
        proc = subprocess.run(
            ["lsof", "-tiTCP:" + str(port), "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return [int(x) for x in proc.stdout.split() if x.strip().isdigit()]
    if shutil.which("ss"):
        proc = subprocess.run(
            ["ss", "-ltnpH", f"sport = :{port}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            pids: list[int] = []
            for line in proc.stdout.splitlines():
                # users:(("python",pid=12345,fd=3))
                if "pid=" not in line:
                    continue
                for part in line.split("pid="):
                    digits = ""
                    for ch in part:
                        if ch.isdigit():
                            digits += ch
                        else:
                            break
                    if digits:
                        pids.append(int(digits))
            return pids
    return []


def open_editor_command(editor: Optional[str]) -> str:
    """Resolve the editor to use for ``sd config edit``."""
    if editor:
        return editor
    env = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if env:
        return env
    if IS_WINDOWS:
        return "notepad"
    for candidate in ("nano", "vim", "vi"):
        if shutil.which(candidate):
            return candidate
    return "vi"
