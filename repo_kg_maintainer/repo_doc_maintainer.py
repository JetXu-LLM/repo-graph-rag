import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional, Any, Union
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import time
from tqdm import tqdm

# For Markdown parsing
import markdown
from bs4 import BeautifulSoup

# For ArangoDB
from arango import ArangoClient

# For Gemini API
import google.genai as genai
from google.genai.types import HarmCategory, HarmBlockThreshold

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("kg_document_builder.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class DocumentChunk:
    """Represents a chunk of a document for processing."""
    doc_id: str
    content: str
    heading_path: List[str]
    code_blocks: List[str]
    position: int
    file_path: str

@dataclass
class Entity:
    """Represents a code entity from the knowledge graph."""
    id: str
    name: str
    entity_type: str
    file_path: Optional[str] = None
    content: Optional[str] = None
    parent_name: Optional[str] = None
    parent_type: Optional[str] = None
    description: Optional[str] = None

@dataclass
class EntityMention:
    """Represents a mention of an entity in a document."""
    entity_id: str
    mention_text: str
    confidence: float
    relation_type: str
    context: str

class AirflowKGDocumentBuilder:
    """
    A class to build and enhance the document part of Airflow Knowledge Graph.
    """
    
    def __init__(
        self, 
        repo_path: str, 
        arango_url: str = "http://localhost:8529", 
        arango_db: str = "apache_airflow",
        arango_username: str = "root",
        arango_password: str = "",
        gemini_api_key: str = None,
        chunk_size: int = 1500,
        chunk_overlap: int = 200,
        confidence_threshold: float = 0.7,
        max_workers: int = 4
    ):
        """
        Initialize the document builder.
        
        Args:
            repo_path: Path to the Airflow repository
            arango_url: URL of the ArangoDB server
            arango_db: Name of the ArangoDB database
            arango_username: ArangoDB username
            arango_password: ArangoDB password
            gemini_api_key: API key for Gemini
            chunk_size: Size of document chunks for processing
            chunk_overlap: Overlap between document chunks
            confidence_threshold: Threshold for entity mention confidence
            max_workers: Maximum number of concurrent workers
        """
        self.repo_path = Path(repo_path)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.confidence_threshold = confidence_threshold
        self.max_workers = max_workers
        
        # Initialize ArangoDB client
        self.arango_client = ArangoClient(hosts=arango_url)
        self.db = self.arango_client.db(
            arango_db, 
            username=arango_username, 
            password=arango_password
        )
        
        # Initialize Gemini
        if gemini_api_key:
            genai.configure(api_key=gemini_api_key)
        
        # Configure Gemini model
        self.generation_config = {
            "temperature": 0.1,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 2048,
        }
        
        self.safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        
        self.model = genai.GenerativeModel(
            model_name="gemini-1.5-pro",
            generation_config=self.generation_config,
            safety_settings=self.safety_settings
        )
        
        # Ensure document collection exists
        if not self.db.has_collection("Document"):
            self.db.create_collection("Document")
            logger.info("Created Document collection")
        
        # Ensure document relationship collections exist
        if not self.db.has_collection("DOCUMENTS"):
            self.db.create_collection("DOCUMENTS", edge=True)
            logger.info("Created DOCUMENTS edge collection")
        
        if not self.db.has_collection("MENTIONS"):
            self.db.create_collection("MENTIONS", edge=True)
            logger.info("Created MENTIONS edge collection")
        
        # Cache for entities to avoid repeated database queries
        self.entity_cache = {}
        
    def find_markdown_files(self) -> List[Path]:
        """
        Find all markdown files in the repository.
        
        Returns:
            A list of paths to markdown files
        """
        markdown_files = []
        for path in self.repo_path.glob("**/*.md"):
            # Skip files in .git directory
            if ".git" in path.parts:
                continue
            markdown_files.append(path)
        
        logger.info(f"Found {len(markdown_files)} markdown files")
        return markdown_files
    
    def parse_markdown_file(self, file_path: Path) -> Dict:
        """
        Parse a markdown file into structured content.
        
        Args:
            file_path: Path to the markdown file
            
        Returns:
            A dictionary containing the structured content
        """
        try:
            content = file_path.read_text(encoding="utf-8")
            
            # Convert markdown to HTML
            html = markdown.markdown(content, extensions=['fenced_code', 'tables'])
            soup = BeautifulSoup(html, 'html.parser')
            
            # Extract headings and create structure
            headings = []
            current_heading_path = []
            current_level = 0
            
            for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                level = int(tag.name[1])
                
                # Adjust heading path based on level
                if level <= current_level:
                    current_heading_path = current_heading_path[:level-1]
                current_heading_path.append(tag.text)
                current_level = level
                
                headings.append({
                    'level': level,
                    'text': tag.text,
                    'path': current_heading_path.copy()
                })
            
            # Extract code blocks
            code_blocks = []
            for pre in soup.find_all('pre'):
                code = pre.find('code')
                if code:
                    code_blocks.append(code.text)
            
            return {
                'file_path': str(file_path),
                'relative_path': str(file_path.relative_to(self.repo_path)),
                'content': content,
                'headings': headings,
                'code_blocks': code_blocks
            }
        except Exception as e:
            logger.error(f"Error parsing markdown file {file_path}: {e}")
            return {
                'file_path': str(file_path),
                'relative_path': str(file_path.relative_to(self.repo_path)),
                'content': '',
                'headings': [],
                'code_blocks': []
            }
    
    def chunk_document(self, doc: Dict) -> List[DocumentChunk]:
        """
        Split a document into overlapping chunks for processing.
        
        Args:
            doc: Parsed document dictionary
            
        Returns:
            A list of DocumentChunk objects
        """
        content = doc['content']
        chunks = []
        
        # Split content by lines first to avoid breaking in the middle of a line
        lines = content.split('\n')
        current_chunk = []
        current_size = 0
        chunk_index = 0
        
        for i, line in enumerate(lines):
            line_size = len(line) + 1  # +1 for the newline
            
            # If adding this line would exceed chunk size, create a new chunk
            if current_size + line_size > self.chunk_size and current_chunk:
                # Find the current heading path for this chunk
                current_position = sum(len(l) + 1 for l in current_chunk)
                heading_path = self._get_heading_path_for_position(doc, current_position)
                
                # Create chunk
                chunks.append(DocumentChunk(
                    doc_id=doc['relative_path'],
                    content='\n'.join(current_chunk),
                    heading_path=heading_path,
                    code_blocks=self._get_code_blocks_for_chunk(doc, current_chunk),
                    position=chunk_index,
                    file_path=doc['file_path']
                ))
                
                # Start a new chunk with overlap
                overlap_start = max(0, len(current_chunk) - self.chunk_overlap // 30)  # Approximate lines for overlap
                current_chunk = current_chunk[overlap_start:]
                current_size = sum(len(l) + 1 for l in current_chunk)
                chunk_index += 1
            
            current_chunk.append(line)
            current_size += line_size
        
        # Add the last chunk if it's not empty
        if current_chunk:
            current_position = sum(len(l) + 1 for l in current_chunk)
            heading_path = self._get_heading_path_for_position(doc, current_position)
            
            chunks.append(DocumentChunk(
                doc_id=doc['relative_path'],
                content='\n'.join(current_chunk),
                heading_path=heading_path,
                code_blocks=self._get_code_blocks_for_chunk(doc, current_chunk),
                position=chunk_index,
                file_path=doc['file_path']
            ))
        
        return chunks
    
    def _get_heading_path_for_position(self, doc: Dict, position: int) -> List[str]:
        """
        Find the heading path for a given position in the document.
        
        Args:
            doc: Parsed document dictionary
            position: Position in the document
            
        Returns:
            A list of heading texts representing the path
        """
        content = doc['content']
        # Find all headings that appear before this position
        heading_positions = []
        
        for heading in doc['headings']:
            heading_text = heading['text']
            # Find all occurrences of this heading in the content
            for match in re.finditer(f"#+\\s+{re.escape(heading_text)}", content):
                heading_positions.append({
                    'position': match.start(),
                    'level': heading['level'],
                    'text': heading_text
                })
        
        # Sort by position
        heading_positions.sort(key=lambda h: h['position'])
        
        # Find headings that appear before our position
        relevant_headings = [h for h in heading_positions if h['position'] <= position]
        
        if not relevant_headings:
            return []
        
        # Build the path
        path = []
        current_level = 1
        
        for h in relevant_headings:
            # If we find a higher level heading, pop items from the path
            while len(path) > 0 and h['level'] <= current_level:
                path.pop()
                current_level -= 1
            
            path.append(h['text'])
            current_level = h['level']
        
        return path
    
    def _get_code_blocks_for_chunk(self, doc: Dict, chunk_lines: List[str]) -> List[str]:
        """
        Find code blocks that appear in the given chunk.
        
        Args:
            doc: Parsed document dictionary
            chunk_lines: Lines in the current chunk
            
        Returns:
            A list of code blocks
        """
        chunk_text = '\n'.join(chunk_lines)
        code_blocks = []
        
        # Look for code blocks in the chunk (```...```)
        code_block_pattern = r'```(?:\w+)?\n(.*?)```'
        for match in re.finditer(code_block_pattern, chunk_text, re.DOTALL):
            code_blocks.append(match.group(1))
        
        return code_blocks
    
    def store_document(self, doc: Dict) -> str:
        """
        Store a document in the ArangoDB database.
        
        Args:
            doc: Document dictionary
            
        Returns:
            The document ID
        """
        doc_collection = self.db.collection("Document")
        
        # Check if document already exists
        existing_docs = list(doc_collection.find({"file_path": doc['file_path']}))
        
        if existing_docs:
            # Update existing document
            doc_id = existing_docs[0]['_key']
            doc_collection.update({
                "_key": doc_id,
                "file_path": doc['file_path'],
                "relative_path": doc['relative_path'],
                "content": doc['content'],
                "headings": doc['headings'],
                "code_blocks": doc['code_blocks'],
                "updated_at": time.time()
            })
            logger.debug(f"Updated document {doc_id}")
        else:
            # Create new document
            result = doc_collection.insert({
                "file_path": doc['file_path'],
                "relative_path": doc['relative_path'],
                "content": doc['content'],
                "headings": doc['headings'],
                "code_blocks": doc['code_blocks'],
                "created_at": time.time(),
                "updated_at": time.time()
            })
            doc_id = result['_key']
            logger.debug(f"Created document {doc_id}")
        
        return doc_id
    
    def get_entities_by_name(self, name: str) -> List[Entity]:
        """
        Get entities by name from the knowledge graph.
        
        Args:
            name: Entity name to search for
            
        Returns:
            A list of Entity objects
        """
        # Check cache first
        cache_key = f"name:{name}"
        if cache_key in self.entity_cache:
            return self.entity_cache[cache_key]
        
        # Query for classes, methods, and files with this name
        entities = []
        
        # Query for classes
        for cls in self.db.collection("Class").find({"name": name}):
            entities.append(Entity(
                id=cls['_id'],
                name=cls['name'],
                entity_type="Class",
                file_path=cls.get('file_path'),
                content=cls.get('content'),
                parent_name=cls.get('parent_name'),
                parent_type=cls.get('parent_type'),
                description=cls.get('description')
            ))
        
        # Query for methods
        for method in self.db.collection("Method").find({"name": name}):
            entities.append(Entity(
                id=method['_id'],
                name=method['name'],
                entity_type="Method",
                file_path=method.get('file_path'),
                content=method.get('content'),
                parent_name=method.get('parent_name'),
                parent_type=method.get('parent_type'),
                description=method.get('description')
            ))
        
        # Query for files
        for file in self.db.collection("File").find({"file_name": name}):
            entities.append(Entity(
                id=file['_id'],
                name=file['file_name'],
                entity_type="File",
                file_path=file.get('file_path'),
                content=file.get('content'),
                description=file.get('description')
            ))
        
        # Cache the results
        self.entity_cache[cache_key] = entities
        return entities
    
    def get_entity_by_id(self, entity_id: str) -> Optional[Entity]:
        """
        Get an entity by its ID.
        
        Args:
            entity_id: Entity ID
            
        Returns:
            Entity object or None if not found
        """
        # Check cache first
        if entity_id in self.entity_cache:
            return self.entity_cache[entity_id]
        
        # Parse the ID to get collection and key
        parts = entity_id.split('/')
        if len(parts) != 2:
            logger.error(f"Invalid entity ID format: {entity_id}")
            return None
        
        collection_name, key = parts
        
        try:
            entity_doc = self.db.collection(collection_name).get(key)
            if not entity_doc:
                return None
            
            entity = Entity(
                id=entity_id,
                name=entity_doc.get('name', entity_doc.get('file_name', '')),
                entity_type=collection_name,
                file_path=entity_doc.get('file_path'),
                content=entity_doc.get('content'),
                parent_name=entity_doc.get('parent_name'),
                parent_type=entity_doc.get('parent_type'),
                description=entity_doc.get('description')
            )
            
            # Cache the entity
            self.entity_cache[entity_id] = entity
            return entity
        except Exception as e:
            logger.error(f"Error retrieving entity {entity_id}: {e}")
            return None
    
    def get_candidate_entities(self, chunk: DocumentChunk) -> List[Entity]:
        """
        Generate candidate entities that might be mentioned in a document chunk.
        
        Args:
            chunk: Document chunk
            
        Returns:
            A list of candidate Entity objects
        """
        candidates = []
        seen_ids = set()
        
        # Extract potential entity names from the chunk
        # This is a simple approach - in a real system, you might use NER or other techniques
        content = chunk.content
        
        # Look for CamelCase words that might be class names
        class_pattern = r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b'
        for match in re.finditer(class_pattern, content):
            name = match.group(0)
            entities = self.get_entities_by_name(name)
            for entity in entities:
                if entity.id not in seen_ids:
                    candidates.append(entity)
                    seen_ids.add(entity.id)
        
        # Look for potential method names (snake_case or camelCase)
        method_pattern = r'\b[a-z]+(?:_[a-z]+)+\b|\b[a-z]+(?:[A-Z][a-z]+)+\b'
        for match in re.finditer(method_pattern, content):
            name = match.group(0)
            entities = self.get_entities_by_name(name)
            for entity in entities:
                if entity.id not in seen_ids:
                    candidates.append(entity)
                    seen_ids.add(entity.id)
        
        # Look for file names in code blocks
        for code_block in chunk.code_blocks:
            file_pattern = r'\b[\w-]+\.(?:py|java|js|ts|html|css|md)\b'
            for match in re.finditer(file_pattern, code_block):
                name = match.group(0)
                entities = self.get_entities_by_name(name)
                for entity in entities:
                    if entity.id not in seen_ids:
                        candidates.append(entity)
                        seen_ids.add(entity.id)
        
        # If we have a heading path, try to use it for context
        if chunk.heading_path:
            for heading in chunk.heading_path:
                # Try to find entities with names similar to headings
                entities = self.get_entities_by_name(heading)
                for entity in entities:
                    if entity.id not in seen_ids:
                        candidates.append(entity)
                        seen_ids.add(entity.id)
        
        return candidates
    
    def identify_entity_mentions(self, chunk: DocumentChunk) -> List[EntityMention]:
        """
        Use Gemini to identify entity mentions in a document chunk.
        
        Args:
            chunk: Document chunk
            
        Returns:
            A list of EntityMention objects
        """
        # Get candidate entities
        candidates = self.get_candidate_entities(chunk)
        
        if not candidates:
            logger.debug(f"No candidate entities found for chunk in {chunk.file_path}")
            return []
        
        # Prepare candidate information for the LLM
        candidate_info = []
        for i, entity in enumerate(candidates):
            # Truncate content if it's too long
            content = entity.content
            if content and len(content) > 500:
                content = content[:500] + "..."
                
            candidate_info.append({
                "id": i,  # Use index as ID for the prompt
                "name": entity.name,
                "type": entity.entity_type,
                "file_path": entity.file_path,
                "parent_name": entity.parent_name,
                "parent_type": entity.parent_type,
                "content_preview": content
            })
        
        # Prepare the prompt
        prompt = f"""
You are an expert code analyzer for Apache Airflow. You need to identify which code entities are mentioned in the following document chunk.

Document path: {chunk.file_path}
Document section: {' > '.join(chunk.heading_path) if chunk.heading_path else 'Unknown section'}

Document chunk content:

{chunk.content}

Candidate code entities:
{json.dumps(candidate_info, indent=2)}

For each candidate entity that is EXPLICITLY mentioned or referenced in the document chunk, provide:
1. The entity ID (from the candidate list)
2. How it's mentioned in the text (direct reference, example usage, explanation, etc.)
3. Confidence score (0.0-1.0) that this is a genuine reference
4. The type of relationship (DOCUMENTS, MENTIONS, EXPLAINS, USES, REFERS_TO)
5. Brief context from the document that shows the mention

Only include entities that are genuinely referenced in the document with confidence > 0.6.
Format your response as a JSON array with objects containing fields: entity_id, mention_type, confidence, relation_type, context.

Example response format:
```json
[
  {
    "entity_id": 2,
    "mention_type": "API reference",
    "confidence": 0.95,
    "relation_type": "DOCUMENTS",
    "context": "The DAG class is the primary building block..."
  }
]

"""
        try:
            # Call Gemini API
            response = self.model.generate_content(prompt)
            
            # Extract JSON from response
            response_text = response.text
            
            # Find JSON in the response
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response_text)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find JSON without the markdown code block
                json_match = re.search(r'\[\s*\{.*\}\s*\]', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    logger.warning(f"Could not extract JSON from response: {response_text}")
                    return []
            
            # Parse JSON
            mentions_data = json.loads(json_str)
            
            # Convert to EntityMention objects
            mentions = []
            for mention in mentions_data:
                entity_index = mention["entity_id"]
                if entity_index < 0 or entity_index >= len(candidates):
                    logger.warning(f"Invalid entity ID: {entity_index}")
                    continue
                
                entity = candidates[entity_index]
                
                mentions.append(EntityMention(
                    entity_id=entity.id,
                    mention_text=mention["mention_type"],
                    confidence=mention["confidence"],
                    relation_type=mention["relation_type"],
                    context=mention["context"]
                ))
            
            # Filter by confidence threshold
            mentions = [m for m in mentions if m.confidence >= self.confidence_threshold]
            
            return mentions
        except Exception as e:
            logger.error(f"Error identifying entity mentions: {e}")
            return []

    def store_entity_mentions(self, doc_id: str, mentions: List[EntityMention]):
        """
        Store entity mentions in the knowledge graph.
        
        Args:
            doc_id: Document ID
            mentions: List of EntityMention objects
        """
        for mention in mentions:
            # Determine which edge collection to use based on relation type
            edge_collection_name = mention.relation_type
            if edge_collection_name not in ["DOCUMENTS", "MENTIONS", "EXPLAINS", "USES", "REFERS_TO"]:
                edge_collection_name = "MENTIONS"  # Default to MENTIONS
            
            # Ensure the edge collection exists
            if not self.db.has_collection(edge_collection_name):
                self.db.create_collection(edge_collection_name, edge=True)
                logger.info(f"Created edge collection {edge_collection_name}")
            
            edge_collection = self.db.collection(edge_collection_name)
            
            # Create a unique key for the edge
            edge_key = f"{doc_id.replace('/', '_')}_{mention.entity_id.replace('/', '_')}"
            
            # Check if edge already exists
            existing_edge = None
            try:
                existing_edge = edge_collection.get(edge_key)
            except:
                pass
            
            edge_data = {
                "_from": f"Document/{doc_id}",
                "_to": mention.entity_id,
                "mention_text": mention.mention_text,
                "confidence": mention.confidence,
                "context": mention.context,
                "updated_at": time.time()
            }
            
            if existing_edge:
                # Update existing edge
                edge_collection.update({
                    "_key": edge_key,
                    **edge_data
                })
                logger.debug(f"Updated {edge_collection_name} edge {edge_key}")
            else:
                # Create new edge
                try:
                    edge_collection.insert({
                        "_key": edge_key,
                        **edge_data
                    })
                    logger.debug(f"Created {edge_collection_name} edge {edge_key}")
                except Exception as e:
                    logger.error(f"Error creating edge {edge_key}: {e}")
    
    def process_markdown_file(self, file_path: Path) -> str:
        """
        Process a markdown file: parse, store, and identify entity mentions.
        
        Args:
            file_path: Path to the markdown file
            
        Returns:
            Document ID
        """
        # Parse the markdown file
        doc = self.parse_markdown_file(file_path)
        
        # Store the document
        doc_id = self.store_document(doc)
        
        # Chunk the document
        chunks = self.chunk_document(doc)
        
        # Process each chunk
        all_mentions = []
        for chunk in chunks:
            mentions = self.identify_entity_mentions(chunk)
            all_mentions.extend(mentions)
        
        # Store entity mentions
        self.store_entity_mentions(doc_id, all_mentions)
        
        logger.info(f"Processed {file_path} - Found {len(all_mentions)} entity mentions")
        
        return doc_id
    
    def process_all_markdown_files(self):
        """
        Process all markdown files in the repository.
        """
        markdown_files = self.find_markdown_files()
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            list(tqdm(
                executor.map(self.process_markdown_file, markdown_files),
                total=len(markdown_files),
                desc="Processing markdown files"
            ))
    
    def get_core_entities(self, limit: int = 100) -> List[Entity]:
        """
        Identify core entities in the knowledge graph using a PageRank-like algorithm.
        
        Args:
            limit: Maximum number of entities to return
            
        Returns:
            A list of core Entity objects
        """
        # Use AQL to find entities with the most relationships
        aql_query = """
        LET class_scores = (
            FOR c IN Class
                LET incoming = LENGTH(FOR v, e IN 1..1 INBOUND c._id GRAPH 'airflow_code_graph' RETURN 1)
                LET outgoing = LENGTH(FOR v, e IN 1..1 OUTBOUND c._id GRAPH 'airflow_code_graph' RETURN 1)
                RETURN {
                    id: c._id,
                    name: c.name,
                    entity_type: 'Class',
                    file_path: c.file_path,
                    score: incoming + outgoing
                }
        )
        
        LET method_scores = (
            FOR m IN Method
                LET incoming = LENGTH(FOR v, e IN 1..1 INBOUND m._id GRAPH 'airflow_code_graph' RETURN 1)
                LET outgoing = LENGTH(FOR v, e IN 1..1 OUTBOUND m._id GRAPH 'airflow_code_graph' RETURN 1)
                RETURN {
                    id: m._id,
                    name: m.name,
                    entity_type: 'Method',
                    file_path: m.file_path,
                    score: incoming + outgoing
                }
        )
        
        LET all_scores = APPEND(class_scores, method_scores)
        
        FOR entity IN all_scores
            SORT entity.score DESC
            LIMIT @limit
            RETURN entity
        """
        
        try:
            cursor = self.db.aql.execute(
                aql_query, 
                bind_vars={"limit": limit},
                count=True
            )
            
            results = list(cursor)
            
            # Convert to Entity objects
            entities = []
            for result in results:
                entity = self.get_entity_by_id(result['id'])
                if entity:
                    entities.append(entity)
            
            return entities
        except Exception as e:
            logger.error(f"Error getting core entities: {e}")
            
            # Fallback: Get entities with direct queries
            entities = []
            
            # Get top classes
            classes = list(self.db.collection("Class").all(limit=limit//2))
            for cls in classes:
                entities.append(Entity(
                    id=cls['_id'],
                    name=cls['name'],
                    entity_type="Class",
                    file_path=cls.get('file_path'),
                    content=cls.get('content'),
                    parent_name=cls.get('parent_name'),
                    parent_type=cls.get('parent_type'),
                    description=cls.get('description')
                ))
            
            # Get top methods
            methods = list(self.db.collection("Method").all(limit=limit//2))
            for method in methods:
                entities.append(Entity(
                    id=method['_id'],
                    name=method['name'],
                    entity_type="Method",
                    file_path=method.get('file_path'),
                    content=method.get('content'),
                    parent_name=method.get('parent_name'),
                    parent_type=method.get('parent_type'),
                    description=method.get('description')
                ))
            
            return entities
    
    def get_entity_context(self, entity: Entity) -> Dict:
        """
        Build rich context for an entity to aid in documentation generation.
        
        Args:
            entity: Entity to build context for
            
        Returns:
            Dictionary containing context information
        """
        context = {
            "entity": {
                "id": entity.id,
                "name": entity.name,
                "type": entity.entity_type,
                "file_path": entity.file_path,
                "content": entity.content,
                "parent_name": entity.parent_name,
                "parent_type": entity.parent_type,
                "description": entity.description
            },
            "related_entities": [],
            "existing_documentation": [],
            "usage_examples": []
        }
        
        try:
            # Get related entities (incoming and outgoing edges)
            aql_query = """
            LET incoming = (
                FOR v, e IN 1..1 INBOUND @entity_id GRAPH 'airflow_code_graph'
                RETURN {
                    id: v._id,
                    name: v.name || v.file_name,
                    type: PARSE_IDENTIFIER(v._id).collection,
                    relation: PARSE_IDENTIFIER(e._id).collection,
                    direction: "incoming"
                }
            )
            
            LET outgoing = (
                FOR v, e IN 1..1 OUTBOUND @entity_id GRAPH 'airflow_code_graph'
                RETURN {
                    id: v._id,
                    name: v.name || v.file_name,
                    type: PARSE_IDENTIFIER(v._id).collection,
                    relation: PARSE_IDENTIFIER(e._id).collection,
                    direction: "outgoing"
                }
            )
            
            RETURN {
                incoming: incoming,
                outgoing: outgoing
            }
            """
            
            cursor = self.db.aql.execute(
                aql_query,
                bind_vars={"entity_id": entity.id}
            )
            
            result = next(cursor)
            
            # Add related entities to context
            for related in result['incoming']:
                related_entity = self.get_entity_by_id(related['id'])
                if related_entity and related_entity.content:
                    # Truncate content if it's too long
                    content = related_entity.content
                    if len(content) > 300:
                        content = content[:300] + "..."
                    
                    context["related_entities"].append({
                        "id": related_entity.id,
                        "name": related_entity.name,
                        "type": related_entity.entity_type,
                        "relation": related['relation'],
                        "direction": "incoming",
                        "content_preview": content
                    })
            
            for related in result['outgoing']:
                related_entity = self.get_entity_by_id(related['id'])
                if related_entity and related_entity.content:
                    # Truncate content if it's too long
                    content = related_entity.content
                    if len(content) > 300:
                        content = content[:300] + "..."
                    
                    context["related_entities"].append({
                        "id": related_entity.id,
                        "name": related_entity.name,
                        "type": related_entity.entity_type,
                        "relation": related['relation'],
                        "direction": "outgoing",
                        "content_preview": content
                    })
            
            # Get existing documentation
            aql_query = """
            FOR v, e IN 1..1 INBOUND @entity_id DOCUMENTS, MENTIONS, EXPLAINS
            RETURN {
                id: v._id,
                path: v.relative_path,
                relation: PARSE_IDENTIFIER(e._id).collection,
                context: e.context
            }
            """
            
            cursor = self.db.aql.execute(
                aql_query,
                bind_vars={"entity_id": entity.id}
            )
            
            for doc in cursor:
                context["existing_documentation"].append(doc)
            
            # Get usage examples
            if entity.entity_type == "Method":
                aql_query = """
                FOR v, e IN 1..1 INBOUND @entity_id CALLS
                LIMIT 5
                RETURN {
                    id: v._id,
                    name: v.name,
                    file_path: v.file_path,
                    source_location: e.source_location
                }
                """
                
                cursor = self.db.aql.execute(
                    aql_query,
                    bind_vars={"entity_id": entity.id}
                )
                
                for usage in cursor:
                    context["usage_examples"].append(usage)
            
            return context
        except Exception as e:
            logger.error(f"Error building context for {entity.id}: {e}")
            return context
    
    def generate_entity_documentation(self, entity: Entity) -> Dict:
        """
        Generate documentation for an entity using Gemini.
        
        Args:
            entity: Entity to generate documentation for
            
        Returns:
            Dictionary containing generated documentation
        """
        # Build rich context
        context = self.get_entity_context(entity)
        
        # Determine the prompt based on entity type
        if entity.entity_type == "Class":
            prompt = self._build_class_documentation_prompt(entity, context)
        elif entity.entity_type == "Method":
            prompt = self._build_method_documentation_prompt(entity, context)
        else:
            prompt = self._build_generic_documentation_prompt(entity, context)
        
        try:
            # Call Gemini API
            response = self.model.generate_content(prompt)
            
            # Extract JSON from response
            response_text = response.text
            
            # Find JSON in the response
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response_text)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find JSON without the markdown code block
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    logger.warning(f"Could not extract JSON from response: {response_text}")
                    return {
                        "error": "Failed to parse response",
                        "raw_response": response_text
                    }
            
            # Parse JSON
            documentation = json.loads(json_str)
            
            # Add metadata
            documentation["entity_id"] = entity.id
            documentation["entity_name"] = entity.name
            documentation["entity_type"] = entity.entity_type
            documentation["generated_at"] = time.time()
            
            return documentation
        except Exception as e:
            logger.error(f"Error generating documentation for {entity.id}: {e}")
            return {
                "error": str(e),
                "entity_id": entity.id,
                "entity_name": entity.name,
                "entity_type": entity.entity_type
            }
    
    def _build_class_documentation_prompt(self, entity: Entity, context: Dict) -> str:
        """
        Build a prompt for class documentation generation.
        
        Args:
            entity: Class entity
            context: Context information
            
        Returns:
            Prompt string
        """
        # Extract methods of this class
        class_methods = []
        for related in context["related_entities"]:
            if related["type"] == "Method" and related["direction"] == "outgoing":
                class_methods.append(related)
        
        # Extract parent classes
        parent_classes = []
        for related in context["related_entities"]:
            if related["relation"] == "INHERITS" and related["direction"] == "outgoing":
                parent_classes.append(related)
        
        prompt = f"""
You are an expert technical documentation writer for Apache Airflow. Generate comprehensive documentation for the following class:

Class Name: {entity.name}
File Path: {entity.file_path}
Parent Class: {', '.join([p["name"] for p in parent_classes]) if parent_classes else "None"}

Class Code:
```python
{entity.content}

{'## Related Methods\n' + '\n'.join([f"- {m['name']}: {m['content_preview']}" for m in class_methods[:5]]) if class_methods else ""}
{'## Existing Documentation\n' + '\n'.join([f"- {d['path']}: {d['context']}" for d in context["existing_documentation"][:3]]) if context["existing_documentation"] else ""}
Generate detailed documentation for this class in JSON format with the following sections:

A clear, concise description of the class's purpose and functionality
Key features and capabilities
Important attributes/properties
Main methods with brief descriptions
Usage examples (based on the context or create realistic examples)
Common patterns and best practices
Related classes or components

Format your response as a JSON object with these fields:

description: A comprehensive description of the class
key_features: Array of key features
attributes: Array of objects with name, type, and description
methods: Array of objects with name, description, parameters, and return_value
usage_examples: Array of code examples with descriptions
best_practices: Array of best practices when using this class
related_components: Array of related classes or components

Example format:
{
  "description": "Detailed description...",
  "key_features": ["Feature 1", "Feature 2"],
  "attributes": [
    {"name": "attr_name", "type": "str", "description": "Description"}
  ],
  "methods": [
    {
      "name": "method_name",
      "description": "Description",
      "parameters": [{"name": "param", "type": "str", "description": "Desc"}],
      "return_value": {"type": "dict", "description": "Return description"}
    }
  ],
  "usage_examples": [
    {
      "description": "Example description",
      "code": "code_example_here"
    }
  ],
  "best_practices": ["Practice 1", "Practice 2"],
  "related_components": ["RelatedClass", "AnotherComponent"]
}

Ensure your documentation is accurate, comprehensive, and follows Airflow's documentation style. Focus on helping developers understand how to use this class effectively.
"""
        return prompt

    def _build_method_documentation_prompt(self, entity: Entity, context: Dict) -> str:
        """
        Build a prompt for method documentation generation.
        
        Args:
            entity: Method entity
            context: Context information
            
        Returns:
            Prompt string
        """
        # Extract methods called by this method
        called_methods = []
        for related in context["related_entities"]:
            if related["relation"] == "CALLS" and related["direction"] == "outgoing":
                called_methods.append(related)
        
        # Extract methods that call this method
        calling_methods = []
        for related in context["related_entities"]:
            if related["relation"] == "CALLS" and related["direction"] == "incoming":
                calling_methods.append(related)
        
        prompt = f"""
You are an expert technical documentation writer for Apache Airflow. Generate comprehensive documentation for the following method:
Method Name: {entity.name}
File Path: {entity.file_path}
Parent Class: {entity.parent_name if entity.parent_name else "None"}
Method Code:
{entity.content}

{'## Methods Called by This Method\n' + '\n'.join([f"- {m['name']}: {m['content_preview']}" for m in called_methods[:3]]) if called_methods else ""}
{'## Methods That Call This Method\n' + '\n'.join([f"- {m['name']}: {m['content_preview']}" for m in calling_methods[:3]]) if calling_methods else ""}
{'## Usage Examples\n' + '\n'.join([f"- In {u['name']} at {u['source_location']}" for u in context["usage_examples"]]) if context["usage_examples"] else ""}
{'## Existing Documentation\n' + '\n'.join([f"- {d['path']}: {d['context']}" for d in context["existing_documentation"][:3]]) if context["existing_documentation"] else ""}
Generate detailed documentation for this method in JSON format with the following sections:

A clear, concise description of the method's purpose and functionality
Parameters with types and descriptions
Return value with type and description
Exceptions that might be raised
Usage examples
Notes or caveats

Format your response as a JSON object with these fields:

description: A comprehensive description of the method
parameters: Array of objects with name, type, description, and whether it's optional
return_value: Object with type and description
exceptions: Array of objects with type and condition
usage_examples: Array of code examples with descriptions
notes: Array of additional notes or caveats

Example format:
{
"description": "Detailed description...",
"parameters": [
    {"name": "param_name", "type": "str", "description": "Description", "optional": false}
],
"return_value": {"type": "dict", "description": "Return description"},
"exceptions": [
    {"type": "ValueError", "condition": "When input is invalid"}
],
"usage_examples": [
    {
    "description": "Example description",
    "code": "code_example_here"
    }
],
"notes": ["Note 1", "Note 2"]
}

Ensure your documentation is accurate, comprehensive, and follows Airflow's documentation style. Focus on helping developers understand how to use this method effectively.
"""
        return prompt
    
    def _build_generic_documentation_prompt(self, entity: Entity, context: Dict) -> str:
        """
        Build a prompt for generic entity documentation generation.
        
        Args:
            entity: Entity
            context: Context information
            
        Returns:
            Prompt string
        """
        prompt = f"""

    You are an expert technical documentation writer for Apache Airflow. Generate comprehensive documentation for the following entity:
    Entity Name: {entity.name}
    Entity Type: {entity.entity_type}
    File Path: {entity.file_path}
    Entity Content:
    {entity.content}

    {'## Related Entities\n' + '\n'.join([f"- {r['name']} ({r['type']}): {r['relation']} ({r['direction']})" for r in context["related_entities"][:5]]) if context["related_entities"] else ""}
    {'## Existing Documentation\n' + '\n'.join([f"- {d['path']}: {d['context']}" for d in context["existing_documentation"][:3]]) if context["existing_documentation"] else ""}
    Generate detailed documentation for this entity in JSON format with the following sections:

    A clear, concise description of the entity's purpose and functionality
    Key features or characteristics
    Usage information
    Related components

    Format your response as a JSON object with these fields:

    description: A comprehensive description of the entity
    key_features: Array of key features or characteristics
    usage: Description of how this entity is used
    related_components: Array of related entities or components

    Example format:
    {
    "description": "Detailed description...",
    "key_features": ["Feature 1", "Feature 2"],
    "usage": "How this entity is used...",
    "related_components": ["RelatedEntity", "AnotherComponent"]
    }

    Ensure your documentation is accurate, comprehensive, and follows Airflow's documentation style. Focus on helping developers understand this entity effectively.
    """
        return prompt

    def store_entity_documentation(self, documentation: Dict) -> str:
        """
        Store entity documentation in the knowledge graph.
        
        Args:
            documentation: Documentation dictionary
            
        Returns:
            Documentation ID
        """
        # Create a document collection for entity documentation if it doesn't exist
        if not self.db.has_collection("EntityDocumentation"):
            self.db.create_collection("EntityDocumentation")
            logger.info("Created EntityDocumentation collection")
        
        doc_collection = self.db.collection("EntityDocumentation")
        
        entity_id = documentation.get("entity_id")
        if not entity_id:
            logger.error("Documentation missing entity_id")
            return None
        
        # Create a key from the entity ID
        doc_key = entity_id.replace("/", "_")
        
        # Check if documentation already exists
        existing_doc = None
        try:
            existing_doc = doc_collection.get(doc_key)
        except:
            pass
        
        if existing_doc:
            # Update existing documentation
            doc_collection.update({
                "_key": doc_key,
                **documentation,
                "updated_at": time.time()
            })
            logger.debug(f"Updated documentation for {entity_id}")
        else:
            # Create new documentation
            doc_collection.insert({
                "_key": doc_key,
                **documentation,
                "created_at": time.time(),
                "updated_at": time.time()
            })
            logger.debug(f"Created documentation for {entity_id}")
        
        # Create a DOCUMENTED_BY edge from the entity to the documentation
        if not self.db.has_collection("DOCUMENTED_BY"):
            self.db.create_collection("DOCUMENTED_BY", edge=True)
            logger.info("Created DOCUMENTED_BY edge collection")
        
        edge_collection = self.db.collection("DOCUMENTED_BY")
        edge_key = f"{entity_id.replace('/', '_')}_doc"
        
        # Check if edge already exists
        existing_edge = None
        try:
            existing_edge = edge_collection.get(edge_key)
        except:
            pass
        
        if existing_edge:
            # Update existing edge
            edge_collection.update({
                "_key": edge_key,
                "_from": entity_id,
                "_to": f"EntityDocumentation/{doc_key}",
                "updated_at": time.time()
            })
        else:
            # Create new edge
            try:
                edge_collection.insert({
                    "_key": edge_key,
                    "_from": entity_id,
                    "_to": f"EntityDocumentation/{doc_key}",
                    "created_at": time.time(),
                    "updated_at": time.time()
                })
            except Exception as e:
                logger.error(f"Error creating DOCUMENTED_BY edge: {e}")
        
        return doc_key

    def generate_documentation_for_core_entities(self, limit: int = 100):
        """
        Generate documentation for core entities in the knowledge graph.
        
        Args:
            limit: Maximum number of entities to process
        """
        # Get core entities
        core_entities = self.get_core_entities(limit=limit)
        
        logger.info(f"Generating documentation for {len(core_entities)} core entities")
        
        for entity in tqdm(core_entities, desc="Generating documentation"):
            # Generate documentation
            documentation = self.generate_entity_documentation(entity)
            
            # Store documentation
            if "error" not in documentation:
                self.store_entity_documentation(documentation)
            else:
                logger.error(f"Error generating documentation for {entity.id}: {documentation['error']}")

    def run_full_workflow(self, doc_limit: int = 100):
        """
        Run the full workflow: process markdown files and generate documentation.
        
        Args:
            doc_limit: Maximum number of core entities to document
        """
        # Process all markdown files
        logger.info("Processing markdown files...")
        self.process_all_markdown_files()
        
        # Generate documentation for core entities
        logger.info("Generating documentation for core entities...")
        self.generate_documentation_for_core_entities(limit=doc_limit)
        
        logger.info("Workflow completed successfully!")

if __name__ == "main":
    import argparse
    parser = argparse.ArgumentParser(description="Airflow Knowledge Graph Document Builder")
    parser.add_argument("--repo-path", required=True, help="Path to the Airflow repository")
    parser.add_argument("--arango-url", default="http://localhost:8529", help="ArangoDB URL")
    parser.add_argument("--arango-db", default="apache_airflow", help="ArangoDB database name")
    parser.add_argument("--arango-username", default="root", help="ArangoDB username")
    parser.add_argument("--arango-password", default="", help="ArangoDB password")
    parser.add_argument("--gemini-api-key", required=True, help="Gemini API key")
    parser.add_argument("--doc-limit", type=int, default=100, help="Maximum number of entities to document")
    parser.add_argument("--max-workers", type=int, default=4, help="Maximum number of concurrent workers")
    parser.add_argument("--mode", choices=["full", "markdown-only", "doc-only"], default="full", 
                        help="Workflow mode: full, markdown-only, or doc-only")

    args = parser.parse_args()

    builder = AirflowKGDocumentBuilder(
        repo_path=args.repo_path,
        arango_url=args.arango_url,
        arango_db=args.arango_db,
        arango_username=args.arango_username,
        arango_password=args.arango_password,
        gemini_api_key=args.gemini_api_key,
        max_workers=args.max_workers
    )

    if args.mode == "full":
        builder.run_full_workflow(doc_limit=args.doc_limit)
    elif args.mode == "markdown-only":
        builder.process_all_markdown_files()
    elif args.mode == "doc-only":
        builder.generate_documentation_for_core_entities(limit=args.doc_limit)