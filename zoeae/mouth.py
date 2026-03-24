"""
Mouth — Data ingestion organ.

The mandibles. Eats raw data and chews it into fragments the brain
can digest. Handles text files, URLs (HTML fetch), JSON, CSV, and
PDF (when PyPDF2 is available). Chunk size adapts to developmental
bleed: high bleed = larger chunks (more context, less precise),
low bleed = smaller chunks (focused).

All ingested content is scrubbed by the exoskeleton before returning.
No external dependencies — stdlib only.

    mouth = Mouth(exo=Exoskeleton(), bleed=0.6)
    fragments = mouth.eat("path/to/data.csv")
    fragments = mouth.eat("https://example.com/report")
    fragments = mouth.eat_text("raw engineering notes go here")

AnnulusLabs LLC — Taos, NM
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Optional

from .accumulator import Fragment
from .exoskeleton import Exoskeleton


# ── CHUNK SIZE SCALING ──

def _chunk_size_for_bleed(bleed: float) -> int:
    """Map bleed width to chunk size in characters.
    High bleed = larger chunks (broad context, less precise).
    Low bleed = smaller chunks (focused, surgical)."""
    # Range: 512 chars (laser) to 8192 chars (divergent)
    if bleed > 0.7:
        return 8192
    elif bleed > 0.4:
        return 4096
    elif bleed > 0.15:
        return 2048
    else:
        return 512


def _chunk_overlap_for_bleed(bleed: float) -> int:
    """Overlap between chunks. More overlap at high bleed for associative links."""
    size = _chunk_size_for_bleed(bleed)
    return size // 4


# ── SOURCE DETECTION ──

def _detect_source(source: str) -> str:
    """Classify a source string: url, file, json_str, csv_str, or text."""
    stripped = source.strip()
    if stripped.startswith(("http://", "https://")):
        return "url"
    if os.path.exists(stripped):
        return "file"
    # Try JSON
    if stripped.startswith(("{", "[")):
        try:
            json.loads(stripped)
            return "json_str"
        except (json.JSONDecodeError, ValueError):
            pass
    # CSV heuristic: multiple commas on first line, multiple lines
    lines = stripped.split("\n", 3)
    if len(lines) >= 2 and lines[0].count(",") >= 2:
        return "csv_str"
    return "text"


def _detect_file_type(path: str) -> str:
    """Classify file by extension."""
    ext = os.path.splitext(path)[1].lower()
    return {
        ".json": "json", ".csv": "csv", ".pdf": "pdf",
        ".txt": "text", ".md": "text", ".rst": "text",
        ".html": "html", ".htm": "html",
        ".xml": "xml", ".yaml": "yaml", ".yml": "yaml",
        ".py": "text", ".js": "text", ".ts": "text",
        ".c": "text", ".h": "text", ".cpp": "text",
        ".toml": "text", ".cfg": "text", ".ini": "text",
        ".log": "text",
    }.get(ext, "text")


# ── MOUTH ──

class Mouth:
    """The data ingestion organ. Eats raw data, chews it into Fragments.

    Chunk size adapts to developmental bleed. All output is scrubbed
    by the exoskeleton — no secrets leak through the mandibles.
    """

    def __init__(self, exo: Optional[Exoskeleton] = None,
                 bleed: float = 0.5) -> None:
        self.exo = exo or Exoskeleton()
        self._bleed = bleed
        self._ingested: int = 0
        self._bytes_eaten: int = 0
        self._t0 = time.time()

    @property
    def bleed(self) -> float:
        return self._bleed

    @bleed.setter
    def bleed(self, value: float) -> None:
        self._bleed = max(0.0, min(1.0, value))

    # ── PRIMARY INTERFACE ──

    def eat(self, source: str) -> list[Fragment]:
        """Universal entry point. Detects source type and ingests.
        Accepts file paths, URLs, raw text, JSON strings, CSV strings."""
        kind = _detect_source(source)
        if kind == "url":
            return self.eat_url(source.strip())
        elif kind == "file":
            return self.eat_file(source.strip())
        elif kind == "json_str":
            return self._ingest_json(source.strip(), origin="inline")
        elif kind == "csv_str":
            return self._ingest_csv(source.strip(), origin="inline")
        else:
            return self.eat_text(source)

    def eat_file(self, path: str) -> list[Fragment]:
        """Ingest a file from disk."""
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            return [self._error_fragment(f"File not found: {path}")]

        ftype = _detect_file_type(path)

        if ftype == "pdf":
            return self._ingest_pdf(path)
        elif ftype == "json":
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    raw = f.read()
                return self._ingest_json(raw, origin=path)
            except Exception as e:
                return [self._error_fragment(f"JSON read error: {e}")]
        elif ftype == "csv":
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    raw = f.read()
                return self._ingest_csv(raw, origin=path)
            except Exception as e:
                return [self._error_fragment(f"CSV read error: {e}")]
        else:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    raw = f.read()
                return self._chew(raw, origin=path)
            except Exception as e:
                return [self._error_fragment(f"File read error: {e}")]

    def eat_url(self, url: str) -> list[Fragment]:
        """Fetch HTML from a URL and ingest it."""
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Zoeae/0.5 (data-ingestion)"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                encoding = resp.headers.get_content_charset() or "utf-8"
                text = raw.decode(encoding, errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            return [self._error_fragment(f"URL fetch error: {e}")]

        # Strip HTML tags — lightweight, no dependencies
        text = self._strip_html(text)
        return self._chew(text, origin=url)

    def eat_text(self, text: str) -> list[Fragment]:
        """Ingest raw text directly."""
        return self._chew(text, origin="direct")

    # ── STRUCTURED DATA ──

    def _ingest_json(self, raw: str, origin: str) -> list[Fragment]:
        """Parse JSON and flatten to text for chunking."""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            return [self._error_fragment(f"JSON parse error: {e}")]

        # Pretty-print for readable chunking
        text = json.dumps(data, indent=2, default=str, ensure_ascii=False)
        return self._chew(text, origin=origin, tag="json")

    def _ingest_csv(self, raw: str, origin: str) -> list[Fragment]:
        """Parse CSV and convert rows to readable text."""
        reader = csv.reader(io.StringIO(raw))
        rows = list(reader)
        if not rows:
            return [self._error_fragment("Empty CSV")]

        header = rows[0] if rows else []
        lines = []
        for i, row in enumerate(rows):
            if i == 0:
                lines.append(" | ".join(row))
                lines.append("-" * len(lines[0]))
            else:
                if header and len(row) == len(header):
                    lines.append(" | ".join(
                        f"{header[j]}={row[j]}" for j in range(len(row))
                    ))
                else:
                    lines.append(" | ".join(row))

        text = "\n".join(lines)
        return self._chew(text, origin=origin, tag="csv")

    def _ingest_pdf(self, path: str) -> list[Fragment]:
        """Extract text from PDF. Falls back gracefully if PyPDF2 unavailable."""
        try:
            import PyPDF2
        except ImportError:
            return [self._error_fragment(
                "PDF ingestion requires PyPDF2: pip install PyPDF2"
            )]

        try:
            pages = []
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for i, page in enumerate(reader.pages):
                    text = page.extract_text()
                    if text and text.strip():
                        pages.append(f"[page {i + 1}]\n{text.strip()}")
            if not pages:
                return [self._error_fragment("PDF contains no extractable text")]
            full = "\n\n".join(pages)
            return self._chew(full, origin=path, tag="pdf")
        except Exception as e:
            return [self._error_fragment(f"PDF extraction error: {e}")]

    # ── CHUNKING ENGINE ──

    def _chew(self, text: str, origin: str = "",
              tag: str = "text") -> list[Fragment]:
        """Break text into bleed-sized chunks, scrub through exoskeleton."""
        chunk_size = _chunk_size_for_bleed(self._bleed)
        overlap = _chunk_overlap_for_bleed(self._bleed)

        # Scrub the whole text first
        text = self.exo.scrub(text)

        self._bytes_eaten += len(text.encode("utf-8"))

        if len(text) <= chunk_size:
            frag = self._make_fragment(text, origin, tag, 0, 1)
            self._ingested += 1
            return [frag]

        fragments: list[Fragment] = []
        start = 0
        idx = 0
        while start < len(text):
            end = start + chunk_size

            # Try to break at a paragraph or sentence boundary
            if end < len(text):
                # Look for paragraph break
                para = text.rfind("\n\n", start, end)
                if para > start + chunk_size // 2:
                    end = para + 2
                else:
                    # Look for sentence break
                    for sep in (". ", ".\n", "! ", "? "):
                        sent = text.rfind(sep, start + chunk_size // 2, end)
                        if sent > start:
                            end = sent + len(sep)
                            break

            chunk = text[start:end].strip()
            if chunk:
                frag = self._make_fragment(chunk, origin, tag, idx, -1)
                fragments.append(frag)
                idx += 1

            start = end - overlap
            if start >= len(text):
                break

        # Patch total count now that we know it
        for i, frag in enumerate(fragments):
            frag.key = self._fragment_key(origin, tag, i, len(fragments))

        self._ingested += len(fragments)
        return fragments

    def _make_fragment(self, content: str, origin: str, tag: str,
                       index: int, total: int) -> Fragment:
        """Create a Fragment with a deterministic key."""
        key = self._fragment_key(origin, tag, index, total)
        return Fragment(
            key=key,
            content=content,
            score=0.5,
        )

    @staticmethod
    def _fragment_key(origin: str, tag: str, index: int, total: int) -> str:
        origin_hash = hashlib.sha256(origin.encode()).hexdigest()[:8]
        return f"mouth:{tag}:{origin_hash}:{index}/{total}"

    def _error_fragment(self, message: str) -> Fragment:
        """Return an error as a Fragment so callers always get the same type."""
        self._ingested += 1
        return Fragment(
            key=f"mouth:error:{hashlib.sha256(message.encode()).hexdigest()[:8]}",
            content=f"[ingestion error] {message}",
            score=0.0,
        )

    # ── HTML STRIPPING (stdlib only) ──

    @staticmethod
    def _strip_html(html: str) -> str:
        """Remove HTML tags and decode entities. Lightweight, no dependencies."""
        import re
        # Remove script and style blocks
        text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html,
                       flags=re.DOTALL | re.IGNORECASE)
        # Remove tags
        text = re.sub(r'<[^>]+>', ' ', text)
        # Decode common entities
        for entity, char in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                             ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")]:
            text = text.replace(entity, char)
        # Collapse whitespace
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    # ── STATS ──

    @property
    def stats(self) -> dict:
        return {
            "ingested": self._ingested,
            "bytes_eaten": self._bytes_eaten,
            "bleed": self._bleed,
            "chunk_size": _chunk_size_for_bleed(self._bleed),
            "uptime_s": round(time.time() - self._t0, 1),
        }
