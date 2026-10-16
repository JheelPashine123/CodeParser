"""Resolves semantic relationships between extracted code symbols.

Builds CONTAINS, IMPORTS, CALLS, INHERITS, and IMPLEMENTS graph edges.
Marks edges as resolved, unresolved, or ambiguous without inventing false links.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from graphagent.models import (
    Edge,
    EdgeType,
    Node,
    NodeType,
    ParseResult,
    RawCall,
    RawImport,
    RawInheritance,
    ResolutionStatus,
)

logger = logging.getLogger("graphagent.resolver")


class RelationshipResolver:
    """Builds and resolves cross-file relationships across all parsed entities."""

    def __init__(self, parse_results: List[ParseResult]) -> None:
        self.parse_results = parse_results
        self.nodes_by_id: Dict[str, Node] = {}
        self.edges_by_id: Dict[str, Edge] = {}

        # Symbol Lookup Tables
        self.symbols_by_file_and_name: Dict[Tuple[str, str], List[Node]] = {}
        self.symbols_by_name: Dict[str, List[Node]] = {}
        self.classes_by_name: Dict[str, List[Node]] = {}
        self.file_nodes_by_path: Dict[str, Node] = {}
        self.imports_by_file: Dict[str, List[RawImport]] = {}

    def resolve(self) -> Tuple[List[Node], List[Edge]]:
        """Execute full relationship resolution pipeline.

        Returns:
            Tuple[List[Node], List[Edge]]: Deduplicated nodes and resolved edges.
        """
        self._index_entities()
        self._resolve_containment()
        self._resolve_inheritance()
        self._resolve_imports()
        self._resolve_calls()

        # Sort nodes and edges deterministically
        sorted_nodes = sorted(self.nodes_by_id.values(), key=lambda n: n.id)
        sorted_edges = sorted(self.edges_by_id.values(), key=lambda e: (e.source, e.type, e.target, e.line or 0))
        return sorted_nodes, sorted_edges

    def _index_entities(self) -> None:
        """Populate lookup tables from all parse results."""
        for result in self.parse_results:
            self.imports_by_file[result.file_path] = result.raw_imports

            for node in result.nodes:
                # Deduplicate nodes by ID
                if node.id not in self.nodes_by_id:
                    self.nodes_by_id[node.id] = node

                if node.type == NodeType.FILE.value:
                    self.file_nodes_by_path[node.file_path] = node
                else:
                    file_key = (node.file_path, node.name)
                    self.symbols_by_file_and_name.setdefault(file_key, []).append(node)
                    self.symbols_by_name.setdefault(node.name, []).append(node)

                    if node.type in (NodeType.CLASS.value, NodeType.STRUCT.value, NodeType.INTERFACE.value):
                        self.classes_by_name.setdefault(node.name, []).append(node)

    def _resolve_containment(self) -> None:
        """Create CONTAINS edges from parent_id references."""
        for node in self.nodes_by_id.values():
            if node.parent_id and node.parent_id in self.nodes_by_id:
                edge_id = f"edge:{node.parent_id}->CONTAINS->{node.id}"
                self.edges_by_id[edge_id] = Edge(
                    id=edge_id,
                    source=node.parent_id,
                    target=node.id,
                    type=EdgeType.CONTAINS.value,
                    resolution=ResolutionStatus.RESOLVED.value,
                    line=node.start_line,
                )

    def _resolve_inheritance(self) -> None:
        """Resolve INHERITS and IMPLEMENTS edges."""
        for result in self.parse_results:
            for inh in result.raw_inheritances:
                edge_type = EdgeType.IMPLEMENTS.value if inh.is_interface else EdgeType.INHERITS.value
                base_clean = inh.base_name.split(".")[-1].split("::")[-1].strip()

                target_id = None
                resolution = ResolutionStatus.UNRESOLVED.value
                confidence = 1.0

                # 1. Check local file classes
                local_candidates = self.symbols_by_file_and_name.get((inh.file_path, base_clean), [])
                matching_local = [c for c in local_candidates if c.type in (NodeType.CLASS.value, NodeType.STRUCT.value, NodeType.INTERFACE.value)]

                if matching_local:
                    target_id = matching_local[0].id
                    resolution = ResolutionStatus.RESOLVED.value

                # 2. Check imported classes in this file
                if not target_id:
                    for imp in self.imports_by_file.get(inh.file_path, []):
                        if base_clean in imp.imported_symbols or imp.source_module.endswith(f"/{base_clean}") or imp.source_module.endswith(f".{base_clean}"):
                            # Look up in candidate targets
                            candidates = self.classes_by_name.get(base_clean, [])
                            if candidates:
                                target_id = candidates[0].id
                                resolution = ResolutionStatus.RESOLVED.value
                                break

                # 3. Check single unique global class
                if not target_id:
                    global_matches = self.classes_by_name.get(base_clean, [])
                    if len(global_matches) == 1:
                        target_id = global_matches[0].id
                        resolution = ResolutionStatus.INFERRED.value
                        confidence = 0.85
                    elif len(global_matches) > 1:
                        target_id = f"symbol:ambiguous:{base_clean}"
                        resolution = ResolutionStatus.AMBIGUOUS.value
                        confidence = 0.5
                    else:
                        target_id = f"symbol:external:{base_clean}"
                        resolution = ResolutionStatus.UNRESOLVED.value
                        confidence = 0.0

                edge_id = f"edge:{inh.class_id}->{edge_type}->{target_id}"
                self.edges_by_id[edge_id] = Edge(
                    id=edge_id,
                    source=inh.class_id,
                    target=target_id,
                    type=edge_type,
                    resolution=resolution,
                    line=inh.line,
                    confidence=confidence,
                    metadata={"base_name": inh.base_name},
                )

    def _resolve_imports(self) -> None:
        """Resolve IMPORTS edges between source files and target modules."""
        for result in self.parse_results:
            source_file_id = f"file:{result.file_path}"
            if source_file_id not in self.nodes_by_id:
                continue

            for imp in result.raw_imports:
                target_file_id = None
                resolution = ResolutionStatus.UNRESOLVED.value
                confidence = 1.0

                # Try to resolve relative file paths
                if imp.is_relative or imp.source_module.startswith("."):
                    current_dir = Path(result.file_path).parent
                    candidate_base = (current_dir / imp.source_module).resolve()
                    # Check existing files
                    for known_path, file_node in self.file_nodes_by_path.items():
                        known_p = Path(known_path)
                        # Check path without extension or exact
                        if known_p == candidate_base or known_p.with_suffix("") == candidate_base:
                            target_file_id = file_node.id
                            resolution = ResolutionStatus.RESOLVED.value
                            break

                # Try matching by repository module path
                if not target_file_id:
                    clean_mod = imp.source_module.replace(".", "/").replace("\\", "/")
                    for known_path, file_node in self.file_nodes_by_path.items():
                        no_ext = str(Path(known_path).with_suffix(""))
                        if no_ext.endswith(clean_mod) or known_path.endswith(clean_mod):
                            target_file_id = file_node.id
                            resolution = ResolutionStatus.RESOLVED.value
                            break

                if not target_file_id:
                    target_file_id = f"external:{imp.source_module}"
                    resolution = ResolutionStatus.UNRESOLVED.value
                    confidence = 0.0

                edge_id = f"edge:{source_file_id}->IMPORTS->{target_file_id}:{imp.line}"
                self.edges_by_id[edge_id] = Edge(
                    id=edge_id,
                    source=source_file_id,
                    target=target_file_id,
                    type=EdgeType.IMPORTS.value,
                    resolution=resolution,
                    line=imp.line,
                    confidence=confidence,
                    metadata={
                        "source_module": imp.source_module,
                        "symbols": imp.imported_symbols,
                    },
                )

    def _resolve_calls(self) -> None:
        """Resolve CALLS edges between callers and target functions/methods."""
        for result in self.parse_results:
            for call in result.raw_calls:
                caller_node = self.nodes_by_id.get(call.caller_id)
                if not caller_node:
                    continue

                called_name = call.called_name.split(".")[-1].split("::")[-1].strip()
                if not called_name:
                    continue

                target_id = None
                resolution = ResolutionStatus.UNRESOLVED.value
                confidence = 1.0

                # 1. Local resolution in the same file
                local_candidates = self.symbols_by_file_and_name.get((call.file_path, called_name), [])
                functions_local = [c for c in local_candidates if c.type in (NodeType.FUNCTION.value, NodeType.METHOD.value)]

                if call.receiver_name in ("self", "this") and caller_node.parent_id:
                    # Look inside caller's class
                    parent_methods = [
                        m for m in functions_local if m.parent_id == caller_node.parent_id
                    ]
                    if parent_methods:
                        target_id = parent_methods[0].id
                        resolution = ResolutionStatus.RESOLVED.value

                if not target_id and functions_local:
                    target_id = functions_local[0].id
                    resolution = ResolutionStatus.RESOLVED.value

                # 2. Check imported symbols
                if not target_id:
                    for imp in self.imports_by_file.get(call.file_path, []):
                        if called_name in imp.imported_symbols:
                            global_matches = self.symbols_by_name.get(called_name, [])
                            matching_imported = [m for m in global_matches if called_name == m.name]
                            if matching_imported:
                                target_id = matching_imported[0].id
                                resolution = ResolutionStatus.RESOLVED.value
                                break

                # 3. Single global candidate in repo
                if not target_id:
                    global_funcs = [
                        n for n in self.symbols_by_name.get(called_name, [])
                        if n.type in (NodeType.FUNCTION.value, NodeType.METHOD.value)
                    ]
                    if len(global_funcs) == 1:
                        target_id = global_funcs[0].id
                        resolution = ResolutionStatus.INFERRED.value
                        confidence = 0.8
                    elif len(global_funcs) > 1:
                        target_id = f"symbol:ambiguous:{called_name}"
                        resolution = ResolutionStatus.AMBIGUOUS.value
                        confidence = 0.4
                    else:
                        target_id = f"symbol:unresolved:{called_name}"
                        resolution = ResolutionStatus.UNRESOLVED.value
                        confidence = 0.0

                edge_id = f"edge:{call.caller_id}->CALLS->{target_id}:{call.line}:{call.column}"
                self.edges_by_id[edge_id] = Edge(
                    id=edge_id,
                    source=call.caller_id,
                    target=target_id,
                    type=EdgeType.CALLS.value,
                    resolution=resolution,
                    line=call.line,
                    confidence=confidence,
                    metadata={
                        "called_name": call.called_name,
                        "receiver": call.receiver_name,
                    },
                )
