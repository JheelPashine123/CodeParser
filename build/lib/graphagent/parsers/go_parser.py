"""Go source code parser using Tree-sitter.

Extracts structs, interfaces, functions, receiver methods, package imports, and function calls.
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
)
from graphagent.parsers.base import BaseParser


class GoParser(BaseParser):
    language_name = "go"

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
    ) -> None:
        for child in node.children:
            ntype = child.type

            if ntype == "import_declaration":
                self._extract_import(child, content, rel_path, result)

            elif ntype == "type_declaration":
                self._extract_type_decl(child, content, rel_path, parent_id, result)

            elif ntype == "function_declaration":
                self._extract_function(child, content, rel_path, parent_id, result)

            elif ntype == "method_declaration":
                self._extract_method(child, content, rel_path, parent_id, result)

            elif ntype == "call_expression":
                self._extract_call(child, content, rel_path, caller_id=parent_id, result=result)

            else:
                if child.child_count > 0 and ntype not in ("function_declaration", "method_declaration"):
                    self._walk_node(child, content, rel_path, parent_id, result)

    def _extract_import(self, node: TSNode, content: bytes, rel_path: str, result: ParseResult) -> None:
        for ch in node.children:
            if ch.type == "import_spec":
                path_node = ch.child_by_field_name("path")
                if path_node:
                    imp_path = self.get_node_text(path_node, content).strip("\"'")
                    alias_node = ch.child_by_field_name("name")
                    alias = self.get_node_text(alias_node, content) if alias_node else None
                    result.raw_imports.append(
                        RawImport(
                            file_path=rel_path,
                            source_module=imp_path,
                            alias=alias,
                            line=ch.start_point.row + 1,
                        )
                    )
            elif ch.type == "import_spec_list":
                for spec in ch.children:
                    if spec.type == "import_spec":
                        path_node = spec.child_by_field_name("path")
                        if path_node:
                            imp_path = self.get_node_text(path_node, content).strip("\"'")
                            alias_node = spec.child_by_field_name("name")
                            alias = self.get_node_text(alias_node, content) if alias_node else None
                            result.raw_imports.append(
                                RawImport(
                                    file_path=rel_path,
                                    source_module=imp_path,
                                    alias=alias,
                                    line=spec.start_point.row + 1,
                                )
                            )

    def _extract_type_decl(
        self,
        node: TSNode,
        content: bytes,
        rel_path: str,
        parent_id: str,
        result: ParseResult,
    ) -> None:
        for spec in node.children:
            if spec.type == "type_spec":
                name_node = spec.child_by_field_name("name")
                type_node = spec.child_by_field_name("type")
                if not name_node:
                    continue

                type_name = self.get_node_text(name_node, content)
                type_kind = type_node.type if type_node else "type"

                if type_kind == "struct_type":
                    node_type = NodeType.STRUCT.value
                elif type_kind == "interface_type":
                    node_type = NodeType.INTERFACE.value
                else:
                    node_type = "type"

                type_id = self.make_symbol_id(rel_path, type_name)
                result.nodes.append(
                    Node(
                        id=type_id,
                        type=node_type,
                        name=type_name,
                        file_path=rel_path,
                        start_line=spec.start_point.row + 1,
                        end_line=spec.end_point.row + 1,
                        language=self.language_name,
                        parent_id=parent_id,
                        properties={"qualified_name": type_name, "kind": type_kind},
                    )
                )

    def _extract_function(
        self,
        node: TSNode,
        content: bytes,
        rel_path: str,
        parent_id: str,
        result: ParseResult,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        func_name = self.get_node_text(name_node, content)
        func_id = self.make_symbol_id(rel_path, func_name)

        params = self._extract_params(node, content)
        ret_node = node.child_by_field_name("result")
        ret_type = self.get_node_text(ret_node, content) if ret_node else None

        func_node = Node(
            id=func_id,
            type=NodeType.FUNCTION.value,
            name=func_name,
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            parameters=params,
            return_type=ret_type,
            parent_id=parent_id,
            properties={"qualified_name": func_name},
        )
        result.nodes.append(func_node)

        body_node = node.child_by_field_name("body")
        if body_node:
            self._walk_node(body_node, content, rel_path, parent_id=func_id, result=result)

    def _extract_method(
        self,
        node: TSNode,
        content: bytes,
        rel_path: str,
        parent_id: str,
        result: ParseResult,
    ) -> None:
        name_node = node.child_by_field_name("name")
        receiver_node = node.child_by_field_name("receiver")
        if not name_node:
            return

        method_name = self.get_node_text(name_node, content)

        # Extract receiver type name (e.g., from (u *User) -> User)
        receiver_type = ""
        if receiver_node:
            rec_text = self.get_node_text(receiver_node, content)
            # Find words like *User or User
            match = re.search(r"\*?([A-Za-z0-9_]+)\s*\)$", rec_text)
            if match:
                receiver_type = match.group(1)

        qualified_name = f"{receiver_type}.{method_name}" if receiver_type else method_name
        method_id = self.make_symbol_id(rel_path, qualified_name)

        # Find parent struct if in same file
        actual_parent = parent_id
        if receiver_type:
            for n in result.nodes:
                if n.name == receiver_type and n.file_path == rel_path and n.type in (NodeType.STRUCT.value, NodeType.CLASS.value):
                    actual_parent = n.id
                    break

        params = self._extract_params(node, content)
        ret_node = node.child_by_field_name("result")
        ret_type = self.get_node_text(ret_node, content) if ret_node else None

        method_node = Node(
            id=method_id,
            type=NodeType.METHOD.value,
            name=method_name,
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            parameters=params,
            return_type=ret_type,
            parent_id=actual_parent,
            properties={"qualified_name": qualified_name, "receiver": receiver_type},
        )
        result.nodes.append(method_node)

        body_node = node.child_by_field_name("body")
        if body_node:
            self._walk_node(body_node, content, rel_path, parent_id=method_id, result=result)

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

        if func_node.type == "selector_expression":
            operand_node = func_node.child_by_field_name("operand")
            field_node = func_node.child_by_field_name("field")
            if field_node:
                called_name = self.get_node_text(field_node, content)
            if operand_node:
                receiver = self.get_node_text(operand_node, content)

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

    def _extract_params(self, node: TSNode, content: bytes) -> List[str]:
        params: List[str] = []
        params_node = node.child_by_field_name("parameters")
        if params_node:
            for p in params_node.children:
                if p.type == "parameter_declaration":
                    name_node = p.child_by_field_name("name")
                    if name_node:
                        params.append(self.get_node_text(name_node, content))
        return params
