"""
Tree-sitter Python parser.

Walks a Python source file and extracts semantic units:
  - Module-level docstrings
  - Class definitions (with their methods)
  - Function / method definitions
  - Standalone code blocks (top-level statements)

Each extracted unit becomes one "raw chunk" that the semantic chunker
then decides whether to keep as-is or split further.

Design decisions:
  - We use tree-sitter for structural extraction (not regex) because it
    correctly handles nested classes, decorators, multi-line signatures,
    and string literals inside code.
  - We fall back to raw text splitting if tree-sitter fails on a file
    (malformed syntax, encoding issues) rather than dropping the file.
  - We do NOT use the LLM here — pure AST traversal.
  - Source text is decoded as UTF-8 with errors='replace' to handle
    files with mixed encodings (common in legacy codebases).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy import so the rest of the app doesn't fail if tree-sitter is missing
try:
    import tree_sitter_python as tspython
    from tree_sitter import Language, Parser, Node
    _PY_LANGUAGE = Language(tspython.language())
    _PARSER_AVAILABLE = True
except ImportError:
    _PARSER_AVAILABLE = False
    logger.warning("tree-sitter-python not installed. Falling back to raw text splitting.")


@dataclass
class ParsedChunk:
    """A single semantic unit extracted from a source file."""
    chunk_type:    str              # "function" | "class" | "method" | "module_docstring" | "raw"
    name:          str              # function/class/method name, or "" for raw
    content:       str              # full source text of this chunk
    file_path:     str
    start_line:    int              # 1-indexed
    end_line:      int              # 1-indexed
    class_name:    Optional[str] = None   # set for methods
    decorators:    list[str] = field(default_factory=list)
    docstring:     Optional[str] = None


class PythonParser:
    """
    Extracts semantic chunks from Python source files using Tree-sitter.
    Falls back to line-based splitting if Tree-sitter is unavailable.
    """

    # How many lines triggers a "split large class" warning
    LARGE_CLASS_LINE_LIMIT = 300

    def __init__(self) -> None:
        if _PARSER_AVAILABLE:
            self._parser = Parser(_PY_LANGUAGE)
        else:
            self._parser = None

    def parse_file(self, file_path: str | Path) -> list[ParsedChunk]:
        """
        Parse a Python file and return a list of semantic chunks.
        Returns empty list if the file cannot be read.
        """
        path = Path(file_path)
        try:
            source = path.read_bytes()
            source_str = source.decode("utf-8", errors="replace")
        except OSError as exc:
            logger.warning(f"Cannot read {file_path}: {exc}")
            return []

        if not source_str.strip():
            return []

        if self._parser is None:
            return self._fallback_parse(source_str, str(file_path))

        try:
            return self._tree_sitter_parse(source, source_str, str(file_path))
        except Exception as exc:
            logger.warning(f"Tree-sitter failed on {file_path}: {exc}. Using fallback.")
            return self._fallback_parse(source_str, str(file_path))

    def _tree_sitter_parse(
        self, source_bytes: bytes, source_str: str, file_path: str
    ) -> list[ParsedChunk]:
        """Full structural parse using Tree-sitter."""
        tree = self._parser.parse(source_bytes)
        root = tree.root_node
        lines = source_str.splitlines()
        chunks: list[ParsedChunk] = []

        # Extract module-level docstring
        module_doc = self._extract_module_docstring(root, source_str)
        if module_doc:
            chunks.append(ParsedChunk(
                chunk_type="module_docstring",
                name="module",
                content=module_doc,
                file_path=file_path,
                start_line=1,
                end_line=module_doc.count("\n") + 1,
            ))

        # Walk top-level nodes
        for node in root.children:
            if node.type == "class_definition":
                chunks.extend(
                    self._extract_class(node, source_str, source_bytes, file_path)
                )
            elif node.type in ("function_definition", "decorated_definition"):
                chunk = self._extract_function(node, source_str, source_bytes, file_path)
                if chunk:
                    chunks.append(chunk)

        # If nothing found (e.g., script with no classes/functions), treat whole file as raw
        if not chunks:
            chunks.append(ParsedChunk(
                chunk_type="raw",
                name=Path(file_path).stem,
                content=source_str,
                file_path=file_path,
                start_line=1,
                end_line=len(lines),
            ))

        return chunks

    def _extract_class(
        self, node: "Node", source_str: str, source_bytes: bytes, file_path: str
    ) -> list[ParsedChunk]:
        """Extract a class and each of its methods as separate chunks."""
        chunks: list[ParsedChunk] = []
        class_name = self._get_node_text(node.child_by_field_name("name"), source_bytes)
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        # Class-level chunk (header + class docstring only, not methods)
        class_header = self._extract_class_header(node, source_str, source_bytes)
        chunks.append(ParsedChunk(
            chunk_type="class",
            name=class_name,
            content=class_header,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            docstring=self._extract_node_docstring(node, source_bytes),
        ))

        # Each method as its own chunk
        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                target = child
                if child.type == "decorated_definition":
                    for sub in child.children:
                        if sub.type == "function_definition":
                            target = sub
                            break
                if target.type == "function_definition":
                    method_chunk = self._extract_function(
                        child, source_str, source_bytes, file_path, class_name=class_name
                    )
                    if method_chunk:
                        chunks.append(method_chunk)

        return chunks

    def _extract_function(
        self,
        node: "Node",
        source_str: str,
        source_bytes: bytes,
        file_path: str,
        class_name: Optional[str] = None,
    ) -> Optional[ParsedChunk]:
        """Extract a function or method as a chunk."""
        # Unwrap decorated_definition
        actual_node = node
        decorators: list[str] = []
        if node.type == "decorated_definition":
            for child in node.children:
                if child.type == "decorator":
                    decorators.append(self._get_node_text(child, source_bytes).strip())
                elif child.type == "function_definition":
                    actual_node = child

        if actual_node.type != "function_definition":
            return None

        name_node = actual_node.child_by_field_name("name")
        func_name = self._get_node_text(name_node, source_bytes) if name_node else "unknown"
        content = self._get_node_text(node, source_bytes)  # include decorators
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        chunk_type = "method" if class_name else "function"

        return ParsedChunk(
            chunk_type=chunk_type,
            name=func_name,
            content=content,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            class_name=class_name,
            decorators=decorators,
            docstring=self._extract_node_docstring(actual_node, source_bytes),
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _get_node_text(self, node: Optional["Node"], source_bytes: bytes) -> str:
        if node is None:
            return ""
        return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def _extract_module_docstring(self, root: "Node", source_str: str) -> Optional[str]:
        """Return the module-level docstring if present."""
        for child in root.children:
            if child.type == "expression_statement":
                for sub in child.children:
                    if sub.type == "string":
                        return source_str[child.start_byte:child.end_byte]
            elif child.type not in ("comment", "newline"):
                break
        return None

    def _extract_node_docstring(self, node: "Node", source_bytes: bytes) -> Optional[str]:
        """Extract the first string expression in a function/class body."""
        body = node.child_by_field_name("body")
        if body is None:
            return None
        for child in body.children:
            if child.type == "expression_statement":
                for sub in child.children:
                    if sub.type == "string":
                        return self._get_node_text(child, source_bytes)
            elif child.type not in ("comment", "newline"):
                break
        return None

    def _extract_class_header(
        self, node: "Node", source_str: str, source_bytes: bytes
    ) -> str:
        """Return class signature + docstring only (not method bodies)."""
        lines = self._get_node_text(node, source_bytes).splitlines()
        header_lines: list[str] = []
        in_docstring = False
        docstring_done = False

        for line in lines:
            stripped = line.strip()
            if not header_lines:  # class definition line
                header_lines.append(line)
                continue
            if not docstring_done:
                header_lines.append(line)
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    if in_docstring:
                        docstring_done = True
                    else:
                        in_docstring = True
                        if stripped.count('"""') >= 2 or stripped.count("'''") >= 2:
                            docstring_done = True
            else:
                break

        return "\n".join(header_lines) if header_lines else self._get_node_text(node, source_bytes)[:500]

    def _fallback_parse(self, source_str: str, file_path: str) -> list[ParsedChunk]:
        """
        Simple line-based fallback when tree-sitter is unavailable.
        Splits on class/def boundaries.
        """
        lines = source_str.splitlines()
        chunks: list[ParsedChunk] = []
        current_block: list[str] = []
        current_start = 1
        current_name = Path(file_path).stem
        current_type = "raw"

        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith(("class ", "def ", "async def ")):
                if current_block:
                    chunks.append(ParsedChunk(
                        chunk_type=current_type,
                        name=current_name,
                        content="\n".join(current_block),
                        file_path=file_path,
                        start_line=current_start,
                        end_line=i - 1,
                    ))
                current_block = [line]
                current_start = i
                if stripped.startswith("class "):
                    current_name = stripped.split("(")[0].replace("class ", "").strip()
                    current_type = "class"
                else:
                    current_name = stripped.split("(")[0].replace("async def ", "").replace("def ", "").strip()
                    current_type = "function"
            else:
                current_block.append(line)

        if current_block:
            chunks.append(ParsedChunk(
                chunk_type=current_type,
                name=current_name,
                content="\n".join(current_block),
                file_path=file_path,
                start_line=current_start,
                end_line=len(lines),
            ))

        return chunks
