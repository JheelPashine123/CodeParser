"""Java source code parser using Tree-sitter.

Extracts classes, interfaces, enums, methods, constructors, imports, inheritance, and method calls.
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


class JavaParser(BaseParser):
    language_name = "java"

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

            if ntype == "import_declaration":
                self._extract_import(child, content, rel_path, result)

            elif ntype == "class_declaration":
                self._extract_class(child, content, rel_path, parent_id, result, scope_prefix)

            elif ntype == "interface_declaration":
                self._extract_interface(child, content, rel_path, parent_id, result, scope_prefix)

            elif ntype == "enum_declaration":
                self._extract_enum(child, content, rel_path, parent_id, result, scope_prefix)

            elif ntype in ("method_declaration", "constructor_declaration"):
                self._extract_method(child, content, rel_path, parent_id, result, scope_prefix)

            elif ntype == "method_invocation":
                self._extract_call(child, content, rel_path, caller_id=parent_id, result=result)

            else:
                if child.child_count > 0 and ntype not in ("class_declaration", "interface_declaration", "method_declaration"):
                    self._walk_node(child, content, rel_path, parent_id, result, scope_prefix)

    def _extract_import(self, node: TSNode, content: bytes, rel_path: str, result: ParseResult) -> None:
        text = self.get_node_text(node, content)
        # e.g. import java.util.List;
        import_path = text.replace("import", "").replace("static", "").replace(";", "").strip()
        result.raw_imports.append(
            RawImport(
                file_path=rel_path,
                source_module=import_path,
                imported_symbols=[import_path.split(".")[-1]],
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

        modifiers = self._extract_modifiers(node, content)

        class_node = Node(
            id=class_id,
            type=NodeType.CLASS.value,
            name=class_name,
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            parent_id=parent_id,
            modifiers=modifiers if modifiers else None,
            properties={"qualified_name": qualified_name},
        )
        result.nodes.append(class_node)

        # Superclass (extends)
        superclass_node = node.child_by_field_name("superclass")
        if superclass_node:
            base_text = self.get_node_text(superclass_node, content).replace("extends", "").strip()
            for base in base_text.split(","):
                b = base.strip()
                if b:
                    result.raw_inheritances.append(
                        RawInheritance(
                            class_id=class_id,
                            base_name=b,
                            line=node.start_point.row + 1,
                            file_path=rel_path,
                            is_interface=False,
                        )
                    )

        # Interfaces (implements)
        interfaces_node = node.child_by_field_name("interfaces")
        if interfaces_node:
            intf_text = self.get_node_text(interfaces_node, content).replace("implements", "").strip()
            for intf in intf_text.split(","):
                i = intf.strip()
                if i:
                    result.raw_inheritances.append(
                        RawInheritance(
                            class_id=class_id,
                            base_name=i,
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
                parent_id=class_id,
                result=result,
                scope_prefix=f"{qualified_name}.",
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
                scope_prefix=f"{qualified_name}.",
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

        result.nodes.append(
            Node(
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

        method_name = self.get_node_text(name_node, content)
        qualified_name = f"{scope_prefix}{method_name}" if scope_prefix else method_name
        method_id = self.make_symbol_id(rel_path, qualified_name)

        params: List[str] = []
        params_node = node.child_by_field_name("parameters")
        if params_node:
            for p in params_node.children:
                if p.type == "formal_parameter":
                    p_name_node = p.child_by_field_name("name")
                    if p_name_node:
                        params.append(self.get_node_text(p_name_node, content))

        type_node = node.child_by_field_name("type")
        return_type = self.get_node_text(type_node, content) if type_node else None

        modifiers = self._extract_modifiers(node, content)

        method_node = Node(
            id=method_id,
            type=NodeType.METHOD.value,
            name=method_name,
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            parameters=params,
            return_type=return_type,
            parent_id=parent_id,
            modifiers=modifiers if modifiers else None,
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
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        called_name = self.get_node_text(name_node, content)
        receiver = None
        obj_node = node.child_by_field_name("object")
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

        args_node = node.child_by_field_name("arguments")
        if args_node:
            for ch in args_node.children:
                if ch.type == "method_invocation":
                    self._extract_call(ch, content, rel_path, caller_id, result)

    def _extract_modifiers(self, node: TSNode, content: bytes) -> List[str]:
        mods: List[str] = []
        for ch in node.children:
            if ch.type == "modifiers":
                for m in ch.children:
                    mods.append(self.get_node_text(m, content))
        return mods
