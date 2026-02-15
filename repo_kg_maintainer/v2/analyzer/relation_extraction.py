from __future__ import annotations

from code_analyze.python_relation import PythonRelationExtractor

from v2.analyzer.context import AnalyzerPassContext


class RelationExtractionPass:
    name = "relation_extraction"

    def __init__(self, extractor: PythonRelationExtractor):
        self._extractor = extractor

    def run(self, context: AnalyzerPassContext) -> AnalyzerPassContext:
        if context.tree is None:
            raise ValueError("AST tree must exist before relation extraction")

        context.relations = self._extractor.extract_relations(
            context.tree,
            context.content,
            context.file_path,
        )
        context.variable_types = dict(self._extractor.variable_types.get(context.file_path, {}))
        context.param_types = dict(self._extractor.param_types.get(context.file_path, {}))
        context.return_types = dict(self._extractor.return_types)
        return context
