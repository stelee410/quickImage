#!/usr/bin/env bash
# quickImage setup for macOS / Linux.
#
# What this does (idempotent — safe to re-run):
#   1. Verify python>=3.11 and create .venv at the repo root.
#   2. pip install -e . into that venv.
#   3. Make sure aria2c is available (best-effort; warn on Linux).
#   4. Optionally clone ComfyUI into ~/ComfyUI and create its own .venv with
#      torch (CUDA on Linux+NVIDIA, MPS on macOS).
#   5. Write the initial config so paths point at this user's machine.
#   6. Append <repo>/bin to PATH in the user's shell rc, if not already there.
#   7. Run `sd info` as a smoke test.

set -e

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo_root"

GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
say()  { printf "${CYAN}[setup]${NC} %s\n" "$*"; }
ok()   { printf "${GREEN}[ ok ]${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}[warn]${NC} %s\n" "$*"; }
die()  { printf "${RED}[fail]${NC} %s\n" "$*" >&2; exit 1; }
ask_yn() {
    # ask_yn "prompt" default("y"|"n"); returns 0 for yes, 1 for no
    local prompt="$1" default="${2:-n}" reply
    local hint="[y/N]"; [ "$default" = "y" ] && hint="[Y/n]"
    if [ ! -t 0 ]; then echo "$prompt $hint -> non-interactive, using default ($default)"; [ "$default" = "y" ]; return; fi
    read -r -p "$prompt $hint " reply || reply=""
    reply="${reply:-$default}"
    case "$reply" in [yY]*) return 0;; *) return 1;; esac
}

uname_s="$(uname -s)"
case "$uname_s" in
    Darwin) os="macos" ;;
    Linux)  os="linux" ;;
    *)      die "unsupported OS: $uname_s (this script is for macOS / Linux). Use setup.bat on Windows." ;;
esac
say "detected OS: $os"

# --- 1. Python >= 3.11 -----------------------------------------------------
py_bin=""
for cand in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        v="$("$cand" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo 0)"
        major="${v%%.*}"; minor="${v##*.}"
        if [ "$major" = "3" ] && [ "$minor" -ge 11 ]; then
            py_bin="$(command -v "$cand")"; break
        fi
    fi
done
[ -z "$py_bin" ] && die "need Python >= 3.11. Install it (e.g. 'brew install python@3.12' on macOS) and re-run."
ok "python: $py_bin ($($py_bin --version))"

# --- 2. venv + editable install --------------------------------------------
if [ ! -d "$repo_root/.venv" ]; then
    say "creating venv at $repo_root/.venv"
    "$py_bin" -m venv "$repo_root/.venv"
fi
# shellcheck disable=SC1091
. "$repo_root/.venv/bin/activate"
pip install --quiet --upgrade pip
say "installing sdcli (editable)"
pip install --quiet -e .
ok "sdcli installed in $repo_root/.venv"

# --- 3. aria2c (optional but recommended) ----------------------------------
if command -v aria2c >/dev/null 2>&1; then
    ok "aria2c: $(command -v aria2c)"
else
    warn "aria2c not found — model downloads will fall back to single-stream and be slower."
    if [ "$os" = "macos" ] && command -v brew >/dev/null 2>&1; then
        if ask_yn "Install aria2 via Homebrew now?" y; then
            brew install aria2
        fi
    elif [ "$os" = "linux" ]; then
        if command -v apt-get >/dev/null 2>&1; then
            warn "on Debian/Ubuntu: sudo apt-get install -y aria2"
        elif command -v dnf >/dev/null 2>&1; then
            warn "on Fedora: sudo dnf install -y aria2"
        elif command -v pacman >/dev/null 2>&1; then
            warn "on Arch: sudo pacman -S aria2"
        fi
    fi
fi

# --- 4. ComfyUI install ----------------------------------------------------
default_comfy="$HOME/ComfyUI"
read -r -p "ComfyUI install directory [$default_comfy]: " comfy_dir || comfy_dir=""
comfy_dir="${comfy_dir:-$default_comfy}"
# Expand ~
comfy_dir="${comfy_dir/#\~/$HOME}"

if [ -f "$comfy_dir/main.py" ]; then
    ok "found existing ComfyUI at $comfy_dir"
