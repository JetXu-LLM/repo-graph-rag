from __future__ import annotations

import builtins
import json
import sys
from pathlib import Path

import pytest

import main
import main_v2


def test_collect_python_files_skips_hidden_and_generated_directories(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("class App:\n    pass\n", encoding="utf-8")
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "ignored.py").write_text("class Ignored:\n    pass\n", encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "generated.py").write_text("class Generated:\n    pass\n", encoding="utf-8")
    (tmp_path / ".hidden.py").write_text("class Hidden:\n    pass\n", encoding="utf-8")

    files = main_v2._collect_python_files(tmp_path)

    assert files == {"src/app.py": "class App:\n    pass\n"}


def test_main_v2_writes_snapshot_and_prints_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    (source / "service.py").write_text(
        "class Service:\n    def run(self):\n        return Worker()\n\n"
        "class Worker:\n    pass\n",
        encoding="utf-8",
    )
    output = tmp_path / "out" / "snapshot.json"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main_v2.py",
            "--tenant",
            "tenant-a",
            "--repo",
            "demo/repo",
            "--commit",
            "sha-1",
            "--source",
            str(source),
            "--output",
            str(output),
        ],
    )

    main_v2.main()

    summary = json.loads(capsys.readouterr().out)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert output.exists()
    assert payload["graph_version"] == "2.0"
    assert payload["nodes"]
    assert payload["edges"]
    assert summary["output"] == str(output.resolve())
    assert summary["snapshot_hash"]
    assert summary["nodes"] == len(payload["nodes"])
    assert summary["edges"] == len(payload["edges"])


def test_main_v2_errors_when_no_python_files_are_found(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    empty_repo = tmp_path / "empty"
    empty_repo.mkdir()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main_v2.py",
            "--tenant",
            "tenant-a",
            "--repo",
            "demo/repo",
            "--commit",
            "sha-1",
            "--source",
            str(empty_repo),
            "--output",
            str(tmp_path / "out.json"),
        ],
    )

    with pytest.raises(SystemExit, match="No Python source files were found"):
        main_v2.main()


def test_legacy_parser_requires_explicit_repo() -> None:
    parser = main._build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_legacy_require_github_rag_surfaces_requirements_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[override]
        if name == "llama_github":
            raise ImportError("missing llama_github")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="requirements-legacy.txt"):
        main._require_github_rag()


def test_load_repo_structure_retries_transient_failures() -> None:
    class FakeRepo:
        def __init__(self) -> None:
            self.calls = 0

        def get_structure(self):
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError("temporary failure")
            return {"service.py": {}}

    repo = FakeRepo()

    assert main._load_repo_structure(repo, attempts=3, delay_seconds=0) == {"service.py": {}}


def test_load_repo_structure_raises_clear_error_after_retries() -> None:
    class FakeRepo:
        def get_structure(self):
            raise RuntimeError("still failing")

    with pytest.raises(RuntimeError, match="Failed to fetch repository structure"):
        main._load_repo_structure(FakeRepo(), attempts=2, delay_seconds=0)
