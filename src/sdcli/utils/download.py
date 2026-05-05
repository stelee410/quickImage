"""Fast HTTP download via aria2c subprocess.

Falls back to a pure-requests stream copy if aria2c is missing.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import requests
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)


def aria2c_available() -> bool:
    return shutil.which("aria2c") is not None


def download(
    url: str,
    dest: Path,
    *,
    parallel: int = 16,
    headers: Optional[dict[str, str]] = None,
    overwrite: bool = False,
    show_progress: bool = True,
) -> Path:
    """Download ``url`` to ``dest``. Returns the final path.

    If ``dest`` is a directory, the filename is derived from the URL.
    """
    dest = Path(dest)
    if dest.is_dir():
        # Derive name from URL path
        name = url.rsplit("/", 1)[-1].split("?", 1)[0]
        dest = dest / name

    if dest.exists() and not overwrite:
        raise FileExistsError(f"{dest} already exists (pass --force to overwrite)")

    dest.parent.mkdir(parents=True, exist_ok=True)

    if aria2c_available():
        return _download_aria2(url, dest, parallel=parallel, headers=headers, show_progress=show_progress)
    return _download_requests(url, dest, headers=headers, show_progress=show_progress)


def _download_aria2(
    url: str,
    dest: Path,
    *,
    parallel: int,
    headers: Optional[dict[str, str]],
    show_progress: bool,
) -> Path:
    args = [
        "aria2c",
        f"--dir={dest.parent}",
        f"--out={dest.name}",
        f"--max-connection-per-server={parallel}",
        f"--split={parallel}",
        "--min-split-size=4M",
        "--file-allocation=none",
        "--continue=true",
        "--check-certificate=true",
        "--auto-file-renaming=false",
        "--allow-overwrite=true",
    ]
    if headers:
        for k, v in headers.items():
            args.append(f"--header={k}: {v}")
    if not show_progress:
        args.extend(["--quiet=true", "--summary-interval=0"])
    else:
        args.extend(["--console-log-level=warn", "--summary-interval=2", "--show-console-readout=true"])
    args.append(url)

    proc = subprocess.run(args, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"aria2c exited {proc.returncode} for {url}")
    if not dest.exists():
        raise RuntimeError(f"aria2c finished but {dest} missing")
    return dest


def _download_requests(
    url: str,
    dest: Path,
    *,
    headers: Optional[dict[str, str]],
    show_progress: bool,
) -> Path:
    with requests.get(url, headers=headers or {}, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0)) or None
        if show_progress:
            progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
            )
            with progress:
                task = progress.add_task(dest.name, total=total)
                with dest.open("wb") as fh:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            fh.write(chunk)
                            progress.update(task, advance=len(chunk))
        else:
            with dest.open("wb") as fh:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        fh.write(chunk)
    return dest
