from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from code_analyze.code_analyzer import EntityInfo, FileInfo, RelationInfo


@dataclass
class AnalyzerPassContext:
    tenant_id: str
    repo_id: str
    commit_sha: str
    file_path: str
    content: str
    language: str = "python"
    tree: object | None = None
    file_entity: FileInfo | None = None
    entities: List[EntityInfo] = field(default_factory=list)
    import_map: Dict[str, str] = field(default_factory=dict)
    variable_types: Dict[str, str] = field(default_factory=dict)
    param_types: Dict[str, str] = field(default_factory=dict)
    return_types: Dict[str, str] = field(default_factory=dict)
    relations: List[RelationInfo] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class RelationRule:
    rule_id: str
    relation_type: str
    extractor_pass: str
    priority: int
    confidence: float


@dataclass
class AnalyzerResult:
    context: AnalyzerPassContext
    graph_hash: str
