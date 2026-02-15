from typing import Dict, List, Any, Optional
import logging
import re
import tree_sitter
from tree_sitter import Language, Parser, Tree
import tree_sitter_python as tspython
from code_analyze.code_analyzer import EntityType, AnalysisContext, CodeAnalyzer, EntityInfo, FileInfo

class PythonAnalyzer:
    PYTHON_NODE_TYPE_TO_ENTITY_TYPE = {
        "class_definition": EntityType.CLASS.value,
        "function_definition": EntityType.METHOD.value,
    }

    def __init__(self):
        """
        Initialize tree-sitter languages using direct package imports.
        """
        self.logger = logging.getLogger(__name__)

        try:
            # Initialize Python parser
            PY_LANGUAGE = Language(tspython.language())
            self.parser = Parser()
            self.parser.language = PY_LANGUAGE
            self.logger.info("Initialized parser for Python")
        except Exception as e:
            self.logger.error(f"Failed to initialize Python parser: {e}", exc_info=True)

    def print_code_entities(self, tree, content: str):
        """
        Print the code entities in a tree-like structure
        """
        import json
        options = {
            'include_position': True,
            'include_empty_text': False,
            'max_depth': 10,
            'skip_types': {'comment'}
        }

        tree_dict = CodeAnalyzer.tree_to_dict_with_options(tree.root_node, content, options)
        print(json.dumps(tree_dict, indent=2, ensure_ascii=False))

    def parser_code(self, content: str) -> Tree:
        """
        Parse the given content using the tree-sitter parser.
        Handles non-ASCII characters by replacing them with ASCII placeholders
        to ensure proper parsing without affecting code structure.
        
        Args:
            content (str): Source code to parse
            
        Returns:
            Tree: The tree-sitter parse tree
        """
        # Skip processing if content is empty
        if not content:
            return self.parser.parse(content.encode("utf-8", errors="ignore"))
        
        # Replace non-ASCII characters with appropriate placeholders
        processed_content = ""
        for c in content:
            if ord(c) < 128:
                # ASCII character - keep as is
                processed_content += c
            else:
                # Non-ASCII character - replace based on character type
                if c.isalpha():
                    # For letters (identifiers, keywords), use 'x'
                    processed_content += 'x'
                elif c.isdigit():
                    # For digits, use '0'
                    processed_content += '0'
                elif c.isspace():
                    # Preserve whitespace as-is
                    processed_content += c
                else:
                    # For symbols and punctuation, use underscore
                    processed_content += '_'
        
        # Parse the processed content with tree-sitter
        tree = self.parser.parse(processed_content.encode("utf-8", errors="ignore"))
        
        return tree

    def get_code_entities(
        self, content: str, language: Optional[str] = None, file_path: Optional[str]="temp"
    ) -> tuple[FileInfo, List[EntityInfo]]:
        """
        Extract code entities from the given content.
        Returns a list of EntityInfo objects.
        """
        # Parse file
        tree = self.parser_code(content)

        # self.print_code_entities(tree, content)

        # Create analysis context
        context = AnalysisContext(
            file_path=file_path, language=language, content=content, tree=tree
        )
        return self._extract_entities(context)
    
    def _create_file_entity(self, context: AnalysisContext) -> FileInfo:
        """Create a File entity according to the schema"""
        return FileInfo(
            entity_type=EntityType.FILE.value,
            file_path=str(context.file_path),
            file_type=context.language,
            size=len(context.content),
            description=self._extract_file_description(context),
            content=context.content,
        )

    def _extract_entities(self, context: AnalysisContext) -> tuple[FileInfo, List[EntityInfo]]:
        """
        Extract all relevant entities from the code
        Returns a list of entity dictionaries
        """
        entities: List[EntityInfo] = []

        # Add file entity first
        file_entity = self._create_file_entity(context)

        # Extract language-specific entities
        python_entities = self._extract_python_entities(context)
        if python_entities:
            entities.extend(python_entities)

        return file_entity, entities
    
    def _extract_python_entities(
        self, context: AnalysisContext
    ) -> List[EntityInfo]:
        """
        Extract Python-specific entities using recursive traversal.
        """
        def traverse(node: tree_sitter.Node) -> List[EntityInfo]:
            ents: List[EntityInfo] = []

            # Process current node
            if node.type == "class_definition" or node.type == "function_definition":
                entity = self._create_code_entity(node, context.content)
                if entity:
                    entity.file_path = context.file_path
                    ents.append(entity)
            elif node.type in ["assignment", "type_alias_statement"]:
                # Check parent chain to ensure it's a file-level variable
                current = node.parent
                is_file_level = True
                while current:
                    if current.type in ["class_definition", "function_definition"]:
                        is_file_level = False
                        break
                    current = current.parent
                if is_file_level:
                    variable = self._create_variable_entity(node, context.content)
                    if variable:
                        variable.file_path = context.file_path
                        ents.append(variable)

            # Recursively process all child nodes
            for child in node.children:
                ents.extend(traverse(child))
            return ents

        return traverse(context.tree.root_node)
    
    def _create_code_entity(self, node: tree_sitter.Node, content: Optional[str] = None) -> Optional[EntityInfo]:
        """Create code entity (class/method) from AST node"""
        name = self._get_node_identifier(node)
        if not name:
            return None

        # Get entity parent name
        parent = node.parent
        parent_name = ""
        parent_type = ""
        while parent:
            if parent.type in ["class_definition", "function_definition"]:
                pname = self._get_node_identifier(parent)
                if pname:
                    parent_name = pname if parent_name == "" else pname + "/" + parent_name
                    if not parent_type:
                        parent_type = self.PYTHON_NODE_TYPE_TO_ENTITY_TYPE.get(parent.type, "Unknown")
            parent = parent.parent

        modifiers = self._get_decorators(node, content)
        is_exported = not name.startswith('_')

        return EntityInfo(
            entity_type=self.PYTHON_NODE_TYPE_TO_ENTITY_TYPE.get(node.type, "Unknown"),
            name=name,
            parent_name=parent_name,
            parent_type=parent_type,
            description=self._extract_docstring(node, content),
            complexity=self._calculate_complexity(node),
            content=self._get_node_text(node, content),
            is_exported=is_exported,
            modifiers=modifiers
        )

    def _create_variable_entity(self, node: tree_sitter.Node, content: Optional[str] = None) -> Optional[EntityInfo]:
        """Create variable entity from AST node"""
        name = self._get_variable_name(node)
        if not name:
            return None

        var_type = self._get_variable_type(node, content)
        var_value = self._get_variable_value(node, content)
        description = f"Type: {var_type if var_type else 'Unknown'}"
        if var_value:
            description += f"\nValue: {var_value}"

        modifiers = []
        if self._is_constant_variable(node):
            modifiers.append("constant")

        return EntityInfo(
            entity_type=EntityType.VARIABLE.value,
            name=name,
            description=description,
            complexity=1,
            content=self._get_node_text(node, content),
            is_exported=not name.startswith('_'),
            modifiers=modifiers
        )

    def _get_variable_name(self, node: tree_sitter.Node, content: Optional[str] = None) -> Optional[str]:
        """Extract variable name from assignment node"""
        if node.type == "assignment":
            left_node = node.child_by_field_name("left")
            if left_node and left_node.type == "identifier":
                return self._get_node_text(left_node, content)
        if node.type == "type_alias_statement":
            return self._get_node_text(node, content)
        return None

    def _get_variable_type(self, node: tree_sitter.Node, content: Optional[str] = None) -> Optional[str]:
        """Extract variable type from type hints or comments"""
        type_comment = None
        for child in node.children:
            if child.type == "comment" and ":" in self._get_node_text(child, content):
                type_comment = self._get_node_text(child, content).split(":")[1].strip()
                break
        return type_comment

    def _get_variable_value(self, node: tree_sitter.Node, content: Optional[str] = None) -> Optional[str]:
        """Extract variable value from assignment node"""
        if node.type == "assignment":
            right_node = node.child_by_field_name("right")
            if right_node:
                return self._get_node_text(right_node, content)
        return None

    def _is_constant_variable(self, node: tree_sitter.Node, content: Optional[str] = None) -> bool:
        """Check if variable follows constant naming convention (all uppercase)"""
        name = self._get_variable_name(node, content)
        if name:
            return name.isupper()
        return False

    def _calculate_complexity(self, node: tree_sitter.Node) -> int:
        """Calculate cyclomatic complexity of code block"""
        complexity = 1  # Base complexity

        # Count decision points
        decision_types = [
            "if_statement",
            "while_statement",
            "for_statement",
            "case_statement",
            "catch_clause",
            "conditional_expression",
            "boolean_operator",
        ]

        for type_ in decision_types:
            complexity += len(self._find_nodes_by_type(node, type_))

        return complexity

    def _extract_docstring(self, node: tree_sitter.Node, content: Optional[str] = None) -> str:
        """Extract documentation string from node"""
        docstring = ""

        # Look for direct string/comment children first
        for child in node.children:
            if child.type in ("string", "string_literal", "comment"):
                text = self._get_node_text(child, content)
                docstring = self._clean_docstring_text(text)
                if docstring:
                    return docstring

        # For Python class/function docstrings, inspect the first statement in the body block
        body = node.child_by_field_name("body")
        if not body:
            for child in node.children:
                if child.type == "block":
                    body = child
                    break

        if body:
            for child in body.children:
                if child.type == "expression_statement":
                    for grandchild in child.children:
                        if grandchild.type in ("string", "string_literal"):
                            text = self._get_node_text(grandchild, content)
                            return self._clean_docstring_text(text)
                elif child.type in ("string", "string_literal", "comment"):
                    text = self._get_node_text(child, content)
                    return self._clean_docstring_text(text)
                elif child.type in (":", ";"):
                    continue
                else:
                    # Docstring must be first logical statement.
                    break

        return docstring

    def _clean_docstring_text(self, text: str) -> str:
        """Normalize extracted docstring/comment text."""
        cleaned = text.strip()
        cleaned = re.sub(r"^#\s*", "", cleaned)
        cleaned = re.sub(r"^[rRuUbBfF]*('{3}|\"{3}|'|\")", "", cleaned)
        cleaned = re.sub(r"('{3}|\"{3}|'|\")$", "", cleaned)
        return cleaned.strip()

    def _get_node_identifier(self, node: tree_sitter.Node) -> Optional[str]:
        """Get identifier name from node"""
        for child in node.children:
            if child.type == "identifier":
                return self._get_node_text(child)
        return None

    def _get_node_text(self, node: tree_sitter.Node, content: Optional[str] = None) -> str:
        """
        Get text content of a node.
        
        Args:
            node (tree_sitter.Node): The node to extract text from
            content (str, optional): Original source code content. If provided, 
                                    text is extracted using byte positions.
                                    
        Returns:
            str: The text content of the node
        """
        if content is not None:
            # Extract text using byte positions from the original content
            return content[node.start_byte:node.end_byte]
        elif hasattr(node, "text") and node.text is not None:
            # Fall back to node.text if content is not provided
            return node.text.decode("utf-8", errors="ignore")
        else:
            # Return empty string if no text is available
            return ""

    def _find_nodes_by_type(
        self, node: tree_sitter.Node, node_type: str
    ) -> List[tree_sitter.Node]:
        """Find all nodes of a specific type in the AST"""
        nodes = []
        if node.type == node_type:
            nodes.append(node)
        for child in node.children:
            nodes.extend(self._find_nodes_by_type(child, node_type))
        return nodes

    def _extract_file_description(self, context: AnalysisContext) -> str:
        """Extract file description from header comments"""
        description = ""
        root_node = context.tree.root_node

        # Look for initial comments
        for child in root_node.children:
            if child.type == "comment":
                text = self._get_node_text(child, context.content)
                # Clean up comment markers
                text = re.sub(r"^[#/*\s]+|[*\/\s]+$", "", text)
                if text:
                    description += text + "\n"
            else:
                break

        return description.strip()

    def _get_decorators(self, node: tree_sitter.Node, content: Optional[str] = None) -> List[str]:
        """Extract decorators from a node"""
        decorators = []
        for child in node.children:
            if child.type == "decorator":
                decorator_text = self._get_node_text(child, content).lstrip('@')
                decorators.append(decorator_text)

        if not decorators and node.parent and node.parent.type == "decorated_definition":
            for child in node.parent.children:
                if child.type == "decorator":
                    decorator_text = self._get_node_text(child, content).lstrip('@')
                    decorators.append(decorator_text)
        return decorators
