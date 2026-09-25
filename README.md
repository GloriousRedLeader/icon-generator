# Icon Generator

Icon Generator is a local batch tool for creating multiple game-icon candidates through ComfyUI, reviewing them at game UI size, and exporting your approval choices.

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

The default local review image is 120 × 120:

```bash
python3 generate_icons.py --target-size 120
```

This does not change the model generation resolution. It changes the resized review copy written after generation.

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
| `--target-size` | Square size of the local review image. Default 120. |
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
├── preview_120/
├── metadata/
├── reports/
└── review.html
```

If you use a different target size, the preview folder follows that value, for example:

```text
preview_96/
preview_120/
preview_256/
```

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

If existing output belongs to a different prompt, seed, workflow, generation size, or target size, the runner refuses to silently replace it.

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

Open it directly in your browser.

Choose the generated folder:

```text
generated_icons/
```

The review page:

- groups candidates by icon name
- displays the candidate set in a row
- prefers the resized `preview_<size>` images for visual review
- shows seed and available metadata
- lets you click one candidate to select it
- tracks how many icons have been selected
- can jump to the next unselected icon
- can import an earlier choices JSON
- can copy the current choices to the clipboard
- can download the choices as JSON

The exported JSON includes the selected candidate path and, when supplied in your prompt metadata, the intended `repository_target_path`.

The review tool **does not copy or modify game assets**. Its only job is to record your selections so another script, tool, or AI can perform a separate installation step.

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
