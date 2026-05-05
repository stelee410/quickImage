"""HTTP client for the local ComfyUI server.

Talks to ComfyUI's REST API documented at https://docs.comfy.org/development/comfyui-server/comms_overview.
The server we target is the one bundled with ``comfyui-rocm`` at port 8188.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

import requests


class ComfyError(RuntimeError):
    """Raised when the ComfyUI server returns an error or is unreachable."""


@dataclass
class GenerationResult:
    prompt_id: str
    status: str
    elapsed: float
    images: list[dict[str, str]]  # [{filename, subfolder, type}]
    error: Optional[str] = None


class ComfyClient:
    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        if not base_url.endswith("/"):
            base_url += "/"
        self.base_url = base_url
        self.timeout = timeout

    # --- low-level -------------------------------------------------------

    def _get(self, path: str, **kw: Any) -> requests.Response:
        return requests.get(urljoin(self.base_url, path.lstrip("/")), timeout=self.timeout, **kw)

    def _post(self, path: str, json_body: dict[str, Any]) -> requests.Response:
        return requests.post(
            urljoin(self.base_url, path.lstrip("/")),
            json=json_body,
            timeout=self.timeout,
        )

    # --- health / metadata ----------------------------------------------

    def is_alive(self) -> bool:
        try:
            r = self._get("system_stats")
        except requests.RequestException:
            return False
        return r.status_code == 200

    def system_stats(self) -> dict[str, Any]:
        r = self._get("system_stats")
        r.raise_for_status()
        return r.json()

    def queue(self) -> dict[str, Any]:
        r = self._get("queue")
        r.raise_for_status()
        return r.json()

    def object_info(self) -> dict[str, Any]:
        r = self._get("object_info")
        r.raise_for_status()
        return r.json()

    def list_checkpoints(self) -> list[str]:
        info = self.object_info()
        try:
            ckpts = info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
            return list(ckpts)
        except (KeyError, IndexError, TypeError):
            return []

    def list_samplers(self) -> list[str]:
        info = self.object_info()
        try:
            return list(info["KSampler"]["input"]["required"]["sampler_name"][0])
        except (KeyError, IndexError, TypeError):
            return []

    def list_schedulers(self) -> list[str]:
        info = self.object_info()
        try:
            return list(info["KSampler"]["input"]["required"]["scheduler"][0])
        except (KeyError, IndexError, TypeError):
            return []

    # --- workflow execution ---------------------------------------------

    def submit(self, workflow: dict[str, Any], *, client_id: Optional[str] = None) -> str:
        client_id = client_id or str(uuid.uuid4())
        body = {"prompt": workflow, "client_id": client_id}
        r = self._post("prompt", body)
        if r.status_code != 200:
            raise ComfyError(f"Prompt rejected: HTTP {r.status_code} — {r.text}")
        data = r.json()
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            node_errors = data.get("node_errors") or {}
            if node_errors:
                msgs = []
                for node_id, err in node_errors.items():
                    msgs.append(f"node {node_id}: {err.get('errors') or err}")
                raise ComfyError("Prompt validation failed:\n  " + "\n  ".join(msgs))
            raise ComfyError(f"No prompt_id in server response: {data}")
        return prompt_id

    def history(self, prompt_id: str) -> Optional[dict[str, Any]]:
        r = self._get(f"history/{prompt_id}")
        r.raise_for_status()
        data = r.json()
        return data.get(prompt_id)

    def wait(self, prompt_id: str, *, timeout: float = 600.0, poll: float = 1.0) -> GenerationResult:
        start = time.time()
        last_status = "queued"
        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                raise ComfyError(f"Timed out after {timeout:.0f}s waiting for {prompt_id}")
            entry = self.history(prompt_id)
            if entry:
                status = entry.get("status", {})
                completed = bool(status.get("completed"))
                status_str = status.get("status_str", "")
                last_status = status_str or last_status
                if completed:
                    images = _collect_images(entry.get("outputs", {}))
                    return GenerationResult(
                        prompt_id=prompt_id,
                        status=status_str or "success",
                        elapsed=elapsed,
                        images=images,
                    )
                if status_str == "error":
                    msgs = status.get("messages") or []
                    return GenerationResult(
                        prompt_id=prompt_id,
                        status="error",
                        elapsed=elapsed,
                        images=[],
                        error=json.dumps(msgs, ensure_ascii=False),
                    )
            time.sleep(poll)

    # --- image / file fetch ---------------------------------------------

    def fetch_image(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        params = {"filename": filename, "type": folder_type}
        if subfolder:
            params["subfolder"] = subfolder
        r = self._get("view", params=params)
        r.raise_for_status()
        return r.content

    def upload_image(self, path: Path, *, overwrite: bool = True, folder_type: str = "input") -> str:
        """Upload a reference image to the ComfyUI ``input`` directory.

        Returns the server-side filename to reference in workflows.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        with path.open("rb") as fh:
            files = {"image": (path.name, fh, "application/octet-stream")}
            data = {"type": folder_type, "overwrite": "true" if overwrite else "false"}
            r = requests.post(
                urljoin(self.base_url, "upload/image"),
                files=files,
                data=data,
                timeout=120,
            )
        r.raise_for_status()
        return r.json().get("name", path.name)


def _collect_images(outputs: dict[str, Any]) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    for node_output in outputs.values():
        for img in node_output.get("images", []) or []:
            images.append(
                {
                    "filename": img.get("filename", ""),
                    "subfolder": img.get("subfolder", ""),
                    "type": img.get("type", "output"),
                }
            )
    return images
