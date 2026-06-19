"""Create reproducible gzip files suitable for committing to GitHub."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
from pathlib import Path


def compress(source: Path, destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    digest = hashlib.sha256()
    uncompressed_bytes = 0
    with source.open("rb") as input_handle, temporary.open("wb") as raw_output:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_output,
            compresslevel=9,
            mtime=0,
        ) as output_handle:
            while True:
                chunk = input_handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                uncompressed_bytes += len(chunk)
                output_handle.write(chunk)
    temporary.replace(destination)
    return {
        "source": str(source),
        "destination": str(destination),
        "uncompressed_bytes": uncompressed_bytes,
        "compressed_bytes": destination.stat().st_size,
        "sha256_uncompressed": digest.hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=Path("training/data/dapt"),
    )
    args = parser.parse_args()

    reports = []
    for split in ("train", "validation"):
        source = args.corpus_dir / f"{split}.jsonl"
        if not source.exists():
            raise FileNotFoundError(source)
        reports.append(compress(source, source.with_suffix(".jsonl.gz")))

    package_report = args.corpus_dir / "package_manifest.json"
    package_report.write_text(
        json.dumps(reports, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
