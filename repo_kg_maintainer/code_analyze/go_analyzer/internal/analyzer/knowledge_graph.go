package analyzer

import (
	"encoding/json"
	"fmt"
	"os"
)

// Node represents a node in our knowledge graph
type Node struct {
	Type         string
	Name         string
	FilePath     string
	Line         uint32
	Column       uint32
	EndLine      uint32
	EndColumn    uint32
	Parameters   []string
	Returns      []string
	PackageName  string
	ParentStruct string
}

// Edge represents a relationship between two nodes
type Edge struct {
	From *Node
	To   *Node
	Type string // e.g., "calls", "imports", "implements"
}

// KnowledgeGraph represents our code structure
// This struct is different from StructuredKnowledgeGraph defined in knowledge_graph.go
// KnowledgeGraph is for debugging information. StructuredKnowledgeGraph is for final output knowledge_graph.json file
type KnowledgeGraph struct {
	// Nodes is a map of node ID to node
	Nodes map[string]*Node
	// Edges is a list of edges
	Edges []*Edge
}

func NewKnowledgeGraph() *KnowledgeGraph {
	return &KnowledgeGraph{
		Nodes: make(map[string]*Node),
		Edges: make([]*Edge, 0),
	}
}

/* --- --- --- */

type CodeLocation struct {
	FilePath string `json:"file_path"`
	Line     int    `json:"line"`
	Col      int    `json:"col"`
	LineEnd  int    `json:"lineEnd"` // New field to record the ending line number
}

type Variable struct {
	PackageName string       `json:"package_name"`
	VarName     string       `json:"var_name,omitempty"`
	VarType     string       `json:"var_type"`
	Location    CodeLocation `json:"location"`
}

type Function struct {
	PackageName  string       `json:"package_name"`
	FunctionName string       `json:"function_name"`
	InputParams  string       `json:"input_params"`  // code string
	ReturnParams string       `json:"return_params"` // code string
	Location     CodeLocation `json:"location"`
	IsGeneric    bool         `json:"is_generic"`
}

type FieldInfo struct {
	PackageName  string `json:"package_name"`
	FieldName    string `json:"field_name"`
	FieldType    string `json:"field_type"`
	ParentStruct string `json:"parent_struct"` // Parent struct id
}

type StructInfo struct {
	PackageName string       `json:"package_name"`
	StructName  string       `json:"struct_name"`
	Fields      []string     `json:"fields"` // Array of Field ids
	Location    CodeLocation `json:"location"`
	IsGeneric   bool         `json:"is_generic"`
}

type InterfaceInfo struct {
	PackageName   string       `json:"package_name"`
	InterfaceName string       `json:"interface_name"`
	Extends       []string     `json:"extends"` // Array of Interface names
	Methods       []string     `json:"methods"` // Array of Method ids
	Location      CodeLocation `json:"location"`
}

