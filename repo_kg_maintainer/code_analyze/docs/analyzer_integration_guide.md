# Analyzer Integration Guide for Go Developers

This document provides guidance for integrating Go analyzer services with the repo-graph-rag knowledge graph system, focusing on the technical details and API specifications needed for successful integration.

## 1. Architecture Overview

![High Level Architecture](./repo_kg_maintainer/code_analyze/docs/analyzer_integration_guide.drawio.svg)

## 2. Integration Process

The Go analyzer service integrates with the repo-graph-rag system through the following steps:

1. **Entity Extraction Phase**
   - The system discovers a Go file (.go)
   - The system sends the file content to the Go analyzer service
   - The Go service extracts entities (structs, methods, interfaces, etc.)
   - The extracted entities are returned and stored in the knowledge graph

2. **Relation Extraction Phase**
   - After all entities are collected, the system sends each Go file with the complete entity collection
   - The Go analyzer extracts relationships between entities (calls, imports, etc.)
   - The extracted relationships are returned and stored in the knowledge graph

## 3. API Specification

### 3.1 Entity Extraction Endpoint

```
Endpoint: /extract-entities
Method: POST
Content-Type: application/json
```

**Request Body:**
```json
{
  "file_path": "path/to/file.go",
  "content": "package main\n\nimport \"fmt\"\n\nfunc main() {\n\tfmt.Println(\"Hello, world!\")\n}",
  "language": "go"
}
```

**Response Body:**
```json
{
  "file_info": {
    "entity_type": "File",
    "file_path": "path/to/file.go",
    "file_type": "go",
    "content": "package main\n\nimport \"fmt\"\n\nfunc main() {\n\tfmt.Println(\"Hello, world!\")\n}",
    "size": 78,
    "description": "Main package file with entry point"
  },
  "entities": [
    {
      "entity_type": "Method",
      "name": "main",
      "parent_name": "",
      "parent_type": "",
      "file_path": "path/to/file.go",
      "description": "Main entry point for the program",
      "complexity": 1,
      "content": "func main() {\n\tfmt.Println(\"Hello, world!\")\n}",
      "is_exported": false,
      "modifiers": []
    }
  ]
}
```

### 3.2 Relation Extraction Endpoint

```
Endpoint: /extract-relations
Method: POST
Content-Type: application/json
```

**Request Body:**
```json
{
  "file_path": "path/to/file.go",
  "content": "package main\n\nimport \"fmt\"\n\nfunc main() {\n\tfmt.Println(\"Hello, world!\")\n}",
  "repo_entities": [
    {
      "entity_type": "Method",
      "name": "main",
      "parent_name": "",
      "parent_type": "",
      "file_path": "path/to/file.go",
      "description": "Main entry point for the program",
      "complexity": 1,
      "content": "func main() {\n\tfmt.Println(\"Hello, world!\")\n}",
      "is_exported": false,
      "modifiers": []
    },
    {
      "entity_type": "Method",
      "name": "Println",
      "parent_name": "fmt",
      "parent_type": "Package",
      "file_path": "fmt/print.go",
      "description": "Prints to the standard output",
      "complexity": 2,
      "is_exported": true,
      "modifiers": []
    }
  ]
}
```

**Response Body:**
```json
{
  "relations": [
    {
      "source": {
        "name": "main",
        "key": "Method/path/to/file.go/main",
        "entity_type": "Method",
        "parent_name": "",
        "module_path": "path/to/file.go",
        "is_local": true
      },
      "target": {
        "name": "Println",
        "key": "Method/fmt/print.go/fmt/Println",
        "entity_type": "Method",
        "parent_name": "fmt",
        "module_path": "fmt/print.go",
        "is_local": false
      },
      "relation_type": "CALLS",
      "source_location": [5, 2],
      "target_location": [5, 6],
      "metadata": {
        "call_arguments": ["\"Hello, world!\""]
      }
    }
  ]
}
```

## 4. Data Structures

### 4.1 Core Entity Types

```go
// EntityType represents the type of code entity
type EntityType string

const (
    EntityTypeRepository EntityType = "Repository"
    EntityTypeModule     EntityType = "Module"
    EntityTypeFile       EntityType = "File"
    EntityTypeClass      EntityType = "Class"
    EntityTypeMethod     EntityType = "Method"
    EntityTypeInterface  EntityType = "Interface"
    EntityTypeVariable   EntityType = "Variable"
    EntityTypeDocument   EntityType = "Document"
    EntityTypeEnum       EntityType = "Enum"
)
```

