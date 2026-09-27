"""Command Line Interface for the Quantitative Trading RAG Pipeline.

Usage:
  python3 -m edge.rag.cli ingest <file_or_dir> [--recursive] [--force]
  python3 -m edge.rag.cli search "<query>" [--top-k 5] [--no-rerank]
  python3 -m edge.rag.cli diagnose "<model_issue_symptom>"
  python3 -m edge.rag.cli eval
  python3 -m edge.rag.cli stats
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

from edge.rag.eval_harness import QuantRAGEvaluator
from edge.rag.model_doctor import ModelDoctor
from edge.rag.pipeline import QuantRAGPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("edge.rag.cli")


def cmd_ingest(args: argparse.Namespace, pipeline: QuantRAGPipeline) -> None:
    target = Path(args.path).resolve()
    if not target.exists():
        print(f"Error: Target path does not exist: {target}", file=sys.stderr)
        sys.exit(1)

    print("\n=======================================================")
    print(f"  INGESTING QUANT TRADING LITERATURE: {target.name}")
    print("=======================================================\n")

    if target.is_dir():
        results = pipeline.ingest_directory(
            target, recursive=args.recursive, force=args.force
        )
        indexed = [r for r in results if r.get("status") == "indexed"]
        skipped = [r for r in results if r.get("status") == "already_indexed"]
        errors = [r for r in results if r.get("status") == "error"]

        print("\n--- Ingestion Summary ---")
        print(f"Total documents processed: {len(results)}")
        print(f"Newly indexed:            {len(indexed)}")
        print(f"Already indexed/skipped:  {len(skipped)}")
        print(f"Errors:                   {len(errors)}")

        for r in indexed:
            print(
                f"  + {r.get('title')}: {r.get('total_chunks')} chunks ({r.get('total_pages')} pages) in {r.get('elapsed_sec')}s"
            )
        if errors:
            print("\nErrors encountered:")
            for e in errors:
                print(f"  ! {e.get('file')}: {e.get('error')}")

    else:
        res = pipeline.ingest_file(target, force=args.force)
        print(f"Status:       {res.get('status')}")
        if res.get("status") == "indexed":
            print(f"Title:        {res.get('title')}")
            print(f"Author:       {res.get('author')}")
            print(f"Pages:        {res.get('total_pages')}")
            print(f"Total Chunks: {res.get('total_chunks')}")
            print(f"Elapsed:      {res.get('elapsed_sec')}s")


def cmd_search(args: argparse.Namespace, pipeline: QuantRAGPipeline) -> None:
    print(f"\nSearching: '{args.query}' (top_k={args.top_k}, rerank={not args.no_rerank})\n")
    results = pipeline.retrieve(
        query=args.query,
        top_k=args.top_k,
        alpha=args.alpha,
        rerank=not args.no_rerank,
        topic_filter=args.topic,
    )

    if not results:
        print("No matching passages found. Have you ingested your books yet?")
        return

    print(f"Found {len(results)} relevant passages:\n")
    for i, r in enumerate(results, 1):
        print("--------------------------------------------------------------------------------")
        print(f"[{i}] {r.get('book_title')} ({r.get('book_year', 'n.d.')})")
        print(f"    Author(s): {r.get('book_author')}")
        print(f"    Chapter:   {r.get('chapter', 'General')} | Page: {r.get('page_number')}")
        print(f"    RRF Score: {r.get('rrf_score', 0):.4f} | Rerank Score: {r.get('rerank_score', 0):.3f}")
        print("--------------------------------------------------------------------------------")
        content = r.get("content", "").strip()
        if len(content) > 600 and not args.full:
            print(content[:600] + "\n... [truncated, use --full to view entire chunk] ...\n")
        else:
            print(content + "\n")


def cmd_diagnose(args: argparse.Namespace, pipeline: QuantRAGPipeline) -> None:
    doctor = ModelDoctor(pipeline)
    print("\n=======================================================")
    print("  QUANT MODEL DOCTOR: LITERATURE-GROUNDED DIAGNOSTIC")
    print("=======================================================")
    print(f"\nReported Symptom: \"{args.problem}\"\n")

    diag = doctor.diagnose_model_issue(
        problem_description=args.problem,
        top_k=args.top_k,
        use_llm=not args.offline,
    )

    print("Detected Quantitative Failure Modes:")
    for mode in diag.detected_failure_modes:
        print(f"  * {mode.replace('_', ' ').title()}")
    print()

    print("================ ROOT CAUSE ANALYSIS ================")
    print(diag.root_cause_analysis)
    print()

    print("================ MATHEMATICAL REMEDY ================")
    print(diag.mathematical_remedy)
    print()

    print("================ IMPLEMENTATION RECIPE ================")
    print(diag.implementation_recipe)
    print()

    print("================ PRIMARY LITERATURE CITATIONS ================")
    for cite in diag.literature_citations:
        print(f"  [+] {cite}")
    print()


def cmd_eval(args: argparse.Namespace, pipeline: QuantRAGPipeline) -> None:
    print("\n=======================================================")
    print("  RUNNING QUANT RAG BENCHMARK EVALUATION (Golden Set)")
    print("=======================================================\n")

    evaluator = QuantRAGEvaluator(pipeline)
    metrics = evaluator.run_benchmark(top_k=args.top_k)

    print(f"Evaluation Results across {metrics['total_test_cases']} quantitative cases:")
    print("-------------------------------------------------------")
    print(f"Recall@1:                 {metrics['recall_at_1'] * 100:.1f}%")
    print(f"Recall@3:                 {metrics['recall_at_3'] * 100:.1f}%")
    print(f"Recall@{args.top_k}:                 {metrics[f'recall_at_{args.top_k}'] * 100:.1f}%")
    print(f"Mean Reciprocal Rank (MRR): {metrics['mean_reciprocal_rank_mrr']:.4f}")
    print(f"Average Precision@{args.top_k}:      {metrics['average_precision_at_k']:.4f}")
    print(f"Latency (p50):             {metrics['latency_p50_ms']} ms")
    print(f"Latency (p95):             {metrics['latency_p95_ms']} ms")
    print("-------------------------------------------------------\n")

    if args.verbose:
        print("Query Breakdown:")
        for d in metrics["details"]:
            print(f"Q: {d['query']}")
            print(f"   First Hit Rank: {d['first_hit_rank']} | Latency: {d['latency_ms']}ms | Top: {d['top_chunk_book']} ({d['top_chunk_author']})")


def cmd_stats(args: argparse.Namespace, pipeline: QuantRAGPipeline) -> None:
    stats = pipeline.stats()
    print("\n=======================================================")
    print("  QUANT RAG STORE & INDEX STATUS")
    print("=======================================================")
    print(f"Total Books/Papers Indexed: {stats['total_books']}")
    print(f"Total Document Chunks:      {stats['total_chunks']}")
    print(f"Total Corpus Tokens:        {stats['total_tokens']:,}")
    print(f"FAISS Vector Index Size:    {stats['vector_index_size']}")
    print(f"Database File:              {pipeline.vector_store.db_path}")
    print(f"FAISS Index File:           {pipeline.vector_store.faiss_path}")
    print("\nIndexed Volumes:")
    print(f"{'Title':<45} | {'Author':<28} | {'Pages':<6} | {'Chunks':<6}")
    print("-" * 92)
    for b in stats["books"]:
        title = (b["title"][:42] + "...") if len(b["title"]) > 45 else b["title"]
        author = (b["author"][:25] + "...") if len(b["author"]) > 28 else b["author"]
        print(f"{title:<45} | {author:<28} | {b['total_pages']:<6} | {b['total_chunks']:<6}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Edge Quantitative RAG Pipeline & Model Doctor"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Ingest
    p_ingest = subparsers.add_parser("ingest", help="Ingest a book or directory of books")
    p_ingest.add_argument("path", help="Path to PDF/file or folder")
    p_ingest.add_argument("--recursive", "-r", action="store_true", default=True, help="Scan directories recursively")
    p_ingest.add_argument("--force", "-f", action="store_true", help="Force re-indexing even if hash matches")

    # Search
    p_search = subparsers.add_parser("search", help="Hybrid retrieval over ingested literature")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--top-k", "-k", type=int, default=5, help="Number of results to retrieve")
    p_search.add_argument("--alpha", type=float, default=0.65, help="RRF alpha weight (1.0 dense, 0.0 BM25)")
    p_search.add_argument("--no-rerank", action="store_true", help="Disable cross-encoder reranking")
    p_search.add_argument("--topic", help="Filter by topic tag")
    p_search.add_argument("--full", action="store_true", help="Print entire chunk text without truncation")

    # Diagnose
    p_diag = subparsers.add_parser("diagnose", help="Diagnose a quantitative model issue using literature")
    p_diag.add_argument("problem", help="Model defect description or symptom")
    p_diag.add_argument("--top-k", "-k", type=int, default=5, help="Passages to retrieve")
    p_diag.add_argument("--offline", action="store_true", help="Use deterministic literature rulebook rather than calling LLM API")

    # Eval
    p_eval = subparsers.add_parser("eval", help="Run golden benchmark evaluation suite")
    p_eval.add_argument("--top-k", "-k", type=int, default=5, help="Top-k evaluation depth")
    p_eval.add_argument("--verbose", "-v", action="store_true", help="Show breakdown per test query")

    # Stats
    subparsers.add_parser("stats", help="Display index statistics and cataloged books")

    args = parser.parse_args()
    pipeline = QuantRAGPipeline()

    if args.command == "ingest":
        cmd_ingest(args, pipeline)
    elif args.command == "search":
        cmd_search(args, pipeline)
    elif args.command == "diagnose":
        cmd_diagnose(args, pipeline)
    elif args.command == "eval":
        cmd_eval(args, pipeline)
    elif args.command == "stats":
        cmd_stats(args, pipeline)


if __name__ == "__main__":
    main()
