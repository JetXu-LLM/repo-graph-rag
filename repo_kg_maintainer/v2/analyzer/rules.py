from __future__ import annotations

from typing import Dict

from code_analyze.code_analyzer import RelationInfo

from v2.analyzer.context import RelationRule


_DEFAULT_RULES: Dict[str, RelationRule] = {
    "INHERITS": RelationRule(
        rule_id="inherits.class.base",
        relation_type="INHERITS",
        extractor_pass="relation_extraction",
        priority=10,
        confidence=0.99,
    ),
    "INSTANTIATES": RelationRule(
        rule_id="instantiates.class.call",
        relation_type="INSTANTIATES",
        extractor_pass="relation_extraction",
        priority=20,
        confidence=0.97,
    ),
    "CALLS": RelationRule(
        rule_id="calls.function.dispatch",
        relation_type="CALLS",
        extractor_pass="relation_extraction",
        priority=30,
        confidence=0.9,
    ),
    "USES": RelationRule(
        rule_id="uses.type.reference",
        relation_type="USES",
        extractor_pass="type_inference",
        priority=40,
        confidence=0.88,
    ),
    "MODIFIES": RelationRule(
        rule_id="modifies.global.variable",
        relation_type="MODIFIES",
        extractor_pass="relation_extraction",
        priority=50,
        confidence=0.9,
    ),
    "IMPORTS": RelationRule(
        rule_id="imports.module.symbol",
        relation_type="IMPORTS",
        extractor_pass="import_resolution",
        priority=60,
        confidence=0.98,
    ),
}


_SUPER_CALL_RULE = RelationRule(
    rule_id="calls.super.method",
    relation_type="CALLS",
    extractor_pass="relation_extraction",
    priority=25,
    confidence=0.94,
)


def resolve_rule(relation: RelationInfo) -> RelationRule:
    if relation.metadata.get("is_super_call"):
        return _SUPER_CALL_RULE
    return _DEFAULT_RULES.get(
        relation.relation_type,
        RelationRule(
            rule_id="relation.unknown",
            relation_type=relation.relation_type,
            extractor_pass="relation_extraction",
            priority=999,
            confidence=0.5,
        ),
    )
