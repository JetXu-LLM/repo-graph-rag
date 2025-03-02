from typing import Dict, List, Any, Optional, Union
from pathlib import Path
import tree_sitter
from tree_sitter import Language, Parser
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjs
import tree_sitter_java as tsjava
from dataclasses import dataclass
from enum import Enum
import logging
import hashlib
from datetime import datetime
import os
import re
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from llama_github.data_retrieval.github_entities import Repository
import json

class EntityType(Enum):
    """Core entity types as defined in the knowledge graph schema"""
    REPOSITORY = "Repository"
    MODULE = "Module"
    FILE = "File"
    CLASS = "Class"
    METHOD = "Method"
    INTERFACE = "Interface"
    VARIABLE = "Variable"
    DOCUMENT = "Document"

class RelationType(Enum):
    """Core relationship types as defined in the knowledge graph schema"""
    CONTAINS = "CONTAINS"
    DEPENDS_ON = "DEPENDS_ON"
    INHERITS = "INHERITS"
    DESCRIBES = "DESCRIBES"
    VERIFIES = "VERIFIES"

@dataclass
class AnalysisContext:
    """Context information for code analysis"""
    file_path: Path
    language: str
    content: str
    tree: Any

@dataclass
class EntityInfo:
    """Represents a code entity with its relationships"""
    entity_type: str
    name: str
    parent_id: Optional[str] = None
    id: Optional[str] = None
    content: Optional[str] = None
    description: Optional[str] = None
    complexity: Optional[int] = None
    relationships: List[Dict[str, Any]] = None

