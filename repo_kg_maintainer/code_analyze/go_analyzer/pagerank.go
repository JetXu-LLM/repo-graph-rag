package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
)

// WeightedNode extends GraphNode with additional weight information
type WeightedNode struct {
	*GraphNode
	Weights NodeWeights `json:"weights"`
}

// NodeWeights stores various weight metrics for different node types
type NodeWeights struct {
	// Package-specific weights
	StructCount   int `json:"struct_count,omitempty"`
	FunctionCount int `json:"function_count,omitempty"`

	// Common weights
	CodeLineCount  int `json:"code_line_count,omitempty"`
	ReferenceCount int `json:"reference_count,omitempty"`

	// Struct-specific weights
	FieldCount  int `json:"field_count,omitempty"`
	MethodCount int `json:"method_count,omitempty"`

	// Function-specific weights
	CallCount int `json:"call_count,omitempty"`
}

// CalculateWeights processes the knowledge graph and adds weight information
func CalculateWeights(graph *StructuredKnowledgeGraph) map[string]WeightedNode {
	weightedNodes := make(map[string]WeightedNode)

	// Initialize weighted nodes
	for _, node := range graph.Nodes {
		if shouldProcessNodeType(node.Type) {
			weightedNodes[node.ID] = WeightedNode{
				GraphNode: &node,
				Weights:   NodeWeights{},
			}
		}
	}

	// Calculate weights for each node
	for id, wNode := range weightedNodes {
		fmt.Printf("Processing node: %s\n", id)
		switch wNode.Type {
		case PackageNode:
			calculatePackageWeights(id, wNode, graph, weightedNodes)
		case StructNode:
			calculateStructWeights(id, wNode, graph, weightedNodes)
		case FunctionNode:
			calculateFunctionWeights(id, wNode, graph, weightedNodes)
		}
	}

	return weightedNodes
}

func shouldProcessNodeType(nodeType NodeType) bool {
	return nodeType == PackageNode || nodeType == StructNode || nodeType == FunctionNode
}

func calculatePackageWeights(id string, wNode WeightedNode, graph *StructuredKnowledgeGraph, weightedNodes map[string]WeightedNode) {
	pkgData, ok := wNode.Data.(map[string]interface{})
	if !ok {
		return
	}
	pkgName, ok := pkgData["package_name"].(string)
	if !ok || pkgName == "main" {
		return // Skip main packages
	}

	// Count structs and functions in the package
	for _, node := range graph.Nodes {
		if node.Type == StructNode {
			structData, ok := node.Data.(map[string]interface{})
			if !ok {
				continue
			}
			structPkg, ok := structData["package_name"].(string)
			if ok && structPkg == pkgName {
				wNode.Weights.StructCount++
			}
		} else if node.Type == FunctionNode {
			funcData, ok := node.Data.(map[string]interface{})
			if !ok {
				continue
			}
			funcPkg, ok := funcData["package_name"].(string)
			if ok && funcPkg == pkgName {
				wNode.Weights.FunctionCount++
			}
		}
	}

	weightedNodes[id] = wNode
}

func calculateStructWeights(id string, wNode WeightedNode, graph *StructuredKnowledgeGraph, weightedNodes map[string]WeightedNode) {
	structData, ok := wNode.Data.(map[string]interface{})
	if !ok {
		return
	}

	// Calculate code line count
	if location, ok := structData["location"].(map[string]interface{}); ok {
		lineStart, startOk := location["line"].(float64)
		lineEnd, endOk := location["lineEnd"].(float64)
		if startOk && endOk {
			wNode.Weights.CodeLineCount = int(lineEnd - lineStart + 1)
		}
	}

	// Count fields
	if fields, ok := structData["fields"].([]interface{}); ok {
		wNode.Weights.FieldCount = len(fields)
	}

	// Count methods and references
	for _, edge := range graph.Edges {
		if edge.SourceID == id {
			if edge.RelationType == HasMethod {
				wNode.Weights.MethodCount++
			}
		}
		if edge.TargetID == id && edge.RelationType == References {
			wNode.Weights.ReferenceCount++
		}
	}

	weightedNodes[id] = wNode
}

func calculateFunctionWeights(id string, wNode WeightedNode, graph *StructuredKnowledgeGraph, weightedNodes map[string]WeightedNode) {
	funcData, ok := wNode.Data.(map[string]interface{})
	if !ok {
		return
	}

	// Calculate code line count
	if location, ok := funcData["location"].(map[string]interface{}); ok {
		lineStart, startOk := location["line"].(float64)
		lineEnd, endOk := location["lineEnd"].(float64)
		if startOk && endOk {
			wNode.Weights.CodeLineCount = int(lineEnd - lineStart + 1)
		}
	}

	// Count calls to this function
	for _, edge := range graph.Edges {
		if edge.TargetID == id && edge.RelationType == Calls {
			if edge.SourceID != id { // Avoid counting self-recursive calls
				wNode.Weights.CallCount++
			}
		}
	}

	weightedNodes[id] = wNode
}

func main() {
	// Read the knowledge graph from JSON file
	data, err := os.ReadFile("knowledge_graph.json")
	if err != nil {
		log.Fatalf("Error reading knowledge graph file: %v", err)
	}

	// Parse the JSON into our knowledge graph structure
	var graph StructuredKnowledgeGraph
	if err := json.Unmarshal(data, &graph); err != nil {
		log.Fatalf("Error parsing knowledge graph JSON: %v", err)
	}

	// Calculate weights
	weightedNodes := CalculateWeights(&graph)

	// Create enriched graph while preserving original structure
	enrichedGraph := StructuredKnowledgeGraph{
		Nodes: make([]GraphNode, len(graph.Nodes)),
		Edges: graph.Edges,
	}

	// Preserve all nodes, enrich only the relevant ones
	for i, node := range graph.Nodes {
		enrichedGraph.Nodes[i] = node // Copy the original node
		if wNode, exists := weightedNodes[node.ID]; exists {
			// Only enrich nodes that we calculated weights for
			enrichedGraph.Nodes[i].Data = map[string]interface{}{
				"original": node.Data,
				"weights":  wNode.Weights,
			}
		}
	}

	// Write the enriched graph to JSON file
	enrichedData, err := json.MarshalIndent(enrichedGraph, "", "  ")
	if err != nil {
		log.Fatalf("Error marshaling enriched graph: %v", err)
	}

	if err := os.WriteFile("enriched_kg.json", enrichedData, 0644); err != nil {
		log.Fatalf("Error writing enriched graph file: %v", err)
	}
}
