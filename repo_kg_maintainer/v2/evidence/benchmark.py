from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from statistics import mean
from typing import Dict, List


@dataclass(frozen=True)
class BenchmarkCaseResult:
    case_id: str
    precision: float
    recall: float
    false_positive_count: int
    latency_ms: float
    cost_usd: float
    failure_type: str = "none"


@dataclass
class MonthlyBenchmarkReport:
    month: str
    generated_at: str
    total_cases: int
    avg_precision: float
    avg_recall: float
    avg_false_positives: float
    p95_latency_ms: float
    avg_cost_usd: float
    failure_taxonomy: Dict[str, int]
    cases: List[BenchmarkCaseResult] = field(default_factory=list)


def build_monthly_report(month: str, results: List[BenchmarkCaseResult]) -> MonthlyBenchmarkReport:
    if not results:
        raise ValueError("benchmark results cannot be empty")

    failure_taxonomy: Dict[str, int] = {}
    for result in results:
        failure_taxonomy[result.failure_type] = failure_taxonomy.get(result.failure_type, 0) + 1

    sorted_latency = sorted(result.latency_ms for result in results)
    p95_index = max(int(len(sorted_latency) * 0.95) - 1, 0)

    return MonthlyBenchmarkReport(
        month=month,
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_cases=len(results),
        avg_precision=mean(result.precision for result in results),
        avg_recall=mean(result.recall for result in results),
        avg_false_positives=mean(result.false_positive_count for result in results),
        p95_latency_ms=sorted_latency[p95_index],
        avg_cost_usd=mean(result.cost_usd for result in results),
        failure_taxonomy=failure_taxonomy,
        cases=results,
    )


def report_to_json(report: MonthlyBenchmarkReport) -> str:
    payload = asdict(report)
    return json.dumps(payload, indent=2, sort_keys=True)


def report_to_markdown(report: MonthlyBenchmarkReport) -> str:
    lines = [
        f"# Code Mesh Monthly Benchmark Report ({report.month})",
        "",
        f"Generated at: {report.generated_at}",
        "",
        "## Summary",
        f"- Total cases: {report.total_cases}",
        f"- Average precision: {report.avg_precision:.4f}",
        f"- Average recall: {report.avg_recall:.4f}",
        f"- Average false positives: {report.avg_false_positives:.2f}",
        f"- P95 latency (ms): {report.p95_latency_ms:.2f}",
        f"- Average cost (USD): {report.avg_cost_usd:.6f}",
        "",
        "## Failure Taxonomy",
    ]

    for failure_type, count in sorted(report.failure_taxonomy.items()):
        lines.append(f"- {failure_type}: {count}")

    lines.append("")
    lines.append("## Case Results")
    for case in sorted(report.cases, key=lambda item: item.case_id):
        lines.append(
            f"- {case.case_id}: precision={case.precision:.4f}, recall={case.recall:.4f}, "
            f"fp={case.false_positive_count}, latency_ms={case.latency_ms:.2f}, cost_usd={case.cost_usd:.6f}, "
            f"failure_type={case.failure_type}"
        )

    return "\n".join(lines)
