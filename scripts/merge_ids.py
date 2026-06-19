#!/usr/bin/env python3
"""
Script to merge multiple JSON ID lists into one output JSON file.
"""

import argparse
import json
from pathlib import Path
from typing import Iterable, List


def _load_ids(file_path: Path) -> List[str]:
    """Load a JSON file and return its list content."""
    print(f"Loading {file_path}...")
    with open(file_path, "r", encoding="utf-8") as f:
        ids = json.load(f)

    if not isinstance(ids, list):
        raise ValueError(f"Expected a JSON list in {file_path}, got {type(ids).__name__}")

    print(f"  Loaded {len(ids):,} IDs")
    return ids


def merge_id_files(input_files: Iterable[Path], output_path: Path) -> None:
    """Merge multiple ID JSON files into a single output JSON file."""
    all_ids: List[str] = []

    for file_path in input_files:
        all_ids.extend(_load_ids(file_path))

    print(f"\nTotal IDs before deduplication: {len(all_ids):,}")

    # Remove duplicates while preserving original encounter order.
    seen = set()
    unique_ids = []
    for id_val in all_ids:
        if id_val not in seen:
            seen.add(id_val)
            unique_ids.append(id_val)

    print(f"Total unique IDs: {len(unique_ids):,}")
    print(f"Duplicates removed: {len(all_ids) - len(unique_ids):,}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Save merged IDs
    print(f"\nSaving to {output_path}...")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(unique_ids, f, ensure_ascii=False, indent=2)

    print(f"✓ Successfully created {output_path}")
    print(f"  Total IDs: {len(unique_ids):,}")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the merge script."""
    parser = argparse.ArgumentParser(
        description="Merge multiple JSON files containing lists of IDs into one output file."
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_files",
        type=Path,
        nargs="+",
        required=True,
        help="Input JSON file paths to merge (space-separated).",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output_file",
        type=Path,
        required=True,
        help="Output JSON file path.",
    )
    return parser.parse_args()


def main() -> None:
    """Entrypoint for CLI execution."""
    args = parse_args()
    merge_id_files(args.input_files, args.output_file)


if __name__ == "__main__":
    main()
