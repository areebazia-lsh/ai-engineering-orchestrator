"""
Semantic code chunker.

Takes ParsedChunk objects from the parser and produces final embedding-ready
chunks with consistent token budgets.

Design decisions:
  - Target: ~400 tokens per chunk (≈1600 chars at ~4 chars/token).
    Small enough to fit in retrieval context, large enough to be meaningful.
  - Functions and methods are kept whole unless they exceed MAX_CHARS.
  - Large functions are split at blank-line boundaries (paragraph split).
  - Each chunk gets a rich text prefix built from its metadata so the
    embedding captures structural context:
      "Python function `authenticate` in class `AuthService` file: auth/service.py\n\n<code>"
  - This "context-enriched embedding" approach significantly improves
    retrieval accuracy for code — the embedding knows what kind of thing it is.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.ingestion.parsers.python_ast_parser import ParsedChunk

logger = logging.getLogger(__name__)

# Approximate character limits (4 chars ≈ 1 token)
TARGET_CHARS  = 1_600   # ~400 tokens — ideal chunk size
MAX_CHARS     = 4_000   # ~1000 tokens — hard split above this


@dataclass
class EmbeddableChunk:
    """
    A final chunk ready for embedding.
    `embed_text` is what gets passed to the embedding model.
    `metadata` is what gets stored alongside the vector.
    """
    embed_text:  str               # Context-enriched text for embedding
    raw_content: str               # Original source, stored for retrieval display
    metadata:    dict[str, Any]    # Stored in vector DB alongside the vector
    chunk_id:    str               # Unique ID: file_path:chunk_type:name:start_line


class CodeChunker:
    """Convert ParsedChunks into EmbeddableChunks."""

    def __init__(
        self,
        project_id: str,
        project_name: str,
        language: str = "python",
    ) -> None:
        self.project_id   = project_id
        self.project_name = project_name
        self.language     = language

    def chunk(self, parsed: ParsedChunk) -> list[EmbeddableChunk]:
        """
        Convert one ParsedChunk into one or more EmbeddableChunks.
        Splits only if the content exceeds MAX_CHARS.
        """
        if len(parsed.content) <= MAX_CHARS:
            return [self._make_chunk(parsed, parsed.content)]

        # Large chunk — split at blank lines, keep each piece ≤ MAX_CHARS
        parts = self._split_large(parsed.content)
        result: list[EmbeddableChunk] = []
        for i, part in enumerate(parts):
            # Clone metadata with a part suffix
            sub = ParsedChunk(
                chunk_type=parsed.chunk_type,
                name=f"{parsed.name}[part{i+1}]",
                content=part,
                file_path=parsed.file_path,
                start_line=parsed.start_line,
                end_line=parsed.end_line,
                class_name=parsed.class_name,
                decorators=parsed.decorators,
                docstring=parsed.docstring,
            )
            result.append(self._make_chunk(sub, part))
        return result

    def _make_chunk(self, parsed: ParsedChunk, content: str) -> EmbeddableChunk:
        embed_text = self._build_embed_text(parsed, content)
        chunk_id = (
            f"{parsed.file_path}:{parsed.chunk_type}:{parsed.name}:{parsed.start_line}"
        )
        metadata: dict[str, Any] = {
            "project_id":    self.project_id,
            "project_name":  self.project_name,
            "file_path":     parsed.file_path,
            "language":      self.language,
            "chunk_type":    parsed.chunk_type,
            "function_name": parsed.name if parsed.chunk_type in ("function", "method") else "",
            "class_name":    parsed.class_name or (parsed.name if parsed.chunk_type == "class" else ""),
            "start_line":    parsed.start_line,
            "end_line":      parsed.end_line,
            "module":        self._module_from_path(parsed.file_path),
            "chunk_id":      chunk_id,
        }
        return EmbeddableChunk(
            embed_text=embed_text,
            raw_content=content,
            metadata=metadata,
            chunk_id=chunk_id,
        )

    def _build_embed_text(self, parsed: ParsedChunk, content: str) -> str:
        """
        Build context-enriched text for the embedding model.
        Structural context prefix significantly improves retrieval quality.
        """
        parts: list[str] = []

        if parsed.chunk_type == "function":
            parts.append(f"Python function `{parsed.name}`")
        elif parsed.chunk_type == "method":
            parts.append(f"Python method `{parsed.name}` in class `{parsed.class_name}`")
        elif parsed.chunk_type == "class":
            parts.append(f"Python class `{parsed.name}`")
        elif parsed.chunk_type == "module_docstring":
            parts.append("Python module documentation")
        else:
            parts.append(f"Python code")

        parts.append(f"file: {parsed.file_path}")

        if parsed.docstring:
            # Include docstring summary (first line only to save tokens)
            first_line = parsed.docstring.strip().strip('"""').strip("'''").splitlines()[0].strip()
            if first_line:
                parts.append(f"summary: {first_line}")

        header = " | ".join(parts)
        return f"{header}\n\n{content}"

    def _split_large(self, content: str) -> list[str]:
        """Split content at blank lines into TARGET_CHARS-sized pieces."""
        paragraphs = content.split("\n\n")
        parts: list[str] = []
        current: list[str] = []
        current_len = 0

        for para in paragraphs:
            if current_len + len(para) > MAX_CHARS and current:
                parts.append("\n\n".join(current))
                current = [para]
                current_len = len(para)
            else:
                current.append(para)
                current_len += len(para)

        if current:
            parts.append("\n\n".join(current))

        return parts or [content[:MAX_CHARS]]

    @staticmethod
    def _module_from_path(file_path: str) -> str:
        """Convert file path to dotted module name."""
        import re
        # Remove leading path separator variants and .py extension
        clean = re.sub(r"^[/\\]", "", file_path.replace("\\", "/"))
        clean = re.sub(r"\.py$", "", clean)
        return clean.replace("/", ".")
