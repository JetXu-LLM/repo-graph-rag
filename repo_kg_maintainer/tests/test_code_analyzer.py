from __future__ import annotations

from typing import Dict, Optional

from code_analyze.code_analyzer import CodeAnalyzer, EntityType
from code_analyze.python_analyzer import PythonAnalyzer


class FakeRepository:
    def __init__(self, files: Dict[str, Optional[str]]):
        self._files = files

    def get_file_content(self, file_path: str, sha: str | None = None) -> Optional[str]:
        return self._files.get(file_path)


def test_supported_extension_lookup_is_case_insensitive() -> None:
    assert CodeAnalyzer.is_supported_extension("PY") is True
    assert CodeAnalyzer.is_supported_extension("Ts") is True
    assert CodeAnalyzer.is_supported_extension("go") is False

    assert CodeAnalyzer.get_language_for_extension("PY") == "python"
    assert CodeAnalyzer.get_language_for_extension("tsx") == "tsx"
    assert CodeAnalyzer.get_language_for_extension("go") is None


def test_get_file_language_uses_extension_map() -> None:
    analyzer = CodeAnalyzer(FakeRepository({}))

    assert analyzer.get_file_language("src/main.py") == "python"
    assert analyzer.get_file_language("cmd/main.go") == "go"
    assert analyzer.get_file_language("README") is None


def test_tree_to_dict_with_options_respects_depth_and_skip_types() -> None:
    code = "x = 1\n# comment\n"
    parser = PythonAnalyzer()
    tree = parser.parser_code(code)

    result = CodeAnalyzer.tree_to_dict_with_options(
        tree.root_node,
        code,
        {
            "include_position": True,
            "include_empty_text": False,
            "max_depth": 2,
            "skip_types": {"comment"},
        },
    )

    assert result["type"] == "module"
    assert "children" in result
    assert all(child["type"] != "comment" for child in result["children"])


def test_get_file_entities_returns_empty_for_unsupported_extension() -> None:
    analyzer = CodeAnalyzer(FakeRepository({"docs/readme.md": "hello"}))

    file_info, entities = analyzer.get_file_entities("docs/readme.md")

    assert file_info is None
    assert entities == []


def test_get_file_entities_returns_empty_when_content_cannot_be_loaded() -> None:
    analyzer = CodeAnalyzer(FakeRepository({"src/a.py": None}))

    file_info, entities = analyzer.get_file_entities("src/a.py")

    assert file_info is None
    assert entities == []


def test_get_file_entities_extracts_python_entities() -> None:
    code = """
VALUE = 1

class Worker:
    def run(self):
        return VALUE
"""
    analyzer = CodeAnalyzer(FakeRepository({"src/worker.py": code}))

    file_info, entities = analyzer.get_file_entities("src/worker.py")

    assert file_info is not None
    assert file_info.entity_type == EntityType.FILE.value
    assert file_info.file_type == "python"
    assert {entity.name for entity in entities} >= {"VALUE", "Worker", "run"}


def test_get_file_relations_returns_placeholder_for_unsupported_extension() -> None:
    analyzer = CodeAnalyzer(FakeRepository({"docs/readme.md": "text"}))

    relations = analyzer.get_file_relations("docs/readme.md", repo_entities=[])

    assert relations == {"file": {}, "entities": [], "relationships": []}


def test_get_file_relations_extracts_python_relations() -> None:
    code = """
class Worker:
    def run(self):
        return 1

class Service:
    def execute(self):
        worker = Worker()
        worker.run()
"""
    repository = FakeRepository({"src/service.py": code})
    analyzer = CodeAnalyzer(repository)

    _, entities = analyzer.get_file_entities("src/service.py")
    relations = analyzer.get_file_relations("src/service.py", repo_entities=entities)

    relation_types = {relation.relation_type for relation in relations}
    edges = {(relation.source.name, relation.target.name) for relation in relations}

    assert "INSTANTIATES" in relation_types
    assert "CALLS" in relation_types
    assert ("execute", "Worker") in edges
    assert ("execute", "run") in edges


def test_get_code_entities_dispatches_python_language() -> None:
    analyzer = CodeAnalyzer(FakeRepository({}))

    file_info, entities = analyzer.get_code_entities("class A:\n    pass\n", "python")

    assert file_info.file_type == "python"
    assert any(entity.name == "A" and entity.entity_type == EntityType.CLASS.value for entity in entities)
