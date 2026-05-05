"""``sd server`` — manage the local ComfyUI server lifecycle."""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import click

from sdcli import config as config_mod
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

    launcher = Path(cfg.get("server.launcher", ""))
    if not launcher.exists():
        error(f"launcher script not found: {launcher}")
        info("set the path with: sd config set server.launcher <path-to-start-detached.ps1>")
        raise click.exceptions.Exit(2)

    info(f"launching: {launcher}")
    proc = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(launcher),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        error(f"launcher failed (exit {proc.returncode})")
        if proc.stderr:
            console.print(proc.stderr)
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
        warn("no listening process found on configured port")
        return
    info(f"will kill PIDs: {pids}")
    if not force and not click.confirm("Proceed?", default=True):
        info("aborted")
        return
    for pid in pids:
        try:
            os.kill(pid, 9)
            success(f"killed PID {pid}")
        except OSError as e:
            error(f"failed to kill {pid}: {e}")


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


def _find_server_pids(server_url: str) -> list[int]:
    """Find PIDs whose process listens on the configured port."""
    from urllib.parse import urlparse

    parsed = urlparse(server_url)
    port = parsed.port or 8188
    # Use PowerShell Get-NetTCPConnection (more reliable than netstat parsing on Windows)
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-Command",
        f"Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue "
        "| Select-Object -ExpandProperty OwningProcess",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return []
    pids: list[int] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids
