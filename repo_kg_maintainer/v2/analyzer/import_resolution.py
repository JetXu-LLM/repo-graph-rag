from __future__ import annotations

from code_analyze.python_relation import PythonRelationExtractor

from v2.analyzer.context import AnalyzerPassContext


class ImportResolutionPass:
    name = "import_resolution"

    def __init__(self, extractor: PythonRelationExtractor):
        self._extractor = extractor

    def run(self, context: AnalyzerPassContext) -> AnalyzerPassContext:
        if context.tree is None:
            raise ValueError("AST tree must exist before import resolution")
        context.import_map = self._extractor._build_import_map(
            context.tree,
            context.content,
            context.file_path,
        )
        return context
