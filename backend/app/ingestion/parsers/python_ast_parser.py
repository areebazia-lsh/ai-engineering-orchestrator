"""
Python AST parser using stdlib ast module.
Simpler replacement for tree-sitter per scope cuts.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


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


class PythonASTParser:
    """
    Extracts semantic chunks from Python source files using stdlib ast.
    """

    def parse_file(self, file_path: str | Path) -> list[ParsedChunk]:
        """
        Parse a Python file and return a list of semantic chunks.
        Returns empty list if the file cannot be read or parsed.
        """
        path = Path(file_path)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning(f"Cannot read {file_path}: {exc}")
            return []

        if not source.strip():
            return []

        try:
            tree = ast.parse(source, filename=str(path))
            lines = source.splitlines()
            chunks: list[ParsedChunk] = []
            
            # Extract module-level docstring
            module_doc = ast.get_docstring(tree)
            if module_doc:
                # Find the docstring node to get line numbers
                for node in ast.walk(tree):
                    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Str):
                        start_line = node.lineno
                        end_line = start_line
                        # Get exact lines for docstring
                        docstring_text = node.value.s
                        # Simple estimation - count newlines in docstring
                        if docstring_text:
                            end_line = start_line + docstring_text.count('\n')
                        chunks.append(ParsedChunk(
                            chunk_type="module_docstring",
                            name="module",
                            content=module_doc,
                            file_path=str(file_path),
                            start_line=start_line,
                            end_line=end_line,
                            docstring=module_doc
                        ))
                        break

            # Extract functions and classes
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Check if this is a method (nested inside a class)
                    class_name = None
                    parent = self._get_parent_class(node)
                    if parent:
                        class_name = parent.name
                    
                    # Get source lines
                    start_line = node.lineno
                    end_line = node.end_lineno if hasattr(node, 'end_lineno') else start_line
                    
                    # Get decorators
                    decorators = []
                    for decorator in node.decorator_list:
                        try:
                            decorator_text = ast.get_source_segment(source, decorator)
                            if decorator_text:
                                decorators.append(decorator_text)
                        except:
                            pass
                    
                    # Get content
                    try:
                        content = ast.get_source_segment(source, node)
                        if not content:
                            content = "\n".join(lines[start_line-1:end_line])
                    except:
                        content = "\n".join(lines[start_line-1:end_line])
                    
                    chunk_type = "method" if class_name else "function"
                    name = node.name
                    
                    chunks.append(ParsedChunk(
                        chunk_type=chunk_type,
                        name=name,
                        content=content,
                        file_path=str(file_path),
                        start_line=start_line,
                        end_line=end_line,
                        class_name=class_name,
                        decorators=decorators,
                        docstring=ast.get_docstring(node)
                    ))
                
                elif isinstance(node, ast.ClassDef):
                    # Class definition
                    start_line = node.lineno
                    end_line = node.end_lineno if hasattr(node, 'end_lineno') else start_line
                    
                    try:
                        content = ast.get_source_segment(source, node)
                        if not content:
                            content = "\n".join(lines[start_line-1:end_line])
                    except:
                        content = "\n".join(lines[start_line-1:end_line])
                    
                    chunks.append(ParsedChunk(
                        chunk_type="class",
                        name=node.name,
                        content=content,
                        file_path=str(file_path),
                        start_line=start_line,
                        end_line=end_line,
                        docstring=ast.get_docstring(node)
                    ))

            # If we found nothing, treat the whole file as raw
            if not chunks:
                chunks.append(ParsedChunk(
                    chunk_type="raw",
                    name=Path(file_path).stem,
                    content=source,
                    file_path=str(file_path),
                    start_line=1,
                    end_line=len(lines),
                ))

            return chunks

        except SyntaxError as exc:
            logger.warning(f"Syntax error in {file_path}: {exc}")
            # Fallback: treat whole file as raw chunk
            lines = source.splitlines()
            return [ParsedChunk(
                chunk_type="raw",
                name=Path(file_path).stem,
                content=source,
                file_path=str(file_path),
                start_line=1,
                end_line=len(lines),
            )]
        except Exception as exc:
            logger.warning(f"Error parsing {file_path} with AST: {exc}")
            return []

    def _get_parent_class(self, node: ast.AST) -> Optional[ast.ClassDef]:
        """Get the parent class of a function if it's a method."""
        parent = node
        while hasattr(parent, 'parent'):
            parent = parent.parent
            if isinstance(parent, ast.ClassDef):
                return parent
        return None


# Monkey-patch to add parent references
_original_visit = None
def _visit_with_parent(self, node):
    """Add parent references to nodes during traversal."""
    for child in ast.iter_child_nodes(node):
        child.parent = node
    if _original_visit:
        _original_visit(node)

# Patch the ast.NodeVisitor to add parent references
if not hasattr(ast.NodeVisitor, '_original_visit'):
    ast.NodeVisitor._original_visit = ast.NodeVisitor.visit
    ast.NodeVisitor.visit = _visit_with_parent