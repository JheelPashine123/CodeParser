"""Python source code parser using Tree-sitter.

Extracts classes, functions, methods, imports, function calls, and inheritance.
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


class PythonParser(BaseParser):
    language_name = "python"

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
            node_type = child.type

            if node_type == "import_statement":
                self._extract_import(child, content, rel_path, result)

            elif node_type == "import_from_statement":
                self._extract_import_from(child, content, rel_path, result)

            elif node_type == "class_definition":
                self._extract_class(child, content, rel_path, parent_id, result, scope_prefix)

            elif node_type == "function_definition":
                self._extract_function(child, content, rel_path, parent_id, result, scope_prefix)

            elif node_type == "call":
                self._extract_call(child, content, rel_path, caller_id=parent_id, result=result)

            else:
                # Recurse down for nested calls or statements
                if child.child_count > 0 and node_type not in ("class_definition", "function_definition"):
                    self._walk_node(child, content, rel_path, parent_id, result, scope_prefix)

    def _extract_import(self, node: TSNode, content: bytes, rel_path: str, result: ParseResult) -> None:
        text = self.get_node_text(node, content)
        # e.g. import os, sys
        for ch in node.children:
            if ch.type == "dotted_name":
                mod_name = self.get_node_text(ch, content)
                result.raw_imports.append(
                    RawImport(
                        file_path=rel_path,
                        source_module=mod_name,
                        imported_symbols=[],
                        line=node.start_point.row + 1,
                    )
                )
            elif ch.type == "aliased_import":
                name_node = ch.child_by_field_name("name")
                alias_node = ch.child_by_field_name("alias")
                if name_node:
                    result.raw_imports.append(
                        RawImport(
                            file_path=rel_path,
                            source_module=self.get_node_text(name_node, content),
                            alias=self.get_node_text(alias_node, content) if alias_node else None,
                            line=node.start_point.row + 1,
                        )
                    )

    def _extract_import_from(self, node: TSNode, content: bytes, rel_path: str, result: ParseResult) -> None:
        module_name_node = node.child_by_field_name("module_name")
        module_name = self.get_node_text(module_name_node, content) if module_name_node else ""

        symbols: List[str] = []
        for ch in node.children:
            if ch.type == "dotted_name" and ch != module_name_node:
                symbols.append(self.get_node_text(ch, content))
            elif ch.type == "aliased_import":
                name_node = ch.child_by_field_name("name")
                if name_node:
                    symbols.append(self.get_node_text(name_node, content))

        is_rel = any(ch.type == "relative_import" for ch in node.children)
        result.raw_imports.append(
            RawImport(
                file_path=rel_path,
                source_module=module_name,
                imported_symbols=symbols,
                line=node.start_point.row + 1,
                is_relative=is_rel,
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

        docstring = self._extract_docstring(node, content)

        class_node = Node(
            id=class_id,
            type=NodeType.CLASS.value,
            name=class_name,
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            parent_id=parent_id,
            docstring=docstring,
            properties={"qualified_name": qualified_name},
        )
        result.nodes.append(class_node)

        # Inheritance
        superclasses_node = node.child_by_field_name("superclasses")
        if superclasses_node:
            for ch in superclasses_node.children:
                if ch.type in ("identifier", "attribute"):
                    base_name = self.get_node_text(ch, content)
                    result.raw_inheritances.append(
                        RawInheritance(
                            class_id=class_id,
                            base_name=base_name,
                            line=node.start_point.row + 1,
                            file_path=rel_path,
                            is_interface=False,
                        )
                    )

        # Walk class body
        body_node = node.child_by_field_name("body")
        if body_node:
            self._walk_node(
                body_node,
                content,
                rel_path,
                parent_id=class_id,
                result=result,
                scope_prefix=f"{qualified_name}.",
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

        func_name = self.get_node_text(name_node, content)
        qualified_name = f"{scope_prefix}{func_name}" if scope_prefix else func_name
        func_id = self.make_symbol_id(rel_path, qualified_name)

        is_method = "." in scope_prefix or parent_id.startswith("symbol:") and ":class" in parent_id
        # Check if parent is a class
        parent_is_class = any(n.id == parent_id and n.type == NodeType.CLASS.value for n in result.nodes)
        node_type = NodeType.METHOD.value if parent_is_class else NodeType.FUNCTION.value

        # Parameters
        params: List[str] = []
        params_node = node.child_by_field_name("parameters")
        if params_node:
            for p in params_node.children:
                if p.type in ("identifier", "typed_parameter", "default_parameter", "typed_default_parameter"):
                    p_text = self.get_node_text(p, content)
                    # Extract parameter name if typed
                    p_name = p_text.split(":")[0].split("=")[0].strip()
                    if p_name and p_name not in ("(", ")", ","):
                        params.append(p_name)

        # Return type
        return_type_node = node.child_by_field_name("return_type")
        return_type = self.get_node_text(return_type_node, content) if return_type_node else None

        docstring = self._extract_docstring(node, content)

        modifiers: List[str] = []
        if any(ch.type == "async" for ch in node.children):
            modifiers.append("async")

        func_node = Node(
            id=func_id,
            type=node_type,
            name=func_name,
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            parameters=params,
            return_type=return_type,
            parent_id=parent_id,
            docstring=docstring,
            modifiers=modifiers if modifiers else None,
            properties={"qualified_name": qualified_name},
        )
        result.nodes.append(func_node)

        # Walk body for nested calls and functions
        body_node = node.child_by_field_name("body")
        if body_node:
            self._walk_node(
                body_node,
                content,
                rel_path,
                parent_id=func_id,
                result=result,
                scope_prefix=f"{qualified_name}.",
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

        if func_node.type == "attribute":
            obj_node = func_node.child_by_field_name("object")
            attr_node = func_node.child_by_field_name("attribute")
            if attr_node:
                called_name = self.get_node_text(attr_node, content)
            if obj_node:
                receiver = self.get_node_text(obj_node, content)

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

        # Recurse into argument list in case calls are arguments (e.g. foo(bar()))
        args_node = node.child_by_field_name("arguments")
        if args_node:
            for ch in args_node.children:
                if ch.type == "call":
                    self._extract_call(ch, content, rel_path, caller_id, result)

    def _extract_docstring(self, node: TSNode, content: bytes) -> Optional[str]:
        body = node.child_by_field_name("body")
        if not body:
            return None
        for ch in body.children:
            if ch.type == "expression_statement":
                for sub in ch.children:
                    if sub.type == "string":
                        raw = self.get_node_text(sub, content)
                        return raw.strip("\"' \n\t")
            elif ch.type not in ("comment",):
                break
        return None
