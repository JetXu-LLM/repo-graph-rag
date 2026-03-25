from __future__ import annotations

import logging
from repo_knowledge_graph import RepoKnowledgeGraph


class FakeCollection:
    def __init__(self, docs=None):
        self._docs = list(docs or [])

    def all(self):
        return iter(self._docs)


class FakeDB:
    def __init__(self, file_docs=None):
        self._collections = {"File": FakeCollection(file_docs)}

    def collection(self, name):
        return self._collections.setdefault(name, FakeCollection())


def _new_kg(db: FakeDB) -> RepoKnowledgeGraph:
    kg = RepoKnowledgeGraph.__new__(RepoKnowledgeGraph)
    kg.db = db
    kg.logger = logging.getLogger("repo_kg_tests")
    return kg


def test_generate_key_sanitizes_and_truncates_long_paths() -> None:
    kg = _new_kg(FakeDB())

    safe_key = kg._generate_key("src/path/module.py")
    long_key = kg._generate_key("module/" + "nested-segment/" * 40 + "file.py")

    assert safe_key == "src_path_module_py"
    assert len(long_key) <= 254
    assert long_key.endswith("_trunc")


def test_calculate_content_hash_is_stable() -> None:
    kg = _new_kg(FakeDB())

    first = kg._calculate_content_hash("same-content")
    second = kg._calculate_content_hash("same-content")
    third = kg._calculate_content_hash("different-content")

    assert first == second
    assert first != third


def test_determine_module_type_classifies_paths() -> None:
    kg = _new_kg(FakeDB())

    assert kg._determine_module_type("tests/test_parser.py") == "test"
    assert kg._determine_module_type("docs/architecture.md") == "documentation"
    assert kg._determine_module_type("config/settings.py") == "config"
    assert kg._determine_module_type("src/runtime/engine.py") == "source"
