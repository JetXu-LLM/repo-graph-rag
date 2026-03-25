from __future__ import annotations

from code_analyze.code_analyzer import EntityReference, EntityType, RelationInfo, RelationType
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
        context.relations.extend(self._build_import_relations(context))
        return context

    def _build_import_relations(self, context: AnalyzerPassContext) -> list[RelationInfo]:
        relations: list[RelationInfo] = []
        import_locations = self._build_import_locations(context)
        source = EntityReference(
            name="<file>",
            key=self._file_reference_key(context.file_path),
            entity_type=EntityType.FILE.value,
            module_path=context.file_path,
            is_local=True,
        )
        seen_targets: set[str] = set()

        for imported_name in sorted(context.import_map):
            target = self._extractor._create_entity_reference(
                imported_name,
                context.import_map,
                context.file_path,
            )
            if target is None or target.key in seen_targets:
                continue

            seen_targets.add(target.key)
            relations.append(
                RelationInfo(
                    source=source,
                    target=target,
                    relation_type=RelationType.IMPORTS.value,
                    source_location=import_locations.get(imported_name, (0, 0)),
                    target_location=(0, 0),
                    metadata={"import_symbol": imported_name},
                )
            )

        return relations

    def _build_import_locations(self, context: AnalyzerPassContext) -> dict[str, tuple[int, int]]:
        locations: dict[str, tuple[int, int]] = {}

        def point(node) -> tuple[int, int]:
            line, column = node.start_point
            return (line + 1, column + 1)

        def process_import_statement(node) -> None:
            for child in node.children:
                if child.type == "dotted_name":
                    module_path = self._extractor._get_node_text(child, context.content)
                    module_parts = module_path.split(".")
                    locations.setdefault(module_parts[0], point(child))
                elif child.type == "aliased_import":
                    alias_node = child.child_by_field_name("alias")
                    if alias_node is not None:
                        alias = self._extractor._get_node_text(alias_node, context.content)
                        locations.setdefault(alias, point(alias_node))

        def process_import_from(node) -> None:
            for child in node.children:
                if child.type == "dotted_name":
                    name = self._extractor._get_node_text(child, context.content)
                    locations.setdefault(name, point(child))
                elif child.type == "aliased_import":
                    alias_node = child.child_by_field_name("alias")
                    if alias_node is not None:
                        alias = self._extractor._get_node_text(alias_node, context.content)
                        locations.setdefault(alias, point(alias_node))
                elif child.type == "identifier" and child.text:
                    name = self._extractor._get_node_text(child, context.content)
                    if name not in {"from", "import", "as"}:
                        locations.setdefault(name, point(child))

        def traverse(node) -> None:
            if node.type == "import_statement":
                process_import_statement(node)
            elif node.type == "import_from_statement":
                process_import_from(node)
            else:
                for child in node.children:
                    traverse(child)

        traverse(context.tree.root_node)
        return locations

    @staticmethod
    def _file_reference_key(file_path: str) -> str:
        return f"{EntityType.FILE.value}/{file_path}/<file>"
