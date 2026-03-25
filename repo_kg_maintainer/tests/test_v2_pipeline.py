from __future__ import annotations

from v2.analyzer.pipeline import PythonGraphAnalyzerV2
from v2.serializer import compute_snapshot_hash


def test_pipeline_produces_deterministic_graph_hash_and_sorted_entities() -> None:
    files = {
        "src/models.py": """
class Worker:
    def work(self):
        return 1
""",
        "src/service.py": """
from src.models import Worker

class Service:
    def run(self):
        worker = Worker()
        worker.work()
""",
    }

    analyzer = PythonGraphAnalyzerV2()
    first_result, first_snapshot = analyzer.analyze_files(files, "tenant-a", "repo-x", "c1")
    second_result, second_snapshot = analyzer.analyze_files(files, "tenant-a", "repo-x", "c1")

    assert first_result.graph_hash == second_result.graph_hash
    assert compute_snapshot_hash(first_snapshot) == compute_snapshot_hash(second_snapshot)

    node_ids = [node.id for node in first_snapshot.nodes]
    assert node_ids == sorted(node_ids)


def test_pipeline_attaches_provenance_for_edges() -> None:
    files = {
        "main.py": """
class A:
    def m(self):
        return B()

class B:
    pass
"""
    }

    analyzer = PythonGraphAnalyzerV2()
    _, snapshot = analyzer.analyze_files(files, "tenant-a", "repo-x", "c2")

    assert snapshot.edges
    for edge in snapshot.edges:
        assert edge.provenance.rule_id
        assert edge.provenance.extractor_pass
        assert edge.provenance.confidence > 0


def test_pipeline_emits_import_edges_for_local_symbols() -> None:
    files = {
        "workers.py": """
class Worker:
    def work(self):
        return 1
""",
        "service.py": """
from workers import Worker

class Service:
    def execute(self):
        worker = Worker()
        return worker.work()
""",
    }

    analyzer = PythonGraphAnalyzerV2()
    _, snapshot = analyzer.analyze_files(files, "tenant-a", "repo-x", "c3")

    assert any(edge.relation_type == "IMPORTS" for edge in snapshot.edges)
