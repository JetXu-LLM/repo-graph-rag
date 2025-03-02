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
        self._build_entity_maps()

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
        self.variable_types[file_path] = {}
        self.param_types[file_path] = {}
        self.current_scope = None
        self.current_function = None

        # Track variable assignments, function parameters and return types.
        self._track_assignments(tree, content)
        self._track_function_params(tree, content)
        self._track_return_types(tree, content)

        import_map = self._build_import_map(tree, content, file_path)

        self.logger.debug(f"Import map: {import_map}")

        relations: List[RelationInfo] = []
        seen_relations = set()

        def add_relation(relation: RelationInfo):
            rk = RelationKey(relation.source.key, relation.target.key, relation.relation_type)
            if rk not in seen_relations:
                seen_relations.add(rk)
                relations.append(relation)

        for rel in self._process_class_relations(tree, content, import_map, file_path):
            add_relation(rel)
        for rel in self._process_call_relations(tree, content, import_map, file_path):
            add_relation(rel)

        return [r for r in relations if self._is_valid_relation(r)]

    def _is_valid_relation(self, relation: RelationInfo) -> bool:
        """A relation is valid if both source and target keys exist in repo_entities."""
        source_valid = relation.source.key in self.entity_by_key
        target_valid = relation.target.key in self.entity_by_key
        
        if not source_valid or not target_valid:
            self.logger.debug(f"Invalid relation: {relation.source.name} -> {relation.target.name}")
            self.logger.debug(f"  Source key '{relation.source.key}' exists: {source_valid}")
            self.logger.debug(f"  Target key '{relation.target.key}' exists: {target_valid}")
            
            if not target_valid:
                target_name = relation.target.name
                similar_keys = [k for k in self.entity_by_key.keys() if target_name in k]
                if similar_keys:
                    self.logger.debug(f"  Similar target keys found: {similar_keys}")
        
        return source_valid and target_valid

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
        3. Import-alias expanded resolution
        4. Hierarchical parent/child relationships
        5. Global qualified name matching
        6. Variable type inference
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

        # 3. Resolve through import aliases with enhanced path matching
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

        # 4. Check hierarchical parent/child relationships
        parts = name.split('.')
        for i in range(len(parts)-1, 0, -1):
            parent_name, child_name = '.'.join(parts[:i]), '.'.join(parts[i:])
            if parent_entity := current_entities.get(parent_name):
                candidate_name = f"{parent_entity.name}.{child_name}"
                if entity := self._find_qualified_entity(candidate_name):
                    self.logger.debug(f"Found hierarchical match: {entity.parent_name} & {entity.name}")
                    return self._entity_to_reference(entity, file_path)

        # 5. Global qualified name search
        if entity := self._find_qualified_entity(name):
            self.logger.debug(f"Found global qualified match: {entity.parent_name} & {entity.name}")
            return self._entity_to_reference(entity, file_path)

        # 6. Check variable type inference
        if var_type := self.variable_types.get(file_path, {}).get(name):
            self.logger.debug(f"Attempting type inference: {name} -> {var_type}")
            return self._create_entity_reference(var_type, import_map, file_path)

        self.logger.debug(f"Entity resolution failed for: {name}")
        return None

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
        Searches all repo entities for matching qualified name.
        Uses entity_by_key for efficient lookup instead of scanning repo_entities.
        """
        normalized_name = qualified_name.replace('.', '/')
        
        # Try to find direct match in entity_by_key
        for entity_key, entity in self.entity_by_key.items():
            key_parts = entity_key.split('/')
            if len(key_parts) < 2:
                continue
                
            # Extract entity name and parent from key
            entity_name = key_parts[-1]
            entity_parent = key_parts[-2] if len(key_parts) > 2 else None
            
            # Check for match with qualified name
            entity_qualified = f"{entity_parent}/{entity_name}" if entity_parent else entity_name
            if entity_qualified == normalized_name or entity_qualified.endswith('/' + normalized_name):
                return entity
                
        # Fallback to original method if no match found
        for entity in self.repo_entities:
            entity_qualified = f"{entity.parent_name}.{entity.name}" if entity.parent_name else entity.name
            if entity_qualified == qualified_name:
                return entity
                
        return None

    def _find_repo_entity(self, entity_name: str, module_path: str) -> Optional[EntityInfo]:
        """
        Find an entity by name in a specific module path.
        
        Args:
            entity_name: Name of the entity to find
            module_path: Module path where the entity should be located
        
        Returns:
            EntityInfo if found, None otherwise
        """
        # Transform module path to possible file path
        file_path = module_path.replace('.', '/') + '.py'
        init_path = module_path.replace('.', '/') + '/__init__.py'
        
        # Scan all entities
        for entity_path, entities in self.entity_by_path.items():
            if entity_path.endswith(file_path) or entity_path.endswith(init_path):
                if entity_name in entities:
                    return entities[entity_name]
                
                # Handle the case if entity is class method
                if "." in entity_name:
                    parts = entity_name.split(".")
                    class_name, method_name = parts[0], parts[-1]
                    
                    for entity in entities.values():
                        if entity.name == method_name and entity.parent_name == class_name:
                            return entity
        
        return None

    def _process_class_relations(self, tree: tree_sitter.Tree, content: str,
                                import_map: Dict[str, str],
                                file_path: str) -> List[RelationInfo]:
        """Process class inheritance relationships using node traversal."""
        relations: List[RelationInfo] = []
        stack = [tree.root_node]
        
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
                
                for base_node in base_class_nodes:
                    if base_node.type in [")", "(", ","]:
                        continue  # Skip syntax nodes
                    
                    base_name = extract_base_class_name(base_node)
                    if not base_name:
                        continue
                    
                    # Create entity references
                    class_ref = self._create_entity_reference(
                        class_name, import_map, file_path)
                    parent_ref = self._create_entity_reference(
                        base_name, import_map, file_path)
                    
                    if class_ref and parent_ref:
                        relations.append(RelationInfo(
                            source=class_ref,
                            target=parent_ref,
                            relation_type=RelationType.INHERITS,
                            source_location=self._get_node_location(class_name_node),
                            target_location=self._get_node_location(base_node)
                        ))
                        self.logger.debug(f"Found inheritance: {class_name} -> {base_name}")
                
                self.current_scope = original_scope  # Restore original scope
            
            # Continue traversal
            stack.extend(reversed(node.children))
        
        return relations

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
        relations: List[RelationInfo] = []
        
        # Track object attribute types for this file
        # Format: {"self.obj": "InternalClass"}
        self.object_types = getattr(self, 'object_types', {})
        self.logger.debug(f"_process_call_relations - object_types: {self.object_types}")
        
        # Initialize call context stack to track nested calls
        call_context_stack = []

        def _resolve_call_chain(node: tree_sitter.Node) -> Tuple[str, List[str], Optional[str]]:
            """
            Enhanced call chain resolver that supports:
            - Multi-level attribute access (obj.attr.subattr)
            - Chained calls (a().b().c())
            - Type tracking (using pre-recorded variable types)
            - Return type tracking for chain calls
            
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
                
                # Handle identifier nodes (base elements)
                if current_node.type == 'identifier':
                    identifier = self._get_node_text(current_node, content)
                    self.logger.debug(f"Found identifier: {identifier}")
                    parts.append(identifier)
                    resolution_path.append(f"identifier:{identifier}")
                    
                    # Check if this identifier has a known type
                    if identifier in self.variable_types.get(file_path, {}):
                        type_hint = self.variable_types[file_path][identifier]
                        self.logger.debug(f"Found type hint for {identifier}: {type_hint}")
                        # Set return type if this is a class name
                        if type_hint in [e.name for e in self.repo_entities if e.entity_type == EntityType.CLASS.value]:
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
                            obj_expr, _, obj_type = _resolve_call_chain(obj_node)
                            
                            # If we know the object type, check for return type annotation
                            if obj_type:
                                qualified_method = f"{obj_type}.{method_name}" if method_name else None
                                if qualified_method and qualified_method in self.return_types:
                                    return_type = self.return_types[qualified_method]
                                    self.logger.debug(f"Found return type for {qualified_method}: {return_type}")
                                # If no explicit return type, but method returns 'self', use object type
                                elif method_name and _is_method_returning_self(obj_type, method_name):
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
                    
            # Rebuild call chain (reverse concatenation)
            full_chain = '.'.join(reversed(parts))
            self.logger.debug(f"Original call chain: {full_chain}")
            
            # Apply type inference (if available)
            if type_hint and len(parts) > 0:
                inferred_chain = f"{type_hint}.{full_chain}"
                self.logger.debug(f"Applied type inference: {full_chain} => {inferred_chain}")
                full_chain = inferred_chain
            elif len(parts) > 1:
                # Check variable type mappings
                base_var = parts[-1]
                
                # Check direct variable types
                if base_var in self.variable_types.get(file_path, {}):
                    var_type = self.variable_types[file_path][base_var]
                    inferred_chain = f"{var_type}.{'.'.join(parts[:-1])}"
                    self.logger.debug(f"Applied variable type mapping: {base_var}->{var_type} => {inferred_chain}")
                    full_chain = inferred_chain
                    
                # Check object attribute types (e.g., self.obj)
                elif len(parts) >= 2 and f"{parts[-1]}.{parts[-2]}" in self.object_types:
                    obj_attr = f"{parts[-1]}.{parts[-2]}"
                    obj_type = self.object_types[obj_attr]
                    inferred_chain = f"{obj_type}.{'.'.join(parts[:-2])}"
                    self.logger.debug(f"Applied object attribute type mapping: {obj_attr}->{obj_type} => {inferred_chain}")
                    full_chain = inferred_chain
                    
            # Handle self call chains
            if full_chain.startswith("self."):
                current_class = self._get_current_class_scope(node, content)
                if current_class:
                    rewritten = full_chain.replace("self.", f"{current_class}.", 1)
                    self.logger.debug(f"Rewrote self call chain: {full_chain} => {rewritten}")
                    full_chain = rewritten
                else:
                    self.logger.warning(f"Found self call outside class context: {full_chain}")
                    
            self.logger.info(f"Final resolved call chain: {full_chain} [path: {resolution_path}, return_type: {return_type}]")
            return full_chain, resolution_path, return_type
        
        def _is_method_returning_self(class_name: str, method_name: str) -> bool:
            """
            Check if a method is likely to return self (for fluent interfaces).
            This is a heuristic - methods like set_*, add_*, etc. often return self.
            
            Args:
                class_name: The class containing the method
                method_name: The method name to check
                
            Returns:
                True if the method likely returns self, False otherwise
            """
            # Common method prefixes that often indicate methods returning self
            fluent_prefixes = ['set_', 'add_', 'remove_', 'clear_', 'update_', 'with_']
            
            # Check method name against common patterns
            if any(method_name.startswith(prefix) for prefix in fluent_prefixes):
                return True
                
            # Check if we have explicit return type information
            qualified_method = f"{class_name}.{method_name}"
            if qualified_method in self.return_types:
                return_type = self.return_types[qualified_method]
                # If return type matches class name or 'self', it returns self
                if return_type in [class_name, 'self']:
                    return True
                    
            return False

        def process_call_node(node: tree_sitter.Node, parent_context: Optional[str] = None):
            """
            Process individual call node with enhanced type inference and chain call support.
            
            Args:
                node: The call node to process
                parent_context: Optional parent context for nested calls
            """
            if node.type != 'call':
                return
                
            # Get caller context - use provided parent_context for chain calls
            node_parent = parent_context or self._get_node_parent(node)
            self.logger.debug(f"Processing call at {node.start_point} in scope: {node_parent}")
            
            # Handle calls in global scope
            if not node_parent:
                # For global scope, use file path as context
                file_name = os.path.basename(file_path).split('.')[0]
                node_parent = f"<{file_name}_global>"
                self.logger.debug(f"Using global scope context: {node_parent}")
                
            # Create caller reference
            caller_ref = None
            if node_parent.startswith("<") and node_parent.endswith("_global>"):
                # For global scope, create a synthetic caller reference
                caller_ref = EntityReference(
                    name=node_parent.strip("<>").replace("_global", ""),
                    key=f"Module/{file_path}",
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
                
            # Resolve call chain with enhanced type tracking
            callee_chain, resolution_path, return_type = _resolve_call_chain(node.child_by_field_name('function'))
            self.logger.debug(f"Raw callee chain: {callee_chain}")
            
            # Handle self calls
            if callee_chain.startswith("self."):
                current_class = self._get_current_class_scope(node, content)
                if current_class:
                    callee_chain = callee_chain.replace("self.", f"{current_class}.", 1)
                    self.logger.debug(f"Rewrote self call to: {callee_chain}")
                else:
                    self.logger.warning("Found self call outside class context")
                    
            # Try different resolution strategies
            resolved = False
            candidate_names = [callee_chain]
            callee_ref = None
            
            # Case 1: Check if full chain exists
            callee_ref = self._create_entity_reference(callee_chain, import_map, file_path)
            if callee_ref:
                self.logger.debug(f"Direct match found for {callee_chain}")
                resolved = True
            else:
                self.logger.debug(f"No direct match for {callee_chain}, trying alternatives...")
                
            # Case 2: Check variable type mapping for object calls
            if not resolved and '.' in callee_chain:
                obj_part, method_part = callee_chain.rsplit('.', 1)
                self.logger.debug(f"Checking variable types for object: {obj_part}")
                
                # Check direct variable types
                if obj_part in self.variable_types.get(file_path, {}):
                    var_type = self.variable_types[file_path][obj_part]
                    candidate = f"{var_type}.{method_part}"
                    candidate_names.append(candidate)
                    self.logger.debug(f"Trying variable type mapping: {candidate}")
                    callee_ref = self._create_entity_reference(candidate, import_map, file_path)
                    if callee_ref:
                        resolved = True
                        callee_chain = candidate
                        
                # Check object attribute types
                elif obj_part in self.object_types:
                    obj_type = self.object_types[obj_part]
                    candidate = f"{obj_type}.{method_part}"
                    candidate_names.append(candidate)
                    self.logger.debug(f"Trying object attribute type mapping: {candidate}")
                    callee_ref = self._create_entity_reference(candidate, import_map, file_path)
                    if callee_ref:
                        resolved = True
                        callee_chain = candidate
                        
                # For patterns like obj.method where obj is a parameter
                elif '.' in obj_part:
                    # Try to resolve parameter types
                    param_parts = obj_part.split('.')
                    if len(param_parts) == 2 and param_parts[0] == 'self':
                        # Handle self.obj.method pattern
                        attr_name = param_parts[1]
                        self_attr = f"self.{attr_name}"
                        
                        # Check if we have type info for this attribute
                        if self_attr in self.object_types:
                            obj_type = self.object_types[self_attr]
                            candidate = f"{obj_type}.{method_part}"
                            candidate_names.append(candidate)
                            self.logger.debug(f"Trying self attribute type mapping: {candidate}")
                            callee_ref = self._create_entity_reference(candidate, import_map, file_path)
                            if callee_ref:
                                resolved = True
                                callee_chain = candidate
                                
            # Case 3: Check imported modules
            if not resolved and '.' in callee_chain:
                module_part, func_part = callee_chain.split('.', 1)
                self.logger.debug(f"Checking imports for module: {module_part}")
                
                if module_part in import_map:
                    import_path = import_map[module_part]
                    self.logger.debug(f"Found import mapping: {module_part} -> {import_path}")
                    candidate = f"{import_path}.{func_part}" if import_path else func_part
                    candidate_names.append(candidate)
                    callee_ref = self._create_entity_reference(func_part, import_map, import_path)
                    if callee_ref:
                        resolved = True
                        callee_chain = candidate

            # Final check for resolution
            if not callee_ref:
                self.logger.warning(f"Failed to resolve callee from candidates: {candidate_names}")
                return
                
            # Create relation
            self.logger.info(f"Found call relation: {node_parent} -> {callee_chain}")
            relations.append(RelationInfo(
                source=caller_ref,
                target=callee_ref,
                relation_type=RelationType.CALLS,
                source_location=self._get_node_location(node),
                target_location=self._get_node_location(node.child_by_field_name('function')),
                metadata={
                    'is_method': '.' in callee_chain,
                    'resolution_path': resolution_path
                }
            ))
            
            # Process arguments for nested calls
            arg_list = node.child_by_field_name('argument_list')
            if arg_list:
                for child in arg_list.children:
                    if child.type == 'call':
                        # Process nested call with current call as context
                        process_call_node(child, node_parent)
                        
            # Handle chain calls - if this call returns a known type
            if return_type and node.parent and node.parent.type == 'attribute':
                # This is part of a chain call like obj.method().next_method()
                # We've already processed this call, but we need to track the return type
                # for the next call in the chain
                parent_attr = node.parent.parent
                if parent_attr and parent_attr.type == 'call':
                    # Add return type to context for the next call
                    call_context_stack.append((parent_attr, return_type))
                    self.logger.debug(f"Added chain call context: {return_type} for call at {parent_attr.start_point}")

        def traverse(node: tree_sitter.Node):
            """
            Recursive traversal with enhanced chain call handling
            """
            # Check if this is a call node
            if node.type == 'call':
                # Check if this call is part of a chain call context
                chain_context = None
                matching_contexts = [(i, ctx) for i, ctx in enumerate(call_context_stack) if ctx[0] == node]
                if matching_contexts:
                    i, (_, context_type) = matching_contexts[0]
                    chain_context = context_type
                    # Remove this context as we're processing it now
                    call_context_stack.pop(i)
                    self.logger.debug(f"Using chain call context: {chain_context} for call at {node.start_point}")

                # Process the call node
                process_call_node(node, chain_context)
                    
            # Process child nodes
            for child in node.children:
                traverse(child)

        # Initialize tracking of object attribute types from assignments
        self._track_object_attributes(tree, content, file_path)
        self.logger.debug(f"After _track_object_attributes, object_types: {self.object_types}")
        
        # Start processing
        self.logger.debug(f"Starting call relation processing for {file_path}")
        traverse(tree.root_node)
        self.logger.debug(f"Total call relations found: {relations}")
        
        return [r for r in relations if self._is_valid_relation(r)]

    def _track_object_attributes(self, tree: tree_sitter.Tree, content: str, file_path: str) -> None:
        """
        Track object attribute types by analyzing assignments like self.obj = Class()
        This enhances type tracking for method calls on object attributes.
        
        Args:
            tree: The parsed AST tree
            content: The source code content
            file_path: Path of the current file being processed
        """
        self.object_types = getattr(self, 'object_types', {})
            
        def process_assignment(node: tree_sitter.Node) -> None:
            """Process assignment node to extract object attribute types"""
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
                
            # We're interested in patterns like self.attr = Class()
            if left.type == 'attribute':
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
                            func_node = right.child_by_field_name('function')
                            if func_node and func_node.type == 'identifier':
                                class_name = self._get_node_text(func_node, content)
                                self.object_types[obj_attr] = class_name
                                self.logger.debug(f"Tracked object attribute type: {obj_attr} -> {class_name}")
                                
                        # Check if right side is an identifier with known type
                        elif right.type == 'identifier':
                            var_name = self._get_node_text(right, content)
                            if var_name in self.variable_types.get(file_path, {}):
                                var_type = self.variable_types[file_path][var_name]
                                self.object_types[obj_attr] = var_type
                                self.logger.debug(f"Tracked object attribute type from variable: {obj_attr} -> {var_type}")
            
        def traverse(node: tree_sitter.Node) -> None:
            """Traverse AST to find assignments"""
            if node.type == 'assignment':
                process_assignment(node)
                
            # Continue traversal
            for child in node.children:
                traverse(child)
                
        # Start traversal from root
        traverse(tree.root_node)

    def _get_node_text(self, node: tree_sitter.Node, content: str) -> str:
        """Return the text content of a node."""
        return content[node.start_byte:node.end_byte]

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
        parent = node.parent
        parent_name = ""
        while parent:
            if parent.type in ["class_definition", "function_definition"]:
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