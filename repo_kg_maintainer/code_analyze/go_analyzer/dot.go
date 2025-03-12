package main

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
)

// Main function to demonstrate the usage
func main() {
	// Read knowledge graph from file
	jsonData, err := os.ReadFile("knowledge_graph.json")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error reading knowledge graph file: %v\n", err)
		os.Exit(1)
	}

	// Parse the JSON data
	var kg StructuredKnowledgeGraph
	if err := json.Unmarshal(jsonData, &kg); err != nil {
		fmt.Fprintf(os.Stderr, "Error parsing knowledge graph JSON: %v\n", err)
		os.Exit(1)
	}

	// Generate DOT representation
	dotOutput := GenerateDOT(&kg)

	// Write to file
	if err := os.WriteFile("output.dot", []byte(dotOutput), 0644); err != nil {
		fmt.Fprintf(os.Stderr, "Error writing DOT file: %v\n", err)
		os.Exit(1)
	}

	fmt.Println("DOT file successfully generated: output.dot")
}

func GenerateDOT(kg *StructuredKnowledgeGraph) string {
	var sb strings.Builder

	// Start the digraph
	sb.WriteString("digraph \"Graph\" {\n")
	sb.WriteString("  node [shape=record];\n  edge [minlen=2];\n  graph [\n    splines=true,\n    nodesep=0.5,\n    overlap=false,\n    ranksep=1.0,\n    concentrate=true\n  ];\n")

	// Organize nodes by package
	packageNodes := make(map[string][]GraphNode)
	nodeMap := make(map[string]GraphNode)
	enumValues := make(map[string][]string)
	fileToFuncs := make(map[string][]string)
	fileToStructs := make(map[string][]string) // Map to track file -> struct relationships

	// First pass: organize nodes and build maps
	for _, node := range kg.Nodes {
		nodeMap[node.ID] = node
		pkgName := getPackageName(node)
		if pkgName != "" {
			packageNodes[pkgName] = append(packageNodes[pkgName], node)
		}

		// Track file -> function relationships
		if node.Type == FunctionNode {
			if data, ok := node.Data.(map[string]interface{}); ok {
				if loc, exists := data["location"].(map[string]interface{}); exists {
					if filePath, hasPath := loc["file_path"]; hasPath {
						fileToFuncs[fmt.Sprintf("%v", filePath)] = append(
							fileToFuncs[fmt.Sprintf("%v", filePath)],
							fmt.Sprintf("%v", data["function_name"]),
						)
					}
				}
			}
		}

		// Track file -> struct relationships
		if node.Type == StructNode {
			if data, ok := node.Data.(map[string]interface{}); ok {
				if loc, exists := data["location"].(map[string]interface{}); exists {
					if filePath, hasPath := loc["file_path"]; hasPath {
						fileToStructs[fmt.Sprintf("%v", filePath)] = append(
							fileToStructs[fmt.Sprintf("%v", filePath)],
							fmt.Sprintf("%v", data["struct_name"]),
						)
					}
				}
			}
		}
	}

	// Process edges to collect enum values
	for _, edge := range kg.Edges {
		if edge.RelationType == HasValue {
			sourceNode := nodeMap[edge.SourceID]
			if sourceNode.Type == StructNode {
				if data, ok := sourceNode.Data.(map[string]interface{}); ok {
					enumName := fmt.Sprintf("%v", data["struct_name"])
					targetNode := nodeMap[edge.TargetID]
					if targetData, ok := targetNode.Data.(map[string]interface{}); ok {
						if valueName, exists := targetData["value_name"]; exists {
							enumValues[enumName] = append(enumValues[enumName], fmt.Sprintf("%v", valueName))
						}
					}
				}
			}
		}
	}

	// Generate subgraphs for each package
	for pkgName, nodes := range packageNodes {
		sb.WriteString(fmt.Sprintf("  subgraph cluster_%s {\n", sanitizeID(pkgName)))
		sb.WriteString(fmt.Sprintf("    label = \"package: %s\";\n", pkgName))
		sb.WriteString("    color = lightblue;\n\n")

		// Generate files record with <fn> fields and get file number mapping
		fileNumMap := generateFilesRecordWithFields(&sb, pkgName, nodes, fileToFuncs)

		// Generate globals record
		generateGlobalsRecord(&sb, pkgName, nodes)

		// Process structs and enums
		processStructsAndEnums(&sb, nodes, kg, nodeMap, enumValues)

		// Process global functions with <fn> fields and get function number mapping
		funcNumMap := processGlobalFunctionsWithFields(&sb, pkgName, nodes)

		// Process relationships within package
		processPackageRelationships(&sb, kg, nodes, nodeMap)

		// Generate "has" relationships between files and functions
		generateContainsRelationships(&sb, pkgName, fileToFuncs, funcNumMap, fileNumMap)

		// Generate "has" relationships between files and structs
		generateHasRelationships(&sb, pkgName, fileToStructs, fileNumMap)

		sb.WriteString("  }\n\n")
	}

	sb.WriteString("}\n")
	return sb.String()
}

