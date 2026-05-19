"""One-time resume PDF → plain text.

Run once when a resume changes:
    python3 scripts/parse_resume.py \
        "/path/to/HarshKumarSharma_April 2026.pdf" \
        resumes/april_2026.txt
"""
from __future__ import annotations

import sys
from pathlib import Path

import pdfplumber


def parse(pdf_path: Path, out_path: Path) -> None:
    pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text.strip())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n\n".join(pages).strip() + "\n", encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: parse_resume.py <input.pdf> <output.txt>", file=sys.stderr)
        sys.exit(2)
    parse(Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser())
