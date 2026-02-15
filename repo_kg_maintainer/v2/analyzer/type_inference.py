from __future__ import annotations

from code_analyze.python_relation import PythonRelationExtractor

from v2.analyzer.context import AnalyzerPassContext


class TypeInferencePass:
    name = "type_inference"

    def __init__(self, extractor: PythonRelationExtractor):
        self._extractor = extractor

    def run(self, context: AnalyzerPassContext) -> AnalyzerPassContext:
        if context.tree is None:
            raise ValueError("AST tree must exist before type inference")

        self._extractor.current_file = context.file_path
        self._extractor.variable_types.setdefault(context.file_path, {})
        self._extractor.param_types.setdefault(context.file_path, {})

        self._extractor._track_assignments(context.tree, context.content)
        self._extractor._track_function_params(context.tree, context.content)
        self._extractor._track_return_types(context.tree, context.content)

        context.variable_types = dict(self._extractor.variable_types.get(context.file_path, {}))
        context.param_types = dict(self._extractor.param_types.get(context.file_path, {}))
        context.return_types = dict(self._extractor.return_types)
        return context
