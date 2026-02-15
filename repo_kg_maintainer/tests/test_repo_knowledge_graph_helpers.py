from __future__ import annotations

import logging
from datetime import datetime, timezone

from code_analyze.code_analyzer import EntityInfo, EntityType
from repo_knowledge_graph import RepoKnowledgeGraph


class FakeCollection:
    def __init__(self, docs=None):
        self._docs = list(docs or [])

    def all(self):
        return iter(self._docs)


class FakeAQL:
    def __init__(self, docs_by_collection):
        self._docs_by_collection = docs_by_collection

    def execute(self, _query, bind_vars):
        collection_name = bind_vars["@collection"]
        file_path = bind_vars.get("file_path")
        docs = self._docs_by_collection.get(collection_name, [])
        if file_path is None:
            return list(docs)
        return [doc for doc in docs if doc.get("file_path") == file_path]


class FakeDB:
    def __init__(self, file_docs=None, entity_docs=None):
        self._collections = {"File": FakeCollection(file_docs)}
        self.aql = FakeAQL(entity_docs or {})

    def collection(self, name):
        return self._collections.setdefault(name, FakeCollection())


class FakeRepo:
    def __init__(self, contents):
        self._contents = contents
        self._repo = object()

    def get_file_content(self, file_path):
        return self._contents[file_path]


def _new_kg(db: FakeDB, repo: FakeRepo | None = None) -> RepoKnowledgeGraph:
    kg = RepoKnowledgeGraph.__new__(RepoKnowledgeGraph)
    kg.db = db
    kg.repo = repo
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


def test_detect_file_changes_detects_added_modified_and_deleted_files() -> None:
    existing_docs = [
        {
            "file_path": "src/a.py",
            "last_modified": "2024-01-01T00:00:00+00:00",
            "content_hash": "old-hash",
        },
        {
            "file_path": "src/deleted.py",
            "last_modified": "2024-01-02T00:00:00+00:00",
            "content_hash": "deleted-hash",
        },
    ]
    repo = FakeRepo(
        {
            "src/a.py": "print('updated')",
            "src/b.py": "print('new')",
        }
    )
    kg = _new_kg(FakeDB(file_docs=existing_docs), repo=repo)

    last_modified_by_file = {
        "src/a.py": datetime(2024, 1, 3, tzinfo=timezone.utc),
        "src/b.py": datetime(2024, 1, 4, tzinfo=timezone.utc),
    }
    kg.get_file_last_modified = lambda _repo, file_path: last_modified_by_file[file_path]

    structure = {
        "src": {
            "children": {
                "a.py": {"path": "src/a.py"},
                "b.py": {"path": "src/b.py"},
            }
        }
    }

    changes = kg._detect_file_changes(structure)
    by_file = {change.file_path: change for change in changes}

    assert by_file["src/a.py"].change_type == "modified"
    assert by_file["src/b.py"].change_type == "added"
    assert by_file["src/deleted.py"].change_type == "deleted"


def test_detect_entity_changes_detects_added_modified_and_deleted_entities() -> None:
    existing_entities = {
        "Class": [
            {
                "entity_type": "Class",
                "file_path": "src/a.py",
                "name": "A",
                "parent_name": "",
                "content_hash": "same-class-hash",
            }
        ],
        "Method": [
            {
                "entity_type": "Method",
                "file_path": "src/a.py",
                "name": "old_method",
                "parent_name": "A",
                "content_hash": "old-method-hash",
            }
        ],
        "Variable": [
            {
                "entity_type": "Variable",
                "file_path": "src/a.py",
                "name": "STALE",
                "parent_name": "",
                "content_hash": "stale-hash",
            }
        ],
    }

    kg = _new_kg(FakeDB(entity_docs=existing_entities))

    new_entities = [
        EntityInfo(entity_type="Class", name="A", file_path="src/a.py", content="same-class"),
        EntityInfo(entity_type="Method", name="old_method", parent_name="A", file_path="src/a.py", content="new-method"),
        EntityInfo(entity_type="Method", name="new_method", parent_name="A", file_path="src/a.py", content="brand-new"),
    ]

    # Align class hash so that Class A is treated as unchanged.
    existing_entities["Class"][0]["content_hash"] = kg._calculate_content_hash("same-class")

    changes = kg._detect_entity_changes("src/a.py", new_entities)
    signatures = {(change.change_type, change.entity_type, change.entity_key) for change in changes}

    assert any(change_type == "modified" and entity_type == "Method" for change_type, entity_type, _ in signatures)
    assert any(change_type == "added" and entity_type == "Method" for change_type, entity_type, _ in signatures)
    assert any(change_type == "deleted" and entity_type == "Variable" for change_type, entity_type, _ in signatures)


def test_determine_module_type_classifies_paths() -> None:
    kg = _new_kg(FakeDB())

    assert kg._determine_module_type("tests/test_parser.py") == "test"
    assert kg._determine_module_type("docs/architecture.md") == "documentation"
    assert kg._determine_module_type("config/settings.py") == "config"
    assert kg._determine_module_type("src/runtime/engine.py") == "source"
