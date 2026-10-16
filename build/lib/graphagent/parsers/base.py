"""Base parser interface and helper utilities for Tree-sitter AST traversal."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, List, Optional

from tree_sitter import Language, Node as TSNode, Parser as TSParser

from graphagent.models import Node, NodeType, ParseResult


class BaseParser(ABC):
    """Abstract base class for language-specific Tree-sitter AST extractors."""

    language_name: str = "unknown"

    def __init__(self, language: Language) -> None:
        self.language = language
        self.ts_parser = TSParser(self.language)

    @abstractmethod
    def parse(self, file_path: str, content: bytes, rel_path: str) -> ParseResult:
        """Parse source code content and extract nodes, calls, imports, and inheritances."""
        pass

    @staticmethod
    def get_node_text(node: TSNode, content: bytes) -> str:
        """Extract decoded UTF-8 text for a given Tree-sitter AST node."""
        if not node:
            return ""
        return content[node.start_byte:node.end_byte].decode("utf-8", errors="replace").strip()

    @staticmethod
    def make_file_id(rel_path: str) -> str:
        """Generate a deterministic ID for a file node."""
        norm_path = rel_path.replace("\\", "/")
        return f"file:{norm_path}"

    @staticmethod
    def make_symbol_id(rel_path: str, qualified_name: str) -> str:
        """Generate a deterministic ID for a code symbol."""
        norm_path = rel_path.replace("\\", "/")
        return f"symbol:{norm_path}:{qualified_name}"

    def create_file_node(self, rel_path: str, line_count: int) -> Node:
        """Create the top-level File entity node."""
        norm_path = rel_path.replace("\\", "/")
        file_name = Path(norm_path).name
        return Node(
            id=self.make_file_id(norm_path),
            type=NodeType.FILE.value,
            name=file_name,
            file_path=norm_path,
            start_line=1,
            end_line=max(1, line_count),
            language=self.language_name,
            properties={"extension": Path(norm_path).suffix},
        )
