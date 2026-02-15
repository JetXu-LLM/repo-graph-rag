from __future__ import annotations

import argparse
from pathlib import Path
import json

from v2.analyzer.pipeline import PythonGraphAnalyzerV2
from v2.serializer import snapshot_to_dict


def _collect_python_files(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*.py")):
        if path.name.startswith("."):
            continue
        relative_path = str(path.relative_to(root))
        files[relative_path] = path.read_text(encoding="utf-8", errors="ignore")
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description="Build deterministic graph snapshot v2")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--source", required=True, help="Local repository path")
    parser.add_argument("--output", required=True, help="Snapshot JSON output path")
    args = parser.parse_args()

    source_path = Path(args.source).resolve()
    files = _collect_python_files(source_path)

    analyzer = PythonGraphAnalyzerV2()
    _, snapshot = analyzer.analyze_files(
        files=files,
        tenant_id=args.tenant,
        repo_id=args.repo,
        commit_sha=args.commit,
    )

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot_to_dict(snapshot), indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
