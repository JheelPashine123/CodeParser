"""PHP source code parser using Tree-sitter.

Extracts classes, interfaces, traits, functions, methods, use statements, inheritance, and calls.
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


class PHPParser(BaseParser):
    language_name = "php"

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

            if ntype == "namespace_use_declaration":
                self._extract_use(child, content, rel_path, result)

            elif ntype == "class_declaration":
                self._extract_class(child, content, rel_path, parent_id, result, scope_prefix)

            elif ntype == "interface_declaration":
                self._extract_interface(child, content, rel_path, parent_id, result, scope_prefix)

            elif ntype == "trait_declaration":
                self._extract_trait(child, content, rel_path, parent_id, result, scope_prefix)

            elif ntype == "function_definition":
                self._extract_function(child, content, rel_path, parent_id, result, scope_prefix)

            elif ntype == "method_declaration":
                self._extract_method(child, content, rel_path, parent_id, result, scope_prefix)

            elif ntype in ("function_call_expression", "member_call_expression", "scoped_call_expression"):
                self._extract_call(child, content, rel_path, caller_id=parent_id, result=result)

            else:
                if child.child_count > 0 and ntype not in ("class_declaration", "interface_declaration", "method_declaration"):
                    self._walk_node(child, content, rel_path, parent_id, result, scope_prefix)

    def _extract_use(self, node: TSNode, content: bytes, rel_path: str, result: ParseResult) -> None:
        use_text = self.get_node_text(node, content).replace("use", "").replace(";", "").strip()
        result.raw_imports.append(
            RawImport(
                file_path=rel_path,
                source_module=use_text,
                imported_symbols=[use_text.split("\\")[-1]],
                line=node.start_point.row + 1,
            )
        )

    def _extract_class(
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

        class_name = self.get_node_text(name_node, content)
        qualified_name = f"{scope_prefix}{class_name}" if scope_prefix else class_name
        class_id = self.make_symbol_id(rel_path, qualified_name)

        class_node = Node(
            id=class_id,
            type=NodeType.CLASS.value,
            name=class_name,
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            parent_id=parent_id,
            properties={"qualified_name": qualified_name},
        )
        result.nodes.append(class_node)

        # Inheritance (extends)
        base_clause = node.child_by_field_name("base_clause")
        if not base_clause:
            # Fallback search in children
            for ch in node.children:
                if ch.type == "base_clause":
                    base_clause = ch
                    break

        if base_clause:
            base_text = self.get_node_text(base_clause, content).replace("extends", "").strip()
            result.raw_inheritances.append(
                RawInheritance(
                    class_id=class_id,
                    base_name=base_text,
                    line=base_clause.start_point.row + 1,
                    file_path=rel_path,
                    is_interface=False,
                )
            )

        # Implements
        intf_clause = None
        for ch in node.children:
            if ch.type == "class_interface_clause":
                intf_clause = ch
                break

        if intf_clause:
            intf_text = self.get_node_text(intf_clause, content).replace("implements", "").strip()
            for intf in intf_text.split(","):
                i = intf.strip()
                if i:
                    result.raw_inheritances.append(
                        RawInheritance(
                            class_id=class_id,
                            base_name=i,
                            line=intf_clause.start_point.row + 1,
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
                parent_id=class_id,
                result=result,
                scope_prefix=f"{qualified_name}::",
            )

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
        intf_name = self.get_node_text(name_node, content)
        qualified_name = f"{scope_prefix}{intf_name}" if scope_prefix else intf_name
        intf_id = self.make_symbol_id(rel_path, qualified_name)

        intf_node = Node(
            id=intf_id,
            type=NodeType.INTERFACE.value,
            name=intf_name,
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            parent_id=parent_id,
            properties={"qualified_name": qualified_name},
        )
        result.nodes.append(intf_node)

        body_node = node.child_by_field_name("body")
        if body_node:
            self._walk_node(
                body_node,
                content,
                rel_path,
                parent_id=intf_id,
                result=result,
                scope_prefix=f"{qualified_name}::",
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
        trait_name = self.get_node_text(name_node, content)
        qualified_name = f"{scope_prefix}{trait_name}" if scope_prefix else trait_name
        trait_id = self.make_symbol_id(rel_path, qualified_name)

        result.nodes.append(
            Node(
                id=trait_id,
                type=NodeType.TRAIT.value,
                name=trait_name,
                file_path=rel_path,
                start_line=node.start_point.row + 1,
                end_line=node.end_point.row + 1,
                language=self.language_name,
                parent_id=parent_id,
                properties={"qualified_name": qualified_name},
            )
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

        params = self._extract_params(node, content)
        ret_node = node.child_by_field_name("return_type")
        ret_type = self.get_node_text(ret_node, content) if ret_node else None

        func_node = Node(
            id=func_id,
            type=NodeType.FUNCTION.value,
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

    def _extract_method(
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
        method_id = self.make_symbol_id(rel_path, qualified_name)

        params = self._extract_params(node, content)
        ret_node = node.child_by_field_name("return_type")
        ret_type = self.get_node_text(ret_node, content) if ret_node else None

        method_node = Node(
            id=method_id,
            type=NodeType.METHOD.value,
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
        result.nodes.append(method_node)

        body_node = node.child_by_field_name("body")
        if body_node:
            self._walk_node(
                body_node,
                content,
                rel_path,
                parent_id=method_id,
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
        receiver = None
        called_name = ""

        if node.type == "function_call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                called_name = self.get_node_text(func_node, content)
        elif node.type == "member_call_expression":
            obj_node = node.child_by_field_name("object")
            name_node = node.child_by_field_name("name")
            if name_node:
                called_name = self.get_node_text(name_node, content)
            if obj_node:
                receiver = self.get_node_text(obj_node, content)
        elif node.type == "scoped_call_expression":
            scope_node = node.child_by_field_name("scope")
            name_node = node.child_by_field_name("name")
            if name_node:
                called_name = self.get_node_text(name_node, content)
            if scope_node:
                receiver = self.get_node_text(scope_node, content)

        if called_name:
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
                if ch.type in ("function_call_expression", "member_call_expression", "scoped_call_expression"):
                    self._extract_call(ch, content, rel_path, caller_id, result)

    def _extract_params(self, node: TSNode, content: bytes) -> List[str]:
        params: List[str] = []
        params_node = node.child_by_field_name("parameters")
        if params_node:
            for p in params_node.children:
                if p.type in ("simple_parameter", "variadic_parameter"):
                    name_node = p.child_by_field_name("name")
                    if name_node:
                        params.append(self.get_node_text(name_node, content))
        return params
