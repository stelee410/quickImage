#!/usr/bin/env bash
# Start ComfyUI detached and write its PID to a file.
#
# Reads the same config sdcli does:
#   - server.install_dir   (directory containing main.py)
#   - server.python        (interpreter to run main.py with)
#   - server.log_path      (stdout+stderr go here)
#   - server.pid_path      (PID is written here)
#
# Usage: ./start-detached.sh [extra-args-passed-to-main.py]
#
# This is the Unix counterpart to start-detached.ps1. It is meant to be run
# either by `sd server start` (via subprocess) or by hand.
set -e

# --- locate sd -------------------------------------------------------------
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sd="$here/sd"
if [ ! -x "$sd" ]; then
    echo "[start-detached] cannot find $sd; run setup.sh first." >&2
    exit 2
fi

# --- read config via sd ----------------------------------------------------
install_dir="$("$sd" config get server.install_dir 2>/dev/null || true)"
python_bin="$("$sd" config get server.python 2>/dev/null || true)"
log_path="$("$sd" config get server.log_path 2>/dev/null || true)"
pid_path="$("$sd" config get server.pid_path 2>/dev/null || true)"

if [ -z "$install_dir" ] || [ ! -d "$install_dir" ]; then
    echo "[start-detached] server.install_dir not set or missing: '$install_dir'" >&2
    exit 2
fi
if [ ! -f "$install_dir/main.py" ]; then
    echo "[start-detached] $install_dir/main.py not found" >&2
    exit 2
fi
if [ -z "$python_bin" ] || [ ! -x "$python_bin" ]; then
    if command -v python3 >/dev/null 2>&1; then
        python_bin="$(command -v python3)"
    else
        echo "[start-detached] server.python not set and no python3 on PATH" >&2
        exit 2
    fi
fi
[ -z "$log_path" ] && log_path="$HOME/.local/state/sdcli/comfyui.log"
[ -z "$pid_path" ] && pid_path="$HOME/.local/state/sdcli/comfyui.pid"

mkdir -p "$(dirname "$log_path")" "$(dirname "$pid_path")"

# --- launch ----------------------------------------------------------------
echo "[start-detached] cwd:    $install_dir"
echo "[start-detached] python: $python_bin"
echo "[start-detached] log:    $log_path"
echo "[start-detached] pid:    $pid_path"

cd "$install_dir"
nohup "$python_bin" main.py "$@" >>"$log_path" 2>&1 &
pid=$!
echo "$pid" >"$pid_path"
echo "[start-detached] pid $pid"
disown "$pid" 2>/dev/null || true
