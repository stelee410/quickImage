# quickImage — `sd` CLI

A production-grade command-line interface for local Stable Diffusion image
generation, sitting on top of a [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
backend. Built for AMD Strix Halo (Ryzen AI Max+ 395, gfx1151) on Windows
running [comfyui-rocm](https://github.com/patientx-cfz/comfyui-rocm) — but
the CLI talks to ComfyUI over HTTP so any ComfyUI install works.

```sh
sd gen "a serene mountain at sunrise"            # text-to-image
sd gen "warrior princess" --ref portrait.png     # image-to-image
sd models pull --recommend realvis-xl            # grab a curated model
sd info                                          # one-shot system check
```

---

## Features

- **One-line image generation** — `sd gen "prompt"` and you get a PNG.
- **Reference-image (img2img)** — `--ref some.png --denoise 0.6`.
- **Model management** — list, pull (HuggingFace / CivitAI / direct URL),
  remove, verify SHA-256, curated recommendations.
- **Server lifecycle** — `sd server start|stop|status|logs|restart`,
  idempotent and detached so the server keeps running across terminals.
- **Config-driven defaults** — model, sampler, steps, size, negative prompt
  all live in `%APPDATA%\sdcli\config.toml`.
- **Fast downloads** — uses `aria2c` with 16 parallel connections (~10×
  faster than single-stream from GitHub / HF).
- **No new GPU stack** — reuses the ROCm + PyTorch already living in
  `D:\comfyui-rocm\python_env`.

## Requirements

- Windows 11 (it shells out to PowerShell for a few host-OS calls).
- A working `comfyui-rocm` install at `D:\comfyui-rocm` (or change paths
  via `sd config set`).
- Python ≥ 3.11. The default install uses the Python 3.12 portable env
  bundled with `comfyui-rocm` — no separate Python needed.
- `aria2c` on PATH (recommended): `winget install aria2.aria2`.
  Without it, downloads fall back to single-stream `requests`.

## Install

```powershell
# 1. clone
git clone https://github.com/stelee410/quickImage.git D:\dev\quickImage
cd D:\dev\quickImage

# 2. editable install into the comfyui-rocm python env
D:\comfyui-rocm\python_env\python.exe -m pip install -e . --no-deps

# 3. add the cmd wrapper to your User PATH (only needs to run once)
powershell -ExecutionPolicy Bypass -File .\bin\add-to-path.ps1

# 4. open a fresh terminal so PATH is reloaded, then:
sd --version
sd info
```

The first run of any `sd` command auto-creates the config file at
`%APPDATA%\sdcli\config.toml` with sensible defaults. Edit with
`sd config edit` or change individual keys with `sd config set`.

## Command reference

### `sd gen` — generate images

```sh
sd gen "PROMPT" [options]
```

| option              | meaning                                                            |
| ------------------- | ------------------------------------------------------------------ |
| `--ref FILE`        | reference image (defaults to img2img mode)                         |
| `--mode MODE`       | `txt2img` / `img2img` / `ipadapter` (auto-detected from `--ref`)   |
| `-m, --model NAME`  | checkpoint filename (under `models/checkpoints/`)                  |
| `-s, --steps N`     | sampling steps                                                     |
| `--cfg N`           | classifier-free guidance scale                                     |
| `--size WxH`        | output resolution (e.g. `1024x1024`)                               |
| `--seed N`          | random seed (use `-1` for random)                                  |
| `--batch N`         | batch size                                                         |
| `--sampler NAME`    | sampler (use `--samplers` to list)                                 |
| `--scheduler NAME`  | scheduler                                                          |
| `--denoise N`       | img2img denoise strength (0.0–1.0)                                 |
| `-n, --negative S`  | negative prompt                                                    |
| `-o, --output PATH` | also copy the result to this path                                  |
| `--workflow FILE`   | use a custom ComfyUI workflow JSON instead of bundled templates    |
| `--dry-run`         | print resolved workflow JSON and exit (debug)                      |
| `--samplers`        | list samplers/schedulers from server and exit                      |
| `--timeout N`       | seconds to wait for completion (default 600)                       |

Examples:

```sh
sd gen "a serene mountain at sunrise"
sd gen "warrior princess in armor" --ref portrait.png --denoise 0.55
sd gen "an oil-painting of a fox" -m sd_xl_base_1.0.safetensors --size 1024x1024 -s 30
sd gen "..." --batch 4 --seed 42 -o D:\out\hero.png
sd gen "..." --workflow my-pipeline.json
```

### `sd models` — manage local model files

```sh
sd models                       # list all (default action)
sd models list -t lora          # filter by type
sd models info <name>           # show metadata
sd models rm <name>             # delete a file
sd models verify [name]         # SHA-256 one or all files
sd models recommend             # curated download list
sd models pull <REF>            # download a model
sd models pull --recommend KEY  # download from the curated list
```

`<REF>` formats:

| ref                            | meaning                                          |
| ------------------------------ | ------------------------------------------------ |
| `hf:owner/repo`                | HuggingFace repo, auto-pick best file            |
| `hf:owner/repo:filename`       | HF, specific file                                |
| `civitai:<modelVersionId>`     | CivitAI version (recommended — exact)            |
| `civitai:model:<modelId>`      | CivitAI model, latest version                    |
| `https://...`                  | direct URL                                       |

Tokens for gated downloads:

```sh
sd config set download.civitai_token <YOUR_TOKEN>
sd config set download.huggingface_token <YOUR_TOKEN>
```

### `sd server` — manage ComfyUI lifecycle

```sh
sd server status         # is it up? show stats
sd server start          # start detached (idempotent)
sd server stop           # kill the listening process
sd server restart
sd server logs -f        # follow stdout/stderr
```

### `sd info` — diagnostics

```sh
sd info
```

Reports config path, server health (PyTorch / ComfyUI versions, GPU,
VRAM), model counts by type, recent outputs.

### `sd config` — read/write config

```sh
sd config                       # show
sd config get defaults.steps    # one value
sd config set defaults.steps 30
sd config edit                  # open in $EDITOR (notepad on Windows)
sd config reset                 # restore defaults
sd config path                  # print config path
```

## Recommended models

Run `sd models recommend` for the live list. As of v0.1.0 these are
preconfigured (all freely public unless tagged "needs token"):

| key            | model                         | size  | use case                            |
| -------------- | ----------------------------- | ----- | ----------------------------------- |
| `sd15`         | Stable Diffusion 1.5 base     | 4 GB  | smallest baseline, fast tests       |
| `sdxl`         | Stable Diffusion XL 1.0 base  | 7 GB  | official SDXL                       |
| `sdxl-refiner` | SDXL Refiner                  | 6 GB  | optional 2-stage detail enhancer    |
| `realvis-xl`   | RealVisXL V5.0 (fp16)         | 7 GB  | photorealistic, no content filters  |
| `flux-schnell` | Flux.1 Schnell (Apache 2.0)   | 24 GB | high quality, license-unrestricted  |
| `flux-dev`     | Flux.1 Dev (gated)            | 24 GB | best Flux, requires HF token        |
| `sdxl-vae`     | SDXL VAE fp16-fix             | 320 MB| color/contrast fix for SDXL         |

For more diverse or NSFW-capable models the easiest path is CivitAI:
generate an API token at <https://civitai.com/user/account>, then

```sh
sd config set download.civitai_token <TOKEN>
sd models pull civitai:<modelVersionId>
```

## Architecture (short)

```
sd  --(HTTP API)-->  ComfyUI server  --(ROCm)-->  AMD Radeon 8060S
↑                          ↑
TOML config        workflow JSON templates parameterised at runtime
```

Workflow templates live at `src/sdcli/workflows/`. The `workflow.py`
module substitutes `${name}` / `${name:int}` placeholders before
submission. To customise generation pipelines, copy a template, modify,
and pass via `sd gen --workflow <file>`.

## Troubleshooting

**`sd server status` says unreachable.**
The server isn't running. `sd server start` (or check `sd server logs`).

**`sd gen` says "model not found".**
List installed checkpoints with `sd models list` or download with
`sd models pull`. Make sure the filename matches exactly.

**`sd models pull civitai:...` rejects with "needs token".**
Generate a token at <https://civitai.com/user/account> (API Keys) and
`sd config set download.civitai_token <TOKEN>`.

**Downloads are slow.**
Install aria2: `winget install aria2.aria2`. The CLI auto-detects it.
With aria2 present, expect ~3–5 MB/s vs ~500 KB/s without.

**Encoding errors on Windows console.**
The CLI sets `PYTHONIOENCODING=utf-8` via `bin/sd.cmd`. If you call
`python -m sdcli` directly from a non-UTF-8 codepage shell, set the
env var manually first.

## Roadmap

- [ ] `--mode ipadapter` — auto-install ComfyUI-IPAdapter custom node
  and SDXL/SD15 IP-Adapter models, then run reference-image generation
  preserving identity better than img2img.
- [ ] LoRA chain (`--lora name:weight,other:weight`).
- [ ] ControlNet preprocessors (canny, depth, openpose).
- [ ] Generation history (`sd history` / `sd replay`).
- [ ] Tab-completion for fish/zsh/PowerShell.

## License

MIT.
