from typing import Dict, List, Any, Optional
import tree_sitter
from tree_sitter import Language, Parser
import tree_sitter_java as tsjava
import logging
import re
from code_analyze.code_analyzer import EntityType, AnalysisContext, CodeAnalyzer, EntityInfo, FileInfo

class JavaAnalyzer:
    """Analyzer for Java source code using tree-sitter"""
    
    # Map node types to entity types
    JAVA_NODE_TYPE_TO_ENTITY_TYPE = {
        "class_declaration": EntityType.CLASS.value,
        "interface_declaration": EntityType.INTERFACE.value,
        "enum_declaration": EntityType.ENUM.value,
        "record_declaration": EntityType.CLASS.value,
        "annotation_type_declaration": EntityType.INTERFACE.value,
        "method_declaration": EntityType.METHOD.value,
    }

    def __init__(self):
        """Initialize tree-sitter Java parser"""
        self.logger = logging.getLogger(__name__)

        try:
            JAVA_LANGUAGE = Language(tsjava.language())
            self.parser = Parser()
            self.parser.language = JAVA_LANGUAGE
            self.logger.info("Initialized parser for Java")
        except Exception as e:
            self.logger.error(f"Failed to initialize Java parser: {e}", exc_info=True)

    def print_code_entities(self, tree, content: str):
        """Print the code entities in a tree-like structure"""
        import json
        options = {
            'include_position': True,
            'include_empty_text': False,
            'max_depth': 10,
            'skip_types': {'comment'}
        }

        tree_dict = CodeAnalyzer.tree_to_dict_with_options(tree.root_node, content, options)
        print(json.dumps(tree_dict, indent=2, ensure_ascii=False))

    def get_code_entities(
        self, content: str, language: Optional[str] = None, file_path: Optional[str]="temp"
    ) -> tuple[FileInfo, List[EntityInfo]]:
        """Extract code entities from Java content"""
        tree = self.parser.parse(content.encode("utf-8", errors="ignore"))

        # self.print_code_entities(tree, content)

        context = AnalysisContext(
            file_path=file_path, language=language, content=content, tree=tree
        )
        return self._extract_entities(context)

    def _extract_entities(self, context: AnalysisContext) -> tuple[FileInfo, List[EntityInfo]]:
        """Extract all entities from the Java code"""
        file_entity = self._create_file_entity(context)
        java_entities = self._extract_java_entities(context)
        return file_entity, java_entities
    
    def is_top_level(self, node: tree_sitter.Node) -> bool:
        """Check if node is at top level (not inside class or method)"""
        current = node.parent
        while current:
            if current.type in ["class_declaration", "method_declaration"]:
                return False
            current = current.parent
        return True

    def _extract_java_entities(self, context: AnalysisContext) -> List[EntityInfo]:
        """
        Extract Java-specific entities using recursive traversal.
        For class and method declarations, process recursively.
        For interface and enum declarations, only process at file level.
        """
        def traverse(node: tree_sitter.Node) -> List[EntityInfo]:
            entities = []

            # Process current node
            if node.type in self.JAVA_NODE_TYPE_TO_ENTITY_TYPE:
                # For interface and enum declarations, only process at top level
                if node.type in ["interface_declaration", "enum_declaration", 
                            "annotation_type_declaration"]:
                    if self.is_top_level(node):
                        entity = self._create_java_entity(node)
                        if entity:
                            entities.append(entity)
                # For class and method declarations, process at all levels
                else:
                    entity = self._create_java_entity(node)
                    if entity:
                        entities.append(entity)

            # Recursively process child nodes
            for child in node.children:
                entities.extend(traverse(child))

            return entities

        return traverse(context.tree.root_node)

    def _create_java_entity(self, node: tree_sitter.Node) -> Optional[EntityInfo]:
        """Create entity for Java declarations"""
        name = self._get_java_name(node)
        if not name:
            return None

        # Get modifiers
        modifiers = self._get_java_modifiers(node)

        # Get parent information
        parent_name, parent_type = self._get_parent_info(node)
        
        # Build description including type-specific information
        description = self._extract_docstring(node)
        if node.type in ["class_declaration", "record_declaration"]:
            superclass = self._get_java_superclass(node)
            if superclass:
                description += f"\nSuperclass: {superclass}"
            interfaces = self._get_java_interfaces(node)
            if interfaces:
                description += f"\nImplements: {', '.join(interfaces)}"
        elif node.type == "method_declaration":
            return_type = self._get_java_return_type(node)
            parameters = self._get_java_parameters(node)
            if return_type:
                description += f"\nReturn Type: {return_type}"
            if parameters:
                params_str = ", ".join([f"{p['type']} {p['name']}" for p in parameters])
                description += f"\nParameters: {params_str}"

        return EntityInfo(
            entity_type=self.JAVA_NODE_TYPE_TO_ENTITY_TYPE.get(node.type, "Unknown"),
            name=name,
            parent_name=parent_name,
            parent_type=parent_type,
            description=description.strip(),
            complexity=self._calculate_complexity(node),
            content=self._get_node_text(node),
            is_exported="public" in modifiers,
            modifiers=modifiers
        )

    def _get_java_name(self, node: tree_sitter.Node) -> Optional[str]:
        """Get name from Java node"""
        name_node = node.child_by_field_name("name")
        if name_node:
            return self._get_node_text(name_node)
        return None

    def _get_java_modifiers(self, node: tree_sitter.Node) -> List[str]:
        """Extract Java modifiers from node's direct children"""
        modifiers = []
        
        # Check modifiers node first
        modifiers_node = next((child for child in node.children if child.type == "modifiers"), None)
        
        if modifiers_node:
            for child in modifiers_node.children:
                if child.type in ["public", "private", "protected", "static", "final", 
                                "abstract", "native", "synchronized"]:
                    modifiers.append(self._get_node_text(child))
                elif child.type in ["annotation", "marker_annotation"]:
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        modifiers.append(f"@{self._get_node_text(name_node)}")
        
        return modifiers

    def _get_node_text(self, node: tree_sitter.Node) -> str:
        """Get text content of node, handling None case"""
        if node and hasattr(node, "text"):
            text = node.text.decode("utf-8", errors="ignore") if isinstance(node.text, bytes) else node.text
            return text.strip()
        return ""

    def _get_parent_info(self, node: tree_sitter.Node) -> tuple[str, str]:
        """Get parent name and type for Java node"""
        parent = node.parent
        parent_name = ""
        parent_type = ""
        
        while parent:
            if parent.type in self.JAVA_NODE_TYPE_TO_ENTITY_TYPE:
                name = self._get_java_name(parent)
                if name:
                    parent_name = name if parent_name == "" else name + "/" + parent_name
                    if parent_type == "":
                        parent_type = self.JAVA_NODE_TYPE_TO_ENTITY_TYPE.get(parent.type, "Unknown")
            parent = parent.parent
            
        return parent_name, parent_type

    def _get_java_return_type(self, node: tree_sitter.Node) -> Optional[str]:
        """Get method return type"""
        type_node = node.child_by_field_name("type")
        if type_node:
            return self._get_node_text(type_node)
        return None

    def _get_java_parameters(self, node: tree_sitter.Node) -> List[Dict[str, str]]:
        """Get method parameters"""
        parameters = []
        params_node = node.child_by_field_name("parameters")
        if params_node:
            for param in params_node.children:
                if param.type == "formal_parameter":
                    param_type = self._get_node_text(param.child_by_field_name("type"))
                    param_name = self._get_node_text(param.child_by_field_name("name"))
                    if param_type and param_name:
                        parameters.append({
                            "type": param_type,
                            "name": param_name
                        })
        return parameters

    def _get_java_superclass(self, node: tree_sitter.Node) -> Optional[str]:
        """Get superclass name if exists"""
        superclass_node = node.child_by_field_name("superclass")
        if superclass_node:
            return self._get_node_text(superclass_node)
        return None

    def _get_java_interfaces(self, node: tree_sitter.Node) -> List[str]:
        """Get implemented interfaces"""
        interfaces = []
        interfaces_node = node.child_by_field_name("interfaces")
        if interfaces_node:
            for interface in interfaces_node.named_children:
                if interface.type == "type_identifier":
                    interfaces.append(self._get_node_text(interface))
        return interfaces

    def _calculate_complexity(self, node: tree_sitter.Node) -> int:
        """Calculate cyclomatic complexity for Java code"""
        complexity = 1
        
        decision_types = [
            "if_statement",
            "while_statement",
            "for_statement",
            "switch_expression",
            "catch_clause",
            "conditional_expression",
            "binary_expression"  # for && and ||
        ]
        
        for type_ in decision_types:
            complexity += len(self._find_nodes_by_type(node, type_))
            
        return complexity

    def _extract_docstring(self, node: tree_sitter.Node) -> str:
        """Extract Java documentation comments"""
        docstring = ""
        
        # Look for block comments before the node
        prev_sibling = node.prev_sibling
        while prev_sibling and prev_sibling.type in ["block_comment", "line_comment"]:
            text = self._get_node_text(prev_sibling)
            # Clean up comment markers
            text = re.sub(r'^/\*+\s*|[\s*]*\*/$', '', text)
            text = re.sub(r'^//\s*', '', text)
            if text:
                docstring = text.strip() + "\n" + docstring
            prev_sibling = prev_sibling.prev_sibling
            
        return docstring.strip()

    def _get_node_text(self, node: tree_sitter.Node) -> str:
        """Get text content of node"""
        if node and hasattr(node, "text"):
            return node.text.decode("utf-8", errors="ignore")
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

    def _create_file_entity(self, context: AnalysisContext) -> FileInfo:
        """Create a File entity"""
        return FileInfo(
            entity_type=EntityType.FILE.value,
            file_path=str(context.file_path),
            file_type=context.language,
            size=len(context.content),
            description=self._extract_file_description(context),
            content=context.content,
        )

    def _extract_file_description(self, context: AnalysisContext) -> str:
        """Extract file description from header comments"""
        description = ""
        root_node = context.tree.root_node

        # Look for initial comments
        for child in root_node.children:
            if child.type in ["block_comment", "line_comment"]:
                text = self._get_node_text(child)
                # Clean up comment markers
                text = re.sub(r'^/\*+\s*|[\s*]*\*/$', '', text)
                text = re.sub(r'^//\s*', '', text)
                if text:
                    description += text + "\n"
            else:
                break

        return description.strip()