### 4.2 Core Relation Types

```go
// RelationType represents the type of relationship between entities
type RelationType string

const (
    RelationTypeInherits  RelationType = "INHERITS"
    RelationTypeCalls     RelationType = "CALLS"
    RelationTypeContains  RelationType = "CONTAINS"
    RelationTypeDecorates RelationType = "DECORATES"
    RelationTypeReferences RelationType = "REFERENCES"
    RelationTypeImports   RelationType = "IMPORTS"
)
```

### 4.3 Entity Information Structure

```go
// EntityInfo represents a code entity with its metadata
type EntityInfo struct {
    EntityType  string   `json:"entity_type"`
    Name        string   `json:"name"`
    ParentName  string   `json:"parent_name,omitempty"`
    ParentType  string   `json:"parent_type,omitempty"`
    FilePath    string   `json:"file_path,omitempty"`
    Description string   `json:"description,omitempty"`
    Complexity  int      `json:"complexity,omitempty"`
    Content     string   `json:"content,omitempty"`
    IsExported  bool     `json:"is_exported,omitempty"`
    Modifiers   []string `json:"modifiers,omitempty"`
}
```

### 4.4 File Information Structure

```go
// FileInfo represents a file with its metadata
type FileInfo struct {
    EntityType  string `json:"entity_type"`
    FilePath    string `json:"file_path"`
    FileType    string `json:"file_type"`
    Content     string `json:"content"`
    Size        int    `json:"size,omitempty"`
    Description string `json:"description,omitempty"`
}
```

### 4.5 Relation Structures

```go
// EntityReference represents a reference to an entity
type EntityReference struct {
    Name       string `json:"name"`
    Key        string `json:"key"`
    EntityType string `json:"entity_type,omitempty"`
    ParentName string `json:"parent_name,omitempty"`
    ModulePath string `json:"module_path,omitempty"`
    IsLocal    bool   `json:"is_local,omitempty"`
}

// RelationInfo represents a relationship between entities
type RelationInfo struct {
    Source         EntityReference        `json:"source"`
    Target         EntityReference        `json:"target"`
    RelationType   string                 `json:"relation_type"`
    SourceLocation [2]int                 `json:"source_location"`
    TargetLocation [2]int                 `json:"target_location"`
    Metadata       map[string]interface{} `json:"metadata,omitempty"`
}
```

## 5. Entity Key Generation

Entity keys must follow the same pattern as in the Python code to ensure proper entity resolution and relationship mapping:

```go
// GenerateEntityKey generates a unique key for an entity
func GenerateEntityKey(entityType string, filePath string, name string, parentName string) string {
    key := entityType + "/" + filePath
    if parentName != "" {
        key += "/" + parentName
    }
    key += "/" + name
    
    // Sanitize key to remove invalid characters
    sanitized := regexp.MustCompile("[^a-zA-Z0-9\\-_]").ReplaceAllString(key, "_")
    
    // Ensure key length does not exceed 254 characters
    if len(sanitized) > 254 {
        sanitized = sanitized[:251]
    }
    
    return sanitized
}
```

This key generation is crucial for the system to correctly identify and link entities. The key format follows:
- For entities without parents: `{EntityType}/{FilePath}/{Name}`
- For entities with parents: `{EntityType}/{FilePath}/{ParentName}/{Name}`

## 6. Go Language Entity Mapping

| Go Construct | Entity Type | Description |
|--------------|------------|-------------|
| Package | Module | Top-level grouping of code |
| Function | Method | Global functions map to Method type |
| Method | Method | Struct methods |
| Struct | Class | Go structs map to Class entity type |
| Interface | Interface | Go interfaces |
| Const | Variable | Constants with "constant" modifier |
| Var | Variable | Global and local variables |
| Type | Class | Type definitions |

## 7. Go Language Relation Mapping

