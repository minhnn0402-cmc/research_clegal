"""
Script to split a large document IDs JSON file into multiple smaller chunks.

This is useful for parallel processing of large document sets.

Usage:
    # Split into 5 chunks
    python scripts/split_ids.py data/all_ids.json --chunks 5
    
    # Split into chunks of specific size (100k docs per chunk)
    python scripts/split_ids.py data/all_ids.json --chunk-size 100000
    
    # Custom output directory
    python scripts/split_ids.py data/all_ids.json --chunks 5 --output-dir data/chunks
"""

import json
import argparse
from pathlib import Path
from typing import List


def load_ids(file_path: str) -> List[int]:
    """Load document IDs from JSON file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Handle both list format and dict format
    if isinstance(data, list):
        return data
    elif isinstance(data, dict) and 'doc_ids' in data:
        return data['doc_ids']
    else:
        raise ValueError("Invalid JSON format. Expected list or dict with 'doc_ids' key")


def split_into_chunks(ids: List[int], num_chunks: int) -> List[List[int]]:
    """Split list into N roughly equal chunks."""
    chunk_size = len(ids) // num_chunks
    remainder = len(ids) % num_chunks
    
    chunks = []
    start = 0
    
    for i in range(num_chunks):
        # Add 1 extra item to first 'remainder' chunks to distribute evenly
        size = chunk_size + (1 if i < remainder else 0)
        end = start + size
        chunks.append(ids[start:end])
        start = end
    
    return chunks


def split_by_size(ids: List[int], chunk_size: int) -> List[List[int]]:
    """Split list into chunks of specific size."""
    chunks = []
    for i in range(0, len(ids), chunk_size):
        chunks.append(ids[i:i + chunk_size])
    return chunks


def save_chunk(chunk: List[int], output_path: Path, chunk_index: int, total_chunks: int):
    """Save a chunk to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(chunk, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Chunk {chunk_index}/{total_chunks}: {len(chunk):,} IDs → {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Split document IDs file into multiple chunks for parallel processing',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Split into 5 equal chunks
    python scripts/split_ids.py data/all_ids.json --chunks 5
    
    # Split into chunks of 100k documents each
    python scripts/split_ids.py data/all_ids.json --chunk-size 100000
    
    # Custom output directory and prefix
    python scripts/split_ids.py data/all_ids.json --chunks 10 \\
        --output-dir data/parallel --prefix batch
        """
    )
    
    parser.add_argument(
        'input_file',
        type=str,
        help='Path to input JSON file containing document IDs'
    )
    
    parser.add_argument(
        '--chunks',
        type=int,
        help='Number of chunks to split into'
    )
    
    parser.add_argument(
        '--chunk-size',
        type=int,
        help='Size of each chunk (alternative to --chunks)'
    )
    
    parser.add_argument(
        '--output-dir',
        type=str,
        help='Output directory for chunk files (default: same as input file)'
    )
    
    parser.add_argument(
        '--prefix',
        type=str,
        default='chunk',
        help='Prefix for output files (default: chunk)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be created without actually creating files'
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.chunks and not args.chunk_size:
        parser.error("Must specify either --chunks or --chunk-size")
    
    if args.chunks and args.chunk_size:
        parser.error("Cannot specify both --chunks and --chunk-size")
    
    # Load IDs
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"❌ Error: File not found: {args.input_file}")
        return 1
    
    print(f"📂 Loading IDs from: {args.input_file}")
    try:
        ids = load_ids(args.input_file)
    except Exception as e:
        print(f"❌ Error loading file: {e}")
        return 1
    
    print(f"✅ Loaded {len(ids):,} document IDs")
    
    # Split into chunks
    if args.chunks:
        print(f"\n🔪 Splitting into {args.chunks} chunks...")
        chunks = split_into_chunks(ids, args.chunks)
    else:
        print(f"\n🔪 Splitting into chunks of {args.chunk_size:,} IDs...")
        chunks = split_by_size(ids, args.chunk_size)
    
    print(f"✅ Created {len(chunks)} chunks")
    print("\nChunk sizes:")
    for i, chunk in enumerate(chunks, 1):
        print(f"  Chunk {i}: {len(chunk):,} IDs")
    
    # Determine output directory
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = input_path.parent
    
    # Save chunks
    print(f"\n💾 Saving chunks to: {output_dir}")
    
    if args.dry_run:
        print("\n🔍 DRY RUN - No files will be created\n")
    
    for i, chunk in enumerate(chunks, 1):
        # Generate output filename
        output_filename = f"{args.prefix}_{i}_ids.json"
        output_path = output_dir / output_filename
        
        if args.dry_run:
            print(f"Would create: {output_path} ({len(chunk):,} IDs)")
        else:
            save_chunk(chunk, output_path, i, len(chunks))
    
    # Print summary
    print(f"\n{'='*70}")
    print("📊 SUMMARY")
    print(f"{'='*70}")
    print(f"Total IDs:        {len(ids):,}")
    print(f"Number of chunks: {len(chunks)}")
    print(f"Output directory: {output_dir}")
    print(f"File pattern:     {args.prefix}_N_ids.json")
    
    if not args.dry_run:
        print("\n✅ All chunks created successfully!")
        print("\n💡 To process in parallel, run:")
        print(f"   python -m src.extract_relations --doc-ids-file {output_dir}/{args.prefix}_1_ids.json")
        print(f"   python -m src.extract_relations --doc-ids-file {output_dir}/{args.prefix}_2_ids.json")
        print("   ... (in separate terminals)")
    
    print(f"{'='*70}\n")
    
    return 0


if __name__ == '__main__':
    exit(main())
