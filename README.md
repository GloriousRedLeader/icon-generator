# Icon Generator

Icon Generator is a local batch tool for creating multiple game-icon candidates through ComfyUI, reviewing them at game UI size, and exporting your approval choices.

## Why This Exists

This project exists because asking Gemini, ChatGPT, or Claude to produce a hundred consistently sized game icons is apparently the computational equivalent of asking three extremely confident interns to assemble a nuclear reactor from a Pinterest board. They can generate one beautiful image, explain image dimensions at tremendous length, and then immediately forget both the dimensions and the image. Ask for a large batch and, somewhere around icon 17, filenames mutate, aspect ratios wander off, transparency becomes a philosophical question, and the entire operation develops the administrative stability of a collapsing government. Icon Generator was created so the computer can do the same boring thing correctly hundreds of times without needing to be reminded what “120×120” means.

The current default review target is `96 × 96`; the line above is retained as the historical joke that caused this project to exist.

It is designed for workflows where you have a JSON list of item names and image prompts and want a repeatable way to:

- generate several candidates for every icon
- keep the exact generated source PNGs
- create smaller review copies
- preserve metadata such as prompt, seed, and workflow
- review candidate sets in a browser
- export your selected choices as JSON

The tool does **not** copy anything into your game's asset folders. Generation and review are intentionally separate from asset installation.

## Repository contents

```text
icon-generator/
├── generate_icons.py       Main batch generator
├── workflow.json           ComfyUI API-format workflow
├── sample.prompts.json     Three fictional example prompts
├── icon_review.html        Standalone review / approval tool
├── tests/
│   └── test_generate_icons.py
├── README.md
└── .gitignore
```

Your own prompt file is normally:

```text
prompts.json
```

That file is ignored by Git so project-specific prompts do not need to be published.

Generated files always go under:

```text
generated_icons/
```

That folder is also ignored by Git.

---

## Minimum requirements

The baseline configuration this repository is currently documented against is:

- Apple Silicon M1-class machine
- 32 GB unified memory
- macOS
- Python 3.10 or newer
- Pillow
- a working local ComfyUI installation

A faster Apple Silicon machine or a suitable CUDA system may also work, but those configurations are not the current reference setup for this repository.

Lower-memory machines may work with smaller generation sizes, but they are not the documented minimum for the supplied workflow.

You also need enough disk space for ComfyUI and the model files referenced by `workflow.json`. The model files are **not** included in this repository.

---

## Setup

Clone the repository:

```bash
git clone https://github.com/GloriousRedLeader/icon-generator.git
cd icon-generator
```

Install Pillow into the Python environment you will use to run the generator:

```bash
python3 -m pip install Pillow
```

Create your private prompt file from the sample:

```bash
cp sample.prompts.json prompts.json
```

Edit `prompts.json` and replace the fictional examples with your own items and prompts.

Before generating anything, make sure ComfyUI is running.

Then validate the local setup:

```bash
python3 generate_icons.py --check-server
```

You can also validate the prompt list and planned outputs without contacting ComfyUI:

```bash
python3 generate_icons.py --dry-run
```

---

## ComfyUI setup

The generator talks to an already-running ComfyUI server. By default it expects:

```text
http://127.0.0.1:8188
```

The supplied `workflow.json` currently uses:

- `flux-2-klein-4b.safetensors`
- `qwen_3_4b.safetensors`
- `flux2-vae.safetensors`
- `birefnet.safetensors`

The workflow also uses background-removal / alpha-related node classes including:

- `RemoveBackground`
- `LoadBackgroundRemovalModel`
- `InvertMask`
- `JoinImageWithAlpha`

Those models and nodes must already be available in your ComfyUI installation. The Python runner does not download or install them.

If a required node or model is missing, this command should report it before generation:

```bash
python3 generate_icons.py --check-server
```

### What the runner changes in the workflow

For each candidate, `generate_icons.py` loads `workflow.json` and changes only the values needed for that request:

- positive prompt
- negative prompt
- seed
- generation width and height
- batch size, fixed to one image
- output filename prefix

The model, sampler, steps, CFG, VAE, text encoder, background removal, and other workflow settings come from `workflow.json`.

The runner no longer locks the workflow to one exact model recipe. You can change the model/settings in `workflow.json`, provided the workflow keeps the node structure the runner expects for prompt, seed, size, sampling, and output discovery.

`workflow.json` is an **API-format** ComfyUI workflow. The runner consumes it directly.

---

## Prompt file format

The prompt file is a JSON array.

The required fields for each entry are:

- `filename` — plain PNG filename, for example `starfall_sabre.png`
- `positive_prompt` — the generation prompt

`negative_prompt` is optional and may be an empty string.

Useful optional metadata includes:

