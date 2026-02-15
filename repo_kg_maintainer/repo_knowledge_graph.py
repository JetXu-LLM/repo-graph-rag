from arango import ArangoClient
from datetime import datetime
import logging
import time
from typing import Dict, Any, Optional, List
import re
from llama_github.data_retrieval.github_entities import Repository
from code_analyze.code_analyzer import CodeAnalyzer, EntityType, EntityInfo, RelationType, FileChangeInfo, EntityChangeInfo
from utils import normalize_datetime
import traceback
import hashlib
import threading

class RepoKnowledgeGraph:
    def __init__(self, repo: Repository,
                 host: str = 'http://localhost:8529', 
                 database: str = 'repo_kg',
                 username: str = 'root',
                 password: str = 'root',
                 base_path: str = '',
                 reset_collections: bool = False):
        """
        Initializes Knowledge Graph connection.
        """
        self.repo = repo
        self.repo_entities = []
        self.analyzer = CodeAnalyzer(repo)
        self._repo_entities_lock = threading.Lock()

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
        self._init_collections(reset=reset_collections)

    def _calculate_content_hash(self, content: str) -> str:
        """Calculate hash for content comparison"""
        import hashlib
        return hashlib.md5(content.encode('utf-8')).hexdigest()

    def _detect_file_changes(self, structure: Dict) -> List[FileChangeInfo]:
        """Detect file-level changes by comparing with database"""
        self.logger.debug("Starting file change detection...")
        changes = []
        file_collection = self.db.collection('File')
        
        # Get all existing files from database
        existing_files = {}
        existing_count = 0
        for doc in file_collection.all():
            existing_files[doc['file_path']] = {
                'last_modified': doc.get('last_modified'),
                'content_hash': doc.get('content_hash', '')
            }
            existing_count += 1
        
        self.logger.debug(f"Found {existing_count} existing files in database")
        
        # Track current files
        current_files = set()
        
        def scan_structure(struct, path_prefix=""):
            for name, info in struct.items():
                current_path = f"{path_prefix}/{name}" if path_prefix else name
                
                if 'children' in info:
                    # Directory - recurse
                    scan_structure(info['children'], current_path)
                else:
                    # File
                    file_path = info['path']
                    current_files.add(file_path)
                    
                    # Get current file info
                    last_modified = normalize_datetime(self.get_file_last_modified(self.repo._repo, file_path))
                    
                    if file_path not in existing_files:
                        # New file
                        self.logger.debug(f"New file detected: {file_path}")
                        changes.append(FileChangeInfo(
                            file_path=file_path,
                            change_type='added',
                            last_modified=last_modified
                        ))
                    else:
                        # Check if modified
                        existing_modified = existing_files[file_path]['last_modified']
                        if not existing_modified or existing_modified < last_modified:
                            self.logger.debug(f"Potentially modified file detected: {file_path}")
                            # Get content to compare hash
                            try:
                                content = self.repo.get_file_content(file_path)
                                current_hash = self._calculate_content_hash(content)
                                old_hash = existing_files[file_path]['content_hash']
                                
                                if current_hash != old_hash:
                                    self.logger.debug(f"Content hash changed for file: {file_path}")
                                    changes.append(FileChangeInfo(
                                        file_path=file_path,
                                        change_type='modified',
                                        current_hash=current_hash,
                                        old_hash=old_hash,
                                        last_modified=last_modified
                                    ))
                                else:
                                    self.logger.debug(f"File timestamp changed but content identical: {file_path}")
                            except Exception as e:
                                self.logger.error(f"Error checking file content: {file_path}: {e}")
        
        scan_structure(structure)
        self.logger.debug(f"Scanned {len(current_files)} current files")
        
        # Find deleted files
        deleted_count = 0
        for file_path in existing_files:
            if file_path not in current_files:
                self.logger.debug(f"Deleted file detected: {file_path}")
                changes.append(FileChangeInfo(
                    file_path=file_path,
                    change_type='deleted'
                ))
                deleted_count += 1
        
        self.logger.debug(f"Found {deleted_count} deleted files")
        self.logger.debug(f"Total file changes detected: {len(changes)}")
        
        return changes

    def _detect_entity_changes(self, file_path: str, new_entities: List[EntityInfo]) -> List[EntityChangeInfo]:
        """Detect entity-level changes within a file"""
        changes = []
        
        # Get existing entities for this file
        existing_entities = {}
        for entity_type in EntityType:
            if entity_type.value in ['Repository', 'Module', 'File']:
                continue
                
            collection = self.db.collection(entity_type.value)
            aql = "FOR doc IN @@collection FILTER doc.file_path == @file_path RETURN doc"
            cursor = self.db.aql.execute(aql, bind_vars={
                '@collection': entity_type.value,
                'file_path': file_path
            })
            
            for doc in cursor:
                # Use consistent key generation with _generate_key()
                entity_key_raw = f"{doc['entity_type']}/{file_path}/{(doc['parent_name']+'/') if doc.get('parent_name') else ''}{doc['name']}"
                entity_key = self._generate_key(entity_key_raw)
                existing_entities[entity_key] = {
                    'content_hash': doc.get('content_hash', ''),
                    'entity_type': doc['entity_type']
                }
        
        # Track current entities
        current_entities = set()
        
        # Check new/modified entities
        for entity in new_entities:
            entity_key_raw = f"{entity.entity_type}/{file_path}/{(entity.parent_name+'/') if entity.parent_name else ''}{entity.name}"
            entity_key = self._generate_key(entity_key_raw)
            current_entities.add(entity_key)
            
            content_hash = self._calculate_content_hash(entity.content)
            
            if entity_key not in existing_entities:
                # New entity
                changes.append(EntityChangeInfo(
                    entity_key=entity_key,
                    entity_type=entity.entity_type,
                    change_type='added',
                    file_path=file_path,
                    content_hash=content_hash
                ))
            else:
                # Check if modified
                old_hash = existing_entities[entity_key]['content_hash']
                if content_hash != old_hash:
                    changes.append(EntityChangeInfo(
                        entity_key=entity_key,
                        entity_type=entity.entity_type,
                        change_type='modified',
                        file_path=file_path,
                        content_hash=content_hash
                    ))
        
        # Find deleted entities
        for entity_key, entity_info in existing_entities.items():
            if entity_key not in current_entities:
                changes.append(EntityChangeInfo(
                    entity_key=entity_key,
                    entity_type=entity_info['entity_type'],
                    change_type='deleted',
                    file_path=file_path
                ))
        
        return changes
    
    def _process_file_deletion(self, file_path: str, files_to_reprocess_relations: set):
        """
        Process file deletion by finding reverse dependencies, then removing the file
        and all its contained entities and their associated relationships.
        """
        self.logger.debug(f"Starting deletion process for file: {file_path}")
        
        file_key = self._generate_key(file_path)
        file_id = f"File/{file_key}"

        # --- STEP 1: Find all entities within this file BEFORE deletion ---
        # We need their IDs to find reverse dependencies and to delete them efficiently.
        self.logger.debug(f"Querying all entities contained within file: {file_path}")
        entities_in_file_query = "FOR doc IN 1..10 OUTBOUND @file_id CONTAINS RETURN doc._id"
        try:
            cursor = self.db.aql.execute(entities_in_file_query, bind_vars={'file_id': file_id})
            entity_ids_to_delete = list(cursor)
        except Exception as e:
            self.logger.error(f"Fatal: Could not query entities for deleted file {file_path}. Aborting deletion for this file. Error: {e}")
            return # Stop processing if we can't get the entities

        # --- STEP 2: Use entity IDs to find all files that reference them ---
        # This is the core fix. We add these referencing files to the reprocessing set.
        if entity_ids_to_delete:
            self.logger.debug(f"Finding reverse dependencies for {len(entity_ids_to_delete)} entities in deleted file.")
            referencing_files = self._find_reverse_dependency_files(entity_ids_to_delete)
            if referencing_files:
                # We must remove the current file_path from the set, as it's being deleted, not reprocessed.
                referencing_files.discard(file_path)
                if referencing_files:
                    self.logger.debug(f"Entities in {file_path} are referenced by: {referencing_files}")
                    files_to_reprocess_relations.update(referencing_files)
        
        # --- STEP 3: Efficiently delete all collected entities ---
        # This is the replacement for the old, verbose deletion loops.
        # Deleting an entity automatically removes all relationships connected to it.
        if entity_ids_to_delete:
            self.logger.debug(f"Deleting {len(entity_ids_to_delete)} entities from file {file_path}")
            # We can't use a simple AQL query with a list of IDs to delete across different collections.
            # We must iterate and delete one by one, or group by collection.
            try:
                for entity_id in entity_ids_to_delete:
                    collection_name, key = entity_id.split('/')
                    if self.db.has_collection(collection_name) and self.db.collection(collection_name).has(key):
                        self.db.collection(collection_name).delete(key)
                self.logger.debug(f"Successfully deleted {len(entity_ids_to_delete)} entities.")
            except Exception as e:
                self.logger.error(f"Error during bulk entity deletion for file {file_path}: {e}")

        # --- STEP 4: Finally, remove the File node itself ---
        # This replaces the final block of the original function.
        try:
            file_collection = self.db.collection('File')
            if file_collection.has(file_key):
                file_collection.delete(file_key)
                self.logger.info(f"✓ Successfully deleted file and all associated data: {file_path}")
            else:
                self.logger.debug(f"File node for {file_path} not found, it might have been already deleted.")
        except Exception as e:
            self.logger.error(f"Error deleting file node {file_path}: {e}")

    def _process_entity_changes(self, file_path: str, entity_changes: List[EntityChangeInfo], new_entities: List[EntityInfo], files_to_reprocess_relations: set):
        """
        Process entity-level changes within a file, find reverse dependencies for
        modified/deleted entities, and perform the database updates.
        """
        added_count = len([c for c in entity_changes if c.change_type == 'added'])
        modified_count = len([c for c in entity_changes if c.change_type == 'modified'])
        deleted_count = len([c for c in entity_changes if c.change_type == 'deleted'])
        
        if added_count > 0 or modified_count > 0 or deleted_count > 0:
            self.logger.info(f"Entity changes in {file_path}: {added_count} added, {modified_count} modified, {deleted_count} deleted")

        # First, collect all IDs of entities that were changed or deleted.
        changed_or_deleted_ids = []
        for change in entity_changes:
            if change.change_type in ['deleted', 'modified']:
                db_key = self._generate_key(change.entity_key)
                entity_id = f"{change.entity_type}/{db_key}"
                changed_or_deleted_ids.append(entity_id)
        
        # Now, use the collected IDs to perform a single, efficient query to find
        # all files that reference ANY of these entities.
        if changed_or_deleted_ids:
            self.logger.debug(f"Finding reverse dependencies for {len(changed_or_deleted_ids)} modified/deleted entities in {file_path}")
            referencing_files = self._find_reverse_dependency_files(changed_or_deleted_ids)
            if referencing_files:
                # The current file is already being processed, so we don't need to add it to the set.
                referencing_files.discard(file_path)
                if referencing_files:
                    self.logger.debug(f"Found referencing files that need relation reprocessing: {referencing_files}")
                    files_to_reprocess_relations.update(referencing_files)

        # This part remains the same: prepare a lookup for new/modified entities.
        entities_by_key = {}
        for entity in new_entities:
            entity_key = f"{entity.entity_type}/{file_path}/{(entity.parent_name+'/') if entity.parent_name else ''}{entity.name}"
            entities_by_key[entity_key] = entity
        
        # Now, process the actual changes.
        for change in entity_changes:
            if change.change_type == 'deleted':
                # The inefficient loop for deleting relationships is removed.
                # Deleting the entity node will automatically remove all connected edges.
                db_key = self._generate_key(change.entity_key)
                try:
                    collection = self.db.collection(change.entity_type)
                    if collection.has(db_key):
                        collection.delete(db_key)
                        self.logger.debug(f"Deleted entity: {change.entity_key}")
                    else:
                        self.logger.warning(f"Attempted to delete entity {change.entity_key}, but it was not found in the database.")
                except Exception as e:
                    self.logger.error(f"Error deleting entity {change.entity_key}: {e}")
                    
            elif change.change_type in ['added', 'modified']:
                if change.entity_key in entities_by_key:
                    entity = entities_by_key[change.entity_key]
                    self._create_or_update_entity(entity, file_path, change.content_hash)

    def _create_or_update_entity(self, entity: EntityInfo, file_path: str, content_hash: str):
        """Create or update a single entity with content hash"""
        if entity.entity_type in ['Class', 'Method', 'Interface', 'Enum']:
            entity_data = {
                'name': entity.name,
                'parent_name': entity.parent_name,
                'parent_type': entity.parent_type,
                'entity_type': entity.entity_type,
                'description': entity.description,
                'complexity': entity.complexity,
                'file_path': file_path,
                'is_exported': entity.is_exported,
                'modifiers': entity.modifiers,
                'content': entity.content,
                'content_hash': content_hash,
                'last_updated': datetime.now().isoformat()
            }
            entity_key = self._generate_key(f"{entity.entity_type}/{file_path}/{(entity.parent_name+'/') if entity.parent_name else ''}{entity.name}")
            entity_id = self._upsert_entity(entity.entity_type, entity_key, entity_data)
            
            # Clean up existing CONTAINS relationships for this entity
            self._cleanup_entity_contains_relations(entity_id)
            
            # Handle parent relationships
            file_key = self._generate_key(file_path)
            file_id = f"File/{file_key}"
            
            has_parent = False
            if entity.parent_name:
                parent_collection = self.db.collection(entity.parent_type)
                parent_key = self._generate_key(f"{entity.parent_type}/{file_path}/{entity.parent_name}")
                if parent_collection.has(parent_key):
                    parent_id = f"{entity.parent_type}/{parent_key}"
                    self._upsert_relationship(parent_id, entity_id, 'CONTAINS', 
                                            {'containment_type': 'physical', 'is_required': True})
                    has_parent = True
            
            if not has_parent:
                self._upsert_relationship(file_id, entity_id, 'CONTAINS', 
                                        {'containment_type': 'physical', 'is_required': True})
                                        
        elif entity.entity_type == 'Variable':
            variable_data = {
                'name': entity.name,
                'entity_type': entity.entity_type,
                'parent_name': entity.parent_name,
                'parent_type': entity.parent_type,
                'file_path': file_path,
                'is_exported': entity.is_exported,
                'modifiers': entity.modifiers,
                'content': entity.content,
                'content_hash': content_hash,
                'last_updated': datetime.now().isoformat()
            }
            variable_key = self._generate_key(f"{entity.entity_type}/{file_path}/{entity.name}")
            variable_id = self._upsert_entity('Variable', variable_key, variable_data)
            
            # Clean up existing CONTAINS relationships for this entity
            self._cleanup_entity_contains_relations(variable_id)
            
            file_key = self._generate_key(file_path)
            file_id = f"File/{file_key}"
            self._upsert_relationship(file_id, variable_id, 'CONTAINS', 
                                    {'containment_type': 'physical', 'is_required': True})

    def _cleanup_entity_contains_relations(self, entity_id: str):
        """Clean up existing CONTAINS relationships for an entity"""
        try:
            aql = """
            FOR edge IN CONTAINS
            FILTER edge._to == @entity_id
            REMOVE edge IN CONTAINS
            """
            self.db.aql.execute(aql, bind_vars={'entity_id': entity_id})
        except Exception as e:
            self.logger.error(f"Error cleaning up CONTAINS relations for {entity_id}: {e}")
            
    def _load_existing_entities(self):
        """Load all existing code entities from database into repo_entities"""
        self.repo_entities = []
        
        # Load entities from all code entity collections
        code_entity_types = [EntityType.CLASS, EntityType.METHOD, EntityType.INTERFACE, 
                            EntityType.ENUM, EntityType.VARIABLE]
        
        for entity_type in code_entity_types:
            try:
                collection = self.db.collection(entity_type.value)
                for doc in collection.all():
                    entity = EntityInfo(
                        name=doc.get('name', ''),
                        entity_type=doc.get('entity_type', ''),
                        parent_name=doc.get('parent_name', ''),
                        parent_type=doc.get('parent_type', ''),
                        is_exported=doc.get('is_exported', False),
                        modifiers=doc.get('modifiers', []),
                        content=doc.get('content', ''),
                        description=doc.get('description', ''),
                        complexity=doc.get('complexity', 0),
                        file_path=doc.get('file_path', '')
                    )
                    self.repo_entities.append(entity)
            except Exception as e:
                self.logger.error(f"Error loading entities from {entity_type.value}: {e}")

    def incremental_update(self, repo_name: str, structure: Dict):
        """Main entry point for incremental repository updates."""
        self.logger.info("=== STARTING INCREMENTAL UPDATE ===")
        self.logger.info(f"Repository: {repo_name}")
        
        # Initialize repo_entities with all existing entities from database (protected)
        self.logger.info("Loading existing entities from database...")
        with self._repo_entities_lock:
            self._load_existing_entities()
        self.logger.info(f"✓ Loaded {len(self.repo_entities)} existing entities")
        
        # Detect file-level changes
        self.logger.info("Detecting file changes...")
        file_changes = self._detect_file_changes(structure)
        self.logger.info(f"✓ Detected {len(file_changes)} file changes")
        
        # Log change summary
        added_files = [c for c in file_changes if c.change_type == 'added']
        modified_files = [c for c in file_changes if c.change_type == 'modified']
        deleted_files = [c for c in file_changes if c.change_type == 'deleted']
        
        self.logger.info(f"Change Summary: {len(added_files)} added, {len(modified_files)} modified, {len(deleted_files)} deleted")
        
        files_to_reprocess_relations = set(c.file_path for c in added_files + modified_files)
        
        # Process file changes (entity updates, protected by lock)
        self.logger.debug("Processing file changes...")
        for change in file_changes:
            with self._repo_entities_lock:  # Lock per change to ensure atomic updates
                if change.change_type == 'deleted':
                    self.logger.info(f"Processing deleted file: {change.file_path}")
                    self._process_file_deletion(change.file_path, files_to_reprocess_relations)
                elif change.change_type == 'added':
                    self.logger.info(f"Processing new file: {change.file_path}")
                    self._process_single_file(change.file_path, structure, repo_name)
                elif change.change_type == 'modified':
                    self.logger.info(f"Processing modified file: {change.file_path}")
                    self._process_modified_file(change.file_path, files_to_reprocess_relations)
        
        # After all entity processing, refresh repo_entities once (ensures complete state for relations)
        with self._repo_entities_lock:
            self._load_existing_entities()  # Reload to capture all updates
        
        # Reprocess relationships for the EXPANDED set of affected files
        if files_to_reprocess_relations:
            self.logger.info(f"Reprocessing relationships for {len(files_to_reprocess_relations)} affected files")
            self._reprocess_file_relations(list(files_to_reprocess_relations))
        else:
            self.logger.debug("No files require relationship reprocessing")
        
        self.logger.info("=== INCREMENTAL UPDATE COMPLETED SUCCESSFULLY ===")

    def _process_modified_file(self, file_path: str, files_to_reprocess_relations: set):
        """Process a modified file by detecting entity changes"""
        self.logger.debug(f"Processing modified file: {file_path}")
        
        file_extension = file_path.split('.')[-1].lower() if '.' in file_path else ''
        
        if not CodeAnalyzer.is_supported_extension(file_extension):
            self.logger.debug(f"File {file_path} has unsupported extension, updating metadata only")
            # Update file metadata only
            self._update_file_metadata(file_path)
            return
        
        try:
            # Get new entities
            self.logger.debug(f"Extracting entities from modified file: {file_path}")
            file_entity, code_entities = self.analyzer.get_file_entities(file_path=file_path)
            self.logger.debug(f"Extracted {len(code_entities)} entities from {file_path}")
            
            # Detect entity changes
            entity_changes = self._detect_entity_changes(file_path, code_entities)
            self.logger.info(f"Detected {len(entity_changes)} entity changes in {file_path}")
            
            for change in entity_changes:
                self.logger.debug(f"Entity change detected: {change.change_type} - {change.entity_key}")
            
            # Update file entity if exists
            if file_entity:
                self.logger.debug(f"Updating file entity for {file_path}")
                self._update_file_with_entity(file_path, file_entity)
            else:
                self.logger.debug(f"No file entity found, updating metadata for {file_path}")
                self._update_file_metadata(file_path)
            
            # Process entity changes
            self._process_entity_changes(file_path, entity_changes, code_entities, files_to_reprocess_relations)
            
            # Update repo_entities for relation processing - FIXED FILTERING LOGIC
            old_entities_count = len(self.repo_entities)
            
            # Remove old entities from this file
            self.repo_entities = [e for e in self.repo_entities if e.file_path != file_path]
            
            # Add new entities
            for entity in code_entities:
                entity.file_path = file_path
                self.repo_entities.append(entity)
            
            new_entities_count = len(self.repo_entities)
            self.logger.debug(f"Updated repo_entities: {old_entities_count} -> {new_entities_count} entities")
                    
        except Exception as e:
            self.logger.error(f"Error processing modified file {file_path}: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")

    def _update_file_metadata(self, file_path: str):
        """Update file metadata without entity processing, with safe content handling."""
        file_key = self._generate_key(file_path)
        last_modified = normalize_datetime(self.get_file_last_modified(self.repo._repo, file_path))
        
        try:
            content = self.repo.get_file_content(file_path)
            content_hash = self._calculate_content_hash(content) if content else ""  # Hash only if content loaded
        except Exception as e:
            self.logger.error(f"Error loading content for {file_path}: {e}")
            content = ""
            content_hash = ""  # Avoid invalid hash on failure
        
        update_data = {
            'last_modified': last_modified,
            'content': content,
            'content_hash': content_hash,
            'last_updated': datetime.now().isoformat()
        }
        
        file_collection = self.db.collection('File')
        if file_collection.has(file_key):
            file_collection.update({'_key': file_key, **update_data})

    def _update_file_with_entity(self, file_path: str, file_entity: EntityInfo):
        """Update file with entity information"""
        file_key = self._generate_key(file_path)
        last_modified = normalize_datetime(self.get_file_last_modified(self.repo._repo, file_path))
        content_hash = self._calculate_content_hash(file_entity.content)
        
        file_data = {
            'last_modified': last_modified,
            'content': file_entity.content,
            'description': file_entity.description,
            'content_hash': content_hash,
            'last_updated': datetime.now().isoformat()
        }
        
        file_collection = self.db.collection('File')
        if file_collection.has(file_key):
            file_collection.update({'_key': file_key, **file_data})

    def _reprocess_file_relations(self, file_paths: List[str]):
        """Reprocess relationships for specific files"""
        self.logger.debug(f"Starting relationship reprocessing for {len(file_paths)} files")
        
        total_relations_created = 0
        for file_path in file_paths:
            file_extension = file_path.split('.')[-1].lower() if '.' in file_path else ''
            if not CodeAnalyzer.is_supported_extension(file_extension):
                self.logger.debug(f"Skipping relation processing for unsupported file: {file_path}")
                continue
                
            try:
                self.logger.debug(f"Removing existing relationships for file: {file_path}")
                # Remove existing relationships for entities in this file
                self._remove_file_relations(file_path)
                
                self.logger.debug(f"Extracting new relationships from file: {file_path}")
                # Extract new relationships
                relations = self.analyzer.get_file_relations(
                    file_path=file_path, 
                    repo_entities=self.repo_entities
                )
                
                self.logger.debug(f"Found {len(relations)} relationships in file: {file_path}")
                
                # Create new relationships
                relations_created = 0
                for relation in relations:
                    if self._create_relation_if_valid(relation, file_path):
                        relations_created += 1
                
                self.logger.debug(f"Created {relations_created} relationships for file: {file_path}")
                total_relations_created += relations_created
                    
            except Exception as e:
                self.logger.error(f"Error reprocessing relations for {file_path}: {e}")
        
        self.logger.info(f"Relationship reprocessing completed. Created {total_relations_created} relationships")

    def _remove_file_relations(self, file_path: str):
        """
        Removes all relationships that were defined within a specific file.
        This is safer than removing all inbound/outbound edges of entities, as it
        preserves relationships defined in other files (reverse dependencies).
        """
        for relation_type in RelationType:
            # CONTAINS relationships are managed by entity creation/deletion, not here.
            if relation_type == RelationType.CONTAINS:
                continue
                
            try:
                # This single query is sufficient and correct. It removes an edge only if
                # its 'file_path' attribute matches the file being processed.
                aql = f"""
                FOR edge IN {relation_type.value}
                    FILTER edge.file_path == @file_path
                    REMOVE edge IN {relation_type.value}
                """
                self.db.aql.execute(aql, bind_vars={'file_path': file_path})
            except Exception as e:
                # Log error but continue, as some relation collections might not exist.
                self.logger.warning(f"Could not remove '{relation_type.value}' relations for '{file_path}': {e}")

    def _create_relation_if_valid(self, relation, file_path: str) -> bool:
        """Create a relationship if both entities exist. Returns True if created successfully."""
        source_collection_name = relation.source.entity_type
        target_collection_name = relation.target.entity_type

        if not source_collection_name or not target_collection_name:
            self.logger.debug(f"Skipping relation - invalid collection names: {source_collection_name} -> {target_collection_name}")
            return False

        if source_collection_name not in [et.value for et in EntityType] or target_collection_name not in [et.value for et in EntityType]:
            self.logger.debug(f"Skipping relation - collections not found: {source_collection_name} -> {target_collection_name}")
            return False

        source_key = self._generate_key(relation.source.key)
        target_key = self._generate_key(relation.target.key)

        source_collection = self.db.collection(source_collection_name)
        target_collection = self.db.collection(target_collection_name)

        if not source_collection.has(source_key) or not target_collection.has(target_key):
            self.logger.debug(f"Skipping relation - entities not found: {source_collection_name}/{source_key} -> {target_collection_name}/{target_key}")
            return False

        try:
            source_doc = source_collection.get(source_key)
            target_doc = target_collection.get(target_key)

            metadata = {
                'source_location': f"{relation.source_location[0]}:{relation.source_location[1]}",
                'target_location': f"{relation.target_location[0]}:{relation.target_location[1]}",
                'file_path': file_path
            }
            
            if relation.metadata:
                metadata.update(relation.metadata)
            
            # 修复：安全地获取关系类型字符串
            if hasattr(relation.relation_type, 'value'):
                relation_type_str = relation.relation_type.value
            elif hasattr(relation.relation_type, 'name'):
                relation_type_str = relation.relation_type.name
            else:
                relation_type_str = str(relation.relation_type)
            
            result = self._upsert_relationship(
                source_doc['_id'], 
                target_doc['_id'], 
                relation_type_str,
                metadata
            )
            
            if result:
                self.logger.debug(f"Created relationship: {relation_type_str} from {source_key} to {target_key}")
                return True
            else:
                self.logger.debug(f"Failed to create relationship: {relation_type_str} from {source_key} to {target_key}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error creating relationship: {e}")
            return False

    def _init_collections(self, reset: bool = False):
        """
        Initializes required collections and edge collections.
        """
        # Entity collections - using EntityType enum values
        for entity_type in EntityType:
            if reset and self.db.has_collection(entity_type.value):
                self.db.delete_collection(entity_type.value)
            if not self.db.has_collection(entity_type.value):
                self.db.create_collection(entity_type.value)
        
        # Relationship collections - using RelationType enum values and CONTAINS
        for relation_type in RelationType:
            if reset and self.db.has_collection(relation_type.value):
                self.db.delete_collection(relation_type.value)
            if not self.db.has_collection(relation_type.value):
                self.db.create_collection(relation_type.value, edge=True)

    def _generate_key(self, path: str) -> str:
        """Generates a unique and readable ArangoDB key based on the path, ensuring no collisions while preserving readability for LLM analysis."""
        # Sanitize the path to remove invalid characters, replacing with underscores
        sanitized = re.sub(r'[^a-zA-Z0-9\-_]', '_', path)
        
        # If the sanitized key is too long, truncate and append a short hash + truncation indicator for uniqueness and clarity
        # This keeps the key readable (most of the path intact) while ensuring it's unique and within limits
        if len(sanitized) > 240:  # Conservative threshold with buffer for suffix (1+8+6=15 chars)
            short_hash = hashlib.md5(path.encode('utf-8')).hexdigest()[:8]
            sanitized = sanitized[:225] + '_' + short_hash + '_trunc'
        
        # Ensure final key length does not exceed ArangoDB's 254 character limit (though our calc keeps it under)
        if len(sanitized) > 254:
            sanitized = sanitized[:254]
        
        return sanitized

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
    
    def get_file_last_modified(self, repo, file_path: str):
        """
        Get file's last modified date without downloading content.
        
        Args:
            repo: PyGithub repository object
            file_path: Path to the file within the repository
            
        Returns:
            Last modified date or None if not found
        """
        # Simple retry mechanism - 3 attempts with 2 second delay
        for attempt in range(3):
            try:
                # Get the commits for the specified file path
                commits = repo.get_commits(path=file_path)
                # Check if any commits were found
                if commits.totalCount > 0:
                    return commits[0].commit.author.date
                return None
            except Exception as e:
                if attempt < 2:  # Only sleep if we're going to retry
                    time.sleep(2)
                else:
                    print(f"Failed to get last modified date: {e}")
                    return None

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
                # last_modified = normalize_datetime(self.repo._repo.get_contents(info['path']).last_modified)
                last_modified = normalize_datetime(self.get_file_last_modified(self.repo._repo, info['path']))
                # self.logger.info(f"Last modified for {info['path']}: {last_modified}")

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
                        self.logger.error(f"Traceback: {traceback.format_exc()}")
                        continue

                    if file_entity:
                        # File entity
                        file_data = {
                            'file_path': info['path'],
                            'file_name': name,
                            'size': info.get('size', 0),
                            'file_type': file_extension,
                            'last_modified': last_modified,
                            'content': file_entity.content if file_entity else self.repo.get_file_content(info['path']),
                            'description': file_entity.description if file_entity else f"File of type {name.split('.')[-1] if '.' in name else 'unknown'}",
                            'content_hash': self._calculate_content_hash(file_entity.content if file_entity else self.repo.get_file_content(info['path'])),
                            'last_updated': datetime.now().isoformat()
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
                                'content_hash': self._calculate_content_hash(entity.content),
                                'last_updated': datetime.now().isoformat()
                            }
                            entity_key = self._generate_key(f"{entity.entity_type}/{current_path}/{(entity.parent_name+'/') if entity.parent_name else ''}{entity.name}")
                            entity_id = self._upsert_entity(entity.entity_type, entity_key, entity_data)
                            self.repo_entities.append(entity)
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
                    content = self.repo.get_file_content(info['path']) or "" # FIX: Fallback to empty string
                    file_data = {
                        'file_path': info['path'],
                        'file_name': name,
                        'size': info.get('size', 0),
                        'file_type': file_extension,
                        'last_modified': last_modified,
                        'content': content,
                        'description': f"File of type {name.split('.')[-1] if '.' in name else 'unknown'}",
                        'content_hash': self._calculate_content_hash(content), # FIX: Calculate hash on fallback content
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
                    
                    if hasattr(relation.relation_type, 'value'):
                        relation_type_str = relation.relation_type.value
                    elif hasattr(relation.relation_type, 'name'):
                        relation_type_str = relation.relation_type.name
                    else:
                        relation_type_str = str(relation.relation_type)
                    
                    # Create the relationship in the database
                    result = self._upsert_relationship(
                        source_id, 
                        target_id, 
                        relation_type_str,
                        metadata
                    )

                    if result:
                        self.logger.info(f"Created entity relationship {relation_type_str}: {source_key} -> {target_key}")
                        total_relations += 1
                    else:
                        self.logger.warning(f"Failed to create relationship {relation_type_str}: {source_key} -> {target_key}")
                        
                processed_files += 1
                    
            except Exception as e:
                self.logger.error(f"Error processing relations for file {file_path}: {str(e)}")
                self.logger.error(f"Traceback: {traceback.format_exc()}")
        
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
    
    def build_knowledge_graph(self, repo_name: str, structure: Dict, incremental: bool = False):
        """
        Build a complete knowledge graph for the repository.
        
        Args:
            repo_name (str): Name of the repository
            structure (Dict): Repository file structure
            incremental (bool): Whether to use incremental update mode
        """
        if incremental:
            self.logger.info("Starting incremental knowledge graph update...")
            self.incremental_update(repo_name, structure)
        else:
            self.logger.info("Starting full knowledge graph construction...")
            # First pass: Process all entities
            self.process_repo_structure(repo_name, structure)
            self.logger.info(f"First pass completed. Extracted {len(self.repo_entities)} entities.")
            
            # Second pass: Process all relationships between entities
            self.logger.info("Starting second pass: Processing entity relationships...")
            self.process_repo_relations()
            
        self.logger.info("Knowledge graph construction completed.")

    def _process_single_file(self, file_path: str, structure: Dict, repo_name: str):
        """Process a single new file by finding its parent and processing it"""
        self.logger.debug(f"Processing single new file: {file_path}")

        # Find the file in structure and get its parent
        def find_file_parent(struct, target_path, current_path="", parent_id=None):
            for name, info in struct.items():
                new_path = f"{current_path}/{name}" if current_path else name
                
                if 'children' in info:
                    # This is a directory
                    module_key = self._generate_key(new_path)
                    module_id = f"Module/{module_key}"
                    
                    # Recurse
                    result, size = find_file_parent(info['children'], target_path, new_path, module_id)
                    if result:
                        return result, size
                else:
                    # This is a file
                    if info['path'] == target_path:
                        final_parent_id = parent_id or self._get_repo_id(repo_name)
                        return final_parent_id, info.get('size', 0)
            return None, 0

        parent_id, file_size = find_file_parent(structure, file_path)

        if parent_id:
            self.logger.debug(f"Found parent for {file_path}: {parent_id}")

            try:
                actual_content = self.repo.get_file_content(file_path)
                actual_file_size = len(actual_content.encode('utf-8')) if actual_content else 0
            except Exception as e:
                self.logger.warning(f"Could not get file content for {file_path}: {e}")
                actual_file_size = file_size
            
            # Create a mini structure containing just this file
            file_name = file_path.split('/')[-1]
            mini_structure = {
                file_name: {'path': file_path, 'size': actual_file_size}
            }
            
            self.logger.debug(f"Created mini structure for {file_path} with size {actual_file_size}")
            
            # Process this single file
            self.process_repo_structure(repo_name, mini_structure, 
                                    parent_path="/".join(file_path.split('/')[:-1]), 
                                    parent_id=parent_id)
            self.logger.debug(f"Successfully processed single file: {file_path}")
        else:
            self.logger.error(f"Could not find parent for file: {file_path}")

    def _get_repo_id(self, repo_name: str) -> str:
        """Get repository ID"""
        repo_key = self._generate_key(repo_name)
        return f"Repository/{repo_key}"

    def _find_reverse_dependency_files(self, entity_ids: List[str]) -> set[str]:
        """
        Finds all unique file paths that contain entities with inbound relationships
        from the given entity IDs. This is crucial for reprocessing reverse dependencies.
        """
        if not entity_ids:
            return set()

        relation_collections = [rel.value for rel in RelationType if rel != RelationType.CONTAINS]
        if not relation_collections:
            self.logger.warning("No relationship collections found to query for reverse dependencies.")
            return set()

        # This robust structure queries each relationship collection separately and unions
        # the results, avoiding potential AQL engine limitations with dynamic collection names.
        subqueries = []
        for coll_name in relation_collections:
            subquery = f"""
                (FOR e IN {coll_name}
                    FILTER e._to IN @entity_ids AND HAS(e, 'file_path')
                    RETURN DISTINCT e.file_path)
            """
            subqueries.append(subquery)

        aql_query = f"""
        LET all_referencing_files = UNION_DISTINCT({', '.join(subqueries)})
        FOR file_path IN all_referencing_files
            RETURN file_path
        """
        
        try:
            cursor = self.db.aql.execute(aql_query, bind_vars={'entity_ids': entity_ids})
            referencing_files = set(doc for doc in cursor)
            self.logger.debug(f"Found {len(referencing_files)} reverse dependency files to reprocess.")
            return referencing_files
        except Exception as e:
            self.logger.error(f"Error finding reverse dependency files: {e}\nFailed AQL query: {aql_query}")
            return set()
