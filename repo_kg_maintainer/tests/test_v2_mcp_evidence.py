from __future__ import annotations

from v2.analyzer.pipeline import PythonGraphAnalyzerV2
from v2.evidence.benchmark import BenchmarkCaseResult, build_monthly_report, report_to_json, report_to_markdown
from v2.graph.store import InMemoryGraphStoreV2
from v2.mcp.toolset import GraphMCPToolsetV2


def _build_snapshot_store() -> InMemoryGraphStoreV2:
    analyzer = PythonGraphAnalyzerV2()
    _, snapshot = analyzer.analyze_files(
        files={
            "main.py": """
class Service:
    def run(self):
        worker = Worker()
        worker.work()

class Worker:
    def work(self):
        return 1
"""
        },
        tenant_id="tenant-a",
        repo_id="repo-x",
        commit_sha="sha-1",
    )
    store = InMemoryGraphStoreV2()
    store.save_snapshot(snapshot)
    return store


def test_mcp_toolset_supports_entity_relation_and_explain_calls() -> None:
    store = _build_snapshot_store()
    mcp = GraphMCPToolsetV2(store)

    entities = mcp.find_entities("tenant-a", "repo-x", "sha-1", limit=20)
    relations = mcp.find_relations("tenant-a", "repo-x", "sha-1", limit=20)
    subgraph = mcp.get_subgraph("tenant-a", "repo-x", "sha-1", hop_limit=2)

    assert entities["nodes"]
    assert relations["edges"]
    assert subgraph["nodes"]

    first_edge_id = relations["edges"][0]["id"]
    explanation = mcp.explain_relation("tenant-a", "repo-x", "sha-1", first_edge_id)
    assert explanation is not None
    assert explanation["provenance"]["rule_id"]


def test_monthly_benchmark_report_generates_json_and_markdown() -> None:
    report = build_monthly_report(
        month="2026-02",
        results=[
            BenchmarkCaseResult(
                case_id="case-1",
                precision=0.95,
                recall=0.9,
                false_positive_count=1,
                latency_ms=120.0,
                cost_usd=0.012,
                failure_type="none",
            ),
            BenchmarkCaseResult(
                case_id="case-2",
                precision=0.92,
                recall=0.93,
                false_positive_count=0,
                latency_ms=150.0,
                cost_usd=0.01,
                failure_type="alias_resolution",
            ),
        ],
    )

    json_payload = report_to_json(report)
    markdown_payload = report_to_markdown(report)

    assert '"month": "2026-02"' in json_payload
    assert "# Code Mesh Monthly Benchmark Report (2026-02)" in markdown_payload
    assert "alias_resolution" in markdown_payload
