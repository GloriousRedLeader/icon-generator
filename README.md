# DNG Icons v2

## What to use

The two working files are:

- `generate_icons_comfy_v2.py` — the complete runner, with your working four-step FLUX API workflow included inside it.
- `prompts_cartoon_v2.json` — all **121 targets from your supplied `prompts_full.json`**, rewritten for the outlined, dimensional cartoon style of the gauntlet example.

The `reference/` and `tests/` folders are documentation and verification material. They are not additional workflows to load.

**Do not drag these files onto the ComfyUI canvas. Do not press ComfyUI's Run button for the scripted batch.** Keep ComfyUI open; run the Python script in Terminal. The script submits jobs to your existing local ComfyUI server.

## Start here

1. Extract `DNG_Icons_v2.zip` into Downloads. Keep the extracted folder name `DNG_Icons_v2`.
2. Open ComfyUI and let any existing run finish. Do not change its model files or install another model.
3. Open Terminal and enter:

```bash
cd ~/Downloads/DNG_Icons_v2
```

First, check the entire plan without generating images:

```bash
python3 generate_icons_comfy_v2.py --dry-run
```

This should report **121 icons, 363 candidate images**, using seeds **101, 1012, 103**.

Generate just the first icon's three candidates:

```bash
python3 generate_icons_comfy_v2.py --limit 1
```

The first icon in the file is Aegis Knuckles. This creates `aegis_knuckles_1.png`, `aegis_knuckles_2.png`, and `aegis_knuckles_3.png`.

To run the full prompt file:

```bash
python3 generate_icons_comfy_v2.py
```

The full command processes every manifest entry, including the entries marked `complete` in the old migration. All output is kept in a separate candidate folder. It never writes to the repository paths stored in the prompt metadata. Completed, unchanged v2 candidates are verified and skipped, so the first three images need not be regenerated after the small test.

To run one specific icon instead:

```bash
python3 generate_icons_comfy_v2.py --only frostweave_gloves
```

This is still three candidates of that icon, not three copies of the same seed.

### Python requirement

Use Python 3.10 or later and Pillow. Pillow was already a dependency of your original runner. If your Terminal Python does not have it, use the same environment that ran the original script, or install it into this Python environment:

```bash
python3 -m pip install Pillow
```

The runner does not import PyTorch, load diffusion weights, or run image generation itself. The existing ComfyUI process does that work. It needs no API key, Hugging Face requests, or paid service.

## Three seeds, three images total per icon

The defaults are exactly the numbers requested:

| Suffix | Seed |
| --- | ---: |
| `_1.png` | 101 |
| `_2.png` | 1012 |
| `_3.png` | 103 |

`1012` has intentionally not been changed to `102`.

For `frostweave_gloves.png`, the saved candidate names are:

```text
frostweave_gloves_1.png
frostweave_gloves_2.png
frostweave_gloves_3.png
```

Each candidate is a separate API request with `batch_size = 1`. The script waits for it, saves it, then submits the next seed. It does not ask for a three-image batch for each seed, and it does not queue all 363 images at once.

### The fixed seed in the canvas is not a lock

In this workflow the seed belongs to the `RandomNoise` node, input `noise_seed`. The runner writes 101, 1012, or 103 into a copy of that graph before submitting it. The canvas's `control after generate = fixed` setting does not override the value supplied by the API.

The code also follows the positive text encoder's input to the large `PrimitiveStringMultiline` prompt box. It replaces that box's value, rather than searching for the old SDXL `KSampler` or relying on misleading node titles.

## Model and settings

The embedded graph preserves the actual working values in your uploaded API export:

| Setting | Value |
| --- | --- |
| Diffusion model | `flux-2-klein-4b.safetensors` — distilled, not Base |
| Text encoder | `qwen_3_4b.safetensors`, type `flux2` |
| VAE | `flux2-vae.safetensors` |
| Steps | 4 |
| CFG | 1 |
| Sampler | Euler |
| Size | 1024 × 1024 |
| Latent batch size | 1 |
| Negative prompt | Empty |
| Input/reference images | None |

