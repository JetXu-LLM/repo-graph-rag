from __future__ import annotations

from code_analyze.python_analyzer import PythonAnalyzer

from v2.analyzer.context import AnalyzerPassContext


class SymbolTablePass:
    name = "symbol_table"

    def __init__(self, analyzer: PythonAnalyzer):
        self._analyzer = analyzer

    def run(self, context: AnalyzerPassContext) -> AnalyzerPassContext:
        file_entity, entities = self._analyzer.get_code_entities(
            content=context.content,
            language=context.language,
            file_path=context.file_path,
        )
        context.file_entity = file_entity
        context.entities = entities
        return context
