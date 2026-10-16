"""Unit tests for repository scanner and safety exclusions."""

from __future__ import annotations

import tempfile
from pathlib import Path

from graphagent.scanner import Scanner


def test_scanner_discovers_supported_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "app.py").write_text("def hello(): pass")
        (root / "index.js").write_text("console.log('hi');")
        (root / "main.go").write_text("package main")
        (root / "readme.txt").write_text("ignored file")

        scanner = Scanner(str(root))
        files, warnings = scanner.scan()

        rel_paths = [rel for _, rel, _ in files]
        assert "app.py" in rel_paths
        assert "index.js" in rel_paths
        assert "main.go" in rel_paths
        assert "readme.txt" not in rel_paths


def test_scanner_excludes_default_ignored_directories():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Normal file
        (root / "main.py").write_text("pass")

        # Excluded directories
        git_dir = root / ".git"
        git_dir.mkdir()
        (git_dir / "hook.py").write_text("pass")

        node_dir = root / "node_modules" / "pkg"
        node_dir.mkdir(parents=True)
        (node_dir / "index.js").write_text("pass")

        venv_dir = root / ".venv" / "lib"
        venv_dir.mkdir(parents=True)
        (venv_dir / "lib.py").write_text("pass")

        scanner = Scanner(str(root))
        files, _ = scanner.scan()

        rel_paths = [rel for _, rel, _ in files]
        assert "main.py" in rel_paths
        assert not any(p.startswith(".git") for p in rel_paths)
        assert not any(p.startswith("node_modules") for p in rel_paths)
        assert not any(p.startswith(".venv") for p in rel_paths)


def test_scanner_respects_gitignore():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / ".gitignore").write_text("secret_code.py\nignored_dir/\n")
        (root / "public.py").write_text("pass")
        (root / "secret_code.py").write_text("pass")

        ign_dir = root / "ignored_dir"
        ign_dir.mkdir()
        (ign_dir / "hidden.py").write_text("pass")

        scanner = Scanner(str(root))
        files, _ = scanner.scan()

        rel_paths = [rel for _, rel, _ in files]
        assert "public.py" in rel_paths
        assert "secret_code.py" not in rel_paths
        assert "ignored_dir/hidden.py" not in rel_paths
