import sys
# Force UTF-8 encoding for stdout/stderr to prevent UnicodeEncodeError on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

import argparse
import subprocess
import time
import os
from datetime import timedelta
from pathlib import Path

# --- TERMINAL COLOR CONFIGURATION ---
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_banner(text):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*80}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD} {text.center(78)} {Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*80}{Colors.ENDC}\n")

def run_step(command, description):
    """Executes a pipeline step with detailed logging."""
    print(f"{Colors.OKCYAN}{Colors.BOLD}[PIPELINE] >>> {description}{Colors.ENDC}")
    print(f"{Colors.OKBLUE}Command: {' '.join(command)}{Colors.ENDC}\n")

    start_time = time.time()
    try:
        # Stream stdout/stderr directly to the console in real-time
        subprocess.run(command, check=True)
        duration = time.time() - start_time
        print(f"\n{Colors.OKGREEN}✅ COMPLETED: {description}{Colors.ENDC}")
        print(f"{Colors.OKGREEN}Duration: {timedelta(seconds=int(duration))}{Colors.ENDC}\n")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n{Colors.FAIL}❌ FAILED: {description}{Colors.ENDC}")
        print(f"{Colors.FAIL}Exit Code: {e.returncode}{Colors.ENDC}")
        return False
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}⚠️ Interrupt received from user (Ctrl+C).{Colors.ENDC}")
        return False


def run_in_process(phase_args, description, phase_main):
    """Run a pipeline phase by calling its main() in-process instead of via subprocess.

    This avoids the cold Python-startup cost (~2-5s on Windows) that the
    subprocess.run path pays for every benchmark run.
    """
    print(f"{Colors.OKCYAN}{Colors.BOLD}[PIPELINE] >>> {description}{Colors.ENDC}")
    print(f"{Colors.OKBLUE}In-process args: {' '.join(phase_args)}{Colors.ENDC}\n")

    start_time = time.time()
    try:
        rc = phase_main(phase_args)
        duration = time.time() - start_time
        if rc not in (0, None):
            print(f"\n{Colors.FAIL}❌ FAILED: {description}{Colors.ENDC}")
            print(f"{Colors.FAIL}Exit Code: {rc}{Colors.ENDC}")
            return False
        print(f"\n{Colors.OKGREEN}✅ COMPLETED: {description}{Colors.ENDC}")
        print(f"{Colors.OKGREEN}Duration: {timedelta(seconds=int(duration))}{Colors.ENDC}\n")
        return True
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        if code == 0:
            duration = time.time() - start_time
            print(f"\n{Colors.OKGREEN}✅ COMPLETED: {description}{Colors.ENDC}")
            print(f"{Colors.OKGREEN}Duration: {timedelta(seconds=int(duration))}{Colors.ENDC}\n")
            return True
        print(f"\n{Colors.FAIL}❌ FAILED: {description}{Colors.ENDC}")
        print(f"{Colors.FAIL}Exit Code: {code}{Colors.ENDC}")
        return False
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}⚠️ Interrupt received from user (Ctrl+C).{Colors.ENDC}")
        return False
    except Exception as e:
        print(f"\n{Colors.FAIL}❌ FAILED: {description}{Colors.ENDC}")
        print(f"{Colors.FAIL}Error: {e}{Colors.ENDC}")
        import traceback
        traceback.print_exc()
        return False

