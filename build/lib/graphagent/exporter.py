"""JSON exporter for GraphAgent graph representation."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from graphagent.models import (
    Edge,
    GraphData,
    MetadataInfo,
    Node,
    RepositoryInfo,
    SummaryInfo,
)

logger = logging.getLogger("graphagent.exporter")

PARSER_VERSION = "0.1.0"
DEFAULT_OUTPUT_DIR = ".graphagent"
DEFAULT_OUTPUT_FILENAME = "graph_data.json"


class Exporter:
    """Exports structured graph entities and relationships to disk as JSON."""

    def __init__(
        self,
        repo_root: Path,
        nodes: List[Node],
        edges: List[Edge],
        summary: SummaryInfo,
        languages: List[str],
        warnings: Optional[List[str]] = None,
    ) -> None:
        self.repo_root = repo_root
        self.nodes = nodes
        self.edges = edges
        self.summary = summary
        self.languages = sorted(languages)
        self.warnings = warnings or []

    def build_graph_data(self) -> GraphData:
        """Construct the complete GraphData model."""
        repo_name = self.repo_root.name or "repository"
        repo_info = RepositoryInfo(root=".", name=repo_name)

        meta_info = MetadataInfo(
            parser_version=PARSER_VERSION,
            generated_at=datetime.now(timezone.utc).isoformat(),
            languages=self.languages,
        )

        return GraphData(
            schema_version="1.0",
            repository=repo_info,
            metadata=meta_info,
            nodes=self.nodes,
            edges=self.edges,
            summary=self.summary,
            warnings=self.warnings,
        )

    def export(self, output_path: Optional[str] = None) -> Path:
        """Write graph JSON to disk.

        Args:
            output_path: Optional custom file path. If None, defaults to `.graphagent/graph_data.json`.

        Returns:
            Path: The resolved path of the created JSON file.
        """
        if output_path:
            target_file = Path(output_path).resolve()
        else:
            out_dir = self.repo_root / DEFAULT_OUTPUT_DIR
            target_file = out_dir / DEFAULT_OUTPUT_FILENAME

        import os
        os.makedirs(str(target_file.parent), exist_ok=True)

        graph_data = self.build_graph_data()
        serialized_json = json.dumps(graph_data.to_dict(), indent=2, ensure_ascii=False)

        target_file.write_text(serialized_json, encoding="utf-8")
        logger.info("Successfully exported graph data to %s", target_file)
        return target_file
