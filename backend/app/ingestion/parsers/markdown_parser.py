"""
Markdown / text document parser for documentation ingestion.
Splits documents by heading sections.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass
class DocChunk:
    """A section of a documentation file."""
    section:    str          # heading text, or "preamble" for text before first heading
    content:    str
    file_path:  str
    start_line: int
    end_line:   int
    doc_type:   str = "markdown"   # readme | architecture | api_doc | requirement


class MarkdownParser:
    """Split markdown/text files into heading-level sections."""

    def parse_file(self, file_path: str | Path, doc_type: str = "markdown") -> list[DocChunk]:
        path = Path(file_path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning(f"Cannot read {file_path}: {exc}")
            return []

        if not text.strip():
            return []

        lines = text.splitlines()
        chunks: list[DocChunk] = []
        sections: list[tuple[int, str, str]] = []  # (line_num, heading, content_start)

        # Find all headings
        current_heading = "preamble"
        current_start = 0
        current_lines: list[str] = []

        for i, line in enumerate(lines):
            m = HEADING_RE.match(line)
            if m:
                if current_lines:
                    chunks.append(DocChunk(
                        section=current_heading,
                        content="\n".join(current_lines).strip(),
                        file_path=str(file_path),
                        start_line=current_start + 1,
                        end_line=i,
                        doc_type=doc_type,
                    ))
                current_heading = m.group(2).strip()
                current_start = i
                current_lines = [line]
            else:
                current_lines.append(line)

        if current_lines:
            chunks.append(DocChunk(
                section=current_heading,
                content="\n".join(current_lines).strip(),
                file_path=str(file_path),
                start_line=current_start + 1,
                end_line=len(lines),
                doc_type=doc_type,
            ))

        # Filter empty sections
        return [c for c in chunks if len(c.content) > 20]
