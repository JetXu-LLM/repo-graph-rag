package main

type CodeLocation struct {
	FilePath string `json:"file_path"`
	Line     int    `json:"line"`
	Col      int    `json:"col"`
	LineEnd  int    `json:"lineEnd"` // New field to record the ending line number
}

type Variable struct {
	VarName  string       `json:"var_name,omitempty"`
	VarType  string       `json:"var_type"`
	Location CodeLocation `json:"location"`
}

type Function struct {
	PackageName  string       `json:"package_name"`
	FunctionName string       `json:"function_name"`
	InputParams  string       `json:"input_params"`  // code string
	ReturnParams string       `json:"return_params"` // code string
	Location     CodeLocation `json:"location"`
}

type FieldInfo struct {
	FieldName    string `json:"field_name"`
	FieldType    string `json:"field_type"`
	ParentStruct string `json:"parent_struct"` // Parent struct id
}

type StructInfo struct {
	PackageName string       `json:"package_name"`
	StructName  string       `json:"struct_name"`
	Fields      []string     `json:"fields"` // Array of Field ids
	Location    CodeLocation `json:"location"`
}

type MemberFunction struct {
	Function
	ParentStruct string `json:"parent_struct"` // Parent struct id
}

type EnumValue struct {
	ValueName string       `json:"value_name"`
	Location  CodeLocation `json:"location"`
}

type EnumInfo struct {
	PackageName string       `json:"package_name"`
	EnumName    string       `json:"enum_name"`
	Values      []EnumValue  `json:"values"`
	Location    CodeLocation `json:"location"`
}

type ImportInfo struct {
	PackageName string       `json:"package_name"`
	ImportPath  string       `json:"import_path"`
	Location    CodeLocation `json:"location"`
}

type PackageInfo struct {
	PackageName string       `json:"package_name"`
	Location    CodeLocation `json:"location"`
}

// Edge types to represent relationships
type EdgeType string

const (
	HasStruct   EdgeType = "has_struct"
	HasField    EdgeType = "has_field"
	HasValue    EdgeType = "has_value"
	HasMethod   EdgeType = "has_method"
	HasFunction EdgeType = "has_function"
	Extends     EdgeType = "extends"
	References  EdgeType = "references"
	Calls       EdgeType = "calls"
)

// Rename Node to GraphNode
type GraphNode struct {
	ID   string      `json:"id"`
	Type NodeType    `json:"type"`
	Data interface{} `json:"data"` // Can be any of the above types (PackageInfo, StructInfo, etc.)
}

// Rename Edge to GraphEdge
type GraphEdge struct {
	SourceType   string   `json:"source_type"` // Type of the source node (e.g., "package", "struct", "field")
	SourceID     string   `json:"source_id"`   // Identifier for the source node
	TargetType   string   `json:"target_type"` // Type of the target node
	TargetID     string   `json:"target_id"`   // Identifier for the target node
	RelationType EdgeType `json:"relation_type"`
}

// Rename KnowledgeGraph to StructuredKnowledgeGraph
type StructuredKnowledgeGraph struct {
	Nodes []GraphNode `json:"nodes"`
	Edges []GraphEdge `json:"edges"`
}

// Node types to represent different elements
type NodeType string

const (
	PackageNode   NodeType = "package"
	StructNode    NodeType = "struct"
	FunctionNode  NodeType = "function"
	FieldNode     NodeType = "field"
	VariableNode  NodeType = "variable"
	EnumNode      NodeType = "enum"
	EnumValueNode NodeType = "enum_value"
	ImportNode    NodeType = "import"
)
