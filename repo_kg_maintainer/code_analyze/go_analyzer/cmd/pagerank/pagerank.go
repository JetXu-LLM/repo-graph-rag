package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"strings"

	"github.com/tengteng/go-code-analyzer/internal/analyzer"
)

// CalculateWeights processes the knowledge graph and adds weight information
func CalculateWeights(
	graph *analyzer.StructuredKnowledgeGraph) map[string]analyzer.WeightedNode {
	weightedNodes := make(map[string]analyzer.WeightedNode)

	// Initialize weighted nodes
	for _, node := range graph.Nodes {
		if shouldProcessNodeType(node.Type) {
			weightedNodes[node.ID] = analyzer.WeightedNode{
				GraphNode: &node,
				Weights: analyzer.NodeWeights{
					Labels: make(map[analyzer.NodeLabel]bool),
				},
			}
		}
	}

	// Calculate weights for each node
	for id, wNode := range weightedNodes {
		fmt.Printf("Processing node: %s\n", id)
		switch wNode.Type {
		case analyzer.PackageNode:
			calculatePackageWeights(id, wNode, graph, weightedNodes)
		case analyzer.StructNode:
			calculateStructWeights(id, wNode, graph, weightedNodes)
		case analyzer.FunctionNode:
			calculateFunctionWeights(id, wNode, graph, weightedNodes)
		case analyzer.InterfaceNode:
			calculateInterfaceWeights(id, wNode, graph, weightedNodes)
		}
	}

	return weightedNodes
}

func shouldProcessNodeType(nodeType analyzer.NodeType) bool {
	return nodeType == analyzer.PackageNode || nodeType == analyzer.StructNode ||
		nodeType == analyzer.FunctionNode || nodeType == analyzer.InterfaceNode
}

func calculatePackageWeights(
	id string,
	wNode analyzer.WeightedNode,
	graph *analyzer.StructuredKnowledgeGraph,
	weightedNodes map[string]analyzer.WeightedNode,
) {
	pkgData, ok := wNode.Data.(map[string]interface{})
	if !ok {
		return
	}
	pkgName, ok := pkgData["package_name"].(string)
	if !ok || pkgName == "main" {
		return // Skip main packages
	}
	pkgDirPath := pkgData["location"].(map[string]interface{})["file_path"].(string)

	// Count structs and functions in the package
	for _, node := range graph.Nodes {
		if node.Type == analyzer.StructNode {
			structData, ok := node.Data.(map[string]interface{})
			if !ok {
				continue
			}
			structPkg, ok := structData["package_name"].(string)
			if ok && structPkg == pkgName {
				wNode.Weights.StructCount++
			}
		} else if node.Type == analyzer.FunctionNode {
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

	// Count .go files in the package by traversing the file system
	goFilesCount := 0
	dir := pkgData["location"].(map[string]interface{})["file_path"].(string)
	files, err := os.ReadDir(dir)
	if err != nil {
		log.Fatalf("Error reading directory: %v", err)
	}
	for _, file := range files {
		if strings.HasSuffix(file.Name(), ".go") {
			goFilesCount++
		}
	}
	wNode.Weights.GoFilesCount = goFilesCount

	// Count imports in the package
	for _, edge := range graph.Edges {
		if edge.RelationType == analyzer.HasImport && edge.SourceID == id {
			wNode.Weights.ImportCount++
		}
	}

	// Count subpackages in the package
	for _, node := range graph.Nodes {
		if node.Type == analyzer.PackageNode {
			d, ok := node.Data.(map[string]interface{})
			if !ok {
				continue
			}
			subPkgDirPath := d["location"].(map[string]interface{})["file_path"].(string)
			if strings.HasPrefix(subPkgDirPath, pkgDirPath) && subPkgDirPath != pkgDirPath {
				wNode.Weights.SubpackageCount++
			}
		}
	}
	weightedNodes[id] = wNode
}

func calculateStructWeights(
	id string,
	wNode analyzer.WeightedNode,
	graph *analyzer.StructuredKnowledgeGraph,
	weightedNodes map[string]analyzer.WeightedNode,
) {
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

	// Count methods, references and instantiates
	for _, edge := range graph.Edges {
		if edge.SourceID == id {
			if edge.RelationType == analyzer.HasMethod {
				wNode.Weights.MethodCount++
			}
		}
		if edge.TargetID == id && edge.RelationType == analyzer.References {
			wNode.Weights.ReferenceCount++
		}
		if edge.TargetID == id && edge.RelationType == analyzer.Instantiates {
			wNode.Weights.TotalInstanceCount++
		}
	}

	weightedNodes[id] = wNode
}

func calculateFunctionWeights(
	id string,
	wNode analyzer.WeightedNode,
	graph *analyzer.StructuredKnowledgeGraph,
	weightedNodes map[string]analyzer.WeightedNode,
) {
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
		if edge.TargetID == id && edge.RelationType == analyzer.Calls {
			if edge.SourceID != id { // Avoid counting self-recursive calls
				wNode.Weights.CalleeCount++
			} else {
				wNode.Weights.Labels[analyzer.SelfRecursiveFunc] = true
			}
		}
		if edge.SourceID == id && edge.RelationType == analyzer.Calls {
			if edge.TargetID != id { // Avoid counting self-recursive calls
				wNode.Weights.CallerCount++
			} else {
				wNode.Weights.Labels[analyzer.SelfRecursiveFunc] = true
			}
		}
		if edge.SourceID == id && edge.RelationType == analyzer.Instantiates {
			wNode.Weights.InstantiatedByFunction++
		}
	}

	weightedNodes[id] = wNode
}

func calculateInterfaceWeights(
	id string,
	wNode analyzer.WeightedNode,
	graph *analyzer.StructuredKnowledgeGraph,
	weightedNodes map[string]analyzer.WeightedNode,
) {
	interfaceData, ok := wNode.Data.(map[string]interface{})
	if !ok {
		return
	}

	// Count methods in the interface
	if methods, ok := interfaceData["methods"].([]interface{}); ok {
		wNode.Weights.MethodCount = len(methods)
	}

	// Count references to this interface
	for _, edge := range graph.Edges {
		if edge.TargetID == id && edge.RelationType == analyzer.References {
			wNode.Weights.ReferenceCount++
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
	var graph analyzer.StructuredKnowledgeGraph
	if err := json.Unmarshal(data, &graph); err != nil {
		log.Fatalf("Error parsing knowledge graph JSON: %v", err)
	}

	// Calculate weights
	weightedNodes := CalculateWeights(&graph)

	// Create enriched graph while preserving original structure
	enrichedGraph := analyzer.StructuredKnowledgeGraph{
		Nodes: make([]analyzer.GraphNode, len(graph.Nodes)),
		Edges: graph.Edges,
		Kg:    graph.Kg,
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
