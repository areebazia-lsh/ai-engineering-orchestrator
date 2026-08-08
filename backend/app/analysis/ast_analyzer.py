"""
AST analyzer for Python code dependency analysis.

Uses stdlib ast module to extract:
- Function signatures (name, parameters, return type, decorators)
- Class hierarchies (bases, methods)
- Imports (what modules/functions are imported)
- Call relationships (what functions/classes are called within a function)

Output: structured dependency graph for code intelligence queries.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class FunctionInfo:
    """Information about a single function or method."""
    name: str
    file_path: str
    start_line: int
    end_line: int
    parameters: List[str]
    return_type: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    class_name: Optional[str] = None  # None for module-level functions
    docstring: Optional[str] = None
    calls: List[str] = field(default_factory=list)  # functions/methods called
    imports: List[str] = field(default_factory=list)  # imports used
    attributes_accessed: List[str] = field(default_factory=list)  # self.attr or cls.attr


@dataclass
class ClassInfo:
    """Information about a single class."""
    name: str
    file_path: str
    start_line: int
    end_line: int
    bases: List[str]
    methods: List[FunctionInfo] = field(default_factory=list)
    class_attributes: Dict[str, Any] = field(default_factory=dict)
    docstring: Optional[str] = None


@dataclass
class ModuleInfo:
    """Information about a Python module."""
    file_path: str
    imports: List[str] = field(default_factory=list)
    functions: List[FunctionInfo] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    module_level_vars: Dict[str, Any] = field(default_factory=dict)


class ASTAnalyzer:
    """
    Analyze Python source files to extract dependency relationships.
    """

    def analyze_file(self, file_path: str | Path) -> Optional[ModuleInfo]:
        """
        Analyze a Python file and return its structure.
        Returns None if the file cannot be parsed.
        """
        path = Path(file_path)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning(f"Cannot read {file_path}: {exc}")
            return None

        if not source.strip():
            return None

        try:
            tree = ast.parse(source, filename=str(path))
            
            # Create visitor to collect information
            visitor = AnalysisVisitor(str(file_path), source)
            visitor.visit(tree)
            
            return visitor.get_module_info()
            
        except SyntaxError as exc:
            logger.warning(f"Syntax error in {file_path}: {exc}")
            return None
        except Exception as exc:
            logger.warning(f"Error analyzing {file_path}: {exc}")
            return None


class AnalysisVisitor(ast.NodeVisitor):
    """AST visitor that collects dependency information."""
    
    def __init__(self, file_path: str, source: str):
        self.file_path = file_path
        self.source = source
        self.lines = source.splitlines()
        
        # Current analysis state
        self.current_class: Optional[str] = None
        self.current_function: Optional[str] = None
        self.imports: List[str] = []
        self.functions: List[FunctionInfo] = []
        self.classes: List[ClassInfo] = []
        self._current_function_info: Optional[FunctionInfo] = None
        self._current_class_info: Optional[ClassInfo] = None
        
    def get_module_info(self) -> ModuleInfo:
        """Return the collected module information."""
        return ModuleInfo(
            file_path=self.file_path,
            imports=self.imports,
            functions=self.functions,
            classes=self.classes
        )
    
    def visit_Import(self, node: ast.Import) -> Any:
        """Record imports."""
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)
    
    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        """Record from-imports."""
        module = node.module or ""
        for alias in node.names:
            import_str = f"{module}.{alias.name}" if module else alias.name
            self.imports.append(import_str)
        self.generic_visit(node)
    
    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        """Analyze class definition."""
        # Save previous context
        prev_class = self.current_class
        
        # Extract class info
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                # Handle dotted names like typing.Generic
                bases.append(self._get_attribute_name(base))
        
        class_info = ClassInfo(
            name=node.name,
            file_path=self.file_path,
            start_line=node.lineno,
            end_line=node.end_lineno if hasattr(node, 'end_lineno') else node.lineno,
            bases=bases,
            docstring=ast.get_docstring(node)
        )
        
        # Set current class and visit body
        self.current_class = node.name
        self._current_class_info = class_info
        self.generic_visit(node)
        
        # Add to results
        self.classes.append(class_info)
        
        # Restore previous context
        self.current_class = prev_class
        self._current_class_info = None
    
    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._visit_function(node, is_async=False)
    
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._visit_function(node, is_async=True)
    
    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool) -> Any:
        """Analyze function/method definition."""
        # Save previous context
        prev_function = self.current_function
        
        # Extract function info
        params = []
        for arg in node.args.args:
            params.append(arg.arg)
        
        # Get decorators
        decorators = []
        for decorator in node.decorator_list:
            decorator_str = self._get_node_source(decorator)
            if decorator_str:
                decorators.append(decorator_str)
        
        # Create function info
        func_info = FunctionInfo(
            name=node.name,
            file_path=self.file_path,
            start_line=node.lineno,
            end_line=node.end_lineno if hasattr(node, 'end_lineno') else node.lineno,
            parameters=params,
            decorators=decorators,
            class_name=self.current_class,
            docstring=ast.get_docstring(node)
        )
        
        # Set current function and analyze body for calls
        self.current_function = node.name
        self._current_function_info = func_info
        
        # Visit body to collect calls
        for child in node.body:
            self.visit(child)
        
        # Add to appropriate collection
        if self.current_class and self._current_class_info:
            # It's a method
            self._current_class_info.methods.append(func_info)
        else:
            # It's a module-level function
            self.functions.append(func_info)
        
        # Restore context
        self.current_function = prev_function
        self._current_function_info = None
    
    def visit_Call(self, node: ast.Call) -> Any:
        """Record function/method calls."""
        if self._current_function_info:
            # Try to get the name of the called function
            call_name = self._get_call_name(node)
            if call_name:
                self._current_function_info.calls.append(call_name)
        
        self.generic_visit(node)
    
    def visit_Attribute(self, node: ast.Attribute) -> Any:
        """Record attribute access (self.attr, cls.attr)."""
        if self._current_function_info:
            # Check if this is self.attr or cls.attr
            if isinstance(node.value, ast.Name):
                var_name = node.value.id
                if var_name in ('self', 'cls'):
                    self._current_function_info.attributes_accessed.append(node.attr)
        
        self.generic_visit(node)
    
    def _get_node_source(self, node: ast.AST) -> Optional[str]:
        """Get source code for a node."""
        try:
            return ast.get_source_segment(self.source, node)
        except:
            return None
    
    def _get_call_name(self, node: ast.Call) -> Optional[str]:
        """Extract the name of a called function."""
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            # Handle method calls like obj.method()
            return self._get_attribute_name(node.func)
        return None
    
    def _get_attribute_name(self, node: ast.Attribute) -> str:
        """Convert attribute node to string (e.g., 'obj.attr' or 'module.func')."""
        parts = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))


def build_dependency_graph(modules: List[ModuleInfo]) -> Dict[str, Dict[str, Any]]:
    """
    Build a dependency graph from analyzed modules.
    
    Returns:
        Dict with keys: functions, classes, imports
    """
    graph = {
        "functions": {},
        "classes": {},
        "imports": set(),
        "dependencies": {}  # function/class -> what it depends on
    }
    
    # Collect all imports
    for module in modules:
        graph["imports"].update(module.imports)
    
    # Build function info
    for module in modules:
        for func in module.functions:
            key = func.name
            if func.class_name:
                key = f"{func.class_name}.{func.name}"
            
            graph["functions"][key] = {
                "file": module.file_path,
                "parameters": func.parameters,
                "calls": func.calls,
                "imports": func.imports,
                "attributes": func.attributes_accessed,
                "class": func.class_name,
                "lines": f"{func.start_line}-{func.end_line}"
            }
            
            # Add dependencies
            deps = set(func.calls)
            deps.update(func.imports)
            if deps:
                graph["dependencies"][key] = list(deps)
    
    # Build class info
    for module in modules:
        for cls in module.classes:
            graph["classes"][cls.name] = {
                "file": module.file_path,
                "bases": cls.bases,
                "methods": [m.name for m in cls.methods],
                "lines": f"{cls.start_line}-{cls.end_line}"
            }
    
    # Convert imports to list
    graph["imports"] = list(graph["imports"])
    
    return graph


def analyze_repository(repo_path: str | Path) -> Dict[str, Dict[str, Any]]:
    """
    Analyze all Python files in a repository and build dependency graph.
    """
    repo = Path(repo_path)
    analyzer = ASTAnalyzer()
    modules: List[ModuleInfo] = []
    
    # Walk Python files
    for py_file in repo.rglob("*.py"):
        # Skip hidden directories and __pycache__
        if any(part.startswith(".") or part == "__pycache__" for part in py_file.parts):
            continue
        
        module_info = analyzer.analyze_file(py_file)
        if module_info:
            modules.append(module_info)
            logger.debug(f"Analyzed {py_file}: {len(module_info.functions)} functions, {len(module_info.classes)} classes")
    
    # Build dependency graph
    return build_dependency_graph(modules)