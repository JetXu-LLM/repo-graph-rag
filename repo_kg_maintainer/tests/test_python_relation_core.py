from __future__ import annotations

from code_analyze.code_analyzer import EntityInfo, EntityReference, EntityType, RelationInfo, RelationType
from code_analyze.python_analyzer import PythonAnalyzer
from code_analyze.python_relation import PythonRelationExtractor


def _build_entities(file_to_code: dict[str, str]):
    analyzer = PythonAnalyzer()
    repo_entities = []
    for path, content in file_to_code.items():
        _, entities = analyzer.get_code_entities(content, language="python", file_path=path)
        repo_entities.extend(entities)
    return analyzer, repo_entities


def _relation_fingerprint(relation: RelationInfo) -> tuple[str, str, str, str, str]:
    return (
        relation.relation_type,
        relation.source.parent_name or "",
        relation.source.name,
        relation.target.parent_name or "",
        relation.target.name,
    )


def test_build_import_map_handles_relative_and_alias_imports() -> None:
    code = """
import pkg.module
import pandas as pd
from .sub.mod import Thing, Other as Alias
from datetime import datetime
"""
    analyzer = PythonAnalyzer()
    extractor = PythonRelationExtractor(analyzer.parser, repo_entities=[])
    tree = analyzer.parser_code(code)

    import_map = extractor._build_import_map(tree, code, "src/current/file.py")

    assert import_map["pkg"] == "pkg/module"
    assert import_map["pd"] == "pandas"
    assert import_map["Thing"] == "src/current/sub/mod/Thing"
    assert import_map["Alias"] == "src/current/sub/mod/Other"
    assert import_map["datetime"] == "datetime/datetime"


def test_track_assignments_captures_multiple_python_patterns() -> None:
    code = """
a = Factory()
b = c = Builder()
x, y = Alpha(), Beta()
if (z := Gamma()):
    pass
items = [Delta() for _ in range(5)]
value = (Epsilon())
res = Zeta() + 1
"""
    analyzer = PythonAnalyzer()
    extractor = PythonRelationExtractor(analyzer.parser, repo_entities=[])
    extractor.current_file = "pkg/sample.py"
    tree = analyzer.parser_code(code)

    extractor._track_assignments(tree, code)

    assert extractor.variable_types["pkg/sample.py"] == {
        "a": "Factory",
        "b": "Builder",
        "c": "Builder",
        "x": "Alpha",
        "y": "Beta",
        "z": "Gamma",
        "items": "Delta",
        "value": "Epsilon",
        "res": "Zeta",
    }


def test_track_function_params_and_return_types_with_complex_annotations() -> None:
    code = """
class C:
    def m(self, a: int, b: list[str]):
        return b

    @classmethod
    def make(cls, dep: "Worker") -> "C":
        return cls()

async def afunc(x: dict[str, int]) -> list[str]:
    return []
"""
    analyzer = PythonAnalyzer()
    extractor = PythonRelationExtractor(analyzer.parser, repo_entities=[])
    extractor.current_file = "pkg/types.py"
    extractor.param_types["pkg/types.py"] = {}
    tree = analyzer.parser_code(code)

    extractor._track_function_params(tree, code)
    extractor._track_return_types(tree, code)

    assert extractor.param_types["pkg/types.py"] == {
        "C.m:a": "int",
        "C.m:b": "list[str]",
        "C.make:cls": "C",
        "C.make:dep": '"Worker"',
        "afunc:x": "dict[str, int]",
    }
    assert extractor.return_types["C.make"] == '"C"'
    assert extractor.return_types["afunc"] == "list[str]"


def test_create_entity_reference_resolves_self_and_variable_type_inference() -> None:
    analyzer, repo_entities = _build_entities(
        {
            "pkg/models.py": """
class Worker:
    def work(self):
        return 1
""",
            "pkg/service.py": """
class Service:
    def helper(self):
        return 1

    def execute(self, dep):
        self.helper()
        dep.work()
""",
        }
    )
    extractor = PythonRelationExtractor(analyzer.parser, repo_entities)
    extractor.current_scope = "Service"
    extractor.current_function = "execute"
    extractor.current_file = "pkg/service.py"
    extractor.variable_types = {"pkg/service.py": {"dep": "Worker"}}

    helper_ref = extractor._create_entity_reference("self.helper", {}, "pkg/service.py")
    worker_ref = extractor._create_entity_reference("dep", {}, "pkg/service.py")
    work_ref = extractor._create_entity_reference("dep.work", {}, "pkg/service.py")

    assert helper_ref is not None
    assert helper_ref.name == "helper"
    assert helper_ref.parent_name == "Service"

    assert worker_ref is not None
    assert worker_ref.entity_type == EntityType.CLASS.value
    assert worker_ref.name == "Worker"

    assert work_ref is not None
    assert work_ref.entity_type == EntityType.METHOD.value
    assert work_ref.parent_name == "Worker"
    assert work_ref.name == "work"


