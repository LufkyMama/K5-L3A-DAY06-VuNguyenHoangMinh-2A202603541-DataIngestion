"""Day 06 pipeline: ingest the corpus for strategies A/B/C, then run top-3 retrieval on the benchmark.

Run from starter/:
    python -m src.run --split dev     # choose / inspect on dev first
    python -m src.run --split test    # only after the configuration and selection rule are fixed
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .embeddings import MyEmbedder
from .evaluation import evaluate_query, summarize
from .ingestion import load_pdf
from .models import DocumentPage
from .store import PgVectorStore

STARTER = Path(__file__).resolve().parents[1]
REPO = STARTER.parent
PDF = REPO / "data" / "corpus" / "Introduction_to_Python_Programming-WEB.pdf"
SOURCE = "data/corpus/Introduction_to_Python_Programming-WEB.pdf"
DOCUMENT_ID = "openstax-intro-python"
PAGE_RANGE = range(95, 175)   # chapters 4-6 (Decisions, Loops, Functions), PDF pages 95-174
MIN_CHARS = 200               # pages below this only hold a running header/footer
BENCHMARK = REPO / "benchmark" / "questions.json"
RESULTS = STARTER / "results"
TOP_K = 3
PRICE_PER_1M_TOKENS = 0.02    # USD, text-embedding-3-small list price when written; check current pricing

# Chunking per strategy. C reuses B's chunks and vectors and differs only by the search filter.
CHUNKERS = {
    "A": lambda page: fixed_size(page, size=500, overlap=50),
    "B": lambda page: by_paragraph(page, max_size=500),
}
USES_FILTER = {"A": False, "B": False, "C": True}

log = logging.getLogger("day06")


def load_corpus() -> tuple[list[DocumentPage], list[DocumentPage]]:
    """Return (all pages, counted pages) for the selected range."""
    all_pages = load_pdf(PDF, DOCUMENT_ID, SOURCE)
    counted = [p for p in all_pages if p.page in PAGE_RANGE
               and p.metadata["char_count"] >= MIN_CHARS and "error" not in p.metadata]
    if len(counted) < 30:
        raise RuntimeError(f"only {len(counted)} content pages; the lab needs at least 30")
    return all_pages, counted


def load_questions() -> list[dict]:
    questions = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    splits = [q["split"] for q in questions]
    if len(questions) < 20 or splits.count("dev") < 15 or splits.count("test") < 5:
        raise RuntimeError("benchmark needs >= 20 questions with >= 15 dev and >= 5 test")
    return questions


def ingest(store: PgVectorStore, embedder: MyEmbedder, pages: list[DocumentPage]) -> dict:
    stats = {}
    chunks_by, vectors_by = {}, {}
    for name, chunker in CHUNKERS.items():
        chunks = [c for p in pages for c in chunker(p)]
        tokens_before = embedder.total_tokens
        started = time.perf_counter()
        vectors = embedder.embed_documents([c.text for c in chunks])
        embed_seconds = time.perf_counter() - started
        store.upsert(name, chunks, vectors)
        chunks_by[name], vectors_by[name] = chunks, vectors
        stats[name] = {"chunks": len(chunks), "embed_seconds": round(embed_seconds, 2),
                       "embed_tokens": embedder.total_tokens - tokens_before}
    store.upsert("C", chunks_by["B"], vectors_by["B"])  # same rows as B under strategy C
    stats["C"] = {"chunks": len(chunks_by["B"]), "embed_seconds": 0.0, "embed_tokens": 0,
                  "note": "reuses B chunks and vectors"}
    for name in USES_FILTER:  # re-running must not duplicate rows
        stored = store.count(name)
        if stored != stats[name]["chunks"]:
            raise RuntimeError(f"strategy {name}: {stored} rows stored, expected {stats[name]['chunks']}")
        stats[name]["rows_in_store"] = stored
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(STARTER / ".env")
    RESULTS.mkdir(exist_ok=True)
    run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    all_pages, pages = load_corpus()
    questions = [q for q in load_questions() if args.split == "all" or q["split"] == args.split]
    log.info("corpus: %d pages read, %d counted; %d %s questions",
             len(all_pages), len(pages), len(questions), args.split)

    embedder = MyEmbedder(os.getenv("EMBEDDING_MODEL", ""))
    store = PgVectorStore(os.getenv("DATABASE_URL", ""), embedder.dimensions)
    store.create_schema()
    ingest_stats = ingest(store, embedder, pages)
    log.info("ingest: %s", ingest_stats)

    traces = []
    query_tokens_before = embedder.total_tokens
    for q in questions:
        query_vector = embedder.embed_query(q["question"])  # one query vector shared by A/B/C
        for strategy, use_filter in USES_FILTER.items():
            filters = q.get("filter") if use_filter else None
            hits = store.search(strategy, query_vector, top_k=TOP_K, filters=filters)
            trace = evaluate_query(q, hits)
            trace.update(strategy=strategy, filter_applied=filters)
            traces.append(trace)

    with (RESULTS / f"traces_{args.split}.jsonl").open("w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    summary = summarize(traces)
    report = {
        "run_at_utc": run_at,
        "split": args.split,
        "model": embedder.model_name,
        "dimensions": embedder.dimensions,
        "search": "exact cosine (pgvector <=>), no ANN index",
        "top_k": TOP_K,
        "corpus_pages": len(pages),
        "ingest": ingest_stats,
        "query_tokens": embedder.total_tokens - query_tokens_before,
        "total_tokens": embedder.total_tokens,
        "estimated_cost_usd": round(embedder.total_tokens * PRICE_PER_1M_TOKENS / 1e6, 6),
        "metrics": summary,
    }
    (RESULTS / f"metrics_{args.split}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