| Go Relationship | Relation Type | Description |
|-----------------|--------------|-------------|
| Struct embedding | INHERITS | When a struct embeds another struct |
| Interface implementation | INHERITS | When a struct implements an interface |
| Function call | CALLS | When a function/method calls another |
| Package import | IMPORTS | When a file imports a package |
| Variable reference | REFERENCES | When code references a variable |
| Type usage | REFERENCES | When a type is used in a declaration |
| Struct field access | REFERENCES | When code accesses a struct field |

## 8. Handling Non-ASCII Characters

> **Important Note**: The parser may fail when processing code containing non-ASCII characters. The Go analyzer must implement similar handling to the Python implementation for robustness.

```go
// PreprocessCode handles non-ASCII characters to ensure reliable parsing
func PreprocessCode(content string) string {
    processed := ""
    for _, c := range content {
        if c < 128 {
            // ASCII character - keep as is
            processed += string(c)
        } else {
            // Non-ASCII character - replace based on character type
            if unicode.IsLetter(c) {
                // For letters (identifiers, keywords), use 'x'
                processed += "x"
            } else if unicode.IsDigit(c) {
                // For digits, use '0'
                processed += "0"
            } else if unicode.IsSpace(c) {
                // Preserve whitespace as-is
                processed += string(c)
            } else {
                // For symbols and punctuation, use underscore
                processed += "_"
            }
        }
    }
    return processed
}
```

When extracting actual text content (such as for documentation or display), use the original source code rather than the processed version to preserve all characters.

## 9. Implementation Guidance

### 9.1 Entity Extraction

The Go analyzer should implement entity extraction by:

1. Parsing Go source code using Go's standard `go/ast`, `go/parser`, and `go/token` packages
2. Traversing the AST to identify entities:
   - Packages → Module entities
   - Functions → Method entities
   - Structs → Class entities
   - Interfaces → Interface entities
   - Constants and Variables → Variable entities
3. Extracting metadata such as:
   - Documentation from comments
   - Complexity metrics
   - Exported status
   - Parent-child relationships
4. Building proper entity keys for each extracted entity

### 9.2 Relationship Extraction

The relationship extractor should:

1. Analyze the AST to identify relationships between entities
2. Resolve entity references by:
   - Direct name matching
   - Qualification through imports
   - Type inference where possible
3. Generate relationship objects with:
   - Source and target entity references with proper keys
   - Relationship type
   - Source and target code locations
   - Additional metadata (e.g., call parameters)

### 9.3 Service Implementation

The Go analyzer service can be implemented as an HTTP service:

```go
package main

import (
    "encoding/json"
    "log"
    "net/http"
)

func main() {
    http.HandleFunc("/extract-entities", extractEntitiesHandler)
    http.HandleFunc("/extract-relations", extractRelationsHandler)
    
    log.Println("Starting Go analyzer service on :8080")
    http.ListenAndServe(":8080", nil)
}

func extractEntitiesHandler(w http.ResponseWriter, r *http.Request) {
    // Parse request
    var req EntityExtractionRequest
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        http.Error(w, err.Error(), http.StatusBadRequest)
        return
    }
    
    // Process file
    fileInfo, entities := extractEntities(req.FilePath, req.Content)
    
    // Return response
    response := EntityExtractionResponse{
        FileInfo: fileInfo,
        Entities: entities,
    }
    
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(response)
}

func extractRelationsHandler(w http.ResponseWriter, r *http.Request) {
    // Parse request
    var req RelationExtractionRequest
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        http.Error(w, err.Error(), http.StatusBadRequest)
        return
    }
    
    // Process file
    relations := extractRelations(req.FilePath, req.Content, req.RepoEntities)
    
    // Return response
    response := RelationExtractionResponse{
        Relations: relations,
    }
    
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(response)
}
```

## 10. Testing and Validation

To ensure proper integration, test your Go analyzer with:

1. Simple Go files to verify basic entity extraction
2. Files with complex relationships to verify relation extraction
3. Files with non-ASCII characters to test character handling
4. Large Go codebases to test performance and robustness

Validate that:
- Entity keys match the expected format
- Entities include all required fields
- Relationships link to valid entities
- All key Go language constructs are properly extracted

## Conclusion

This document provides the technical specifications for integrating a Go analyzer with the repo-graph-rag knowledge graph system. By implementing the described API endpoints and following the data structure guidelines, your Go analyzer will seamlessly integrate with the existing system to provide comprehensive analysis of Go code repositories.