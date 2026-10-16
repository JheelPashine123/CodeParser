"""Modular Language Registry for Tree-sitter parsers in GraphAgent."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from tree_sitter import Language

from graphagent.parsers.base import BaseParser
from graphagent.parsers.c_cpp_parser import CCppParser
from graphagent.parsers.go_parser import GoParser
from graphagent.parsers.java_parser import JavaParser
from graphagent.parsers.javascript_parser import JavaScriptParser
from graphagent.parsers.php_parser import PHPParser
from graphagent.parsers.python_parser import PythonParser
from graphagent.parsers.rust_parser import RustParser
from graphagent.parsers.typescript_parser import TypeScriptParser

logger = logging.getLogger("graphagent.registry")


class LanguageRegistry:
    """Registry managing language detection, Tree-sitter grammars, and parser instances."""

    def __init__(self) -> None:
        self._extension_map: Dict[str, str] = {}
        self._parser_factories: Dict[str, Callable[[], BaseParser]] = {}
        self._parser_cache: Dict[str, BaseParser] = {}
        self._register_default_languages()

    def _register_default_languages(self) -> None:
        """Register the 8 default languages + TSX using their Tree-sitter grammars."""

        # 1. Python
        def make_python() -> BaseParser:
            import tree_sitter_python
            lang = Language(tree_sitter_python.language())
            return PythonParser(lang)

        self.register_language("python", [".py", ".pyi"], make_python)

        # 2. JavaScript
        def make_javascript() -> BaseParser:
            import tree_sitter_javascript
            lang = Language(tree_sitter_javascript.language())
            return JavaScriptParser(lang)

        self.register_language("javascript", [".js", ".mjs", ".cjs", ".jsx"], make_javascript)

        # 3. TypeScript
        def make_typescript() -> BaseParser:
            import tree_sitter_typescript
            lang = Language(tree_sitter_typescript.language_typescript())
            return TypeScriptParser(lang, is_tsx=False)

        self.register_language("typescript", [".ts", ".mts", ".cts"], make_typescript)

        # 3b. TSX
        def make_tsx() -> BaseParser:
            import tree_sitter_typescript
            lang = Language(tree_sitter_typescript.language_tsx())
            return TypeScriptParser(lang, is_tsx=True)

        self.register_language("tsx", [".tsx"], make_tsx)

        # 4. Java
        def make_java() -> BaseParser:
            import tree_sitter_java
            lang = Language(tree_sitter_java.language())
            return JavaParser(lang)

        self.register_language("java", [".java"], make_java)

        # 5. Go
        def make_go() -> BaseParser:
            import tree_sitter_go
            lang = Language(tree_sitter_go.language())
            return GoParser(lang)

        self.register_language("go", [".go"], make_go)

        # 6a. C
        def make_c() -> BaseParser:
            import tree_sitter_c
            lang = Language(tree_sitter_c.language())
            return CCppParser(lang, is_c=True)

        self.register_language("c", [".c", ".h"], make_c)

        # 6b. C++
        def make_cpp() -> BaseParser:
            import tree_sitter_cpp
            lang = Language(tree_sitter_cpp.language())
            return CCppParser(lang, is_c=False)

        self.register_language("cpp", [".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"], make_cpp)

        # 7. Rust
        def make_rust() -> BaseParser:
            import tree_sitter_rust
            lang = Language(tree_sitter_rust.language())
            return RustParser(lang)

        self.register_language("rust", [".rs"], make_rust)

        # 8. PHP
        def make_php() -> BaseParser:
            import tree_sitter_php
            lang = Language(tree_sitter_php.language_php())
            return PHPParser(lang)

        self.register_language("php", [".php", ".phtml", ".php3", ".php4", ".php5"], make_php)

    def register_language(
        self,
        language_name: str,
        extensions: List[str],
        factory: Callable[[], BaseParser],
    ) -> None:
        """Register a new language or file extensions with a parser factory."""
        self._parser_factories[language_name] = factory
        for ext in extensions:
            normalized_ext = ext.lower().strip()
            if not normalized_ext.startswith("."):
                normalized_ext = f".{normalized_ext}"
            self._extension_map[normalized_ext] = language_name

    def get_language_for_file(self, file_path: str) -> Optional[str]:
        """Detect language name based on file extension."""
        suffix = Path(file_path).suffix.lower()
        return self._extension_map.get(suffix)

    def get_parser_for_file(self, file_path: str) -> Optional[BaseParser]:
        """Retrieve or lazily instantiate parser for the given file."""
        lang_name = self.get_language_for_file(file_path)
        if not lang_name:
            return None
        return self.get_parser_for_language(lang_name)

    def get_parser_for_language(self, language_name: str) -> Optional[BaseParser]:
        """Retrieve or lazily instantiate parser for a language name."""
        if language_name in self._parser_cache:
            return self._parser_cache[language_name]

        factory = self._parser_factories.get(language_name)
        if not factory:
            return None

        try:
            parser_instance = factory()
            self._parser_cache[language_name] = parser_instance
            return parser_instance
        except Exception as exc:
            logger.error("Failed to initialize parser for '%s': %s", language_name, exc)
            return None

    def get_supported_extensions(self) -> Set[str]:
        """Return all supported file extensions."""
        return set(self._extension_map.keys())

    def get_supported_languages(self) -> List[str]:
        """Return sorted list of supported language names."""
        return sorted(list(self._parser_factories.keys()))


# Global default registry instance
default_registry = LanguageRegistry()
