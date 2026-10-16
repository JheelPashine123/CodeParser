"""Rust source code parser using Tree-sitter.

Extracts structs, enums, traits, functions, impl blocks (IMPLEMENTS relationships), and function calls.
"""

from __future__ import annotations

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


class RustParser(BaseParser):
    language_name = "rust"

    def __init__(self, language: Language) -> None:
        super().__init__(language)

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

            if ntype == "use_declaration":
                self._extract_use(child, content, rel_path, result)

            elif ntype == "struct_item":
                self._extract_struct(child, content, rel_path, parent_id, result, scope_prefix)

            elif ntype == "enum_item":
                self._extract_enum(child, content, rel_path, parent_id, result, scope_prefix)

            elif ntype == "trait_item":
                self._extract_trait(child, content, rel_path, parent_id, result, scope_prefix)

            elif ntype == "impl_item":
                self._extract_impl(child, content, rel_path, parent_id, result, scope_prefix)

            elif ntype == "function_item":
                self._extract_function(child, content, rel_path, parent_id, result, scope_prefix)

            elif ntype == "call_expression":
                self._extract_call(child, content, rel_path, caller_id=parent_id, result=result)

            else:
                if child.child_count > 0 and ntype not in ("struct_item", "enum_item", "trait_item", "impl_item", "function_item"):
                    self._walk_node(child, content, rel_path, parent_id, result, scope_prefix)

    def _extract_use(self, node: TSNode, content: bytes, rel_path: str, result: ParseResult) -> None:
        use_text = self.get_node_text(node, content).replace("use", "").replace(";", "").strip()
        result.raw_imports.append(
            RawImport(
                file_path=rel_path,
                source_module=use_text,
                line=node.start_point.row + 1,
            )
        )

    def _extract_struct(
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

        struct_node = Node(
            id=symbol_id,
            type=NodeType.STRUCT.value,
            name=name,
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            parent_id=parent_id,
            properties={"qualified_name": qualified_name},
        )
        result.nodes.append(struct_node)

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
        name = self.get_node_text(name_node, content)
        qualified_name = f"{scope_prefix}{name}" if scope_prefix else name
        symbol_id = self.make_symbol_id(rel_path, qualified_name)

        result.nodes.append(
            Node(
                id=symbol_id,
                type=NodeType.ENUM.value,
                name=name,
                file_path=rel_path,
                start_line=node.start_point.row + 1,
                end_line=node.end_point.row + 1,
                language=self.language_name,
                parent_id=parent_id,
                properties={"qualified_name": qualified_name},
            )
        )

    def _extract_trait(
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

        trait_node = Node(
            id=symbol_id,
            type=NodeType.TRAIT.value,
            name=name,
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            parent_id=parent_id,
            properties={"qualified_name": qualified_name},
        )
        result.nodes.append(trait_node)

        body_node = node.child_by_field_name("body")
        if body_node:
            self._walk_node(body_node, content, rel_path, parent_id=symbol_id, result=result, scope_prefix=f"{qualified_name}::")

    def _extract_impl(
        self,
        node: TSNode,
        content: bytes,
        rel_path: str,
        parent_id: str,
        result: ParseResult,
        scope_prefix: str,
    ) -> None:
        type_node = node.child_by_field_name("type")
        trait_node = node.child_by_field_name("trait")
        if not type_node:
            return

        type_name = self.get_node_text(type_node, content)
        struct_id = self.make_symbol_id(rel_path, type_name)

        # If impl Trait for Type, record implementation relationship
        if trait_node:
            trait_name = self.get_node_text(trait_node, content)
            result.raw_inheritances.append(
                RawInheritance(
                    class_id=struct_id,
                    base_name=trait_name,
                    line=node.start_point.row + 1,
                    file_path=rel_path,
                    is_interface=True,
                )
            )

        body_node = node.child_by_field_name("body")
        if body_node:
            self._walk_node(
                body_node,
                content,
                rel_path,
                parent_id=struct_id,
                result=result,
                scope_prefix=f"{type_name}::",
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
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        name = self.get_node_text(name_node, content)
        qualified_name = f"{scope_prefix}{name}" if scope_prefix else name
        func_id = self.make_symbol_id(rel_path, qualified_name)

        params: List[str] = []
        params_node = node.child_by_field_name("parameters")
        if params_node:
            for p in params_node.children:
                if p.type == "parameter":
                    p_name_node = p.child_by_field_name("pattern")
                    if p_name_node:
                        params.append(self.get_node_text(p_name_node, content))
                elif p.type == "self_parameter":
                    params.append("self")

        ret_node = node.child_by_field_name("return_type")
        ret_type = self.get_node_text(ret_node, content) if ret_node else None

        is_method = bool(scope_prefix)
        node_type = NodeType.METHOD.value if is_method else NodeType.FUNCTION.value

        func_node = Node(
            id=func_id,
            type=node_type,
            name=name,
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            parameters=params,
            return_type=ret_type,
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
            val_node = func_node.child_by_field_name("value")
            field_node = func_node.child_by_field_name("field")
            if field_node:
                called_name = self.get_node_text(field_node, content)
            if val_node:
                receiver = self.get_node_text(val_node, content)
        elif func_node.type == "scoped_identifier":
            path_node = func_node.child_by_field_name("path")
            name_node = func_node.child_by_field_name("name")
            if name_node:
                called_name = self.get_node_text(name_node, content)
            if path_node:
                receiver = self.get_node_text(path_node, content)

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
