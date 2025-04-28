from typing import Dict, List, Any, Optional, Union, Tuple
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
import logging
from functools import lru_cache
from llama_github.data_retrieval.github_entities import Repository

class EntityType(Enum):
    """Core entity types as defined in the knowledge graph schema"""
    REPOSITORY = "Repository"
    MODULE = "Module" # folder or package
    FILE = "File"
    CLASS = "Class"
    METHOD = "Method"
    INTERFACE = "Interface"
    VARIABLE = "Variable"
    DOCUMENT = "Document"
    ENUM = "Enum"

class RelationType(Enum):
    """Types of relationships between code entities"""
    INHERITS = "INHERITS"
    CALLS = "CALLS"
    CONTAINS = "CONTAINS"
    DECORATES = "DECORATES"
    REFERENCES = "REFERENCES"
    IMPORTS = "IMPORTS"
    USES = "USES"
    MODIFIES = "MODIFIES"
    INSTANTIATES = "INSTANTIATES"

@dataclass
class AnalysisContext:
    """Context information for code analysis"""
    file_path: Path
    language: str
    content: str
    tree: Any

@dataclass
class EntityInfo:
    """Represents a code entity with its relationships and metadata
    
    Attributes:
        entity_type: Type of the entity (e.g., 'Class', 'Method', 'Function', etc.)
        name: Name of the entity
        parent_name: Name of the parent entity (empty string if no parent)
        parent_type: Type of the parent entity (empty string if no parent)
        description: Documentation or description of the entity
        complexity: Cyclomatic complexity measure
        content: The entity's complete content/implementation
        is_exported: Whether the entity is publicly exported/accessible
        modifiers: List of modifiers (e.g., 'static', 'async', 'private', etc.)
    """
    entity_type: str
    name: str
    parent_name: str = ""
    parent_type: str = ""
    file_path: str = ""
    description: str = ""
    complexity: int = 1
    content: str = ""
    is_exported: bool = False
    modifiers: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Validate the entity info after initialization"""
        if not self.name:
            raise ValueError("Entity name cannot be empty")
        if not self.entity_type:
            raise ValueError("Entity type cannot be empty")
        
@dataclass
class FileInfo:
    """Represents a file with its entities and relationships
    Attributes:
        file_path: Path to the file
        language: Programming language of the file
        content: Content of the file
        tree: Parsed tree of the file
        entities: List of entities in the file
        relationships: List of relationships in the file
    """
    entity_type: str
    file_path: str
    file_type: str
    content: str
    size: int = 0
    description: str = ""
    content: str

@dataclass
class EntityReference:
    """Reference to a code entity with both name and key"""
    name: str
    key: str
    entity_type: Optional[str] = None
    parent_name: Optional[str] = None
    module_path: Optional[str] = None
    is_local: bool = False

@dataclass
class RelationInfo:
    """Information about a relationship between two entities"""
    source: EntityReference
    target: EntityReference
    relation_type: RelationType
    source_location: Tuple[int, int]
    target_location: Tuple[int, int]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class RelationKey:
    """Unique key for a relation to prevent duplicates"""
    source_key: str
    target_key: str
    relation_type: RelationType

    def __hash__(self):
        return hash((self.source_key, self.target_key, self.relation_type))

    def __eq__(self, other):
        return (self.source_key == other.source_key and
                self.target_key == other.target_key and
                self.relation_type == other.relation_type)

class CodeAnalyzer:
    """
    Advanced code analyzer using tree-sitter for extracting repository knowledge graph information.
    Supports multiple programming languages and follows the specified knowledge graph schema.
    """

    # Class-level constant for supported file extensions and their corresponding languages
    # This is defined as a class variable since it's shared across all instances
    # and represents the static capability of the analyzer
    SUPPORTED_EXTENSIONS = {
        "py": "python",
        "js": "javascript",
        "jsx": "javascript",
        "ts": "typescript",
        "tsx": "tsx",
        "java": "java",
        # "go": "go",
        # "html": "html",
        # "htm": "html",
    }

    def __init__(self, repo: Repository, language_paths=None):
        """
        Initialize the code analyzer with language configurations.

        Args:
            language_paths (dict, optional): Custom language paths if needed
        """
        self.logger = logging.getLogger(__name__)
        self.repo = repo
        # Instance-specific supported extensions can be initialized here if needed
        # For example, if we want to allow instance-specific customization
        self.supported_extensions = self.SUPPORTED_EXTENSIONS.copy()

        # Map file extensions to languages
        self.file_type_map = {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".java": "java",
            ".ts": "typescript",
            ".tsx": "tsx",
            ".go": "go",
            ".rb": "ruby",
            ".cpp": "cpp",
            ".hpp": "cpp",
            ".c": "c",
            ".h": "c",
        }

    @classmethod
    def is_supported_extension(cls, extension: str) -> bool:
        """
        Check if a file extension is supported by the analyzer.

        Args:
            extension (str): The file extension to check (without the dot)

        Returns:
            bool: True if the extension is supported, False otherwise
        """
        return extension.lower() in cls.SUPPORTED_EXTENSIONS

    @classmethod
    def get_language_for_extension(cls, extension: str) -> Optional[str]:
        """
        Get the programming language for a given file extension.

        Args:
            extension (str): The file extension (without the dot)

        Returns:
            Optional[str]: The programming language name or None if not supported
        """
        return cls.SUPPORTED_EXTENSIONS.get(extension.lower())

    @lru_cache(maxsize=1000)
    def get_file_language(self, file_path: Union[str, Path]) -> Optional[str]:
        """Determine the programming language from file extension"""
        ext = Path(file_path).suffix.lower()
        return self.file_type_map.get(ext)
    
    @classmethod
    def tree_to_dict_with_options(cls, node, source_code, options=None):
        """
        Convert Tree-sitter node to configurable dictionary structure

        options = {
            'include_position': bool,  # Whether to include position information
            'include_empty_text': bool,  # Whether to include empty text
            'max_depth': int,  # Maximum depth limit
            'skip_types': set(),  # Node types to skip
        }
        """
        if options is None:
            options = {
                "include_position": False,
                "include_empty_text": False,
                "max_depth": None,
                "skip_types": set(),
            }

        if options.get("max_depth") == 0:
            return None

        if node.type in options.get("skip_types", set()):
            return None

        text = source_code[node.start_byte : node.end_byte].strip()
        if not text and not options.get("include_empty_text"):
            text = None

        result = {"type": node.type, "text": text}

        if options.get("include_position"):
            result.update(
                {
                    "start_point": node.start_point,
                    "end_point": node.end_point,
                    "start_byte": node.start_byte,
                    "end_byte": node.end_byte,
                }
            )

        if node.children:
            next_depth = (
                None
                if options.get("max_depth") is None
                else options.get("max_depth") - 1
            )
            options["max_depth"] = next_depth
            children = [
                cls.tree_to_dict_with_options(child, source_code, options.copy())
                for child in node.children
            ]
            children = [c for c in children if c is not None]
            if children:
                result["children"] = children

        return result

    def get_file_entities(
        self, file_path: str, sha: Optional[str] = None
    ) -> tuple[FileInfo, List[EntityInfo]]:
        """
        Analyze a source code file and extract knowledge graph entities

        Args:
            file_path: Path to the source code file
            sha: Optional SHA for version control

        Returns:
            Dictionary containing extracted entities
        """
        language = self.get_file_language(file_path)
        if not language:
            self.logger.warning(f"Unsupported language for file: {file_path}")
            return {"file": {}, "entities": [], "relationships": []}

        content = self.repo.get_file_content(file_path, sha)

        if language.lower() == "python":
            from code_analyze.python_analyzer import PythonAnalyzer
            python_anlyzer = PythonAnalyzer()
            return python_anlyzer.get_code_entities(content=content, language=language, file_path=file_path)
        elif language.lower() == "java":
            from code_analyze.java_analyzer import JavaAnalyzer
            java_anlyzer = JavaAnalyzer()
            return java_anlyzer.get_code_entities(content=content, language=language, file_path=file_path)
        elif language.lower() == "javascript" or language.lower() == "typescript" or language.lower() == "tsx":
            from code_analyze.jsts_analyzer import JstsAnalyzer
            jsts_anlyzer = JstsAnalyzer()
            return jsts_anlyzer.get_code_entities(content=content, language=language, file_path=file_path)

    def get_file_relations(
        self, file_path: str, sha: Optional[str] = None, repo_entities: Optional[List[EntityInfo]] = None
    ) -> List[RelationInfo]:
        """
        Analyze a source code file and extract knowledge graph relationships.

        Args:
            file_path: Path to the source code file
            sha: Optional SHA for version control

        Returns:
            Dictionary containing extracted relationships
        """
        language = self.get_file_language(file_path)
        if not language:
            self.logger.warning(f"Unsupported language for file: {file_path}")
            return {"file": {}, "entities": [], "relationships": []}

        content = self.repo.get_file_content(file_path, sha)

        if language.lower() == "python":
            from code_analyze.python_analyzer import PythonAnalyzer
            from code_analyze.python_relation import PythonRelationExtractor
            python_anlyzer = PythonAnalyzer()
            tree = python_anlyzer.parser_code(content)
            extractor = PythonRelationExtractor(python_anlyzer.parser, repo_entities=repo_entities)
            relations = extractor.extract_relations(tree, content, file_path)
            return relations
        # elif language.lower() == "java":
        #     from code_analyze.java_analyzer import JavaAnalyzer
        #     java_anlyzer = JavaAnalyzer()
        #     return java_anlyzer.get_code_entities(content=content, language=language, file_path=file_path)
        # elif language.lower() == "javascript" or language.lower() == "typescript" or language.lower() == "tsx":
        #     from code_analyze.jsts_analyzer import JstsAnalyzer
        #     jsts_anlyzer = JstsAnalyzer()
        #     return jsts_anlyzer.get_code_entities(content=content, language=language, file_path=file_path)
    
    def get_code_entities(
        self, code_content: str, language: str
    ) -> tuple[FileInfo, List[EntityInfo]]:
        """
        Analyze source code and extract knowledge graph entities and relationships.

        Args:
            file_path: Path to the source code file
            sha: Optional SHA for version control

        Returns:
            Dictionary containing extracted entities and relationships
        """
        if not language:
            self.logger.warning(f"Unsupported language: {language}")
            return {"file": {}, "entities": [], "relationships": []}

        content = code_content

        if language.lower() == "python":
            from code_analyze.python_analyzer import PythonAnalyzer
            python_anlyzer = PythonAnalyzer()
            return python_anlyzer.get_code_entities(content=content, language=language)
        elif language.lower() == "java":
            from code_analyze.java_analyzer import JavaAnalyzer
            java_anlyzer = JavaAnalyzer()
            return java_anlyzer.get_code_entities(content=content, language=language)
        elif language.lower() == "javascript" or language.lower() == "typescript" or language.lower() == "tsx":
            from code_analyze.jsts_analyzer import JstsAnalyzer
            jsts_anlyzer = JstsAnalyzer()
            return jsts_anlyzer.get_code_entities(content=content, language=language)
    