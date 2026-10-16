"""JavaScript source code parser using Tree-sitter."""

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


class JavaScriptParser(BaseParser):
    language_name = "javascript"

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
            self._process_node(child, content, rel_path, parent_id, result, scope_prefix)

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

        if ntype == "import_statement":
            self._extract_import(node, content, rel_path, result)

        elif ntype == "class_declaration":
            self._extract_class(node, content, rel_path, parent_id, result, scope_prefix)

        elif ntype in ("function_declaration", "generator_function_declaration"):
            self._extract_function(node, content, rel_path, parent_id, result, scope_prefix)

        elif ntype == "method_definition":
            self._extract_method(node, content, rel_path, parent_id, result, scope_prefix)

        elif ntype in ("lexical_declaration", "variable_declaration"):
            self._extract_variable_or_arrow_func(node, content, rel_path, parent_id, result, scope_prefix)

        elif ntype == "call_expression":
            self._extract_call(node, content, rel_path, caller_id=parent_id, result=result)

        elif ntype == "export_statement":
            # Recurse inside export statement children
            self._walk_node(node, content, rel_path, parent_id, result, scope_prefix)

        else:
            if node.child_count > 0 and ntype not in ("class_declaration", "function_declaration", "method_definition"):
                self._walk_node(node, content, rel_path, parent_id, result, scope_prefix)

    def _extract_import(self, node: TSNode, content: bytes, rel_path: str, result: ParseResult) -> None:
        source_node = node.child_by_field_name("source")
        source_module = self.get_node_text(source_node, content).strip("\"'") if source_node else ""

        symbols: List[str] = []
        clause = node.child_by_field_name("import_clause") or node.child_by_field_name("clause")
        if clause:
            for ch in clause.children:
                if ch.type in ("identifier", "type_identifier"):
                    symbols.append(self.get_node_text(ch, content))
                elif ch.type == "named_imports":
                    for spec in ch.children:
                        if spec.type == "import_specifier":
                            name_node = spec.child_by_field_name("name")
                            if name_node:
                                symbols.append(self.get_node_text(name_node, content))

        is_rel = source_module.startswith(".")
        result.raw_imports.append(
            RawImport(
                file_path=rel_path,
                source_module=source_module,
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

        # Heritage (extends / implements)
        for ch in node.children:
            if ch.type == "class_heritage":
                for h_ch in ch.children:
                    if h_ch.type == "extends_clause":
                        for sub in h_ch.children:
                            if sub.type in ("identifier", "type_identifier", "member_expression"):
                                base_name = self.get_node_text(sub, content)
                                if base_name and base_name != "extends":
                                    result.raw_inheritances.append(
                                        RawInheritance(
                                            class_id=class_id,
                                            base_name=base_name,
                                            line=h_ch.start_point.row + 1,
                                            file_path=rel_path,
                                            is_interface=False,
                                        )
                                    )
                    elif h_ch.type == "implements_clause":
                        for sub in h_ch.children:
                            if sub.type in ("identifier", "type_identifier"):
                                base_name = self.get_node_text(sub, content)
                                if base_name and base_name != "implements":
                                    result.raw_inheritances.append(
                                        RawInheritance(
                                            class_id=class_id,
                                            base_name=base_name,
                                            line=h_ch.start_point.row + 1,
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
        func_name = self.get_node_text(name_node, content) if name_node else "anonymous"
        qualified_name = f"{scope_prefix}{func_name}" if scope_prefix else func_name
        func_id = self.make_symbol_id(rel_path, qualified_name)

        params = self._extract_parameters(node, content)

        func_node = Node(
            id=func_id,
            type=NodeType.FUNCTION.value,
            name=func_name,
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            parameters=params,
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
                scope_prefix=f"{qualified_name}.",
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

        params = self._extract_parameters(node, content)

        method_node = Node(
            id=method_id,
            type=NodeType.METHOD.value,
            name=method_name,
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            language=self.language_name,
            parameters=params,
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
                scope_prefix=f"{qualified_name}.",
            )

    def _extract_variable_or_arrow_func(
        self,
        node: TSNode,
        content: bytes,
        rel_path: str,
        parent_id: str,
        result: ParseResult,
        scope_prefix: str,
    ) -> None:
        for decl in node.children:
            if decl.type == "variable_declarator":
                name_node = decl.child_by_field_name("name")
                value_node = decl.child_by_field_name("value")
                if not name_node:
                    continue

                var_name = self.get_node_text(name_node, content)
                qualified_name = f"{scope_prefix}{var_name}" if scope_prefix else var_name

                if value_node and value_node.type in ("arrow_function", "function_expression"):
                    func_id = self.make_symbol_id(rel_path, qualified_name)
                    params = self._extract_parameters(value_node, content)
                    func_node = Node(
                        id=func_id,
                        type=NodeType.FUNCTION.value,
                        name=var_name,
                        file_path=rel_path,
                        start_line=decl.start_point.row + 1,
                        end_line=decl.end_point.row + 1,
                        language=self.language_name,
                        parameters=params,
                        parent_id=parent_id,
                        properties={"qualified_name": qualified_name, "is_arrow": True},
                    )
                    result.nodes.append(func_node)

                    body = value_node.child_by_field_name("body")
                    if body:
                        self._walk_node(
                            body,
                            content,
                            rel_path,
                            parent_id=func_id,
                            result=result,
                            scope_prefix=f"{qualified_name}.",
                        )
                else:
                    # Capture top-level constant or variable
                    var_id = self.make_symbol_id(rel_path, qualified_name)
                    is_const = "const" in self.get_node_text(node, content)[:6]
                    node_type = NodeType.CONSTANT.value if is_const else NodeType.VARIABLE.value
                    var_node = Node(
                        id=var_id,
                        type=node_type,
                        name=var_name,
                        file_path=rel_path,
                        start_line=decl.start_point.row + 1,
                        end_line=decl.end_point.row + 1,
                        language=self.language_name,
                        parent_id=parent_id,
                    )
                    result.nodes.append(var_node)

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

        if func_node.type == "member_expression":
            obj_node = func_node.child_by_field_name("object")
            prop_node = func_node.child_by_field_name("property")
            if prop_node:
                called_name = self.get_node_text(prop_node, content)
            if obj_node:
                receiver = self.get_node_text(obj_node, content)

        # Detect CommonJS require("module")
        if called_name == "require":
            args_node = node.child_by_field_name("arguments")
            if args_node and args_node.child_count > 1:
                arg_text = self.get_node_text(args_node.children[1], content).strip("\"'")
                if arg_text:
                    result.raw_imports.append(
                        RawImport(
                            file_path=rel_path,
                            source_module=arg_text,
                            imported_symbols=[],
                            line=node.start_point.row + 1,
                            is_relative=arg_text.startswith("."),
                        )
                    )
            return

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

    def _extract_parameters(self, node: TSNode, content: bytes) -> List[str]:
        params: List[str] = []
        params_node = node.child_by_field_name("parameters")
        if not params_node:
            # For arrow functions, parameter might be single identifier
            single_param = node.child_by_field_name("parameter")
            if single_param:
                p_text = self.get_node_text(single_param, content)
                return [p_text] if p_text else []
            return []

        for p in params_node.children:
            if p.type in ("identifier", "required_parameter", "optional_parameter"):
                p_name = self.get_node_text(p, content).split(":")[0].split("=")[0].strip()
                if p_name and p_name not in ("(", ")", ","):
                    params.append(p_name)
        return params
