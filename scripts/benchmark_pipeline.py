"""Benchmark runner for the CLS pipeline.

Baseline Command:
python ./scripts/benchmark_pipeline.py --doc-ids-file ./data/benchmark_100_ids.json --sample-size 100 \
    --seed 42 --runs 10 --warmup --sample-interval 1 --output reports/performance_benchmark.md \
    --show-stats --extraction-batch-size 1000 --graph-batch-size 500 \
    --extraction-parallel-workers 16 --graph-parallel-workers 1 \
    --neo4j-env DEV --neo4j-db neo4jtest \
    --with-tvpl --node-batch-size 300 --structural-rel-batch-size 500 \
    --status-rel-batch-size 200 --inferred-rel-batch-size 100 --tvpl-batch-size 300

This script samples N IDs from an input JSON array, writes a sampled file
(`data/benchmark_<N>_ids.json`), runs `main.py` the configured number of times
(capturing stdout/stderr), optionally samples system metrics with psutil,
parses timing output from the pipeline logs, and writes a Markdown report with
aggregated statistics and simple plots (if matplotlib is available).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import subprocess
import time
import threading
import re
import statistics
from pathlib import Path
from datetime import datetime

try:
    import psutil  # type: ignore
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False

try:
    import matplotlib.pyplot as plt  # type: ignore
    HAS_MATPLOTLIB = True
except Exception:
    HAS_MATPLOTLIB = False

ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def remove_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


def parse_hms(hms: str) -> int:
    parts = [int(p) for p in hms.split(":")]
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h = 0
        m, s = parts
    else:
        h = 0
        m = 0
        s = parts[0]
    return h * 3600 + m * 60 + s


def sample_ids(infile: Path, outpath: Path, size: int, seed: int | None = None):
    with infile.open("r", encoding="utf-8") as fh:
        ids = json.load(fh)
    if not isinstance(ids, list):
        raise ValueError("Input IDs file must contain a JSON array")
    if seed is not None:
        random.seed(seed)
    if size > len(ids):
        raise ValueError(f"Requested sample size {size} larger than available IDs ({len(ids)})")
    sample = random.sample(ids, size)
    outpath.parent.mkdir(parents=True, exist_ok=True)
    with outpath.open("w", encoding="utf-8") as fh:
        json.dump(sample, fh, indent=2, ensure_ascii=False)
    return sample


def system_sampler(stop_event: threading.Event, interval: float, collector: list):
    if not HAS_PSUTIL:
        return
    # First call primes cpu_percent
    psutil.cpu_percent(interval=None)
    while not stop_event.is_set():
        t = time.time()
        cpu = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        mem = vm.used
        collector.append((t, cpu, mem))
        time.sleep(interval)


def run_pipeline_once(cmd: list[str], cwd: Path, logfile_path: Path, sample_interval: float = 1.0):
    logfile_path.parent.mkdir(parents=True, exist_ok=True)
    captured_lines: list[str] = []
    sys_samples: list[tuple[float, float, int]] = []
    stop_event = threading.Event()
    sampler_thread = threading.Thread(target=system_sampler, args=(stop_event, sample_interval, sys_samples), daemon=True)

    start_ts = time.time()
    with logfile_path.open("w", encoding="utf-8") as fh:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(cwd), text=True, bufsize=1, encoding='utf-8')
        sampler_thread.start()
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip("\n")
                clean = remove_ansi(line)
                fh.write(clean + "\n")
                fh.flush()
                captured_lines.append(clean)
        except Exception:
            proc.kill()
            raise
        returncode = proc.wait()
    stop_event.set()
    sampler_thread.join(timeout=2)
    duration = time.time() - start_ts
    return {
        "returncode": returncode,
        "duration": duration,
        "lines": captured_lines,
        "sys_samples": sys_samples,
    }


def parse_run_metrics(lines: list[str]) -> dict:
    txt = "\n".join(lines)
    metrics: dict = {}
    m = re.search(r"Total Time Elapsed:\s*([0-9:]+)", txt)
    if m:
        metrics["total_time"] = parse_hms(m.group(1))
    durations = re.findall(r"Duration:\s*([0-9:]+)", txt)
    if durations:
        metrics["durations"] = [parse_hms(x) for x in durations]
    m = re.search(r"Processing speed:\s*([\d.]+)\s*docs/second", txt)
    if m:
        metrics["processing_speed"] = float(m.group(1))
    m = re.search(r"Average Speed:\s*([\d.]+)\s*docs/sec", txt)
    if m:
        metrics["avg_speed"] = float(m.group(1))
    m = re.search(r"Average time per document:\s*([\d.]+)\s*seconds", txt)
    if m:
        metrics["avg_time_per_doc"] = float(m.group(1))
    return metrics


def _trim_iqr(values: list[float]) -> tuple[list[float], list[float]]:
    """Split values into (kept, trimmed) using a Tukey 1.5*IQR fence.

    With < 4 samples there is no robust IQR to compute, so nothing is trimmed.
    """
    if len(values) < 4:
        return list(values), []
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    q1 = sorted_vals[n // 4]
    q3 = sorted_vals[(3 * n) // 4]
    iqr = q3 - q1
    lo = q1 - 1.5 * iqr
    hi = q3 + 1.5 * iqr
    kept = [v for v in values if lo <= v <= hi]
    trimmed = [v for v in values if v < lo or v > hi]
    return kept, trimmed


def _safe_stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": 0.0, "median": 0.0, "stdev": 0.0, "cov": 0.0}
    mean = statistics.mean(values)
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    return {
        "n": len(values),
        "mean": mean,
        "median": statistics.median(values),
        "stdev": stdev,
        "cov": (stdev / mean) if mean > 0 else 0.0,
    }


def generate_report(output_path: Path, run_records: list[dict], sample_size: int, sample_file: Path, plots_enabled: bool = True):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    from datetime import timezone
    now = datetime.now(timezone.utc).isoformat() + "Z"
    durations = [r["duration"] for r in run_records]
    throughputs = [sample_size / d if d > 0 else 0.0 for d in durations]

    md_lines = []
    md_lines.append("# Pipeline Benchmark Report\n")
    md_lines.append(f"Generated: {now}")
    md_lines.append(f"\n**Sample file**: {sample_file}\n")
    md_lines.append(f"**Sample size**: {sample_size}")
    md_lines.append("\n## Per-run summary\n")
    md_lines.append("| Run | Exit | Duration (s) | Throughput (docs/s) | Notes |")
    md_lines.append("|---:|---:|---:|---:|---|")
    for i, r in enumerate(run_records, start=1):
        rc = r.get("returncode", "?")
        dur = f"{r['duration']:.2f}"
        tp = f"{throughputs[i-1]:.2f}"
        notes = []
        parsed = r.get("parsed_metrics", {})
        if parsed.get("processing_speed"):
            notes.append(f"log_speed={parsed['processing_speed']:.2f}")
        md_lines.append(f"| {i} | {rc} | {dur} | {tp} | {'; '.join(notes)} |")

    md_lines.append("\n## Aggregates\n")
    raw_dur_stats = _safe_stats(durations)
    raw_tp_stats = _safe_stats(throughputs)
    md_lines.append(f"- Runs: {raw_dur_stats['n']}")
    md_lines.append(
        f"- Duration (s) [raw]: mean={raw_dur_stats['mean']:.2f}, "
        f"median={raw_dur_stats['median']:.2f}, stdev={raw_dur_stats['stdev']:.2f}, "
        f"CoV={raw_dur_stats['cov']:.3f}"
    )
    md_lines.append(
        f"- Throughput (docs/s) [raw]: mean={raw_tp_stats['mean']:.2f}, "
        f"median={raw_tp_stats['median']:.2f}, stdev={raw_tp_stats['stdev']:.2f}"
    )

    # Tukey 1.5*IQR trimming: VPN jitter can cause individual runs to balloon.
    # The trimmed mean is the headline used to compare baseline vs optimized.
    kept, trimmed = _trim_iqr(durations)
    trimmed_dur_stats = _safe_stats(kept)
    trimmed_tps = [sample_size / d for d in kept if d > 0]
    trimmed_tp_stats = _safe_stats(trimmed_tps)
    md_lines.append("")
    md_lines.append("### Trimmed (Tukey 1.5*IQR, headline metric)")
    md_lines.append(f"- Kept: {trimmed_dur_stats['n']} / Trimmed-as-outlier: {len(trimmed)}")
    if trimmed:
        md_lines.append(f"- Trimmed values (s): {[f'{v:.2f}' for v in trimmed]}")
    md_lines.append(
        f"- Duration (s) [trimmed]: mean={trimmed_dur_stats['mean']:.2f}, "
        f"median={trimmed_dur_stats['median']:.2f}, stdev={trimmed_dur_stats['stdev']:.2f}, "
        f"CoV={trimmed_dur_stats['cov']:.3f}"
    )
    md_lines.append(
        f"- Throughput (docs/s) [trimmed]: mean={trimmed_tp_stats['mean']:.2f}, "
        f"median={trimmed_tp_stats['median']:.2f}"
    )
    # Variance acceptance signal — boss-readable in the report.
    if trimmed_dur_stats["cov"] > 0.10:
        md_lines.append(
            f"- ⚠️ Trimmed CoV is **{trimmed_dur_stats['cov']:.3f}** (> 0.10). "
            "Variance is high; consider more runs or re-measure off-VPN."
        )
    else:
        md_lines.append(f"- ✅ Trimmed CoV is {trimmed_dur_stats['cov']:.3f} (≤ 0.10).")

    # System metrics summary (if any)
    all_samples = [r.get("sys_samples", []) for r in run_records]
    md_lines.append("\n## System metrics summary\n")
    any_sys = any(len(s) > 0 for s in all_samples)
    if any_sys:
        for i, s in enumerate(all_samples, start=1):
            if not s:
                md_lines.append(f"- Run {i}: no system samples collected")
                continue
            cpus = [x[1] for x in s]
            mems = [x[2] for x in s]
            md_lines.append(f"- Run {i}: CPU% mean={statistics.mean(cpus):.1f}%, max={max(cpus):.1f}% | RAM mean={statistics.mean(mems)/1024**2:.1f} MB, peak={max(mems)/1024**2:.1f} MB")

    # Plots
    plots_dir = output_path.parent
    if HAS_MATPLOTLIB and plots_enabled:
        try:
            fig, ax = plt.subplots(figsize=(6, 3))
            ax.bar(range(1, len(throughputs) + 1), throughputs)
            ax.set_xlabel('Run')
            ax.set_ylabel('Throughput (docs/s)')
            ax.set_title('Throughput per run')
            plot1 = plots_dir / 'throughput_per_run.png'
            fig.tight_layout()
            fig.savefig(plot1)
            md_lines.append(f"\n![Throughput per run]({plot1})\n")
            plt.close(fig)

            # CPU over time for first run if available
            if any_sys and len(all_samples[0]) > 0:
                times = [x[0] - all_samples[0][0][0] for x in all_samples[0]]
                cpus = [x[1] for x in all_samples[0]]
                fig, ax = plt.subplots(figsize=(8, 2.5))
                ax.plot(times, cpus)
                ax.set_xlabel('Seconds')
                ax.set_ylabel('CPU %')
                ax.set_title('CPU during run 1')
                plot2 = plots_dir / 'cpu_run1.png'
                fig.tight_layout()
                fig.savefig(plot2)
                md_lines.append(f"\n![CPU run1]({plot2})\n")
                plt.close(fig)
        except Exception as e:
            md_lines.append(f"\nPlots generation failed: {e}\n")
    else:
        md_lines.append("\nPlotting skipped (matplotlib not available).\n")

    with output_path.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(md_lines))


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Benchmark the CLS pipeline for N sampled IDs")
    parser.add_argument("--doc-ids-file", required=True, help="Path to JSON array of doc IDs (input)")
    parser.add_argument("--sample-size", type=int, default=100, help="Number of IDs to sample")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for sampling")
    parser.add_argument("--runs", type=int, default=15, help="Number of benchmark runs (default: 15, allows Tukey IQR trimming)")
    parser.add_argument("--dry-run", action="store_true", help="Do everything except execute the pipeline")
    parser.add_argument("--warmup", action="store_true", help="Perform a warm-up run (not counted)")
    parser.add_argument("--sample-interval", type=float, default=1.0, help="System metrics sampling interval (s)")
    parser.add_argument("--output", default="reports/performance_benchmark.md", help="Markdown report output path (relative)")
    parser.add_argument("--show-stats", action="store_true", help="Add --show-stats to pipeline runs")
    parser.add_argument("--extraction-batch-size", type=int, default=1000)
    parser.add_argument("--graph-batch-size", type=int, default=1000)
    parser.add_argument("--extraction-parallel-workers", type=int, default=8)
    parser.add_argument("--graph-parallel-workers", type=int, default=8)
    parser.add_argument("--neo4j-env", default="DEV")
    parser.add_argument("--neo4j-db", default="neo4jtest")
    parser.add_argument("--with-tvpl", action="store_true")
    parser.add_argument("--with-luoc-do-export", action="store_true")
    parser.add_argument("--node-batch-size", type=int, default=300)
    parser.add_argument("--structural-rel-batch-size", type=int, default=500)
    parser.add_argument("--status-rel-batch-size", type=int, default=200)
    parser.add_argument("--inferred-rel-batch-size", type=int, default=100)
    parser.add_argument("--tvpl-batch-size", type=int, default=300)
    parser.add_argument("--luoc-do-batch-size", type=int, default=200)
    parser.add_argument("--skip-enrichment", action="store_true", help="Skip PHASE 6 enrichment in the pipeline")
    parser.add_argument(
        "--reset-relations",
        action="store_true",
        help="Pass --reset-relations to main.py so every benchmark run rebuilds relationships from a clean slate (recommended for fair before/after comparison).",
    )
    parser.add_argument(
        "--phase",
        choices=["full", "extract", "build"],
        default="full",
        help="Which pipeline phase to benchmark. extract/build pass --only-extract/--only-build to main.py.",
    )

    ns = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    infile = repo_root / ns.doc_ids_file
    if not infile.exists():
        print(f"Input file not found: {infile}")
        sys.exit(1)

    sample_file = repo_root / "data" / f"benchmark_{ns.sample_size}_ids.json"
    print(f"Sampling {ns.sample_size} IDs from {infile} -> {sample_file}")
    sample_ids(infile, sample_file, ns.sample_size, ns.seed)

    # Build base command for main.py
    main_py = repo_root / "main.py"
    if not main_py.exists():
        print(f"Cannot find main.py at {main_py}")
        sys.exit(1)

    base_cmd = [
        sys.executable, str(main_py),
        "--doc-ids-file", str(sample_file),
        "--extraction-batch-size", str(ns.extraction_batch_size),
        "--graph-batch-size", str(ns.graph_batch_size),
        "--extraction-parallel-workers", str(ns.extraction_parallel_workers),
        "--graph-parallel-workers", str(ns.graph_parallel_workers),
        "--neo4j-env", ns.neo4j_env,
        "--neo4j-db", ns.neo4j_db,
        "--suffix", f"benchmark_{ns.sample_size}",
    ]

    # pipeline flags
    if ns.with_tvpl:
        base_cmd.append("--with-tvpl")
    if ns.with_luoc_do_export:
        base_cmd.append("--with-luoc-do-export")
    if ns.show_stats:
        base_cmd.append("--show-stats")
    if ns.skip_enrichment:
        base_cmd.append("--skip-enrichment")
    if ns.reset_relations:
        base_cmd.append("--reset-relations")
    if ns.phase == "extract":
        base_cmd.append("--only-extract")
    elif ns.phase == "build":
        base_cmd.append("--only-build")
    # batch overrides
    base_cmd.extend(["--node-batch-size", str(ns.node_batch_size)])
    base_cmd.extend(["--structural-rel-batch-size", str(ns.structural_rel_batch_size)])
    base_cmd.extend(["--status-rel-batch-size", str(ns.status_rel_batch_size)])
    base_cmd.extend(["--inferred-rel-batch-size", str(ns.inferred_rel_batch_size)])
    base_cmd.extend(["--tvpl-batch-size", str(ns.tvpl_batch_size)])
    base_cmd.extend(["--luoc-do-batch-size", str(ns.luoc_do_batch_size)])

    runs_to_execute = ns.runs
    run_records: list[dict] = []

    if ns.warmup:
        print("Running warm-up run (not recorded)...")
        if not ns.dry_run:
            _ = run_pipeline_once(base_cmd, repo_root, repo_root / "logs/benchmark_warmup.log", ns.sample_interval)

    for i in range(1, runs_to_execute + 1):
        print(f"Starting run {i}/{runs_to_execute}")
        logfile = repo_root / f"logs/benchmark_run_{i}.log"
        if ns.dry_run:
            print("Dry-run: would execute:", " ".join(base_cmd))
            record = {"returncode": 0, "duration": 0.0, "lines": [], "sys_samples": []}
            record["parsed_metrics"] = {}
            run_records.append(record)
            continue

        rec = run_pipeline_once(base_cmd, repo_root, logfile, ns.sample_interval)
        parsed = parse_run_metrics(rec["lines"])
        rec["parsed_metrics"] = parsed
        run_records.append(rec)

    output_path = Path(ns.output)
    generate_report(output_path, run_records, ns.sample_size, sample_file, plots_enabled=True)
    print(f"Benchmark complete. Report written to {output_path}")


if __name__ == "__main__":
    main()
