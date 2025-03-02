from typing import Dict, List, Any, Optional
import tree_sitter
from tree_sitter import Language, Parser
import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
import logging
import re
import math
from code_analyze.code_analyzer import EntityType, AnalysisContext, CodeAnalyzer, EntityInfo, FileInfo

class JstsAnalyzer:
    """Analyzer for JavaScript/TypeScript source code using tree-sitter"""
    
    # Map node types to entity types
    JSTS_NODE_TYPE_TO_ENTITY_TYPE = {
        # JavaScript nodes
        "class_declaration": EntityType.CLASS.value,
        "class": EntityType.CLASS.value,  # For class expressions
        "function_declaration": EntityType.METHOD.value,
        "method_definition": EntityType.METHOD.value,
        # "variable_declaration": EntityType.VARIABLE.value,
        "variable_declarator": EntityType.VARIABLE.value,
        
        # TypeScript specific nodes
        "interface_declaration": EntityType.INTERFACE.value,
        "enum_declaration": EntityType.ENUM.value,
        "abstract_class_declaration": EntityType.CLASS.value,
        "type_alias_declaration": EntityType.VARIABLE.value,

         # jsx & tsx components
        "jsx_element": EntityType.CLASS.value,
        "jsx_self_closing_element": EntityType.CLASS.value,
        "function_expression": EntityType.METHOD.value,
        "arrow_function": EntityType.METHOD.value,
    }

    # Node types that should be processed recursively
    RECURSIVE_NODE_TYPES = {
        "class_declaration",
        "class",
        "method_definition",
        "function_declaration",
        "jsx_element",
        "function_expression",
        "arrow_function",
    }

    def __init__(self):
        """Initialize tree-sitter languages for both JavaScript and TypeScript"""
        self.logger = logging.getLogger(__name__)

        try:
            # Initialize JavaScript parser
            JS_LANGUAGE = Language(tsjs.language())
            self.js_parser = Parser()
            self.js_parser.language = JS_LANGUAGE

            try:
                TS_LANGUAGE = Language(tsts.typescript.language())
                TSX_LANGUAGE = Language(tsts.tsx.language())
                self.ts_parser = Parser()
                self.ts_parser.language = TS_LANGUAGE
                self.tsx_parser = Parser()
                self.tsx_parser.language = TSX_LANGUAGE
            except AttributeError:
                TS_LANGUAGE = Language(tsts.language_typescript())
                TSX_LANGUAGE = Language(tsts.language_tsx())
                self.ts_parser = Parser()
                self.ts_parser.language = TS_LANGUAGE
                self.tsx_parser = Parser()
                self.tsx_parser.language = TSX_LANGUAGE
            
            self.logger.info("Initialized parsers for JavaScript and TypeScript")
        except Exception as e:
            self.logger.error(f"Failed to initialize JS/TS parsers: {e}", exc_info=True)

    def print_code_entities(self, tree, content):
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

    def get_code_entities(
        self, content: str, language: Optional[str] = None, file_path: Optional[str]="temp"
    ) -> tuple[FileInfo, List[EntityInfo]]:
        """Extract code entities from the given JS/TS content"""
        if language.lower() == "typescript":
            parser = self.ts_parser
        elif language.lower() == "tsx":
            parser = self.tsx_parser
        else:
            parser = self.js_parser

        tree = parser.parse(content.encode("utf-8", errors="ignore"))
        # self.print_code_entities(tree, content)
        context = AnalysisContext(
            file_path=file_path, language=language, content=content, tree=tree
        )
        return self._extract_entities(context)

    def _extract_entities(self, context: AnalysisContext) -> tuple[FileInfo, List[EntityInfo]]:
        """Extract all entities from the code"""
        file_entity = self._create_file_entity(context)
        entities = []
        
        jsts_entities = self._extract_jsts_entities(context)
        if jsts_entities:
            unique_entities = self._deduplicate_entities(jsts_entities)
            entities.extend(unique_entities)
            
        return file_entity, entities
    
    def _deduplicate_entities(self, entities: List[EntityInfo]) -> List[EntityInfo]:
        """Remove duplicate entities based on their key attributes"""
        seen = set()
        unique_entities = []
        
        for entity in entities:
            # Create a tuple of key attributes that define uniqueness
            key = (
                entity.entity_type,
                entity.name,
                entity.parent_name,
                entity.content,
            )
            
            if key not in seen:
                seen.add(key)
                unique_entities.append(entity)
        
        return unique_entities

    def _extract_jsts_entities(
        self, context: AnalysisContext
    ) -> List[EntityInfo]:
        """Extract JavaScript/TypeScript entities"""
        def is_top_level(node: tree_sitter.Node) -> bool:
            """Check if node is at top level (not inside class or method)"""
            current = node.parent
            while current:
                if current.type in self.RECURSIVE_NODE_TYPES:
                    return False
                current = current.parent
            return True

        def traverse(node: tree_sitter.Node) -> List[EntityInfo]:
            entities = []

            # Process current node
            if node.type in self.JSTS_NODE_TYPE_TO_ENTITY_TYPE and node.type not in ["variable_declarator"]:
                # For non-recursive types, only process at top level
                if node.type in self.RECURSIVE_NODE_TYPES or is_top_level(node):
                    entity = self._create_code_entity(node)
                    if entity:
                        entities.append(entity)
            
            # Handle variable declarations that might contain class/function expressions
            elif node.type in ["variable_declaration", "lexical_declaration"]:
                if is_top_level(node):  # Only process top-level variables
                    for declarator in node.children:
                        if declarator.type == "variable_declarator":
                            name_node = declarator.child_by_field_name("name")
                            if name_node:
                                if name_node.type in ["object_pattern", "array_pattern"]:
                                    entity = self._create_variable_entity(
                                        declarator,
                                        node  # parent declaration node
                                    )
                                    if entity:
                                        entities.append(entity)
                                else:
                                    # Handle variable declarations with initializers
                                    initializer = declarator.child_by_field_name("initializer")
                                    value = initializer.child_by_field_name("value") if initializer else None
                                    entity = self._create_variable_entity(
                                        declarator,
                                        node,  # parent declaration node
                                        value
                                    )
                                    if entity:
                                        entities.append(entity)

            # Handle export declarations
            elif node.type == "export_statement":
                declaration = node.child_by_field_name("declaration")

                if declaration and declaration.type in self.JSTS_NODE_TYPE_TO_ENTITY_TYPE:
                    entity = self._create_code_entity(declaration)
                    if entity:
                        entities.append(entity)

            # Recursively process child nodes
            for child in node.children:
                entities.extend(traverse(child))

            return entities

        return traverse(context.tree.root_node)

    def _is_exported(self, node: tree_sitter.Node) -> bool:
        """Check if a node is exported by analyzing its context in the AST"""
        current = node
        while current:
            # Check if parent is an export_statement
            if current.parent and current.parent.type == "export_statement":
                return True
                
            # Handle named exports: 'export { foo as bar }'
            if (current.type == "identifier" and 
                current.parent and 
                current.parent.type == "export_specifier"):
                return True
                
            current = current.parent
            
        return False
    
    def _create_variable_entity(
        self,
        declarator: tree_sitter.Node,
        declaration_node: tree_sitter.Node,
        value_node: Optional[tree_sitter.Node] = None
    ) -> Optional[EntityInfo]:
        """Create entity for variable declaration"""
        # Get basic name information
        name_node = declarator.child_by_field_name("name")
        if not name_node:
            return None
        
        # Handle destructuring patterns
        if name_node.type in ["object_pattern", "array_pattern"]:
            # Get the full text for definition and content
            full_text = self._get_node_text(declarator)
            
            # Create a simplified name
            name = self._get_destructuring_name(name_node)
            
            return EntityInfo(
                entity_type=EntityType.VARIABLE.value,
                name=name,
                parent_name="",
                parent_type="",
                description="Destructured Variable",
                complexity=1,
                content=full_text,
                is_exported=self._is_exported(declarator),
                modifiers=[]
            )
        
        # Handle regular variable declarations
        name = self._get_node_text(name_node)
        if not name:
            return None

        # Get parent information
        parent_name, parent_type = self._get_parent_info(declaration_node)
        modifiers = []

        # Get declaration type (var/let/const)
        declaration_keyword = declaration_node.child_by_field_name("kind")
        if declaration_keyword and self._get_node_text(declaration_keyword) == "const":
            modifiers.append("constant")

        description = self._extract_docstring(declaration_node)

        # Handle value/initializer
        if value_node:
            # For class/function expressions, use existing logic
            if value_node.type in ["class", "function_expression", "arrow_function"]:
                entity_type = self.JSTS_NODE_TYPE_TO_ENTITY_TYPE.get(value_node.type, EntityType.VARIABLE.value)
                
                # Add type-specific information
                if value_node.type in ["function_expression", "arrow_function"]:
                    for mod in ["static", "async", "private", "protected", "public"]:
                        if self._has_modifier(value_node, mod):
                            modifiers.append(mod)
            else:
                entity_type = EntityType.VARIABLE.value
        else:
            entity_type = EntityType.VARIABLE.value

        return EntityInfo(
            entity_type=entity_type,
            name=name,
            parent_name=parent_name,
            parent_type=parent_type,
            description=description,
            complexity=1,
            content=self._get_node_text(declarator),
            is_exported=self._is_exported(declarator),
            modifiers=modifiers
        )

    def _get_destructuring_name(self, pattern_node: tree_sitter.Node) -> str:
        """Get a readable name for a destructuring pattern"""
        # Get the original text first
        original_text = self._get_node_text(pattern_node)
        
        # If the text is too long, create a simplified version
        if len(original_text) > 50:
            # For object pattern
            if pattern_node.type == "object_pattern":
                props = []
                for child in pattern_node.children:
                    if child.type == "object_assignment_pattern":
                        # Handle patterns like "ENDPOINTS: {...}"
                        id_node = child.child_by_field_name("left")
                        if id_node and id_node.type == "shorthand_property_identifier_pattern":
                            props.append(self._get_node_text(id_node).strip().rstrip(':'))
                    elif child.type == "pair_pattern":
                        # Handle nested patterns
                        key_node = child.child_by_field_name("key")
                        if key_node:
                            props.append(self._get_node_text(key_node))
                
                if props:
                    return "{" + ", ".join(props) + "}"
                return "{destructured}"
                
            # For array pattern
            elif pattern_node.type == "array_pattern":
                return "[...]"
        
        return original_text
    
    def _should_skip_entity(self, node: tree_sitter.Node) -> bool:
        """Determine if an entity should be skipped based on context"""

        NEVER_SKIP = {
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "type_alias_declaration"
        }
        
        if node.type in NEVER_SKIP:
            return False
            
        parent = node.parent
        while parent:
            if parent.type == "variable_declarator":
                return True
            parent = parent.parent
        
        return False

    def _create_code_entity(
        self, node: tree_sitter.Node, name_node: Optional[tree_sitter.Node] = None
    ) -> Optional[EntityInfo]:
        """Create code entity from AST node"""
        if self._should_skip_entity(node):
            return None
        
        # Get name from either name_node or node itself
        if node.type == "arrow_function":
            name = None
            parent = node.parent
            while parent:
                if parent.type == "assignment_expression":
                    left = parent.child_by_field_name("left")
                    if left:
                        name = self._get_node_text(left)
                        break
                elif parent.type == "variable_declarator":
                    name_field = parent.child_by_field_name("name")
                    if name_field:
                        name = self._get_node_text(name_field)
                        break
                elif parent.type == "pair":
                    key = parent.child_by_field_name("key")
                    if key:
                        name = self._get_node_text(key)
                        break
                parent = parent.parent
            if not name:
                name = "<anonymous_arrow_function>"
        else:
            name = None
            if name_node:
                name = self._get_node_text(name_node)
            else:
                name_field = node.child_by_field_name("name")
                if name_field:
                    name = self._get_node_text(name_field)

        if not name:
            return None

        parent_name, parent_type = self._get_parent_info(node)
        modifiers = []

        # Get method modifiers
        if self.JSTS_NODE_TYPE_TO_ENTITY_TYPE.get(node.type, "Unknown") == EntityType.METHOD.value:
            for mod in ["get", "set", "static", "async", "private", "protected", "public"]:
                if self._has_modifier(node, mod):
                    modifiers.append(mod)

        # Create EntityInfo instance
        return EntityInfo(
            entity_type=self.JSTS_NODE_TYPE_TO_ENTITY_TYPE.get(node.type, "Unknown"),
            name=name,
            parent_name=parent_name,
            parent_type=parent_type,
            description=self._extract_docstring(node),
            complexity=self._calculate_complexity(node),
            content=self._get_node_text(node),
            is_exported=self._is_exported(node),
            modifiers=modifiers
        )

    def _has_modifier(self, node: tree_sitter.Node, modifier: str) -> bool:
        """Check if node has specific modifier"""
        if not node:
            return False

        for child in node.children:
            if child.type == modifier:
                return True
            
        modifiers = node.child_by_field_name("modifiers")
        if modifiers:
            for mod in modifiers.children:
                if mod.type == modifier:
                    return True
                
        return False

    def _get_parent_info(self, node: tree_sitter.Node) -> tuple[str, str]:
        """Get parent name and type for node"""
        parent = node.parent
        parent_name = ""
        parent_type = ""
        
        while parent:
            if parent.type in self.JSTS_NODE_TYPE_TO_ENTITY_TYPE:
                name_field = parent.child_by_field_name("name")
                if name_field:
                    current_name = self._get_node_text(name_field)
                    # Build parent name path
                    parent_name = (
                        current_name
                        if parent_name == ""
                        else current_name + "/" + parent_name
                    )
                    # Only set parent type once (from immediate parent)
                    if parent_type == "":
                        parent_type = self.JSTS_NODE_TYPE_TO_ENTITY_TYPE.get(parent.type, "Unknown")
                        
            parent = parent.parent
            
        return parent_name, parent_type

    def _calculate_complexity(self, node: tree_sitter.Node) -> int:
        """Calculate cyclomatic complexity of code block"""
        complexity = 1

        # JavaScript/TypeScript specific decision points
        decision_types = [
            "if_statement",
            "while_statement",
            "for_statement",
            "for_in_statement",
            "for_of_statement",  # ES6+ specific
            "catch_clause",
            "case_clause",
            "ternary_expression",
            "binary_expression",  # Will count && and || operations
            "optional_chain"     # TypeScript optional chaining
        ]

        ts_complexity_factors = [
            "type_parameter",
            "union_type",
            "intersection_type",
            "conditional_type",
            "mapped_type"
        ]

        jsx_complexity_factors = [
            "jsx_element",
            "jsx_expression",
            "conditional_expression"
        ]

        for type_ in decision_types:
            nodes = self._find_nodes_by_type(node, type_)
            for n in nodes:
                # For binary expressions, only count logical operators
                if type_ == "binary_expression":
                    operator = n.child_by_field_name("operator")
                    if operator and self._get_node_text(operator) in ["&&", "||"]:
                        complexity += 1
                else:
                    complexity += 1
        
        # Add fractional complexity for TypeScript and JSX constructs
        for type_ in ts_complexity_factors:
            nodes = self._find_nodes_by_type(node, type_)
            complexity += len(nodes) * 0.5

        for type_ in jsx_complexity_factors:
            nodes = self._find_nodes_by_type(node, type_)
            complexity += len(nodes) * 0.5

        return math.floor(complexity)

    def _extract_docstring(self, node: tree_sitter.Node) -> str:
        """
        Extract documentation comments from node and prepend type description.
        Handles JSDoc, TSDoc, single-line and block comments.
        """
        TYPE_DESCRIPTIONS = {
            # Class-like declarations
            "class_declaration": "Class",
            "class": "Class",
            "abstract_class_declaration": "Abstract Class",
            
            # Function-like declarations
            "function_declaration": "Function",
            "method_definition": "Method",
            "function_expression": "Function Expression",
            "arrow_function": "Arrow Function",
            
            # Variable declarations
            "variable_declaration": "Variable",
            "variable_declarator": "Variable",
            
            # TypeScript specific
            "interface_declaration": "Interface",
            "enum_declaration": "Enum",
            "type_alias_declaration": "Type Alias",
            
            # React/JSX specific
            "jsx_element": "React Component",
            "jsx_self_closing_element": "React Component",
            "jsx_fragment": "React Fragment",
        }

        docstring = ""
        prev_sibling = node.prev_sibling
        
        while prev_sibling and prev_sibling.type == "comment":
            text = self._get_node_text(prev_sibling)
            
            # Clean up various comment styles
            text = re.sub(r'^/\*\*\s*|\s*\*/$', '', text)  # JSDoc/TSDoc markers
            text = re.sub(r'^\s*\*\s*', '', text, flags=re.MULTILINE)  # Line stars
            text = re.sub(r'^//+\s*', '', text, flags=re.MULTILINE)  # Single-line comments
            text = re.sub(r'^/\*\s*|\s*\*/$', '', text)  # Block comments
            
            # Clean common tags while preserving content
            text = re.sub(r'@(param|returns?|description|example)\s+', '', text)
            
            if text:
                docstring = text.strip() + "\n" + docstring
            prev_sibling = prev_sibling.prev_sibling

        # Add type description
        type_desc = TYPE_DESCRIPTIONS.get(node.type, "")
        if type_desc and docstring:
            docstring = f"{type_desc}: {docstring}"
        elif type_desc:
            docstring = type_desc

        return docstring.strip()

    def _get_node_text(self, node: tree_sitter.Node) -> str:
        """Get text content of node"""
        try:
            if node and hasattr(node, "text"):
                return node.text.decode("utf-8", errors="ignore")
            return ""
        except Exception as e:
            self.logger.warning(f"Failed to get node text: {e}")
            return ""

    def _find_nodes_by_type(self, node: tree_sitter.Node, node_type: str) -> List[tree_sitter.Node]:
        """Find all nodes of a specific type in the AST"""
        nodes = []
        queue = [node]
        
        while queue:
            current = queue.pop(0)
            if current.type == node_type:
                nodes.append(current)
            queue.extend(current.children)
                
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
            if child.type == "comment":
                text = self._get_node_text(child)
                # Clean up comment markers
                text = re.sub(r'^/\*\*?\s*|\s*\*/$', '', text)
                text = re.sub(r'^\s*\*\s*', '', text, flags=re.MULTILINE)
                text = re.sub(r'^//\s*', '', text)
                if text:
                    description += text + "\n"
            else:
                break

        return description.strip()