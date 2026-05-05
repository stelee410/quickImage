"""``sd server`` — manage the local ComfyUI server lifecycle.

The actual platform-specific glue (start a detached process, find PIDs by
listening port) lives in :mod:`sdcli.platform_utils`. Everything in this
module above the helpers should read the same on Windows and Unix.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import click

from sdcli import config as config_mod
from sdcli import platform_utils as plat
from sdcli.backends.comfy import ComfyClient
from sdcli.utils.format import console, error, info, success, warn


@click.group()
def server() -> None:
    """Manage the local ComfyUI server."""


@server.command(name="status")
def cmd_status() -> None:
    """Show whether the ComfyUI server is reachable and report a few stats."""
    cfg = config_mod.load()
    client = ComfyClient(cfg.server_url)
    if not client.is_alive():
        error(f"server unreachable at {cfg.server_url}")
        info("start it with: sd server start")
        raise click.exceptions.Exit(1)
    stats = client.system_stats()
    sys_ = stats.get("system", {})
    devs = stats.get("devices", []) or []
    success(f"server alive at {cfg.server_url}")
    console.print(f"  comfyui: [bold]{sys_.get('comfyui_version','?')}[/bold]   pytorch: {sys_.get('pytorch_version','?')}")
    console.print(f"  python:  {sys_.get('python_version','?').splitlines()[0]}")
    if devs:
        d = devs[0]
        vram_total = d.get("vram_total", 0) / 2**30
        vram_free = d.get("vram_free", 0) / 2**30
        console.print(f"  device:  {d.get('name','?')}  VRAM {vram_free:.1f}/{vram_total:.1f} GiB free")
    queue = client.queue()
    running = len(queue.get("queue_running", []) or [])
    pending = len(queue.get("queue_pending", []) or [])
    console.print(f"  queue:   running={running}  pending={pending}")


@server.command(name="start")
@click.option("--wait/--no-wait", default=True, help="Wait for /system_stats to respond before returning.")
def cmd_start(wait: bool) -> None:
    """Start the ComfyUI server in the background (idempotent)."""
    cfg = config_mod.load()
    client = ComfyClient(cfg.server_url)
    if client.is_alive():
        success(f"server already running at {cfg.server_url}")
        return

    launcher = cfg.get("server.launcher", "")
    launcher_path = Path(launcher) if launcher else None
    try:
        if launcher_path and launcher_path.exists():
            _launch_via_script(launcher_path)
        else:
            _launch_builtin(cfg)
    except _LaunchError as e:
        error(str(e))
        raise click.exceptions.Exit(2)

    if not wait:
        success("launcher started; not waiting for readiness")
        return

    timeout = int(cfg.get("server.start_timeout", 180) or 180)
    info(f"waiting up to {timeout}s for server readiness...")
    start = time.time()
    next_log = start + 15
    while time.time() - start < timeout:
        if client.is_alive():
            success(f"server up after {time.time()-start:.0f}s — {cfg.server_url}")
            return
        if time.time() > next_log:
            elapsed = time.time() - start
            info(f"  still waiting... ({elapsed:.0f}s)")
            next_log = time.time() + 30
        time.sleep(2)
    error("server did not become ready within timeout")
    info(f"check log: {cfg.get('server.log_path','?')}")
    raise click.exceptions.Exit(1)


@server.command(name="stop")
@click.option("--force", is_flag=True, help="Skip confirmation and kill all matching processes.")
def cmd_stop(force: bool) -> None:
    """Stop ComfyUI by killing the python process bound to its port."""
    cfg = config_mod.load()
    pids = _find_server_pids(cfg.server_url)
    if not pids:
        # Try the PID file as a backstop (Unix launchers write one).
        pid_path = Path(cfg.get("server.pid_path", "") or "")
        if pid_path.exists():
            try:
                pid = int(pid_path.read_text().strip())
                pids = [pid]
            except (ValueError, OSError):
                pass
    if not pids:
        warn("no listening process found on configured port")
        return
    info(f"will kill PIDs: {pids}")
    if not force and not click.confirm("Proceed?", default=True):
        info("aborted")
        return
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            success(f"sent SIGTERM to PID {pid}")
        except OSError as e:
            error(f"failed to signal {pid}: {e}")
    # Best-effort cleanup of stale pid file
    pid_path = Path(cfg.get("server.pid_path", "") or "")
    if pid_path.exists():
        try:
            pid_path.unlink()
        except OSError:
            pass


@server.command(name="restart")
@click.pass_context
def cmd_restart(ctx: click.Context) -> None:
    """Stop the server then start it again."""
    ctx.invoke(cmd_stop, force=True)
    time.sleep(2)
    ctx.invoke(cmd_start, wait=True)


@server.command(name="logs")
@click.option("-f", "--follow", is_flag=True, help="Tail and follow the log file.")
@click.option("-n", "--lines", default=50, show_default=True, help="Number of lines to show initially.")
def cmd_logs(follow: bool, lines: int) -> None:
    """Show the ComfyUI server stdout/stderr log."""
    cfg = config_mod.load()
    log_path = Path(cfg.get("server.log_path", ""))
    if not log_path.exists():
        error(f"log file not found: {log_path}")
        raise click.exceptions.Exit(1)
    # Initial dump
    with log_path.open("r", encoding="utf-8", errors="replace") as fh:
        all_lines = fh.readlines()
        for line in all_lines[-lines:]:
            console.print(line.rstrip())
        if not follow:
            return
        # Follow mode
        try:
            while True:
                where = fh.tell()
                line = fh.readline()
                if not line:
                    time.sleep(0.5)
                    fh.seek(where)
                else:
                    console.print(line.rstrip())
        except KeyboardInterrupt:
            return


# --- internals --------------------------------------------------------------


class _LaunchError(RuntimeError):
    pass


def _launch_via_script(launcher: Path) -> None:
    """Run an explicit launcher script (.ps1 on Windows, .sh on Unix)."""
    info(f"launching: {launcher}")
    if plat.IS_WINDOWS:
        cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher)]
    else:
        if not os.access(launcher, os.X_OK):
            try:
                launcher.chmod(launcher.stat().st_mode | 0o111)
            except OSError:
                pass
        cmd = [str(launcher)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        msg = f"launcher failed (exit {proc.returncode})"
        if proc.stderr:
            msg += "\n" + proc.stderr
        raise _LaunchError(msg)


def _launch_builtin(cfg: config_mod.Config) -> None:
    """Fallback launcher used when no script is configured.

    Windows: error out — there's no clean built-in detach without the
    bundled PowerShell helper, and most Windows installs already point at
    ``start-detached.ps1``. Tell the user how to fix it.
    Unix: ``nohup python main.py ... > log 2>&1 &`` and write the PID file.
    """
    if plat.IS_WINDOWS:
        raise _LaunchError(
            "no launcher script configured. Set server.launcher to a "
            ".ps1 file (e.g. D:\\comfyui-rocm\\start-detached.ps1)."
        )

    install_dir = cfg.install_dir
    main_py = install_dir / "main.py"
    if not main_py.exists():
        raise _LaunchError(
            f"could not find ComfyUI entry point at {main_py}. "
            "Set server.install_dir to your ComfyUI directory."
        )
    python = cfg.server_python or "python3"
    log_path = Path(cfg.get("server.log_path", "") or plat.default_log_path())
    pid_path = Path(cfg.get("server.pid_path", "") or plat.default_pid_path())
    log_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.parent.mkdir(parents=True, exist_ok=True)

    info(f"launching: {python} {main_py}")
    info(f"  log -> {log_path}")
    info(f"  pid -> {pid_path}")
    log_fh = open(log_path, "ab", buffering=0)
    try:
        proc = subprocess.Popen(
            [python, str(main_py)],
            cwd=str(install_dir),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    finally:
        log_fh.close()
    pid_path.write_text(str(proc.pid) + "\n", encoding="utf-8")


def _find_server_pids(server_url: str) -> list[int]:
    from urllib.parse import urlparse

    parsed = urlparse(server_url)
    port = parsed.port or 8188
    return plat.find_listening_pids(port)
