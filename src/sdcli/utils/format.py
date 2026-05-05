"""Shared rich console helpers.

Uses ASCII-only glyphs so output is safe on Windows consoles in legacy
codepages (GBK, etc.) where the codepage cannot encode unicode bullets.
"""
from __future__ import annotations

import os
import sys

from rich.console import Console

# Force UTF-8 stdout where supported so rich's own internal text doesn't trip on
# legacy codepages.  Best-effort — older `cmd.exe` may still fall back to GBK.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

console = Console()
err_console = Console(stderr=True)


def info(msg: str) -> None:
    console.print(f"[cyan]*[/cyan] {msg}")


def success(msg: str) -> None:
    console.print(f"[green][OK][/green] {msg}")


def warn(msg: str) -> None:
    err_console.print(f"[yellow][!][/yellow] {msg}")


def error(msg: str) -> None:
    err_console.print(f"[red][x][/red] {msg}")


def human_size(num: float) -> str:
    """Format bytes as human-readable size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024:
            return f"{num:.1f} {unit}" if unit != "B" else f"{num:.0f} {unit}"
        num /= 1024
    return f"{num:.1f} PB"
