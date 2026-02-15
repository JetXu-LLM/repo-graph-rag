from __future__ import annotations

from code_analyze.code_analyzer import EntityType
from code_analyze.python_analyzer import PythonAnalyzer


def _find_entity(entities, entity_type: str, name: str):
    for entity in entities:
        if entity.entity_type == entity_type and entity.name == name:
            return entity
    raise AssertionError(f"Entity not found: {entity_type} {name}")


def test_parser_code_handles_non_ascii_content() -> None:
    analyzer = PythonAnalyzer()
    tree = analyzer.parser_code("变量 = 1\n\ndef обработать():\n    return 变量\n")

    assert tree.root_node.type == "module"


def test_get_code_entities_extracts_file_metadata_and_symbols() -> None:
    code = """
# deterministic graph extraction
# repository fixture

CONSTANT_VALUE = 10
_private_flag = False

class Service:
    \"\"\"Service behavior\"\"\"

    @classmethod
    def build(cls, cfg):
        if cfg:
            return cls()
        return cls()

    class Nested:
        def run(self):
            return 1


def top_level(value):
    for i in range(2):
        if i and value:
            pass
    local_value = 1
    return local_value
"""
    analyzer = PythonAnalyzer()

    file_info, entities = analyzer.get_code_entities(code, language="python", file_path="pkg/service.py")

    assert file_info.entity_type == EntityType.FILE.value
    assert file_info.file_path == "pkg/service.py"
    assert file_info.description == "deterministic graph extraction\nrepository fixture"

    constant = _find_entity(entities, EntityType.VARIABLE.value, "CONSTANT_VALUE")
    private_flag = _find_entity(entities, EntityType.VARIABLE.value, "_private_flag")
    service = _find_entity(entities, EntityType.CLASS.value, "Service")
    build = _find_entity(entities, EntityType.METHOD.value, "build")
    nested = _find_entity(entities, EntityType.CLASS.value, "Nested")
    nested_run = _find_entity(entities, EntityType.METHOD.value, "run")
    top_level = _find_entity(entities, EntityType.METHOD.value, "top_level")

    assert constant.modifiers == ["constant"]
    assert constant.is_exported is True
    assert private_flag.is_exported is False

    assert service.description == "Service behavior"
    assert build.parent_name == "Service"
    assert build.parent_type == EntityType.CLASS.value
    assert "classmethod" in build.modifiers
    assert build.complexity > 1

    assert nested.parent_name == "Service"
    assert nested_run.parent_name == "Service/Nested"

    assert top_level.complexity == 4
    assert all(entity.name != "local_value" for entity in entities)


def test_create_code_entity_marks_private_methods_as_non_exported() -> None:
    code = """
class Thing:
    def _hidden(self):
        return 1
"""
    analyzer = PythonAnalyzer()

    _, entities = analyzer.get_code_entities(code, language="python", file_path="pkg/thing.py")

    hidden = _find_entity(entities, EntityType.METHOD.value, "_hidden")
    assert hidden.is_exported is False


def test_extract_docstring_from_function_body() -> None:
    code = """
def compute(value):
    \"\"\"Compute a deterministic value.\"\"\"
    return value
"""
    analyzer = PythonAnalyzer()

    _, entities = analyzer.get_code_entities(code, language="python", file_path="pkg/compute.py")

    compute = _find_entity(entities, EntityType.METHOD.value, "compute")
    assert compute.description == "Compute a deterministic value."


def test_file_level_assignment_detection_ignores_nested_scopes() -> None:
    code = """
GLOBAL_FLAG = True


def wrapper():
    inner_value = 1
    class Inner:
        inside = 2
"""
    analyzer = PythonAnalyzer()

    _, entities = analyzer.get_code_entities(code, language="python", file_path="pkg/flags.py")

    variable_names = {entity.name for entity in entities if entity.entity_type == EntityType.VARIABLE.value}
    assert variable_names == {"GLOBAL_FLAG"}
