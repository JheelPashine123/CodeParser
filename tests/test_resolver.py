"""Unit tests for relationship resolution (CONTAINS, IMPORTS, CALLS, INHERITS)."""

from __future__ import annotations

from graphagent.models import (
    EdgeType,
    Node,
    NodeType,
    ParseResult,
    RawCall,
    RawImport,
    RawInheritance,
    ResolutionStatus,
)
from graphagent.relationship_resolver import RelationshipResolver


def test_resolver_containment():
    file_node = Node(
        id="file:app.py",
        type=NodeType.FILE.value,
        name="app.py",
        file_path="app.py",
        start_line=1,
        end_line=20,
        language="python",
    )
    class_node = Node(
        id="symbol:app.py:Service",
        type=NodeType.CLASS.value,
        name="Service",
        file_path="app.py",
        start_line=2,
        end_line=15,
        language="python",
        parent_id=file_node.id,
    )
    method_node = Node(
        id="symbol:app.py:Service.do_work",
        type=NodeType.METHOD.value,
        name="do_work",
        file_path="app.py",
        start_line=5,
        end_line=10,
        language="python",
        parent_id=class_node.id,
    )

    result = ParseResult(
        file_path="app.py",
        language="python",
        success=True,
        nodes=[file_node, class_node, method_node],
    )

    resolver = RelationshipResolver([result])
    nodes, edges = resolver.resolve()

    contains_edges = [e for e in edges if e.type == EdgeType.CONTAINS.value]
    assert len(contains_edges) == 2

    edge_targets = {e.target for e in contains_edges}
    assert class_node.id in edge_targets
    assert method_node.id in edge_targets


def test_resolver_calls_resolved_and_unresolved():
    caller = Node(
        id="symbol:app.py:main",
        type=NodeType.FUNCTION.value,
        name="main",
        file_path="app.py",
        start_line=1,
        end_line=10,
        language="python",
    )
    callee = Node(
        id="symbol:app.py:helper",
        type=NodeType.FUNCTION.value,
        name="helper",
        file_path="app.py",
        start_line=11,
        end_line=20,
        language="python",
    )

    result = ParseResult(
        file_path="app.py",
        language="python",
        success=True,
        nodes=[caller, callee],
        raw_calls=[
            RawCall(caller_id=caller.id, called_name="helper", line=5, file_path="app.py"),
            RawCall(caller_id=caller.id, called_name="non_existent_func", line=6, file_path="app.py"),
        ],
    )

    resolver = RelationshipResolver([result])
    nodes, edges = resolver.resolve()

    call_edges = [e for e in edges if e.type == EdgeType.CALLS.value]
    assert len(call_edges) == 2

    resolved_edge = next(e for e in call_edges if "helper" in e.target)
    assert resolved_edge.resolution == ResolutionStatus.RESOLVED.value
    assert resolved_edge.target == callee.id

    unresolved_edge = next(e for e in call_edges if "non_existent_func" in e.target)
    assert unresolved_edge.resolution == ResolutionStatus.UNRESOLVED.value
    assert unresolved_edge.confidence == 0.0


def test_resolver_inheritance():
    base_class = Node(
        id="symbol:base.py:BaseEntity",
        type=NodeType.CLASS.value,
        name="BaseEntity",
        file_path="base.py",
        start_line=1,
        end_line=10,
        language="python",
    )
    derived_class = Node(
        id="symbol:app.py:User",
        type=NodeType.CLASS.value,
        name="User",
        file_path="app.py",
        start_line=1,
        end_line=10,
        language="python",
    )

    res1 = ParseResult(file_path="base.py", language="python", success=True, nodes=[base_class])
    res2 = ParseResult(
        file_path="app.py",
        language="python",
        success=True,
        nodes=[derived_class],
        raw_inheritances=[
            RawInheritance(class_id=derived_class.id, base_name="BaseEntity", line=1, file_path="app.py")
        ],
    )

    resolver = RelationshipResolver([res1, res2])
    nodes, edges = resolver.resolve()

    inh_edges = [e for e in edges if e.type == EdgeType.INHERITS.value]
    assert len(inh_edges) == 1
    assert inh_edges[0].target == base_class.id
    assert inh_edges[0].resolution in (ResolutionStatus.RESOLVED.value, ResolutionStatus.INFERRED.value)
