package analyzer

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"

	sitter "github.com/smacker/go-tree-sitter"
)

func PrintKnowledgeGraph(kg *KnowledgeGraph) {
	fmt.Println("\nKnowledge Graph:")

	// Create maps to group nodes by type
	packageNodes := make([]*Node, 0)
	typeNodes := make([]*Node, 0)
	functionNodes := make([]*Node, 0)
	fieldNodes := make([]*Node, 0)
	otherNodes := make([]*Node, 0)

	// Group nodes by type
	for _, node := range kg.Nodes {
		switch node.Type {
		case "package":
			packageNodes = append(packageNodes, node)
		case "type_spec":
			typeNodes = append(typeNodes, node)
		case "function":
			functionNodes = append(functionNodes, node)
		case "field":
			fieldNodes = append(fieldNodes, node)
		default:
			otherNodes = append(otherNodes, node)
		}
	}

	// Sort each group by name and file path
	sortNodes := func(nodes []*Node) {
		sort.Slice(nodes, func(i, j int) bool {
			if nodes[i].FilePath != nodes[j].FilePath {
				return nodes[i].FilePath < nodes[j].FilePath
			}
			return nodes[i].Name < nodes[j].Name
		})
	}

	sortNodes(packageNodes)
	sortNodes(typeNodes)
	sortNodes(functionNodes)
	sortNodes(fieldNodes)
	sortNodes(otherNodes)

	// Print nodes by category
	fmt.Println("\nPackages:")
	for _, node := range packageNodes {
		fmt.Printf("- package '%s' (line %d, col %d) in %s\n",
			node.Name, node.Line, node.Column, node.FilePath)
	}

	fmt.Println("\nTypes:")
	for _, node := range typeNodes {
		fmt.Printf("- type_spec '%s' (line %d-%d, col %d) in %s\n",
			node.Name, node.Line, node.EndLine, node.Column, node.FilePath)
	}

	fmt.Println("\nFunctions:")
	for _, node := range functionNodes {
		params := strings.Join(node.Parameters, ", ")
		returns := strings.Join(node.Returns, ", ")
		returnStr := ""
		if len(node.Returns) > 0 {
			returnStr = fmt.Sprintf(" returns (%s)", returns)
		}
		fmt.Printf("- function '%s' (line %d-%d, col %d) - takes (%s)%s in %s\n",
			node.Name, node.Line, node.EndLine, node.Column, params, returnStr, node.FilePath)
	}

	fmt.Println("\nFields:")
	for _, node := range fieldNodes {
		fmt.Printf("- field '%s' (line %d, col %d) in %s\n",
			node.Name, node.Line, node.Column, node.FilePath)
	}

	if len(otherNodes) > 0 {
		fmt.Println("\nOther Nodes:")
		for _, node := range otherNodes {
			fmt.Printf("- %s '%s' (line %d, col %d) in %s\n",
				node.Type, node.Name, node.Line, node.Column, node.FilePath)
		}
	}

	// Group and sort edges by type
	edgesByType := make(map[string][]*Edge)
	for _, edge := range kg.Edges {
		edgesByType[edge.Type] = append(edgesByType[edge.Type], edge)
	}

	// Get sorted edge types
	edgeTypes := make([]string, 0, len(edgesByType))
	for edgeType := range edgesByType {
		edgeTypes = append(edgeTypes, edgeType)
	}
	sort.Strings(edgeTypes)

	fmt.Println("\nRelationships:")
	for _, edgeType := range edgeTypes {
		edges := edgesByType[edgeType]
		// Sort edges by source and target names
		sort.Slice(edges, func(i, j int) bool {
			if edges[i].From.Name != edges[j].From.Name {
				return edges[i].From.Name < edges[j].From.Name
			}
			return edges[i].To.Name < edges[j].To.Name
		})

		fmt.Printf("\n%s:\n", edgeType)
		for _, edge := range edges {
			fmt.Printf("- %s '%s' -> %s '%s'\n",
				edge.From.Type, edge.From.Name,
				edge.To.Type, edge.To.Name)
		}
	}
}

