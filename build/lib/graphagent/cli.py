"""Command-line interface for GraphAgent Code Parser."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import List, Optional

from graphagent.exporter import PARSER_VERSION, Exporter
from graphagent.language_registry import default_registry
from graphagent.models import SummaryInfo
from graphagent.relationship_resolver import RelationshipResolver
from graphagent.scanner import Scanner
from graphagent.symbol_extractor import SymbolExtractor


def setup_logging(verbose: bool) -> None:
    """Configure console logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s" if verbose else "%(message)s",
    )


def print_banner() -> None:
    print(
        """
  ██████╗ ██████╗  █████╗ ██████╗ ██╗  ██╗ █████╗  ██████╗ ███████╗███╗   ██╗████████╗
 ██╔════╝ ██╔══██╗██╔══██╗██╔══██╗██║  ██║██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝
 ██║  ███╗██████╔╝███████║██████╔╝███████║███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   
 ██║   ██║██╔══██╗██╔══██║██╔═══╝ ██╔══██║██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   
 ╚██████╔╝██║  ██║██║  ██║██║     ██║  ██║██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   
  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   
                        Multi-Language Code Graph Parser v{version}
""".format(version=PARSER_VERSION)
    )


def run_parse(
    repo_path: str,
    output_path: Optional[str] = None,
    verbose: bool = False,
    extra_excludes: Optional[List[str]] = None,
) -> int:
    """Execute repository parse and export JSON."""
    setup_logging(verbose)
    target_dir = Path(repo_path).resolve()

    if not target_dir.is_dir():
        print(f"❌ Error: Target path is not a directory: {target_dir}", file=sys.stderr)
        return 1

    start_time = time.perf_counter()
    print_banner()
    print(f"🔍 Scanning repository: {target_dir}")

    # 1. Scanner
    scanner = Scanner(str(target_dir), extra_excludes=extra_excludes)
    discovered_files, scan_warnings = scanner.scan()

    if not discovered_files:
        print("⚠️ No supported source code files found in repository.")
        return 0

    detected_languages = sorted({lang for _, _, lang in discovered_files})
    print(f"📁 Found {len(discovered_files)} source files across {len(detected_languages)} languages: {', '.join(detected_languages)}")

    # 2. Extract symbols
    if verbose:
        print("\n⚙️ Parsing source ASTs...")
    extractor = SymbolExtractor(default_registry)
    parse_results, extract_messages = extractor.extract_all(discovered_files)

    success_files = sum(1 for r in parse_results if r.success)
    error_files = len(parse_results) - success_files

    # 3. Resolve relationships
    if verbose:
        print("🔗 Resolving cross-file relationships (CALLS, IMPORTS, INHERITS)...")
    resolver = RelationshipResolver(parse_results)
    nodes, edges = resolver.resolve()

    # 4. Compile statistics
    node_type_counts: dict[str, int] = {}
    for n in nodes:
        node_type_counts[n.type] = node_type_counts.get(n.type, 0) + 1

    edge_type_counts: dict[str, int] = {}
    edge_res_counts: dict[str, int] = {}
    for e in edges:
        edge_type_counts[e.type] = edge_type_counts.get(e.type, 0) + 1
        edge_res_counts[e.resolution] = edge_res_counts.get(e.resolution, 0) + 1

    all_warnings = list(scan_warnings) + list(extract_messages)
    summary = SummaryInfo(
        files_scanned=len(discovered_files),
        files_parsed=success_files,
        nodes_count=len(nodes),
        edges_count=len(edges),
        errors_count=error_files,
    )

    # 5. Export JSON
    exporter = Exporter(
        repo_root=target_dir,
        nodes=nodes,
        edges=edges,
        summary=summary,
        languages=detected_languages,
        warnings=all_warnings,
    )
    written_file = exporter.export(output_path)
    file_size_kb = written_file.stat().st_size / 1024
    elapsed = time.perf_counter() - start_time

    # 6. Terminal Summary Report
    print("\n" + "=" * 65)
    print("                    PARSER EXECUTION SUMMARY")
    print("=" * 65)
    print(f"  • Repository:           {target_dir.name} ({target_dir})")
    print(f"  • Execution Time:       {elapsed:.2f} seconds")
    print(f"  • Files Discovered:     {len(discovered_files)}")
    print(f"  • Files Parsed:         {success_files} (errors: {error_files})")
    print(f"  • Languages Detected:   {', '.join(detected_languages)}")
    print("\n  📦 Extracted Entities (Nodes):")
    for ntype, count in sorted(node_type_counts.items()):
        print(f"     - {ntype.capitalize():<15} {count}")
    print(f"     Total Nodes:        {len(nodes)}")

    print("\n  🔗 Resolved Relationships (Edges):")
    for etype, count in sorted(edge_type_counts.items()):
        print(f"     - {etype:<15} {count}")
    print(f"     Total Edges:        {len(edges)}")

    print("\n  🎯 Relationship Resolutions:")
    for res_name, count in sorted(edge_res_counts.items()):
        print(f"     - {res_name:<15} {count}")

    if all_warnings:
        print(f"\n  ⚠️ Warnings ({len(all_warnings)}):")
        for w in all_warnings[:5]:
            print(f"     • {w}")
        if len(all_warnings) > 5:
            print(f"     ... and {len(all_warnings) - 5} more warnings.")

    print("\n" + "-" * 65)
    print(f"  ✅ Output Graph JSON:   {written_file} ({file_size_kb:.1f} KB)")
    print("=" * 65 + "\n")

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="graphagent",
        description="GraphAgent Multi-Language Code Parser CLI — Analyzes repositories and produces graph JSON.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"graphagent {PARSER_VERSION}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommand to execute")

    # 'parse' subcommand
    parse_cmd = subparsers.add_parser("parse", help="Analyze repository source code and export graph JSON")
    parse_cmd.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to repository root (defaults to current directory)",
    )
    parse_cmd.add_argument(
        "-o",
        "--output",
        default=None,
        help="Custom destination path for graph JSON (default: .graphagent/graph_data.json)",
    )
    parse_cmd.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable detailed logging during parsing",
    )
    parse_cmd.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Additional glob pattern to exclude from scanning",
    )

    return parser


def main() -> None:
    """CLI entrypoint."""
    parser = build_parser()

    # If invoked without arguments, show help
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    if args.command == "parse":
        exit_code = run_parse(
            repo_path=args.path,
            output_path=args.output,
            verbose=args.verbose,
            extra_excludes=args.exclude,
        )
        sys.exit(exit_code)
    else:
        parser.print_help(sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
