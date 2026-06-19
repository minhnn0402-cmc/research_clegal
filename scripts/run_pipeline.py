"""
Production end-to-end pipeline orchestrator.

Runs `collect IDs -> enrich law_docs.csv -> build graph` as a single,
schedulable entry point. Each step stays independently runnable (this script
only wires them together): `scripts/get_doc_ids.py` discovers new document
IDs, `LawDocsEnrichmentService` appends newly-discovered law documents to
`data/law_docs.csv`, and `main.py` builds the knowledge graph.

Usage:
    # Daily incremental run (only newly-discovered IDs)
    python scripts/run_pipeline.py --mode incremental --neo4j-env PROD ...

    # Full rebuild (all known central + local IDs)
    python scripts/run_pipeline.py --mode full --neo4j-env PROD ...

    # Custom ID set (bypasses collect + enrich entirely)
    python scripts/run_pipeline.py --doc-ids-file ./data/my_ids.json --neo4j-env DEV
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.get_doc_ids import get_doc_ids
from src.infrastructure.config import AppConfig
from src.infrastructure.connections import ConnectionManager
from src.services.law_docs_enrichment_service import LawDocsEnrichmentService

DOC_IDS_OUTPUT_PATH = _PROJECT_ROOT / "data" / "doc_ids.json"
LAW_DOCS_CSV_PATH = _PROJECT_ROOT / "data" / "law_docs.csv"

# `--doc-ids-file` value swapped per `--mode`; everything else forwarded as-is
# to `main.py` (only when the user explicitly sets it, so main.py's own
# defaults still apply otherwise).
_PASS_THROUGH_VALUE_FLAGS = (
    "--suffix",
    "--extraction-batch-size",
    "--extraction-parallel-workers",
    "--mongo-extraction-collection",
    "--graph-batch-size",
    "--graph-parallel-workers",
    "--neo4j-db",
    "--neo4j-env",
    "--graph-audit-output",
    "--graph-resolution-mode",
    "--node-batch-size",
    "--structural-rel-batch-size",
    "--status-rel-batch-size",
    "--inferred-rel-batch-size",
    "--tvpl-batch-size",
    "--luoc-do-batch-size",
    "--orphan-node-batch-size",
)
_PASS_THROUGH_STORE_TRUE_FLAGS = (
    "--with-tvpl",
    "--with-luoc-do-export",
    "--reconcile-after-build",
    "--clear-es-cache",
    "--clear-checkpoints",
    "--delete-orphan-nodes",
    "--use-llm",
)



def _flag_to_dest(flag: str) -> str:
    return flag.lstrip("-").replace("-", "_")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Production pipeline: collect IDs -> enrich law_docs.csv -> build graph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--mode", choices=["full", "incremental"],
        help=(
            "full: build data/doc_ids.json from central_ids.json + local_ids.json; "
            "incremental: build it from latest_central_ids.json + latest_local_ids.json"
        ),
    )
    source_group.add_argument(
        "--doc-ids-file", type=str,
        help="Custom doc-ids JSON file. Bypasses collect + enrich entirely and is forwarded to main.py as-is.",
    )

    parser.add_argument("--skip-collect", action="store_true",
                        help="Skip ID collection; reuse the existing local doc_ids/*.json files (ignored with --doc-ids-file)")
    parser.add_argument("--skip-enrich", action="store_true",
                        help="Skip law_docs.csv enrichment (ignored with --doc-ids-file)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the planned steps and main.py command without making any changes")

    pass_through_group = parser.add_argument_group("Pass-through to main.py (forwarded only when set)")
    for flag in _PASS_THROUGH_VALUE_FLAGS:
        if flag == "--neo4j-env":
            pass_through_group.add_argument(flag, type=str, choices=["DEV", "PROD"], default=None)
        elif flag == "--graph-resolution-mode":
            pass_through_group.add_argument(flag, type=str, choices=["strict", "permissive"], default=None)
        elif flag in ("--suffix", "--mongo-extraction-collection", "--neo4j-db", "--graph-audit-output"):
            pass_through_group.add_argument(flag, type=str, default=None)
        else:
            pass_through_group.add_argument(flag, type=int, default=None)
    for flag in _PASS_THROUGH_STORE_TRUE_FLAGS:
        pass_through_group.add_argument(flag, action="store_true")

    return parser


def _load_ids(path) -> List[int]:
    path = Path(path)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _dedup_preserve_order(*id_lists: Sequence[int]) -> List[int]:
    seen = set()
    result = []
    for ids in id_lists:
        for doc_id in ids:
            if doc_id not in seen:
                seen.add(doc_id)
                result.append(doc_id)
    return result


def _assemble_doc_ids(mode: str, file_paths: Dict[str, str], output_path: Path) -> List[int]:
    """Build `doc_ids.json` per `--mode`, deduping across the two source files."""
    source_keys = ("central_ids", "local_ids") if mode == "full" else ("latest_central_ids", "latest_local_ids")
    sources = [file_paths[key] for key in source_keys]
    ids = _dedup_preserve_order(*[_load_ids(path) for path in sources])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(ids, f, ensure_ascii=False, indent=2)
    return ids


def _get_cls_collection(conn_manager: ConnectionManager):
    conn_manager.register_mongo_from_env("cls_mongo", "MONGO_PROD")
    cfg = AppConfig()
    return conn_manager.get_mongo_collection("cls_mongo", cfg.cls_collection, cfg.cls_database)


def _build_main_argv(doc_ids_file, ns: argparse.Namespace) -> List[str]:
    """Assemble main.py argv: swap `--doc-ids-file`, replace `--clear-before-build`
    with `--reset-relations`, forward every pass-through flag the user set."""
    argv = ["--doc-ids-file", str(doc_ids_file), "--reset-relations"]

    for flag in _PASS_THROUGH_VALUE_FLAGS:
        value = getattr(ns, _flag_to_dest(flag))
        if value is not None:
            argv.extend([flag, str(value)])
    for flag in _PASS_THROUGH_STORE_TRUE_FLAGS:
        if getattr(ns, _flag_to_dest(flag)):
            argv.append(flag)

    return argv


def _collect_ids(ns: argparse.Namespace, conn_manager: ConnectionManager) -> Optional[Dict[str, str]]:
    if ns.skip_collect:
        print("[PIPELINE] --skip-collect set: reusing existing data/doc_ids/*.json files")
        return {
            "central_ids": "./data/doc_ids/central_ids.json",
            "local_ids": "./data/doc_ids/local_ids.json",
            "law_ids": "./data/doc_ids/law_ids.json",
            "latest_central_ids": "./data/doc_ids/latest_central_ids.json",
            "latest_local_ids": "./data/doc_ids/latest_local_ids.json",
            "latest_law_ids": "./data/doc_ids/latest_law_ids.json",
        }
    if ns.dry_run:
        print("[DRY-RUN] Would run get_doc_ids() to refresh data/doc_ids/*.json from MongoDB")
        return _collect_ids(argparse.Namespace(**{**vars(ns), "skip_collect": True, "dry_run": False}), conn_manager)

    print("[PIPELINE] >>> STEP 1: Collecting document IDs from MongoDB")
    file_paths = get_doc_ids(conn_manager=conn_manager)
    if file_paths is None:
        print("[PIPELINE] ID collection failed (could not connect to MongoDB)")
        return None
    return file_paths


def _enrich_law_docs(ns: argparse.Namespace, conn_manager: ConnectionManager, file_paths: Dict[str, str]) -> bool:
    if ns.skip_enrich:
        print("[PIPELINE] --skip-enrich set: skipping law_docs.csv enrichment")
        return True
    if ns.dry_run:
        print(f"[DRY-RUN] Would enrich {LAW_DOCS_CSV_PATH} from {file_paths['latest_law_ids']}")
        return True

    print("[PIPELINE] >>> STEP 2: Enriching law_docs.csv")
    cls_collection = _get_cls_collection(conn_manager)
    service = LawDocsEnrichmentService(mongo_collection=cls_collection, csv_path=LAW_DOCS_CSV_PATH)
    appended = service.enrich(file_paths["latest_law_ids"])
    print(f"[PIPELINE] Appended {appended} new row(s) to {LAW_DOCS_CSV_PATH.name}")
    return True


def _resolve_doc_ids_file(ns: argparse.Namespace, conn_manager: ConnectionManager) -> Optional[str]:
    """Returns the path to forward as `--doc-ids-file` to main.py, or None on failure."""
    if ns.doc_ids_file:
        print(f"[PIPELINE] Custom --doc-ids-file provided ({ns.doc_ids_file}); skipping collect + enrich")
        return ns.doc_ids_file

    file_paths = _collect_ids(ns, conn_manager)
    if file_paths is None:
        return None

    if not _enrich_law_docs(ns, conn_manager, file_paths):
        return None

    print(f"[PIPELINE] >>> STEP 3: Assembling {DOC_IDS_OUTPUT_PATH.name} (mode={ns.mode})")
    if ns.dry_run:
        source_keys = ("central_ids", "local_ids") if ns.mode == "full" else ("latest_central_ids", "latest_local_ids")
        print(f"[DRY-RUN] Would write {DOC_IDS_OUTPUT_PATH} from {[file_paths[k] for k in source_keys]} (deduped)")
        return str(DOC_IDS_OUTPUT_PATH)

    ids = _assemble_doc_ids(ns.mode, file_paths, DOC_IDS_OUTPUT_PATH)
    print(f"[PIPELINE] Wrote {len(ids)} ID(s) to {DOC_IDS_OUTPUT_PATH}")
    return str(DOC_IDS_OUTPUT_PATH)


def main(argv: Optional[List[str]] = None) -> int:
    ns = _build_arg_parser().parse_args(argv)

    conn_manager = ConnectionManager()

    print("\n" + "=" * 70)
    print(" " * 15 + "PRODUCTION PIPELINE: collect -> enrich -> build")
    print("=" * 70)

    doc_ids_file = _resolve_doc_ids_file(ns, conn_manager)
    if doc_ids_file is None:
        return 1

    main_argv = _build_main_argv(doc_ids_file, ns)
    main_cmd = [sys.executable, str(_PROJECT_ROOT / "main.py")] + main_argv

    print("\n[PIPELINE] >>> STEP 4: Build graph (main.py)")
    print(f"Command: {' '.join(main_cmd)}\n")

    if ns.dry_run:
        print("[DRY-RUN] main.py was not executed.")
        return 0

    result = subprocess.run(main_cmd, cwd=str(_PROJECT_ROOT))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