func generateFilesRecordWithFields(sb *strings.Builder, pkgName string, nodes []GraphNode, fileToFuncs map[string][]string) map[string]int {
	files := make(map[string]bool)
	fileNumMap := make(map[string]int) // Map to track file numbers

	for _, node := range nodes {
		if data, ok := node.Data.(map[string]interface{}); ok {
			if loc, exists := data["location"].(map[string]interface{}); exists {
				if filePath, hasPath := loc["file_path"]; hasPath {
					files[fmt.Sprintf("%v", filePath)] = true
				}
			}
		}
	}

	if len(files) > 0 {
		sb.WriteString(fmt.Sprintf("    %s_files [label=\"{Files", sanitizeID(pkgName)))
		fileNum := 0
		// Sort files for consistent numbering
		sortedFiles := make([]string, 0, len(files))
		for file := range files {
			sortedFiles = append(sortedFiles, file)
		}
		sort.Strings(sortedFiles)

		for _, file := range sortedFiles {
			fileNum++
			fileNumMap[file] = fileNum
			sb.WriteString(fmt.Sprintf("|<f%d> %s", fileNum, file))
		}
		sb.WriteString("}\"];\n\n")
	}
	return fileNumMap
}

func generateGlobalsRecord(sb *strings.Builder, pkgName string, nodes []GraphNode) {
	vars := filterNodesByType(nodes, VariableNode)
	if len(vars) > 0 {
		sb.WriteString(fmt.Sprintf("    %s_globals [label=\"{Global Variables|", sanitizeID(pkgName)))
		for _, v := range vars {
			if data, ok := v.Data.(map[string]interface{}); ok {
				varName := fmt.Sprintf("%v", data["var_name"])
				varType := fmt.Sprintf("%v", data["var_type"])
				sb.WriteString(fmt.Sprintf("%s: %s\\l", varName, varType))
			}
		}
		sb.WriteString("}\"];\n\n")
	}
}

func processStructsAndEnums(sb *strings.Builder, nodes []GraphNode, kg *StructuredKnowledgeGraph, nodeMap map[string]GraphNode, enumValues map[string][]string) {
	structs := filterNodesByType(nodes, StructNode)
	for _, s := range structs {
		if data, ok := s.Data.(map[string]interface{}); ok {
			structName := fmt.Sprintf("%v", data["struct_name"])
			pkgName := fmt.Sprintf("%v", data["package_name"])

			// Check if this is an enum
			if values, isEnum := enumValues[structName]; isEnum {
				// Use package_StructName for the node name but keep original name in label
				sb.WriteString(fmt.Sprintf("    %s_%s [label=\"{enum %s|",
					sanitizeID(pkgName),
					sanitizeID(structName),
					structName))
				for _, value := range values {
					sb.WriteString(value + "\\l")
				}
				sb.WriteString("}\"];\n")
				continue
			}

			// Regular struct processing
			// Use package_StructName for the node name but keep original name in label
			sb.WriteString(fmt.Sprintf("    %s_%s [label=\"{struct %s|",
				sanitizeID(pkgName),
				sanitizeID(structName),
				structName))

			// Process fields
			if fields, ok := data["fields"].([]interface{}); ok {
				for _, fieldID := range fields {
					if fieldNode, exists := nodeMap[fmt.Sprintf("%v", fieldID)]; exists {
						if fieldData, ok := fieldNode.Data.(map[string]interface{}); ok {
							fieldName := fmt.Sprintf("%v", fieldData["field_name"])
							fieldType := fmt.Sprintf("%v", fieldData["field_type"])
							sb.WriteString(fmt.Sprintf("%s %s\\l", fieldName, fieldType))
						}
					}
				}
			}

			// Process methods
			sb.WriteString("|")
			for _, node := range kg.Nodes {
				if node.Type == FunctionNode {
					if funcData, ok := node.Data.(map[string]interface{}); ok {
						if parentStruct, hasParent := funcData["parent_struct"]; hasParent {
							if fmt.Sprintf("%v", parentStruct) == s.ID {
								funcName := fmt.Sprintf("%v", funcData["function_name"])
								if parts := strings.Split(funcName, "."); len(parts) > 1 {
									funcName = parts[1]
								}
								inputParams := fmt.Sprintf("%v", funcData["input_params"])
								returnParams := fmt.Sprintf("%v", funcData["return_params"])

								methodStr := funcName + inputParams
								if returnParams != "" {
									methodStr += " " + returnParams
								}
								sb.WriteString(methodStr + "\\l")
							}
						}
					}
				}
			}
			sb.WriteString("}\"];\n")
		}
	}
	sb.WriteString("\n")
}

