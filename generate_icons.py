#!/usr/bin/env python3
"""Generate independent, reviewable game icon candidates through local ComfyUI.

Defaults: the supplied FLUX.2 Klein 4B DISTILLED workflow, 4 steps, CFG 1,
1024 x 1024, and seeds 101, 102, 103. Three requests, not a batch of nine.

Run beside prompts.json:
    python3 generate_icons.py --dry-run
    python3 generate_icons.py --only frostweave_gloves
    python3 generate_icons.py

No reference images, model downloads, or repository writes.
The external workflow.json workflow performs BiRefNet background removal and alpha joining.
The only third-party dependency used by this runner is Pillow, also used by the original runner.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "2.0.1"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SEEDS = (101, 102, 103)
DEFAULT_MODEL = "flux-2-klein-4b.safetensors"
DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
# The ComfyUI API graph is intentionally kept in a separate JSON file.
# Put workflow.json beside this script, or pass --workflow /path/to/file.json.
DEFAULT_WORKFLOW = SCRIPT_DIR / "workflow.json"


class IconError(RuntimeError):
    """An actionable validation, API, or output error."""


class QueueUncertain(IconError):
    """A submission may have reached ComfyUI; never retry it blindly."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IconError(f"Cannot read JSON file {path}: {exc}") from exc


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def save_json(path: Path, data: Any) -> None:
    atomic_bytes(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_hash(data: Any) -> str:
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_seeds(seeds: list[int]) -> list[int]:
    if not seeds or any(type(s) is not int or not 0 <= s <= 2**64 - 1 for s in seeds):
        raise IconError("Seeds must be whole numbers from 0 through 18446744073709551615.")
    if len(set(seeds)) != len(seeds):
        raise IconError("Repeated seeds would duplicate candidates. Supply distinct seeds.")
    return seeds


def validate_entries(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise IconError("The prompt file must be a JSON array of icon entries.")
    seen: set[str] = set()
    for number, entry in enumerate(data, 1):
        if not isinstance(entry, dict):
            raise IconError(f"Prompt entry {number} must be an object.")
        name = entry.get("filename")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.png", name):
            raise IconError(f"Entry {number}: use a plain safe .png filename, not a path: {name!r}")
        if name.casefold() in seen:
            raise IconError(f"Duplicate icon filename (including case-only differences): {name}")
        seen.add(name.casefold())
        positive = entry.get("positive_prompt")
        if not isinstance(positive, str) or not positive.strip():
            raise IconError(f"{name}: positive_prompt must be a nonempty string.")
        if not isinstance(entry.get("negative_prompt", ""), str):
            raise IconError(f"{name}: negative_prompt must be a string; an empty string is valid.")
    return data


def select_entries(entries: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    selected = entries
    if args.only:
        requested = set(args.only)
        matched: set[str] = set()
        selected = []
        for entry in entries:
            keys = {entry["filename"], Path(entry["filename"]).stem, entry.get("semantic_key", "")}
            if keys & requested:
                selected.append(entry)
                matched |= keys & requested
        missing = requested - matched
        if missing:
            raise IconError("Unknown --only value(s): " + ", ".join(sorted(missing)))
    if args.only_status:
        selected = [e for e in selected if e.get("migration_status") in args.only_status]
    if args.limit is not None:
        selected = selected[:args.limit]
    return selected


def is_link(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and type(value[1]) is int


def validate_graph(graph: Any) -> dict[str, Any]:
    if not isinstance(graph, dict) or not graph:
        raise IconError("Workflow must be a nonempty API-format JSON object.")
    if "nodes" in graph or "links" in graph:
        raise IconError("This is a visual-editor workflow, not an API export. Use ComfyUI API-format JSON such as workflow.json.")
    for node_id, node in graph.items():
        if not isinstance(node_id, str) or not isinstance(node, dict):
            raise IconError("Invalid API graph: expected string node IDs and node objects.")
        if not isinstance(node.get("class_type"), str) or not isinstance(node.get("inputs"), dict):
            raise IconError(f"Node {node_id} is missing class_type or inputs.")
        for field, value in node["inputs"].items():
            if is_link(value) and value[0] not in graph:
                raise IconError(f"Broken workflow connection: {node_id}.{field} refers to {value[0]}.")
    return graph


def unique_node(graph: dict[str, Any], class_type: str) -> str:
    matches = [key for key, value in graph.items() if value["class_type"] == class_type]
    if len(matches) != 1:
        raise IconError(f"Expected exactly one {class_type} node; found {len(matches)} in the API workflow.")
    return matches[0]


def linked_node(graph: dict[str, Any], node_id: str, field: str, expected: str) -> str:
    link = graph[node_id]["inputs"].get(field)
    if not is_link(link) or link[1] != 0 or graph[link[0]]["class_type"] != expected:
        raise IconError(f"{node_id}.{field} must be connected to a {expected} output.")
    return link[0]


def discover_nodes(graph: dict[str, Any]) -> dict[str, str]:
    """Use connections and node classes, never stale names such as 'STEPS - 50'."""
    validate_graph(graph)
    sampler = unique_node(graph, "SamplerCustomAdvanced")
    guider = linked_node(graph, sampler, "guider", "CFGGuider")
    nodes = {
        "sampler": sampler,
        "guider": guider,
        "noise": linked_node(graph, sampler, "noise", "RandomNoise"),
        "scheduler": linked_node(graph, sampler, "sigmas", "Flux2Scheduler"),
        "latent": linked_node(graph, sampler, "latent_image", "EmptyFlux2LatentImage"),
        "method": linked_node(graph, sampler, "sampler", "KSamplerSelect"),
        "positive": linked_node(graph, guider, "positive", "CLIPTextEncode"),
        "negative": linked_node(graph, guider, "negative", "CLIPTextEncode"),
        "model": linked_node(graph, guider, "model", "UNETLoader"),
        "save": unique_node(graph, "SaveImage"),
        "clip": unique_node(graph, "CLIPLoader"),
        "vae": unique_node(graph, "VAELoader"),
    }
    # All normal graph nodes must lead to the selected output. Reject accidental
    # extra branches that could execute unrelated work or make seed mapping ambiguous.
    visited: set[str] = set()
    active: set[str] = set()
    def visit(node_id: str) -> None:
        if node_id in active:
            raise IconError("Workflow contains a cycle.")
        if node_id in visited:
            return
        active.add(node_id)
        for value in graph[node_id]["inputs"].values():
            if is_link(value):
                visit(value[0])
        active.remove(node_id)
        visited.add(node_id)
    visit(nodes["save"])
    if sampler not in visited:
        raise IconError("Save Image is not connected to the FLUX generator.")
    if len(visited) != len(graph):
        raise IconError("Workflow has disconnected or additional output branches. Use a single-output API graph.")
    for field in ("positive", "negative"):
        if linked_node(graph, nodes[field], "clip", "CLIPLoader") != nodes["clip"]:
            raise IconError("Both prompt encoders must use the same CLIP loader.")
    return nodes


def literal_input(graph: dict[str, Any], node_id: str, field: str) -> Any:
    value = graph[node_id]["inputs"].get(field)
    if is_link(value):
        primitive = graph[value[0]]
        if value[1] != 0 or primitive["class_type"] not in {"PrimitiveInt", "PrimitiveFloat", "PrimitiveString", "PrimitiveStringMultiline"}:
            raise IconError(f"Unsupported linked widget {node_id}.{field}; expected a simple primitive value.")
        return primitive["inputs"].get("value")
    return value


def set_input(graph: dict[str, Any], node_id: str, field: str, value: Any) -> None:
    current = graph[node_id]["inputs"].get(field)
    if is_link(current):
        # Preserve the graph's primitive connection, including the large prompt box.
        literal_input(graph, node_id, field)  # verifies the primitive type first
        graph[current[0]]["inputs"]["value"] = value
    else:
        graph[node_id]["inputs"][field] = value


def validate_recipe(graph: dict[str, Any], nodes: dict[str, str], allow_nonstandard: bool = False) -> dict[str, Any]:
    recipe = {
        "model": literal_input(graph, nodes["model"], "unet_name"),
        "text_encoder": literal_input(graph, nodes["clip"], "clip_name"),
        "text_encoder_type": literal_input(graph, nodes["clip"], "type"),
        "vae": literal_input(graph, nodes["vae"], "vae_name"),
        "steps": literal_input(graph, nodes["scheduler"], "steps"),
        "cfg": literal_input(graph, nodes["guider"], "cfg"),
        "sampler": literal_input(graph, nodes["method"], "sampler_name"),
    }
    expected = {"model": DEFAULT_MODEL, "text_encoder": "qwen_3_4b.safetensors", "text_encoder_type": "flux2", "vae": "flux2-vae.safetensors", "steps": 4, "cfg": 1, "sampler": "euler"}
    problems = [f"{key}={recipe[key]!r}, expected {value!r}" for key, value in expected.items() if recipe[key] != value]
    if problems and not allow_nonstandard:
        raise IconError("Workflow is not the four-step distilled recipe. " + "; ".join(problems) + ". Fix workflow.json, or deliberately use --allow-nonstandard-workflow.")
    if problems:
        print("WARNING: explicitly allowing a nonstandard recipe: " + "; ".join(problems), flush=True)
    return recipe


def build_workflow(template: dict[str, Any], nodes: dict[str, str], entry: dict[str, Any], seed: int, size: int, prefix: str) -> dict[str, Any]:
    graph = copy.deepcopy(template)
    set_input(graph, nodes["positive"], "text", entry["positive_prompt"])
    set_input(graph, nodes["negative"], "text", entry.get("negative_prompt", ""))
    # This overrides the saved seed for this API request. UI 'fixed' is irrelevant.
    set_input(graph, nodes["noise"], "noise_seed", seed)
    for node_key in ("scheduler", "latent"):
        set_input(graph, nodes[node_key], "width", size)
        set_input(graph, nodes[node_key], "height", size)
    set_input(graph, nodes["latent"], "batch_size", 1)
    set_input(graph, nodes["save"], "filename_prefix", prefix)
    return graph


def fingerprint(graph: dict[str, Any], nodes: dict[str, str], target_size: int) -> str:
    stable = copy.deepcopy(graph)
    for node in stable.values():
        node.pop("_meta", None)
    set_input(stable, nodes["save"], "filename_prefix", "<candidate-output>")
    return json_hash({"workflow": stable, "target_size": target_size, "resize": "Pillow-LANCZOS"})


def request_json(url: str, *, payload: Any = None, timeout: float = 30) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"User-Agent": "Icon-Generator/" + VERSION}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=max(0.1, timeout)) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:6000]
        raise IconError(f"ComfyUI HTTP {exc.code} at {urllib.parse.urlsplit(url).path}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise IconError(f"Cannot reach ComfyUI at {url}: {exc}") from exc
    if not body.strip():
        return {}  # /interrupt and /queue may return an empty successful response.
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise IconError(f"ComfyUI returned non-JSON data at {url}.") from exc


class ComfyClient:
    def __init__(self, base_url: str, client_id: str) -> None:
        self.url = base_url.rstrip("/")
        self.client_id = client_id

    def get(self, path: str, timeout: float = 30) -> Any:
        return request_json(self.url + path, timeout=timeout)

    def post(self, path: str, payload: Any, timeout: float = 30) -> Any:
        return request_json(self.url + path, payload=payload, timeout=timeout)

    def preflight(self, graph: dict[str, Any]) -> None:
        info = self.get("/object_info", timeout=60)
        if not isinstance(info, dict):
            raise IconError("Unexpected /object_info response. Check --comfy-url.")
        for node in graph.values():
            cls = node["class_type"]
            if cls not in info:
                raise IconError(f"Your ComfyUI server does not have the {cls} node. No job was submitted.")
            fields = {}
            for group in ("required", "optional"):
                fields.update(info[cls].get("input", {}).get(group, {}))
            for field in ("unet_name", "clip_name", "vae_name"):
                if field not in node["inputs"]:
                    continue
                value = node["inputs"][field]
                spec = fields.get(field)
                choices = spec[0] if isinstance(spec, (list, tuple)) and spec else None
                if isinstance(choices, list) and value not in choices:
                    raise IconError(f"Missing model in {cls}.{field}: {value}. No substitute was selected and nothing was downloaded.")
        queue = self.get("/queue")
        if queue.get("queue_running") or queue.get("queue_pending"):
            raise IconError("ComfyUI already has a running or queued job. Let it finish, then rerun this command. This script will not clear someone else's queue.")

    def submit(self, graph: dict[str, Any]) -> str:
        try:
            response = self.post("/prompt", {"prompt": graph, "client_id": self.client_id}, timeout=60)
        except IconError as exc:
            if isinstance(exc.__cause__, urllib.error.HTTPError) and exc.__cause__.code < 500:
                raise  # explicit validation rejection, not ambiguous acceptance
            raise QueueUncertain("Submission response was lost. The job MAY be queued. Check ComfyUI before retrying; the script has stopped to avoid duplicate generation. " + str(exc)) from exc
        if not isinstance(response, dict) or not response.get("prompt_id"):
            raise IconError("ComfyUI rejected the job: " + json.dumps(response, ensure_ascii=False)[:6000])
        if response.get("node_errors"):
            print("ComfyUI node warnings: " + json.dumps(response["node_errors"])[:3000], flush=True)
        return str(response["prompt_id"])

    def history(self, prompt_id: str, timeout: float = 30) -> Any:
        data = self.get("/history/" + urllib.parse.quote(prompt_id, safe=""), timeout)
        return data.get(prompt_id) if isinstance(data, dict) else None

    @staticmethod
    def completed_outputs(entry: Any, save_id: str) -> dict[str, Any] | None:
        if not entry:
            return None
        status = entry.get("status", {})
        if status.get("status_str") in {"error", "interrupted"}:
            messages = status.get("messages", [])
            detail = json.dumps(messages or status, ensure_ascii=False)
            raise IconError("ComfyUI execution failed: " + detail[-6000:])
        if status.get("completed") is False:
            return None
        outputs = entry.get("outputs", {})
        if save_id in outputs:
            return outputs
        if status.get("completed") is True:
            raise IconError("ComfyUI finished but the selected Save Image node has no output.")
        return None

    def wait(self, prompt_id: str, save_id: str, poll: float) -> dict[str, Any]:
        start = time.monotonic()
        next_notice = start + 15
        consecutive_errors = 0
        while True:
            try:
                entry = self.history(prompt_id, timeout=15)
                consecutive_errors = 0
            except IconError:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    raise
                entry = None
            outputs = self.completed_outputs(entry, save_id)
            if outputs is not None:
                return outputs
            if time.monotonic() >= next_notice:
                print(f"  Waiting for ComfyUI: {time.monotonic() - start:.0f}s elapsed.", flush=True)
                next_notice = time.monotonic() + 15
            time.sleep(poll)

    def cancel_own(self, prompt_id: str) -> str:
        """Best effort only: remove this queued ID, interrupt only if it is running."""
        try:
            queue = self.get("/queue", timeout=10)
            running = {str(row[1]) for row in queue.get("queue_running", []) if len(row) > 1}
            pending = {str(row[1]) for row in queue.get("queue_pending", []) if len(row) > 1}
            if prompt_id in pending:
                self.post("/queue", {"delete": [prompt_id]}, timeout=10)
                return "Removal requested for this pending job only."
            if prompt_id in running:
                self.post("/interrupt", {"prompt_id": prompt_id}, timeout=10)
                return "Interruption requested for this running prompt_id. Check ComfyUI; cancellation may not be immediate."
            return "This prompt_id is no longer in the active queue."
        except IconError as exc:
            return "Could not confirm cancellation. Check ComfyUI manually. " + str(exc)

    def download(self, image_info: dict[str, Any]) -> bytes:
        params = urllib.parse.urlencode({"filename": image_info["filename"], "subfolder": image_info.get("subfolder", ""), "type": image_info.get("type", "output")})
        try:
            with urllib.request.urlopen(self.url + "/view?" + params, timeout=120) as response:
                data = response.read(100 * 1024 * 1024 + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise IconError(f"Could not download the saved ComfyUI image: {exc}") from exc
        if len(data) > 100 * 1024 * 1024:
            raise IconError("Image response exceeds the 100 MB safety limit.")
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise IconError("Save Image did not return a PNG file.")
        return data


def pillow() -> Any:
    try:
        from PIL import Image
        return Image
    except ImportError as exc:
        raise IconError("Pillow is missing from this Python environment. Use the Python environment used by your old runner, or run: python3 -m pip install Pillow") from exc


def inspect_image(path: Path, expected_size: int | None = None) -> dict[str, Any]:
    Image = pillow()
    try:
        with Image.open(path) as image:
            image.load()
            if image.format != "PNG":
                raise IconError(f"{path.name} is not a PNG.")
            if expected_size is not None and image.size != (expected_size, expected_size):
                raise IconError(f"{path.name}: expected {expected_size} x {expected_size}, received {image.size}.")
            rgba = image.convert("RGBA")
            alpha = rgba.getchannel("A")
            lo, hi = alpha.getextrema()
            border_max = max(alpha.crop(box).getextrema()[1] for box in ((0, 0, image.width, 1), (0, image.height - 1, image.width, image.height), (0, 0, 1, image.height), (image.width - 1, 0, image.width, image.height)))
            return {"dimensions": list(image.size), "mode": image.mode, "alpha_present": "A" in image.getbands() or "transparency" in image.info, "real_transparency": lo < 255 and hi > 0, "alpha_range": [lo, hi], "border_max_alpha": border_max}
    except (OSError, ValueError) as exc:
        raise IconError(f"Cannot read image {path}: {exc}") from exc


def make_preview(source: Path, destination: Path, size: int) -> None:
    Image = pillow()
    with Image.open(source) as image:
        # RGBA is a container mode, not a claim of real background transparency.
        mode = "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
        preview = image.convert(mode).resize((size, size), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        preview.save(buffer, format="PNG")
    atomic_bytes(destination, buffer.getvalue())


def candidate_name(filename: str, variant: int) -> str:
    return f"{Path(filename).stem}_{variant}.png"


def candidate_paths(root: Path, name: str, target_size: int) -> dict[str, Path]:
    return {"source": root / "source" / name, "preview": root / f"preview_{target_size}" / name, "meta": root / "metadata" / (Path(name).stem + ".json")}


def finalize_candidate(meta: dict[str, Any], paths: dict[str, Path], args: argparse.Namespace) -> dict[str, Any]:
    source_info = inspect_image(paths["source"], args.generation_size)
    if args.require_alpha and not source_info["real_transparency"]:
        raise IconError("Generated source is opaque. --require-alpha requires genuine transparent pixels from the external API workflow.")
    make_preview(paths["source"], paths["preview"], args.target_size)
    meta.update({"phase": "complete", "status": "rendered-unreviewed", "qa_status": "needs-visual-review", "finished_at": utc_now(), "source": source_info, "preview": inspect_image(paths["preview"], args.target_size), "source_sha256": sha256_file(paths["source"]), "preview_sha256": sha256_file(paths["preview"]), "source_path": str(paths["source"]), "preview_path": str(paths["preview"])})
    save_json(paths["meta"], meta)
    return meta


def download_and_finalize(client: ComfyClient, outputs: dict[str, Any], nodes: dict[str, str], meta: dict[str, Any], paths: dict[str, Path], args: argparse.Namespace) -> dict[str, Any]:
    images = outputs.get(nodes["save"], {}).get("images", [])
    if len(images) != 1:
        raise IconError(f"Expected exactly one output image, received {len(images)}. Each seed must be a separate request with batch_size=1.")
    data = client.download(images[0])
    atomic_bytes(paths["source"], data)  # exact source bytes, including ComfyUI PNG metadata
    meta.update({"phase": "downloaded", "comfy_image": images[0], "source_sha256": sha256_file(paths["source"])})
    save_json(paths["meta"], meta)
    return finalize_candidate(meta, paths, args)


def generate_candidate(args: argparse.Namespace, client: ComfyClient, template: dict[str, Any], nodes: dict[str, str], entry: dict[str, Any], seed: int, variant: int, run_id: str) -> dict[str, Any]:
    name = candidate_name(entry["filename"], variant)
    paths = candidate_paths(args.output_root, name, args.target_size)
    prefix = "icon_generator/" + Path(name).stem + "_" + run_id[-8:]
    graph = build_workflow(template, nodes, entry, seed, args.generation_size, prefix)
    key = fingerprint(graph, nodes, args.target_size)
    old = load_json(paths["meta"]) if paths["meta"].exists() else None
    if not args.overwrite and (old is not None or paths["source"].exists() or paths["preview"].exists()):
        if not isinstance(old, dict) or old.get("fingerprint") != key:
            raise IconError(f"{name} already exists for a different or unrecorded recipe. Use --overwrite only if you deliberately want to regenerate and replace it. Nothing was replaced.")
        if old.get("phase") in {"complete", "downloaded"} and paths["source"].exists():
            if sha256_file(paths["source"]) != old.get("source_sha256"):
                raise IconError(f"{name}: source hash changed. Refusing to treat this edited file as the recorded generated source.")
            if old.get("phase") == "complete" and paths["preview"].exists() and sha256_file(paths["preview"]) == old.get("preview_sha256"):
                if args.require_alpha and not old.get("source", {}).get("real_transparency"):
                    raise IconError(f"{name} is opaque; it cannot pass --require-alpha.")
                print(f"  SKIP verified existing candidate: {name}", flush=True)
                return {**old, "action": "skipped-existing"}
            result = finalize_candidate(old, paths, args)
            return {**result, "action": "restored-local-preview"}
        # A prior process may have ended after generation but before download.
        prior_id = old.get("prompt_id")
        if prior_id:
            try:
                outputs = client.completed_outputs(client.history(prior_id), nodes["save"])
            except IconError:
                if not args.retry_failed:
                    raise IconError(f"Previous job for {name} failed. Use --retry-failed to request a new run of failed candidates.")
                outputs = None
            if outputs is not None:
                print(f"  Recovering completed ComfyUI output for {name}; no new generation.", flush=True)
                return {**download_and_finalize(client, outputs, nodes, old, paths, args), "action": "recovered-from-history"}
        if not args.retry_failed:
            raise IconError(f"{name} has an unfinished/failed submission record. Check ComfyUI, then use --retry-failed after confirming that no old job is still running. The script will not silently submit a duplicate.")
    meta = {"runner_version": VERSION, "filename": name, "original_filename": entry["filename"], "display_name": entry.get("display_name", entry["filename"]), "variant": variant, "seed": seed, "fingerprint": key, "phase": "submitting", "status": "unreviewed", "qa_status": "needs-visual-review", "started_at": utc_now(), "run_id": run_id, "comfy_client_id": client.client_id, "entry": entry, "submitted_workflow": graph, "source_path": str(paths["source"]), "preview_path": str(paths["preview"])}
    save_json(paths["meta"], meta)
    prompt_id = None
    start = time.monotonic()
    try:
        prompt_id = client.submit(graph)
        meta.update({"phase": "queued", "prompt_id": prompt_id})
        save_json(paths["meta"], meta)
        print(f"  ComfyUI prompt_id: {prompt_id}", flush=True)
        outputs = client.wait(prompt_id, nodes["save"], args.poll_seconds)
        meta["generation_wait_seconds"] = round(time.monotonic() - start, 3)
        result = download_and_finalize(client, outputs, nodes, meta, paths, args)
        result["action"] = "generated"
        result["total_seconds"] = round(time.monotonic() - start, 3)
        save_json(paths["meta"], result)
        print(f"  Saved {name} in {result['total_seconds']:.1f}s — unreviewed, " + ("has transparency" if result["source"]["real_transparency"] else "opaque background"), flush=True)
        return result
    except (KeyboardInterrupt, Exception) as exc:
        cancel_note = None
        if prompt_id and (isinstance(exc, KeyboardInterrupt) or meta.get("phase") == "queued"):
            cancel_note = client.cancel_own(prompt_id)
            print("  " + cancel_note, flush=True)
        meta.update({"phase": "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed", "status": "failed", "error": str(exc) or type(exc).__name__, "elapsed_seconds": round(time.monotonic() - start, 3), "updated_at": utc_now()})
        if isinstance(exc, QueueUncertain):
            meta["phase"] = "submission-uncertain"
        if cancel_note:
            meta["cancellation"] = cancel_note
        save_json(paths["meta"], meta)
        raise


def write_gallery(root: Path, entries: list[dict[str, Any]], seeds: list[int], target_size: int) -> None:
    parts = ["<!doctype html><html lang='en'><meta charset='utf-8'><title>Icon candidates</title>", "<style>body{font:16px system-ui;margin:28px;background:#eceff1;color:#16202b}section{margin:24px 0;padding:20px;background:white;border-radius:10px}.row{display:flex;gap:20px;flex-wrap:wrap}figure{margin:0;width:240px}img{width:220px;height:220px;object-fit:contain;background:repeating-conic-gradient(#eee 0% 25%,white 0% 50%) 50%/20px 20px}.small{width:120px;height:120px}code{overflow-wrap:anywhere}figcaption{margin:8px 0;font-size:14px}</style>", "<h1>Icon candidates — not automatically approved</h1><p>Click an image for the exact generated source. Check shape, material, matching pairs, borders and small-size readability. White pixels are not transparency.</p>"]
    for entry in entries:
        figures = []
        for index, seed in enumerate(seeds, 1):
            name = candidate_name(entry["filename"], index)
            paths = candidate_paths(root, name, target_size)
            if not paths["meta"].exists() or not paths["source"].exists():
                continue
            meta = load_json(paths["meta"])
            if meta.get("phase") != "complete":
                continue
            source = "source/" + urllib.parse.quote(name)
            preview = f"preview_{target_size}/" + urllib.parse.quote(name)
            figures.append(f"<figure><a href='{source}'><img src='{source}' alt='{html.escape(name)}'></a><figcaption><code>{html.escape(name)}</code><br>Seed {meta.get('seed', seed)} · Needs review</figcaption><img class='small' src='{preview}' alt='Small-size preview'></figure>")
        if figures:
            parts.append(f"<section><h2>{html.escape(entry.get('display_name', entry['filename']))}</h2><div class='row'>{''.join(figures)}</div></section>")
    parts.append("</html>")
    atomic_bytes(root / "review.html", "\n".join(parts).encode("utf-8"))


ASCII_HEADER = r"""  ___ ___ ___  _  _    ___ ___ _  _ ___ ___    _ _____ ___  ___
 |_ _/ __/ _ \| \| |  / __| __| \| | __| _ \  /_\_   _/ _ \| _ \
  | | (_| (_) | .` | | (_ | _|| .` | _||   / / _ \| || (_) |   /
 |___\___\___/|_|\_|  \___|___|_|\_|___|_|_\/_/ \_\_| \___/|_|_\
"""


def format_argument_value(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "(not set)"
    if isinstance(value, (list, tuple)):
        return " ".join(str(item) for item in value) if value else "(none)"
    return str(value)


def print_startup_header() -> None:
    print(ASCII_HEADER.rstrip())
    print()


def print_argument_summary(args: argparse.Namespace) -> None:
    rows = [
        ("prompt_file", args.prompt_file, "Prompt definitions JSON"),
        ("--workflow", args.workflow, "ComfyUI API workflow JSON"),
        ("--comfy-url", args.comfy_url, "ComfyUI server address"),
        ("--seeds", args.seeds, "One candidate per seed"),
        ("--only", args.only, "Generate only named icons"),
        ("--only-status", args.only_status, "Filter by migration_status"),
        ("--limit", args.limit, "Maximum icons to process"),
        ("--generation-size", args.generation_size, "Model generation size in pixels"),
        ("--target-size", args.target_size, "Local review image size in pixels"),
        ("--poll-seconds", args.poll_seconds, "Seconds between status checks"),
        ("--overwrite", args.overwrite, "Replace matching existing candidates"),
        ("--retry-failed", args.retry_failed, "Retry recorded failed candidates"),
        ("--require-alpha", args.require_alpha, "Require real transparent pixels"),
        ("--allow-nonstandard-workflow", args.allow_nonstandard_workflow, "Allow non-default model/settings"),
        ("--dry-run", args.dry_run, "Validate plan without generating"),
        ("--check-server", args.check_server, "Validate ComfyUI without generating"),
        ("output directory", args.output_root, "Fixed generated output folder"),
    ]
    option_width = max(len(name) for name, _, _ in rows)
    value_width = max(12, min(52, max(len(format_argument_value(value)) for _, value, _ in rows)))
    print("Arguments:")
    print(f"  {'OPTION':<{option_width}}  {'VALUE':<{value_width}}  DESCRIPTION")
    for name, value, description in rows:
        rendered = format_argument_value(value)
        print(f"  {name:<{option_width}}  {rendered:<{value_width}}  {description}")
    print()
    print("-" * 72)
    print()

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate three independent FLUX cartoon candidates per icon; never install into game assets.")
    parser.add_argument("prompt_file", nargs="?", type=Path, default=SCRIPT_DIR / "prompts.json", help="Prompt JSON array; defaults to prompts.json beside this script.")
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW, help="ComfyUI API-format workflow JSON. Default: workflow.json beside this script.")
    parser.add_argument("--comfy-url", default=DEFAULT_COMFY_URL)
    parser.add_argument("--seeds", type=int, nargs="+", default=None, help="Seed values in candidate suffix order. Default: 101 102 103. One candidate is generated per seed.")
    parser.add_argument("--only", nargs="+", help="Select exact filename, filename stem, or semantic key; e.g. --only frostweave_gloves health_potion")
    parser.add_argument("--only-status", nargs="+", help="Optional migration_status filter. Default includes every manifest entry, including complete.")
    parser.add_argument("--limit", type=int, help="Maximum number of matching ICONS, not images. --limit 1 makes three candidates by default.")
    parser.add_argument("--generation-size", dest="generation_size", type=int, default=1024, help="Square pixel size sent to the image model. Default: 1024.")
    parser.add_argument("--target-size", dest="target_size", type=int, default=120, help="Square pixel size of the local review image. Default: 120.")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--overwrite", action="store_true", help="Explicitly regenerate and replace selected candidate files; never touches repository paths.")
    parser.add_argument("--retry-failed", action="store_true", help="Retry recorded failed/lost jobs after checking that they are not still active. Complete matching candidates are skipped.")
    parser.add_argument("--require-alpha", action="store_true", help="Require real transparent pixels. Recommended with the supplied BiRefNet + JoinImageWithAlpha workflow.")
    parser.add_argument("--allow-nonstandard-workflow", action="store_true", help="Explicitly permit a different model/settings in the external workflow; disables the default fast-recipe guard.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the plan only; no server connection and no generation.")
    parser.add_argument("--check-server", action="store_true", help="Validate files and installed server models only; no generation.")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1.")
    if args.generation_size < 256 or args.generation_size > 2048 or args.generation_size % 16:
        parser.error("--generation-size must be a multiple of 16 between 256 and 2048.")
    if not 1 <= args.target_size <= 2048:
        parser.error("--target-size must be from 1 through 2048.")
    if not math.isfinite(args.poll_seconds) or args.poll_seconds <= 0:
        parser.error("--poll-seconds must be a positive finite number.")
    args.seeds = validate_seeds(args.seeds or list(DEFAULT_SEEDS))
    parts = urllib.parse.urlsplit(args.comfy_url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.query or parts.fragment or parts.username or parts.password:
        parser.error("--comfy-url must be a plain HTTP(S) server address without credentials, query or fragment.")
    args.output_root = Path("generated_icons").resolve()
    args.workflow = args.workflow.expanduser().resolve()
    return args



def format_elapsed_time(seconds: float) -> str:
    """Format elapsed wall time using the requested unit."""
    if seconds < 60:
        return f"{int(round(seconds))} seconds"
    if seconds < 3600:
        return f"{seconds / 60:.1f} minutes"
    return f"{seconds / 3600:.1f} hours"

def main(argv: list[str] | None = None) -> int:
    total_started = time.monotonic()
    print_startup_header()
    try:
        args = parse_args(argv)
        print_argument_summary(args)
        entries = select_entries(validate_entries(load_json(args.prompt_file)), args)
        template = validate_graph(load_json(args.workflow))
        nodes = discover_nodes(template)
        recipe = validate_recipe(template, nodes, args.allow_nonstandard_workflow)
        jobs = [(entry, index, seed) for entry in entries for index, seed in enumerate(args.seeds, 1)]
        # Exercise linked prompt/size/seed setters before talking to the server.
        if entries:
            build_workflow(template, nodes, entries[0], args.seeds[0], args.generation_size, "icon_generator/preflight")
        print(f"Model: {recipe['model']}\nSteps / CFG: {recipe['steps']} / {recipe['cfg']}\nGeneration / target size: {args.generation_size} / {args.target_size}\nIcons: {len(entries)}; candidate images: {len(jobs)}", flush=True)
        print("Images are unreviewed candidates. Background removal is performed only if the external workflow contains it; no game-asset replacement is performed.", flush=True)
        if args.dry_run:
            for entry in entries:
                names = [f"{candidate_name(entry['filename'], i)} (seed {seed})" for i, seed in enumerate(args.seeds, 1)]
                print("  " + " | ".join(names))
            print("DRY RUN: nothing queued, no images generated.")
            return 0
        if not entries:
            print("No entries match the requested filters.")
            return 0
        pillow()
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        client = ComfyClient(args.comfy_url, str(uuid.uuid4()))
        client.preflight(template)
        if args.check_server:
            print("SERVER CHECK PASSED: required nodes and selected model names are available; queue is idle. No image was generated.")
            return 0
    except (IconError, OSError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1

    args.output_root.mkdir(parents=True, exist_ok=True)
    lock_path = args.output_root / ".runner.lock"
    try:
        lock = lock_path.open("x", encoding="utf-8")
    except FileExistsError:
        print(f"ERROR: {lock_path} already exists. Another runner may be active. Only remove this lock after confirming that the earlier script has stopped.", file=sys.stderr)
        return 1
    lock.write(json.dumps({"pid": os.getpid(), "run_id": run_id, "started_at": utc_now()}))
    lock.close()
    reports = args.output_root / "reports"
    run = {"runner_version": VERSION, "run_id": run_id, "started_at": utc_now(), "prompt_file": str(args.prompt_file.resolve()), "prompt_file_sha256": sha256_file(args.prompt_file), "workflow": str(args.workflow), "workflow_sha256": sha256_file(args.workflow), "recipe": recipe, "generation_size": args.generation_size, "target_size": args.target_size, "seeds": args.seeds, "icons_selected": len(entries), "candidate_count": len(jobs), "results": [], "artwork_qa": "not performed automatically", "background_removal": any(node.get("class_type") == "RemoveBackground" for node in template.values()), "alpha_join": any(node.get("class_type") == "JoinImageWithAlpha" for node in template.values())}
    exit_code = 0
    times: list[float] = []
    try:
        for position, (entry, variant, seed) in enumerate(jobs, 1):
            name = candidate_name(entry["filename"], variant)
            print(f"\n[{position}/{len(jobs)}] {entry.get('display_name', entry['filename'])} — {name} — seed {seed}", flush=True)
            try:
                result = generate_candidate(args, client, template, nodes, entry, seed, variant, run_id)
                # Full item prompt and submitted workflow live in metadata/<name>.json.
                concise = {k: v for k, v in result.items() if k not in {"entry", "submitted_workflow"}}
                run["results"].append(concise)
                if result.get("action") == "generated":
                    times.append(result["total_seconds"])
                    remaining = len(jobs) - position
                    print(f"  Measured mean: {sum(times)/len(times):.1f}s/image. Estimated remaining at that mean: {remaining*sum(times)/len(times)/60:.1f} minutes (existing files may skip).", flush=True)
            except KeyboardInterrupt:
                exit_code = 130
                run["results"].append({"filename": name, "seed": seed, "status": "interrupted"})
                print("Stopped. No further icon requests will be submitted.", flush=True)
                break
            except Exception as exc:
                exit_code = 1
                run["results"].append({"filename": name, "seed": seed, "status": "failed", "error": str(exc)})
                print(f"ERROR: {exc}\nStopped at the first failure; no later candidates were queued.", file=sys.stderr)
                break
            finally:
                run["updated_at"] = utc_now()
                save_json(reports / "latest_run.json", run)
                save_json(reports / (run_id + ".json"), run)
        run["finished_at"] = utc_now()
        run["exit_code"] = exit_code
        run["generated"] = sum(r.get("action") == "generated" for r in run["results"])
        run["reused"] = sum(r.get("action") in {"skipped-existing", "restored-local-preview", "recovered-from-history"} for r in run["results"])
        run["not_attempted"] = len(jobs) - len(run["results"])
        save_json(reports / "latest_run.json", run)
        save_json(reports / (run_id + ".json"), run)
        write_gallery(args.output_root, entries, args.seeds, args.target_size)
        total_time = format_elapsed_time(time.monotonic() - total_started)
        print(f"\nGenerated: {run['generated']}; reused: {run['reused']}; not attempted: {run['not_attempted']}; total time: {total_time}\nReview: {args.output_root / 'review.html'}\nReport: {reports / 'latest_run.json'}", flush=True)
        return exit_code
    finally:
        lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
