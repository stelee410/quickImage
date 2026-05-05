"""``sd config`` — view and edit the CLI config file."""
from __future__ import annotations

import os
import subprocess
import sys

import click
from rich.syntax import Syntax

from sdcli import config as config_mod
from sdcli.utils.format import console, error, info, success


@click.group(name="config", invoke_without_command=True)
@click.pass_context
def config_cmd(ctx: click.Context) -> None:
    """View or edit the CLI config file."""
    if ctx.invoked_subcommand is None:
        # `sd config` with no args = show
        ctx.invoke(cmd_show)


@config_cmd.command(name="show")
def cmd_show() -> None:
    """Print the current config."""
    cfg = config_mod.load()
    console.print(f"[dim]{cfg.path}[/dim]")
    text = cfg.path.read_text(encoding="utf-8")
    console.print(Syntax(text, "toml", line_numbers=False))


@config_cmd.command(name="path")
def cmd_path() -> None:
    """Print the config file path (useful for scripts)."""
    print(config_mod.CONFIG_PATH)


@config_cmd.command(name="get")
@click.argument("key")
def cmd_get(key: str) -> None:
    """Get one config value (dotted path, e.g. ``defaults.steps``)."""
    cfg = config_mod.load()
    value = cfg.get(key, None)
    if value is None:
        error(f"key not set: {key}")
        raise click.exceptions.Exit(1)
    print(value)


@config_cmd.command(name="set")
@click.argument("key")
@click.argument("value")
def cmd_set(key: str, value: str) -> None:
    """Set one config value (dotted path)."""
    cfg = config_mod.load()
    cfg.set(key, value)
    cfg.save()
    success(f"{key} = {cfg.get(key)}")


@config_cmd.command(name="reset")
@click.option("--yes", is_flag=True, help="Don't prompt for confirmation.")
def cmd_reset(yes: bool) -> None:
    """Restore the default config (overwrites your edits)."""
    if not yes and not click.confirm("Overwrite config with defaults?", default=False):
        info("aborted")
        return
    config_mod.reset()
    success(f"reset {config_mod.CONFIG_PATH}")


@config_cmd.command(name="edit")
def cmd_edit() -> None:
    """Open the config in your editor (``$EDITOR``, fall back to notepad on Windows)."""
    cfg = config_mod.load()
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        editor = "notepad" if sys.platform == "win32" else "vi"
    info(f"opening {cfg.path} with {editor}")
    subprocess.run([editor, str(cfg.path)], check=False)
