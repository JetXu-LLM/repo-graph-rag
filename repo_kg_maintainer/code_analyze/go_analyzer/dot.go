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
	// Parse debug flag
	debug := false
	for _, arg := range os.Args[1:] {
		if arg == "--debug" {
			debug = true
			break
		}
	}

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
	dotOutput := GenerateDOT(&kg, debug)

	// Write to file
	if err := os.WriteFile("output.dot", []byte(dotOutput), 0644); err != nil {
		fmt.Fprintf(os.Stderr, "Error writing DOT file: %v\n", err)
		os.Exit(1)
	}

	fmt.Println("DOT file successfully generated: output.dot")
}

func GenerateDOT(kg *StructuredKnowledgeGraph, debug bool) string {
	var sb strings.Builder

	// Start the digraph
	sb.WriteString("digraph \"Graph\" {\n")
	sb.WriteString("  node [shape=record];\n  edge [minlen=2];\n  graph [\n    splines=true,\n    nodesep=0.5,\n    overlap=false,\n    ranksep=1.0,\n    concentrate=true\n  ];\n")

	// Organize nodes by package
	// packageNodes is a map[string][]GraphNode tracking package_name -> []GraphNode
	packageNodes := make(map[string][]GraphNode)

	// nodeMap is a map[string]GraphNode tracking node_id -> GraphNode
	nodeMap := make(map[string]GraphNode)

	// enumValues is a map[string][]string tracking struct_name -> []value_name
	enumValues := make(map[string][]string)

	// Map to trace file_path -> []function_name
	// function_name here can be "function_name" or "struct_name.function_name"
	fileToFuncs := make(map[string][]string)

	// Map to track file_path -> struct_name
	fileToStructs := make(map[string][]string)

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
	// JSON dump of nodeMap
	if debug {
		jsonData, err := json.MarshalIndent(nodeMap, "", "  ")
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error marshaling nodeMap: %v\n", err)
			os.Exit(1)
		}
		os.WriteFile("nodeMap.debug.json", jsonData, 0644)

		// JSON dump of packageNodes
		jsonData, err = json.MarshalIndent(packageNodes, "", "  ")
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error marshaling packageNodes: %v\n", err)
			os.Exit(1)
		}
		os.WriteFile("packageNodes.debug.json", jsonData, 0644)
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

	// packageFunctionMap is a map[string]map[string]string
	// tracking package_name -> function_name -> fmt.Sprintf("%d:%d", numParts, function_number)
	packageFunctionMap := make(map[string]map[string]string)
	// packageStructMethodMap is a map[string]map[string]map[string]int
	// tracking package_name -> struct_name -> method_name -> method_number
	packageStructMethodMap := make(map[string]map[string]map[string]int)
	// Generate subgraphs for each package
	for pkgName, nodes := range packageNodes {
		sb.WriteString(fmt.Sprintf("  subgraph cluster_%s {\n", sanitizeID(pkgName)))
		sb.WriteString(fmt.Sprintf("    label = \"package: %s\";\n", pkgName))
		sb.WriteString("    color = lightblue;\n\n")

		// Generate files record with <f> fields and get file number mapping
		// fileNumMap is a map tracking file_path -> int. File paths are sorted alphabetically
		fileNumMap, filePartMap := generateFilesRecordWithFields(&sb, pkgName, nodes)

		// Generate globals record
		generateGlobalsRecord(&sb, pkgName, nodes)

		// Process structs and enums
		// methodNumMap is a map[string]map[string]int tracking struct_name -> method_name -> method_number
		methodNumMap := processStructsAndEnums(&sb, nodes, kg, nodeMap, enumValues)
		packageStructMethodMap[pkgName] = methodNumMap

		// Process global functions with <fn> fields and get function number mapping
		// funcNumMap is a map[string]int tracking global function_name -> int
		// numParts is an int tracking the number of parts in the global functions record
		// partMap is a map[int]int tracking function_number -> part_number
		funcNumMap, partMap := processGlobalFunctionsWithFields(&sb, pkgName, nodes)
		packageFunctionMap[pkgName] = make(map[string]string)
		for funcName, funcNum := range funcNumMap {
			packageFunctionMap[pkgName][funcName] = fmt.Sprintf("%d:%d", partMap[funcNum], funcNum)
		}

		// Process relationships within package
		processPackageRelationships(&sb, kg, nodes, nodeMap)

		// Generate "has" relationships between files and functions
		generateContainsRelationships(&sb, pkgName, fileToFuncs, funcNumMap, fileNumMap, partMap, filePartMap)

		// Generate "has" relationships between files and structs
		generateHasRelationships(&sb, pkgName, fileToStructs, fileNumMap, filePartMap)

		sb.WriteString("  }\n\n")
	}

	// JSON dump of packageStructMethodMap and packageFunctionMap
	if debug {
		jsonData, err := json.MarshalIndent(packageStructMethodMap, "", "  ")
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error marshaling packageStructMethodMap: %v\n", err)
			os.Exit(1)
		}
		os.WriteFile("packageStructMethodMap.debug.json", jsonData, 0644)
		jsonData, err = json.MarshalIndent(packageFunctionMap, "", "  ")
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error marshaling packageFunctionMap: %v\n", err)
			os.Exit(1)
		}
		os.WriteFile("packageFunctionMap.debug.json", jsonData, 0644)
	}

	// Generate "calls" relationships between functions and functions
	for _, edge := range kg.Edges {
		if edge.RelationType == Calls {
			callerPackage := getPackageName(nodeMap[edge.SourceID])
			callerFuncName := getNodeLabel(nodeMap[edge.SourceID]) // "function_name" or "struct_name.function_name"
			calleePackage := getPackageName(nodeMap[edge.TargetID])
			calleeFuncName := getNodeLabel(nodeMap[edge.TargetID]) // "function_name" or "struct_name.function_name"
			callerFuncNameParts := strings.Split(callerFuncName, ".")
			calleeFuncNameParts := strings.Split(calleeFuncName, ".")

			// If caller is a method, callerStr is
			// fmt.Sprintf("%s_%s:m%d", sanitizeID(callerPackage), structName, methodNum)
			// If callerStr is a global function, callerStr is
			// fmt.Sprintf("%s_functions_part%d:fn%d", sanitizeID(callerPackage), numParts, funcNum)
			var callerStr string

			// If callee is a method, it is
			// fmt.Sprintf("%s_%s:m%d", sanitizeID(calleePackage), structName, methodNum)
			// If callee is a global function, calleeStr is
			// fmt.Sprintf("%s_functions_part%d:fn%d", sanitizeID(calleePackage), numParts, funcNum)
			var calleeStr string

			if len(callerFuncNameParts) > 1 {
				// This is a method caller
				structName := callerFuncNameParts[0]
				functionName := callerFuncNameParts[1]
				methodNum := packageStructMethodMap[callerPackage][structName][functionName]
				if methodNum == 0 {
					fmt.Printf("Methodnum is 0: %s %s %s\n", sanitizeID(callerPackage), structName, functionName)
				}
				callerStr = fmt.Sprintf("%s_%s:m%d", sanitizeID(callerPackage), structName, methodNum)
			} else {
				// This is a global function caller
				parts := strings.Split(packageFunctionMap[callerPackage][callerFuncName], ":")
				numParts := parts[0]
				funcNum := parts[1]
				callerStr = fmt.Sprintf("%s_functions_part%s:fn%s", sanitizeID(callerPackage), numParts, funcNum)
			}
			if len(calleeFuncNameParts) > 1 {
				// This is a method callee
				structName := calleeFuncNameParts[0]
				functionName := calleeFuncNameParts[1]
				methodNum := packageStructMethodMap[calleePackage][structName][functionName]
				calleeStr = fmt.Sprintf("%s_%s:m%d", sanitizeID(calleePackage), structName, methodNum)
			} else {
				// This is a global function callee
				parts := strings.Split(packageFunctionMap[calleePackage][calleeFuncName], ":")
				numParts := parts[0]
				funcNum := parts[1]
				calleeStr = fmt.Sprintf("%s_functions_part%s:fn%s", sanitizeID(calleePackage), numParts, funcNum)
			}
			sb.WriteString(
				fmt.Sprintf("    %s -> %s [label=\"calls\"];\n",
					callerStr,
					calleeStr))
		}
	}

	sb.WriteString("}\n")
	return sb.String()
}

