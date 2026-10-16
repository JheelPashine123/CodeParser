"""TypeScript & TSX source code parser using Tree-sitter.

Extends JavaScript parser to extract interfaces, types, enums, and type-annotated declarations.
"""

from __future__ import annotations

from typing import Any, List, Optional

from tree_sitter import Language, Node as TSNode

from graphagent.models import (
    Node,
    NodeType,
    ParseResult,
    RawInheritance,
)
from graphagent.parsers.javascript_parser import JavaScriptParser


class TypeScriptParser(JavaScriptParser):
    language_name = "typescript"

    def __init__(self, language: Language, is_tsx: bool = False) -> None:
        super().__init__(language)
        self.is_tsx = is_tsx
        if is_tsx:
            self.language_name = "tsx"

    def _process_node(
        self,
        node: TSNode,
        content: bytes,
        rel_path: str,
        parent_id: str,
        result: ParseResult,
        scope_prefix: str = "",
    ) -> None:
        ntype = node.type

        if ntype == "interface_declaration":
            self._extract_interface(node, content, rel_path, parent_id, result, scope_prefix)

        elif ntype == "enum_declaration":
            self._extract_enum(node, content, rel_path, parent_id, result, scope_prefix)

        elif ntype == "type_alias_declaration":
            self._extract_type_alias(node, content, rel_path, parent_id, result, scope_prefix)

        else:
            super()._process_node(node, content, rel_path, parent_id, result, scope_prefix)

    def _extract_interface(
        self,
        node: TSNode,
        content: bytes,
        rel_path: str,
        parent_id: str,
        result: ParseResult,
        scope_prefix: str,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        interface_name = self.get_node_text(name_node, content)
        qualified_name = f"{scope_prefix}{interface_name}" if scope_prefix else interface_name
        interface_id = self.make_symbol_id(rel_path, qualified_name)

        interface_node = Node(
            id=interface_id,
            type=NodeType.INTERFACE.value,
            name=interface_name,
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            parent_id=parent_id,
            properties={"qualified_name": qualified_name},
        )
        result.nodes.append(interface_node)

        # Extends clauses on interfaces
        for ch in node.children:
            if ch.type == "extends_type_clause":
                for sub in ch.children:
                    if sub.type in ("identifier", "type_identifier"):
                        base_name = self.get_node_text(sub, content)
                        if base_name and base_name != "extends":
                            result.raw_inheritances.append(
                                RawInheritance(
                                    class_id=interface_id,
                                    base_name=base_name,
                                    line=ch.start_point.row + 1,
                                    file_path=rel_path,
                                    is_interface=True,
                                )
                            )

        # Walk interface body to extract method signatures
        body_node = node.child_by_field_name("body")
        if body_node:
            for member in body_node.children:
                if member.type == "method_signature":
                    m_name_node = member.child_by_field_name("name")
                    if m_name_node:
                        m_name = self.get_node_text(m_name_node, content)
                        m_qual = f"{qualified_name}.{m_name}"
                        m_id = self.make_symbol_id(rel_path, m_qual)
                        m_params = self._extract_parameters(member, content)
                        ret_node = member.child_by_field_name("return_type")
                        ret_type = self.get_node_text(ret_node, content) if ret_node else None

                        result.nodes.append(
                            Node(
                                id=m_id,
                                type=NodeType.METHOD.value,
                                name=m_name,
                                file_path=rel_path,
                                start_line=member.start_point.row + 1,
                                end_line=member.end_point.row + 1,
                                language=self.language_name,
                                parameters=m_params,
                                return_type=ret_type,
                                parent_id=interface_id,
                                properties={"qualified_name": m_qual, "is_abstract": True},
                            )
                        )

    def _extract_enum(
        self,
        node: TSNode,
        content: bytes,
        rel_path: str,
        parent_id: str,
        result: ParseResult,
        scope_prefix: str,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        enum_name = self.get_node_text(name_node, content)
        qualified_name = f"{scope_prefix}{enum_name}" if scope_prefix else enum_name
        enum_id = self.make_symbol_id(rel_path, qualified_name)

        enum_node = Node(
            id=enum_id,
            type=NodeType.ENUM.value,
            name=enum_name,
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            parent_id=parent_id,
            properties={"qualified_name": qualified_name},
        )
        result.nodes.append(enum_node)

    def _extract_type_alias(
        self,
        node: TSNode,
        content: bytes,
        rel_path: str,
        parent_id: str,
        result: ParseResult,
        scope_prefix: str,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        type_name = self.get_node_text(name_node, content)
        qualified_name = f"{scope_prefix}{type_name}" if scope_prefix else type_name
        type_id = self.make_symbol_id(rel_path, qualified_name)

        alias_node = Node(
            id=type_id,
            type="type",
            name=type_name,
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            parent_id=parent_id,
            properties={"qualified_name": qualified_name},
        )
        result.nodes.append(alias_node)
