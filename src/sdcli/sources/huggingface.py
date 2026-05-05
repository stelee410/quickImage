"""HuggingFace Hub source for ``sd models pull``.

Resolves a HF spec like ``hf:owner/repo[:filename]`` to a direct download URL
for ``download.download``. We don't use ``huggingface_hub.hf_hub_download`` so
we can drive aria2c for multi-connection download speed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import requests


@dataclass
class HFRef:
    repo: str
    filename: Optional[str]
    revision: str = "main"

    @classmethod
    def parse(cls, spec: str) -> "HFRef":
        """Parse 'hf:owner/repo' or 'hf:owner/repo:filename' or 'owner/repo[:filename]'."""
        s = spec
        if s.startswith("hf:"):
            s = s[3:]
        if ":" in s:
            repo, filename = s.split(":", 1)
        else:
            repo, filename = s, None
        if "/" not in repo:
            raise ValueError(f"HuggingFace ref must be 'owner/repo' (got '{repo}')")
        return cls(repo=repo, filename=filename)


def list_repo_files(repo: str, revision: str = "main", token: str = "") -> list[dict]:
    """Return repo siblings (files) via the HF API."""
    url = f"https://huggingface.co/api/models/{repo}/revision/{revision}"
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("siblings", [])


def resolve_url(repo: str, filename: str, revision: str = "main") -> str:
    return f"https://huggingface.co/{repo}/resolve/{revision}/{filename}"


def pick_default_filename(siblings: list[dict]) -> Optional[str]:
    """Heuristic: prefer ``model.safetensors`` then any ``*.safetensors`` then ``*.ckpt``."""
    names = [s["rfilename"] for s in siblings]
    weights = [n for n in names if n.endswith((".safetensors", ".ckpt", ".gguf", ".bin"))]
    # Prefer fp16/pruned/emaonly/single-file patterns
    for pat in ("model.safetensors", ".fp16.safetensors", "_fp16.safetensors", "pruned", "emaonly"):
        for n in weights:
            if pat in n:
                return n
    return weights[0] if weights else None
