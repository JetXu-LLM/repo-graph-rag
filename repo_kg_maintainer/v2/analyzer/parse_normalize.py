from __future__ import annotations

from code_analyze.python_analyzer import PythonAnalyzer

from v2.analyzer.context import AnalyzerPassContext


class ParseNormalizePass:
    name = "parse_normalize"

    def __init__(self, analyzer: PythonAnalyzer):
        self._analyzer = analyzer

    def run(self, context: AnalyzerPassContext) -> AnalyzerPassContext:
        normalized = context.content.replace("\r\n", "\n").replace("\r", "\n")
        if normalized.endswith("\n") is False:
            normalized = f"{normalized}\n"
        context.content = normalized
        context.tree = self._analyzer.parser_code(normalized)
        return context
