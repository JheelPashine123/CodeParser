"""Symbol extractor coordinator for multi-file repository analysis."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

from graphagent.language_registry import LanguageRegistry, default_registry
from graphagent.models import ParseResult

logger = logging.getLogger("graphagent.extractor")


class SymbolExtractor:
    """Coordinates parsing across all discovered source files using LanguageRegistry."""

    def __init__(self, registry: Optional[LanguageRegistry] = None) -> None:
        self.registry = registry or default_registry

    def extract_file(self, abs_path: Path, rel_path: str, language: str) -> ParseResult:
        """Read and parse a single file with safe error containment."""
        parser = self.registry.get_parser_for_language(language)
        if not parser:
            return ParseResult(
                file_path=rel_path,
                language=language,
                success=False,
                error=f"No parser available for language: {language}",
            )

        try:
            content = abs_path.read_bytes()
            # Fast binary file detection
            if b"\x00" in content[:1024]:
                return ParseResult(
                    file_path=rel_path,
                    language=language,
                    success=False,
                    error="Binary content detected, skipped.",
                )

            return parser.parse(str(abs_path), content, rel_path)
        except Exception as exc:
            logger.warning("Error parsing %s: %s", rel_path, exc)
            return ParseResult(
                file_path=rel_path,
                language=language,
                success=False,
                error=str(exc),
            )

    def extract_all(
        self, discovered_files: List[Tuple[Path, str, str]]
    ) -> Tuple[List[ParseResult], List[str]]:
        """Extract symbols and relationships across all discovered files.

        Returns:
            Tuple[List[ParseResult], List[str]]: (results, errors_and_warnings)
        """
        results: List[ParseResult] = []
        messages: List[str] = []

        for abs_path, rel_path, language in discovered_files:
            res = self.extract_file(abs_path, rel_path, language)
            results.append(res)
            if not res.success:
                messages.append(f"Failed to parse {rel_path}: {res.error}")
            elif res.warnings:
                messages.extend(res.warnings)

        return results, messages