func generateFilesRecordWithFields(sb *strings.Builder, pkgName string, nodes []GraphNode) (map[string]int, map[int]int) {
	files := make(map[string]bool)
	fileNumMap := make(map[string]int) // Map to track file_path -> file_number
	filePartMap := make(map[int]int)   // Map to track file_number -> part_number

	for _, node := range nodes {
		if data, ok := node.Data.(map[string]interface{}); ok {
			if loc, exists := data["location"].(map[string]interface{}); exists {
				if filePath, hasPath := loc["file_path"]; hasPath {
					files[fmt.Sprintf("%v", filePath)] = true
				}
			}
		}
	}

	if len(files) == 0 {
		return fileNumMap, filePartMap
	}

	const maxLabelLength = 16000 // Keep some buffer below 16384
	var currentLength int
	var currentPart int
	var fileNum int

	// Sort files for consistent numbering
	sortedFiles := make([]string, 0, len(files))
	for file := range files {
		sortedFiles = append(sortedFiles, file)
	}
	sort.Strings(sortedFiles)

	// Start first part
	currentPart++
	sb.WriteString(fmt.Sprintf("    %s_files_part%d [label=\"{Files part%d",
		sanitizeID(pkgName), currentPart, currentPart))
	currentLength = len("Files")

	for _, file := range sortedFiles {
		entryLength := len(fmt.Sprintf("|<f%d> %s", fileNum+1, file))

		if currentLength+entryLength > maxLabelLength {
			sb.WriteString("}\"];\n\n")
			currentPart++
			sb.WriteString(fmt.Sprintf("    %s_files_part%d [label=\"{Files part%d",
				sanitizeID(pkgName), currentPart, currentPart))
			currentLength = len("Files")
		}

		fileNum++
		fileNumMap[file] = fileNum
		filePartMap[fileNum] = currentPart // Store which part this file belongs to
		sb.WriteString(fmt.Sprintf("|<f%d> %s", fileNum, file))
		currentLength += entryLength
	}
	sb.WriteString("}\"];\n\n")

	// Add invisible edges between parts
	for i := 1; i < currentPart; i++ {
		sb.WriteString(fmt.Sprintf("    %s_files_part%d -> %s_files_part%d [style=invis];\n",
			sanitizeID(pkgName), i, sanitizeID(pkgName), i+1))
	}
	sb.WriteString("\n")

	return fileNumMap, filePartMap
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

func processStructsAndEnums(
	sb *strings.Builder, nodes []GraphNode, kg *StructuredKnowledgeGraph,
	nodeMap map[string]GraphNode, enumValues map[string][]string) map[string]map[string]int {
	structs := filterNodesByType(nodes, StructNode)

	// methodNumMap is a map[string]map[string]int tracking struct_name -> method_name -> method_number
	methodNumMap := make(map[string]map[string]int)

	for _, s := range structs {
		if data, ok := s.Data.(map[string]interface{}); ok {
			structName := fmt.Sprintf("%v", data["struct_name"])
			methodNumMap[structName] = make(map[string]int)
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
					fieldIDParts := strings.SplitN(fmt.Sprintf("%v", fieldID), ":", 2)
					fieldFullID := fmt.Sprintf("%s:%s.%s", fieldIDParts[0], structName, fieldIDParts[1])
					if fieldNode, exists := nodeMap[fieldFullID]; exists {
						if fieldData, ok := fieldNode.Data.(map[string]interface{}); ok {
							fieldName := fmt.Sprintf("%v", fieldData["field_name"])
							fieldType := sanitizeParams(fmt.Sprintf("%v", fieldData["field_type"]))
							sb.WriteString(fmt.Sprintf("%s %s\\l", fieldName, fieldType))
						}
					}
				}
			}

			// Process methods and add <m> fields
			sb.WriteString("|")
			methodNum := 0
			for _, node := range kg.Nodes {
				if node.Type == FunctionNode {
					if funcData, ok := node.Data.(map[string]interface{}); ok {
						if parentStruct, hasParent := funcData["parent_struct"]; hasParent {
							if fmt.Sprintf("%v", parentStruct) == s.ID {
								funcName := fmt.Sprintf("%v", funcData["function_name"])
								if parts := strings.Split(funcName, "."); len(parts) > 1 {
									funcName = parts[1]
								}
								inputParams := sanitizeParams(fmt.Sprintf("%v", funcData["input_params"]))
								returnParams := sanitizeParams(fmt.Sprintf("%v", funcData["return_params"]))

								methodNum++
								methodStr := fmt.Sprintf("<m%d> %s%s", methodNum, funcName, inputParams)
								if returnParams != "" {
									methodStr += " " + returnParams
								}
								methodNumMap[structName][funcName] = methodNum
								sb.WriteString(methodStr + "|")
							}
						}
					}
				}
			}
			sb.WriteString("}\"];\n")
		}
	}
	sb.WriteString("\n")
	return methodNumMap
}