def main():
    parser = argparse.ArgumentParser(
        description='🚀 Legal Knowledge Graph Pipeline (End-to-End)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""{Colors.OKCYAN}
Example Usage:
    # Full pipeline with defaults
    python main.py --doc-ids-file <.json file> --extraction-batch-size 1000 --extraction-parallel-workers 16 --graph-batch-size 500 --graph-parallel-workers 1
{Colors.ENDC}"""
    )

    # --- GROUP 1: GLOBAL CONFIGURATION ---
    global_group = parser.add_argument_group('🌐 Global Configuration')
    global_group.add_argument('--doc-ids-file', type=str, required=True, help='Path to JSON file containing document IDs')
    global_group.add_argument('--suffix', type=str, help='Custom suffix for logs/checkpoints (auto-generated from filename if empty)')
    global_group.add_argument('--dry-run', action='store_true', help='Show planned commands without executing them')

    # --- GROUP 2: PIPELINE CONTROL ---
    ctrl_group = parser.add_argument_group('⚙️ Pipeline Control')
    ctrl_group.add_argument('--only-extract', action='store_true', help='Run PHASE 1 only')
    ctrl_group.add_argument('--only-build', action='store_true', help='Run PHASE 2 only')
    ctrl_group.add_argument('--skip-extraction', action='store_true', help='Skip Phase 1, start from Phase 2')
    ctrl_group.add_argument('--skip-build', action='store_true', help='Stop after Phase 1 completion')
    ctrl_group.add_argument('--clear-checkpoints', action='store_true', help='Reset all checkpoints before starting')

    # --- GROUP 3: EXTRACTION SETTINGS (PHASE 1) ---
    ext_group = parser.add_argument_group('🔍 Phase 1: Relationship Extraction (Raw Data -> MongoDB)')
    ext_group.add_argument('--extraction-batch-size', type=int, default=1000, help='Batch size for Phase 1 extraction (default: 1000)')
    ext_group.add_argument('--extraction-parallel-workers', type=int, default=8, help='Parallel workers for Phase 1 extraction (default: 8)')
    ext_group.add_argument('--mongo-extraction-collection', type=str, help='MongoDB collection name for extraction output (overrides IE_COLLECTION env var)')
    ext_group.add_argument('--clear-es-cache', action='store_true', help='Clear the persisted Elasticsearch reference cache before extraction')
    ext_group.add_argument('--use-llm', action='store_true', help='Enable AI-powered relationship extraction (LLM fallback)')
    ext_group.add_argument('--skip-already-processed', action='store_true', help='Incremental mode: Skip docs already existing in IE collection')
    ext_group.add_argument('--skip-infer-relations', action='store_true', help='Skip building reverse/inferred relationships in MongoDB')

    # --- GROUP 4: BUILDING SETTINGS (PHASE 2) ---
    build_group = parser.add_argument_group('💎 Phase 2: Knowledge Graph Building (MongoDB -> Neo4j -> MongoDB)')
    build_group.add_argument('--graph-batch-size', type=int, default=1000, help='Batch size for Phase 2 graph building (default: 1000)')
    build_group.add_argument('--graph-parallel-workers', type=int, default=8, help='Parallel workers for Phase 2 graph building (default: 8)')
    build_group.add_argument('--neo4j-db', type=str, default='neo4j', help='Target Neo4j database (default: neo4j)')
    build_group.add_argument('--neo4j-env', type=str, choices=['DEV', 'PROD'], default='DEV', help='Neo4j environment target')
    build_group.add_argument('--with-tvpl', action='store_true', help='Include legacy TVPL (cls_luoc_do) relationships')
    build_group.add_argument('--with-luoc-do-export', action='store_true', help='Synchronize Neo4j relations back to MongoDB luoc_do')
    build_group.add_argument('--reset-relations', action='store_true', help='Delete outgoing semantic relationships of in-scope nodes before building (preserves bao_gom, nodes, and incoming edges)')
    build_group.add_argument('--delete-orphan-nodes', action='store_true', help='After building, delete VAN_BAN/DIEU_KHOAN nodes left with no relationships at all (database-wide cleanup)')
    build_group.add_argument('--orphan-node-batch-size', type=int, help='Transaction batch size for --delete-orphan-nodes (default: 10000)')
    build_group.add_argument('--reconcile-after-build', action='store_true', help='Write a strict reconciliation report comparing Mongo expected relationships with Neo4j actual endpoints')
    build_group.add_argument('--graph-audit-output', type=str, default='reports/graph_audit.json', help='Path for graph reconciliation/audit JSON output')
    build_group.add_argument('--graph-resolution-mode', choices=['strict', 'permissive'], default='strict', help='Target resolution mode used by graph reconciliation')
    build_group.add_argument('--re-update', action='store_true', help='Refresh all properties for existing nodes')
    build_group.add_argument('--skip-enrichment', action='store_true', help='Skip PHASE 6: Metadata enrichment for skeleton nodes')
    build_group.add_argument('--skip-nodes', action='store_true', help='Skip node building in Phase 2')
    build_group.add_argument('--skip-bao-gom', action='store_true', help='Skip BAO_GOM relationship building')
    build_group.add_argument('--only-luoc-do-export', action='store_true', help='Execute Phase 5 only: Export Neo4j relationships back to MongoDB')
    build_group.add_argument('--show-stats', action='store_true', help='Show graph statistics before and after building')
    build_group.add_argument('--node-batch-size', type=int, help='Batch size for node creation (overrides --graph-batch-size)')
    build_group.add_argument('--structural-rel-batch-size', type=int, help='Batch size for structural (BAO_GOM) relationship creation (overrides --graph-batch-size)')
    build_group.add_argument('--status-rel-batch-size', type=int, help='Batch size for status relationship creation (overrides --graph-batch-size)')
    build_group.add_argument('--inferred-rel-batch-size', type=int, help='Batch size for inferred relationship creation (overrides --graph-batch-size)')
    build_group.add_argument('--tvpl-batch-size', type=int, help='Batch size for TVPL relationship creation (overrides --graph-batch-size)')
    build_group.add_argument('--luoc-do-batch-size', type=int, help='Batch size for luoc_do export (overrides --graph-batch-size)')

    args = parser.parse_args()

    # --- ENVIRONMENT VALIDATION ---
    if not os.path.exists(args.doc_ids_file):
        print(f"{Colors.FAIL}❌ ERROR: Input file '{args.doc_ids_file}' not found!{Colors.ENDC}")
        sys.exit(1)

    # --- AUTO-GENERATED SUFFIX ---
    suffix = args.suffix or Path(args.doc_ids_file).stem
    
    # --- CONFIGURATION DASHBOARD ---
    print_banner("LEGAL KNOWLEDGE GRAPH PIPELINE")
    print(f"{Colors.BOLD}Input File:               {Colors.ENDC}{args.doc_ids_file}")
    print(f"{Colors.BOLD}Logic Suffix:             {Colors.ENDC}{suffix}")
    print(f"{Colors.BOLD}Extraction Batch Size:    {Colors.ENDC}{args.extraction_batch_size}")
    print(f"{Colors.BOLD}Extraction Workers:       {Colors.ENDC}{args.extraction_parallel_workers}")
    print(f"{Colors.BOLD}Graph Batch Size:         {Colors.ENDC}{args.graph_batch_size}")
    print(f"{Colors.BOLD}Graph Workers:            {Colors.ENDC}{args.graph_parallel_workers}")
    if args.mongo_extraction_collection:
        print(f"{Colors.BOLD}Extraction Collection:    {Colors.ENDC}{args.mongo_extraction_collection}")
    print(f"{Colors.BOLD}Neo4j Target:             {Colors.ENDC}{args.neo4j_db} ({args.neo4j_env})")
    print("-" * 80)

    start_timestamp = time.time()
    
    # Decide which phases to execute based on flags
    run_phase_1 = not (args.only_build or args.skip_extraction)
    run_phase_2 = not (args.only_extract or args.skip_build)

    # --- PHASE 1: EXTRACTION (Text to MongoDB) ---
    if run_phase_1:
        cmd_1 = [
            sys.executable, "-m", "src.extract_relations",
            "--doc-ids-file", args.doc_ids_file,
            "--batch-size", str(args.extraction_batch_size),
            "--parallel-workers", str(args.extraction_parallel_workers),
            "--checkpoint-suffix", suffix
        ]
        if args.mongo_extraction_collection:
            cmd_1.extend(["--mongo-extraction-collection", args.mongo_extraction_collection])
        if args.clear_es_cache:
            cmd_1.append("--clear-es-cache")
        if args.use_llm:
            cmd_1.append("--use-llm")
        if args.skip_already_processed:
            cmd_1.append("--skip-already-processed")
        if args.skip_infer_relations:
            cmd_1.append("--skip-infer-relations")
        if args.clear_checkpoints:
            cmd_1.append("--clear-checkpoint")
        
        if args.dry_run:
            print(f"{Colors.WARNING}[DRY-RUN] Planned Phase 1: {' '.join(cmd_1)}{Colors.ENDC}")
        else:
            from src.extract_relations import main as _extract_main
            if not run_in_process(cmd_1[3:], "PHASE 1: RELATIONSHIP EXTRACTION (Text -> MongoDB)", _extract_main):
                print(f"{Colors.FAIL}🛑 Pipeline aborted: Phase 1 critical failure.{Colors.ENDC}")
                sys.exit(1)

    # --- PHASE 2: BUILDING (MongoDB to Neo4j) ---
    if run_phase_2:
        cmd_2 = [
            sys.executable, "-m", "src.build_graph",
            "--doc-ids-file", args.doc_ids_file,
            "--batch-size", str(args.graph_batch_size),
            "--parallel-workers", str(args.graph_parallel_workers),
            "--neo4j-database", args.neo4j_db,
            "--neo4j-env", args.neo4j_env,
            "--checkpoint-suffix", suffix
        ]
        if args.mongo_extraction_collection:
            cmd_2.extend(["--mongo-extraction-collection", args.mongo_extraction_collection])
        if args.with_tvpl:
            cmd_2.append("--with-tvpl")
        if args.with_luoc_do_export:
            cmd_2.append("--with-luoc-do-export")
        if args.only_luoc_do_export:
            cmd_2.append("--only-luoc-do-export")
        if args.reset_relations:
            cmd_2.append("--reset-relations")
        if args.delete_orphan_nodes:
            cmd_2.append("--delete-orphan-nodes")
            if args.orphan_node_batch_size:
                cmd_2.extend(["--orphan-node-batch-size", str(args.orphan_node_batch_size)])
        if args.reconcile_after_build:
            cmd_2.append("--reconcile-after-build")
            cmd_2.extend(["--graph-audit-output", args.graph_audit_output])
            cmd_2.extend(["--graph-resolution-mode", args.graph_resolution_mode])
        if args.re_update:
            cmd_2.append("--re-update")
        if args.skip_enrichment:
            cmd_2.append("--skip-enrichment")
        if args.skip_nodes:
            cmd_2.append("--skip-nodes")
        if args.skip_bao_gom:
            cmd_2.append("--skip-bao-gom")
        if args.clear_checkpoints:
            cmd_2.append("--clear-checkpoint")
        if args.show_stats:
            cmd_2.append("--show-stats")
        if args.node_batch_size:
            cmd_2.extend(["--node-batch-size", str(args.node_batch_size)])
        if args.structural_rel_batch_size:
            cmd_2.extend(["--structural-rel-batch-size", str(args.structural_rel_batch_size)])
        if args.status_rel_batch_size:
            cmd_2.extend(["--status-rel-batch-size", str(args.status_rel_batch_size)])
        if args.inferred_rel_batch_size:
            cmd_2.extend(["--inferred-rel-batch-size", str(args.inferred_rel_batch_size)])
        if args.tvpl_batch_size:
            cmd_2.extend(["--tvpl-batch-size", str(args.tvpl_batch_size)])
        if args.luoc_do_batch_size:
            cmd_2.extend(["--luoc-do-batch-size", str(args.luoc_do_batch_size)])

        
        if args.dry_run:
            print(f"{Colors.WARNING}[DRY-RUN] Planned Phase 2: {' '.join(cmd_2)}{Colors.ENDC}")
        else:
            from src.build_graph import main as _build_main
            if not run_in_process(cmd_2[3:], "PHASE 2: KNOWLEDGE GRAPH BUILDING (MongoDB -> Neo4j)", _build_main):
                print(f"{Colors.FAIL}🛑 Pipeline interrupted: Phase 2 incomplete.{Colors.ENDC}")
                sys.exit(1)

    # --- FINAL PIPELINE SUMMARY ---
    if not args.dry_run:
        total_pipeline_time = time.time() - start_timestamp
        print_banner("PIPELINE COMPLETED SUCCESSFULLY")
        print(f"{Colors.OKGREEN}{Colors.BOLD}Success! All legal documents have been processed and mapped to the graph.{Colors.ENDC}")
        print(f"{Colors.BOLD}Total Time Elapsed: {timedelta(seconds=int(total_pipeline_time))}{Colors.ENDC}")
        print(f"{Colors.BOLD}Open your Neo4j Browser to visualize the Knowledge Graph.{Colors.ENDC}\n")

if __name__ == "__main__":
    main()
