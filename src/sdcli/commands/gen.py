"""``sd gen`` — generate images via the local ComfyUI server."""
from __future__ import annotations

import json
import random
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import click

from sdcli import config as config_mod
from sdcli import workflow as wf_mod
from sdcli.backends.comfy import ComfyClient, ComfyError
from sdcli.utils.format import console, error, human_size, info, success, warn


def _parse_size(size: str) -> tuple[int, int]:
    sep = "x" if "x" in size else ("X" if "X" in size else "*")
    if sep not in size:
        raise click.BadParameter(f"--size must be WxH (got '{size}')")
    w, h = size.split(sep, 1)
    return int(w), int(h)


def _ensure_server(cfg: config_mod.Config, client: ComfyClient) -> None:
    if client.is_alive():
        return
    if not cfg.auto_start:
        error(f"server not reachable at {cfg.server_url} (and server.auto_start=false)")
        info("start with: sd server start")
        raise click.exceptions.Exit(1)
    info("server not running — starting it (this may take ~30-60s)...")
    from sdcli.commands.server import cmd_start as start_cmd  # local import to avoid cycle
    ctx = click.get_current_context()
    ctx.invoke(start_cmd, wait=True)


def _slug(text: str, *, maxlen: int = 30) -> str:
    keep = []
    for ch in text:
        if ch.isalnum():
            keep.append(ch.lower())
        elif ch in " -_":
            keep.append("-")
        if len("".join(keep)) >= maxlen:
            break
    out = "".join(keep).strip("-")
    return out or "img"


def _filename_prefix(prompt: str) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"sd_{ts}_{_slug(prompt)}"


def _validate_model(client: ComfyClient, model: str) -> str:
    """Confirm `model` is one of the available checkpoints; suggest if not."""
    available = client.list_checkpoints()
    if not available:
        warn("could not list available checkpoints from server (continuing anyway)")
        return model
    if model in available:
        return model
    # try basename-only match
    base_matches = [a for a in available if Path(a).name == model]
    if len(base_matches) == 1:
        return base_matches[0]
    error(f"model '{model}' not found in models/checkpoints")
    info("available checkpoints:")
    for a in available:
        info(f"  - {a}")
    info("download more with: sd models pull <ref>  (see `sd models recommend`)")
    raise click.exceptions.Exit(1)