func sanitizeParams(params string) string {
	// Replace "chan struct{}" with "chan struct"
	params = strings.ReplaceAll(params, "struct{}", "struct")
	// Replace nested struct definitions with just "struct"
	if idx := strings.Index(params, "struct {"); idx != -1 {
		prefix := params[:idx]
		return prefix + "struct"
	}
	return params
}

func processGlobalFunctionsWithFields(sb *strings.Builder, pkgName string, nodes []GraphNode) (map[string]int, map[int]int) {
	funcs := filterNodesByType(nodes, FunctionNode)
	globalFuncs := make([]GraphNode, 0)
	funcNumMap := make(map[string]int)
	funcNum := 0

	// Filter out member functions
	for _, f := range funcs {
		if data, ok := f.Data.(map[string]interface{}); ok {
			if _, hasParent := data["parent_struct"]; !hasParent {
				globalFuncs = append(globalFuncs, f)
			}
		}
	}

	if len(globalFuncs) == 0 {
		return funcNumMap, nil
	}

	const maxLabelLength = 16000 // Keep some buffer below 16384
	var currentLength int
	var currentPart int

	// Start first part
	currentPart++
	sb.WriteString(fmt.Sprintf("    %s_functions_part%d [label=\"{Functions part%d",
		sanitizeID(pkgName), currentPart, currentPart))
	currentLength = len("Functions")

	// Store the part number for each function as we create it
	partMap := make(map[int]int) // funcNum -> partNum

	for _, f := range globalFuncs {
		if data, ok := f.Data.(map[string]interface{}); ok {
			funcName := fmt.Sprintf("%v", data["function_name"])
			inputParams := sanitizeParams(fmt.Sprintf("%v", data["input_params"]))
			returnParams := sanitizeParams(fmt.Sprintf("%v", data["return_params"]))

			label := funcName + inputParams
			if returnParams != "" {
				label += " " + returnParams
			}

			entryLength := len(fmt.Sprintf("|<fn%d> %s", funcNum+1, label))

			if currentLength+entryLength > maxLabelLength {
				sb.WriteString("}\"];\n\n")
				currentPart++
				sb.WriteString(fmt.Sprintf("    %s_functions_part%d [label=\"{Functions part%d",
					sanitizeID(pkgName), currentPart, currentPart))
				currentLength = len("Functions")
			}

			funcNum++
			sb.WriteString(fmt.Sprintf("|<fn%d> %s", funcNum, label))
			currentLength += entryLength
			funcNumMap[funcName] = funcNum
			partMap[funcNum] = currentPart // Store which part this function belongs to
		}
	}
	sb.WriteString("}\"];\n\n")

	// Add invisible edges between parts
	for i := 1; i < currentPart; i++ {
		sb.WriteString(fmt.Sprintf("    %s_functions_part%d -> %s_functions_part%d [style=invis];\n",
			sanitizeID(pkgName), i, sanitizeID(pkgName), i+1))
	}
	sb.WriteString("\n")

	// Store the part mapping in a global variable or pass it through the return value
	return funcNumMap, partMap
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

func generateContainsRelationships(sb *strings.Builder, pkgName string, fileToFuncs map[string][]string, funcNumMap map[string]int, fileNumMap map[string]int, partMap map[int]int, filePartMap map[int]int) {
	// Generate relationships using both part mappings
	for file, funcs := range fileToFuncs {
		if fileNum, exists := fileNumMap[file]; exists {
			if filePart, exists := filePartMap[fileNum]; exists {
				for _, fn := range funcs {
					if funcNum, exists := funcNumMap[fn]; exists {
						if partNum, exists := partMap[funcNum]; exists {
							sb.WriteString(fmt.Sprintf("    %s_files_part%d:f%d -> %s_functions_part%d:fn%d [label=\"has\"];\n",
								sanitizeID(pkgName),
								filePart,
								fileNum,
								sanitizeID(pkgName),
								partNum,
								funcNum))
						}
					}
				}
			}
		}
	}
	sb.WriteString("\n")
}

func generateHasRelationships(sb *strings.Builder, pkgName string, fileToStructs map[string][]string, fileNumMap map[string]int, filePartMap map[int]int) {
	// Generate relationships using the file part mapping
	for file, structs := range fileToStructs {
		if fileNum, exists := fileNumMap[file]; exists {
			if filePart, exists := filePartMap[fileNum]; exists {
				for _, structName := range structs {
					sb.WriteString(fmt.Sprintf("    %s_files_part%d:f%d -> %s_%s [label=\"has\"];\n",
						sanitizeID(pkgName),
						filePart,
						fileNum,
						sanitizeID(pkgName),
						sanitizeID(structName)))
				}
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
