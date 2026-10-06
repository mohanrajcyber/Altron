from __future__ import annotations

"""Safe PDF text extraction for ALTRON FLOWS Phase 2.

Uses pypdf. Never fabricates content. Password-protected / malformed → explicit error.
"""

from pathlib import Path
from typing import Any


class PdfExtractError(RuntimeError):
    """Raised when a PDF cannot be read safely."""


def extract_text(path: Path, *, max_chars: int = 64000, max_pages: int = 40) -> dict[str, Any]:
    """Extract plain text from a PDF under trusted roots (caller must resolve path).

    Returns:
      {text, pages, chars, encrypted: False, name, path}
    Raises PdfExtractError on malformed / encrypted / empty-unreadable PDFs.
    """
    path = Path(path)
    if not path.is_file():
        raise PdfExtractError(f"PDF not found: {path}")
    if path.suffix.lower() != ".pdf":
        raise PdfExtractError(f"Not a PDF: {path.name}")

    try:
        from pypdf import PdfReader
        from pypdf.errors import FileNotDecryptedError, PdfReadError
    except ImportError as exc:
        raise PdfExtractError("pypdf is not installed — cannot extract PDF text") from exc

    try:
        reader = PdfReader(str(path), strict=False)
    except PdfReadError as exc:
        raise PdfExtractError(f"Malformed PDF: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise PdfExtractError(f"PDF open failed: {exc}") from exc

    if getattr(reader, "is_encrypted", False):
        # Try empty password; if still locked → explicit error (never invent content)
        try:
            unlocked = reader.decrypt("")
        except Exception:
            unlocked = 0
        if not unlocked:
            raise PdfExtractError("Password-protected PDF — cannot extract without credentials")

    parts: list[str] = []
    page_count = len(reader.pages)
    try:
        for i, page in enumerate(reader.pages[:max_pages]):
            try:
                chunk = page.extract_text() or ""
            except FileNotDecryptedError as exc:
                raise PdfExtractError("Password-protected PDF — cannot extract without credentials") from exc
            except Exception as exc:  # noqa: BLE001
                raise PdfExtractError(f"PDF page {i+1} extract failed: {exc}") from exc
            if chunk.strip():
                parts.append(chunk)
    except PdfExtractError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PdfExtractError(f"PDF extract failed: {exc}") from exc

    text = "\n".join(parts).strip()
    if not text:
        # Honest empty — not fabricated. Still return structure; caller may treat as weak content.
        text = ""
    text = text[:max_chars]
    return {
        "text": text,
        "pages": page_count,
        "chars": len(text),
        "encrypted": False,
        "name": path.name,
        "path": str(path),
        "truncated": page_count > max_pages or len("\n".join(parts)) > max_chars,
    }


def write_simple_pdf(path: Path, lines: list[str]) -> Path:
    """Write a minimal real PDF with extractable Helvetica text (for tests)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Escape PDF string literals
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content_ops = ["BT", "/F1 12 Tf", "50 120 Td"]
    for i, line in enumerate(lines):
        if i:
            content_ops.append("0 -16 Td")
        content_ops.append(f"({esc(line)}) Tj")
    content_ops.append("ET")
    stream = "\n".join(content_ops)
    stream_bytes = stream.encode("latin-1", errors="replace")

    objects: list[bytes] = []
    objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objects.append(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 200] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
    )
    objects.append(
        f"4 0 obj<< /Length {len(stream_bytes)} >>stream\n".encode("ascii")
        + stream_bytes
        + b"\nendstream\nendobj\n"
    )
    objects.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects)+1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(bytes(out))
    return path
