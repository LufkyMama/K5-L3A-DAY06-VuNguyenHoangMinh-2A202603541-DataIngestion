"""Implement fixed-size and structure-aware chunking."""
import re

from .models import Chunk, DocumentPage

# Labels the OpenStax layout uses to start a new block (checkpoints, exercises, etc.).
_LABELS = {"CHECKPOINT", "CONCEPTS IN PRACTICE", "TRY IT", "Learning objectives", "Chapter Outline", "Introduction"}
_SECTION = re.compile(r"^\d+\.\d+ [A-Z]")      # "4.5 Chained decisions"
_EXAMPLE = re.compile(r"^(EXAMPLE|Table) \d+\.\d+")
_SENTENCE_END = (".", "?", "!")


def _make_chunk(page: DocumentPage, label: str, index: int, text: str) -> Chunk:
    """Copy page traceability into the chunk; the ID is stable across re-runs."""
    return Chunk(
        chunk_id=f"{page.document_id}:p{page.page:03d}:{label}:{index:03d}",
        document_id=page.document_id,
        source=page.source,
        page=page.page,
        text=text,
        metadata={k: v for k, v in page.metadata.items() if k in ("chapter", "chapter_number")},
    )


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Split text into windows of `size` characters; each window starts `size - overlap` after the last."""
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError(f"need size > 0 and 0 <= overlap < size, got size={size}, overlap={overlap}")
    text = page.text
    label = f"fixed{size}o{overlap}"
    chunks = []
    start = 0
    while start < len(text):
        piece = text[start:start + size].strip()
        if piece:
            chunks.append(_make_chunk(page, label, len(chunks), piece))
        if start + size >= len(text):  # this window already reached the end of the page
            break
        start += size - overlap
    return chunks


def _is_heading(line: str) -> bool:
    """Heuristic for a heading line, e.g. 'Continue', '5.4 Break and continue', 'CHECKPOINT'."""
    if line in _LABELS or _SECTION.match(line) or _EXAMPLE.match(line):
        return True
    return (
        len(line) <= 40
        and line[:1].isupper()
        and not line.endswith((".", ",", ":", ";", "?", "!"))
        and not any(ch in line for ch in "=()[]#\"'")  # code and output lines usually contain these
    )


def _blocks(text: str) -> list[str]:
    """Group layout lines into blocks: a block ends after a sentence end or before a heading."""
    blocks, current = [], []
    for line in text.split("\n"):
        if not line:
            continue
        if current and _is_heading(line):
            blocks.append("\n".join(current))
            current = []
        current.append(line)
        if line.endswith(_SENTENCE_END) and not _is_heading(line):
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def _split_oversized(block: str, max_size: int) -> list[str]:
    """Split a block longer than max_size at sentence ends; hard-cut a single sentence that is still too long."""
    parts, current = [], ""
    for sentence in re.split(r"(?<=[.?!])\s+", block):
        while len(sentence) > max_size:
            if current:
                parts.append(current)
                current = ""
            parts.append(sentence[:max_size])
            sentence = sentence[max_size:]
        candidate = f"{current} {sentence}" if current else sentence
        if len(candidate) > max_size:
            parts.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Pack sentence/heading-bounded blocks into chunks of at most max_size characters.

    A new chunk starts at a heading, so a topic like 'Continue' is not glued to the previous
    exercise, unless the current chunk is still shorter than max_size // 4 (avoids chunks that
    hold only a label such as 'CHECKPOINT'). Blocks longer than max_size are split at sentence ends.
    """
    if max_size <= 0:
        raise ValueError(f"need max_size > 0, got {max_size}")
    label = f"para{max_size}"
    min_size = max_size // 4
    texts, current = [], ""
    for block in _blocks(page.text):
        starts_topic = _is_heading(block.split("\n", 1)[0])
        if len(block) > max_size:
            if current:
                texts.append(current)
                current = ""
            texts.extend(_split_oversized(block, max_size))
            continue
        candidate = f"{current}\n{block}" if current else block
        if current and (len(candidate) > max_size or (starts_topic and len(current) >= min_size)):
            texts.append(current)
            current = block
        else:
            current = candidate
    if current:
        texts.append(current)
    return [_make_chunk(page, label, i, t) for i, t in enumerate(texts)]
