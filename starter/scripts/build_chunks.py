"""Build and inspect chunks for strategies A/B/C (no embedding, no database).

Run from starter/:  python scripts/build_chunks.py
Writes results/ingest_log.json, results/chunks_A.jsonl, results/chunks_B.jsonl, results/chunk_stats.json.
C uses the same chunks as B; it only adds a metadata filter at search time.
"""
import json
import re
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

# Corpus settings and chunkers come from src/run.py so both scripts always use the same configuration.
from src.run import BENCHMARK, MIN_CHARS, PAGE_RANGE, SOURCE, load_corpus  # noqa: E402
from src.run import CHUNKERS as STRATEGIES  # noqa: E402

OUT = ROOT / "results"


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    all_pages, pages = load_corpus()
    in_range = [p for p in all_pages if p.page in PAGE_RANGE]
    log = {
        "source": SOURCE,
        "pages_read": len(all_pages),
        "selected_range": f"{PAGE_RANGE.start}-{PAGE_RANGE.stop - 1}",
        "empty_pages": [p.page for p in all_pages if p.metadata["is_empty"]],
        "error_pages": {p.page: p.metadata["error"] for p in all_pages if "error" in p.metadata},
        f"excluded_in_range_below_{MIN_CHARS}_chars": [p.page for p in in_range if p not in pages],
        "counted_pages": len(pages),
        "counted_chars": sum(p.metadata["char_count"] for p in pages),
    }
    (OUT / "ingest_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(json.dumps(log, indent=2))

    questions = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    stats = {}
    for name, chunker in STRATEGIES.items():
        started = time.perf_counter()
        chunks = [c for p in pages for c in chunker(p)]
        seconds = time.perf_counter() - started
        with (OUT / f"chunks_{name}.jsonl").open("w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids)), f"duplicate chunk IDs in {name}"
        lengths = [len(c.text) for c in chunks]
        # Is each gold evidence quote fully inside at least one chunk on a gold page?
        whole = [q["id"] for q in questions
                 if any(c.page in q["gold_page"] and flat(q["evidence_quote"]) in flat(c.text) for c in chunks)]
        stats[name] = {
            "chunks": len(chunks),
            "chars_total": sum(lengths),
            "len_min": min(lengths),
            "len_median": statistics.median(lengths),
            "len_mean": round(statistics.mean(lengths), 1),
            "len_max": max(lengths),
            "chunks_under_100_chars": sum(n < 100 for n in lengths),
            "chunk_seconds": round(seconds, 4),
            "evidence_whole_in_one_chunk": f"{len(whole)}/{len(questions)}",
            "evidence_split_or_missing": [q["id"] for q in questions if q["id"] not in whole],
        }
    (OUT / "chunk_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
