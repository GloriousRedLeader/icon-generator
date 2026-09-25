"""Offline/local-mock tests. Never uses ComfyUI or a diffusion model.

From the repository root:
    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("runner", ROOT / "generate_icons.py")
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

TEST_WORKFLOW = r.validate_graph(r.load_json(ROOT / "icon_api_call.json"))
TEST_NODES = r.discover_nodes(TEST_WORKFLOW)


class MockComfy:
    def __init__(self):
        self.graphs = []
        self.history = {}
        self.running = []
        self.pending = []
        self.interrupts = []
        self.deletions = []
        self.behaviour = "success"
        self.missing_model = False
        self.workflow = copy.deepcopy(TEST_WORKFLOW)
        self.nodes = r.discover_nodes(self.workflow)

        from PIL import Image

        image = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        image.paste((210, 215, 220, 255), (256, 256, 768, 768))
        buf = io.BytesIO()
        image.save(buf, "PNG")
        self.image_bytes = buf.getvalue()

        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send_json(self, data, status=200):
                body = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = urllib.parse.urlsplit(self.path).path
                if path == "/object_info":
                    info = {
                        node["class_type"]: {"input": {"required": {}, "optional": {}}}
                        for node in owner.workflow.values()
                    }
                    for cls, field, value in (
                        ("UNETLoader", "unet_name", r.DEFAULT_MODEL),
                        ("CLIPLoader", "clip_name", "qwen_3_4b.safetensors"),
                        ("VAELoader", "vae_name", "flux2-vae.safetensors"),
                    ):
                        info[cls]["input"]["required"][field] = [
                            [value] if not owner.missing_model else []
                        ]
                    self.send_json(info)
                elif path == "/queue":
                    self.send_json(
                        {
                            "queue_running": owner.running,
                            "queue_pending": owner.pending,
                        }
                    )
                elif path.startswith("/history/"):
                    pid = path.split("/")[-1]
                    self.send_json(
                        {pid: owner.history[pid]} if pid in owner.history else {}
                    )
                elif path == "/view":
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(owner.image_bytes)))
                    self.end_headers()
                    self.wfile.write(owner.image_bytes)
                else:
                    self.send_json({"error": "not found"}, 404)

            def do_POST(self):
                payload = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                if self.path == "/prompt":
                    owner.graphs.append(payload["prompt"])
                    pid = "mock-" + str(len(owner.graphs))
                    if owner.behaviour == "rejected":
                        self.send_json({"error": "invalid graph"}, 400)
                        return
                    if owner.behaviour == "success":
                        owner.history[pid] = {
                            "status": {"status_str": "success", "completed": True},
                            "outputs": {
                                owner.nodes["save"]: {
                                    "images": [
                                        {
                                            "filename": pid + ".png",
                                            "subfolder": "mock",
                                            "type": "output",
                                        }
                                    ]
                                }
                            },
                        }
                    elif owner.behaviour == "error":
                        owner.history[pid] = {
                            "status": {
                                "status_str": "error",
                                "completed": False,
                                "messages": [
                                    [
                                        "execution_error",
                                        {"exception_message": "mock out of memory"},
                                    ]
                                ],
                            },
                            "outputs": {},
                        }
                    elif owner.behaviour == "timeout":
                        owner.running.append(
                            [0, pid, payload["prompt"], {}, [owner.nodes["save"]]]
                        )
                    self.send_json({"prompt_id": pid, "node_errors": {}})
                elif self.path == "/interrupt":
                    owner.interrupts.append(payload)
                    owner.running = [
                        row
                        for row in owner.running
                        if row[1] != payload.get("prompt_id")
                    ]
                    self.send_response(200)
                    self.end_headers()
                elif self.path == "/queue":
                    owner.deletions.append(payload)
                    owner.pending = [
                        row
                        for row in owner.pending
                        if row[1] not in payload.get("delete", [])
                    ]
                    self.send_response(200)
                    self.end_headers()
                else:
                    self.send_json({"error": "not found"}, 404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)


def example(name="test_icon.png"):
    return {
        "filename": name,
        "display_name": "Test icon",
        "semantic_key": "ui.item.test_icon",
        "positive_prompt": "One fantasy item on a white background.",
        "negative_prompt": "",
        "migration_status": "pending",
    }


class UnitTests(unittest.TestCase):
    def setUp(self):
        self.graph = copy.deepcopy(TEST_WORKFLOW)
        self.nodes = r.discover_nodes(self.graph)

    def test_public_layout_defaults(self):
        args = r.parse_args([])
        self.assertEqual(args.prompt_file, ROOT / "prompts.json")
        self.assertEqual(args.workflow, (ROOT / "icon_api_call.json").resolve())
        self.assertEqual(args.output_root.name, "generated_icons")
        self.assertEqual(args.seeds, [101, 102, 103])

    def test_output_root_override_removed(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                r.parse_args(["--output-root", "somewhere-else"])

    def test_startup_header_and_argument_summary(self):
        args = r.parse_args(
            [
                str(ROOT / "sample.prompts.json"),
                "--source-size",
                "768",
                "--require-alpha",
                "--limit",
                "1",
            ]
        )
        with contextlib.redirect_stdout(io.StringIO()) as output:
            r.print_startup_header()
            r.print_argument_summary(args)
        text = output.getvalue()
        self.assertIn("___", text)
        self.assertIn("Arguments:", text)
        self.assertIn("prompt_file", text)
        self.assertIn("--workflow", text)
        self.assertIn("--seeds", text)
        self.assertIn("101 102 103", text)
        self.assertIn("--source-size", text)
        self.assertIn("768", text)
        self.assertIn("--require-alpha", text)
        self.assertIn("true", text)
        self.assertIn("output directory (fixed)", text)
        self.assertIn("-" * 72, text)

    def test_flux_topology_not_titles(self):
        for node in self.graph.values():
            node["_meta"] = {"title": "deliberately wrong name"}
        nodes = r.discover_nodes(self.graph)
        self.assertEqual(nodes["noise"], "9")
        self.assertEqual(nodes["positive"], "7")
        self.assertEqual(nodes["scheduler"], "12")

    def test_literal_seeds_and_suffixes(self):
        for i, seed in enumerate((101, 102, 103), 1):
            graph = r.build_workflow(
                self.graph, self.nodes, example(), seed, 1024, "test"
            )
            self.assertEqual(graph["9"]["inputs"]["noise_seed"], seed)
            self.assertEqual(graph["13"]["inputs"]["batch_size"], 1)
            self.assertEqual(
                r.candidate_name("normal_icon_name.png", i),
                f"normal_icon_name_{i}.png",
            )
        self.assertEqual(self.graph["9"]["inputs"]["noise_seed"], 101)

    def test_prompt_written_to_primitive(self):
        entry = example()
        graph = r.build_workflow(
            self.graph, self.nodes, entry, 101, 512, "test"
        )
        self.assertEqual(graph["6"]["inputs"]["value"], entry["positive_prompt"])
        self.assertEqual(graph["7"]["inputs"]["text"], ["6", 0])
        self.assertEqual(graph["8"]["inputs"]["text"], "")

    def test_size_updates_scheduler_and_latent(self):
        graph = r.build_workflow(
            self.graph, self.nodes, example(), 103, 768, "test"
        )
        for node in ("12", "13"):
            for field in ("width", "height"):
                self.assertEqual(r.literal_input(graph, node, field), 768)

    def test_seed_validation(self):
        for seeds in ([True], [-1], [2**64], [101, 101], [], [1.2]):
            with self.assertRaises(r.IconError):
                r.validate_seeds(seeds)
        self.assertEqual(
            r.validate_seeds([101, 102, 103]), [101, 102, 103]
        )

    def test_empty_negative_valid(self):
        self.assertEqual(len(r.validate_entries([example()])), 1)

    def test_duplicate_and_unsafe_filenames(self):
        with self.assertRaises(r.IconError):
            r.validate_entries([example("a.png"), example("A.png")])
        for filename in (
            "../a.png",
            "/a.png",
            "a\\b.png",
            "x:xx.png",
            "a.png\n",
            "a.jpg",
        ):
            with self.assertRaises(r.IconError):
                r.validate_entries([example(filename)])

    def test_base_model_is_rejected(self):
        self.graph["1"]["inputs"]["unet_name"] = (
            "flux-2-klein-base-4b.safetensors"
        )
        with self.assertRaises(r.IconError):
            r.validate_recipe(self.graph, self.nodes)

    def test_fifty_steps_rejected(self):
        self.graph["12"]["inputs"]["steps"] = 50
        with self.assertRaises(r.IconError):
            r.validate_recipe(self.graph, self.nodes)

    def test_ui_graph_rejected(self):
        with self.assertRaises(r.IconError):
            r.validate_graph({"nodes": [], "links": []})

    def test_fingerprint_ignores_output_prefix_not_seed(self):
        a = r.build_workflow(
            self.graph, self.nodes, example(), 101, 1024, "first"
        )
        b = r.build_workflow(
            self.graph, self.nodes, example(), 101, 1024, "second"
        )
        c = r.build_workflow(
            self.graph, self.nodes, example(), 103, 1024, "second"
        )
        self.assertEqual(
            r.fingerprint(a, self.nodes, 120),
            r.fingerprint(b, self.nodes, 120),
        )
        self.assertNotEqual(
            r.fingerprint(a, self.nodes, 120),
            r.fingerprint(c, self.nodes, 120),
        )

    def test_sample_prompt_file(self):
        prompts = r.validate_entries(
            r.load_json(ROOT / "sample.prompts.json")
        )
        self.assertEqual(len(prompts), 3)
        self.assertEqual(len({x["filename"] for x in prompts}), 3)
        self.assertTrue(all(x["negative_prompt"] == "" for x in prompts))
        self.assertTrue(
            all(x["generation_seeds"] == [101, 102, 103] for x in prompts)
        )

    def test_filters_and_limit(self):
        args = r.parse_args(["--only", "test_icon", "--limit", "1"])
        selected = r.select_entries(
            [example(), example("other.png")], args
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(args.seeds, [101, 102, 103])

    def test_dry_run_does_not_need_server_or_create_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            try:
                os.chdir(tmp)
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    code = r.main(
                        [
                            str(ROOT / "sample.prompts.json"),
                            "--dry-run",
                            "--limit",
                            "1",
                            "--comfy-url",
                            "http://127.0.0.1:1",
                        ]
                    )
                self.assertEqual(code, 0)
                text = output.getvalue()
                self.assertIn("Arguments:", text)
                self.assertIn("-" * 72, text)
                self.assertIn("candidate images: 3", text)
                self.assertLess(text.index("Arguments:"), text.index("Model:"))
                self.assertFalse(Path(tmp, "generated_icons").exists())
            finally:
                os.chdir(previous)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.previous_cwd = Path.cwd()
        os.chdir(self.root)

        self.prompts = self.root / "prompts.json"
        r.save_json(self.prompts, [example()])
        self.server = MockComfy()
        self.args = [
            str(self.prompts),
            "--comfy-url",
            self.server.url,
            "--poll-seconds",
            "0.01",
        ]

    def tearDown(self):
        self.server.close()
        os.chdir(self.previous_cwd)
        self.tmp.cleanup()

    def run_script(self, extra=None):
        with contextlib.redirect_stdout(
            io.StringIO()
        ), contextlib.redirect_stderr(io.StringIO()):
            return r.main(self.args + (extra or []))

    @property
    def results(self):
        return self.root / "generated_icons"

    def test_three_separate_outputs_and_resume(self):
        self.assertEqual(self.run_script(), 0)
        self.assertEqual(len(self.server.graphs), 3)
        for variant, seed in enumerate((101, 102, 103), 1):
            self.assertEqual(
                self.server.graphs[variant - 1]["9"]["inputs"]["noise_seed"],
                seed,
            )
            source = self.results / "source" / f"test_icon_{variant}.png"
            preview = self.results / "preview_120" / source.name
            self.assertTrue(source.exists())
            self.assertEqual(
                r.inspect_image(preview)["dimensions"], [120, 120]
            )
            self.assertTrue(
                r.inspect_image(source)["real_transparency"]
            )
        self.assertFalse(
            (self.results / "source" / "test_icon.png").exists()
        )
        self.assertEqual(self.run_script(), 0)
        self.assertEqual(len(self.server.graphs), 3)
        report = r.load_json(self.results / "reports" / "latest_run.json")
        self.assertEqual(report["reused"], 3)
        self.assertEqual(report["generated"], 0)

    def test_reconstruct_missing_preview_without_generation(self):
        self.assertEqual(self.run_script(), 0)
        preview = self.results / "preview_120" / "test_icon_2.png"
        preview.unlink()
        self.assertEqual(self.run_script(), 0)
        self.assertTrue(preview.exists())
        self.assertEqual(len(self.server.graphs), 3)

    def test_changed_prompt_refuses_overwrite(self):
        self.assertEqual(self.run_script(), 0)
        data = [example()]
        data[0]["positive_prompt"] = "A different item."
        r.save_json(self.prompts, data)
        self.assertEqual(self.run_script(), 1)
        self.assertEqual(len(self.server.graphs), 3)

    def test_explicit_overwrite(self):
        self.assertEqual(self.run_script(), 0)
        self.assertEqual(self.run_script(["--overwrite"]), 0)
        self.assertEqual(len(self.server.graphs), 6)

    def test_history_recovery_without_resubmitting(self):
        self.assertEqual(self.run_script(), 0)
        path = self.results / "metadata" / "test_icon_2.json"
        data = r.load_json(path)
        data["phase"] = "queued"
        r.save_json(path, data)
        (self.results / "source" / "test_icon_2.png").unlink()
        self.assertEqual(self.run_script(), 0)
        self.assertEqual(len(self.server.graphs), 3)
        self.assertTrue(
            (self.results / "source" / "test_icon_2.png").exists()
        )

    def test_timeout_stops_after_one_request_and_targets_id(self):
        self.server.behaviour = "timeout"
        self.assertEqual(self.run_script(["--timeout", "0.07"]), 1)
        self.assertEqual(len(self.server.graphs), 1)
        self.assertEqual(
            self.server.interrupts, [{"prompt_id": "mock-1"}]
        )
        self.assertEqual(self.server.deletions, [])
        self.assertFalse((self.results / ".runner.lock").exists())

    def test_execution_error_stops_batch(self):
        self.server.behaviour = "error"
        self.assertEqual(self.run_script(), 1)
        self.assertEqual(len(self.server.graphs), 1)

    def test_validation_error_does_not_blindly_retry(self):
        self.server.behaviour = "rejected"
        self.assertEqual(self.run_script(), 1)
        self.assertEqual(len(self.server.graphs), 1)
        self.assertEqual(self.run_script(), 1)
        self.assertEqual(len(self.server.graphs), 1)

    def test_busy_queue_untouched(self):
        self.server.running = [[0, "someone-else", {}, {}, []]]
        self.assertEqual(self.run_script(), 1)
        self.assertEqual(self.server.graphs, [])
        self.assertEqual(self.server.interrupts, [])
        self.assertEqual(self.server.deletions, [])

    def test_missing_model_stops_before_submission(self):
        self.server.missing_model = True
        self.assertEqual(self.run_script(), 1)
        self.assertEqual(self.server.graphs, [])

    def test_server_check_has_no_generation(self):
        self.assertEqual(self.run_script(["--check-server"]), 0)
        self.assertEqual(self.server.graphs, [])

    def test_require_alpha_accepts_transparent_output(self):
        self.assertEqual(self.run_script(["--require-alpha"]), 0)
        self.assertEqual(len(self.server.graphs), 3)

    def test_pending_cancel_only_own_id(self):
        self.server.pending = [
            [0, "own", {}, {}, []],
            [1, "other", {}, {}, []],
        ]
        client = r.ComfyClient(self.server.url, "client")
        client.cancel_own("own")
        self.assertEqual(self.server.deletions, [{"delete": ["own"]}])
        self.assertEqual(self.server.pending[0][1], "other")
        self.assertEqual(self.server.interrupts, [])


if __name__ == "__main__":
    unittest.main()
