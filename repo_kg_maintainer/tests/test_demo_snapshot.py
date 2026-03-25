from __future__ import annotations

import json
from pathlib import Path

from main_v2 import _collect_python_files
from v2.analyzer.pipeline import PythonGraphAnalyzerV2
from v2.serializer import compute_snapshot_hash, snapshot_to_dict


REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_REPO = REPO_ROOT / "examples" / "python_demo_repo"
EXPECTED_SNAPSHOT = REPO_ROOT / "examples" / "python_demo_snapshot_v2.json"
DEMO_TENANT = "tenant-demo"
DEMO_REPO_ID = "examples/python-demo"
DEMO_COMMIT = "demo-commit"


def test_demo_snapshot_matches_committed_fixture() -> None:
    files = _collect_python_files(DEMO_REPO)
    analyzer = PythonGraphAnalyzerV2()
    _, snapshot = analyzer.analyze_files(files, DEMO_TENANT, DEMO_REPO_ID, DEMO_COMMIT)

    actual = json.loads(json.dumps(snapshot_to_dict(snapshot)))
    expected = json.loads(EXPECTED_SNAPSHOT.read_text(encoding="utf-8"))

    actual.pop("generated_at", None)
    expected.pop("generated_at", None)

    assert actual == expected


def test_demo_snapshot_hash_is_stable() -> None:
    files = _collect_python_files(DEMO_REPO)
    analyzer = PythonGraphAnalyzerV2()
    _, snapshot = analyzer.analyze_files(files, DEMO_TENANT, DEMO_REPO_ID, DEMO_COMMIT)

    assert compute_snapshot_hash(snapshot) == "1c6493238faab5970ec76770a1ddafed05099c21a8d4b411776aa6111aecea1e"
