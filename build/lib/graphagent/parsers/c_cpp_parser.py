"""C and C++ source code parser using Tree-sitter.

Extracts classes, structs, functions, methods, #include preprocessors, and function calls.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional

from tree_sitter import Language, Node as TSNode

from graphagent.models import (
    Node,
    NodeType,
    ParseResult,
    RawCall,
    RawImport,
    RawInheritance,
)
from graphagent.parsers.base import BaseParser


class CCppParser(BaseParser):
    language_name = "cpp"

    def __init__(self, language: Language, is_c: bool = False) -> None:
        super().__init__(language)
        self.is_c = is_c
        if is_c:
            self.language_name = "c"

    def parse(self, file_path: str, content: bytes, rel_path: str) -> ParseResult:
        result = ParseResult(file_path=rel_path, language=self.language_name, success=True)
        try:
            tree = self.ts_parser.parse(content)
        except Exception as exc:
            result.success = False
            result.error = f"Tree-sitter parse failure: {exc}"
            return result

        lines = content.splitlines()
        file_node = self.create_file_node(rel_path, len(lines))
        result.nodes.append(file_node)

        self._walk_node(tree.root_node, content, rel_path, parent_id=file_node.id, result=result)
        return result

    def _walk_node(
        self,
        node: TSNode,
        content: bytes,
        rel_path: str,
        parent_id: str,
        result: ParseResult,
        scope_prefix: str = "",
    ) -> None:
        for child in node.children:
            ntype = child.type

            if ntype == "preproc_include":
                self._extract_include(child, content, rel_path, result)

            elif ntype in ("class_specifier", "struct_specifier"):
                self._extract_class_or_struct(child, content, rel_path, parent_id, result, scope_prefix)

            elif ntype == "function_definition":
                self._extract_function(child, content, rel_path, parent_id, result, scope_prefix)

            elif ntype == "call_expression":
                self._extract_call(child, content, rel_path, caller_id=parent_id, result=result)

            elif ntype in ("field_declaration", "declaration"):
                # Check for inline function definitions or method calls
                self._walk_node(child, content, rel_path, parent_id, result, scope_prefix)

            else:
                if child.child_count > 0 and ntype not in ("class_specifier", "struct_specifier", "function_definition"):
                    self._walk_node(child, content, rel_path, parent_id, result, scope_prefix)

    def _extract_include(self, node: TSNode, content: bytes, rel_path: str, result: ParseResult) -> None:
        path_node = node.child_by_field_name("path")
        if path_node:
            inc_path = self.get_node_text(path_node, content).strip("\"'<>")
            is_rel = not (self.get_node_text(path_node, content).startswith("<"))
            result.raw_imports.append(
                RawImport(
                    file_path=rel_path,
                    source_module=inc_path,
                    line=node.start_point.row + 1,
                    is_relative=is_rel,
                )
            )

    def _extract_class_or_struct(
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

        name = self.get_node_text(name_node, content)
        qualified_name = f"{scope_prefix}{name}" if scope_prefix else name
        symbol_id = self.make_symbol_id(rel_path, qualified_name)

        is_struct = node.type == "struct_specifier"
        node_type = NodeType.STRUCT.value if is_struct else NodeType.CLASS.value

        spec_node = Node(
            id=symbol_id,
            type=node_type,
            name=name,
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            parent_id=parent_id,
            properties={"qualified_name": qualified_name},
        )
        result.nodes.append(spec_node)

        # Base classes in C++
        for ch in node.children:
            if ch.type == "base_class_clause":
                for sub in ch.children:
                    if sub.type == "type_identifier":
                        base_name = self.get_node_text(sub, content)
                        result.raw_inheritances.append(
                            RawInheritance(
                                class_id=symbol_id,
                                base_name=base_name,
                                line=ch.start_point.row + 1,
                                file_path=rel_path,
                                is_interface=False,
                            )
                        )

        body_node = node.child_by_field_name("body")
        if body_node:
            self._walk_node(
                body_node,
                content,
                rel_path,
                parent_id=symbol_id,
                result=result,
                scope_prefix=f"{qualified_name}::",
            )

    def _extract_function(
        self,
        node: TSNode,
        content: bytes,
        rel_path: str,
        parent_id: str,
        result: ParseResult,
        scope_prefix: str,
    ) -> None:
        declarator_node = node.child_by_field_name("declarator")
        if not declarator_node:
            return

        func_name = self._extract_declarator_name(declarator_node, content)
        if not func_name:
            return

        qualified_name = f"{scope_prefix}{func_name}" if scope_prefix else func_name
        func_id = self.make_symbol_id(rel_path, qualified_name)

        type_node = node.child_by_field_name("type")
        return_type = self.get_node_text(type_node, content) if type_node else None

        # Check if parent is a class or struct
        parent_is_class = any(n.id == parent_id and n.type in (NodeType.CLASS.value, NodeType.STRUCT.value) for n in result.nodes)
        node_type = NodeType.METHOD.value if parent_is_class or "::" in func_name else NodeType.FUNCTION.value

        func_node = Node(
            id=func_id,
            type=node_type,
            name=func_name.split("::")[-1],
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            return_type=return_type,
            parent_id=parent_id,
            properties={"qualified_name": qualified_name},
        )
        result.nodes.append(func_node)

        body_node = node.child_by_field_name("body")
        if body_node:
            self._walk_node(
                body_node,
                content,
                rel_path,
                parent_id=func_id,
                result=result,
                scope_prefix=f"{qualified_name}::",
            )

    def _extract_declarator_name(self, node: TSNode, content: bytes) -> str:
        if node.type in ("identifier", "type_identifier", "field_identifier", "qualified_identifier"):
            return self.get_node_text(node, content)
        decl = node.child_by_field_name("declarator")
        if decl:
            return self._extract_declarator_name(decl, content)
        for ch in node.children:
            if ch.type in ("identifier", "type_identifier", "field_identifier", "qualified_identifier"):
                return self.get_node_text(ch, content)
        return ""

    def _extract_call(
        self,
        node: TSNode,
        content: bytes,
        rel_path: str,
        caller_id: str,
        result: ParseResult,
    ) -> None:
        func_node = node.child_by_field_name("function")
        if not func_node:
            return

        called_text = self.get_node_text(func_node, content)
        receiver = None
        called_name = called_text

        if func_node.type == "field_expression":
            arg_node = func_node.child_by_field_name("argument")
            field_node = func_node.child_by_field_name("field")
            if field_node:
                called_name = self.get_node_text(field_node, content)
            if arg_node:
                receiver = self.get_node_text(arg_node, content)

        result.raw_calls.append(
            RawCall(
                caller_id=caller_id,
                called_name=called_name,
                receiver_name=receiver,
                line=node.start_point.row + 1,
                column=node.start_point.column + 1,
                file_path=rel_path,
            )
        )

        args_node = node.child_by_field_name("arguments")
        if args_node:
            for ch in args_node.children:
                if ch.type == "call_expression":
                    self._extract_call(ch, content, rel_path, caller_id, result)
