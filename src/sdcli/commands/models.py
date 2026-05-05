"""``sd models`` — list, pull, remove, inspect models."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import click
from rich.table import Table

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from importlib import resources

from sdcli import config as config_mod
from sdcli.sources import civitai as civitai_src
from sdcli.sources import huggingface as hf_src
from sdcli.utils import download as download_util
from sdcli.utils.format import console, error, human_size, info, success, warn
from sdcli.utils.io import sha256_file, walk_models


@click.group(name="models", invoke_without_command=True)
@click.pass_context
def models_cmd(ctx: click.Context) -> None:
    """Manage local models (checkpoints, loras, vae, ...)."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(cmd_list, type=None)


@models_cmd.command(name="list")
@click.option(
    "-t", "--type", "type_",
    type=click.Choice(["checkpoint", "checkpoints", "lora", "loras", "vae", "controlnet", "embeddings",
                       "upscale_models", "diffusion_models", "clip", "clip_vision", "all"]),
    default=None,
    help="Filter by model type.",
)
def cmd_list(type_: Optional[str]) -> None:
    """List installed models grouped by type."""
    cfg = config_mod.load()
    by_type: dict[str, list[Path]] = {}
    for kind, path in walk_models(cfg.models_dir):
        by_type.setdefault(kind, []).append(path)

    if type_ and type_ != "all":
        # Normalise singular vs plural
        norm = {"checkpoint": "checkpoints", "lora": "loras"}.get(type_, type_)
        by_type = {norm: by_type.get(norm, [])}

    if not any(by_type.values()):
        warn("no models found")
        info(f"models dir: {cfg.models_dir}")
        info("use `sd models pull <ref>` to download some")
        return

    for kind in sorted(by_type):
        files = by_type[kind]
        if not files:
            continue
        console.rule(f"[bold]{kind} ({len(files)})")
        t = Table(show_header=True, header_style="bold", padding=(0, 2))
        t.add_column("filename")
        t.add_column("size", justify="right")
        for f in sorted(files):
            t.add_row(f.relative_to(cfg.models_dir / kind).as_posix(), human_size(f.stat().st_size))
        console.print(t)


@models_cmd.command(name="info")
@click.argument("name")
def cmd_info(name: str) -> None:
    """Show metadata for one model file (looked up by basename)."""
    cfg = config_mod.load()
    matches = [p for kind, p in walk_models(cfg.models_dir) if p.name == name or p.stem == name]
    if not matches:
        error(f"no model named '{name}' under {cfg.models_dir}")
        raise click.exceptions.Exit(1)
    if len(matches) > 1:
        warn(f"{len(matches)} matches; showing first: {matches[0]}")
    p = matches[0]
    st = p.stat()
    console.print(f"path:    {p}")
    console.print(f"type:    {p.parent.relative_to(cfg.models_dir)}")
    console.print(f"size:    {human_size(st.st_size)} ({st.st_size:,} bytes)")
    console.print(f"mtime:   {st.st_mtime}")


@models_cmd.command(name="rm")
@click.argument("name")
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def cmd_rm(name: str, yes: bool) -> None:
    """Delete a model file (looked up by basename)."""
    cfg = config_mod.load()
    matches = [p for _, p in walk_models(cfg.models_dir) if p.name == name or p.stem == name]
    if not matches:
        error(f"no model named '{name}'")
        raise click.exceptions.Exit(1)
    if len(matches) > 1:
        error(f"{len(matches)} matches — pass full filename to disambiguate:")
        for m in matches:
            error(f"  {m.name}")
        raise click.exceptions.Exit(1)
    p = matches[0]
    info(f"will delete: {p}  ({human_size(p.stat().st_size)})")
    if not yes and not click.confirm("proceed?", default=False):
        info("aborted")
        return
    p.unlink()
    success(f"deleted {p.name}")


