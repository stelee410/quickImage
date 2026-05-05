"""``sd info`` — system & install diagnostics."""
from __future__ import annotations

from pathlib import Path

import click
from rich.table import Table

from sdcli import config as config_mod
from sdcli.backends.comfy import ComfyClient
from sdcli.utils.format import console, human_size, info as msg_info, warn
from sdcli.utils.io import walk_models


@click.command(name="info")
def info_cmd() -> None:
    """Show system info: server status, GPU, install paths, model summary."""
    cfg = config_mod.load()
    console.rule("[bold]quickImage")
    console.print(f"config: [dim]{cfg.path}[/dim]")
    console.print(f"server URL: {cfg.server_url}")
    console.print(f"install dir: {cfg.install_dir}")
    console.print(f"models dir: {cfg.models_dir}")
    console.print(f"output dir: {cfg.output_dir}")

    console.rule("[bold]server")
    client = ComfyClient(cfg.server_url)
    if not client.is_alive():
        warn("server not reachable; start with `sd server start`")
    else:
        try:
            stats = client.system_stats()
        except Exception as e:  # noqa: BLE001
            warn(f"server reachable but /system_stats failed: {e}")
        else:
            sys_ = stats.get("system", {}) or {}
            devs = stats.get("devices", []) or []
            console.print(f"comfyui: [bold]{sys_.get('comfyui_version','?')}[/bold]")
            console.print(f"pytorch: {sys_.get('pytorch_version','?')}")
            console.print(f"python:  {sys_.get('python_version','?').splitlines()[0]}")
            for d in devs:
                vt = d.get("vram_total", 0) / 2**30
                vf = d.get("vram_free", 0) / 2**30
                console.print(f"device:  {d.get('name','?')} — VRAM {vf:.1f}/{vt:.1f} GiB free")

    console.rule("[bold]models")
    counts: dict[str, list] = {}
    total = 0
    for kind, path in walk_models(cfg.models_dir):
        counts.setdefault(kind, []).append(path)
        total += 1
    if total == 0:
        msg_info("no models found")
    else:
        t = Table(show_header=True, header_style="bold")
        t.add_column("type")
        t.add_column("count", justify="right")
        t.add_column("size", justify="right")
        for kind in sorted(counts):
            files = counts[kind]
            size = sum(p.stat().st_size for p in files)
            t.add_row(kind, str(len(files)), human_size(size))
        console.print(t)

    console.rule("[bold]paths summary")
    console.print(f"recent outputs ({cfg.output_dir}):")
    if cfg.output_dir.exists():
        recent = sorted(cfg.output_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
        if not recent:
            console.print("  [dim](none yet)[/dim]")
        for p in recent:
            console.print(f"  {p.name}  [dim]{human_size(p.stat().st_size)}[/dim]")
    else:
        console.print("  [dim](output dir does not exist)[/dim]")