class CodeAnalyzer:
    """
    Advanced code analyzer using tree-sitter for extracting repository knowledge graph information.
    Supports multiple programming languages and follows the specified knowledge graph schema.
    """
    
    def __init__(self, repo: Repository, language_paths = None):
        """
        Initialize the code analyzer with language configurations.
        
        Args:
            language_paths (dict, optional): Custom language paths if needed
        """
        self.logger = logging.getLogger(__name__)
        self.parsers = {}
        self._init_languages(language_paths)
        self.repo = repo
        
        # File type to language mapping
        self.file_type_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.java': 'java',
            '.ts': 'typescript',
            '.go': 'go',
            '.rb': 'ruby',
            '.cpp': 'cpp',
            '.hpp': 'cpp',
            '.c': 'c',
            '.h': 'c'
        }

    def _init_languages(self, language_paths=None):
        """
        Initialize tree-sitter languages using direct package imports
        """
        try:
            # Create parser for Python
            PY_LANGUAGE = Language(tspython.language())
            self.parsers['python'] = Parser()
            self.parsers['python'].language = PY_LANGUAGE
            self.logger.info("Initialized parser for Python")

            # Optional: Initialize JavaScript parser
            try:
                js_language = Language(tsjs.language())
                self.parsers['javascript'] = Parser()
                self.parsers['javascript'].language = js_language
                self.logger.info("Initialized parser for JavaScript")
            except Exception as e:
                self.logger.warning(f"Failed to initialize JavaScript parser: {e}")

            # Optional: Initialize Java parser
            try:
                java_language = Language(tsjava.language())
                self.parsers['java'] = Parser()
                self.parsers['java'].language = java_language
                self.logger.info("Initialized parser for Java")
            except Exception as e:
                self.logger.warning(f"Failed to initialize Java parser: {e}")

        except Exception as e:
            self.logger.error(f"Failed to initialize languages: {e}", exc_info=True)
            self.parsers = {}

    @lru_cache(maxsize=1000)
    def get_file_language(self, file_path: Union[str, Path]) -> Optional[str]:
        """Determine the programming language from file extension"""
        ext = Path(file_path).suffix.lower()
        return self.file_type_map.get(ext)
    
    def tree_to_dict_with_options(self, node, source_code, options=None):
        """
        将 Tree-sitter 节点转换为可配置的字典结构
        
        options = {
            'include_position': bool,  # 是否包含位置信息
            'include_empty_text': bool,  # 是否包含空文本
            'max_depth': int,  # 最大深度限制
            'skip_types': set(),  # 要跳过的节点类型
        }
        """
        if options is None:
            options = {
                'include_position': False,
                'include_empty_text': False,
                'max_depth': None,
                'skip_types': set()
            }
        
        if options.get('max_depth') == 0:
            return None
        
        if node.type in options.get('skip_types', set()):
            return None
        
        text = source_code[node.start_byte:node.end_byte].strip()
        if not text and not options.get('include_empty_text'):
            text = None
        
        result = {
            'type': node.type,
            'text': text
        }
        
        if options.get('include_position'):
            result.update({
                'start_point': node.start_point,
                'end_point': node.end_point,
                'start_byte': node.start_byte,
                'end_byte': node.end_byte
            })
        
        if node.children:
            next_depth = None if options.get('max_depth') is None else options.get('max_depth') - 1
            options['max_depth'] = next_depth
            children = [
                self.tree_to_dict_with_options(child, source_code, options.copy())
                for child in node.children
            ]
            children = [c for c in children if c is not None]
            if children:
                result['children'] = children
        
        return result

    def analyze_file(self, file_path: str, sha: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyze a source code file and extract knowledge graph entities and relationships.
        
        Args:
            file_path: Path to the source code file
            
        Returns:
            Dictionary containing extracted entities and relationships
        """
        language = self.get_file_language(file_path)
        if not language or language not in self.parsers:
            self.logger.warning(f"Unsupported language for file: {file_path}")
            return {
                'file': {},
                'entities': [],
                'relationships': []
            }
            
        content = self.repo.get_file_content(file_path, sha)

        # Parse file
        tree = self.parsers[language].parse(content.encode('utf-8', errors='ignore'))

        options = {
            'include_position': True,  # 包含位置信息
            'include_empty_text': False,  # 不包含空文本
            'max_depth': 3,  # 最多显示3层
            'skip_types': {'comment'}  # 跳过注释节点
        }

        tree_dict = self.tree_to_dict_with_options(tree.root_node, content, options)
        print(json.dumps(tree_dict, indent=2, ensure_ascii=False))
        
        # Create analysis context
        context = AnalysisContext(
            file_path=file_path,
            language=language,
            content=content,
            tree=tree
        )

        # result = self._extract_entities_with_relationships(context)
        
        # Extract all information
        return {
            'entities': self._extract_entities(context),
            # 'relationships': self._extract_relationships(context)
            # 'entities': result['entities'],
            # 'relationships': result['relationships']
        }

    def _create_file_entity(self, context: AnalysisContext) -> Dict[str, Any]:
        """Create a File entity according to the schema"""
        return {
            'entity_type': EntityType.FILE.value,
            'file_path': str(context.file_path),
            # 'file_name': context.file_path.name,
            'file_type': context.language,
            'size': len(context.content),
            # 'last_modified': datetime.fromtimestamp(context.file_path.stat().st_mtime).isoformat(),
            'content_hash': hashlib.md5(context.content.encode()).hexdigest(),
            'description': self._extract_file_description(context),
            'content': context.content
        }

    # def _extract_entities(self, context: AnalysisContext) -> List[Dict[str, Any]]:
    #     """Extract all relevant entities from the code"""
    #     entities = []
        
    #     # Extract classes
    #     entities.extend(self._extract_classes(context))
        
    #     # Extract methods
    #     entities.extend(self._extract_methods(context))
        
    #     # # Extract interfaces
    #     # entities.extend(self._extract_interfaces(context))
        
    #     # # Extract variables
    #     # entities.extend(self._extract_variables(context))
        
    #     return entities

    def _extract_classes(self, context: AnalysisContext) -> List[Dict[str, Any]]:
        """Extract class entities"""
        classes = []
        class_nodes = self._find_nodes_by_type(context.tree.root_node, "class_definition")
        
        for node in class_nodes:
            class_info = {
                'entity_type': EntityType.CLASS.value,
                'class_name': self._get_node_identifier(node),
                'complexity': self._calculate_complexity(node),
                'description': self._extract_docstring(node),
                'definition': self._get_node_text(node),
                'content': self._get_node_text(node)
            }
            classes.append(class_info)
            
        return classes

    def _extract_methods(self, context: AnalysisContext) -> List[Dict[str, Any]]:
        """Extract method entities"""
        methods = []
        method_nodes = self._find_nodes_by_type(context.tree.root_node, "function_definition")
        
        for node in method_nodes:
            method_info = {
                'entity_type': EntityType.METHOD.value,
                'method_name': self._get_node_identifier(node),
                'description': self._extract_docstring(node),
                'complexity': self._calculate_complexity(node),
                'content': self._get_node_text(node)
            }
            methods.append(method_info)
            
        return methods

    def _extract_relationships(self, context: AnalysisContext) -> List[Dict[str, Any]]:
        """Extract relationships between entities"""
        relationships = []
        
        # Extract inheritance relationships
        inheritance_rels = self._extract_inheritance_relationships(context)
        relationships.extend(inheritance_rels)
        
        # Extract dependency relationships
        dependency_rels = self._extract_dependency_relationships(context)
        relationships.extend(dependency_rels)
        
        return relationships

    def _extract_inheritance_relationships(self, context: AnalysisContext) -> List[Dict[str, Any]]:
        """Extract class inheritance relationships"""
        relationships = []
        class_nodes = self._find_nodes_by_type(context.tree.root_node, "class_definition")
        
        for node in class_nodes:
            base_classes = self._get_base_classes(node)
            class_name = self._get_node_identifier(node)
            
            for base in base_classes:
                rel = {
                    'relationship_type': RelationType.INHERITS.value,
                    'source': class_name,
                    'target': base,
                    'inheritance_type': 'extends',
                    'visibility': 'public'
                }
                relationships.append(rel)
                
        return relationships

    def _extract_dependency_relationships(self, context: AnalysisContext) -> List[Dict[str, Any]]:
        """Extract dependency relationships"""
        relationships = []
        import_nodes = self._find_nodes_by_type(context.tree.root_node, "import_statement")
        
        for node in import_nodes:
            module_name = self._get_imported_module(node)
            if module_name:
                rel = {
                    'relationship_type': RelationType.DEPENDS_ON.value,
                    'source': str(context.file_path),
                    'target': module_name,
                    'dependency_type': 'import',
                    'is_direct': True,
                    'change_impact_score': 5  # Default medium impact
                }
                relationships.append(rel)
                
        return relationships

    def _calculate_complexity(self, node: tree_sitter.Node) -> int:
        """Calculate cyclomatic complexity"""
        complexity = 1  # Base complexity
        
        # Count decision points
        decision_types = [
            'if_statement', 'while_statement', 'for_statement',
            'case_statement', 'catch_clause', 'conditional_expression',
            'boolean_operator'
        ]
        
        for type_ in decision_types:
            complexity += len(self._find_nodes_by_type(node, type_))
            
        return complexity

    def _extract_docstring(self, node: tree_sitter.Node) -> str:
        """Extract documentation string from a node"""
        docstring = ""
        
        # Look for string literal immediately after node start
        for child in node.children:
            if child.type in ('string', 'string_literal', 'comment'):
                text = self._get_node_text(child)
                # Clean up the docstring
                text = re.sub(r'^["\']|["\']$', '', text)
                text = re.sub(r'^#\s*', '', text)
                docstring = text.strip()
                break
                
        return docstring

    def _get_node_identifier(self, node: tree_sitter.Node) -> Optional[str]:
        """Get identifier name from a node"""
        for child in node.children:
            if child.type == 'identifier':
                return self._get_node_text(child)
        return None

    def _get_node_text(self, node: tree_sitter.Node) -> str:
        """Get text content of a node"""
        if hasattr(node, 'text'):
            return node.text.decode('utf-8', errors='ignore')
        return ""

    def _find_nodes_by_type(self, node: tree_sitter.Node, node_type: str) -> List[tree_sitter.Node]:
        """Find all nodes of a specific type in the AST"""
        nodes = []
        if node.type == node_type:
            nodes.append(node)
        for child in node.children:
            nodes.extend(self._find_nodes_by_type(child, node_type))
        return nodes

    def _get_base_classes(self, class_node: tree_sitter.Node) -> List[str]:
        """Get base classes for a class definition"""
        bases = []
        # Implementation depends on language
        return bases

    def _get_imported_module(self, import_node: tree_sitter.Node) -> Optional[str]:
        """Get the name of an imported module"""
        # Implementation depends on language
        return None

    def _extract_file_description(self, context: AnalysisContext) -> str:
        """Extract file description from header comments"""
        description = ""
        root_node = context.tree.root_node
        
        # Look for initial comments
        for child in root_node.children:
            if child.type == 'comment':
                text = self._get_node_text(child)
                # Clean up comment markers
                text = re.sub(r'^[#/*\s]+|[*\/\s]+$', '', text)
                if text:
                    description += text + "\n"
            else:
                break
                
        return description.strip()

##############################################################################################################################

    def _extract_entities(self, context: AnalysisContext) -> List[Dict[str, Any]]:
        """Extract all relevant entities from the code"""
        entities = []
        
        # 首先添加文件实体
        file_entity = self._create_file_entity(context)
        entities.append(file_entity)
        
        # 根据语言提取特定实体
        if context.language == 'python':
            python_entities = self._extract_python_entities(context)
            if python_entities:  # 检查是否为None
                entities.extend(python_entities)
        elif context.language == 'java':
            entities.extend(self._extract_java_entities(context))
        elif context.language in ['javascript', 'typescript']:
            entities.extend(self._extract_js_ts_entities(context))
        elif context.language == 'go':
            entities.extend(self._extract_go_entities(context))
            
        return entities

    def _extract_python_entities(self, context: AnalysisContext) -> List[Dict[str, Any]]:
        """Extract Python-specific entities"""
        entities = []
        root_node = context.tree.root_node
        
        for node in root_node.children:
            if node.type == 'class_definition':
                class_entity = self._create_class_entity(node, context)
                if class_entity:
                    entities.append(class_entity)
            elif node.type == 'function_definition':
                method_entity = self._create_method_entity(node, context)
                if method_entity:
                    entities.append(method_entity)
            elif node.type == 'assignment':
                if not self._has_class_or_function_parent(node):
                    var_entity = self._create_variable_entity(node, context)
                    if var_entity:
                        entities.append(var_entity)
        
        return entities

    def _has_class_or_function_parent(self, node: tree_sitter.Node) -> bool:
        """Check if node has class or function parent"""
        current = node.parent
        while current:
            if current.type in ['class_definition', 'function_definition']:  # Python
                return True
            if current.type in ['class_declaration', 'method_declaration']:  # Java
                return True
            if current.type in ['class_declaration', 'method_definition']:  # JS/TS
                return True
            if current.type in ['struct_type', 'function_declaration']:     # Go
                return True
            current = current.parent
        return False

    def _create_class_entity(self, node: tree_sitter.Node, context: AnalysisContext) -> Dict[str, Any]:
        """Create class entity from node"""
        name = self._get_node_identifier(node)
        if not name:
            return None
            
        return {
            'entity_type': EntityType.CLASS.value,
            'name': name,
            'description': self._extract_docstring(node),
            'complexity': self._calculate_complexity(node),
            # 'methods': self._extract_class_methods(node, context),
            # 'attributes': self._extract_class_attributes(node, context),
            'base_classes': self._get_base_classes(node),
            'definition': self._get_node_text(node),
            'content': self._get_node_text(node)
        }

    def _create_method_entity(self, node: tree_sitter.Node, context: AnalysisContext) -> Dict[str, Any]:
        """Create method entity from node"""
        name = self._get_node_identifier(node)
        if not name:
            return None
            
        return {
            'entity_type': EntityType.METHOD.value,
            'name': name,
            'description': self._extract_docstring(node),
            'complexity': self._calculate_complexity(node),
            # 'parameters': self._extract_method_parameters(node),
            # 'return_type': self._extract_return_type(node),
            'definition': self._get_node_text(node),
            'content': self._get_node_text(node)
        }

    def _create_variable_entity(self, node: tree_sitter.Node, context: AnalysisContext) -> Dict[str, Any]:
        """Create variable entity from node"""
        name = self._get_variable_name(node)
        if not name:
            print(f"Warning: No variable name found in node: {node}")
            return None
        else:
            print("Variable name:", name)
            
        return {
            'entity_type': EntityType.VARIABLE.value,
            'name': name,
            'type': self._get_variable_type(node),
            'value': self._get_variable_value(node),
            'is_constant': self._is_constant_variable(node),
            'definition': self._get_node_text(node),
            'content': self._get_node_text(node)
        }

    def _get_variable_name(self, node: tree_sitter.Node) -> Optional[str]:
        """Extract variable name from assignment node"""
        # 对于Python的赋值语句
        if node.type == 'assignment':
            left_node = node.child_by_field_name('left')
            if left_node and left_node.type == 'identifier':
                return self._get_node_text(left_node)
        return None

    def _get_variable_type(self, node: tree_sitter.Node) -> Optional[str]:
        """Extract variable type from node"""
        # Python不强制类型声明，尝试从注释或类型提示中提取
        type_comment = None
        for child in node.children:
            if child.type == 'comment' and ':' in self._get_node_text(child):
                type_comment = self._get_node_text(child).split(':')[1].strip()
                break
        return type_comment

    def _get_variable_value(self, node: tree_sitter.Node) -> Optional[str]:
        """Extract variable value from assignment node"""
        if node.type == 'assignment':
            right_node = node.child_by_field_name('right')
            if right_node:
                return self._get_node_text(right_node)
        return None

    def _is_constant_variable(self, node: tree_sitter.Node) -> bool:
        """Check if variable is a constant"""
        name = self._get_variable_name(node)
        if name:
            # Python约定：全大写的变量名通常表示常量
            return name.isupper()
        return False

    def _extract_method_parameters(self, node: tree_sitter.Node) -> List[Dict[str, Any]]:
        """Extract method parameters"""
        parameters = []
        params_node = node.child_by_field_name('parameters')
        
        if params_node:
            for param in params_node.children:
                if param.type == 'identifier':
                    param_info = {
                        'name': self._get_node_text(param),
                        'type': self._get_parameter_type(param)
                    }
                    parameters.append(param_info)
                    
        return parameters

    def _get_parameter_type(self, node: tree_sitter.Node) -> Optional[str]:
        """Extract parameter type from type annotation or comment"""
        # 检查是否有类型注解
        next_sibling = node.next_sibling
        if next_sibling and next_sibling.type == 'type':
            return self._get_node_text(next_sibling)
        return None

    def _extract_return_type(self, node: tree_sitter.Node) -> Optional[str]:
        """Extract function return type"""
        # 检查是否有返回类型注解
        arrow_node = None
        for child in node.children:
            if child.type == '->':
                arrow_node = child
                break
                
        if arrow_node and arrow_node.next_sibling:
            return self._get_node_text(arrow_node.next_sibling)
        return None

    def _has_class_parent(self, node: tree_sitter.Node) -> bool:
        """Check if node has class parent"""
        current = node.parent
        while current:
            if current.type == 'class_definition':
                return True
            current = current.parent
        return False