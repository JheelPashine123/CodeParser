"""Repository scanner for discovering supported source code files.

Handles .gitignore parsing, directory exclusions, safety checks, and relative path normalization.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path
from typing import List, Optional, Set, Tuple

from graphagent.language_registry import LanguageRegistry, default_registry

logger = logging.getLogger("graphagent.scanner")

DEFAULT_EXCLUDED_DIRS: Set[str] = {
    ".git",
    ".github",
    ".gitlab",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "ENV",
    ".conda",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "dist",
    "build",
    "target",
    "bin",
    "obj",
    "out",
    ".graphagent",
    ".idea",
    ".vscode",
    ".gradle",
    ".mvn",
    "vendor",
    "coverage",
    "htmlcov",
    ".next",
    ".nuxt",
    ".svelte-kit",
}

DEFAULT_EXCLUDED_FILE_PATTERNS: List[str] = [
    ".env",
    "*.env",
    ".env.*",
    "*.min.js",
    "*.min.css",
    "*.bundle.js",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    ".DS_Store",
    "Thumbs.db",
    "*.pem",
    "*.key",
    "*.pfx",
    "id_rsa",
    "id_ed25519",
]

MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB limit for source files


class Scanner:
    """Recursively scans a repository root and filters eligible source files."""

    def __init__(
        self,
        repo_root: str,
        registry: Optional[LanguageRegistry] = None,
        extra_excludes: Optional[List[str]] = None,
        respect_gitignore: bool = True,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.registry = registry or default_registry
        self.respect_gitignore = respect_gitignore

        self.excluded_dirs = set(DEFAULT_EXCLUDED_DIRS)
        self.excluded_patterns = list(DEFAULT_EXCLUDED_FILE_PATTERNS)

        if extra_excludes:
            for pat in extra_excludes:
                if pat:
                    self.excluded_patterns.append(pat)

        self.gitignore_patterns = self._load_gitignore() if respect_gitignore else []

    def _load_gitignore(self) -> List[str]:
        """Load and parse ignore rules from root .gitignore."""
        gitignore_file = self.repo_root / ".gitignore"
        patterns: List[str] = []
        if gitignore_file.is_file():
            try:
                for line in gitignore_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                    cleaned = line.strip()
                    if cleaned and not cleaned.startswith("#"):
                        patterns.append(cleaned)
            except Exception as exc:
                logger.warning("Could not read .gitignore: %s", exc)
        return patterns

    def is_ignored(self, rel_path: str, is_dir: bool = False) -> bool:
        """Check if relative path matches any exclusion rule or gitignore pattern."""
        norm_rel = rel_path.replace("\\", "/")
        parts = norm_rel.split("/")

        # Check directory names
        for part in parts[:-1] if not is_dir else parts:
            if part in self.excluded_dirs:
                return True

        filename = parts[-1]

        # Check default pattern exclusions
        for pat in self.excluded_patterns:
            if fnmatch.fnmatch(filename, pat) or fnmatch.fnmatch(norm_rel, pat):
                return True

        # Check gitignore rules
        for rule in self.gitignore_patterns:
            rule_clean = rule.rstrip("/")
            if fnmatch.fnmatch(norm_rel, rule_clean) or fnmatch.fnmatch(filename, rule_clean):
                return True
            # Match subpaths (e.g. `foo/bar`)
            if rule.endswith("/") and fnmatch.fnmatch(norm_rel + "/", f"*{rule}*"):
                return True

        return False

    def scan(self) -> Tuple[List[Tuple[Path, str, str]], List[str]]:
        """Scan directory and return list of (absolute_path, relative_path, language).

        Returns:
            Tuple[List[Tuple[Path, str, str]], List[str]]: (discovered_files, warnings)
        """
        discovered: List[Tuple[Path, str, str]] = []
        warnings: List[str] = []

        if not self.repo_root.is_dir():
            warnings.append(f"Repository root directory does not exist: {self.repo_root}")
            return discovered, warnings

        for root, dirs, files in os.walk(self.repo_root, topdown=True):
            # Prune excluded directories in-place
            dirs[:] = [
                d
                for d in dirs
                if d not in self.excluded_dirs
                and not self.is_ignored(
                    str(Path(root, d).relative_to(self.repo_root)), is_dir=True
                )
            ]

            for file_name in files:
                abs_path = Path(root, file_name)
                rel_path = str(abs_path.relative_to(self.repo_root)).replace("\\", "/")

                if self.is_ignored(rel_path, is_dir=False):
                    continue

                lang = self.registry.get_language_for_file(file_name)
                if not lang:
                    continue

                try:
                    size = abs_path.stat().st_size
                    if size > MAX_FILE_SIZE_BYTES:
                        warnings.append(f"Skipping large file ({size / 1024:.1f} KB): {rel_path}")
                        continue
                    if size == 0:
                        # Empty file
                        continue
                except OSError as exc:
                    warnings.append(f"Error accessing file {rel_path}: {exc}")
                    continue

                discovered.append((abs_path, rel_path, lang))

        # Sort files deterministically
        discovered.sort(key=lambda item: item[1])
        return discovered, warnings
