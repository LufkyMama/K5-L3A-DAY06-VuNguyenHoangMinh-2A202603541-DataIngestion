"""Manual test for src.ingestion.normalize_text.

Run from starter/:  python scripts/try_normalize.py
Optional real-page preview: python scripts/try_normalize.py ../data/corpus/<file>.pdf 21
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # Windows console is not UTF-8 by default

from src.ingestion import normalize_text  # noqa: E402

# (name, input, expected output)
CASES = [
    ("empty string", "", ""),
    ("only whitespace", "  \n\t \n ", ""),
    ("strip ends", "  hello  ", "hello"),
    ("collapse spaces in a line", "a    b\t\tc", "a b c"),
    ("trailing space before newline", "line one \nline two ", "line one\nline two"),
    ("windows newlines", "a\r\nb\rc", "a\nb\nc"),
    ("keep single line break", "a\nb", "a\nb"),
    ("keep paragraph break", "para 1\n\npara 2", "para 1\n\npara 2"),
    ("3+ newlines -> 2", "para 1\n\n\n\npara 2", "para 1\n\npara 2"),
    ("NFKC ligature", "ﬁle", "file"),                      # 'ﬁle'
    ("non-breaking space", "a b", "a b"),
    ("keep bullet / pi / dash", "• π – x", "• π – x"),
    ("keep case and punctuation", 'print("Hi!")', 'print("Hi!")'),
    ("keep Vietnamese", "Tiếng Việt", "Tiếng Việt"),
    ("decomposed -> composed", "Việt", "Việt"),  # combining marks
]


def run_cases() -> bool:
    failed = 0
    for name, given, expected in CASES:
        try:
            got = normalize_text(given)
        except Exception as exc:  # show the error, keep testing other cases
            got = f"<{type(exc).__name__}: {exc}>"
        if got == expected:
            print(f"PASS  {name}")
        else:
            failed += 1
            print(f"FAIL  {name}\n      input:    {given!r}\n      expected: {expected!r}\n      got:      {got!r}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return failed == 0


def preview_page(pdf_path: str, page: int) -> None:
    from pypdf import PdfReader

    raw = PdfReader(pdf_path).pages[page - 1].extract_text() or ""
    clean = normalize_text(raw)
    print(f"\n===== PDF page {page}: raw ({len(raw)} chars) =====\n{raw!r}")
    print(f"\n===== normalized ({len(clean)} chars) =====\n{clean}")


if __name__ == "__main__":
    ok = run_cases()
    if len(sys.argv) == 3:
        preview_page(sys.argv[1], int(sys.argv[2]))
    sys.exit(0 if ok else 1)