The old titles saying “BASE,” “50,” or “cfg = 4” are not actual settings. They were corrected inside the embedded copy without changing the working generation values.

The script checks that the required nodes and selected model filenames exist on your running server before submitting a job. It does not download, rename, or substitute models.

An optional `--workflow path/to/export.json` accepts a single-output **API-format export** of this FLUX architecture. It is unnecessary for the supplied package. A visual-editor JSON, SDXL graph, Base model, or unexpected 50-step recipe is rejected rather than silently used. Nonstandard model/settings require the explicit `--allow-nonstandard-workflow` flag.

## Where the results go

After a run, open:

```text
generated_icons_v2/review.html
```

It is an ordinary local web page. It shows the saved candidates for the current command's selection and their small previews; clicking a candidate opens the full-resolution source. Do not judge a scripted run from the old picture still displayed in a manually opened ComfyUI canvas tab.

Files are organized as:

```text
generated_icons_v2/
    source/          Exact PNG bytes downloaded from ComfyUI, normally 1024 × 1024
    preview_120/     120 × 120 Lanczos resizes of those same images
    metadata/        One JSON record per candidate, including seed and full submitted graph
    reports/         Timestamped run reports and latest_run.json
    review.html      Local visual review page
```

The exact `_1`, `_2`, `_3` names apply to the files managed by this script in `source/` and `preview_120/`. ComfyUI also retains its own native Save Image copies with its automatic counter; those native filenames are recorded in the metadata. The runner downloads the selected output and gives the managed copy the exact requested name.

## These are candidates, not approved production icons

The prompt set follows the requested cartoon treatment: strong dark outlines, chunky silhouettes, clean material boundaries, bright painted highlights, simple shaded planes, controlled magical accents, and item-appropriate angled compositions.

The prompts are specific to each item. A cloth glove remains cloth; a vambrace remains a forearm guard; a scroll remains parchment; the gauntlet example does not make everything metal armor. Equipment pairs use matching materials and cuffs. Handwear prompts explicitly separate four finger stalls from the thumb and describe plain caps rather than nail-shaped panels.

**None of that guarantees correct construction.** All generated results are marked `rendered-unreviewed` / `needs-visual-review`, not approved. Check the images for wrong objects, crossed or fused fingers, false nail panels, mismatched pairs, cropped silhouettes, and readability at game size. The software validates files and workflow values, not visual anatomy.

### Transparency

Your uploaded FLUX workflow decodes and saves an image without background removal. This package deliberately preserves that generation stage.

**A white background is not a transparent background.** The 120-pixel outputs are unreviewed previews, not final transparent game assets. The runner does no segmentation, masking, recoloring, cropping, alpha invention, or automatic asset installation. Source bytes are preserved exactly; previews are resizes only. It records whether real transparent pixels are present.

`--require-alpha` remains available for a deliberately supplied alpha-producing workflow, but it refuses the embedded opaque workflow before spending a generation. Background removal and approval remain separate from this candidate batch.

## Restarting, stopping, and protecting time

A normal rerun verifies existing candidates against their prompt, seed, graph settings, and file hashes, then skips matches. A missing local preview can be rebuilt from its source without another generation. A finished server job whose image was not downloaded can be recovered from ComfyUI history while that history remains available.

A changed prompt or seed set using the same suffix filenames is a conflict, not an automatic overwrite. Use a fresh output folder for a new revision:

```bash
python3 generate_icons_comfy_v2.py --only frostweave_gloves --output-root generated_icons_revision_2
```

`--overwrite` is an explicit request to regenerate and replace selected v2 candidate files. It still does not write to game assets.

The default wait limit is **300 seconds per submitted image**. This is a wait budget, not a promised runtime; server checks, model loading/submission and downloading also have bounded network waits. On a timeout or error the script stops the batch instead of continuing to queue more expensive work. When possible it requests cancellation for its own `prompt_id`; a GPU operation may not stop instantly, so check ComfyUI after a timeout.

