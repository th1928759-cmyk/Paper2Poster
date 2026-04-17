from utils.poster_eval_utils import get_poster_text

from pathlib import Path
import argparse
import os

def write_poster_texts(root_folder: str | Path) -> dict:
    """
    For each immediate subfolder of `root_folder`, look for a file named `poster.png`.
    If found, call `get_poster_text(path)` and save the returned text to `poster_text.md`
    in that same subfolder.

    Returns a summary dict with counts and any errors.
    """
    root = Path(root_folder)
    processed = 0
    missing = 0
    errors: list[tuple[Path, str]] = []

    for subdir in root.iterdir():
        if not subdir.is_dir():
            continue
        if os.path.exists(subdir / "poster_text.md"):
            print(f"Skipping {subdir.name} as poster_text.md already exists.")
            continue
        print(f"Processing {subdir.name}...")

        poster_path = subdir / "poster.png"
        if not poster_path.exists():
            print(f"Missing poster.png in {subdir.name}.")
            missing += 1
            continue

        try:
            text = get_poster_text(poster_path, False)  # assumes this function is available
            out_path = subdir / "poster_text.md"
            # Ensure we always write UTF-8 with a trailing newline.
            Path(out_path).write_text((text or "").rstrip() + "\n", encoding="utf-8")
            processed += 1
        except Exception as e:  # keep going even if one folder fails
            errors.append((poster_path, str(e)))

    return {
        "processed": processed,
        "missing_poster_png": missing,
        "errors": errors,
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract poster texts from images.")
    parser.add_argument("--root_folder", type=str, help="Root folder containing subfolders with posters.")
    args = parser.parse_args()

    result = write_poster_texts(args.root_folder)
    print(f"Processed {result['processed']} posters.")
    print(f"Missing poster.png files: {result['missing_poster_png']}")
    if result['errors']:
        print("Errors encountered:")
        for path, error in result['errors']:
            print(f"  {path}: {error}")