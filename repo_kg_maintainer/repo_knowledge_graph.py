from arango import ArangoClient
from datetime import datetime
import logging
from typing import Dict, Any, Optional
import re
from llama_github.data_retrieval.github_entities import Repository
from code_analyze.code_analyzer import CodeAnalyzer, EntityType, EntityInfo, RelationType
from utils import normalize_datetime

class RepoKnowledgeGraph:
    def __init__(self, repo: Repository,
                 host: str = 'http://localhost:8529', 
                 database: str = 'repo_kg',
                 username: str = 'root',
                 password: str = 'root',
                 base_path: str = ''):
        """
        Initializes Knowledge Graph connection.
        """
        self.repo = repo
        self.repo_entities = []
        self.analyzer = CodeAnalyzer(repo)

        # Set up logging
        self.logger = logging.getLogger(__name__)
        logging.basicConfig(level=logging.INFO)
        
        # Base path to the repository files
        self.base_path = base_path
        
        # Connect to ArangoDB
        self.client = ArangoClient(hosts=host)
        
        # Connect to database; create if it doesn't exist
        sys_db = self.client.db('_system', username=username, password=password)
        if not sys_db.has_database(database):
            sys_db.create_database(database)
        
        self.db = self.client.db(database, username=username, password=password)
        
        # Initialize collections
        self._init_collections()

    def _init_collections(self):
        """
        Initializes required collections and edge collections.
        """
        # Entity collections - using EntityType enum values
        for entity_type in EntityType:
            if self.db.has_collection(entity_type.value):
                self.db.delete_collection(entity_type.value)
            if not self.db.has_collection(entity_type.value):
                self.db.create_collection(entity_type.value)
        
        # Relationship collections - using RelationType enum values and CONTAINS
        edge_collections = ['CONTAINS']
        for relation_type in RelationType:
            edge_collections.append(relation_type.value)
        
        for edge_collection in edge_collections:
            if self.db.has_collection(edge_collection):
                self.db.delete_collection(edge_collection)
            if not self.db.has_collection(edge_collection):
                self.db.create_collection(edge_collection, edge=True)

    def _generate_key(self, path: str) -> str:
        """
        Generates a unique and valid ArangoDB key based on the path.
        """
        # Sanitize the path to remove invalid characters
        sanitized = re.sub(r'[^a-zA-Z0-9\-_]', '_', path)

        key = sanitized
        # Ensure key length does not exceed 254 characters
        if len(key) > 254:
            key = sanitized[:251]
        return key

    def _upsert_entity(self, collection: str, key: str, data: Dict[str, Any]) -> str:
        """
        Creates an entity and returns its ID.
        """
        collection = self.db.collection(collection)
        document = {'_key': key, **data}
        try:
            # Check if document exists
            if collection.has(key):
                # Update existing document
                result = collection.update(document, return_new=True, silent=False)
            else:
                # Insert new document
                result = collection.insert(document, return_new=True)
            
            return result['_id']
        except Exception as e:
            self.logger.error(f"Error inserting document into {collection.name}: {e}")
            return f"{collection.name}/{key}"

    def _upsert_relationship(self, from_id: str, to_id: str, 
                            relationship_type: str, properties: Optional[Dict] = None,
                            delete: bool = False) -> Optional[Dict]:
        """
        Manages relationships between vertices in ArangoDB.
        If delete=False (default), performs an upsert operation:
            - If relationship exists: updates the properties
            - If relationship doesn't exist: creates new relationship
        If delete=True, removes the relationship if it exists.
        
        Args:
            from_id (str): Source vertex ID
            to_id (str): Target vertex ID
            relationship_type (str): Name of the edge collection
            properties (Optional[Dict]): Properties to be set on the edge
            delete (bool): If True, deletes the relationship; if False, performs upsert
        
        Returns:
            Optional[Dict]: Returns the edge document on success, None on failure
        """
        edge_collection = self.db.collection(relationship_type)
        
        try:
            if delete:
                # Delete the edge if exists
                aql = """
                FOR e IN @@collection
                    FILTER e._from == @from_id AND e._to == @to_id
                    REMOVE e IN @@collection
                    RETURN OLD
                """
                bind_vars = {
                    '@collection': relationship_type,
                    'from_id': from_id,
                    'to_id': to_id
                }
                cursor = self.db.aql.execute(aql, bind_vars=bind_vars)
                return next(cursor, None)
            
            else:
                # Perform upsert operation
                # Prepare the document with required fields
                edge_doc = {
                    '_from': from_id,
                    '_to': to_id
                }
                if properties:
                    edge_doc.update(properties)
                
                # Use AQL for atomic upsert operation
                aql = """
                UPSERT { _from: @from_id, _to: @to_id }
                INSERT @doc
                UPDATE @doc
                IN @@collection
                RETURN NEW
                """
                bind_vars = {
                    '@collection': relationship_type,
                    'from_id': from_id,
                    'to_id': to_id,
                    'doc': edge_doc
                }
                cursor = self.db.aql.execute(aql, bind_vars=bind_vars)
                return next(cursor, None)

        except Exception as e:
            operation = "deleting" if delete else "upserting"
            self.logger.error(
                f"Error {operation} edge in {edge_collection.name}: "
                f"from {from_id} to {to_id}: {str(e)}"
            )
            return None

    def create_repository(self, repo_name: str, description: str = "", 
                          primary_language: str = "", content_summary: str = "") -> str:
        """
        Creates a Repository node.
        """
        repo_data = {
            'repository_id': repo_name,
            'description': description,
            'primary_language': primary_language,
            'content_summary': content_summary,
            'created_at': datetime.now().isoformat()
        }
        repo_key = self._generate_key(repo_name)
        return self._upsert_entity('Repository', repo_key, repo_data)

    def process_repo_structure(self, repo_name: str, structure: Dict, 
                               parent_path: str = "", parent_id: Optional[str] = None):
        """
        Recursively processes the repository structure.
        """
        if parent_id is None:
            # Create repository node
            parent_id = self.create_repository(repo_name)
            self.logger.info(f"Created repository {repo_name} with ID {parent_id}")
        
        self.logger.info(f"Processing structure at path: '{parent_path}' with parent_id: '{parent_id}'")
        
        for name, info in structure.items():
            current_path = f"{parent_path}/{name}" if parent_path else name
            self.logger.debug(f"Processing '{name}' at path '{current_path}'")
            
            if 'children' in info:
                self.logger.info(f"Processin0g directory: {current_path}")
                # This is a module/directory
                module_data = {
                    'module_name': name,
                    'type': self._determine_module_type(current_path),
                    'description': f"Module containing {len(info['children'])} items",
                    'content_summary': "",  # Placeholder; can be generated using LLM
                }
                module_key = self._generate_key(current_path)
                module_id = self._upsert_entity('Module', module_key, module_data)
                
                self.logger.info(f"Created module '{name}' with ID '{module_id}'")
                
                # Create CONTAINS relationship
                self._upsert_relationship(parent_id, module_id, 'CONTAINS', 
                                          {'containment_type': 'physical', 'is_required': True})
                
                # Recursively process child items
                self.process_repo_structure(repo_name, info['children'], 
                                            current_path, module_id)
            else:
                self.logger.info(f"Processing file: {current_path}")
                file_extension = name.split('.')[-1].lower() if '.' in name else ''
                last_modified = normalize_datetime(self.repo._repo.get_contents(info['path']).last_modified)

                # Generate the key for file lookup
                file_key = self._generate_key(info['path'])

                # Get File collection
                file_collection = self.db.collection('File')
                
                # Check if file exists and compare last_modified
                if file_collection.has(file_key):
                    existing_file = file_collection.get(file_key)
                    existing_last_modified = existing_file.get('last_modified')
                    
                    # Skip if existing file is newer or same
                    if existing_last_modified and existing_last_modified >= last_modified:
                        self.logger.info(f"Skipping file '{name}' as it hasn't been modified")

                        # Query all entities associated with this file
                        file_id = f"File/{file_key}"
                        aql = """
                        FOR entity IN 1..1 OUTBOUND @file_id CONTAINS
                        FILTER entity._collection NOT IN @excluded_collections
                        RETURN entity
                        """
                        
                        # Exclude high-level structural entities and only include code-level entities
                        excluded_collections = [
                            EntityType.REPOSITORY.value,
                            EntityType.MODULE.value,
                            EntityType.FILE.value
                        ]
                        
                        cursor = self.db.aql.execute(aql, bind_vars={
                            'file_id': file_id,
                            'excluded_collections': excluded_collections
                        })
                        
                        # Convert query results to EntityInfo objects and add to repo_entities
                        for doc in cursor:
                            self.repo_entities.append(EntityInfo(
                                name=doc.get('name', ''),
                                entity_type=doc.get('entity_type', ''),
                                parent_name=doc.get('parent_name', ''),
                                parent_type=doc.get('parent_type', ''),
                                is_exported=doc.get('is_exported', False),
                                modifiers=doc.get('modifiers', []),
                                content=doc.get('content', ''),
                                description=doc.get('description', ''),
                                complexity=doc.get('complexity', 0)
                            ))

                        continue

                file_entity_created = False

                if CodeAnalyzer.is_supported_extension(file_extension):
                    try:
                        file_entity, code_entities = self.analyzer.get_file_entities(file_path = info['path'])
                        self.logger.info(f"File '{name}' is supported. Extracted entities: {len(code_entities)}")
                    except Exception as e:
                        self.logger.error(f"Error processing file {info['path']}: {str(e)}")
                        continue

                    if file_entity:
                        # File entity
                        file_data = {
                            'file_path': info['path'],
                            'file_name': name,
                            'size': info.get('size', 0),
                            'file_type': file_extension,
                            'last_modified': last_modified,
                            'content': file_entity.content,
                            'description': file_entity.description,
                        }
                        file_key = self._generate_key(info['path'])
                        file_id = self._upsert_entity('File', file_key, file_data)
                        file_entity_created = True
                        
                        self.logger.info(f"Created file '{name}' with ID '{file_id}'")
                        
                        # Create CONTAINS relationship
                        self._upsert_relationship(parent_id, file_id, 'CONTAINS', 
                                                {'containment_type': 'physical', 'is_required': True})

                    for entity in code_entities:
                        if entity.entity_type in ['Class', 'Method', 'Interface', 'Enum']:
                            # Entity data
                            entity_data = {
                                'name': entity.name,
                                'parent_name': entity.parent_name,
                                'parent_type': entity.parent_type,
                                'entity_type': entity.entity_type,
                                'description': entity.description,
                                'complexity': entity.complexity,
                                'file_path': info['path'],
                                'is_exported': entity.is_exported,
                                'modifiers': entity.modifiers,
                                'content': entity.content,
                            }
                            entity_key = self._generate_key(f"{entity.entity_type}/{current_path}/{(entity.parent_name+'/') if entity.parent_name else ''}{entity.name}")
                            entity_id = self._upsert_entity(entity.entity_type, entity_key, entity_data)
                            self.logger.info(f"Created {entity.entity_type.lower()} '{entity_key}' with ID '{entity_id}'")

                            has_parent = False
                            if entity.parent_name != "":
                                parent_collection = self.db.collection(entity.parent_type)
                                parent_key = self._generate_key(f"{entity.parent_type}/{current_path}/{entity.parent_name}")
                                parent_entity = parent_collection.get(parent_key)
                                if parent_entity:
                                    self._upsert_relationship(parent_entity['_id'], entity_id, 'CONTAINS', 
                                                            {'containment_type': 'physical', 'is_required': True})
                                    has_parent = True
                                    self.repo_entities.append(entity)
                                    self.logger.info(f"Created relationship between '{parent_entity['_id']}' and '{entity_id}'")
                            
                            # Create CONTAINS relationship
                            if not has_parent:
                                self._upsert_relationship(file_id, entity_id, 'CONTAINS', 
                                                        {'containment_type': 'physical', 'is_required': True})
                        elif entity.entity_type == 'Variable':
                            # Variable entity
                            variable_data = {
                                'name': entity.name,
                                'entity_type': entity.entity_type,
                                'parent_name': entity.parent_name,
                                'parent_type': entity.parent_type,
                                'file_path': info['path'],
                                'is_exported': entity.is_exported,
                                'modifiers': entity.modifiers,
                                'content': entity.content,
                            }
                            variable_key = self._generate_key(f"{entity.entity_type}/{current_path}/{entity.name}")
                            variable_id = self._upsert_entity('Variable', variable_key, variable_data)
                            self.repo_entities.append(entity)
                            # Create CONTAINS relationship
                            self._upsert_relationship(file_id, variable_id, 'CONTAINS', 
                                                    {'containment_type': 'physical', 'is_required': True})
                if not file_entity_created:
                    # This is a file
                    file_data = {
                        'file_path': info['path'],
                        'file_name': name,
                        'size': info.get('size', 0),
                        'file_type': file_extension,
                        'last_modified': last_modified,
                        'content': self.repo.get_file_content(info['path']),
                        'description': f"File of type {name.split('.')[-1] if '.' in name else 'unknown'}",
                    }
                    file_key = self._generate_key(info['path'])
                    file_id = self._upsert_entity('File', file_key, file_data)
                    
                    self.logger.info(f"Created file '{name}' with ID '{file_id}'")
                
                    # Create CONTAINS relationship
                    self._upsert_relationship(parent_id, file_id, 'CONTAINS', 
                                            {'containment_type': 'physical', 'is_required': True})
                    
    def process_repo_relations(self):
        """
        Process all code relationships after entities have been extracted.
        Iterates through all supported code files in the repository and
        extracts relationships between entities using the CodeAnalyzer.
        """
        self.logger.info("Starting to process code relationships...")
        
        # Get all files from the File collection
        file_collection = self.db.collection('File')
        all_files = list(file_collection.all())
        
        # Track statistics
        processed_files = 0
        total_relations = 0
        
        # Process each file
        for file_doc in all_files:
            file_path = file_doc.get('file_path')
            file_name = file_doc.get('file_name', '')
            
            # Skip files that aren't supported for relation extraction
            file_extension = file_name.split('.')[-1].lower() if '.' in file_name else ''
            if not CodeAnalyzer.is_supported_extension(file_extension):
                continue
            
            self.logger.info(f"Extracting relations from file: {file_path}")
            
            try:
                # Get relations for this file
                relations = self.analyzer.get_file_relations(
                    file_path=file_path, 
                    repo_entities=self.repo_entities
                )
                
                if not relations:
                    self.logger.info(f"No relations found in file: {file_path}")
                    continue
                    
                # Process each relation
                for relation in relations:
                    # Get source and target entity collections
                    source_collection_name = relation.source.entity_type if relation.source.entity_type else None
                    target_collection_name = relation.target.entity_type if relation.target.entity_type else None

                    # Skip if collection names are not valid
                    if not source_collection_name or not target_collection_name:
                        self.logger.warning(f"Skipping relation - invalid collection names: {source_collection_name} -> {target_collection_name}")
                        continue

                    # Check if collections exist
                    if source_collection_name not in [et.value for et in EntityType] or target_collection_name not in [et.value for et in EntityType]:
                        self.logger.warning(f"Skipping relation - collections not found: {source_collection_name} -> {target_collection_name}")
                        continue

                    # Get entity keys
                    source_key = self._generate_key(relation.source.key)
                    target_key = self._generate_key(relation.target.key)

                    # Get collections
                    source_collection = self.db.collection(source_collection_name)
                    target_collection = self.db.collection(target_collection_name)

                    # Check if entities exist in the database
                    if not source_collection.has(source_key) or not target_collection.has(target_key):
                        self.logger.warning(f"Skipping relation - entities not found: {source_collection_name}/{source_key} -> {target_collection_name}/{target_key}")
                        continue

                    # Get actual document IDs from the database
                    source_doc = source_collection.get(source_key)
                    target_doc = target_collection.get(target_key)

                    source_id = source_doc['_id']
                    target_id = target_doc['_id']
                    
                    # Create relationship metadata
                    metadata = {
                        'source_location': f"{relation.source_location[0]}:{relation.source_location[1]}",
                        'target_location': f"{relation.target_location[0]}:{relation.target_location[1]}",
                        'file_path': file_path
                    }
                    
                    # Add any additional metadata from the relation
                    if relation.metadata:
                        metadata.update(relation.metadata)
                    
                    # Create the relationship in the database
                    self._upsert_relationship(
                        source_id, 
                        target_id, 
                        relation.relation_type.value,
                        metadata
                    )
                    
                    total_relations += 1
                    
                processed_files += 1
                
            except Exception as e:
                self.logger.error(f"Error processing relations for file {file_path}: {str(e)}")
        
        self.logger.info(f"Completed processing relations: {total_relations} relations from {processed_files} files")

    def _determine_module_type(self, path: str) -> str:
        """
        Determines module type based on path.
        """
        path_lower = path.lower()
        if 'test' in path_lower:
            return 'test'
        elif 'doc' in path_lower:
            return 'documentation'
        elif 'config' in path_lower:
            return 'config'
        return 'source'

    def query_repository_structure(self, repo_name: str):
        """
        Queries the repository structure.
        """
        query = """
        FOR v, e, p IN 1..3 OUTBOUND @repo_id CONTAINS
        RETURN {
            entity: v,
            edge: e,
            path: p.vertices[*]._id
        }
        """
        repo_key = self._generate_key(repo_name)
        repo_id = f"Repository/{repo_key}"
        cursor = self.db.aql.execute(query, bind_vars={'repo_id': repo_id})
        return [doc for doc in cursor]
    
    def build_knowledge_graph(self, repo_name: str, structure: Dict):
        """
        Build a complete knowledge graph for the repository.
        First processes all entities, then processes all relationships.
        
        Args:
            repo_name (str): Name of the repository
            structure (Dict): Repository file structure
        """
        # First pass: Process all entities
        self.logger.info("Starting first pass: Processing repository structure and entities...")
        self.process_repo_structure(repo_name, structure)
        self.logger.info(f"First pass completed. Extracted {len(self.repo_entities)} entities.")
        
        # Second pass: Process all relationships between entities
        self.logger.info("Starting second pass: Processing entity relationships...")
        self.process_repo_relations()
        self.logger.info("Knowledge graph construction completed.")

