"""Config file management.

Config lives at a per-platform location (see ``platform_utils.config_dir``).
First call seeds it with defaults that point at a sensible local ComfyUI
install for the current OS:

- Windows: ``D:\\comfyui-rocm`` with the bundled portable Python.
- macOS / Linux: ``~/ComfyUI`` with a ``.venv`` Python or system ``python3``.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sdcli import platform_utils as plat

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore


CONFIG_DIR = plat.config_dir()
CONFIG_PATH = CONFIG_DIR / "config.toml"
HISTORY_PATH = CONFIG_DIR / "history.jsonl"


# --- Default config ---------------------------------------------------------

def _default_config_toml() -> str:
    """Build a default config.toml string using platform-specific paths."""
    install = plat.default_install_dir()
    python = plat.default_python()
    launcher = plat.default_launcher()
    log_path = plat.default_log_path()
    pid_path = plat.default_pid_path()
    models = install / "models"
    output = install / "output"

    # TOML basic strings need "\" doubled. Path objects render with forward
    # slashes on Unix and backslashes on Windows; we just escape backslashes.
    def q(p: Any) -> str:
        return '"' + str(p).replace("\\", "\\\\") + '"'

    return f"""\
# quickImage CLI config
# Edit with `sd config edit` or change individual keys with `sd config set k.path v`.

[server]
# ComfyUI HTTP API URL
url = "http://127.0.0.1:8188"
# ComfyUI install directory (the one containing main.py)
install_dir = {q(install)}
# Python interpreter that runs ComfyUI
python = {q(python)}
# When set, `sd gen` will auto-start the server if it is not already running
auto_start = true
# Server stdout / stderr log
log_path = {q(log_path)}
# PID file written by the launcher (Unix). Unused on Windows.
pid_path = {q(pid_path)}
# Optional detached launcher script. If empty, `sd server start` uses a
# built-in fallback (PowerShell on Windows, nohup on Unix).
launcher = {q(launcher)}
# Seconds to wait for the server to become responsive after start
start_timeout = 180

[paths]
# ComfyUI models root (contains checkpoints/, loras/, vae/, ...)
models_dir = {q(models)}
# Where ComfyUI saves output images
output_dir = {q(output)}
# Where `sd gen` copies its results to (set to "" to leave them only in output_dir)
copy_to_dir = ""

[defaults]
model = "v1-5-pruned-emaonly.safetensors"
sampler = "euler"
scheduler = "normal"
steps = 20
cfg = 7.0
size = "512x512"
negative = "blurry, low quality, distorted, deformed"
batch = 1

[download]
parallel_connections = 16
# Optional API tokens
huggingface_token = ""
civitai_token = ""
"""


# --- Loading / saving -------------------------------------------------------

@dataclass
class Config:
    raw: dict[str, Any] = field(default_factory=dict)
    path: Path = CONFIG_PATH

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self.raw
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = _coerce(value)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(_to_toml(self.raw), encoding="utf-8")

    # Convenience accessors with proper types

    @property
    def server_url(self) -> str:
        return self.get("server.url", "http://127.0.0.1:8188")

    @property
    def install_dir(self) -> Path:
        return Path(self.get("server.install_dir", str(plat.default_install_dir())))

    @property
    def server_python(self) -> str:
        return self.get("server.python", plat.default_python())

    @property
    def models_dir(self) -> Path:
        return Path(self.get("paths.models_dir", str(self.install_dir / "models")))

    @property
    def output_dir(self) -> Path:
        return Path(self.get("paths.output_dir", str(self.install_dir / "output")))

    @property
    def auto_start(self) -> bool:
        return bool(self.get("server.auto_start", True))


def _coerce(value: Any) -> Any:
    """Coerce string values to bool/int/float when obvious (for ``sd config set``)."""
    if not isinstance(value, str):
        return value
    low = value.strip().lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _to_toml(data: dict[str, Any]) -> str:
    """Minimal TOML writer (avoid extra dep). Supports nested tables and basic scalars."""
    lines: list[str] = []

    def emit_value(v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, str):
            escaped = v.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        if isinstance(v, list):
            return "[" + ", ".join(emit_value(x) for x in v) + "]"
        # fallback
        escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    # Emit root scalars first (none expected, but safe)
    for k, v in data.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {emit_value(v)}")
    if lines:
        lines.append("")

    for table, body in data.items():
        if not isinstance(body, dict):
            continue
        lines.append(f"[{table}]")
        for k, v in body.items():
            lines.append(f"{k} = {emit_value(v)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def load(create_if_missing: bool = True) -> Config:
    if not CONFIG_PATH.exists():
        if not create_if_missing:
            return Config(raw={}, path=CONFIG_PATH)
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(_default_config_toml(), encoding="utf-8")
    with CONFIG_PATH.open("rb") as fh:
        raw = tomllib.load(fh)
    return Config(raw=raw, path=CONFIG_PATH)


def reset() -> Config:
    """Replace config with defaults. Returns the freshly written Config."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(_default_config_toml(), encoding="utf-8")
    return load(create_if_missing=False)