type InterfaceFunction struct {
	PackageName   string       `json:"package_name"`
	InterfaceName string       `json:"interface_name"`
	Method        string       `json:"method"`
	Location      CodeLocation `json:"location"`
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

type FileInfo struct {
	FilePath  string `json:"file_path"`
	PackageID string `json:"package_id"`
}

// Edge types to represent relationships
type EdgeType string

const (
	HasStruct    EdgeType = "has_struct"
	HasField     EdgeType = "has_field"
	HasValue     EdgeType = "has_value"
	HasMethod    EdgeType = "has_method"
	HasFunction  EdgeType = "has_function"
	HasImport    EdgeType = "has_import"
	Extends      EdgeType = "extends"
	References   EdgeType = "references"
	Calls        EdgeType = "calls"
	Instantiates EdgeType = "instantiates"
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
	Kg    *KnowledgeGraph
}

// Node types to represent different elements
type NodeType string

const (
	PackageNode           NodeType = "package"
	StructNode            NodeType = "struct"
	InterfaceNode         NodeType = "interface"
	FunctionNode          NodeType = "function"
	InterfaceFunctionNode NodeType = "interface_func"
	FieldNode             NodeType = "field"
	VariableNode          NodeType = "variable"
	EnumNode              NodeType = "enum"
	EnumValueNode         NodeType = "enum_value"
	ImportNode            NodeType = "import"
	FileNode              NodeType = "file"
)

type WeightedKnowledgeGraph struct {
	Nodes []WeightedNode `json:"nodes"`
	Edges []GraphEdge    `json:"edges"`
}

// WeightedNode will be used by pagerank and LLM
// WeightedNode extends GraphNode with additional weight information
type WeightedNode struct {
	*GraphNode
	Weights NodeWeights `json:"weights,omitempty"`
}

// Unmarshaling strategy for WeightedKnowledgeGraph with embedded GraphNode pointers
func UnmarshalWeightedKnowledgeGraph(data []byte) (*WeightedKnowledgeGraph, error) {
	// Create a temporary struct that flattens the embedded pointer fields
	type tempNode struct {
		// GraphNode fields
		ID   string      `json:"id"`
		Type NodeType    `json:"type"`
		Data interface{} `json:"data"`

		// WeightedNode fields
		Weights NodeWeights `json:"weights"`
	}

	// Temporary graph structure that uses the flattened node structure
	type tempGraph struct {
		Nodes []tempNode  `json:"nodes"`
		Edges []GraphEdge `json:"edges"`
	}

	// Unmarshal into the temporary structure
	var tmpG tempGraph
	if err := json.Unmarshal(data, &tmpG); err != nil {
		return nil, fmt.Errorf("failed to unmarshal JSON: %w", err)
	}

	// Create the actual WeightedKnowledgeGraph
	graph := &WeightedKnowledgeGraph{
		Nodes: make([]WeightedNode, len(tmpG.Nodes)),
		Edges: tmpG.Edges,
	}

	// Convert tempNodes to WeightedNodes
	for i, tn := range tmpG.Nodes {
		// Create a new GraphNode with the data from the temporary node
		graphNode := &GraphNode{
			ID:   tn.ID,
			Type: tn.Type,
			Data: tn.Data,
		}

		// Create the WeightedNode with the GraphNode pointer
		graph.Nodes[i] = WeightedNode{
			GraphNode: graphNode,
			Weights:   tn.Weights,
		}
	}

	return graph, nil
}

// NodeWeights stores various weight metrics for different node types
type NodeWeights struct {
	// Common weights
	CodeLineCount int `json:"code_line_count,omitempty"`

	// Package-specific weights
	// How many .go files in this package
	GoFilesCount int `json:"go_files_count,omitempty"`
	// How many structs in this package
	StructCount int `json:"struct_count,omitempty"`
	// How many interfaces in this package
	InterfaceCount int `json:"interface_count,omitempty"`
	// How many functions in this package
	FunctionCount int `json:"function_count,omitempty"`
	// How many imports in this package
	ImportCount int `json:"import_count,omitempty"`
	// How many subpackages in this package
	SubpackageCount int `json:"subpackage_count,omitempty"`
	// Main function and struct names in this package
	MainFuncAndStructNames []string `json:"main_func_and_struct_names,omitempty"`

	// Struct-specific weights
	// How many fields this struct has
	FieldCount int `json:"field_count,omitempty"`
	// How many methods this struct has
	MethodCount int `json:"method_count,omitempty"`
	// How many instances for this struct are instantiated
	TotalInstanceCount int `json:"total_instance_count,omitempty"`
	// How many times this struct is referenced
	ReferenceCount int `json:"reference_count,omitempty"`

	// Function-specific weights
	// How many times this function is called
	CalleeCount int `json:"callee_count,omitempty"`
	// How many functions this function is calling
	CallerCount int `json:"caller_count,omitempty"`
	// How many instances are instantiated by this function
	InstantiatedByFunction int `json:"instantiated_by_function,omitempty"`

	// Whether this function is self-recursive
	SelfRecursiveFunc bool `json:"self_recursive_func,omitempty"`

	// Importance of the node
	Importance int `json:"importance,omitempty"`

	// Tags for the node
	Tags []string `json:"tags,omitempty"`
}

func LoadKnowledgeGraph(path string) (*StructuredKnowledgeGraph, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("error reading knowledge graph file: %v", err)
	}

	var graph StructuredKnowledgeGraph
	if err := json.Unmarshal(data, &graph); err != nil {
		return nil, fmt.Errorf("error parsing knowledge graph JSON: %v", err)
	}

	return &graph, nil
}
