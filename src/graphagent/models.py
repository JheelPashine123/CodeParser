"""Data models for GraphAgent Code Parser.

Defines schemas for nodes, edges, parse results, relationships, and the final JSON export.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class NodeType(str, Enum):
    FILE = "file"
    MODULE = "module"
    CLASS = "class"
    INTERFACE = "interface"
    STRUCT = "struct"
    TRAIT = "trait"
    ENUM = "enum"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"
    CONSTANT = "constant"


class EdgeType(str, Enum):
    CONTAINS = "CONTAINS"
    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    DEFINES = "DEFINES"
    REFERENCES = "REFERENCES"


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"
    INFERRED = "inferred"


@dataclass
class Node:
    """Represents a code entity in the graph (file, class, function, etc.)."""
    id: str
    type: str
    name: str
    file_path: str
    start_line: int
    end_line: int
    language: str
    parameters: Optional[List[str]] = None
    return_type: Optional[str] = None
    parent_id: Optional[str] = None
    docstring: Optional[str] = None
    modifiers: Optional[List[str]] = None
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert node to JSON-serializable dictionary."""
        d = {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "language": self.language,
        }
        if self.parameters is not None:
            d["parameters"] = self.parameters
        if self.return_type is not None:
            d["return_type"] = self.return_type
        if self.parent_id is not None:
            d["parent_id"] = self.parent_id
        if self.docstring is not None:
            d["docstring"] = self.docstring
        if self.modifiers:
            d["modifiers"] = self.modifiers
        if self.properties:
            d["properties"] = self.properties
        return d


@dataclass
class Edge:
    """Represents a directed relationship between two code entities."""
    id: str
    source: str
    target: str
    type: str
    resolution: str = ResolutionStatus.RESOLVED.value
    line: Optional[int] = None
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert edge to JSON-serializable dictionary."""
        d = {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "resolution": self.resolution,
        }
        if self.line is not None:
            d["line"] = self.line
        if self.confidence < 1.0:
            d["confidence"] = round(self.confidence, 2)
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class RawCall:
    """Intermediate structure for a detected function/method invocation."""
    caller_id: str
    called_name: str
    receiver_name: Optional[str] = None
    line: int = 0
    column: int = 0
    file_path: str = ""


@dataclass
class RawImport:
    """Intermediate structure for an import statement."""
    file_path: str
    source_module: str
    imported_symbols: List[str] = field(default_factory=list)
    alias: Optional[str] = None
    line: int = 0
    is_relative: bool = False


@dataclass
class RawInheritance:
    """Intermediate structure for class inheritance or interface implementation."""
    class_id: str
    base_name: str
    line: int = 0
    file_path: str = ""
    is_interface: bool = False


@dataclass
class ParseResult:
    """Container for entities extracted from a single source file."""
    file_path: str
    language: str
    success: bool
    error: Optional[str] = None
    nodes: List[Node] = field(default_factory=list)
    raw_calls: List[RawCall] = field(default_factory=list)
    raw_imports: List[RawImport] = field(default_factory=list)
    raw_inheritances: List[RawInheritance] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class RepositoryInfo:
    root: str
    name: str

    def to_dict(self) -> Dict[str, str]:
        return {"root": self.root, "name": self.name}


@dataclass
class MetadataInfo:
    parser_version: str
    generated_at: str
    languages: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parser_version": self.parser_version,
            "generated_at": self.generated_at,
            "languages": self.languages,
        }


@dataclass
class SummaryInfo:
    files_scanned: int = 0
    files_parsed: int = 0
    nodes_count: int = 0
    edges_count: int = 0
    errors_count: int = 0

    def to_dict(self) -> Dict[str, int]:
        return asdict(self)


@dataclass
class GraphData:
    """Root graph structure matching the required JSON schema."""
    schema_version: str = "1.0"
    repository: RepositoryInfo = field(default_factory=lambda: RepositoryInfo(".", "unknown"))
    metadata: MetadataInfo = field(default_factory=lambda: MetadataInfo("0.1.0", "", []))
    nodes: List[Node] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    summary: SummaryInfo = field(default_factory=SummaryInfo)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "repository": self.repository.to_dict(),
            "metadata": self.metadata.to_dict(),
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "summary": self.summary.to_dict(),
            "warnings": self.warnings,
        }
