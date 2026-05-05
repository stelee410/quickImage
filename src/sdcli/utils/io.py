"""File / path helpers."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterator


def sha256_file(path: Path, *, chunk: int = 1024 * 1024) -> str:
    """Stream-hash a file. Returns lowercase hex digest."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            buf = fh.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def walk_models(root: Path) -> Iterator[tuple[str, Path]]:
    """Yield (model_type, file_path) for every model file under ``root``.

    The model type is the immediate subfolder name (checkpoints, loras, vae, ...).
    """
    if not root.exists():
        return
    interesting_suffixes = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf"}
    for kind_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for f in kind_dir.rglob("*"):
            if f.is_file() and f.suffix.lower() in interesting_suffixes:
                yield kind_dir.name, f