func inferTypeFromValue(valueNode *sitter.Node, content []byte) string {
	if valueNode == nil {
		return ""
	}

	switch valueNode.Type() {
	case "call_expression":
		funcNode := valueNode.ChildByFieldName("function")
		if funcNode != nil {
			funcName := getNodeText(funcNode, content)
			if funcName == "make" {
				// Get the type argument for make
				argNode := valueNode.ChildByFieldName("arguments")
				if argNode != nil && argNode.NamedChildCount() > 0 {
					firstArg := argNode.NamedChild(0)
					if firstArg != nil {
						return getNodeText(firstArg, content)
					}
				}
			}
		}
	case "composite_literal":
		// Handle composite literals like []Type{} or map[string]Type{}
		typeNode := valueNode.ChildByFieldName("type")
		if typeNode != nil {
			return getNodeText(typeNode, content)
		}
	}

	return ""
}

// Update extractReferencedTypes to handle more cases
func extractReferencedTypes(typeStr string) []string {
	var types []string

	// Skip if empty
	if typeStr == "" {
		return types
	}

	// Handle map types
	if strings.HasPrefix(typeStr, "map[") {
		// Extract key and value types
		inner := strings.TrimPrefix(typeStr, "map[")
		parts := strings.SplitN(inner, "]", 2)
		if len(parts) == 2 {
			// Add key type if it's not built-in
			keyType := strings.TrimSpace(parts[0])
			if !isBuiltinType(keyType) {
				types = append(types, keyType)
			}
			// Add value type if it's not built-in
			valueType := strings.TrimSpace(parts[1])
			// Handle pointer types in map values
			valueType = strings.TrimPrefix(valueType, "*")
			if !isBuiltinType(valueType) {
				types = append(types, valueType)
			}
		}
		return types
	}

	// Handle slice types
	if strings.HasPrefix(typeStr, "[]") {
		elemType := strings.TrimPrefix(typeStr, "[]")
		// Handle pointer types in slices
		elemType = strings.TrimPrefix(elemType, "*")
		if !isBuiltinType(elemType) {
			types = append(types, elemType)
		}
		return types
	}

	// Handle simple pointer types
	if strings.HasPrefix(typeStr, "*") {
		elemType := strings.TrimPrefix(typeStr, "*")
		if !isBuiltinType(elemType) {
			types = append(types, elemType)
		}
		return types
	}

	// Handle package-qualified types (e.g., sync.Mutex)
	if strings.Contains(typeStr, ".") {
		parts := strings.Split(typeStr, ".")
		if len(parts) == 2 && !isBuiltinType(parts[1]) {
			types = append(types, parts[1])
		}
		return types
	}

	// Handle simple types
	if !isBuiltinType(typeStr) {
		types = append(types, typeStr)
	}

	return types
}

func SaveKnowledgeGraph(structuredKG *StructuredKnowledgeGraph) error {
	// Sort structuredKG's nodes by id
	sort.Slice(structuredKG.Nodes, func(i, j int) bool {
		return structuredKG.Nodes[i].ID < structuredKG.Nodes[j].ID
	})
	// Sort structuredKG's edges by source_id + target_id
	sort.Slice(structuredKG.Edges, func(i, j int) bool {
		if structuredKG.Edges[i].SourceID == structuredKG.Edges[j].SourceID {
			return structuredKG.Edges[i].TargetID < structuredKG.Edges[j].TargetID
		}
		return structuredKG.Edges[i].SourceID < structuredKG.Edges[j].SourceID
	})

	data, err := json.MarshalIndent(*structuredKG, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal knowledge graph: %v", err)
	}

	return os.WriteFile("knowledge_graph.json", data, 0644)
}
