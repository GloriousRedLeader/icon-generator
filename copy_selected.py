#!/usr/bin/env python3

import argparse
import json
import shutil
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CHOICES = SCRIPT_DIR / "icon_review_choices.json"


def main():
    parser = argparse.ArgumentParser(
        description="Copy selected resized icons into ./staging."
    )
    parser.add_argument(
        "choices",
        nargs="?",
        type=Path,
        default=DEFAULT_CHOICES,
        help="Choices JSON file (default: icon_review_choices.json next to this script)",
    )
    args = parser.parse_args()

    choices_path = args.choices.resolve()

    with choices_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    repo_dir = choices_path.parent
    generated_root = repo_dir / data.get("generated_root_folder", "generated_icons")

    staging_dir = repo_dir / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    copied = 0

    for item in data.get("selections", []):
        preview_rel = item.get("preview_relative_path")
        output_name = item.get("original_filename")

        if not preview_rel or not output_name:
            print(
                f"Skipping incomplete selection: "
                f"{item.get('selected_candidate', '<unknown>')}"
            )
            continue

        source = generated_root / preview_rel
        destination = staging_dir / output_name

        if not source.is_file():
            raise FileNotFoundError(f"Selected preview not found: {source}")

        shutil.copy2(source, destination)
        print(f"{source} -> {destination}")
        copied += 1

    print(f"Copied {copied} selected icon(s) to {staging_dir}")


if __name__ == "__main__":
    main()