- `display_name`
- `semantic_key`
- `repository_target_path`
- any other project-specific fields you want preserved in candidate metadata

Example:

```json
[
  {
    "filename": "starfall_sabre.png",
    "semantic_key": "ui.item.starfall_sabre",
    "display_name": "Starfall Sabre",
    "repository_target_path": "Assets/Icons/Items/starfall_sabre.png",
    "positive_prompt": "A hand-painted cartoon fantasy RPG inventory icon of one elegant curved steel sabre on a clean white background.",
    "negative_prompt": ""
  }
]
```

See `sample.prompts.json` for three complete fictional examples.

If your prompt JSON contains a `generation_seeds` metadata field, it is preserved as metadata only. Actual generation seeds are controlled by the runner's `--seeds` option.

---

## Basic usage

### Generate everything

```bash
python3 generate_icons.py
```

By default, every icon gets three candidates using seeds:

```text
101
102
103
```

For:

```text
starfall_sabre.png
```

the generator creates managed candidate names:

```text
starfall_sabre_1.png
starfall_sabre_2.png
starfall_sabre_3.png
```

### Generate one icon

You can select an icon by filename, filename stem, or semantic key:

```bash
python3 generate_icons.py --only starfall_sabre
```

### Generate only the first N icons

For a quick test:

```bash
python3 generate_icons.py --limit 1
```

Or:

```bash
python3 generate_icons.py --limit 10
```

### Change the number of candidates

`--seeds` accepts one or more seed values.

One candidate per icon:

```bash
python3 generate_icons.py --seeds 101
```

Three candidates:

```bash
python3 generate_icons.py --seeds 101 102 103
```

Five candidates:

```bash
python3 generate_icons.py --seeds 101 102 103 104 105
```

One candidate is generated for each supplied seed.

### Use a smaller generation size

The default generation size is 1024 × 1024.

For faster generation on constrained hardware:

```bash
python3 generate_icons.py --generation-size 768
```

Or:

```bash
python3 generate_icons.py --generation-size 640
```

The generation size must be a multiple of 16 between 256 and 2048.

### Change the review target size

The default local review image is 96 × 96:

```bash
python3 generate_icons.py --target-size 96
```

This does not change the model generation resolution. It changes the resized review copy written after generation.

Changing only `--target-size` does not require regenerating the AI source image. The runner reuses the existing generated source and rebuilds the derived review image at the new size.

### Require transparency

The supplied workflow performs background removal and joins an alpha channel.

To make the runner reject a result that does not contain real transparent pixels:

```bash
python3 generate_icons.py --require-alpha
```

This flag is a validation check. It does not run an additional background-removal pass.

### Use a different ComfyUI address

```bash
python3 generate_icons.py --comfy-url http://127.0.0.1:8188
```

### Use a different compatible workflow file

```bash
python3 generate_icons.py --workflow /path/to/workflow.json
```

---

## Command-line options

| Argument | What it does |
| --- | --- |
| `prompt_file` | Prompt JSON file. Defaults to `prompts.json` beside the script. |
| `--workflow` | ComfyUI API workflow. Defaults to `workflow.json`. |
| `--comfy-url` | Address of the running ComfyUI server. |
| `--seeds` | Seed values. One candidate is generated per seed. |
| `--only` | Generate only specific filenames, filename stems, or semantic keys. |
| `--limit` | Process only the first N matching icons. |
| `--generation-size` | Square resolution sent to the image model. Default 1024. |
| `--target-size` | Square size of the local review image. Default 96. |
| `--overwrite` | Deliberately regenerate and replace selected existing candidates. |
| `--require-alpha` | Fail a candidate if the downloaded PNG has no real transparency. |
| `--dry-run` | Validate and print the generation plan without contacting ComfyUI. |
| `--check-server` | Validate the workflow, required ComfyUI nodes, models, and queue without generating. |
| `--version` | Print the runner version. |

The ComfyUI status poll interval is fixed internally at one second. It is intentionally not configurable.

There is no generation-duration timeout. Once a candidate has been submitted, the runner waits until ComfyUI finishes, reports an error, the connection repeatedly fails, or you interrupt the process.

---

## Output

Generated files are always stored under:

```text
generated_icons/
├── source/
├── preview_96/
├── metadata/
├── reports/
└── review.html
```

If you generate more than one target size over time, multiple preview folders can coexist, for example:

```text
preview_96/
preview_120/
preview_256/
```

Changing only `--target-size` reuses the existing generated source PNGs and creates or rebuilds the corresponding `preview_<size>/` folder. It does not rerun the image model.

### `source/`

Contains the exact PNG bytes downloaded from ComfyUI.

### `preview_<size>/`