else
    if ask_yn "ComfyUI not found at $comfy_dir. Clone it from GitHub?" y; then
        command -v git >/dev/null 2>&1 || die "git not on PATH"
        git clone https://github.com/comfyanonymous/ComfyUI.git "$comfy_dir"
        ok "cloned ComfyUI to $comfy_dir"
    else
        warn "skipping ComfyUI clone — you'll need to set server.install_dir later."
    fi
fi

# Create ComfyUI's own venv and install requirements
comfy_python=""
if [ -f "$comfy_dir/main.py" ]; then
    if [ ! -d "$comfy_dir/.venv" ]; then
        if ask_yn "Create a venv at $comfy_dir/.venv and install ComfyUI requirements?" y; then
            "$py_bin" -m venv "$comfy_dir/.venv"
            # shellcheck disable=SC1091
            . "$comfy_dir/.venv/bin/activate"
            pip install --quiet --upgrade pip
            say "installing torch (this can take a few minutes)"
            if [ "$os" = "macos" ]; then
                # MPS comes with the standard wheel on Apple Silicon
                pip install --quiet torch torchvision torchaudio
            else
                # Linux: assume CUDA. Users on AMD/CPU should edit afterwards.
                pip install --quiet torch torchvision torchaudio
            fi
            say "installing ComfyUI requirements"
            pip install --quiet -r "$comfy_dir/requirements.txt"
            deactivate
            # Re-activate sdcli venv for the rest of the script
            # shellcheck disable=SC1091
            . "$repo_root/.venv/bin/activate"
            ok "ComfyUI venv ready"
        fi
    else
        ok "ComfyUI venv already exists at $comfy_dir/.venv"
    fi
    if [ -x "$comfy_dir/.venv/bin/python" ]; then
        comfy_python="$comfy_dir/.venv/bin/python"
    fi
fi

# --- 5. Write initial config ----------------------------------------------
say "writing initial config"
sd_bin="$repo_root/bin/sd"
chmod +x "$sd_bin" "$repo_root/bin/start-detached.sh" 2>/dev/null || true

# Touch config (creates with defaults if absent)
"$sd_bin" config path >/dev/null
config_path="$("$sd_bin" config path)"
ok "config: $config_path"

if [ -f "$comfy_dir/main.py" ]; then
    "$sd_bin" config set server.install_dir "$comfy_dir" >/dev/null
    "$sd_bin" config set paths.models_dir "$comfy_dir/models" >/dev/null
    "$sd_bin" config set paths.output_dir "$comfy_dir/output" >/dev/null
fi
if [ -n "$comfy_python" ]; then
    "$sd_bin" config set server.python "$comfy_python" >/dev/null
fi
"$sd_bin" config set server.launcher "$repo_root/bin/start-detached.sh" >/dev/null

# --- 6. PATH ---------------------------------------------------------------
shell_name="$(basename "${SHELL:-/bin/bash}")"
case "$shell_name" in
    zsh)  rc="$HOME/.zshrc" ;;
    bash) rc="$HOME/.bashrc"; [ "$os" = "macos" ] && rc="$HOME/.bash_profile" ;;
    fish) rc="$HOME/.config/fish/config.fish" ;;
    *)    rc="$HOME/.profile" ;;
esac
line="export PATH=\"$repo_root/bin:\$PATH\"  # quickImage"
[ "$shell_name" = "fish" ] && line="set -gx PATH $repo_root/bin \$PATH  # quickImage"

if [ -f "$rc" ] && grep -Fq "$repo_root/bin" "$rc"; then
    ok "PATH already includes $repo_root/bin in $rc"
else
    if ask_yn "Append '$repo_root/bin' to PATH in $rc?" y; then
        mkdir -p "$(dirname "$rc")"
        printf '\n%s\n' "$line" >>"$rc"
        ok "added to $rc — open a new terminal for it to take effect"
    else
        warn "skipped PATH update; run '$sd_bin' with the full path"
    fi
fi

# --- 7. smoke test ---------------------------------------------------------
say "running 'sd info' as a smoke test"
"$sd_bin" info || true

ok "setup complete."
echo
echo "Next steps:"
echo "  - Open a new terminal (so PATH picks up)."
echo "  - sd server start    # boot ComfyUI"
echo "  - sd models pull --recommend sdxl    # grab a base checkpoint"
echo "  - sd gen \"a serene mountain at sunrise\""