@models_cmd.command(name="verify")
@click.argument("name", required=False)
def cmd_verify(name: Optional[str]) -> None:
    """Compute sha256 for one or all model files."""
    cfg = config_mod.load()
    targets: list[Path]
    if name:
        targets = [p for _, p in walk_models(cfg.models_dir) if p.name == name or p.stem == name]
        if not targets:
            error(f"no model named '{name}'")
            raise click.exceptions.Exit(1)
    else:
        targets = [p for _, p in walk_models(cfg.models_dir)]
    for p in targets:
        info(f"hashing {p.name}...")
        digest = sha256_file(p)
        console.print(f"  [green]{digest}[/green]  {p.name}")


@models_cmd.command(name="recommend")
def cmd_recommend() -> None:
    """List curated model recommendations available via `sd models pull --recommend <key>`."""
    items = _load_recommendations()
    t = Table(show_header=True, header_style="bold")
    t.add_column("key")
    t.add_column("name")
    t.add_column("type")
    t.add_column("size", justify="right")
    t.add_column("notes")
    for it in items:
        notes = it.get("description", "")
        if it.get("requires_token"):
            notes = "[yellow](needs token)[/yellow] " + notes
        size = human_size(int(it.get("size_mb", 0)) * 1024 * 1024)
        t.add_row(it["key"], it["name"], it["type"], size, notes)
    console.print(t)
    info("download with: sd models pull --recommend <key>")


@models_cmd.command(name="pull")
@click.argument("ref", required=False)
@click.option("--recommend", "recommend_key", help="Pull a curated model by key (see `sd models recommend`).")
@click.option("--type", "type_override", help="Override target subdir (checkpoints/loras/vae/...).")
@click.option("--name", "out_name", help="Save as this filename instead of source default.")
@click.option("--force", is_flag=True, help="Overwrite if exists.")
def cmd_pull(
    ref: Optional[str],
    recommend_key: Optional[str],
    type_override: Optional[str],
    out_name: Optional[str],
    force: bool,
) -> None:
    """Download a model.

    REF formats:

      hf:owner/repo                 — pick best file in repo
      hf:owner/repo:filename        — specific file
      civitai:<modelVersionId>      — specific version (recommended)
      civitai:model:<modelId>       — latest version of model
      <https direct URL>            — download as-is
    """
    cfg = config_mod.load()

    if recommend_key:
        items = _load_recommendations()
        match = next((i for i in items if i["key"] == recommend_key), None)
        if not match:
            error(f"unknown recommendation key '{recommend_key}'")
            info("see available keys: sd models recommend")
            raise click.exceptions.Exit(1)
        ref = match["source"]
        if not type_override:
            type_override = match["type"]
        if match.get("requires_token") and not _has_hf_token(cfg):
            warn("this model is gated — set huggingface_token first")
            info("  sd config set download.huggingface_token <YOUR_TOKEN>")

    if not ref:
        error("usage: sd models pull <ref>  OR  sd models pull --recommend <key>")
        raise click.exceptions.Exit(2)

    target_dir = _resolve_target_dir(cfg, type_override or "checkpoints")
    target_dir.mkdir(parents=True, exist_ok=True)

    if ref.startswith("hf:") or _looks_like_hf_repo(ref):
        _pull_huggingface(ref, target_dir, cfg, out_name=out_name, force=force)
    elif ref.startswith("civitai:"):
        _pull_civitai(ref, target_dir, cfg, type_override=type_override, out_name=out_name, force=force)
    elif ref.startswith(("http://", "https://")):
        _pull_direct(ref, target_dir, cfg, out_name=out_name, force=force)
    else:
        error(f"don't know how to interpret ref: {ref!r}")
        raise click.exceptions.Exit(2)


# --- helpers ---------------------------------------------------------------

def _load_recommendations() -> list[dict]:
    with resources.files("sdcli.data").joinpath("recommendations.toml").open("rb") as fh:
        data = tomllib.load(fh)
    return data.get("recommend", [])


