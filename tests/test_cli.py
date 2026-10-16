"""Integration tests for the graphagent CLI."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from graphagent.cli import run_parse

SAMPLE_REPO_DIR = Path(__file__).resolve().parent / "sample_repo"


def test_cli_parse_sample_repo():
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_out = Path(tmpdir) / "output_graph.json"

        exit_code = run_parse(
            repo_path=str(SAMPLE_REPO_DIR),
            output_path=str(custom_out),
            verbose=False,
        )
        assert exit_code == 0
        assert custom_out.is_file()

        data = json.loads(custom_out.read_text(encoding="utf-8"))
        assert data["schema_version"] == "1.0"
        assert "repository" in data
        assert "metadata" in data
        assert "nodes" in data
        assert "edges" in data
        assert "summary" in data

        summary = data["summary"]
        assert summary["files_scanned"] >= 8
        assert summary["files_parsed"] >= 8
        assert summary["nodes_count"] > 20
        assert summary["edges_count"] > 20
        assert summary["errors_count"] == 0

        # Verify edge structure
        for edge in data["edges"]:
            assert "id" in edge
            assert "source" in edge
            assert "target" in edge
            assert "type" in edge
            assert "resolution" in edge


def test_cli_invalid_path():
    exit_code = run_parse(repo_path="/non_existent_directory_abc_xyz_123")
    assert exit_code == 1


def test_cli_deterministic_output_and_referential_integrity():
    with tempfile.TemporaryDirectory() as tmpdir:
        out1 = Path(tmpdir) / "run1.json"
        out2 = Path(tmpdir) / "run2.json"

        code1 = run_parse(repo_path=str(SAMPLE_REPO_DIR), output_path=str(out1), verbose=False)
        code2 = run_parse(repo_path=str(SAMPLE_REPO_DIR), output_path=str(out2), verbose=False)

        assert code1 == 0 and code2 == 0

        data1 = json.loads(out1.read_text(encoding="utf-8"))
        data2 = json.loads(out2.read_text(encoding="utf-8"))

        # Check unique node IDs
        node_ids = [n["id"] for n in data1["nodes"]]
        assert len(node_ids) == len(set(node_ids)), "Duplicate node IDs detected"

        # Check unique edge IDs
        edge_ids = [e["id"] for e in data1["edges"]]
        assert len(edge_ids) == len(set(edge_ids)), "Duplicate edge IDs detected"

        # Check referential integrity for resolved containment, inheritance, and resolved calls
        node_id_set = set(node_ids)
        for edge in data1["edges"]:
            assert edge["source"] in node_id_set, f"Edge source {edge['source']} does not exist in nodes"
            if edge["resolution"] == "resolved":
                assert edge["target"] in node_id_set, f"Resolved edge target {edge['target']} does not exist in nodes"

        # Verify idempotence (ignoring generated_at timestamp)
        data1["metadata"]["generated_at"] = ""
        data2["metadata"]["generated_at"] = ""
        assert data1 == data2, "Repeated parsing generated non-deterministic output"
