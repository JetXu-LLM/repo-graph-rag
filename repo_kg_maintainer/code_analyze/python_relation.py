from typing import Dict, List, Optional, Tuple, Any
import logging
from dataclasses import dataclass, field
from enum import Enum
import tree_sitter
import os
from pathlib import Path
from code_analyze.code_analyzer import EntityType, EntityInfo, RelationType, EntityReference, RelationInfo, RelationKey

class PythonRelationExtractor:
    """
    Extract relationships from Python code using tree-sitter.
    This implementation covers various Python call styles:
      - Direct function calls
      - self.method() calls (instance methods)
      - Instance, static, and class methods via object or class name
      - Imported calls (and filters out external libraries)
      - Variable and parameter-based calls
      - Chain calls are partially handled via return type tracking
    """

    def __init__(self, parser: tree_sitter.Parser, repo_entities: List[EntityInfo]):
        """
        Initialize with parser and all entities in the repo
        
        Args:
            parser: Tree-sitter parser
            repo_entities: All entities (classes, methods, variables, etc.) from repository
        """
        self.logger = logging.getLogger(__name__)
        self.parser = parser

        # Build entity lookup maps for quick matching
        self.repo_entities = repo_entities
        self.entity_by_path: Dict[str, Dict[str, EntityInfo]] = {}
        self.entity_by_key: Dict[str, EntityInfo] = {}
        self.relations: List[RelationInfo] = []
        self._build_entity_maps()

        self.inheritance_map: Dict[str, List[str]] = {}  # class_name -> [parent_classes]

        # Tracking current file, scope (e.g. current class name), and function name (for parameter type)
        self.current_file: str = ""
        self.current_scope: Optional[str] = None
        self.current_function: Optional[str] = None
        
        # Type tracking: variable assignments and function parameter type annotations, as well as return types.
        # variable_types[file_path]: {var_name: class_name}
        self.variable_types: Dict[str, Dict[str, str]] = {}
        # param_types[file_path]: { "qualified_func:param_name" : type_name }
        self.param_types: Dict[str, Dict[str, str]] = {}
        # return_types: { qualified_func: return_type }
        self.return_types: Dict[str, str] = {}

    def _build_entity_maps(self):
        for entity in self.repo_entities:
            normalized_path = os.path.normpath(entity.file_path)
            self.entity_by_path.setdefault(normalized_path, {})
            qualified_name = f"{entity.parent_name}.{entity.name}" if entity.parent_name else entity.name
            self.entity_by_path[normalized_path][qualified_name] = entity
            entity_key = self._generate_entity_key(entity.entity_type, normalized_path, entity.name, entity.parent_name)
            self.entity_by_key[entity_key] = entity

            # self.logger.debug(f"Adding entity: {qualified_name} from {normalized_path}")

        self.logger.debug(f"Current repo entities: {list(self.entity_by_key.keys())}")

    def _process_param_type_relations(self, tree: tree_sitter.Tree, content: str,
                                    import_map: Dict[str, str],
                                    file_path: str) -> List[RelationInfo]:
        """
        Process relationships between methods and their parameter types.
        Creates USES relations for method parameters that are classes.
        
        Args:
            tree: The parsed AST tree
            content: The source code content
            import_map: Mapping of imported names to their module paths
            file_path: Path of the current file being processed
            
        Returns:
            List of parameter type relations extracted from the code
        """
        relations: List[RelationInfo] = []
        
        # Process methods in the current file
        for entity_key, entity in self.entity_by_key.items():
            if entity.entity_type == EntityType.METHOD.value and entity.file_path == file_path:
                method_name = entity.name
                parent_name = entity.parent_name
                qualified_name = f"{parent_name}.{method_name}" if parent_name else method_name
                
                # Get method reference
                method_ref = self._entity_to_reference(entity, file_path)
                
                # Process parameter types
                for param_key, param_type in self.param_types.get(file_path, {}).items():
                    if param_key.startswith(f"{qualified_name}:"):
                        # Try to resolve the parameter type to a class
                        param_type_ref = self._create_entity_reference(param_type, import_map, file_path)
                        if param_type_ref and param_type_ref.entity_type == EntityType.CLASS.value:
                            self.logger.debug(f"Found parameter type relation: {qualified_name} -> {param_type}")
                            relations.append(RelationInfo(
                                source=method_ref,
                                target=param_type_ref,
                                relation_type=RelationType.USES.value,
                                source_location=(0, 0),  # Simplified location
                                target_location=(0, 0),
                                metadata={'is_param_type': True}
                            ))
        
        return relations

    def _post_process_relations(self, relations: List[RelationInfo]) -> List[RelationInfo]:
        """
        Post-process relations to remove duplicates and apply priority rules.
        When the same source-target pair has both CALLS and INSTANTIATES relations,
        keep only the INSTANTIATES relation.
        
        Args:
            relations: List of relations to process
            
        Returns:
            Optimized list of relations with duplicates removed
        """
        # Create a mapping to track each source-target pair
        relation_map = {}
        
        for relation in relations:
            key = (relation.source.key, relation.target.key)
            
            if key in relation_map:
                # Already have a relation with the same source and target
                existing = relation_map[key]
                
                # If we have both CALLS and INSTANTIATES, prefer INSTANTIATES
                if (relation.relation_type == RelationType.INSTANTIATES.value and 
                    existing.relation_type == RelationType.CALLS.value and
                    relation.target.entity_type == EntityType.CLASS.value):
                    self.logger.debug(f"Replacing CALLS with INSTANTIATES: {relation.source.name} -> {relation.target.name}")
                    relation_map[key] = relation
                # Otherwise keep the existing relation
            else:
                relation_map[key] = relation
        
        # Return the optimized relations
        return list(relation_map.values())

    def _process_class_relations(self, tree: tree_sitter.Tree, content: str,
                                import_map: Dict[str, str],
                                file_path: str) -> List[RelationInfo]:
        """Process class inheritance relationships using node traversal."""
        relations: List[RelationInfo] = []
        stack = [tree.root_node]
        
        # For inheritance mapping in the current file
        file_inheritance_map: Dict[str, List[str]] = {}
        
        def extract_base_class_name(node: tree_sitter.Node) -> Optional[str]:
            """Recursively extract base class name with enhanced coverage."""
            if node.type == "identifier":
                return self._get_node_text(node, content)
            elif node.type == "attribute":
                obj = extract_base_class_name(node.child_by_field_name("object"))
                attr = extract_base_class_name(node.child_by_field_name("attribute"))
                return f"{obj}.{attr}" if obj and attr else None
            elif node.type == "subscript":
                base = extract_base_class_name(node.child_by_field_name("value"))
                return base
            elif node.type == "call":
                return extract_base_class_name(node.child_by_field_name("function"))
            elif node.type in ["tuple", "list", "dictionary"]:
                return None
            return None

        while stack:
            node = stack.pop()
            
            if node.type == "class_definition":
                # Extract class name
                class_name_node = node.child_by_field_name("name")
                if not class_name_node:
                    continue
                class_name = self._get_node_text(class_name_node, content)
                original_scope = self.current_scope
                self.current_scope = class_name  # Update current scope
                
                # Extract base classes
                base_class_nodes = []
                base_list = node.child_by_field_name("superclasses")
                if base_list and base_list.type == "argument_list":
                    base_class_nodes = list(base_list.children)
                
                # Initialize parent class list for the current class
                parent_classes = []
                file_inheritance_map[class_name] = parent_classes
                
                for base_node in base_class_nodes:
                    if base_node.type in [")", "(", ","]:
                        continue  # Skip syntax nodes
                    
                    base_name = extract_base_class_name(base_node)
                    if not base_name:
                        continue
                    
                    # Add to parent class list
                    parent_classes.append(base_name)
                    
                    # Create entity references
                    class_ref = self._create_entity_reference(
                        class_name, import_map, file_path)
                    parent_ref = self._create_entity_reference(
                        base_name, import_map, file_path)
                    
                    if class_ref and parent_ref:
                        relations.append(RelationInfo(
                            source=class_ref,
                            target=parent_ref,
                            relation_type=RelationType.INHERITS.value,
                            source_location=self._get_node_location(class_name_node),
                            target_location=self._get_node_location(base_node)
                        ))
                        self.logger.debug(f"Found inheritance: {class_name} -> {base_name}")
                
                self.current_scope = original_scope  # Restore original scope
            
            # Continue traversal
            stack.extend(reversed(node.children))
        
        # Update global inheritance mapping
        self.inheritance_map.update(file_inheritance_map)
        
        return relations
    
    def _get_parent_classes(self, class_name: str, file_path: str, import_map: Dict[str, str]) -> List[str]:
        """
        Get the parent classes of a given class.
        
        Args:
            class_name: The name of the class
            file_path: The file path where the class is used
            import_map: Import mapping to resolve class names
            
        Returns:
            List of parent class names
        """
        # Direct lookup from inheritance map
        if class_name in self.inheritance_map:
            parent_classes = self.inheritance_map[class_name]
            if parent_classes:
                self.logger.debug(f"Found parent classes for {class_name} in inheritance map: {parent_classes}")
                return parent_classes
        
        # Check if class name is imported
        for module_prefix, module_path in import_map.items():
            if class_name.startswith(f"{module_prefix}."):
                # Remove module prefix to get local name
                local_name = class_name[len(module_prefix)+1:]
                # Build possible qualified name
                qualified_name = f"{module_path.replace('/', '.')}.{local_name}"
                # Check if qualified name exists in inheritance map
                if qualified_name in self.inheritance_map:
                    self.logger.debug(f"Found parent classes for {class_name} through import: {self.inheritance_map[qualified_name]}")
                    return self.inheritance_map[qualified_name]
        
        # If still not found, try to find through entity search
        for entity_key, entity in self.entity_by_key.items():
            if entity.entity_type == EntityType.CLASS.value and entity.name == class_name:
                # Check for inheritance relations targeting this entity
                for relation in self.relations:
                    if (relation.relation_type == RelationType.INHERITS.value and 
                        relation.source.name == class_name):
                        self.logger.debug(f"Found parent class for {class_name} through relations: {relation.target.name}")
                        return [relation.target.name]
        
        # Last resort: look for any class with this name
        for class_key, parents in self.inheritance_map.items():
            if class_key.endswith(f".{class_name}") or class_key == class_name:
                self.logger.debug(f"Found parent classes for {class_name} through name matching: {parents}")
                return parents
        
        self.logger.warning(f"No parent classes found for {class_name}")
        return []

    def _generate_entity_key(self, entity_type: str, file_path: str, name: str, parent_name: Optional[str] = None) -> str:
        """Generate a unique key for an entity."""
        parts = [entity_type, file_path]
        if parent_name:
            parts.append(parent_name)
        parts.append(name)
        return "/".join(parts)

    def _resolve_import_path(self, import_name: str, current_path: str) -> str:
        if import_name.startswith('.'):
            current_dir = os.path.dirname(current_path)
            dot_count = len(import_name) - len(import_name.lstrip('.'))
            remaining = import_name.lstrip('.')
            for _ in range(dot_count - 1):
                current_dir = os.path.dirname(current_dir)
            if remaining:
                return os.path.join(current_dir, remaining.replace('.', '/'))
            return current_dir
        else:
            return import_name.replace('.', '/')

    def extract_relations(self, tree: tree_sitter.Tree, content: str, file_path: str) -> List[RelationInfo]:
        """Extract all relationships from a Python file."""
        self.logger.debug(f"Available entities in current file: {list(self.entity_by_path.get(file_path, {}).keys())}")

        self.current_file = file_path
        self.variable_types.setdefault(file_path, {})
        self.param_types.setdefault(file_path, {})
        self.current_param_types = {}  # For tracking parameter types in current context
        self.method_references = getattr(self, 'method_references', {})  # For tracking method references
        self.method_references.setdefault(file_path, {})
        self.current_scope = None
        self.current_function = None

        # Initialize relations if not already done
        if not hasattr(self, 'relations'):
            self.relations = []

        # Track variable assignments, function parameters and return types.
        self._track_assignments(tree, content)
        self._track_function_params(tree, content)
        self._track_return_types(tree, content)

        import_map = self._build_import_map(tree, content, file_path)
        self.import_map = import_map  # Store for use in other methods

        self.logger.debug(f"Import map: {import_map}")

        relations: List[RelationInfo] = []
        seen_relations = set()

        def add_relation(relation: RelationInfo):
            rk = RelationKey(relation.source.key, relation.target.key, relation.relation_type)
            if rk not in seen_relations:
                seen_relations.add(rk)
                relations.append(relation)
                # Also store in instance variable for later use
                self.relations.append(relation)

        # Process class inheritance relations
        for rel in self._process_class_relations(tree, content, import_map, file_path):
            add_relation(rel)

        # Process class instantiation relations
        for rel in self._process_instantiation_relations(tree, content, import_map, file_path):
            add_relation(rel)
        
        # Process method call relations
        for rel in self._process_call_relations(tree, content, import_map, file_path):
            add_relation(rel)
            
        # Process global variable reference and modification relations
        for rel in self._process_global_var_relations(tree, content, import_map, file_path):
            add_relation(rel)
            
        # Process global function call relations
        for rel in self._process_global_function_calls(tree, content, import_map, file_path):
            add_relation(rel)

        # Add parameter type relations (NEW)
        for rel in self._process_param_type_relations(tree, content, import_map, file_path):
            add_relation(rel)

        # Post-process relations to remove duplicates (NEW)
        processed_relations = self._post_process_relations([r for r in relations if self._is_valid_relation(r)])
        
        return processed_relations

    def _build_import_map(self, tree: tree_sitter.Tree, content: str, file_path: str) -> Dict[str, str]:
        """
        Build import mapping through AST traversal.
        
        Returns a dict mapping imported names to their source paths:
        - For direct imports: name -> module_path/name
        - For aliased imports: alias -> module_path/original_name
        """
        import_map = {}
        
        def process_import_statement(node: tree_sitter.Node):
            """Handle 'import module[.submodule] [as alias]' statements."""
            for child in node.children:
                if child.type == "dotted_name":
                    # Handle direct imports like 'import os' or 'import src.models.user'
                    module_path = self._get_node_text(child, content)
                    module_parts = module_path.split('.')
                    resolved_path = self._resolve_import_path(module_path, file_path)
                    
                    # Map the base module name to its full path
                    import_map[module_parts[0]] = resolved_path
                    
                elif child.type == "aliased_import":
                    # Handle aliased imports like 'import pandas as pd'
                    orig_node = child.child_by_field_name("name")
                    alias_node = child.child_by_field_name("alias")
                    if orig_node and alias_node:
                        orig = self._get_node_text(orig_node, content)
                        alias = self._get_node_text(alias_node, content)
                        resolved_path = self._resolve_import_path(orig, file_path)
                        import_map[alias] = resolved_path

        def process_import_from(node: tree_sitter.Node):
            """Handle 'from module import name[, name2[, ...]] [as alias]' statements."""
            # Get module path from either absolute or relative import
            module_node = node.child_by_field_name("module_name") or node.child_by_field_name("relative_import")
            if not module_node:
                return
                
            module_path = self._get_node_text(module_node, content)
            base_path = self._resolve_import_path(module_path, file_path)
            
            # Process imported items
            for child in node.children:
                if child.type == "dotted_name":
                    # Handle direct imports like 'from typing import List'
                    name = self._get_node_text(child, content)
                    import_map[name] = f"{base_path}/{name}"
                    
                elif child.type == "aliased_import":
                    # Handle aliased imports like 'from datetime import datetime as dt'
                    orig_node = child.child_by_field_name("name")
                    alias_node = child.child_by_field_name("alias")
                    if orig_node and alias_node:
                        orig = self._get_node_text(orig_node, content)
                        alias = self._get_node_text(alias_node, content)
                        import_map[alias] = f"{base_path}/{orig}"
                        
                elif child.type == "identifier" and child.text:
                    # Handle simple imports like 'from os import path'
                    name = self._get_node_text(child, content)
                    if name not in ("import", "from", "as"):
                        import_map[name] = f"{base_path}/{name}"

        def traverse(node: tree_sitter.Node):
            """Traverse AST to find and process import statements."""
            if node.type == "import_statement":
                process_import_statement(node)
            elif node.type == "import_from_statement":
                process_import_from(node)
            else:
                for child in node.children:
                    traverse(child)

        traverse(tree.root_node)
        
        # Remove any invalid entries but keep valid paths
        return {
            k: v for k, v in import_map.items() 
            if v and not any(x in v for x in ['as '])
        }

    def _track_assignments(self, tree: tree_sitter.Tree, content: str) -> None:
        """
        Track variable assignments by traversing the AST.
        Updates self.variable_types[self.current_file] with variable type mappings.
        
        Handles various assignment patterns:
        - Basic assignment: x = Class()
        - Multiple assignment: x = y = Class()
        - Type annotated: x: Type = Class()
        - Tuple unpacking: a, b = Class(), Class()
        - List comprehension: items = [Item() for _ in range(5)]
        - Named expression: if (x := Class())
        - Chain calls: x = Builder().method().build()
        - Parenthesized: x = (Class())
        - Binary operations: x = Class() + 5
        """
        def extract_class_from_node(node: tree_sitter.Node) -> Optional[str]:
            """Extract class name from a node that might contain a class instantiation"""
            if not node:
                return None
                
            if node.type == "call":
                # Direct call: Class()
                func_node = node.child_by_field_name("function")
                if func_node:
                    if func_node.type == "identifier":
                        return self._get_node_text(func_node, content)
                    elif func_node.type == "attribute":
                        current = func_node
                        while current and current.type == "attribute":
                            obj_node = current.child_by_field_name("object")
                            if obj_node and obj_node.type == "call":
                                current = obj_node.child_by_field_name("function")
                            else:
                                break
                        if current and current.type == "identifier":
                            return self._get_node_text(current, content)
                            
            elif node.type == "parenthesized_expression":
                # Handle (Class())
                for child in node.children:
                    class_name = extract_class_from_node(child)
                    if class_name:
                        return class_name
                        
            elif node.type == "binary_operator":
                # Handle Class() + 5
                left_node = node.children[0] if node.children else None
                return extract_class_from_node(left_node)
                
            elif node.type == "list_comprehension":
                # Handle [Class() for x in range(5)]
                if node.children:
                    # The first non-bracket child should be the expression being comprehended
                    for child in node.children:
                        if child.type not in ["[", "]", "for_in_clause"]:
                            return extract_class_from_node(child)
                            
            return None
        
        def process_assignment_node(node: tree_sitter.Node) -> None:
            """Process an assignment node and extract variable types"""
            if node.type != "assignment":
                return
                
            # Get left side (variable names)
            left = node.child_by_field_name("left")
            if not left:
                return
                
            # Get right side (value)
            right = node.child_by_field_name("right")
            if not right:
                return
                
            # Extract variable names based on left side pattern
            var_names = []
            if left.type == "identifier":
                var_names.append(self._get_node_text(left, content))
            elif left.type == "pattern_list":
                # Handle tuple unpacking: a, b = ...
                for child in left.children:
                    if child.type == "identifier":
                        var_names.append(self._get_node_text(child, content))
                        
            # Handle nested assignments (x = y = z)
            if right.type == "assignment":
                process_assignment_node(right)
                right = right.child_by_field_name("right")
                
            # Handle expression list (tuple unpacking right side)
            if right.type == "expression_list":
                # Match each variable with corresponding expression
                expr_nodes = [child for child in right.children if child.type not in [",", ";"]]
                for var_name, expr_node in zip(var_names, expr_nodes):
                    class_name = extract_class_from_node(expr_node)
                    if class_name:
                        self.variable_types[self.current_file][var_name] = class_name
            else:
                # Single value assignment
                class_name = extract_class_from_node(right)
                if class_name:
                    for var_name in var_names:
                        self.variable_types[self.current_file][var_name] = class_name

        def process_named_expression(node: tree_sitter.Node) -> None:
            """Handle walrus operator (:=) assignments"""
            if node.type != "named_expression":
                return
                
            var_node = node.child_by_field_name("name")
            if not var_node or var_node.type != "identifier":
                return
                
            value_node = node.child_by_field_name("value")
            if not value_node:
                return
                
            var_name = self._get_node_text(var_node, content)
            class_name = extract_class_from_node(value_node)
            if class_name:
                self.variable_types[self.current_file][var_name] = class_name

        def traverse(node: tree_sitter.Node) -> None:
            """Traverse AST to find assignments"""
            if node.type == "assignment":
                process_assignment_node(node)
            elif node.type == "named_expression":
                process_named_expression(node)
                
            for child in node.children:
                traverse(child)

        # Initialize variable types dict for current file
        self.variable_types[self.current_file] = {}
        
        # Start traversal from root
        traverse(tree.root_node)

    def _track_function_params(self, tree: tree_sitter.Tree, content: str):
        """Track function parameters with type annotations by traversing the syntax tree.
        
        Handles various parameter patterns including:
        - Regular parameters (self)
        - Typed parameters (x: int)
        - Typed parameters with default values (z: str = "default")
        - Parameters with complex type hints (Union[int, str], Optional[list[str]])
        - Async function parameters
        - Nested function parameters
        """
        stack = [tree.root_node]
        
        while stack:
            node = stack.pop()
            
            if node.type in ['function_definition', 'async_function_definition']:
                # Handle both sync and async functions
                func_name_node = node.child_by_field_name('name')
                if not func_name_node:
                    continue

                # Get function name and parent class
                func_name = self._get_node_text(func_name_node, content)
                current_class = None
                parent = node.parent
                while parent:
                    if parent.type == 'class_definition':
                        class_name_node = parent.child_by_field_name('name')
                        if class_name_node:
                            current_class = self._get_node_text(class_name_node, content)
                        break
                    parent = parent.parent

                # Build qualified name with class context
                qualified_func = f"{current_class}.{func_name}" if current_class else func_name

                # Process parameters
                parameters_node = node.child_by_field_name('parameters')
                if parameters_node:
                    for param_node in parameters_node.children:
                        param_type = param_node.type
                        param_name = None
                        type_node = None

                        # Handle different parameter types
                        if param_type in ['typed_parameter', 'typed_default_parameter']:
                            # Extract from structured parameter nodes
                            for child in param_node.children:
                                if child.type == 'identifier':
                                    param_name = self._get_node_text(child, content)
                                elif child.type == 'type':
                                    type_node = child
                                elif child.type in ['subscript', 'generic_type', 'tuple', 'list']:
                                    # Capture complex type annotations
                                    type_node = child
                        elif param_type == 'default_parameter':
                            # Handle simple default parameters without type hints
                            continue  # Skip parameters without type annotations
                        elif param_type == 'identifier':
                            # Handle simple parameters without type hints (like 'self')
                            param_name = self._get_node_text(param_node, content)
                            type_node = None

                        if not param_name:
                            continue

                        # For typed_default_parameter, we need to look deeper for the type
                        if param_type == 'typed_default_parameter' and not type_node:
                            # Handle cases where type might be in a different child structure
                            for child in param_node.children:
                                if child.type == ':':
                                    next_sibling = child.next_named_sibling
                                    if next_sibling and next_sibling.type in ['type', 'subscript', 'generic_type']:
                                        type_node = next_sibling
                                        break

                        if type_node:
                            # Capture full type text including nested structures
                            type_text = self._get_node_text(type_node, content)
                            key = f"{qualified_func}:{param_name}"
                            self.param_types[self.current_file][key] = type_text

                        if param_name == "cls" and current_class:
                            # For 'cls' parameter, always bind it to the current class
                            key = f"{qualified_func}:{param_name}"
                            self.param_types[self.current_file][key] = current_class
                            self.logger.debug(f"Set cls parameter type to current class: {current_class}")

            stack.extend(reversed(node.children))

    def _track_return_types(self, tree: tree_sitter.Tree, content: str):
        """
        Track function return types by traversing the syntax tree.
        Handles various return type patterns including:
        - Simple types (int, str)
        - Generic types (List[str], Dict[str, int])
        - Nested generics (Dict[str, Optional[List[int]]])
        - Union types (Union[int, str])
        - Forward references ('MyClass')
        - Async function return types
        - Tuple types (tuple[int, ...])
        - No return type annotation
        """
        stack = [tree.root_node]

        while stack:
            node = stack.pop()

            if node.type in ['function_definition', 'async_function_definition']:
                # Handle both sync and async functions
                func_name_node = node.child_by_field_name('name')
                if not func_name_node:
                    continue

                func_name = self._get_node_text(func_name_node, content)

                # Determine the current scope (class or global)
                current_class = None
                parent = node.parent
                while parent:
                    if parent.type == 'class_definition':
                        class_name_node = parent.child_by_field_name('name')
                        if class_name_node:
                            current_class = self._get_node_text(class_name_node, content)
                        break
                    parent = parent.parent

                qualified_func = f"{current_class}.{func_name}" if current_class else func_name

                # Find the return type node
                return_type_node = node.child_by_field_name('return_type')
                if return_type_node:
                    # Extract the full return type text, handling complex types
                    return_type = self._get_node_text(return_type_node, content)
                    self.return_types[qualified_func] = return_type

            stack.extend(reversed(node.children))

    def _create_entity_reference(self, name: str, import_map: Dict[str, str], file_path: str) -> Optional[EntityReference]:
        """
        Resolves a name to an EntityReference by searching through multiple resolution strategies:
        1. Self-referential calls within class context
        2. Direct matches in current file entities
        3. Method references (like handler = obj.method)
        4. Import-alias expanded resolution
        5. Hierarchical parent/child relationships
        6. Global qualified name matching
        7. Variable type inference
        8. Parameter type inference
        9. Method reference type inference
        10. Fuzzy matching as last resort
        
        Enhanced with better error handling and recovery strategies.
        """
        current_entities = self.entity_by_path.get(file_path, {})
        self.logger.debug(f"Resolving entity reference for: {name}")

        # 1. Handle self-referential calls
        if name.startswith("self.") and self.current_scope:
            method_name = name.split("self.", 1)[1]
            qualified_name = f"{self.current_scope}.{method_name}"
            if entity := current_entities.get(qualified_name):
                self.logger.debug(f"Resolved self-call to class method: {entity.parent_name} & {entity.name}")
                return self._entity_to_reference(entity, file_path)

        # 2. Check direct match in current file
        if entity := current_entities.get(name):
            self.logger.debug(f"Found direct entity match: {entity.parent_name} & {entity.name}")
            return self._entity_to_reference(entity, file_path)
            
        # 3. Check method references (handler = obj.method)
        if hasattr(self, 'method_references') and file_path in self.method_references:
            if name in self.method_references[file_path]:
                method_ref = self.method_references[file_path][name]
                self.logger.debug(f"Found method reference: {name} -> {method_ref}")
                
                # Try to get the class type for this method reference
                ref_type = None
                if hasattr(self, 'method_reference_types') and file_path in self.method_reference_types:
                    ref_type = self.method_reference_types[file_path].get(name)
                    
                if ref_type:
                    # If we know the type, try to get the actual method
                    if '.' in method_ref:
                        method_name = method_ref.split('.')[-1]
                        qualified_name = f"{ref_type}.{method_name}"
                        self.logger.debug(f"Method reference with type: {qualified_name}")
                        return self._create_entity_reference(qualified_name, import_map, file_path)
                
                # If we don't know the type or failed to resolve with type,
                # try to directly resolve the method reference
                return self._create_entity_reference(method_ref, import_map, file_path)

        # 4. Resolve through import aliases with enhanced path matching
        if "." in name:
            parts = name.split('.')
            for i in range(1, len(parts)):
                module_part, entity_part = '.'.join(parts[:i]), '.'.join(parts[i:])
                if import_path := import_map.get(module_part):
                    # Try exact match first
                    if entity := self._find_repo_entity(entity_part, import_path):
                        self.logger.debug(f"Resolved through import {module_part} => {import_path} : {entity.parent_name} & key {entity.name}")
                        return self._entity_to_reference(entity, file_path)
                    
                    # Try normalized path matching for complex imports
                    normalized_import = import_path.replace('.', '/')
                    normalized_entity = entity_part.replace('.', '/')
                    
                    for entity_key, entity in self.entity_by_key.items():
                        # Skip entity type prefix
                        key_parts = entity_key.split('/')
                        if len(key_parts) < 3:
                            continue
                            
                        entity_type = key_parts[0]
                        entity_path = '/'.join(key_parts[1:-1])
                        entity_name = key_parts[-1]
                        
                        # Check if paths match and entity name matches
                        if (entity_path.endswith(normalized_import) or 
                            normalized_import.endswith(entity_path)) and entity_name == normalized_entity.split('/')[-1]:
                            self.logger.debug(f"Resolved through complex path matching: {entity.parent_name} & {entity.name}")
                            return self._entity_to_reference(entity, file_path)

        # 5. Check hierarchical parent/child relationships
        parts = name.split('.')
        for i in range(len(parts)-1, 0, -1):
            parent_name, child_name = '.'.join(parts[:i]), '.'.join(parts[i:])
            if parent_entity := current_entities.get(parent_name):
                candidate_name = f"{parent_entity.name}.{child_name}"
                if entity := self._find_qualified_entity(candidate_name):
                    self.logger.debug(f"Found hierarchical match: {entity.parent_name} & {entity.name}")
                    return self._entity_to_reference(entity, file_path)

        # 6. Global qualified name search
        if '.' in name:
            parts = name.split('.')
            class_name, method_name = parts[0], '.'.join(parts[1:])
            
            # First try: exact match with class and method name
            exact_match = None
            for entity in self.repo_entities:
                if (entity.entity_type == EntityType.METHOD.value and 
                    entity.name == method_name and 
                    entity.parent_name == class_name):
                    exact_match = entity
                    self.logger.debug(f"Found exact method match for {class_name}.{method_name}")
                    return self._entity_to_reference(entity, file_path)
            
            # If no exact match found, continue with regular search
            if not exact_match and (entity := self._find_qualified_entity(name)):
                # Verify that the found method belongs to the expected class
                if entity.entity_type == EntityType.METHOD.value and entity.parent_name != class_name:
                    self.logger.debug(f"Rejecting method match due to class mismatch: expected {class_name}, got {entity.parent_name}")
                else:
                    self.logger.debug(f"Found global qualified match: {entity.parent_name} & {entity.name}")
                    return self._entity_to_reference(entity, file_path)
        else:
            # Regular search for non-method entities
            if entity := self._find_qualified_entity(name):
                self.logger.debug(f"Found global qualified match: {entity.parent_name} & {entity.name}")
                return self._entity_to_reference(entity, file_path)

        # 7. Check variable type inference
        if hasattr(self, 'variable_types') and file_path in self.variable_types and name in self.variable_types[file_path]:
            var_type = self.variable_types[file_path][name]
            self.logger.debug(f"Attempting type inference: {name} -> {var_type}")
            return self._create_entity_reference(var_type, import_map, file_path)
        
        # 8. Check parameter type inference from current function context
        if hasattr(self, 'current_param_types') and self.current_param_types:
            # Try direct parameter match
            current_func = self._get_current_function_context()
            if current_func:
                param_key = f"{current_func}:{name}"
                if param_key in self.current_param_types:
                    param_type = self.current_param_types[param_key]
                    self.logger.debug(f"Found parameter type in current context: {param_key} -> {param_type}")
                    return self._create_entity_reference(param_type, import_map, file_path)
                    
            # Try any parameter match (might be from nested context)
            for param_key, param_type in self.current_param_types.items():
                if param_key.endswith(f":{name}") and param_type:
                    self.logger.debug(f"Found parameter type in any context: {param_key} -> {param_type}")
                    return self._create_entity_reference(param_type, import_map, file_path)
        
        # 9. Check parameter types from file-wide tracking
        if hasattr(self, 'param_types') and file_path in self.param_types:
            for param_key, param_type in self.param_types[file_path].items():
                if param_key.endswith(f":{name}") and param_type:
                    self.logger.debug(f"Found parameter type from file tracking: {param_key} -> {param_type}")
                    return self._create_entity_reference(param_type, import_map, file_path)
        
        # 10. Check object attribute types (for self.attr patterns)
        if hasattr(self, 'object_types'):
            obj_attr = f"self.{name}" if self.current_scope else None
            if obj_attr and obj_attr in self.object_types:
                attr_type = self.object_types[obj_attr]
                self.logger.debug(f"Found object attribute type: {obj_attr} -> {attr_type}")
                return self._create_entity_reference(attr_type, import_map, file_path)
        
        # 11. Additional recovery strategy: try fuzzy matching for similar names
        if '.' in name:
            # For qualified names, try matching the last part
            last_part = name.split('.')[-1]
            for entity_key, entity in self.entity_by_key.items():
                if entity.name == last_part:
                    self.logger.debug(f"Found potential match by name: {entity.name} (from {name})")
                    return self._entity_to_reference(entity, file_path)
        
        # Log detailed information about the failed resolution
        self.logger.debug(f"Entity resolution failed for: {name}")
        # if import_map:
            # self.logger.debug(f"Available imports: {list(import_map.keys())}")
        # self.logger.debug(f"Available entities in current file: {list(current_entities.keys())}")
        
        return None
    
    def _get_current_function_context(self) -> Optional[str]:
        """
        Get the current function context (class.method or function)
        for parameter type lookup.
        """
        if self.current_scope and self.current_function:
            return f"{self.current_scope}.{self.current_function}"
        return self.current_function

    def _entity_to_reference(self, entity: EntityInfo, current_file: str) -> EntityReference:
        """Creates an EntityReference from EntityInfo with proper localization"""
        return EntityReference(
            name=entity.name,
            key=self._generate_entity_key(
                entity.entity_type,
                entity.file_path,
                entity.name,
                entity.parent_name
            ),
            entity_type=entity.entity_type,
            parent_name=entity.parent_name,
            module_path=entity.file_path,
            is_local=entity.file_path == current_file
        )

    def _find_qualified_entity(self, qualified_name: str) -> Optional[EntityInfo]:
        """
        Enhanced method to find an entity by qualified name with strict context matching.
        
        Args:
            qualified_name: Fully qualified name like "Class.method"
            
        Returns:
            EntityInfo if found, None otherwise
        """
        normalized_name = qualified_name.replace('.', '/')
        
        # First try: exact match with fully qualified name
        for entity in self.repo_entities:
            entity_qualified = f"{entity.parent_name}.{entity.name}" if entity.parent_name else entity.name
            if entity_qualified == qualified_name:
                return entity
        
        # Second try: strict method matching with class context
        if '.' in qualified_name:
            class_name, method_name = qualified_name.split('.', 1)
            
            # Find methods that match both name and parent class exactly
            for entity in self.repo_entities:
                if (entity.entity_type == EntityType.METHOD.value and 
                    entity.name == method_name and 
                    entity.parent_name == class_name):
                    return entity
            
            # If no exact match found, avoid cross-class method matching
            self.logger.debug(f"No exact method match found for {qualified_name}")
        
        # Third try: for non-method entities or when class context is not critical
        # This is useful for variables, classes, etc.
        if not '.' in qualified_name or not any(e for e in self.repo_entities 
                                            if e.entity_type == EntityType.METHOD.value and 
                                                e.name == qualified_name.split('.')[-1]):
            for entity_key, entity in self.entity_by_key.items():
                key_parts = entity_key.split('/')
                if len(key_parts) < 2:
                    continue
                    
                entity_name = key_parts[-1]
                entity_parent = key_parts[-2] if len(key_parts) > 2 else None
                
                entity_qualified = f"{entity_parent}/{entity_name}" if entity_parent else entity_name
                if entity_qualified == normalized_name or entity_qualified.endswith('/' + normalized_name):
                    return entity
        
        return None

    def _find_repo_entity(self, entity_name: str, module_path: str) -> Optional[EntityInfo]:
        """
        Find an entity by name in a specific module path.
        Enhanced to handle more complex import patterns.
        
        Args:
            entity_name: Name of the entity to find
            module_path: Module path where the entity should be located
        
        Returns:
            EntityInfo if found, None otherwise
        """
        # Transform module path to possible file paths
        file_path = module_path.replace('.', '/') + '.py'
        init_path = module_path.replace('.', '/') + '/__init__.py'
        
        # Handle relative imports
        if module_path.startswith('.'):
            current_dir = os.path.dirname(self.current_file)
            dot_count = len(module_path) - len(module_path.lstrip('.'))
            remaining = module_path.lstrip('.')
            
            # Go up directories based on dot count
            for _ in range(dot_count - 1):
                current_dir = os.path.dirname(current_dir)
                
            # Construct relative path
            if remaining:
                rel_path = os.path.join(current_dir, remaining.replace('.', '/'))
            else:
                rel_path = current_dir
                
            file_path = rel_path + '.py'
            init_path = os.path.join(rel_path, '__init__.py')
        
        # Scan all entities
        for entity_path, entities in self.entity_by_path.items():
            if entity_path.endswith(file_path) or entity_path.endswith(init_path):
                # Direct match by name
                if entity_name in entities:
                    return entities[entity_name]
                
                # Handle the case if entity is class method
                if "." in entity_name:
                    parts = entity_name.split(".")
                    class_name, method_name = parts[0], parts[-1]
                    
                    # First try strict matching of both class name and method name
                    for entity in entities.values():
                        if entity.name == method_name and entity.parent_name == class_name:
                            self.logger.debug(f"Found exact match for {class_name}.{method_name} in {entity_path}")
                            return entity
                    
                    # If no exact match found, DO NOT return any partial match
                    # This prevents incorrect associations
                    self.logger.debug(f"No exact match found for {class_name}.{method_name} in {entity_path}")
                    return None
                
                # Try qualified name match
                for qualified_name, entity in entities.items():
                    if qualified_name.endswith(f".{entity_name}"):
                        return entity
        
        # If not found by exact path, try more flexible matching
        entity_name_parts = entity_name.split('.')
        last_part = entity_name_parts[-1]
        
        for entity_path, entities in self.entity_by_path.items():
            # Check if any part of the module path matches
            if any(part in entity_path for part in module_path.split('/')):
                # Try to find by last part of name
                for qualified_name, entity in entities.items():
                    if entity.name == last_part:
                        self.logger.debug(f"Found entity by name match: {entity.name} in {entity.file_path}")
                        return entity
        
        return None

    def _process_class_relations(self, tree: tree_sitter.Tree, content: str,
                                import_map: Dict[str, str],
                                file_path: str) -> List[RelationInfo]:
        """Process class inheritance relationships using node traversal."""
        relations: List[RelationInfo] = []
        stack = [tree.root_node]
        
        # For inheritance mapping in the current file
        file_inheritance_map: Dict[str, List[str]] = {}
        
        def extract_base_class_name(node: tree_sitter.Node) -> Optional[str]:
            """Recursively extract base class name with enhanced coverage."""
            if node.type == "identifier":
                return self._get_node_text(node, content)
            elif node.type == "attribute":
                obj = extract_base_class_name(node.child_by_field_name("object"))
                attr = extract_base_class_name(node.child_by_field_name("attribute"))
                return f"{obj}.{attr}" if obj and attr else None
            elif node.type == "subscript":
                base = extract_base_class_name(node.child_by_field_name("value"))
                return base
            elif node.type == "call":
                return extract_base_class_name(node.child_by_field_name("function"))
            elif node.type in ["tuple", "list", "dictionary"]:
                return None
            return None

        while stack:
            node = stack.pop()
            
            if node.type == "class_definition":
                # Extract class name
                class_name_node = node.child_by_field_name("name")
                if not class_name_node:
                    continue
                class_name = self._get_node_text(class_name_node, content)
                original_scope = self.current_scope
                self.current_scope = class_name  # Update current scope
                
                # Extract base classes
                base_class_nodes = []
                base_list = node.child_by_field_name("superclasses")
                if base_list and base_list.type == "argument_list":
                    base_class_nodes = list(base_list.children)
                
                # Initialize parent class list for the current class
                parent_classes = []
                file_inheritance_map[class_name] = parent_classes
                
                for base_node in base_class_nodes:
                    if base_node.type in [")", "(", ","]:
                        continue  # Skip syntax nodes
                    
                    base_name = extract_base_class_name(base_node)
                    if not base_name:
                        continue
                    
                    # Add to parent class list
                    parent_classes.append(base_name)
                    
                    # Create entity references
                    class_ref = self._create_entity_reference(
                        class_name, import_map, file_path)
                    parent_ref = self._create_entity_reference(
                        base_name, import_map, file_path)
                    
                    if class_ref and parent_ref:
                        relations.append(RelationInfo(
                            source=class_ref,
                            target=parent_ref,
                            relation_type=RelationType.INHERITS.value,
                            source_location=self._get_node_location(class_name_node),
                            target_location=self._get_node_location(base_node)
                        ))
                        self.logger.debug(f"Found inheritance: {class_name} -> {base_name}")
                
                self.current_scope = original_scope  # Restore original scope
            
            # Continue traversal
            stack.extend(reversed(node.children))
        
        # Update global inheritance mapping
        self.inheritance_map.update(file_inheritance_map)
        self.logger.debug(f"Updated inheritance map with {len(file_inheritance_map)} classes")
        
        return relations
    
    def _resolve_call_chain(self, node: tree_sitter.Node, content: str, file_path: str) -> Tuple[str, List[str], Optional[str]]:
        """
        Enhanced call chain resolver that supports:
        - Multi-level attribute access (obj.attr.subattr)
        - Chained calls (a().b().c())
        - Type tracking (using pre-recorded variable types)
        - Return type tracking for chain calls
        - Super() calls to parent class methods
        
        Args:
            node: The node to resolve
            content: Source code content
            file_path: Current file path

        Returns:
            Tuple of (full_chain, resolution_path, inferred_return_type)
        """
        resolution_path = []
        current_node = node
        parts = []
        type_hint = None  # For storing type inference information
        return_type = None  # For tracking return types in chain calls
        
        while current_node:
            self.logger.debug(f"Resolving node type: {current_node.type} [position:{current_node.start_point}]")
            
            if current_node.type == 'identifier':
                identifier = self._get_node_text(current_node, content)
                self.logger.debug(f"Found identifier: {identifier}")
                parts.append(identifier)
                resolution_path.append(f"identifier:{identifier}")
                
                # Special handling for 'cls' parameter in class methods
                if identifier == "cls":
                    # When 'cls' is used, it should always refer to the current class
                    current_class = self._get_current_class_scope(node, content)
                    if current_class:
                        type_hint = current_class
                        return_type = current_class
                        self.logger.debug(f"Setting cls type to current class: {type_hint}")
                # Handle super() identifier specifically
                elif identifier == "super" and len(parts) == 1:
                    # This might be a super() call, will be confirmed when we process the call node
                    resolution_path.append("potential_super_call")
                
                # Check if this identifier is a method reference first
                elif hasattr(self, 'method_references') and file_path in self.method_references and identifier in self.method_references[file_path]:
                    method_ref = self.method_references[file_path][identifier]
                    self.logger.debug(f"Found method reference for {identifier}: {method_ref}")
                    # Return the full method reference directly
                    return method_ref, resolution_path, None
                
                # Check if this identifier has a known type from various sources
                # 1. Variable type mapping
                elif identifier in self.variable_types.get(file_path, {}):
                    type_hint = self.variable_types[file_path][identifier]
                    self.logger.debug(f"Found type hint for {identifier}: {type_hint}")
                    # Set return type if this is a class name
                    if type_hint in [e.name for e in self.repo_entities if e.entity_type == EntityType.CLASS.value]:
                        return_type = type_hint

                # 2. Parameter type mapping
                elif hasattr(self, 'current_param_types') and self.current_param_types:
                    # Try current function context first
                    current_func = self._get_current_function_context()
                    if current_func:
                        param_key = f"{current_func}:{identifier}"
                        if param_key in self.current_param_types:
                            type_hint = self.current_param_types[param_key]
                            self.logger.debug(f"Found param type hint for {identifier}: {type_hint}")
                            return_type = type_hint
                    
                    # Try any matching parameter
                    for param_key, param_type in self.current_param_types.items():
                        if param_key.endswith(f":{identifier}"):
                            type_hint = param_type
                            self.logger.debug(f"Found param type hint for {identifier} from key {param_key}: {type_hint}")
                            return_type = type_hint
                            break
                # 3. Method reference type mapping
                elif hasattr(self, 'method_reference_types') and file_path in self.method_reference_types:
                    if identifier in self.method_reference_types[file_path]:
                        type_hint = self.method_reference_types[file_path][identifier]
                        self.logger.debug(f"Found method reference type for {identifier}: {type_hint}")
                        return_type = type_hint
                break
                    
            # Handle attribute access (obj.attr form)
            elif current_node.type == 'attribute':
                attr_node = current_node.child_by_field_name('attribute')
                obj_node = current_node.child_by_field_name('object')
                
                if attr_node:
                    attr_name = self._get_node_text(attr_node, content)
                    self.logger.debug(f"Found attribute: {attr_name}")
                    parts.append(attr_name)
                    resolution_path.append(f"attribute.attr:{attr_name}")
                
                # Continue with object node for further resolution
                current_node = obj_node
                resolution_path.append("attribute.object")
                
            # Handle call expressions (method() form)
            elif current_node.type == 'call':
                func_node = current_node.child_by_field_name('function')
                resolution_path.append(f"call.function")
                
                # Special handling for super() calls
                if func_node and func_node.type == 'identifier':
                    func_name = self._get_node_text(func_node, content)
                    if func_name == "super":
                        resolution_path.append("super_call")
                        
                        # Get current class
                        current_class = self._get_current_class_scope(current_node, content)
                        if current_class:
                            # Get parent classes
                            self.logger.debug(f"Looking for parent classes of {current_class}")
                            parent_classes = self._get_parent_classes(current_class, file_path, self.import_map)
                            
                            if parent_classes:
                                # Use the first parent class (in single inheritance)
                                parent_class = parent_classes[0]
                                self.logger.debug(f"Resolved super() to parent class: {parent_class}")
                                
                                # If this is part of a chain like super().method()
                                if current_node.parent and current_node.parent.type == 'attribute':
                                    # The parent class will be used when processing the attribute
                                    return_type = parent_class
                                else:
                                    # Otherwise, just return the parent class
                                    parts = [parent_class]
                                    break
                            else:
                                self.logger.warning(f"Could not find parent class for {current_class} in inheritance map: {self.inheritance_map}")
                        else:
                            self.logger.warning(f"super() call outside class context at {current_node.start_point}")
                
                # Check if this is a constructor call (Class())
                if func_node and func_node.type == 'identifier':
                    class_name = self._get_node_text(func_node, content)
                    # Track return type for constructors
                    if class_name in [e.name for e in self.repo_entities if e.entity_type == EntityType.CLASS.value]:
                        return_type = class_name
                    
                    # Check if this call is part of an assignment
                    if current_node.parent and current_node.parent.type == 'assignment':
                        var_node = current_node.parent.child_by_field_name('left')
                        if var_node:
                            var_name = self._get_node_text(var_node, content)
                            self.variable_types.setdefault(file_path, {})[var_name] = class_name
                            self.logger.debug(f"Tracked variable type: {var_name} -> {class_name}")
                            
                            # Track object attribute types for patterns like self.obj = Class()
                            if var_node.type == 'attribute' and var_node.child_by_field_name('object'):
                                obj_node = var_node.child_by_field_name('object')
                                if obj_node.type == 'identifier' and self._get_node_text(obj_node, content) == 'self':
                                    obj_attr = self._get_node_text(var_node, content)  # e.g., "self.obj"
                                    if hasattr(self, 'object_types'):
                                        self.object_types[obj_attr] = class_name
                                        self.logger.debug(f"Tracked object attribute type: {obj_attr} -> {class_name}")
                
                # For method calls, check if we can determine the return type
                elif func_node and func_node.type == 'attribute':
                    # Try to get method name and object
                    method_name = None
                    obj_expr = None
                    attr_node = func_node.child_by_field_name('attribute')
                    obj_node = func_node.child_by_field_name('object')
                    
                    if attr_node:
                        method_name = self._get_node_text(attr_node, content)
                    
                    if obj_node:
                        # Recursively resolve the object expression
                        obj_expr, _, obj_type = self._resolve_call_chain(obj_node, content, file_path)
                        
                        # If we know the object type, check for return type annotation
                        if obj_type:
                            qualified_method = f"{obj_type}.{method_name}" if method_name else None
                            if qualified_method and qualified_method in self.return_types:
                                return_type = self.return_types[qualified_method]
                                self.logger.debug(f"Found return type for {qualified_method}: {return_type}")
                            # If no explicit return type, but method returns 'self', use object type
                            elif method_name and self._is_method_returning_self(obj_type, method_name):
                                return_type = obj_type
                                self.logger.debug(f"Method {qualified_method} returns self, using type: {return_type}")
                
                current_node = func_node
                
            # Handle parenthesized expressions ((expr) form)
            elif current_node.type == 'parenthesized_expression':
                resolution_path.append("parenthesized_expression")
                if current_node.named_children:
                    current_node = current_node.named_children[0]
                else:
                    break
                    
            # Handle lambda expressions
            elif current_node.type == 'lambda':
                resolution_path.append("lambda")
                # Lambda doesn't have a meaningful chain part, but we want to track it
                parts.append("lambda")
                break

            # Handle unrecognized node types
            else:
                resolution_path.append(f"unhandled:{current_node.type}")
                break
                
        # Apply type inference for cls parameter - ensure it always refers to current class
        if len(parts) == 1 and parts[0] == "cls":
            current_class = self._get_current_class_scope(node, content)
            if current_class:
                full_chain = current_class
                self.logger.debug(f"Overriding cls reference to current class: {full_chain}")
                return full_chain, resolution_path, current_class
        
        # Rebuild call chain (reverse concatenation)
        full_chain = '.'.join(reversed(parts))
        self.logger.debug(f"Original call chain: {full_chain}")
        
        # Handle super().method() calls - if we identified a super call and have a return type (parent class)
        if "super_call" in resolution_path and return_type and current_node and current_node.parent:
            parent_node = current_node.parent
            if parent_node.type == 'attribute':
                attr_node = parent_node.child_by_field_name('attribute')
                if attr_node:
                    method_name = self._get_node_text(attr_node, content)
                    full_chain = f"{return_type}.{method_name}"
                    self.logger.debug(f"Resolved super().method() call to: {full_chain}")
        
        # Apply type inference (if available)
        if type_hint and len(parts) > 0:
            # For simple identifiers with type hints, we want the type itself
            if len(parts) == 1:
                inferred_chain = type_hint
            else:
                # For attribute access on typed variables, we want to qualify the chain
                inferred_chain = f"{type_hint}.{'.'.join(reversed(parts[:-1]))}"
            
            self.logger.debug(f"Applied type inference: {full_chain} => {inferred_chain}")
            full_chain = inferred_chain
        elif len(parts) > 1:
            # Check variable type mappings
            base_var = parts[-1]
            
            # Check direct variable types
            if base_var in self.variable_types.get(file_path, {}):
                var_type = self.variable_types[file_path][base_var]
                inferred_chain = f"{var_type}.{'.'.join(reversed(parts[:-1]))}"
                self.logger.debug(f"Applied variable type mapping: {base_var}->{var_type} => {inferred_chain}")
                full_chain = inferred_chain
                
            # Check object attribute types (e.g., self.obj)
            elif hasattr(self, 'object_types') and len(parts) >= 2 and f"{parts[-1]}.{parts[-2]}" in self.object_types:
                obj_attr = f"{parts[-1]}.{parts[-2]}"
                obj_type = self.object_types[obj_attr]
                inferred_chain = f"{obj_type}.{'.'.join(reversed(parts[:-2]))}"
                self.logger.debug(f"Applied object attribute type mapping: {obj_attr}->{obj_type} => {inferred_chain}")
                full_chain = inferred_chain
                
        # Handle self call chains
        if full_chain.startswith("self."):
            current_class = self._get_current_class_scope(node, content)
            if current_class:
                rewritten = full_chain.replace("self.", f"{current_class}.", 1)
                self.logger.debug(f"Rewrote self call chain: {full_chain} => {rewritten}")
                full_chain = rewritten
                
                # Check if this is a method with known return type
                if '.' in rewritten:
                    class_name, method_name = rewritten.split('.', 1)
                    qualified_method = f"{class_name}.{method_name}"
                    
                    if qualified_method in self.return_types:
                        return_type = self.return_types[qualified_method]
                        self.logger.debug(f"Found return type for self method: {qualified_method} -> {return_type}")
            else:
                self.logger.warning(f"Found self call outside class context: {full_chain}")

        # Check for chain calls with return type annotations
        if '.' in full_chain and not return_type:
            parts = full_chain.split('.')
            
            # Try to find return type for methods in the chain
            for i in range(1, len(parts)):
                prefix = '.'.join(parts[:i])
                method = parts[i]
                qualified_method = f"{prefix}.{method}"
                
                if qualified_method in self.return_types:
                    return_type = self.return_types[qualified_method]
                    self.logger.debug(f"Found return type for chain method: {qualified_method} -> {return_type}")
                    break
                
        self.logger.info(f"Final resolved call chain: {full_chain} [path: {resolution_path}, return_type: {return_type}]")
        return full_chain, resolution_path, return_type
    
    def _is_method_returning_self(self, class_name: str, method_name: str) -> bool:
        """
        Check if a method is likely to return self (for fluent interfaces).
        Uses both heuristics and return type information.
        
        Args:
            class_name: The class containing the method
            method_name: The method name to check
            
        Returns:
            True if the method likely returns self, False otherwise
        """
        # Common method prefixes that often indicate methods returning self
        fluent_prefixes = ['set_', 'add_', 'remove_', 'clear_', 'update_', 'with_', 'build']
        
        # Common method names that often return self
        fluent_methods = ['chain', 'configure', 'setup', 'initialize']
        
        # Check method name against common patterns
        if any(method_name.startswith(prefix) for prefix in fluent_prefixes) or method_name in fluent_methods:
            return True
            
        # Check if we have explicit return type information
        qualified_method = f"{class_name}.{method_name}"
        if qualified_method in self.return_types:
            return_type = self.return_types[qualified_method]
            # If return type matches class name or 'self', it returns self
            if return_type in [class_name, 'self', f"'{class_name}'"]:
                return True
        
        # Check if this is a builder pattern method
        if 'builder' in method_name.lower() or class_name.lower().endswith('builder'):
            return True
                
        return False

    def _process_call_relations(self, tree: tree_sitter.Tree, content: str,
                                import_map: Dict[str, str],
                                file_path: str) -> List[RelationInfo]:
        """
        Process method and function call relationships using AST traversal.
        
        Args:
            tree: The parsed AST tree
            content: The source code content
            import_map: Mapping of imported names to their module paths
            file_path: Path of the current file being processed
            
        Returns:
            List of call relations extracted from the code
        """
        def process_chain_call(node: tree_sitter.Node, object_type: str):
            """
            Process a call that is part of a chain call with known object type.
            
            Args:
                node: The call node to process
                object_type: The type of the object being called on
            """
            if node.type != 'call':
                return
                
            # Get caller context
            node_parent = self._get_node_parent(node)
            self.logger.debug(f"Processing chain call at {node.start_point} in scope: {node_parent}")
            
            # Create caller reference
            caller_ref = self._create_entity_reference(node_parent, import_map, file_path)
            if not caller_ref:
                self.logger.debug(f"Caller reference not found for scope: {node_parent}")
                return
                
            # Get the method name from the attribute
            func_node = node.child_by_field_name('function')
            if not func_node or func_node.type != 'attribute':
                self.logger.debug(f"Chain call does not have attribute function node")
                return
                
            attr_node = func_node.child_by_field_name('attribute')
            if not attr_node:
                return
                
            method_name = self._get_node_text(attr_node, content)
            qualified_method = f"{object_type}.{method_name}"
            self.logger.debug(f"Chain call method: {qualified_method}")
            
            # Try to resolve the method
            callee_ref = self._create_entity_reference(qualified_method, import_map, file_path)
            if not callee_ref:
                self.logger.debug(f"Failed to resolve chain call method: {qualified_method}")
                return
                
            # Create relation
            self.logger.info(f"Found chain call relation: {node_parent} -> {qualified_method}")
            relation = RelationInfo(
                source=caller_ref,
                target=callee_ref,
                relation_type=RelationType.CALLS.value,
                source_location=self._get_node_location(node),
                target_location=self._get_node_location(func_node),
                metadata={
                    'is_method': True,
                    'is_chain_call': True,
                    'chain_object_type': object_type
                }
            )
            
            # Add relation if it's valid
            if self._is_valid_relation(relation):
                relations.append(relation)
                
            # Check if this method also returns a type for further chain calls
            return_type = None
            if qualified_method in self.return_types:
                return_type = self.return_types[qualified_method]
            elif self._is_method_returning_self(object_type, method_name):
                return_type = object_type
                
            if return_type and node.parent and node.parent.type == 'attribute' and node.parent.parent and node.parent.parent.type == 'call':
                # Continue the chain
                self.logger.debug(f"Continuing chain call with type: {return_type}")
                process_chain_call(node.parent.parent, return_type)
                
        def process_lambda_expression(node: tree_sitter.Node, parent_scope: str):
            """
            Process a lambda expression and extract call relationships from it.
            Enhanced with better parameter type inference.
            
            Args:
                node: The lambda expression node
                parent_scope: The parent scope of the lambda expression
            """
            if node.type != 'lambda':
                return
                
            # Extract lambda parameters
            lambda_params = []
            lambda_body = None
            
            for child in node.children:
                if child.type == 'lambda_parameters':
                    for param_child in child.children:
                        if param_child.type == 'identifier':
                            lambda_params.append(self._get_node_text(param_child, content))
                elif child.type not in ['lambda', ':', 'lambda_parameters']:
                    # This should be the lambda body
                    lambda_body = child
                    
            # If no body or parameters found, return
            if not lambda_body:
                return
            
            # Enhanced: Check if this lambda is immediately called
            if node.parent and node.parent.type == 'parenthesized_expression' and node.parent.parent and node.parent.parent.type == 'call':
                call_node = node.parent.parent
                arg_list = call_node.child_by_field_name('argument_list')
                
                if arg_list and lambda_params:
                    # Try to infer parameter types from arguments
                    arg_index = 0
                    param_index = 0
                    
                    for child in arg_list.children:
                        if child.type in [',', '(', ')']:
                            continue  # Skip syntax nodes
                        
                        # We only care about arguments that correspond to lambda parameters
                        if param_index < len(lambda_params):
                            param_name = lambda_params[param_index]
                            
                            # Try to determine argument type
                            arg_type = None
                            
                            if child.type == 'call':
                                # If argument is a call, process it and try to get its return type
                                func_node = child.child_by_field_name('function')
                                if func_node:
                                    # Process the call first
                                    process_call_node(child, parent_scope)
                                    
                                    # Then try to determine its return type
                                    callee, _, return_type = self._resolve_call_chain(func_node, content, file_path)
                                    
                                    if return_type:
                                        arg_type = return_type
                                        self.logger.debug(f"Determined lambda param type from call return: {param_name} -> {arg_type}")
                                    elif '.' in callee:
                                        # If we know it's a class method call, use the class as type hint
                                        class_name = callee.split('.')[0]
                                        for entity in self.repo_entities:
                                            if entity.entity_type == EntityType.CLASS.value and entity.name == class_name:
                                                arg_type = class_name
                                                self.logger.debug(f"Inferred lambda param type from class: {param_name} -> {arg_type}")
                                                break
                            
                            # If we determined a type, store it
                            if arg_type:
                                self.variable_types.setdefault(file_path, {})[param_name] = arg_type
                            
                            param_index += 1
                        arg_index += 1
            
            # Process calls within lambda body
            if lambda_body.type == 'call':
                process_call_node(lambda_body, parent_scope)
            
            # Recursively process any nested structures in the lambda body
            for child in lambda_body.children:
                process_node(child, parent_scope)
                
            # Enhanced: If lambda body contains method calls on parameters, try to infer types
            if lambda_params and lambda_body:
                for param_name in lambda_params:
                    # If we don't already know the type
                    if param_name not in self.variable_types.get(file_path, {}):
                        # Look for method calls on this parameter
                        def find_method_calls(node, param_name):
                            if node.type == 'call':
                                func_node = node.child_by_field_name('function')
                                if func_node and func_node.type == 'attribute':
                                    obj_node = func_node.child_by_field_name('object')
                                    if obj_node and obj_node.type == 'identifier':
                                        obj_name = self._get_node_text(obj_node, content)
                                        if obj_name == param_name:
                                            attr_node = func_node.child_by_field_name('attribute')
                                            if attr_node:
                                                return self._get_node_text(attr_node, content)
                            return None
                        
                        # Recursively search for method calls
                        def search_node(node):
                            method_name = find_method_calls(node, param_name)
                            if method_name:
                                # Find classes that have this method
                                for entity in self.repo_entities:
                                    if (entity.entity_type == EntityType.METHOD.value and 
                                        entity.name == method_name and entity.parent_name):
                                        # Set parameter type to the parent class of this method
                                        self.variable_types.setdefault(file_path, {})[param_name] = entity.parent_name
                                        self.logger.debug(f"Inferred lambda param type from method call: {param_name} -> {entity.parent_name}")
                                        return True
                            
                            # Continue searching in children
                            for child in node.children:
                                if search_node(child):
                                    return True
                            return False
                        
                        # Start the search from lambda body
                        search_node(lambda_body)
                
        def process_list_comprehension(node: tree_sitter.Node, parent_scope: str):
            """
            Process a list comprehension and extract call relationships from it.
            Enhanced with better type inference for iteration variables.
            
            Args:
                node: The list comprehension node
                parent_scope: The parent scope of the list comprehension
            """
            if node.type != 'list_comprehension':
                return
                
            # Extract comprehension components
            expr_node = None
            for_in_clause = None
            
            for child in node.children:
                if child.type == 'for_in_clause':
                    for_in_clause = child
                elif child.type not in ['[', ']', 'for_in_clause']:
                    expr_node = child
                    
            # Process the for_in_clause first to establish iterator variable type
            if for_in_clause:
                iterator_var = None
                iterable_expr = None
                
                for child in for_in_clause.children:
                    if child.type == 'identifier' and not iterator_var:
                        iterator_var = self._get_node_text(child, content)
                    elif child.type in ['call', 'identifier', 'attribute'] and not iterable_expr:
                        iterable_expr = child
                        
                # Process the iterable expression first
                if iterable_expr and iterable_expr.type == 'call':
                    process_call_node(iterable_expr, parent_scope)
                    
                    # Try to determine element type from iterable with enhanced inference
                    if iterator_var:
                        func_node = iterable_expr.child_by_field_name('function')
                        if func_node:
                            iterable_callee, _, iterable_return_type = self._resolve_call_chain(func_node, content, file_path)
                            
                            # If the return type indicates a list or iterable, extract element type
                            if iterable_return_type:
                                element_type = None
                                
                                # Parse List[ElementType] format
                                if 'List[' in iterable_return_type or 'list[' in iterable_return_type:
                                    element_type = iterable_return_type.split('[')[1].split(']')[0]
                                # Parse other iterable formats
                                elif any(x in iterable_return_type for x in ['Iterable[', 'Sequence[', 'Collection[']):
                                    element_type = iterable_return_type.split('[')[1].split(']')[0]
                                    
                                # Set iterator variable type
                                if element_type:
                                    self.variable_types.setdefault(file_path, {})[iterator_var] = element_type
                                    self.logger.debug(f"Set list comprehension iterator type: {iterator_var} -> {element_type}")
                            
                            # Enhanced: Use heuristic inference when return type annotation is not available
                            if not iterable_return_type or not self.variable_types.get(file_path, {}).get(iterator_var):
                                # Check if method name suggests it returns items/collection
                                if func_node.type == 'attribute':
                                    attr_node = func_node.child_by_field_name('attribute')
                                    if attr_node:
                                        method_name = self._get_node_text(attr_node, content)
                                        # Heuristic for collection-returning methods
                                        if any(hint in method_name.lower() for hint in ['get_item', 'items', 'list', 'collection', 'all']):
                                            # Try to infer from object type or method context
                                            obj_node = func_node.child_by_field_name('object')
                                            if obj_node and obj_node.type == 'identifier':
                                                obj_name = self._get_node_text(obj_node, content)
                                                if obj_name == 'self' and self.current_scope:
                                                    # Look for class attributes that might be collections
                                                    for entity in self.repo_entities:
                                                        if entity.entity_type == EntityType.CLASS.value:
                                                            # Set a reasonable guess for iterator type
                                                            self.variable_types.setdefault(file_path, {})[iterator_var] = entity.name
                                                            self.logger.debug(f"Inferred list item type (heuristic): {iterator_var} -> {entity.name}")
                                                            break
                
                # If we still don't have a type for the iterator, try more aggressive inference
                if iterator_var and iterator_var not in self.variable_types.get(file_path, {}):
                    # Look for method calls on the iterator in the expression
                    if expr_node and expr_node.type == 'call':
                        func_node = expr_node.child_by_field_name('function')
                        if func_node and func_node.type == 'attribute':
                            obj_node = func_node.child_by_field_name('object')
                            if obj_node and obj_node.type == 'identifier':
                                iter_name = self._get_node_text(obj_node, content)
                                if iter_name == iterator_var:
                                    # Get the method being called
                                    attr_node = func_node.child_by_field_name('attribute')
                                    if attr_node:
                                        method_name = self._get_node_text(attr_node, content)
                                        # Find classes that have this method
                                        for entity in self.repo_entities:
                                            if (entity.entity_type == EntityType.METHOD.value and 
                                                entity.name == method_name and entity.parent_name):
                                                # Set iterator type to the parent class of this method
                                                self.variable_types.setdefault(file_path, {})[iterator_var] = entity.parent_name
                                                self.logger.debug(f"Inferred type from method call: {iterator_var} -> {entity.parent_name}")
                                                break
            
            # Process the expression part of the list comprehension
            if expr_node:
                process_node(expr_node, parent_scope)
                
        def process_conditional_expression(node: tree_sitter.Node, parent_scope: str):
            """
            Process a conditional expression (ternary operator) and extract call relationships from it.
            
            Args:
                node: The conditional expression node
                parent_scope: The parent scope of the conditional expression
            """
            if node.type != 'conditional_expression':
                return
            
            # Extract the condition, true branch and false branch
            condition = None
            true_branch = None
            false_branch = None
            
            # Find the components based on keywords
            for i, child in enumerate(node.children):
                if child.type == 'if':
                    # True branch is before 'if'
                    if i > 0:
                        true_branch = node.children[i-1]
                    # Condition is after 'if'
                    if i+1 < len(node.children):
                        condition = node.children[i+1]
                elif child.type == 'else':
                    # False branch is after 'else'
                    if i+1 < len(node.children):
                        false_branch = node.children[i+1]
                        
            # Process all components
            if condition:
                process_node(condition, parent_scope)
            if true_branch:
                process_node(true_branch, parent_scope)
            if false_branch:
                process_node(false_branch, parent_scope)
                
        def process_call_in_parenthesis(node: tree_sitter.Node, parent_scope: str):
            """
            Process a call expression inside parentheses, including lambda calls.
            
            Args:
                node: The parenthesized expression node
                parent_scope: The parent scope
            """
            if node.type != 'call' or not node.children:
                return
                
            func_node = node.child_by_field_name('function')
            if not func_node:
                return
                
            # Handle special case of lambda call: (lambda x: ...)(arg)
            if func_node.type == 'parenthesized_expression':
                lambda_node = None
                for child in func_node.children:
                    if child.type == 'lambda':
                        lambda_node = child
                        break
                        
                if lambda_node:
                    # Process the lambda expression
                    process_lambda_expression(lambda_node, parent_scope)
                    
                    # Process the arguments
                    arg_list = node.child_by_field_name('argument_list')
                    if arg_list:
                        for child in arg_list.children:
                            if child.type not in ['(', ')', ',']:
                                # Process each argument
                                process_node(child, parent_scope)
                                
                                # If this is a call, we want to create a parameter binding
                                # so that when we process the lambda body, we use the correct type
                                if child.type == 'call':
                                    arg_func = child.child_by_field_name('function')
                                    if arg_func:
                                        arg_callee, _, arg_return_type = self._resolve_call_chain(arg_func, content, file_path)
                                        if arg_return_type:
                                            # Get lambda parameters
                                            lambda_params = []
                                            for param_child in lambda_node.children:
                                                if param_child.type == 'lambda_parameters':
                                                    for p in param_child.children:
                                                        if p.type == 'identifier':
                                                            lambda_params.append(self._get_node_text(p, content))
                                                            
                                            # Bind parameter to argument type
                                            if lambda_params:
                                                param_name = lambda_params[0]  # Usually lambda has one parameter in this case
                                                # Create a temporary type binding for this lambda execution
                                                self.variable_types.setdefault(file_path, {})[param_name] = arg_return_type
                                                self.logger.debug(f"Set lambda parameter type: {param_name} -> {arg_return_type}")
                else:
                    # Regular parenthesized call
                    process_call_node(node, parent_scope)
            else:
                # Regular call
                process_call_node(node, parent_scope)
        
        def process_node(node: tree_sitter.Node, parent_scope: Optional[str] = None):
            """
            Process a node and extract call relationships from it and its children.
            
            Args:
                node: The node to process
                parent_scope: The parent scope
            """
            # If no parent scope provided, get it from the node
            if parent_scope is None:
                parent_scope = self._get_node_parent(node)
                
            # Process node based on its type
            if node.type == 'call':
                # If this is a call within a parenthesized expression (including lambda calls),
                # use the specialized handler
                if node.parent and node.parent.type == 'parenthesized_expression':
                    process_call_in_parenthesis(node, parent_scope)
                else:
                    process_call_node(node, parent_scope)
                    
            elif node.type == 'list_comprehension':
                process_list_comprehension(node, parent_scope)
                
            elif node.type == 'conditional_expression':
                process_conditional_expression(node, parent_scope)
                
            elif node.type == 'lambda':
                process_lambda_expression(node, parent_scope)
                
            # Process children
            for child in node.children:
                if child.type not in ['(', ')', '[', ']', '{', '}', ',', ';', ':', '.']:
                    process_node(child, parent_scope)
        """
        Above is the sub method
        """
        relations: List[RelationInfo] = []
        
        # Track object attribute types for this file
        self.object_types = getattr(self, 'object_types', {})
        self.logger.debug(f"_process_call_relations - object_types: {self.object_types}")
        
        # Initialize call context stack to track nested calls
        call_context_stack = []
        
        # Initialize parameter type tracking for current function context
        self.current_param_types = {}  # For tracking parameter types in current context
        
        # Set to track already processed nodes (to avoid duplicates)
        processed_nodes = set()
        
        def process_call_node(node: tree_sitter.Node, parent_context: Optional[str] = None):
            """
            Process individual call node with enhanced type inference and chain call support.
            Adds strict validation for method calls to ensure class context is respected,
            while providing fallback mechanisms for complex scenarios.
            
            Args:
                node: The call node to process
                parent_context: Optional parent context for nested calls (e.g., chain call return type)
            """
            # Avoid processing the same node multiple times (e.g., in conditional expressions)
            node_id = f"{node.start_point}:{node.end_point}"
            if node_id in processed_nodes:
                return
            processed_nodes.add(node_id)
            
            if node.type != 'call':
                return
                
            # Get caller context - use provided parent_context for chain calls or determine from node
            node_parent = parent_context or self._get_node_parent(node)
            
            # For global scope, use file name as context
            if not node_parent:
                file_name = os.path.basename(file_path).split('.')[0]
                node_parent = f"<{file_name}_global>"
                self.logger.debug(f"Using global scope context: {node_parent}")
                
            self.logger.debug(f"Processing call at {node.start_point} in scope: {node_parent}")
            
            # Create caller reference
            caller_ref = None
            if node_parent.startswith("<") and node_parent.endswith("_global>"):
                # Check if this is a method reference call
                if node.type == 'call' and node.child_by_field_name('function') and node.child_by_field_name('function').type == 'identifier':
                    func_name = self._get_node_text(node.child_by_field_name('function'), content)
                    if hasattr(self, 'method_references') and file_path in self.method_references and func_name in self.method_references[file_path]:
                        # For method reference calls, use the reference name as caller
                        caller_ref = EntityReference(
                            name=func_name,
                            key=f"Variable/{file_path}/{func_name}",
                            entity_type="Variable",
                            parent_name=None,
                            module_path=file_path,
                            is_local=True
                        )
                    else:
                        # For other global calls, use module as caller
                        module_name = node_parent.strip("<>").replace("_global", "")
                        caller_ref = EntityReference(
                            name=module_name,
                            key=f"Module/{file_path}/{module_name}",  # Include module name in key
                            entity_type="Module",
                            parent_name=None,
                            module_path=file_path,
                            is_local=True
                        )
                else:
                    # For other global calls, use module as caller
                    module_name = node_parent.strip("<>").replace("_global", "")
                    caller_ref = EntityReference(
                        name=module_name,
                        key=f"Module/{file_path}/{module_name}",  # Include module name in key
                        entity_type="Module",
                        parent_name=None,
                        module_path=file_path,
                        is_local=True
                    )
            else:
                caller_ref = self._create_entity_reference(node_parent, import_map, file_path)
                
            if not caller_ref:
                self.logger.debug(f"Caller reference not found for scope: {node_parent}")
                return
                
            # Check for super() calls specifically
            func_node = node.child_by_field_name('function')
            if func_node:
                # Case 1: Direct super() call
                if func_node.type == 'identifier' and self._get_node_text(func_node, content) == 'super':
                    self.logger.debug(f"Found direct super() call")
                    
                    # Get current class
                    current_class = self._get_current_class_scope(node, content)
                    if not current_class:
                        self.logger.warning(f"super() call outside class context")
                        return
                        
                    # Get parent classes
                    parent_classes = self._get_parent_classes(current_class, file_path, import_map)
                    if not parent_classes:
                        self.logger.warning(f"No parent classes found for {current_class}")
                        return
                        
                    # Use first parent class (simplification for multiple inheritance)
                    parent_class = parent_classes[0]
                    
                    # If this is a standalone super() call (rare), create a relation to the parent class constructor
                    if node.parent and node.parent.type != 'attribute':
                        parent_constructor = f"{parent_class}.__init__"
                        
                        # ENHANCED: Directly create the target reference without using _create_entity_reference
                        # to avoid potential mismatches
                        parent_constructor_ref = None
                        for entity in self.repo_entities:
                            if (entity.entity_type == EntityType.METHOD.value and 
                                entity.name == "__init__" and 
                                entity.parent_name == parent_class):
                                parent_constructor_ref = self._entity_to_reference(entity, file_path)
                                self.logger.debug(f"Found exact parent constructor match: {parent_class}.__init__")
                                break
                        
                        if parent_constructor_ref and caller_ref:
                            relation = RelationInfo(
                                source=caller_ref,
                                target=parent_constructor_ref,
                                relation_type=RelationType.CALLS.value,
                                source_location=self._get_node_location(node),
                                target_location=self._get_node_location(func_node),
                                metadata={
                                    'is_method': True,
                                    'is_super_call': True,
                                    'parent_class': parent_class
                                }
                            )
                            
                            if self._is_valid_relation(relation):
                                self.logger.info(f"Found super() call relation: {node_parent} -> {parent_constructor}")
                                relations.append(relation)
                        return
                
                # Case 2: super().method() pattern
                elif func_node.type == 'attribute':
                    obj_node = func_node.child_by_field_name('object')
                    if obj_node and obj_node.type == 'call':
                        inner_func = obj_node.child_by_field_name('function')
                        if inner_func and inner_func.type == 'identifier' and self._get_node_text(inner_func, content) == 'super':
                            self.logger.debug(f"Found super().method() call")
                            
                            # Get method name
                            attr_node = func_node.child_by_field_name('attribute')
                            if not attr_node:
                                return
                                
                            method_name = self._get_node_text(attr_node, content)
                            
                            # Get current class
                            current_class = self._get_current_class_scope(node, content)
                            if not current_class:
                                self.logger.warning(f"super() call outside class context")
                                return
                                
                            # Get parent classes
                            parent_classes = self._get_parent_classes(current_class, file_path, import_map)
                            if not parent_classes:
                                self.logger.warning(f"No parent classes found for {current_class}")
                                return
                                
                            # Use first parent class (simplification for multiple inheritance)
                            parent_class = parent_classes[0]
                            
                            # ENHANCED: Directly search for the parent method entity
                            # to avoid potential mismatches
                            parent_method_ref = None
                            for entity in self.repo_entities:
                                if (entity.entity_type == EntityType.METHOD.value and 
                                    entity.name == method_name and 
                                    entity.parent_name == parent_class):
                                    parent_method_ref = self._entity_to_reference(entity, file_path)
                                    self.logger.debug(f"Found exact parent method match: {parent_class}.{method_name}")
                                    break
                            
                            if parent_method_ref and caller_ref:
                                relation = RelationInfo(
                                    source=caller_ref,
                                    target=parent_method_ref,
                                    relation_type=RelationType.CALLS.value,
                                    source_location=self._get_node_location(node),
                                    target_location=self._get_node_location(func_node),
                                    metadata={
                                        'is_method': True,
                                        'is_super_call': True,
                                        'parent_class': parent_class
                                    }
                                )
                                
                                if self._is_valid_relation(relation):
                                    self.logger.info(f"Found super().method() call relation: {node_parent} -> {parent_class}.{method_name}")
                                    relations.append(relation)
                            return

            # Resolve call chain with enhanced type tracking
            callee_chain, resolution_path, return_type = self._resolve_call_chain(func_node, content, file_path)
            self.logger.debug(f"Raw callee chain: {callee_chain}")
            
            # Enhanced handling for method calls to prevent incorrect association
            callee_ref = None
            
            # For method calls (containing a dot), ensure class context is respected
            if '.' in callee_chain:
                # Split into class and method parts
                parts = callee_chain.split('.')
                class_name = parts[0]
                method_name = '.'.join(parts[1:])
                
                # First try: look for an exact match with the specific class
                for entity in self.repo_entities:
                    if (entity.entity_type == EntityType.METHOD.value and 
                        entity.name == method_name and 
                        entity.parent_name == class_name):
                        callee_ref = self._entity_to_reference(entity, file_path)
                        self.logger.debug(f"Found exact class method match: {class_name}.{method_name}")
                        break
                
                # If not found with exact match, try the standard entity reference creation
                if not callee_ref:
                    callee_ref = self._create_entity_reference(callee_chain, import_map, file_path)
                    
                    # If we found something, double-check it actually belongs to the expected class
                    if callee_ref and callee_ref.entity_type == EntityType.METHOD.value:
                        # Make sure the parent class matches what was specified in the call
                        if callee_ref.parent_name != class_name:
                            self.logger.debug(
                                f"Rejecting method call due to class mismatch: expected {class_name}.{method_name}, "
                                f"got {callee_ref.parent_name}.{callee_ref.name}"
                            )
                            callee_ref = None
            else:
                # For non-method calls, use standard resolution
                callee_ref = self._create_entity_reference(callee_chain, import_map, file_path)
            
            # Try different fallback resolution strategies if needed
            if not callee_ref:
                self.logger.debug(f"No direct match for {callee_chain}, trying alternatives...")
                
                # Try additional resolution strategies
                candidates = [callee_chain]
                
                # If simple name (no dots), try method references
                if '.' not in callee_chain and hasattr(self, 'method_references') and file_path in self.method_references:
                    if callee_chain in self.method_references[file_path]:
                        method_ref = self.method_references[file_path][callee_chain]
                        
                        # Try to resolve the method reference with type info
                        if hasattr(self, 'method_reference_types') and file_path in self.method_reference_types:
                            if callee_chain in self.method_reference_types[file_path]:
                                ref_type = self.method_reference_types[file_path][callee_chain]
                                if '.' in method_ref:
                                    method_name = method_ref.split('.')[-1]
                                    candidate = f"{ref_type}.{method_name}"
                                    self.logger.debug(f"Trying method reference with type: {candidate}")
                                    candidates.append(candidate)
                                    callee_ref = self._create_entity_reference(candidate, import_map, file_path)
                                    if callee_ref:
                                        callee_chain = candidate
                                        self.logger.debug(f"Resolved method reference with type: {callee_chain}")
                                        
                        # If still not resolved, try the direct method reference
                        if not callee_ref:
                            candidates.append(method_ref)
                            self.logger.debug(f"Trying method reference: {method_ref}")
                            callee_ref = self._create_entity_reference(method_ref, import_map, file_path)
                            if callee_ref:
                                callee_chain = method_ref
                                self.logger.debug(f"Resolved method reference: {callee_chain}")
                
                # If still not resolved and contains a dot, try object attribute type mappings
                if not callee_ref and '.' in callee_chain:
                    parts = callee_chain.split('.')
                    obj_part = parts[0]
                    method_part = '.'.join(parts[1:])
                    
                    # Check if we know the type of this object
                    obj_type = None
                    
                    # Check variable types
                    if obj_part in self.variable_types.get(file_path, {}):
                        obj_type = self.variable_types[file_path][obj_part]
                        candidate = f"{obj_type}.{method_part}"
                        self.logger.debug(f"Trying variable type mapping: {candidate}")
                        candidates.append(candidate)
                        callee_ref = self._create_entity_reference(candidate, import_map, file_path)
                        if callee_ref:
                            callee_chain = candidate
                            self.logger.debug(f"Resolved through variable type: {callee_chain}")
                    
                    # Check parameter types
                    if not callee_ref and hasattr(self, 'current_param_types'):
                        # Try to get parameter type from current context
                        current_func = self._get_current_function_context()
                        if current_func:
                            param_key = f"{current_func}:{obj_part}"
                            if param_key in self.current_param_types:
                                obj_type = self.current_param_types[param_key]
                                candidate = f"{obj_type}.{method_part}"
                                self.logger.debug(f"Trying parameter type mapping: {candidate}")
                                candidates.append(candidate)
                                callee_ref = self._create_entity_reference(candidate, import_map, file_path)
                                if callee_ref:
                                    callee_chain = candidate
                                    self.logger.debug(f"Resolved through parameter type: {callee_chain}")
                
                # Enhanced: Fallback for method calls on variables with unknown type
                if not callee_ref and '.' in callee_chain:
                    parts = callee_chain.split('.')
                    obj_part = parts[0]
                    method_name = parts[-1]
                    
                    # Try to find any method with this name and infer the class
                    method_entities = []
                    for entity in self.repo_entities:
                        if entity.entity_type == EntityType.METHOD.value and entity.name == method_name and entity.parent_name:
                            method_entities.append(entity)
                    
                    if method_entities:
                        # If we have only one matching method, use it
                        if len(method_entities) == 1:
                            entity = method_entities[0]
                            callee_ref = self._entity_to_reference(entity, file_path)
                            callee_chain = f"{entity.parent_name}.{entity.name}"
                            self.logger.debug(f"Inferred method call from unique method name: {callee_chain}")
                            
                            # Also update our variable type knowledge for future references
                            self.variable_types.setdefault(file_path, {})[obj_part] = entity.parent_name
                            self.logger.debug(f"Inferred variable type: {obj_part} -> {entity.parent_name}")
            
            # Enhanced: Special handling for method references (like handler = obj.method)
            if not callee_ref and node.child_by_field_name('function') and node.child_by_field_name('function').type == 'identifier':
                func_name = self._get_node_text(node.child_by_field_name('function'), content)
                
                # Check if this is a stored method reference
                if hasattr(self, 'method_references') and file_path in self.method_references and func_name in self.method_references[file_path]:
                    method_ref = self.method_references[file_path][func_name]
                    
                    # If the method reference is a qualified name (Class.method)
                    if '.' in method_ref:
                        parts = method_ref.split('.')
                        class_name = parts[0]
                        method_name = parts[-1]
                        
                        # Look for the method in repo entities
                        for entity in self.repo_entities:
                            if (entity.entity_type == EntityType.METHOD.value and 
                                entity.name == method_name and 
                                entity.parent_name == class_name):
                                callee_ref = self._entity_to_reference(entity, file_path)
                                callee_chain = method_ref
                                self.logger.debug(f"Resolved method reference call: {func_name}() -> {callee_chain}")
                                break
            
            # If still not resolved, give up
            if not callee_ref:
                self.logger.warning(f"Failed to resolve callee from candidates: {candidates}")
                return
        
            # Enhanced: Special handling for instantiation of subclasses
            if callee_ref and callee_ref.entity_type == EntityType.CLASS.value:
                # Check if this is a direct class instantiation
                if func_node and func_node.type == 'identifier':
                    class_name = self._get_node_text(func_node, content)
                    
                    # Make sure we're using the concrete class, not a parent class
                    for entity_key, entity in self.entity_by_key.items():
                        if (entity.entity_type == EntityType.CLASS.value and 
                            entity.name == class_name):
                            # Use the concrete class reference
                            callee_ref = self._entity_to_reference(entity, file_path)
                            callee_chain = class_name
                            self.logger.debug(f"Using concrete class for instantiation: {class_name}")
                            break
            
            # Create relation
            self.logger.info(f"Found call relation: {node_parent} -> {callee_chain}")
            relation = RelationInfo(
                source=caller_ref,
                target=callee_ref,
                relation_type=RelationType.CALLS.value,
                source_location=self._get_node_location(node),
                target_location=self._get_node_location(node.child_by_field_name('function')),
                metadata={
                    'is_method': '.' in callee_chain,
                    'resolution_path': resolution_path
                }
            )
            
            # Add relation if it's valid
            if self._is_valid_relation(relation):
                relations.append(relation)
            
            # Process arguments for nested calls and track parameter types
            arg_list = node.child_by_field_name('argument_list')
            if arg_list and callee_ref:
                # Get parameter information for the called function/method
                method_key = f"{callee_ref.parent_name}.{callee_ref.name}" if callee_ref.parent_name else callee_ref.name
                    
                arg_index = 0
                for child in arg_list.children:
                    if child.type in [',', '(', ')']:
                        continue  # Skip syntax nodes
                        
                    # Process argument and try to determine its type
                    arg_type = None
                    
                    if child.type == 'call':
                        # Process nested call with current call as context
                        process_call_node(child, node_parent)
                        
                        # Try to determine the return type of the nested call
                        func_node = child.child_by_field_name('function')
                        if func_node:
                            nested_callee, _, nested_return_type = self._resolve_call_chain(func_node, content, file_path)
                            if nested_return_type:
                                arg_type = nested_return_type
                                self.logger.debug(f"Determined argument type from nested call: {arg_type}")
                            
                            # Enhanced: If no return type but we know the callee, infer from class
                            if not nested_return_type and '.' in nested_callee:
                                class_name = nested_callee.split('.')[0]
                                # Use class name as type hint
                                for entity in self.repo_entities:
                                    if entity.entity_type == EntityType.CLASS.value and entity.name == class_name:
                                        arg_type = class_name
                                        self.logger.debug(f"Inferred argument type from class: {arg_type}")
                                        break
                    
                    # If we have parameter information for this function, track the argument type
                    if method_key:
                        param_key = f"{method_key}:param{arg_index}"
                        if arg_type:
                            self.current_param_types[param_key] = arg_type
                            self.logger.debug(f"Tracked parameter type: {param_key} -> {arg_type}")
                    
                    arg_index += 1
            
            # Handle chain calls - if this call returns a known type
            if node.parent:
                # Check chain call pattern: obj.method().next_method()
                if return_type and node.parent.type == 'attribute' and node.parent.parent and node.parent.parent.type == 'call':
                    # This call returns a type that will be used in the next call in the chain
                    self.logger.debug(f"Adding chain call context: {return_type} for call at {node.parent.parent.start_point}")
                    # Process next call in the chain with the return type as context
                    process_chain_call(node.parent.parent, return_type)
        
        def traverse(node: tree_sitter.Node):
            """
            Recursive traversal with enhanced handling for various node types.
            Delegates to process_node for actual processing.
            """
            process_node(node)
                    
        # Initialize tracking of object attribute types from assignments
        self._track_object_attributes(tree, content, file_path)
        self.logger.debug(f"After _track_object_attributes, object_types: {self.object_types}")
        
        # Start processing from the root
        self.logger.debug(f"Starting call relation processing for {file_path}")
        traverse(tree.root_node)
        self.logger.debug(f"Total call relations found: {len(relations)}")
        
        return relations

    def _is_valid_relation(self, relation: RelationInfo) -> bool:
        """
        Improved method to validate a relation with more strict checks.
        
        A relation is valid if:
        1. Source and target are not the same entity (prevents self-reference)
        2. Both source and target entities exist in repo_entities
        3. Special handling for module-level entities
        
        Args:
            relation: The relation to validate
            
        Returns:
            True if the relation is valid, False otherwise
        """
        # Prevent self-reference
        if relation.source.key == relation.target.key:
            self.logger.debug(f"Skipping self-reference: {relation.source.name}")
            return False
            
        # Prevent module source relations (except for INSTANTIATES relations)
        if relation.source.entity_type == "Module" and relation.relation_type != RelationType.INSTANTIATES.value:
            self.logger.debug(f"Skipping module source relation: {relation.source.name} -> {relation.target.name}")
            return False
            
        # Validate source and target entities exist
        source_valid = relation.source.key in self.entity_by_key
        target_valid = relation.target.key in self.entity_by_key
        
        if not source_valid or not target_valid:
            self.logger.debug(f"Invalid relation: {relation.source.name} -> {relation.target.name}")
            self.logger.debug(f"  Source key '{relation.source.key}' exists: {source_valid}")
            self.logger.debug(f"  Target key '{relation.target.key}' exists: {target_valid}")
            
        return source_valid and target_valid

    def _track_object_attributes(self, tree: tree_sitter.Tree, content: str, file_path: str) -> None:
        """
        Track object attribute types by analyzing assignments like self.obj = Class()
        Enhanced to better track method references and variable types.
        
        Args:
            tree: The parsed AST tree
            content: The source code content
            file_path: Path of the current file being processed
        """
        self.object_types = getattr(self, 'object_types', {})
        
        # Track method references (e.g., handler = obj.method)
        self.method_references = getattr(self, 'method_references', {})
        self.method_references.setdefault(file_path, {})
        
        # Track method reference types (handler -> ClassName)
        self.method_reference_types = getattr(self, 'method_reference_types', {})
        self.method_reference_types.setdefault(file_path, {})
            
        def extract_class_from_node(node: tree_sitter.Node) -> Optional[str]:
            """Extract class name or type from a node that might contain a class instantiation"""
            if not node:
                return None
                
            if node.type == "call":
                # Direct call: Class()
                func_node = node.child_by_field_name("function")
                if func_node:
                    if func_node.type == "identifier":
                        return self._get_node_text(func_node, content)
                    elif func_node.type == "attribute":
                        # Handle obj.method() where method returns a class instance
                        obj_node = func_node.child_by_field_name("object")
                        attr_node = func_node.child_by_field_name("attribute")
                        if obj_node and attr_node:
                            obj_name = self._get_node_text(obj_node, content)
                            attr_name = self._get_node_text(attr_node, content)
                            # Try to find type from object's method return type
                            if obj_name == "self" and self.current_scope:
                                method_key = f"{self.current_scope}.{attr_name}"
                                if method_key in self.return_types:
                                    return self.return_types[method_key]
                            # Look for object's type to determine method return type
                            elif obj_name in self.variable_types.get(file_path, {}):
                                obj_type = self.variable_types[file_path][obj_name]
                                method_key = f"{obj_type}.{attr_name}"
                                if method_key in self.return_types:
                                    return self.return_types[method_key]
                        return None
            elif node.type == "identifier":
                # Simple variable reference, check its type
                var_name = self._get_node_text(node, content)
                if var_name in self.variable_types.get(file_path, {}):
                    return self.variable_types[file_path][var_name]
                
            return None
        
        def process_assignment(node: tree_sitter.Node) -> None:
            """Process assignment node to extract object attribute types with enhanced tracking"""
            if node.type != 'assignment':
                return
                
            # Get left side (variable or attribute being assigned)
            left = node.child_by_field_name('left')
            if not left:
                return
                
            # Get right side (value being assigned)
            right = node.child_by_field_name('right')
            if not right:
                return
                
            # Enhanced: Track variable assignment to object method (handler = obj.method)
            if left.type == 'identifier' and right.type == 'attribute':
                var_name = self._get_node_text(left, content)
                attr_text = self._get_node_text(right, content)
                
                # Store the method reference with enhanced tracking
                self.method_references[file_path][var_name] = attr_text
                self.logger.debug(f"Tracked method reference: {var_name} -> {attr_text}")
                
                # Try to determine the class type of the object
                obj_node = right.child_by_field_name('object')
                if obj_node:
                    obj_type = None
                    
                    # If obj is a direct call like MyClass()
                    if obj_node.type == 'call':
                        class_name = extract_class_from_node(obj_node)
                        if class_name:
                            obj_type = class_name
                    
                    # If obj is an identifier like obj in obj.method
                    elif obj_node.type == 'identifier':
                        obj_name = self._get_node_text(obj_node, content)
                        if obj_name in self.variable_types.get(file_path, {}):
                            obj_type = self.variable_types[file_path][obj_name]
                        elif obj_name == 'self' and self.current_scope:
                            obj_type = self.current_scope
                        
                        # Enhanced: If we don't know the type but have a method name,
                        # try to find classes that have this method
                        if not obj_type and right.child_by_field_name('attribute'):
                            method_name = self._get_node_text(right.child_by_field_name('attribute'), content)
                            for entity in self.repo_entities:
                                if (entity.entity_type == EntityType.METHOD.value and 
                                    entity.name == method_name and entity.parent_name):
                                    obj_type = entity.parent_name
                                    self.logger.debug(f"Inferred object type from method: {obj_name} -> {obj_type}")
                                    break
                    
                    # Store method reference type information
                    if obj_type:
                        self.method_reference_types[file_path][var_name] = obj_type
                        self.logger.debug(f"Tracked method reference type: {var_name} -> {obj_type}")
                
            # Track self.attr = Class() patterns
            elif left.type == 'attribute':
                obj_node = left.child_by_field_name('object')
                attr_node = left.child_by_field_name('attribute')
                
                if obj_node and attr_node and obj_node.type == 'identifier':
                    obj_name = self._get_node_text(obj_node, content)
                    attr_name = self._get_node_text(attr_node, content)
                    
                    # Focus on self.attr patterns
                    if obj_name == 'self':
                        obj_attr = f"self.{attr_name}"
                        
                        # Check if right side is a call (Class instantiation)
                        if right.type == 'call':
                            class_name = extract_class_from_node(right)
                            if class_name:
                                self.object_types[obj_attr] = class_name
                                self.logger.debug(f"Tracked object attribute type: {obj_attr} -> {class_name}")
                                
                        # Check if right side is an identifier with known type
                        elif right.type == 'identifier':
                            var_name = self._get_node_text(right, content)
                            if var_name in self.variable_types.get(file_path, {}):
                                var_type = self.variable_types[file_path][var_name]
                                self.object_types[obj_attr] = var_type
                                self.logger.debug(f"Tracked object attribute type from variable: {obj_attr} -> {var_type}")
                        
                        # Handle other assignment patterns
                        else:
                            class_name = extract_class_from_node(right)
                            if class_name:
                                self.object_types[obj_attr] = class_name
                                self.logger.debug(f"Tracked object attribute type from expression: {obj_attr} -> {class_name}")
        
        def traverse(node: tree_sitter.Node) -> None:
            """Traverse AST to find assignments with enhanced tracking"""
            if node.type == 'assignment':
                process_assignment(node)
                
            # Continue traversal
            for child in node.children:
                traverse(child)
                
        # Start traversal from root
        traverse(tree.root_node)

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

    def _get_node_location(self, node: tree_sitter.Node) -> Tuple[int, int]:
        """Return (line, column) for a node (1-indexed)."""
        return (node.start_point[0] + 1, node.start_point[1] + 1)
    
    def _get_node_identifier(self, node: tree_sitter.Node) -> Optional[str]:
        """Get identifier name from node"""
        for child in node.children:
            if child.type == "identifier":
                if hasattr(child, "text") and child.text is not None:
                    return child.text.decode("utf-8", errors="ignore")
        return None

    def _get_node_parent(self, node: tree_sitter.Node) -> str:
        """
        Get the parent scope (class or function) of a node.
        For nodes at module level, returns empty string.
        """
        parent = node.parent
        parent_name = ""
        while parent:
            if parent.type in ["class_definition", "function_definition", "async_function_definition"]:
                pname = self._get_node_identifier(parent)
                if pname:
                    parent_name = pname if parent_name == "" else pname + "." + parent_name
            parent = parent.parent
        
        return parent_name

    def _resolve_call_target(self, node: tree_sitter.Node, content: str) -> str:
        """
        Resolve the callee of a function call.
        For attribute calls, includes handling for self.method calls.
        """
        if node.type == "identifier":
            return self._get_node_text(node, content)
        elif node.type == "attribute":
            obj = node.child_by_field_name("object")
            attr = node.child_by_field_name("attribute")
            if obj and attr:
                obj_name = self._get_node_text(obj, content)
                attr_name = self._get_node_text(attr, content)
                if obj_name == "self":
                    current_class = self._get_current_class_scope(node, content)
                    if current_class:
                        return f"{current_class}.{attr_name}"
                    return f"self.{attr_name}"
                return f"{obj_name}.{attr_name}"
        return ""

    def _get_current_class_scope(self, node: tree_sitter.Node, content: str) -> Optional[str]:
        """Return the name of the enclosing class if any."""
        current = node.parent
        while current:
            if current.type == "class_definition":
                for child in current.children:
                    if child.type == "identifier":
                        return self._get_node_text(child, content)
            current = current.parent
        return None
    
    def _process_global_var_relations(self, tree: tree_sitter.Tree, content: str,
                                    import_map: Dict[str, str],
                                    file_path: str) -> List[RelationInfo]:
        """
        Process global variable references and modifications.
        
        Args:
            tree: The parsed AST tree
            content: The source code content
            import_map: Mapping of imported names to their module paths
            file_path: Path of the current file being processed
            
        Returns:
            List of global variable relations extracted from the code
        """
        relations: List[RelationInfo] = []
        processed_nodes = set()  # Track processed nodes to avoid duplicates
        
        # Get all global variables in this file
        global_vars = {}
        for entity_key, entity in self.entity_by_key.items():
            if (entity.entity_type == "Variable" and 
                entity.file_path == file_path and 
                not entity.parent_name):  # No parent means it's a global variable
                global_vars[entity.name] = entity
        
        self.logger.debug(f"Global variables in {file_path}: {list(global_vars.keys())}")
        
        def is_assignment_target(node: tree_sitter.Node) -> bool:
            """Check if a node is the target of an assignment."""
            parent = node.parent
            if not parent:
                return False
                
            if parent.type == 'assignment':
                left = parent.child_by_field_name('left')
                return left == node
                
            return False
        
        def process_identifier(node: tree_sitter.Node, scope: str):
            """Process an identifier node that might be a global variable."""
            # Skip if already processed
            node_id = f"{node.start_point}:{node.end_point}"
            if node_id in processed_nodes:
                return
            processed_nodes.add(node_id)
            
            # Get the identifier name
            var_name = self._get_node_text(node, content)
            
            # Check if it's a global variable
            if var_name not in global_vars:
                return
                
            # Get the global variable entity
            var_entity = global_vars[var_name]
            var_ref = self._entity_to_reference(var_entity, file_path)
            
            # Get the caller context
            caller_scope = scope or self._get_node_parent(node)
            
            # Skip if the identifier is in global scope (would create self-reference)
            if not caller_scope:
                return
                
            # Create caller reference
            caller_ref = self._create_entity_reference(caller_scope, import_map, file_path)
            if not caller_ref:
                self.logger.debug(f"Caller reference not found for scope: {caller_scope}")
                return
                
            # Determine relation type (USES or MODIFIES)
            relation_type = RelationType.USES.value
            if is_assignment_target(node):
                relation_type = RelationType.MODIFIES.value
                
            # Create relation
            relation = RelationInfo(
                source=caller_ref,
                target=var_ref,
                relation_type=relation_type,
                source_location=self._get_node_location(node),
                target_location=self._get_node_location(node),
                metadata={}
            )
            
            # Add relation if it's valid
            if self._is_valid_relation(relation):
                relation_name = "MODIFIES" if relation_type == RelationType.MODIFIES.value else "USES"
                self.logger.info(f"Found global variable relation: {caller_scope} {relation_name} {var_name}")
                relations.append(relation)
        
        def traverse(node: tree_sitter.Node, scope: Optional[str] = None):
            """Traverse the AST to find global variable references and modifications."""
            # Get the current scope if not provided
            if scope is None:
                scope = self._get_node_parent(node)
                
            # Process current node if it's an identifier
            if node.type == 'identifier':
                process_identifier(node, scope)
                
            # Process children
            for child in node.children:
                # Skip syntax nodes
                if child.type not in ['(', ')', '[', ']', '{', '}', ',', ';', ':', '.']:
                    traverse(child, scope)
        
        # Start traversal from the root
        traverse(tree.root_node)
        
        return relations
    
    def _process_global_function_calls(self, tree: tree_sitter.Tree, content: str,
                                    import_map: Dict[str, str],
                                    file_path: str) -> List[RelationInfo]:
        """
        Process global function call relationships.
        
        Args:
            tree: The parsed AST tree
            content: The source code content
            import_map: Mapping of imported names to their module paths
            file_path: Path of the current file being processed
            
        Returns:
            List of global function call relations extracted from the code
        """
        relations: List[RelationInfo] = []
        processed_nodes = set()  # Track processed nodes to avoid duplicates
        
        # Get all global functions in the repository
        global_funcs = {}
        for entity in self.repo_entities:
            if (entity.entity_type == EntityType.METHOD.value and 
                not entity.parent_name):  # No parent means it's a global function
                global_funcs[entity.name] = entity
        
        self.logger.debug(f"Global functions found: {list(global_funcs.keys())}")
        
        def process_call(node: tree_sitter.Node, scope: str):
            """Process a potential global function call."""
            # Skip if already processed
            node_id = f"{node.start_point}:{node.end_point}"
            if node_id in processed_nodes:
                return
            processed_nodes.add(node_id)
            
            # Skip if not a call node
            if node.type != 'call':
                return
                
            # Get the function node
            func_node = node.child_by_field_name('function')
            if not func_node or func_node.type != 'identifier':
                return
                
            # Get the function name
            func_name = self._get_node_text(func_node, content)
            
            # Check if this is a global function
            if func_name not in global_funcs:
                return
                
            # Get the global function entity
            func_entity = global_funcs[func_name]
            func_ref = self._entity_to_reference(func_entity, file_path)
            
            # Get the caller context
            caller_scope = scope or self._get_node_parent(node)
            
            # Skip if the call is in global scope (would create self-reference)
            if not caller_scope:
                return
                
            # Create caller reference
            caller_ref = self._create_entity_reference(caller_scope, import_map, file_path)
            if not caller_ref:
                self.logger.debug(f"Caller reference not found for scope: {caller_scope}")
                return
                
            # Create relation
            relation = RelationInfo(
                source=caller_ref,
                target=func_ref,
                relation_type=RelationType.CALLS.value,
                source_location=self._get_node_location(node),
                target_location=self._get_node_location(func_node),
                metadata={}
            )
            
            # Add relation if it's valid
            if self._is_valid_relation(relation):
                self.logger.info(f"Found global function call relation: {caller_scope} -> {func_name}")
                relations.append(relation)
        
        def traverse(node: tree_sitter.Node, scope: Optional[str] = None):
            """Traverse the AST to find global function calls."""
            # Get the current scope if not provided
            if scope is None:
                scope = self._get_node_parent(node)
                
            # Process current node if it's a call
            if node.type == 'call':
                process_call(node, scope)
                
            # Process children
            for child in node.children:
                # Skip syntax nodes
                if child.type not in ['(', ')', '[', ']', '{', '}', ',', ';', ':', '.']:
                    traverse(child, scope)
        
        # Start traversal from the root
        traverse(tree.root_node)
        
        return relations
    
    def _process_instantiation_relations(self, tree: tree_sitter.Tree, content: str,
                                        import_map: Dict[str, str],
                                        file_path: str) -> List[RelationInfo]:
        """
        Process class instantiation relationships using node traversal.
        
        Args:
            tree: The parsed AST tree
            content: The source code content
            import_map: Mapping of imported names to their module paths
            file_path: Path of the current file being processed
            
        Returns:
            List of instantiation relations extracted from the code
        """
        relations: List[RelationInfo] = []
        processed_nodes = set()  # Track processed nodes to avoid duplicates
        
        def process_instantiation(node: tree_sitter.Node, scope: str):
            """Process a potential class instantiation node."""
            # Skip if already processed
            node_id = f"{node.start_point}:{node.end_point}"
            if node_id in processed_nodes:
                return
            processed_nodes.add(node_id)
            
            # Check if this is a call node
            if node.type != 'call':
                return
                
            # Get the function node (potential class name)
            func_node = node.child_by_field_name('function')
            if not func_node or func_node.type != 'identifier':
                return
                
            # Get the class name
            class_name = self._get_node_text(func_node, content)
            
            # Check if this is a class (not a function call)
            class_ref = None
            for entity in self.repo_entities:
                if entity.entity_type == EntityType.CLASS.value and entity.name == class_name:
                    class_ref = self._entity_to_reference(entity, file_path)
                    self.logger.debug(f"Found exact class match for instantiation: {class_name}")
                    break
                    
            if not class_ref:
                return  # Not a class instantiation
                
            # Get the caller context
            caller_scope = scope or self._get_node_parent(node)
            
            # For global scope, use file name as context
            if not caller_scope:
                file_name = os.path.basename(file_path).split('.')[0]
                caller_scope = f"<{file_name}_global>"
                
            # Create caller reference
            caller_ref = None
            if caller_scope.startswith("<") and caller_scope.endswith("_global>"):
                # For global scope, use module as caller
                module_name = caller_scope.strip("<>").replace("_global", "")
                caller_ref = EntityReference(
                    name=module_name,
                    key=f"Module/{file_path}/{module_name}",
                    entity_type="Module",
                    parent_name=None,
                    module_path=file_path,
                    is_local=True
                )
            else:
                caller_ref = self._create_entity_reference(caller_scope, import_map, file_path)
                
            if not caller_ref:
                self.logger.debug(f"Caller reference not found for scope: {caller_scope}")
                return
                
            # Create instantiation relation
            relation = RelationInfo(
                source=caller_ref,
                target=class_ref,
                relation_type=RelationType.INSTANTIATES.value,
                source_location=self._get_node_location(node),
                target_location=self._get_node_location(func_node),
                metadata={}
            )
            
            # Add relation if it's valid
            if self._is_valid_relation(relation):
                self.logger.info(f"Found instantiation relation: {caller_scope} -> {class_name}")
                relations.append(relation)
        
        def traverse(node: tree_sitter.Node, scope: Optional[str] = None):
            """Traverse the AST to find class instantiations."""
            # Get the current scope if not provided
            if scope is None:
                scope = self._get_node_parent(node)
                
            # Process current node if it's a call
            if node.type == 'call':
                process_instantiation(node, scope)
                
            # Process children
            for child in node.children:
                # Skip syntax nodes
                if child.type not in ['(', ')', '[', ']', '{', '}', ',', ';', ':', '.']:
                    traverse(child, scope)
        
        # Start traversal from the root
        traverse(tree.root_node)
        
        return relations