from __future__ import annotations

from datetime import datetime
import hashlib
import logging
import re
import time
import traceback
from typing import Any, Dict, List, Optional, TYPE_CHECKING

try:
    from arango import ArangoClient
except ImportError:  # pragma: no cover - optional for public mainline
    ArangoClient = None

from code_analyze.code_analyzer import CodeAnalyzer, EntityInfo, EntityType, RelationType
from utils import normalize_datetime

if TYPE_CHECKING:
    from llama_github.data_retrieval.github_entities import Repository
else:
    Repository = Any


class RepoKnowledgeGraph:
    """
    Legacy Arango-backed repository knowledge graph builder.

    This path is intentionally kept as a historical full-build-only workflow.
    Incremental update support was never stabilized and is not part of the
    public runtime surface.
    """

    def __init__(
        self,
        repo: Repository,
        host: str = "http://localhost:8529",
        database: str = "repo_kg",
        username: str = "root",
        password: str = "root",
        base_path: str = "",
        reset_collections: bool = False,
    ) -> None:
        self.repo = repo
        self.repo_entities: List[EntityInfo] = []
        self.analyzer = CodeAnalyzer(repo)
        self.logger = logging.getLogger(__name__)
        logging.basicConfig(level=logging.INFO)
        self.base_path = base_path
        self._current_relation_files: List[str] = []

        if ArangoClient is None:
            raise RuntimeError(
                "The legacy Arango path requires python-arango. "
                "Install repo_kg_maintainer/requirements-legacy.txt to use RepoKnowledgeGraph."
            )

        self.client = ArangoClient(hosts=host)
        sys_db = self.client.db("_system", username=username, password=password)
        if not sys_db.has_database(database):
            sys_db.create_database(database)

        self.db = self.client.db(database, username=username, password=password)
        self._init_collections(reset=reset_collections)

    def _calculate_content_hash(self, content: str) -> str:
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def _init_collections(self, reset: bool = False) -> None:
        """
        Initialize collections. Destructive reset is explicit opt-in only.
        """
        for entity_type in EntityType:
            if reset and self.db.has_collection(entity_type.value):
                self.db.delete_collection(entity_type.value)
            if not self.db.has_collection(entity_type.value):
                self.db.create_collection(entity_type.value)

        for relation_type in RelationType:
            if reset and self.db.has_collection(relation_type.value):
                self.db.delete_collection(relation_type.value)
            if not self.db.has_collection(relation_type.value):
                self.db.create_collection(relation_type.value, edge=True)

    def _generate_key(self, path: str) -> str:
        """
        Generate a readable, collision-resistant Arango key.
        """
        sanitized = re.sub(r"[^a-zA-Z0-9\-_]", "_", path)
        if len(sanitized) > 240:
            short_hash = hashlib.md5(path.encode("utf-8")).hexdigest()[:8]
            sanitized = sanitized[:225] + "_" + short_hash + "_trunc"
        if len(sanitized) > 254:
            sanitized = sanitized[:254]
        return sanitized

    def _upsert_entity(self, collection_name: str, key: str, data: Dict[str, Any]) -> str:
        collection = self.db.collection(collection_name)
        document = {"_key": key, **data}
        try:
            if collection.has(key):
                result = collection.update(document, return_new=True, silent=False)
            else:
                result = collection.insert(document, return_new=True)
            return result["_id"]
        except Exception as exc:
            self.logger.error("Error inserting document into %s: %s", collection.name, exc)
            return f"{collection.name}/{key}"

    def _upsert_relationship(
        self,
        from_id: str,
        to_id: str,
        relationship_type: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        edge_collection = self.db.collection(relationship_type)
        edge_doc = {"_from": from_id, "_to": to_id}
        if properties:
            edge_doc.update(properties)

        try:
            aql = """
            UPSERT { _from: @from_id, _to: @to_id }
            INSERT @doc
            UPDATE @doc
            IN @@collection
            RETURN NEW
            """
            cursor = self.db.aql.execute(
                aql,
                bind_vars={
                    "@collection": relationship_type,
                    "from_id": from_id,
                    "to_id": to_id,
                    "doc": edge_doc,
                },
            )
            return next(cursor, None)
        except Exception as exc:
            self.logger.error(
                "Error upserting edge in %s: %s -> %s (%s)",
                edge_collection.name,
                from_id,
                to_id,
                exc,
            )
            return None

    def create_repository(
        self,
        repo_name: str,
        description: str = "",
        primary_language: str = "",
        content_summary: str = "",
    ) -> str:
        repo_data = {
            "repository_id": repo_name,
            "description": description,
            "primary_language": primary_language,
            "content_summary": content_summary,
            "created_at": datetime.now().isoformat(),
        }
        repo_key = self._generate_key(repo_name)
        return self._upsert_entity("Repository", repo_key, repo_data)

    def get_file_last_modified(self, repo, file_path: str):
        """
        Get a file's last modified date without downloading the content.
        """
        for attempt in range(3):
            try:
                commits = repo.get_commits(path=file_path)
                if commits.totalCount > 0:
                    return commits[0].commit.author.date
                return None
            except Exception as exc:
                if attempt < 2:
                    time.sleep(2)
                else:
                    self.logger.warning("Failed to get last modified date for %s: %s", file_path, exc)
                    return None

    def _entity_key(self, entity: EntityInfo, file_path: str) -> str:
        parent = f"{entity.parent_name}/" if entity.parent_name else ""
        return self._generate_key(f"{entity.entity_type}/{file_path}/{parent}{entity.name}")

    def _parent_entity_key(self, entity: EntityInfo, file_path: str) -> Optional[str]:
        if not entity.parent_name or not entity.parent_type:
            return None
        return self._generate_key(f"{entity.parent_type}/{file_path}/{entity.parent_name}")

    def _build_entity_payload(self, entity: EntityInfo, file_path: str) -> Dict[str, Any]:
        payload = {
            "name": entity.name,
            "entity_type": entity.entity_type,
            "parent_name": entity.parent_name,
            "parent_type": entity.parent_type,
            "file_path": file_path,
            "description": entity.description,
            "complexity": entity.complexity,
            "is_exported": entity.is_exported,
            "modifiers": entity.modifiers,
            "content": entity.content,
        }
        if entity.content:
            payload["content_hash"] = self._calculate_content_hash(entity.content)
        return payload

    def _process_supported_file(
        self,
        file_path: str,
        file_name: str,
        file_extension: str,
        last_modified: Optional[str],
        parent_id: str,
    ) -> str:
        file_entity = None
        code_entities: List[EntityInfo] = []
        try:
            file_entity, code_entities = self.analyzer.get_file_entities(file_path=file_path)
        except Exception as exc:
            self.logger.error("Error processing file %s: %s", file_path, exc)
            self.logger.error("Traceback: %s", traceback.format_exc())

        file_content = ""
        if file_entity and file_entity.content:
            file_content = file_entity.content
        else:
            try:
                file_content = self.repo.get_file_content(file_path) or ""
            except Exception:
                file_content = ""

        file_data = {
            "file_path": file_path,
            "file_name": file_name,
            "size": getattr(file_entity, "size", 0) if file_entity else 0,
            "file_type": file_extension,
            "last_modified": last_modified,
            "content": file_content,
            "description": file_entity.description if file_entity else f"File of type {file_extension or 'unknown'}",
        }
        if file_content:
            file_data["content_hash"] = self._calculate_content_hash(file_content)

        file_key = self._generate_key(file_path)
        file_id = self._upsert_entity("File", file_key, file_data)
        self._upsert_relationship(
            parent_id,
            file_id,
            RelationType.CONTAINS.value,
            {"containment_type": "physical", "is_required": True},
        )

        self.repo_entities.extend(code_entities)
        self._current_relation_files.append(file_path)

        for entity in code_entities:
            if entity.entity_type not in {
                EntityType.CLASS.value,
                EntityType.METHOD.value,
                EntityType.INTERFACE.value,
                EntityType.ENUM.value,
                EntityType.VARIABLE.value,
            }:
                continue

            entity_key = self._entity_key(entity, file_path)
            entity_id = self._upsert_entity(
                entity.entity_type,
                entity_key,
                self._build_entity_payload(entity, file_path),
            )

            parent_entity_key = self._parent_entity_key(entity, file_path)
            if parent_entity_key and self.db.collection(entity.parent_type).has(parent_entity_key):
                parent_doc = self.db.collection(entity.parent_type).get(parent_entity_key)
                self._upsert_relationship(
                    parent_doc["_id"],
                    entity_id,
                    RelationType.CONTAINS.value,
                    {"containment_type": "physical", "is_required": True},
                )
            else:
                self._upsert_relationship(
                    file_id,
                    entity_id,
                    RelationType.CONTAINS.value,
                    {"containment_type": "physical", "is_required": True},
                )

        return file_id

    def process_repo_structure(
        self,
        repo_name: str,
        structure: Dict[str, Any],
        parent_path: str = "",
        parent_id: Optional[str] = None,
    ) -> None:
        """
        Recursively process repository structure and create file/entity nodes.
        """
        if parent_id is None:
            parent_id = self.create_repository(repo_name)
            self.logger.info("Created repository %s with ID %s", repo_name, parent_id)

        for name, info in structure.items():
            current_path = f"{parent_path}/{name}" if parent_path else name

            if "children" in info:
                module_data = {
                    "module_name": name,
                    "type": self._determine_module_type(current_path),
                    "description": f"Module containing {len(info['children'])} items",
                    "content_summary": "",
                }
                module_key = self._generate_key(current_path)
                module_id = self._upsert_entity("Module", module_key, module_data)
                self._upsert_relationship(
                    parent_id,
                    module_id,
                    RelationType.CONTAINS.value,
                    {"containment_type": "physical", "is_required": True},
                )
                self.process_repo_structure(repo_name, info["children"], current_path, module_id)
                continue

            file_path = info["path"]
            file_extension = name.split(".")[-1].lower() if "." in name else ""
            last_modified = normalize_datetime(self.get_file_last_modified(self.repo._repo, file_path))

            if CodeAnalyzer.is_supported_extension(file_extension):
                self._process_supported_file(file_path, name, file_extension, last_modified, parent_id)
                continue

            try:
                content = self.repo.get_file_content(file_path) or ""
            except Exception:
                content = ""

            file_data = {
                "file_path": file_path,
                "file_name": name,
                "size": info.get("size", 0),
                "file_type": file_extension,
                "last_modified": last_modified,
                "content": content,
                "description": f"File of type {file_extension or 'unknown'}",
            }
            if content:
                file_data["content_hash"] = self._calculate_content_hash(content)

            file_key = self._generate_key(file_path)
            file_id = self._upsert_entity("File", file_key, file_data)
            self._upsert_relationship(
                parent_id,
                file_id,
                RelationType.CONTAINS.value,
                {"containment_type": "physical", "is_required": True},
            )

    def process_repo_relations(self) -> None:
        """
        Process semantic relations for supported files discovered in the current full build.
        """
        self.logger.info("Starting to process code relationships...")
        processed_files = 0
        total_relations = 0

        for file_path in self._current_relation_files:
            file_extension = file_path.split(".")[-1].lower() if "." in file_path else ""
            if not CodeAnalyzer.is_supported_extension(file_extension):
                continue

            self.logger.info("Extracting relations from file: %s", file_path)
            try:
                relations = self.analyzer.get_file_relations(file_path=file_path, repo_entities=self.repo_entities)
            except Exception as exc:
                self.logger.error("Error processing relations for file %s: %s", file_path, exc)
                self.logger.error("Traceback: %s", traceback.format_exc())
                continue

            if not relations or not isinstance(relations, list):
                continue

            for relation in relations:
                source_collection_name = relation.source.entity_type
                target_collection_name = relation.target.entity_type

                if not source_collection_name or not target_collection_name:
                    continue
                if source_collection_name not in [et.value for et in EntityType]:
                    continue
                if target_collection_name not in [et.value for et in EntityType]:
                    continue

                source_key = self._generate_key(relation.source.key)
                target_key = self._generate_key(relation.target.key)

                source_collection = self.db.collection(source_collection_name)
                target_collection = self.db.collection(target_collection_name)
                if not source_collection.has(source_key) or not target_collection.has(target_key):
                    continue

                source_doc = source_collection.get(source_key)
                target_doc = target_collection.get(target_key)

                metadata = {
                    "source_location": f"{relation.source_location[0]}:{relation.source_location[1]}",
                    "target_location": f"{relation.target_location[0]}:{relation.target_location[1]}",
                    "file_path": file_path,
                }
                if relation.metadata:
                    metadata.update(relation.metadata)

                self._upsert_relationship(
                    source_doc["_id"],
                    target_doc["_id"],
                    relation.relation_type,
                    metadata,
                )
                total_relations += 1

            processed_files += 1

        self.logger.info(
            "Completed processing relations: %s relations from %s files",
            total_relations,
            processed_files,
        )

    def _determine_module_type(self, path: str) -> str:
        path_lower = path.lower()
        if "test" in path_lower:
            return "test"
        if "doc" in path_lower:
            return "documentation"
        if "config" in path_lower:
            return "config"
        return "source"

    def query_repository_structure(self, repo_name: str):
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
        cursor = self.db.aql.execute(query, bind_vars={"repo_id": repo_id})
        return [doc for doc in cursor]

    def build_knowledge_graph(self, repo_name: str, structure: Dict[str, Any]) -> None:
        """
        Build a complete knowledge graph using a full extraction pass.
        """
        self.repo_entities = []
        self._current_relation_files = []

        self.logger.info("Starting first pass: processing repository structure and entities...")
        self.process_repo_structure(repo_name, structure)
        self.logger.info("First pass completed. Extracted %s entities.", len(self.repo_entities))

        self.logger.info("Starting second pass: processing entity relationships...")
        self.process_repo_relations()
        self.logger.info("Legacy full-build knowledge graph construction completed.")