Contains resized review copies using high-quality Lanczos resampling.

### `metadata/`

Contains one JSON file per candidate, including information such as:

- seed
- prompt entry
- submitted workflow
- source and preview paths
- image dimensions
- transparency information
- hashes
- timing

### `reports/`

Contains run summaries, including `latest_run.json`.

### `review.html`

A simple gallery generated by the Python runner.

---

## Failure and resume behavior

The generator processes candidates sequentially.

If a generation or runtime operation fails, the batch stops immediately. It does not continue submitting later candidates after a failure.

Successfully completed candidates are kept.

When you run the command again:

- matching completed candidates are verified and reused
- missing review copies can be rebuilt from an existing source image
- completed ComfyUI history can be recovered when available
- candidates explicitly recorded as failed or interrupted can be attempted again
- an uncertain prior submission is **not** blindly duplicated

This is designed to protect long batches from wasting completed work.

If an existing source candidate belongs to a different prompt, seed, workflow, or generation size, the runner refuses to silently replace it. A different `--target-size` is safe because it changes only the derived review image, not the generated source.

To deliberately replace selected candidates:

```bash
python3 generate_icons.py --only starfall_sabre --overwrite
```

Press Control+C to stop the current run. The runner does not clear unrelated ComfyUI jobs.

---

## Reviewing and approving icons

The repository includes a standalone browser review tool:

```text
icon_review.html
```

Open that file directly in your browser.

### 1. Load the top-level generated folder

Click **1. Load generated_icons folder** and choose:

```text
generated_icons/
```

Choose the top-level folder, not an individual `preview_<size>` folder. The review tool needs the top-level folder so it can read the selected preview images together with their metadata and full-resolution source paths.

### 2. Choose exactly one preview dimension

The page detects every available preview folder, such as:

```text
preview_96/
preview_120/
preview_256/
```

If more than one exists, the **2. Choose preview folder** menu requires you to choose the exact dimension you want to review.

For example:

```text
preview_96 (96 × 96)
```

The review page displays **only that one preview dimension**. It does not mix sizes and does not silently substitute the full-resolution source image when a preview is missing.

If only one preview folder exists, the page selects it automatically.

Changing the selected preview folder clears the current on-page selections. This is intentional: each approval pass belongs to one exact image dimension.

### 3. Review and select candidates

For the selected preview dimension, the page:

- groups candidates by icon name
- dynamically detects every numbered candidate present for an icon, so `_1` through `_5`, `_10`, or any other generated count are shown
- displays the complete candidate set in one horizontally scrollable row
- shows the active review dimension in the status line
- shows seed and available metadata
- lets you click one candidate per icon
- tracks selected versus total icons
- can jump to the next unselected icon
- can import an earlier choices JSON after a preview dimension has been selected
- can copy the current choices JSON to the clipboard
- can download the choices as JSON

### 4. Export the approval metadata

The exported JSON records the dimension that was actually reviewed:

```json
{
  "review_preview_folder": "preview_96",
  "review_target_size": 96
}
```

Each selected icon also records its selected preview path, matching full-resolution source path when available, metadata path, seed, and `repository_target_path` when that field was supplied in the prompt file.

The review tool **does not copy, rename, resize, or modify game assets**. Its only job is to record which candidate you approved at one specific preview dimension so another script, tool, or AI can perform a separate installation step.

To compare 96 × 96 against 120 × 120, review and export one dimension first, then switch the selector and perform a separate review pass for the other dimension.

---

## Recommended first run

After setup:

```bash
cp sample.prompts.json prompts.json
python3 generate_icons.py --dry-run
python3 generate_icons.py --check-server
python3 generate_icons.py --limit 1 --generation-size 768 --require-alpha
```

Review the three generated candidates before committing to a large batch.

When the setup looks correct:

```bash
python3 generate_icons.py --generation-size 768 --require-alpha
```

---

## Tests

The included tests use a local mock ComfyUI server. They do not run a diffusion model.

Run:

```bash
python3 -m unittest discover -s tests -v
```

---

## What this project does not do

Icon Generator does not:

- download AI models
- install ComfyUI or custom nodes
- send prompts to a paid cloud API
- copy approved icons into a game repository
- modify paths listed in `repository_target_path`
- automatically decide which generated icon is best

It generates candidates, records metadata, and gives you a review/approval workflow.

---

## License

Icon Generator is released under the [MIT License](LICENSE).

You may use, modify, redistribute, sublicense, and include this project's code in commercial or closed-source software, subject to the MIT License notice requirements.

Third-party software, ComfyUI custom nodes, and model weights used with this project are **not** relicensed by this repository. ComfyUI, FLUX, Qwen, BiRefNet, and any other external models or dependencies remain subject to their own licenses and terms.

