"""CivitAI source for ``sd models pull``.

Spec format: ``civitai:<modelVersionId>`` (specific version, recommended)
or ``civitai:model:<modelId>`` (latest version of model).

CivitAI requires an API token for downloads — set it via
``sd config set download.civitai_token <TOKEN>`` or env var
``CIVITAI_TOKEN``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass
class CivitaiRef:
    kind: str  # "version" or "model"
    id: int

    @classmethod
    def parse(cls, spec: str) -> "CivitaiRef":
        s = spec
        if s.startswith("civitai:"):
            s = s[len("civitai:") :]
        if s.startswith("model:"):
            return cls(kind="model", id=int(s[len("model:") :]))
        return cls(kind="version", id=int(s))


def get_token(cfg_value: str = "") -> str:
    return cfg_value or os.environ.get("CIVITAI_TOKEN", "")


def fetch_version(version_id: int, token: str = "") -> dict:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(f"https://civitai.com/api/v1/model-versions/{version_id}", headers=headers, timeout=30)
    if r.status_code == 404:
        raise LookupError(f"CivitAI version {version_id} not found (or is private)")
    r.raise_for_status()
    return r.json()


def fetch_latest_version_for_model(model_id: int, token: str = "") -> dict:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(f"https://civitai.com/api/v1/models/{model_id}", headers=headers, timeout=30)
    if r.status_code == 404:
        raise LookupError(f"CivitAI model {model_id} not found")
    r.raise_for_status()
    versions = r.json().get("modelVersions") or []
    if not versions:
        raise LookupError(f"Model {model_id} has no versions")
    return versions[0]


def pick_primary_file(version: dict) -> dict:
    files = version.get("files") or []
    # Prefer the file marked as primary, else the largest safetensors
    for f in files:
        if f.get("primary"):
            return f
    cands = [f for f in files if f.get("name", "").endswith(".safetensors")]
    cands.sort(key=lambda f: f.get("sizeKB", 0), reverse=True)
    if cands:
        return cands[0]
    if files:
        return files[0]
    raise LookupError("No downloadable files for this version")


def model_type_to_dir(civitai_type: str) -> str:
    """Map CivitAI 'type' field to local models/<dir>."""
    return {
        "Checkpoint": "checkpoints",
        "TextualInversion": "embeddings",
        "Hypernetwork": "hypernetworks",
        "AestheticGradient": "embeddings",
        "LORA": "loras",
        "LoCon": "loras",
        "Controlnet": "controlnet",
        "Upscaler": "upscale_models",
        "MotionModule": "diffusion_models",
        "VAE": "vae",
        "Poses": "loras",
        "Wildcards": "embeddings",
        "Workflows": "workflows",
        "Other": "checkpoints",
    }.get(civitai_type, "checkpoints")


def build_download_url(file_obj: dict, token: str = "") -> str:
    url = file_obj.get("downloadUrl")
    if not url:
        raise LookupError("File has no downloadUrl")
    if token:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}token={token}"
    return url


def resolve(ref: CivitaiRef, token: str = "") -> tuple[dict, dict]:
    """Resolve a ``CivitaiRef`` to ``(version_dict, primary_file_dict)``."""
    token = get_token(token)
    if ref.kind == "version":
        version = fetch_version(ref.id, token=token)
    else:
        version = fetch_latest_version_for_model(ref.id, token=token)
    return version, pick_primary_file(version)
