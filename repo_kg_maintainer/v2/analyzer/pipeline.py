from __future__ import annotations

from typing import Dict, List, Tuple

from code_analyze.code_analyzer import EntityInfo
from code_analyze.python_analyzer import PythonAnalyzer
from code_analyze.python_relation import PythonRelationExtractor

from v2.analyzer.context import AnalyzerPassContext, AnalyzerResult
from v2.analyzer.import_resolution import ImportResolutionPass
from v2.analyzer.parse_normalize import ParseNormalizePass
from v2.analyzer.relation_extraction import RelationExtractionPass
from v2.analyzer.symbol_table import SymbolTablePass
from v2.analyzer.type_inference import TypeInferencePass
from v2.analyzer.validation import RelationValidationPass
from v2.ids import build_edge_id, build_node_id, canonical_symbol_path
from v2.models import GRAPH_VERSION, GraphEdge, GraphNode, GraphSnapshot, RelationProvenance
from v2.serializer import compute_snapshot_hash, get_schema_hash, canonicalize_snapshot


class PythonGraphAnalyzerV2:
    def __init__(self) -> None:
        self._analyzer = PythonAnalyzer()

    def analyze_files(
        self,
        files: Dict[str, str],
        tenant_id: str,
        repo_id: str,
        commit_sha: str,
    ) -> tuple[AnalyzerResult, GraphSnapshot]:
        if not files:
            raise ValueError("files cannot be empty")

        contexts: Dict[str, AnalyzerPassContext] = {}
        repo_entities: List[EntityInfo] = []

        parse_pass = ParseNormalizePass(self._analyzer)
        symbol_pass = SymbolTablePass(self._analyzer)

        for file_path in sorted(files):
            context = AnalyzerPassContext(
                tenant_id=tenant_id,
                repo_id=repo_id,
                commit_sha=commit_sha,
                file_path=file_path,
                content=files[file_path],
            )
            parse_pass.run(context)
            symbol_pass.run(context)
            contexts[file_path] = context
            repo_entities.extend(context.entities)

        nodes, legacy_to_node_id = self._build_nodes(contexts, tenant_id, repo_id, commit_sha)

        edges: List[GraphEdge] = []
        for file_path in sorted(contexts):
            context = contexts[file_path]
            extractor = PythonRelationExtractor(self._analyzer.parser, repo_entities)
            ImportResolutionPass(extractor).run(context)
            TypeInferencePass(extractor).run(context)
            RelationExtractionPass(extractor).run(context)
            RelationValidationPass().run(context)
            edges.extend(
                self._build_edges(
                    context,
                    tenant_id,
                    repo_id,
                    commit_sha,
                    legacy_to_node_id,
                )
            )

        snapshot = GraphSnapshot(
            tenant_id=tenant_id,
            repo_id=repo_id,
            commit_sha=commit_sha,
            graph_version=GRAPH_VERSION,
            schema_hash=get_schema_hash(),
            nodes=nodes,
            edges=edges,
        )
        canonicalize_snapshot(snapshot)
        graph_hash = compute_snapshot_hash(snapshot)

        representative_context = contexts[sorted(contexts)[0]]
        return AnalyzerResult(context=representative_context, graph_hash=graph_hash), snapshot

    def _build_nodes(
        self,
        contexts: Dict[str, AnalyzerPassContext],
        tenant_id: str,
        repo_id: str,
        commit_sha: str,
    ) -> Tuple[List[GraphNode], Dict[str, str]]:
        nodes: List[GraphNode] = []
        legacy_to_node_id: Dict[str, str] = {}

        for file_path in sorted(contexts):
            context = contexts[file_path]
            if context.file_entity is not None:
                symbol_path = canonical_symbol_path(file_path, "", "<file>")
                file_node_id = build_node_id(
                    tenant_id,
                    repo_id,
                    commit_sha,
                    context.file_entity.entity_type,
                    symbol_path,
                )
                nodes.append(
                    GraphNode(
                        id=file_node_id,
                        tenant_id=tenant_id,
                        repo_id=repo_id,
                        commit_sha=commit_sha,
                        entity_kind=context.file_entity.entity_type,
                        symbol_path=symbol_path,
                        file_path=file_path,
                        name="<file>",
                        parent_name="",
                        metadata={
                            "description": context.file_entity.description,
                            "size": context.file_entity.size,
                            "file_type": context.file_entity.file_type,
                        },
                    )
                )

            for entity in sorted(
                context.entities,
                key=lambda item: (
                    item.entity_type,
                    item.file_path,
                    item.parent_name,
                    item.name,
                ),
            ):
                symbol_path = canonical_symbol_path(
                    entity.file_path,
                    entity.parent_name,
                    entity.name,
                )
                node_id = build_node_id(
                    tenant_id,
                    repo_id,
                    commit_sha,
                    entity.entity_type,
                    symbol_path,
                )
                nodes.append(
                    GraphNode(
                        id=node_id,
                        tenant_id=tenant_id,
                        repo_id=repo_id,
                        commit_sha=commit_sha,
                        entity_kind=entity.entity_type,
                        symbol_path=symbol_path,
                        file_path=entity.file_path,
                        name=entity.name,
                        parent_name=entity.parent_name,
                        metadata={
                            "description": entity.description,
                            "complexity": entity.complexity,
                            "is_exported": entity.is_exported,
                            "modifiers": list(entity.modifiers),
                        },
                    )
                )
                legacy_key = self._legacy_entity_key(entity)
                legacy_to_node_id[legacy_key] = node_id

        return nodes, legacy_to_node_id

    def _build_edges(
        self,
        context: AnalyzerPassContext,
        tenant_id: str,
        repo_id: str,
        commit_sha: str,
        legacy_to_node_id: Dict[str, str],
    ) -> List[GraphEdge]:
        edges: List[GraphEdge] = []
        for relation in context.relations:
            source_id = legacy_to_node_id.get(relation.source.key)
            target_id = legacy_to_node_id.get(relation.target.key)
            if not source_id or not target_id:
                continue

            provenance_dict = relation.metadata.get("provenance", {})
            provenance = RelationProvenance(
                extractor_pass=provenance_dict.get("extractor_pass", "relation_extraction"),
                rule_id=provenance_dict.get("rule_id", "relation.unknown"),
                source_span=tuple(provenance_dict.get("source_span", relation.source_location)),
                confidence=float(provenance_dict.get("confidence", 0.5)),
            )
            edge_id = build_edge_id(source_id, relation.relation_type, target_id, provenance.rule_id)

            metadata = dict(relation.metadata)
            metadata.pop("provenance", None)

            edges.append(
                GraphEdge(
                    id=edge_id,
                    tenant_id=tenant_id,
                    repo_id=repo_id,
                    commit_sha=commit_sha,
                    source_id=source_id,
                    target_id=target_id,
                    relation_type=relation.relation_type,
                    provenance=provenance,
                    metadata=metadata,
                )
            )

        return edges

    @staticmethod
    def _legacy_entity_key(entity: EntityInfo) -> str:
        parent = f"{entity.parent_name}/" if entity.parent_name else ""
        return f"{entity.entity_type}/{entity.file_path}/{parent}{entity.name}"
