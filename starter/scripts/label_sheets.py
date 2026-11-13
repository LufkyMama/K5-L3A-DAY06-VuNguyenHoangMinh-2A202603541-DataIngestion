"""Create manual labeling sheets, then summarize them after you fill them in.

Run from starter/:
    python scripts/label_sheets.py make        # writes results/manual/*.csv (refuses to overwrite)
    python scripts/label_sheets.py summarize   # reads your labels, writes results/manual/summary.json

Sheets (open in Excel; UTF-8):
  coherence_labels.csv  10 fixed source positions x strategies A, B (C uses B's chunks). Fill `score` 0/1/2 + `reason`.
  metadata_labels.csv   5 test questions x top-3 x A/B/C. Fill `source_ok`, `page_ok`, `chapter_ok` with Y/N + `note`.
  grounding_labels.csv  5 test questions x A/B/C. Fill `score` 0/1/2 + `reason`.
"""
import csv
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from src.run import CHUNKERS, load_corpus  # noqa: E402

RESULTS = ROOT / "results"
OUT = RESULTS / "manual"
N_POSITIONS = 10


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig so Excel shows bullets correctly
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def anchor(page_text: str) -> str:
    """Fixed position rule: the first full line that starts at or after the middle of the page."""
    lines = page_text.split("\n")
    offset, middle = 0, len(page_text) // 2
    for line in lines:
        if offset >= middle and len(line) >= 20:
            return line
        offset += len(line) + 1
    return max(lines, key=len)


def make() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    targets = [OUT / n for n in ("coherence_labels.csv", "metadata_labels.csv", "grounding_labels.csv")]
    if any(p.exists() for p in targets):
        sys.exit("label sheets already exist; delete them first if you really want to regenerate (labels would be lost)")

    # 1. Coherence: positions chosen by rule before looking at scores (first 10 counted pages, middle line).
    _, pages = load_corpus()
    chunks = {name: [c for p in pages for c in chunker(p)] for name, chunker in CHUNKERS.items()}
    rows = []
    for i, page in enumerate(sorted(pages, key=lambda p: p.page)[:N_POSITIONS], start=1):
        line = anchor(page.text)
        probe = flat(line)[:40]
        for name in ("A", "B"):
            match = next((c for c in chunks[name] if c.page == page.page and probe in flat(c.text)), None)
            rows.append({"position_id": f"pos{i:02d}", "page": page.page, "anchor_line": line, "strategy": name,
                         "chunk_id": match.chunk_id if match else "NOT FOUND (anchor cut across chunks)",
                         "chunk_text": match.text if match else "", "score": "", "reason": ""})
    write_csv(targets[0], list(rows[0]), rows)

    # 2 + 3. Metadata and grounding on the 5 test questions, from the saved test traces.
    traces = [json.loads(line) for line in (RESULTS / "traces_test.jsonl").open(encoding="utf-8")]
    questions = {q["id"]: q for q in json.loads((ROOT.parent / "benchmark" / "questions.json").read_text(encoding="utf-8"))}
    by_id = {c.chunk_id: c for name in chunks for c in chunks[name]}  # C reuses B's chunk IDs
    meta_rows, ground_rows = [], []
    for t in traces:
        q = questions[t["id"]]
        for h in t["top3"]:
            stored = by_id[h["chunk_id"]]
            meta_rows.append({"question_id": t["id"], "strategy": t["strategy"], "rank": h["rank"],
                              "chunk_id": h["chunk_id"], "stored_document_id": stored.document_id,
                              "stored_source": stored.source,
                              "stored_page": h["page"], "stored_chapter": h["chapter"],
                              "chunk_text": h["text"], "source_ok": "", "page_ok": "", "chapter_ok": "", "note": ""})
        ground_rows.append({"question_id": t["id"], "strategy": t["strategy"], "question": q["question"],
                            "expected_answer": q["expected_answer"], "evidence_quote": q["evidence_quote"],
                            "gold_page": q["gold_page"], "filter_applied": t["filter_applied"],
                            "auto_hit_at_3": t["hit_at_3"],
                            "top3_text": "\n\n".join(f"[#{h['rank']} p{h['page']}] {h['text']}" for h in t["top3"]),
                            "score": "", "reason": ""})
    write_csv(targets[1], list(meta_rows[0]), meta_rows)
    write_csv(targets[2], list(ground_rows[0]), ground_rows)
    for p in targets:
        print("wrote", p)


def summarize() -> None:
    summary = {}

    coherence = read_csv(OUT / "coherence_labels.csv")
    by = defaultdict(list)
    for r in coherence:
        if r["score"].strip():
            by[r["strategy"]].append(int(r["score"]))
    summary["coherence"] = {s: {"n": len(v), "mean_of_2": round(statistics.mean(v), 2),
                                "counts": {k: v.count(k) for k in (0, 1, 2)}} for s, v in by.items()}
    summary["coherence"]["C"] = "same chunks as B"

    meta = read_csv(OUT / "metadata_labels.csv")
    by = defaultdict(lambda: [0, 0])
    for r in meta:
        marks = [r[k].strip().upper() for k in ("source_ok", "page_ok", "chapter_ok")]
        if all(marks):
            by[r["strategy"]][0] += all(m == "Y" for m in marks)
            by[r["strategy"]][1] += 1
    summary["metadata_complete_and_correct"] = {s: f"{ok}/{n}" for s, (ok, n) in by.items()}

    ground = read_csv(OUT / "grounding_labels.csv")
    by = defaultdict(list)
    for r in ground:
        if r["score"].strip():
            by[r["strategy"]].append(int(r["score"]))
    summary["grounding"] = {s: {"n": len(v), "mean_of_2": round(statistics.mean(v), 2),
                                "counts": {k: v.count(k) for k in (0, 1, 2)}} for s, v in by.items()}

    unlabeled = (sum(not r["score"].strip() for r in coherence) + sum(not r["score"].strip() for r in ground)
                 + sum(not all(r[k].strip() for k in ("source_ok", "page_ok", "chapter_ok")) for r in meta))
    summary["rows_still_unlabeled"] = unlabeled
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    {"make": make, "summarize": summarize}[sys.argv[1] if len(sys.argv) > 1 else "make"]()