Press **Control+C in Terminal** to stop. The script will not clear the entire ComfyUI queue. It refuses to start while other jobs are active.

A failed/unfinished submission is not blindly repeated. After checking ComfyUI and confirming that no old job is running, use:

```bash
python3 generate_icons_comfy_v2.py --retry-failed
```

Already completed matching candidates still skip. If a submission response was lost, a generation may have reached the server; check before deliberately retrying. If the process was forcibly killed, a `.runner.lock` may remain. Remove that lock only after confirming that no earlier runner is still active.

## Other useful commands

Check the server/model list, with no generation:

```bash
python3 generate_icons_comfy_v2.py --check-server
```

Use the old status filter deliberately:

```bash
python3 generate_icons_comfy_v2.py --only-status pending qa-failed deferred
```

Supply a different ordered seed set:

```bash
python3 generate_icons_comfy_v2.py --seeds 101 1012 103
```

The command-line seed list governs generation. The `generation_seeds` entries in the prompt file document the intended defaults; they do not silently override `--seeds`.

The legacy `--seed 101` option deliberately makes only one candidate per icon. `--limit` always counts icons. `--production-size` is retained as an alias for the local preview size; it does not mark the output production-ready.

For all options:

```bash
python3 generate_icons_comfy_v2.py --help
```

## Prompt sources and exact scope

Every one of the 121 entries in the supplied `prompts_full.json` was rewritten. Its filenames, semantic keys, display names, source IDs, repository target paths, prior migration status, recorded master SHA and authored context were preserved. The two example test files were treated as overlapping subsets, not additional targets.

The set represents 127 source IDs because three existing filenames intentionally serve more than one item. Those shared mappings have not been split into newly invented filenames.

The current `GloriousRedLeader/dng` master was checked at commit `b1fab46c2870c8fa9d102db66623c1fcbb1f44a7`, the same commit cited by the supplied manifest. Current Items.json, Abilities.json and the item-image directory were accessed, and selected identities were checked against those files. The supplied per-item `authored_context` remains the principal semantic basis. There was **not** a new exhaustive visual inspection of every repository PNG or a complete reread of every ability tier. Palette, construction and motif details in the new `visual_brief` are art-direction interpretations, not additional claims about gameplay mechanics.

The current item-image directory also contains **61 PNGs absent from the supplied full prompt manifest**. They are listed in `reference/source_audit.json`; they were not silently added to this 363-image batch. This delivery therefore covers the full supplied target manifest, not every image in the repository or every separate ability-upgrade icon.

The old `authored_context` and `migration_status` sometimes describe previously approved artwork. That historical metadata is retained for traceability only. It does not approve new v2 candidates.

## What was tested

The script was syntax-checked and exercised with unit tests and a local mock HTTP server. The mock creates simple test PNGs; it does not invoke diffusion or contact your ComfyUI installation. Tests cover seed mapping, linked prompt replacement, exact filenames, serial requests, missing models, resume, changed-prompt conflicts, server errors, timeout cancellation, and transparency guards.

```bash
python3 -m unittest discover -s tests -v
```

See `reference/validation_report.json` for the recorded results. The new prompts have not been rendered on your Mac or visually approved as a set.

## Technical references

- ComfyUI API routes: https://docs.comfy.org/development/comfyui-server/comms_routes
- RandomNoise implementation: https://github.com/comfyanonymous/ComfyUI/blob/master/comfy_extras/nodes_custom_sampler.py
- Queue/history/targeted interruption implementation: https://github.com/comfyanonymous/ComfyUI/blob/master/server.py
- Distilled model: https://huggingface.co/black-forest-labs/FLUX.2-klein-4B
- Item data at the checked commit: https://github.com/GloriousRedLeader/dng/blob/b1fab46c2870c8fa9d102db66623c1fcbb1f44a7/DNG.Common/Data/Items.json
- Ability data at the checked commit: https://github.com/GloriousRedLeader/dng/blob/b1fab46c2870c8fa9d102db66623c1fcbb1f44a7/DNG.Common/Data/Abilities.json
