"""Evaluate retrieved evidence and preserve per-query traces."""
import re
from collections import defaultdict
from typing import Any

from .ingestion import normalize_text


def _flat(text: str) -> str:
    """Compare text ignoring Unicode form and line-break/whitespace differences."""
    return re.sub(r"\s+", " ", normalize_text(text)).strip()


def _is_hit(question: dict[str, Any], hit: dict[str, Any]) -> bool:
    """A hit is on a gold source/page AND contains the full evidence quote (or a documented alternative)."""
    quotes = [question["evidence_quote"], *question.get("alternative_evidence_quotes", [])]
    return (hit["document_id"] == question["gold_source_id"]
            and hit["page"] in question["gold_page"]
            and any(_flat(q) in _flat(hit["text"]) for q in quotes))


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Automatic Hit@1 / Evidence Hit@3 only. Coherence and grounding stay manual labels."""
    flags = [_is_hit(question, h) for h in hits[:3]]
    wanted = question.get("filter") or {}
    return {
        "id": question["id"],
        "split": question["split"],
        "type": question.get("type"),
        "question": question["question"],
        "gold_page": question["gold_page"],
        "hit_at_1": bool(flags[:1] and flags[0]),
        "hit_at_3": any(flags),
        "first_hit_rank": flags.index(True) + 1 if any(flags) else None,
        "top3": [{"rank": i + 1, "chunk_id": h["chunk_id"], "page": h["page"],
                  "chapter": h["metadata"].get("chapter"), "score": round(h["score"], 4),
                  "is_hit": f, "text": h["text"]} for i, (h, f) in enumerate(zip(hits, flags))],
        # Does every returned chunk match the question's filter? None when the question has no filter.
        "filter_compliant": (all(h["metadata"].get(k) == v for h in hits for k, v in wanted.items())
                             if wanted else None),
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Hit@1 and Evidence Hit@3 per strategy and split, as counts and fractions."""
    groups = defaultdict(list)
    for t in traces:
        groups[(t["strategy"], t["split"])].append(t)
    summary = {}
    for (strategy, split), items in sorted(groups.items()):
        n = len(items)
        h1 = sum(t["hit_at_1"] for t in items)
        h3 = sum(t["hit_at_3"] for t in items)
        filtered = [t for t in items if t["filter_compliant"] is not None]
        summary.setdefault(strategy, {})[split] = {
            "n": n,
            "hit_at_1": f"{h1}/{n}",
            "hit_at_3": f"{h3}/{n}",
            "hit_at_1_rate": round(h1 / n, 3),
            "hit_at_3_rate": round(h3 / n, 3),
            "filter_compliance": (f"{sum(t['filter_compliant'] for t in filtered)}/{len(filtered)}"
                                  if filtered else "N/A"),
            "missed": [t["id"] for t in items if not t["hit_at_3"]],
        }
    return summary
