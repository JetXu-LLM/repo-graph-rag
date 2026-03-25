"""Public CLI entrypoint for the deterministic Python v2 snapshot pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from v2.analyzer.pipeline import PythonGraphAnalyzerV2
from v2.serializer import compute_snapshot_hash, snapshot_to_dict


_IGNORED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "env",
    "node_modules",
    "venv",
}


def _is_ignored_relative_path(relative_path: Path) -> bool:
    """Exclude hidden and generated directories from snapshot collection."""
    for part in relative_path.parts[:-1]:
        if part.startswith(".") or part in _IGNORED_DIR_NAMES:
            return True
    return False


def _collect_python_files(root: Path) -> dict[str, str]:
    """Collect repository Python sources using stable relative-path ordering."""
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if path.name.startswith(".") or _is_ignored_relative_path(relative):
            continue
        relative_path = str(relative)
        files[relative_path] = path.read_text(encoding="utf-8", errors="ignore")
    return files


def main() -> None:
    """Build a deterministic graph snapshot from a local Python repository."""
    parser = argparse.ArgumentParser(
        description=(
            "Build a deterministic graph snapshot for a local Python repository. "
            "The public v2 path analyzes tracked source-style Python files and "
            "writes a canonical JSON snapshot."
        )
    )
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--source", required=True, help="Local repository path")
    parser.add_argument("--output", required=True, help="Snapshot JSON output path")
    args = parser.parse_args()

    source_path = Path(args.source).resolve()
    if not source_path.exists():
        raise SystemExit(f"Source path does not exist: {source_path}")
    if not source_path.is_dir():
        raise SystemExit(f"Source path must be a directory: {source_path}")

    files = _collect_python_files(source_path)
    if not files:
        raise SystemExit(
            "No Python source files were found under --source after applying "
            "the built-in directory filters."
        )

    analyzer = PythonGraphAnalyzerV2()
    _, snapshot = analyzer.analyze_files(
        files=files,
        tenant_id=args.tenant,
        repo_id=args.repo,
        commit_sha=args.commit,
    )

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_dict = snapshot_to_dict(snapshot)
    output_path.write_text(json.dumps(snapshot_dict, indent=2, sort_keys=True), encoding="utf-8")

    summary = {
        "output": str(output_path),
        "graph_version": snapshot_dict["graph_version"],
        "schema_hash": snapshot_dict["schema_hash"],
        "snapshot_hash": compute_snapshot_hash(snapshot),
        "nodes": len(snapshot_dict["nodes"]),
        "edges": len(snapshot_dict["edges"]),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
