from __future__ import annotations

from typing import Dict, List, Tuple

from code_analyze.code_analyzer import RelationInfo, RelationKey

from v2.analyzer.context import AnalyzerPassContext, RelationRule
from v2.analyzer.rules import resolve_rule


class RelationValidationPass:
    name = "relation_validation"

    def run(self, context: AnalyzerPassContext) -> AnalyzerPassContext:
        deduped: Dict[RelationKey, RelationInfo] = {}
        prioritized: Dict[RelationKey, RelationRule] = {}

        for relation in context.relations:
            rule = resolve_rule(relation)
            key = RelationKey(relation.source.key, relation.target.key, relation.relation_type)
            existing_rule = prioritized.get(key)
            if existing_rule and existing_rule.priority <= rule.priority:
                continue
            relation.metadata = dict(relation.metadata or {})
            relation.metadata["provenance"] = {
                "extractor_pass": rule.extractor_pass,
                "rule_id": rule.rule_id,
                "source_span": relation.source_location,
                "confidence": rule.confidence,
            }
            deduped[key] = relation
            prioritized[key] = rule

        context.relations = sorted(
            deduped.values(),
            key=lambda rel: (
                rel.source.key,
                rel.relation_type,
                rel.target.key,
                rel.metadata["provenance"]["rule_id"],
            ),
        )
        return context