def test_extract_relations_covers_inheritance_calls_instantiation_and_param_usage() -> None:
    code = """
class Base:
    def ping(self):
        return 1


class Child(Base):
    def __init__(self):
        self.worker = Worker()

    def run(self, dep: Worker) -> Worker:
        obj = Worker()
        obj.work()
        self.helper()
        dep.work()
        return obj

    def helper(self):
        super().ping()


class Worker:
    def work(self):
        return self


def global_func():
    local = Worker()
    local.work()
"""
    analyzer, repo_entities = _build_entities({"pkg/sample.py": code})
    extractor = PythonRelationExtractor(analyzer.parser, repo_entities)
    tree = analyzer.parser_code(code)

    relations = extractor.extract_relations(tree, code, "pkg/sample.py")
    fingerprints = {_relation_fingerprint(relation) for relation in relations}

    assert ("INHERITS", "", "Child", "", "Base") in fingerprints
    assert ("INSTANTIATES", "Child", "run", "", "Worker") in fingerprints
    assert ("CALLS", "Child", "run", "Worker", "work") in fingerprints
    assert ("CALLS", "Child", "helper", "Base", "ping") in fingerprints
    assert extractor.param_types["pkg/sample.py"]["Child.run:dep"] == "Worker"

    super_rel = next(
        relation
        for relation in relations
        if relation.relation_type == RelationType.CALLS.value
        and relation.source.name == "helper"
        and relation.target.name == "ping"
    )
    assert super_rel.metadata["is_super_call"] is True


def test_extract_relations_resolves_import_alias_method_calls() -> None:
    analyzer, repo_entities = _build_entities(
        {
            "pkg/base.py": """
class External:
    def run(self):
        return 1
""",
            "pkg/current.py": """
from pkg.base import External as Ext


class Local:
    def execute(self):
        dep = Ext()
        dep.run()
""",
        }
    )
    extractor = PythonRelationExtractor(analyzer.parser, repo_entities)
    source = """
from pkg.base import External as Ext


class Local:
    def execute(self):
        dep = Ext()
        dep.run()
"""
    tree = analyzer.parser_code(source)

    relations = extractor.extract_relations(tree, source, "pkg/current.py")

    call_edges = {
        (relation.source.name, relation.source.parent_name, relation.target.name, relation.target.parent_name)
        for relation in relations
        if relation.relation_type == RelationType.CALLS.value
    }
    assert ("execute", "Local", "run", "External") in call_edges


def test_post_process_relations_prefers_instantiates_over_calls() -> None:
    extractor = PythonRelationExtractor(PythonAnalyzer().parser, repo_entities=[])

    source = EntityReference(name="build", key="Method/pkg/a.py/Factory/build", entity_type=EntityType.METHOD.value)
    target = EntityReference(name="Worker", key="Class/pkg/a.py/Worker", entity_type=EntityType.CLASS.value)

    calls = RelationInfo(
        source=source,
        target=target,
        relation_type=RelationType.CALLS.value,
        source_location=(1, 1),
        target_location=(1, 10),
    )
    instantiates = RelationInfo(
        source=source,
        target=target,
        relation_type=RelationType.INSTANTIATES.value,
        source_location=(1, 1),
        target_location=(1, 10),
    )

    optimized = extractor._post_process_relations([calls, instantiates])

    assert len(optimized) == 1
    assert optimized[0].relation_type == RelationType.INSTANTIATES.value


def test_is_valid_relation_rejects_self_reference_and_unknown_entities() -> None:
    analyzer, repo_entities = _build_entities(
        {
            "pkg/mod.py": """
class A:
    def call(self):
        return 1
"""
        }
    )
    extractor = PythonRelationExtractor(analyzer.parser, repo_entities)
    method = next(entity for entity in repo_entities if entity.entity_type == EntityType.METHOD.value)
    method_ref = extractor._entity_to_reference(method, "pkg/mod.py")

    self_relation = RelationInfo(
        source=method_ref,
        target=method_ref,
        relation_type=RelationType.CALLS.value,
        source_location=(1, 1),
        target_location=(1, 1),
    )
    unknown_relation = RelationInfo(
        source=method_ref,
        target=EntityReference(name="Missing", key="Method/pkg/mod.py/A/missing", entity_type=EntityType.METHOD.value),
        relation_type=RelationType.CALLS.value,
        source_location=(1, 1),
        target_location=(1, 1),
    )

    assert extractor._is_valid_relation(self_relation) is False
    assert extractor._is_valid_relation(unknown_relation) is False
