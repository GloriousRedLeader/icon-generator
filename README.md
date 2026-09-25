# Icon Generator

A local ComfyUI-based pipeline for generating reviewable fantasy-game inventory icon candidates.

The repository keeps the ComfyUI API workflow, Python runner, sample prompt manifest, review page, and tests separate. The runner submits one image at a time to an already-running local ComfyUI server; it does not download models or copy anything into a game's asset folders.

## Repository layout

```text
icon-generator/
├── generate_icons.py
├── icon_api_call.json
├── sample.prompts.json
├── icon_review.html
├── tests/
│   └── test_generate_icons.py
├── README.md
└── .gitignore
```

Your private/local prompt file should be named:

```text
prompts.json
```

`prompts.json` is intentionally ignored by Git so you can keep project-specific prompt data out of the public repository.

Generated files always go to:

```text
generated_icons/
```

That folder is also ignored by Git.

## Requirements

- Python 3.10 or later
- Pillow
- A running local ComfyUI server, defaulting to `http://127.0.0.1:8188`
- The models and custom nodes referenced by `icon_api_call.json`

The supplied workflow currently expects these model filenames:

- `flux-2-klein-4b.safetensors`
- `qwen_3_4b.safetensors`
- `flux2-vae.safetensors`
- `birefnet.safetensors`

It also expects the background-removal/alpha node classes used by the supplied API workflow, including `RemoveBackground`, `LoadBackgroundRemovalModel`, `InvertMask`, and `JoinImageWithAlpha`.

Install Pillow into the Python environment you use to run the script:

```bash
python3 -m pip install Pillow
```

## Quick start

Clone the repository and enter it:

```bash
git clone https://github.com/GloriousRedLeader/icon-generator.git
cd icon-generator
```

Create your local prompt file from the public example:

```bash
cp sample.prompts.json prompts.json
```

Edit `prompts.json` with your own icon names and prompts.

With ComfyUI already running, validate the plan without generating anything:

```bash
python3 generate_icons.py --dry-run
```

Check that the required ComfyUI nodes and model filenames are available without generating an image:

```bash
python3 generate_icons.py --check-server
```

Generate one icon's three candidates:

```bash
python3 generate_icons.py --limit 1
```

Generate the full prompt file:

```bash
python3 generate_icons.py
```

Generate one specific icon by filename stem, filename, or semantic key:

```bash
python3 generate_icons.py --only starfall_sabre
```

## Default candidates and seeds

By default, each icon is generated three times as three independent ComfyUI requests:

| Candidate | Seed |
| --- | ---: |
| `_1.png` | 101 |
| `_2.png` | 102 |
| `_3.png` | 103 |

For an input filename such as:

```text
starfall_sabre.png
```

the managed outputs are:

```text
starfall_sabre_1.png
starfall_sabre_2.png
starfall_sabre_3.png
```

You can deliberately supply a different ordered seed list:

```bash
python3 generate_icons.py --seeds 201 202 203
```

The `generation_seeds` field in a prompt manifest is metadata for humans and tools. The runner's command-line/default seed list controls generation.

## Output layout

The output directory is fixed to `generated_icons/`:

```text
generated_icons/
├── source/
├── preview_120/
├── metadata/
├── reports/
└── review.html
```

- `source/` contains the exact PNG bytes downloaded from ComfyUI.
- `preview_120/` contains 120×120 Lanczos previews.
- `metadata/` contains one JSON record per candidate, including the seed and submitted workflow.
- `reports/` contains run reports.
- `review.html` is the runner's simple generated gallery.

The command-line option for changing the output root has intentionally been removed so the repository has one predictable output layout.

## Standalone approval page

Open:

```text
icon_review.html
```

in a browser, then choose your local `generated_icons` folder.

The page displays each icon's candidate images in a row and lets you select one. It can copy or download a JSON document containing your choices, including candidate-relative paths and any `repository_target_path` present in your prompt metadata.

The review page does **not** copy, rename, or install game assets.

## Prompt file format

The prompt file is a JSON array. The runner requires:

- `filename` — a plain safe `.png` filename, not a path
- `positive_prompt` — a non-empty string
- `negative_prompt` — optional string; an empty string is valid

Additional metadata is preserved in each candidate's metadata file and can be useful to the review/export workflow.

See `sample.prompts.json` for three fictional examples.

A minimal entry looks like:

```json
{
  "filename": "example_sword.png",
  "semantic_key": "ui.item.example_sword",
  "display_name": "Example Sword",
  "repository_target_path": "Assets/Icons/Items/example_sword.png",
  "positive_prompt": "A hand-painted cartoon fantasy RPG inventory icon of one complete fantasy sword on a plain white background.",
  "negative_prompt": ""
}
```

## Resolution and speed

The default source size is 1024×1024.

You can request a smaller square size to reduce local generation cost:

```bash
python3 generate_icons.py --source-size 768
```

The runner accepts source sizes from 256 through 2048, in multiples of 16. Lower resolutions can be faster, but may reduce small structural detail.

The 120-pixel preview size can be changed separately:

```bash
python3 generate_icons.py --production-size 120
```

Despite the historical option name, these are review previews; the runner does not install production assets.

## Transparency

The supplied `icon_api_call.json` includes background removal and alpha joining before `SaveImage`.

`--require-alpha` does **not** perform another background-removal pass. It only verifies that the downloaded result contains real transparent pixels and fails the candidate if it does not:

```bash
python3 generate_icons.py --require-alpha
```

## Workflow file

The ComfyUI API graph is stored explicitly in:

```text
icon_api_call.json
```

It is not embedded inside `generate_icons.py`.

The runner uses that file by default. A different API-format workflow can be supplied deliberately:

```bash
python3 generate_icons.py --workflow path/to/workflow.json
```

The default validation expects the supplied four-step FLUX.2 Klein recipe. Use `--allow-nonstandard-workflow` only when you intentionally want different model/settings.

## Existing candidates and retries

A normal rerun verifies compatible existing candidate files and skips them rather than regenerating them.

If an existing candidate was generated from a different prompt/workflow/seed recipe, the runner refuses to silently replace it.

To deliberately regenerate selected candidates:

```bash
python3 generate_icons.py --only starfall_sabre --overwrite
```

If a previous submission failed or was interrupted, first make sure no old ComfyUI job is still active, then use:

```bash
python3 generate_icons.py --retry-failed
```

Press Control+C to stop a run. The runner does not clear unrelated ComfyUI jobs.

## Tests

The tests use a local mock HTTP server and do not invoke diffusion:

```bash
python3 -m unittest discover -s tests -v
```

They cover the public file layout, workflow topology, prompt replacement, seed mapping, size overrides, output naming, resume behavior, overwrite protection, timeout handling, model validation, and alpha verification.

## Safety of repository writes

The generator never writes to the `repository_target_path` values in a prompt file. Those paths are metadata only.

The generator writes only under `generated_icons/` plus ComfyUI's own normal output location. The standalone review page only exports selection metadata.