@click.command(name="gen")
@click.argument("prompt")
@click.option("--ref", "ref_image", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Reference image for img2img (or IP-Adapter when --mode ipadapter).")
@click.option("--mode", type=click.Choice(["txt2img", "img2img", "ipadapter"]), default=None,
              help="Generation mode. Default: txt2img, or img2img when --ref is given.")
@click.option("-m", "--model", help="Checkpoint filename (under models/checkpoints).")
@click.option("-n", "--negative", help="Negative prompt.")
@click.option("-s", "--steps", type=int, help="Sampling steps.")
@click.option("--cfg", "cfg_scale", type=float, help="Classifier-free guidance scale.")
@click.option("--size", help="Image size as WxH (e.g. 1024x1024).")
@click.option("--seed", type=int, help="Random seed (-1 = random).")
@click.option("--batch", type=int, help="Batch size.")
@click.option("--sampler", help="Sampler (euler, dpmpp_2m, ...). See `--samplers` to list.")
@click.option("--scheduler", help="Scheduler (normal, karras, simple, ddim_uniform, ...).")
@click.option("--denoise", type=float, default=0.7, show_default=True,
              help="img2img denoise strength (0.0=keep ref, 1.0=ignore ref).")
@click.option("-o", "--output", type=click.Path(path_type=Path),
              help="Copy result image(s) here. Defaults to ComfyUI output dir.")
@click.option("--workflow", "workflow_path", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Use a custom workflow JSON file instead of bundled templates.")
@click.option("--samplers", is_flag=True, help="List samplers/schedulers from server and exit.")
@click.option("--dry-run", is_flag=True, help="Print resolved workflow JSON and exit (no submit).")
@click.option("--timeout", type=int, default=600, show_default=True,
              help="How long to wait for completion, in seconds.")
def gen_cmd(
    prompt: str,
    ref_image: Optional[Path],
    mode: Optional[str],
    model: Optional[str],
    negative: Optional[str],
    steps: Optional[int],
    cfg_scale: Optional[float],
    size: Optional[str],
    seed: Optional[int],
    batch: Optional[int],
    sampler: Optional[str],
    scheduler: Optional[str],
    denoise: float,
    output: Optional[Path],
    workflow_path: Optional[Path],
    samplers: bool,
    dry_run: bool,
    timeout: int,
) -> None:
    """Generate image(s) from a PROMPT.

    Examples:

      sd gen "a serene mountain at sunrise"

      sd gen "warrior princess" --ref portrait.png

      sd gen "..." -m sd_xl_base_1.0.safetensors --size 1024x1024 -s 30
    """
    cfg = config_mod.load()
    client = ComfyClient(cfg.server_url)

    if samplers:
        _ensure_server(cfg, client)
        sm = client.list_samplers()
        sc = client.list_schedulers()
        console.print("[bold]samplers:[/bold]")
        for x in sm: console.print(f"  {x}")
        console.print("\n[bold]schedulers:[/bold]")
        for x in sc: console.print(f"  {x}")
        return

    # Determine mode
    if mode is None:
        mode = "img2img" if ref_image else "txt2img"
    if mode == "ipadapter":
        error("--mode ipadapter not yet implemented; falling back coming in next release")
        info("for now, use img2img: --mode img2img --ref <image> --denoise 0.5")
        raise click.exceptions.Exit(2)
    if mode == "img2img" and not ref_image:
        raise click.BadParameter("--ref is required for --mode img2img")

    # Resolve params, filling from defaults
    width, height = _parse_size(size or cfg.get("defaults.size", "512x512"))
    params: dict[str, Any] = {
        "prompt": prompt,
        "negative": negative if negative is not None else cfg.get("defaults.negative", ""),
        "model": model or cfg.get("defaults.model", "v1-5-pruned-emaonly.safetensors"),
        "sampler": sampler or cfg.get("defaults.sampler", "euler"),
        "scheduler": scheduler or cfg.get("defaults.scheduler", "normal"),
        "steps": steps if steps is not None else int(cfg.get("defaults.steps", 20)),
        "cfg": cfg_scale if cfg_scale is not None else float(cfg.get("defaults.cfg", 7.0)),
        "seed": seed if seed is not None and seed != -1 else random.randint(0, 2**31 - 1),
        "batch": batch if batch is not None else int(cfg.get("defaults.batch", 1)),
        "width": width,
        "height": height,
        "filename_prefix": _filename_prefix(prompt),
        "denoise": float(denoise),
    }

    # Bring up server if needed
    _ensure_server(cfg, client)

    # Validate model unless explicit workflow file
    if not workflow_path:
        params["model"] = _validate_model(client, params["model"])

    # Upload ref image if needed
    if ref_image is not None:
        info(f"uploading ref image: {ref_image.name}")
        try:
            params["ref_image"] = client.upload_image(ref_image)
        except Exception as e:  # noqa: BLE001
            error(f"upload failed: {e}")
            raise click.exceptions.Exit(1)

    # Load workflow
    if workflow_path:
        with workflow_path.open("r", encoding="utf-8") as fh:
            template = json.load(fh)
    else:
        template = wf_mod.load(mode)

    try:
        rendered = wf_mod.render(template, params)
    except KeyError as e:
        error(f"workflow needs param: {e}")
        raise click.exceptions.Exit(2)

    if dry_run:
        console.print_json(data=rendered)
        return

    # Show summary
    console.rule(f"[bold]{mode}[/bold]  seed={params['seed']}")
    console.print(f"prompt: {prompt}")
    console.print(f"model: {params['model']}  size: {width}x{height}  steps: {params['steps']}  cfg: {params['cfg']}")
    if mode == "img2img":
        console.print(f"ref: {ref_image}  denoise: {params['denoise']}")

    # Submit
    try:
        prompt_id = client.submit(rendered)
    except ComfyError as e:
        error(str(e))
        raise click.exceptions.Exit(1)
    info(f"submitted ({prompt_id[:8]}...) — waiting...")

    start = time.time()
    try:
        result = client.wait(prompt_id, timeout=float(timeout))
    except ComfyError as e:
        error(str(e))
        raise click.exceptions.Exit(1)

    elapsed = time.time() - start
    if result.status == "error":
        error(f"server reported error: {result.error}")
        raise click.exceptions.Exit(1)

    if not result.images:
        warn("server reported success but no images returned")
        return

    # Materialise
    saved: list[Path] = []
    output_dir = cfg.output_dir
    for img in result.images:
        src = output_dir / img["subfolder"] / img["filename"] if img["subfolder"] else output_dir / img["filename"]
        if not src.exists():
            # fall back to /view download
            try:
                data = client.fetch_image(img["filename"], img["subfolder"], img["type"])
                src.parent.mkdir(parents=True, exist_ok=True)
                src.write_bytes(data)
            except Exception as e:  # noqa: BLE001
                warn(f"could not retrieve {img['filename']}: {e}")
                continue
        saved.append(src)

    # Optionally copy to a user-chosen path
    if output:
        output = Path(output)
        if output.is_dir() or str(output).endswith(("/", "\\")):
            output.mkdir(parents=True, exist_ok=True)
            for src in saved:
                shutil.copy2(src, output / src.name)
                console.print(f"  -> {output / src.name}")
        else:
            # single-file output, only meaningful for batch=1
            if len(saved) > 1:
                output.parent.mkdir(parents=True, exist_ok=True)
                for i, src in enumerate(saved):
                    name = output.with_suffix("").name + f"_{i:02d}" + (output.suffix or ".png")
                    shutil.copy2(src, output.parent / name)
                    console.print(f"  -> {output.parent / name}")
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(saved[0], output)
                console.print(f"  -> {output}")

    success(f"done in {elapsed:.1f}s")
    for p in saved:
        console.print(f"  [bold]{p}[/bold]   [dim]{human_size(p.stat().st_size)}[/dim]")
