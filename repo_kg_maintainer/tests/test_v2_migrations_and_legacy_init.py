from __future__ import annotations

from code_analyze.code_analyzer import EntityType, RelationType
from repo_knowledge_graph import RepoKnowledgeGraph
from v2.graph.migrations import EDGE_COLLECTION, MigrationManagerV2, VERTEX_COLLECTION


class FakeCollection:
    def __init__(self, name: str) -> None:
        self.name = name
        self._indexes = []

    def indexes(self):
        return list(self._indexes)

    def add_persistent_index(self, fields, unique=False):
        self._indexes.append({"fields": fields, "unique": unique})


class FakeDB:
    def __init__(self, existing=None):
        self._collections = {name: FakeCollection(name) for name in (existing or [])}
        self.deleted = []
        self.created = []

    def has_collection(self, name):
        return name in self._collections

    def create_collection(self, name, edge=False):
        self._collections[name] = FakeCollection(name)
        self.created.append((name, edge))

    def delete_collection(self, name):
        self.deleted.append(name)
        self._collections.pop(name, None)

    def collection(self, name):
        return self._collections[name]


def test_migration_manager_bootstraps_non_destructively() -> None:
    db = FakeDB(existing=[VERTEX_COLLECTION])
    manager = MigrationManagerV2()

    result = manager.bootstrap(db)

    assert any(name == EDGE_COLLECTION for name, _ in db.created)
    assert VERTEX_COLLECTION not in [name for name, _ in db.created]
    assert result["indexes"]


def test_repo_knowledge_graph_init_collections_default_is_non_destructive() -> None:
    db = FakeDB(existing=[entity.value for entity in EntityType] + [relation.value for relation in RelationType])
    kg = RepoKnowledgeGraph.__new__(RepoKnowledgeGraph)
    kg.db = db

    kg._init_collections(reset=False)

    assert db.deleted == []


def test_repo_knowledge_graph_init_collections_can_reset_when_requested() -> None:
    db = FakeDB(existing=[entity.value for entity in EntityType] + [relation.value for relation in RelationType])
    kg = RepoKnowledgeGraph.__new__(RepoKnowledgeGraph)
    kg.db = db

    kg._init_collections(reset=True)

    assert set(db.deleted) >= {entity.value for entity in EntityType}
    assert set(db.deleted) >= {relation.value for relation in RelationType}