def _has_hf_token(cfg: config_mod.Config) -> bool:
    return bool(cfg.get("download.huggingface_token") or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN"))


def _hf_token(cfg: config_mod.Config) -> str:
    return cfg.get("download.huggingface_token") or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN") or ""


def _resolve_target_dir(cfg: config_mod.Config, kind: str) -> Path:
    norm = {"checkpoint": "checkpoints", "lora": "loras"}.get(kind, kind)
    return cfg.models_dir / norm


def _looks_like_hf_repo(s: str) -> bool:
    """Detect bare 'owner/repo' strings as HF refs (without the 'hf:' prefix)."""
    return "/" in s and not s.startswith(("http://", "https://", "civitai:"))


def _pull_huggingface(
    ref: str,
    target_dir: Path,
    cfg: config_mod.Config,
    *,
    out_name: Optional[str],
    force: bool,
) -> None:
    parsed = hf_src.HFRef.parse(ref)
    token = _hf_token(cfg)
    if not parsed.filename:
        info(f"listing files in {parsed.repo}...")
        try:
            siblings = hf_src.list_repo_files(parsed.repo, revision=parsed.revision, token=token)
        except Exception as e:  # noqa: BLE001
            error(f"failed to list repo: {e}")
            raise click.exceptions.Exit(1)
        chosen = hf_src.pick_default_filename(siblings)
        if not chosen:
            error("could not auto-pick a file; specify one with hf:repo:filename")
            raise click.exceptions.Exit(1)
        info(f"chose: {chosen}")
        parsed.filename = chosen
    url = hf_src.resolve_url(parsed.repo, parsed.filename, parsed.revision)
    headers = {"Authorization": f"Bearer {token}"} if token else None
    dest = target_dir / (out_name or Path(parsed.filename).name)
    info(f"downloading {parsed.repo}/{parsed.filename}")
    info(f"  -> {dest}")
    download_util.download(
        url,
        dest,
        parallel=int(cfg.get("download.parallel_connections", 16)),
        headers=headers,
        overwrite=force,
    )
    success(f"saved {dest.name} ({human_size(dest.stat().st_size)})")


def _pull_civitai(
    ref: str,
    target_dir: Path,
    cfg: config_mod.Config,
    *,
    type_override: Optional[str],
    out_name: Optional[str],
    force: bool,
) -> None:
    parsed = civitai_src.CivitaiRef.parse(ref)
    token = civitai_src.get_token(cfg.get("download.civitai_token", ""))
    if not token:
        warn("CivitAI requires a token to download.")
        info("  set with: sd config set download.civitai_token <TOKEN>")
        info("  generate at: https://civitai.com/user/account (API Keys section)")
        raise click.exceptions.Exit(2)
    info(f"resolving {ref}...")
    try:
        version, file_obj = civitai_src.resolve(parsed, token=token)
    except (LookupError, Exception) as e:  # noqa: BLE001
        error(f"resolve failed: {e}")
        raise click.exceptions.Exit(1)
    model_meta = version.get("model") or {}
    civitai_type = model_meta.get("type", "Checkpoint")
    if not type_override:
        target_dir = cfg.models_dir / civitai_src.model_type_to_dir(civitai_type)
        target_dir.mkdir(parents=True, exist_ok=True)
    url = civitai_src.build_download_url(file_obj, token=token)
    fname = out_name or file_obj.get("name") or f"civitai_{parsed.id}.safetensors"
    dest = target_dir / fname
    info(f"name: {model_meta.get('name','?')} / version {version.get('name','?')}")
    info(f"file: {fname}  ({file_obj.get('sizeKB',0)/1024:.1f} MB)")
    info(f"  -> {dest}")
    download_util.download(
        url,
        dest,
        parallel=int(cfg.get("download.parallel_connections", 16)),
        overwrite=force,
    )
    success(f"saved {dest.name} ({human_size(dest.stat().st_size)})")


def _pull_direct(
    url: str,
    target_dir: Path,
    cfg: config_mod.Config,
    *,
    out_name: Optional[str],
    force: bool,
) -> None:
    fname = out_name or Path(url.split("?", 1)[0]).name
    dest = target_dir / fname
    info(f"downloading {url}")
    info(f"  -> {dest}")
    download_util.download(
        url,
        dest,
        parallel=int(cfg.get("download.parallel_connections", 16)),
        overwrite=force,
    )
    success(f"saved {dest.name} ({human_size(dest.stat().st_size)})")