func processGlobalFunctionsWithFields(sb *strings.Builder, pkgName string, nodes []GraphNode) map[string]int {
	funcs := filterNodesByType(nodes, FunctionNode)
	globalFuncs := make([]GraphNode, 0)
	funcNumMap := make(map[string]int)

	// Filter out member functions
	for _, f := range funcs {
		if data, ok := f.Data.(map[string]interface{}); ok {
			if _, hasParent := data["parent_struct"]; !hasParent {
				globalFuncs = append(globalFuncs, f)
			}
		}
	}

	if len(globalFuncs) > 0 {
		sb.WriteString(fmt.Sprintf("    %s_functions [label=\"{Functions", sanitizeID(pkgName)))
		for i, f := range globalFuncs {
			if data, ok := f.Data.(map[string]interface{}); ok {
				funcName := fmt.Sprintf("%v", data["function_name"])
				inputParams := fmt.Sprintf("%v", data["input_params"])
				returnParams := fmt.Sprintf("%v", data["return_params"])

				label := funcName + inputParams
				if returnParams != "" {
					label += " " + returnParams
				}
				sb.WriteString(fmt.Sprintf("|<fn%d> %s", i+1, label))
				funcNumMap[funcName] = i + 1
			}
		}
		sb.WriteString("}\"];\n\n")
	}
	return funcNumMap
}

func processPackageRelationships(sb *strings.Builder, kg *StructuredKnowledgeGraph, nodes []GraphNode, nodeMap map[string]GraphNode) {
	nodeIDs := make(map[string]bool)
	for _, node := range nodes {
		nodeIDs[node.ID] = true
	}

	for _, edge := range kg.Edges {
		if edge.RelationType == References || edge.RelationType == Extends {
			if nodeIDs[edge.SourceID] && nodeIDs[edge.TargetID] {
				sourceNode := nodeMap[edge.SourceID]
				targetNode := nodeMap[edge.TargetID]

				sourceLabel := getNodeLabel(sourceNode)
				targetLabel := getNodeLabel(targetNode)

				// Get package names for both source and target
				sourcePkg := getPackageName(sourceNode)
				targetPkg := getPackageName(targetNode)

				sb.WriteString(fmt.Sprintf("    %s_%s -> %s_%s [label=\"%s\"];\n",
					sanitizeID(sourcePkg),
					sanitizeID(sourceLabel),
					sanitizeID(targetPkg),
					sanitizeID(targetLabel),
					edge.RelationType))
			}
		}
	}
}

func generateContainsRelationships(sb *strings.Builder, pkgName string, fileToFuncs map[string][]string, funcNumMap map[string]int, fileNumMap map[string]int) {
	// Generate relationships
	for file, funcs := range fileToFuncs {
		if fileNum, exists := fileNumMap[file]; exists {
			for _, fn := range funcs {
				if funcNum, exists := funcNumMap[fn]; exists {
					sb.WriteString(fmt.Sprintf("    %s_files:f%d -> %s_functions:fn%d [label=\"contains\"];\n",
						sanitizeID(pkgName),
						fileNum,
						sanitizeID(pkgName),
						funcNum))
				}
			}
		}
	}
	sb.WriteString("\n")
}

func generateHasRelationships(sb *strings.Builder, pkgName string, fileToStructs map[string][]string, fileNumMap map[string]int) {
	// Generate relationships
	for file, structs := range fileToStructs {
		if fileNum, exists := fileNumMap[file]; exists {
			for _, structName := range structs {
				// Use package_StructName for the node reference
				sb.WriteString(fmt.Sprintf("    %s_files:f%d -> %s_%s [label=\"has\"];\n",
					sanitizeID(pkgName),
					fileNum,
					sanitizeID(pkgName),
					sanitizeID(structName)))
			}
		}
	}
	sb.WriteString("\n")
}

func getPackageName(node GraphNode) string {
	if data, ok := node.Data.(map[string]interface{}); ok {
		if pkgName, exists := data["package_name"]; exists {
			return fmt.Sprintf("%v", pkgName)
		}
	}
	return ""
}

func getNodeLabel(node GraphNode) string {
	if data, ok := node.Data.(map[string]interface{}); ok {
		switch node.Type {
		case StructNode:
			return fmt.Sprintf("%v", data["struct_name"])
		case FunctionNode:
			return fmt.Sprintf("%v", data["function_name"])
		case VariableNode:
			return fmt.Sprintf("%v", data["var_name"])
		}
	}
	return node.ID
}

func filterNodesByType(nodes []GraphNode, nodeType NodeType) []GraphNode {
	filtered := make([]GraphNode, 0)
	for _, node := range nodes {
		if node.Type == nodeType {
			filtered = append(filtered, node)
		}
	}
	return filtered
}

func sanitizeID(id string) string {
	replacer := strings.NewReplacer(
		".", "_",
		"*", "ptr_",
		"[", "arr_",
		"]", "",
		" ", "_",
		"-", "_",
		"/", "_",
		":", "_",
	)
	return replacer.Replace(id)
}
