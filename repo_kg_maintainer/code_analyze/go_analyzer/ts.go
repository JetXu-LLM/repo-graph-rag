package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	mapset "github.com/deckarep/golang-set/v2"
	sitter "github.com/smacker/go-tree-sitter"
	"github.com/smacker/go-tree-sitter/golang"
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

// Update the global variable type and initialization
var structuredKG = StructuredKnowledgeGraph{
	Nodes: []GraphNode{}, // Initialize as empty slice instead of map
	Edges: []GraphEdge{}, // Initialize as empty slice instead of pointer slice
}

// Update the generateNodeID function to accept NodeType
func generateNodeID(nodeType NodeType, name string, filePath string) string {
	if filePath == "" || nodeType == ImportNode {
		// For ImportNode id doesn't need filePath
		return fmt.Sprintf("%s:%s", string(nodeType), name)
	}
	return fmt.Sprintf("%s:%s:%s", string(nodeType), name, filePath)
}

func NewKnowledgeGraph() *KnowledgeGraph {
	return &KnowledgeGraph{
		Nodes: make(map[string]*Node),
		Edges: make([]*Edge, 0),
	}
}

func findNodeID(nodeIds mapset.Set[string], filePath string, nodeName string) (string, bool) {
	sections := strings.Split(nodeName, ".")
	var nodeId string
	if len(sections) == 2 {
		// package.function
		funcName := sections[1]
		nodeId = fmt.Sprintf("function:%s:%s", funcName, filePath)
		if nodeIds.Contains(nodeId) {
			return nodeId, true
		}
	} else if len(sections) == 3 {
		// package.struct.function
		funcName := sections[2]
		structName := sections[1]
		nodeId = fmt.Sprintf("function:%s.%s:%s", structName, funcName, filePath)
		if nodeIds.Contains(nodeId) {
			return nodeId, true
		}
	}
	return "", false
}

func main() {
	// Parse debug flag
	debug := false
	for _, arg := range os.Args[1:] {
		if arg == "--debug" {
			debug = true
			break
		}
	}

	if len(os.Args) < 2 {
		fmt.Println("Usage: program <project-path> [--debug]")
		os.Exit(1)
	}

	projectPath := os.Args[1]
	if projectPath == "--debug" {
		if len(os.Args) < 3 {
			fmt.Println("Usage: program <project-path> [--debug]")
			os.Exit(1)
		}
		projectPath = os.Args[2]
	}

	kg := NewKnowledgeGraph()
	parser := sitter.NewParser()
	language := golang.GetLanguage()
	parser.SetLanguage(language)

	if parser == nil || language == nil {
		fmt.Println("Failed to initialize parser or language")
		os.Exit(1)
	}

	// Walk through all Go files in the project. For each file we has 3 loops.
	err := filepath.Walk(projectPath, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && strings.HasSuffix(path, ".go") {
			if debug {
				fmt.Printf("Scanning file: %s\n", path)
			}
			if err := parseFile(path, parser, kg, debug); err != nil {
				fmt.Printf("Error parsing %s: %v\n", path, err)
			}
		}
		return nil
	})

	if err != nil {
		fmt.Printf("Error walking project: %v\n", err)
		os.Exit(1)
	}
	if debug {
		// Dump kg to a json file
		kgJSON, err := json.MarshalIndent(kg, "", "  ")
		if err != nil {
			fmt.Printf("Error marshalling knowledge graph: %v\n", err)
		}
		os.WriteFile("kg.json", kgJSON, 0644)
	}

	// Print the knowledge graph in std
	// This is for debugging purpose only, not for the final output knowledge_graph.json file
	printKnowledgeGraph(kg)

	// Generate the call graph
	relationships, err := GenerateCallGraph(projectPath)
	if err != nil {
		fmt.Printf("Error generating call graph: %v\n", err)
		os.Exit(1)
	}

	// Add all node IDs to a set
	nodeIds := mapset.NewSet[string]()
	for _, node := range structuredKG.Nodes {
		nodeIds.Add(node.ID)
	}

	// Add the call graph to the knowledge graph
	existingCallEdges := mapset.NewSet[string]()
	for _, relationship := range relationships {
		callerID, exists := findNodeID(nodeIds, relationship.CallerFilePath, relationship.Caller)
		if !exists {
			fmt.Printf("Caller node not found: [function:%s:%s]\n", relationship.Caller, relationship.CallerFilePath)
			continue
		}
		calleeID, exists := findNodeID(nodeIds, relationship.CalleeFilePath, relationship.Callee)
		if !exists {
			fmt.Printf("Callee node not found: [function:%s:%s]\n", relationship.Callee, relationship.CalleeFilePath)
			continue
		}

		// If this edge is already in the knowledge graph, skip it
		if existingCallEdges.Contains(fmt.Sprintf("%s:%s", callerID, calleeID)) {
			continue
		}
		structuredKG.Edges = append(structuredKG.Edges, GraphEdge{
			SourceType:   "function",
			SourceID:     callerID,
			TargetType:   "function",
			TargetID:     calleeID,
			RelationType: Calls,
		})
		existingCallEdges.Add(fmt.Sprintf("%s:%s", callerID, calleeID))
	}
	// Save the structuredKG (which is a StructuredKnowledgeGraph) in knowledge_graph.json file
	if err := saveKnowledgeGraph(); err != nil {
		fmt.Printf("Error saving knowledge graph: %v\n", err)
	}
}

func parseFile(filePath string, parser *sitter.Parser, kg *KnowledgeGraph, debug bool) error {
	content, err := os.ReadFile(filePath)
	if err != nil {
		return err
	}

	inputStr := string(content)
	tree := parser.Parse(nil, []byte(inputStr))
	if tree == nil {
		return fmt.Errorf("failed to parse file: %s", filePath)
	}
	defer tree.Close()

	// Use the new two-pass processing with debug flag
	ProcessASTNodes(tree.RootNode(), content, filePath, kg, debug)

	return nil
}

// First, add a new function to process all nodes first
func ProcessASTNodes(root *sitter.Node, content []byte, filePath string, kg *KnowledgeGraph, debug bool) {
	if debug {
		fmt.Println("\nProcessing AST nodes for:", filePath)
	}

	// First pass: Process package declaration
	if debug {
		fmt.Println("- Processing package declaration")
	}
	processPackageDecl(root, content, filePath, kg)

	// Second pass: Process all type declarations
	if debug {
		fmt.Println("- Processing type declarations")
	}
	processTypes(root, content, filePath, kg, debug)

	// Third pass: Process everything else
	if debug {
		fmt.Println("- Processing other nodes")
	}
	processOtherNodes(root, content, filePath, kg, debug)
}

func processPackageDecl(node *sitter.Node, content []byte, filePath string, kg *KnowledgeGraph) {
	if node.Type() == "source_file" {
		// Find package clause
		for i := 0; i < int(node.NamedChildCount()); i++ {
			child := node.NamedChild(i)
			if child.Type() == "package_clause" {
				// The package identifier is the first named child of the package clause
				if child.NamedChildCount() > 0 {
					nameNode := child.NamedChild(0)
					if nameNode != nil {
						packageName := getNodeText(nameNode, content)
						addNode(kg, "package", packageName, filePath, child.StartPoint(), child.EndPoint(), "", packageName)
					}
				}
				break // We only need the first package clause
			}
		}
	}
}

func processTypes(node *sitter.Node, content []byte, filePath string, kg *KnowledgeGraph, debug bool) {
	// Find the package name first
	var packageName string
	for _, n := range kg.Nodes {
		if n.Type == "package" && n.FilePath == filePath {
			packageName = n.Name
			break
		}
	}

	if node.Type() == "type_declaration" {
		typeNode := node.NamedChild(0)
		if typeNode != nil {
			typeName := getNodeText(typeNode.ChildByFieldName("name"), content)
			if debug {
				fmt.Printf("  Found type declaration: %s\n", typeName)
			}

			// Get the underlying type definition
			typeDefNode := typeNode.ChildByFieldName("type")
			if typeDefNode != nil {
				// Find the package node for this file first
				var packageNode *Node
				if packageNode, exists := kg.Nodes[generateNodeID("package", packageName, filePath)]; exists {
					packageNode = packageNode
				}

				if typeDefNode.Type() == "struct_type" {
					// Store old temporary node IDs before removing them
					oldNodeIDs := make([]string, 0)
					for _, n := range kg.Nodes {
						if n.Type == "type_spec" && n.Name == typeName && n.PackageName == packageName && n.FilePath != filePath {
							oldNodeIDs = append(oldNodeIDs, generateNodeID(StructNode, typeName, n.FilePath))
						}
					}

					// Remove temporary nodes as before
					for _, n := range kg.Nodes {
						if n.Type == "type_spec" && n.Name == typeName && n.PackageName == packageName && n.FilePath != filePath {
							delete(kg.Nodes, fmt.Sprintf("%s:%s:%s:%d", n.Type, n.Name, n.FilePath, n.Line-1))

							for i := len(structuredKG.Nodes) - 1; i >= 0; i-- {
								node := structuredKG.Nodes[i]
								if node.Type == StructNode {
									if structData, ok := node.Data.(StructInfo); ok {
										if structData.StructName == typeName && structData.PackageName == packageName {
											structuredKG.Nodes = append(structuredKG.Nodes[:i], structuredKG.Nodes[i+1:]...)
										}
									}
								}
							}
						}
					}

					// Create the new struct node
					typeNodeObj := addNode(kg, "type_spec", typeName, filePath, typeNode.StartPoint(), typeNode.EndPoint(), "", packageName)

					if packageNode != nil {
						addEdge(kg, packageNode, typeNodeObj, "has_struct")
					}

					// Update has_method edges in structuredKG
					newNodeID := generateNodeID(StructNode, typeName, filePath)
					for i := len(structuredKG.Edges) - 1; i >= 0; i-- {
						edge := structuredKG.Edges[i]
						if edge.RelationType == "has_method" {
							// Check if this edge was connected to any of the old temporary nodes
							for _, oldID := range oldNodeIDs {
								if edge.SourceID == oldID {
									// Update the edge to point to the new struct node
									structuredKG.Edges[i].SourceID = newNodeID
									break
								}
							}
						}
					}

					// Update parent_struct references in function nodes
					for i := range structuredKG.Nodes {
						node := &structuredKG.Nodes[i]
						if node.Type == FunctionNode {
							if memberFunc, ok := node.Data.(MemberFunction); ok {
								for _, oldID := range oldNodeIDs {
									if memberFunc.ParentStruct == oldID {
										memberFunc.ParentStruct = newNodeID
										node.Data = memberFunc
										break
									}
								}
							}
						}
					}

					// Update the struct data in the structured graph
					for i, n := range structuredKG.Nodes {
						if n.Type == StructNode && n.ID == newNodeID {
							if structData, ok := n.Data.(StructInfo); ok {
								structData.PackageName = packageName
								structuredKG.Nodes[i].Data = structData
							}
							break
						}
					}

					processStructFields(typeDefNode, content, filePath, kg, typeNodeObj, typeName, packageName)
				} else if typeDefNode.Type() == "function_type" {
					// Handle function type
					functionNodeObj := addNode(kg, "function", typeName, filePath, typeNode.StartPoint(), typeNode.EndPoint(), "", packageName)

					// Extract parameters and return types from the function type
					paramsNode := typeDefNode.ChildByFieldName("parameters")
					resultNode := typeDefNode.ChildByFieldName("result")

					var inputParams, returnParams string
					if paramsNode != nil {
						inputParams = getNodeText(paramsNode, content)
					}
					if resultNode != nil {
						returnParams = getNodeText(resultNode, content)
					}

					if packageNode != nil {
						addEdge(kg, packageNode, functionNodeObj, "has_function")

						// Update the function data in the structured graph
						for i, n := range structuredKG.Nodes {
							if n.Type == FunctionNode && n.ID == generateNodeID(FunctionNode, typeName, filePath) {
								funcData := Function{
									PackageName:  packageName,
									FunctionName: typeName,
									InputParams:  inputParams,
									ReturnParams: returnParams,
									Location: CodeLocation{
										FilePath: filePath,
										Line:     int(typeNode.StartPoint().Row + 1),
										Col:      int(typeNode.StartPoint().Column + 1),
										LineEnd:  int(typeNode.EndPoint().Row + 1),
									},
								}
								structuredKG.Nodes[i].Data = funcData
								break
							}
						}
					}
				} else {
					// Remove temporary nodes as before
					for _, n := range kg.Nodes {
						if n.Type == "type_spec" && n.Name == typeName && n.PackageName == packageName && n.FilePath != filePath {
							delete(kg.Nodes, fmt.Sprintf("%s:%s:%s:%d", n.Type, n.Name, n.FilePath, n.Line-1))

							for i := len(structuredKG.Nodes) - 1; i >= 0; i-- {
								node := structuredKG.Nodes[i]
								if node.Type == StructNode {
									if structData, ok := node.Data.(StructInfo); ok {
										if structData.StructName == typeName && structData.PackageName == packageName {
											structuredKG.Nodes = append(structuredKG.Nodes[:i], structuredKG.Nodes[i+1:]...)
										}
									}
								}
							}
						}
					}
					// Handle other types. e.g, enum
					typeNodeObj := addNode(kg, "type_spec", typeName, filePath, typeNode.StartPoint(), typeNode.EndPoint(), "", packageName)
					if packageNode != nil {
						addEdge(kg, packageNode, typeNodeObj, "has_type_spec")
					}
				}
			}
		}
	}

	// Recursively process children
	for i := 0; i < int(node.NamedChildCount()); i++ {
		processTypes(node.NamedChild(i), content, filePath, kg, debug)
	}
}

func processStructFields(structNode *sitter.Node, content []byte, filePath string, kg *KnowledgeGraph, parentTypeNode *Node, parentTypeName string, packageName string) {
	fieldListNode := structNode.NamedChild(0)
	if fieldListNode != nil {
		for i := 0; i < int(fieldListNode.NamedChildCount()); i++ {
			fieldNode := fieldListNode.NamedChild(i)
			if fieldNode.Type() == "field_declaration" {
				nameNode := fieldNode.ChildByFieldName("name")
				typeRef := fieldNode.ChildByFieldName("type")

				if typeRef != nil {
					if nameNode == nil {
						// Handle embedded types in the second pass
						continue
					}

					fieldName := getNodeText(nameNode, content)

					// Handle different field types
					switch typeRef.Type() {
					case "struct_type":
						// Direct nested struct
						processNestedStruct(fieldName, "", typeRef, content, filePath, kg, parentTypeNode, parentTypeName, packageName)

					case "slice_type":
						// Array/slice of structs
						elementType := typeRef.ChildByFieldName("element")
						if elementType != nil && elementType.Type() == "struct_type" {
							processNestedStruct(fieldName, "[]", elementType, content, filePath, kg, parentTypeNode, parentTypeName, packageName)
						} else {
							// Regular array field
							processRegularField(fieldName, typeRef, content, filePath, kg, parentTypeNode, parentTypeName, packageName)
						}

					case "map_type":
						// Map with struct value
						valueType := typeRef.ChildByFieldName("value")
						if valueType != nil && valueType.Type() == "struct_type" {
							keyType := getNodeText(typeRef.ChildByFieldName("key"), content)
							mapPrefix := fmt.Sprintf("map[%s]", keyType)
							processNestedStruct(fieldName, mapPrefix, valueType, content, filePath, kg, parentTypeNode, parentTypeName, packageName)
						} else {
							// Regular map field
							processRegularField(fieldName, typeRef, content, filePath, kg, parentTypeNode, parentTypeName, packageName)
						}

					default:
						// Regular field
						processRegularField(fieldName, typeRef, content, filePath, kg, parentTypeNode, parentTypeName, packageName)
					}
				}
			}
		}
	}
}

func processNestedStruct(fieldName string, typePrefix string, structNode *sitter.Node, content []byte, filePath string, kg *KnowledgeGraph, parentTypeNode *Node, parentTypeName string, packageName string) {
	// Create a field node for the struct field itself
	var fieldDesc string
	if typePrefix == "[]" {
		fieldDesc = fmt.Sprintf("%s []struct", fieldName)
	} else if typePrefix != "" {
		fieldDesc = fmt.Sprintf("%s %sstruct", fieldName, typePrefix)
	} else {
		fieldDesc = fmt.Sprintf("%s struct", fieldName)
	}

	fieldNodeObj := addNode(kg, "field", fieldDesc, filePath, structNode.StartPoint(), structNode.EndPoint(), parentTypeName, packageName)
	fieldNodeObj.ParentStruct = parentTypeName

	addEdge(kg, parentTypeNode, fieldNodeObj, "has_field")

	// Update the parent struct's Fields array
	fieldNodeID := generateNodeID(FieldNode, fieldDesc, filePath)
	for i, n := range structuredKG.Nodes {
		if n.Type == StructNode && n.ID == generateNodeID(StructNode, parentTypeName, filePath) {
			if structData, ok := n.Data.(StructInfo); ok {
				structData.Fields = append(structData.Fields, fieldNodeID)
				structuredKG.Nodes[i].Data = structData
			}
			break
		}
	}

	// Create a type node for the nested struct
	nestedTypeName := fieldName
	nestedTypeNode := addNode(kg, "type_spec", nestedTypeName, filePath, structNode.StartPoint(), structNode.EndPoint(), "", packageName)

	// Process the nested struct's fields
	processStructFields(structNode, content, filePath, kg, nestedTypeNode, nestedTypeName, packageName)
}

func processRegularField(fieldName string, typeRef *sitter.Node, content []byte, filePath string, kg *KnowledgeGraph, parentTypeNode *Node, parentTypeName string, packageName string) {
	fieldType := getNodeText(typeRef, content)
	fieldDesc := fmt.Sprintf("%s %s", fieldName, fieldType)
	fieldNodeObj := addNode(kg, "field", fieldDesc, filePath, typeRef.StartPoint(), typeRef.EndPoint(), parentTypeName, packageName)
	fieldNodeObj.ParentStruct = parentTypeName

	// Create has_field relationship
	addEdge(kg, parentTypeNode, fieldNodeObj, "has_field")

	// Update the parent struct's Fields array
	fieldNodeID := generateNodeID(FieldNode, fieldDesc, filePath)
	for i, n := range structuredKG.Nodes {
		if n.Type == StructNode && n.ID == generateNodeID(StructNode, parentTypeName, filePath) {
			if structData, ok := n.Data.(StructInfo); ok {
				structData.Fields = append(structData.Fields, fieldNodeID)
				structuredKG.Nodes[i].Data = structData
			}
			break
		}
	}
}

func processOtherNodes(node *sitter.Node, content []byte, filePath string, kg *KnowledgeGraph, debug bool) {
	// Find the package name first
	var packageName string
	for _, n := range kg.Nodes {
		if n.Type == "package" && n.FilePath == filePath {
			packageName = n.Name
			break
		}
	}

	switch node.Type() {
	case "source_file":
		// Process package declaration and imports
		for i := 0; i < int(node.NamedChildCount()); i++ {
			child := node.NamedChild(i)
			if child.Type() == "package_clause" {
				packageName := getNodeText(child.NamedChild(0), content)
				pkgNode := addNode(kg, "package", packageName, filePath, child.StartPoint(), child.EndPoint(), "", packageName)
				pkgNode.PackageName = packageName // Set package name for package node
			} else if child.Type() == "import_declaration" {
				processImports(child, filePath, content, kg, packageName)
			}
		}

	case "function_declaration", "method_declaration":
		var funcName string
		var funcNode *Node
		var typeNodeObj *Node
		var parentStruct string
		var inputParams string
		var returnParams string

		if node.Type() == "method_declaration" {
			methodName := getNodeText(node.ChildByFieldName("name"), content)
			receiverNode := node.ChildByFieldName("receiver")
			if receiverNode != nil {
				paramDecl := receiverNode.NamedChild(0)
				if paramDecl != nil {
					paramText := getNodeText(paramDecl, content)
					parts := strings.Fields(paramText)
					if len(parts) >= 1 {
						receiverType := parts[len(parts)-1]
						receiverType = strings.TrimPrefix(receiverType, "*")
						funcName = fmt.Sprintf("%s.%s", receiverType, methodName)

						// Look for the actual struct definition file
						var structFilePath string
						for _, node := range kg.Nodes {
							if node.Type == "type_spec" && node.Name == receiverType {
								// Check if the node is in the same package
								if node.PackageName == packageName || node.PackageName == "" {
									structFilePath = node.FilePath
									typeNodeObj = node
									break
								}
							}
						}

						// Use the correct file path for parent_struct ID
						if structFilePath != "" {
							parentStruct = generateNodeID(StructNode, receiverType, structFilePath)
						} else {
							// Fallback to current file if struct not found
							parentStruct = generateNodeID(StructNode, receiverType, filePath)
						}

						// If type node wasn't found in the current package, create a temporary one
						if typeNodeObj == nil {
							typeNodeObj = addNode(kg, "type_spec", receiverType, filePath, node.StartPoint(), node.EndPoint(), "", packageName)
						}

						// Update parent_struct for existing function nodes with the same name
						for _, n := range kg.Nodes {
							if n.Type == "function" && n.Name == funcName && n.PackageName == packageName {
								n.ParentStruct = parentStruct
							}
						}
					}
				}
			}
		} else {
			funcName = getNodeText(node.ChildByFieldName("name"), content)
		}

		// Extract parameters and return type
		paramsNode := node.ChildByFieldName("parameters")
		if paramsNode != nil {
			inputParams = getNodeText(paramsNode, content)
		}

		resultNode := node.ChildByFieldName("result")
		if resultNode != nil {
			returnParams = getNodeText(resultNode, content)
		}

		// Create function node
		funcNode = addNode(kg, "function", funcName, filePath, node.StartPoint(), node.EndPoint(), parentStruct, packageName)

		// Update the function data in the structured graph
		for i, n := range structuredKG.Nodes {
			if n.Type == FunctionNode && n.ID == generateNodeID(FunctionNode, funcName, filePath) {
				if parentStruct != "" {
					// This is a member function
					memberFunc := MemberFunction{
						Function: Function{
							PackageName:  packageName,
							FunctionName: funcName,
							InputParams:  inputParams,
							ReturnParams: returnParams,
							Location: CodeLocation{
								FilePath: filePath,
								Line:     int(node.StartPoint().Row + 1),
								Col:      int(node.StartPoint().Column + 1),
								LineEnd:  int(node.EndPoint().Row + 1),
							},
						},
						ParentStruct: parentStruct,
					}
					structuredKG.Nodes[i].Data = memberFunc
				} else {
					// This is a global function
					funcData := Function{
						PackageName:  packageName,
						FunctionName: funcName,
						InputParams:  inputParams,
						ReturnParams: returnParams,
						Location: CodeLocation{
							FilePath: filePath,
							Line:     int(node.StartPoint().Row + 1),
							Col:      int(node.StartPoint().Column + 1),
							LineEnd:  int(node.EndPoint().Row + 1),
						},
					}
					structuredKG.Nodes[i].Data = funcData
				}
				break
			}
		}

		// Create the edge for methods
		if typeNodeObj != nil && node.Type() == "method_declaration" {
			addEdge(kg, typeNodeObj, funcNode, "has_method")
		}

		// Process parameters
		paramList := node.ChildByFieldName("parameters")
		if paramList != nil {
			var params []string
			for i := 0; i < int(paramList.NamedChildCount()); i++ {
				paramNode := paramList.NamedChild(i)
				if paramNode.Type() == "parameter_declaration" {
					paramName := getNodeText(paramNode.ChildByFieldName("name"), content)
					paramType := getNodeText(paramNode.ChildByFieldName("type"), content)
					params = append(params, fmt.Sprintf("%s %s", paramName, paramType))
				}
			}
			funcNode.Parameters = params
		}

		// Process return values - first try result list
		resultList := node.ChildByFieldName("result")
		if resultList != nil {
			var returns []string
			for i := 0; i < int(resultList.NamedChildCount()); i++ {
				returnNode := resultList.NamedChild(i)
				if returnNode.Type() == "parameter_declaration" {
					returnType := getNodeText(returnNode.ChildByFieldName("type"), content)
					returnName := getNodeText(returnNode.ChildByFieldName("name"), content)
					if returnName != "" {
						returns = append(returns, fmt.Sprintf("%s %s", returnName, returnType))
					} else {
						returns = append(returns, returnType)
					}
				}
			}
			funcNode.Returns = returns
		}

		// If no return list, try to get the single return type
		if len(funcNode.Returns) == 0 {
			returnType := node.ChildByFieldName("result")
			if returnType != nil {
				returnTypeText := getNodeText(returnType, content)
				if returnTypeText != "" {
					funcNode.Returns = append(funcNode.Returns, returnTypeText)
				}
			}
		}

		// Process function body for function calls
		body := node.ChildByFieldName("body")
		if body != nil {
			processFunctionBody(body, funcNode, content, kg)
		}

		// Find the package node for this file
		var packageNode *Node
		for _, n := range kg.Nodes {
			if n.Type == "package" && n.FilePath == filePath {
				packageNode = n
				break
			}
		}

		// Create has_function relationship if package node exists
		if packageNode != nil && node.Type() == "function_declaration" {
			addEdge(kg, packageNode, funcNode, "has_function")
		}

	case "const_declaration":
		// Get the const spec list
		constSpecList := node.NamedChild(0)
		if constSpecList != nil {
			// First, try to find the type identifier
			var typeName string
			for i := 0; i < int(constSpecList.NamedChildCount()); i++ {
				child := constSpecList.NamedChild(i)
				if child.Type() == "type_identifier" {
					typeName = getNodeText(child, content)
				}
			}

			// Get the parent node to find all const specs in the block
			parentNode := node.Parent()
			if parentNode != nil {
				// Find the const declaration block
				for i := 0; i < int(parentNode.NamedChildCount()); i++ {
					child := parentNode.NamedChild(i)
					if child.Type() == "const_declaration" {
						// Process all const specs in the block
						for j := 0; j < int(child.NamedChildCount()); j++ {
							constSpec := child.NamedChild(j)
							if constSpec != nil && constSpec.Type() == "const_spec" {
								// For each const spec, get the identifier
								for k := 0; k < int(constSpec.NamedChildCount()); k++ {
									identNode := constSpec.NamedChild(k)
									if identNode.Type() == "identifier" {
										constName := getNodeText(identNode, content)
										if typeName != "" {
											// Create a node for the enum value
											enumValueNode := addNode(kg, "enum_value", constName, filePath, identNode.StartPoint(), identNode.EndPoint(), "", packageName)

											// Look for the type node
											for _, node := range kg.Nodes {
												if node.Type == "type_spec" && node.Name == typeName {
													addEdge(kg, node, enumValueNode, "has_value")
													break
												}
											}
										}
									}
								}
							}
						}
					}
				}
			}
		}

	case "var_declaration":
		// Get the var spec list
		varSpecList := node.NamedChild(0)
		if varSpecList != nil {
			for i := 0; i < int(varSpecList.NamedChildCount()); i++ {
				varSpec := varSpecList.NamedChild(i)
				if varSpec.Type() == "var_spec" {
					// Get variable name
					nameNode := varSpec.ChildByFieldName("name")
					if nameNode != nil {
						varName := getNodeText(nameNode, content)

						// Get variable type if explicitly specified
						typeNode := varSpec.ChildByFieldName("type")
						var typeStr string
						if typeNode != nil {
							typeStr = getNodeText(typeNode, content)
						} else {
							// If type is not explicitly specified, try to get it from the value
							valueNode := varSpec.ChildByFieldName("value")
							if valueNode != nil {
								if valueNode.Type() == "expression_list" {
									// For expression_list, look at the first expression
									if valueNode.NamedChildCount() > 0 {
										typeStr = inferTypeFromValue(valueNode.NamedChild(0), content)
									}
								} else {
									typeStr = inferTypeFromValue(valueNode, content)
								}
							}
						}

						// Create the variable node
						varNodeObj := addNode(kg, "variable",
							fmt.Sprintf("%s %s", varName, typeStr),
							filePath, varSpec.StartPoint(), varSpec.EndPoint(), "", packageName)
						varNodeObj.PackageName = packageName // Set package name for variable node

						// Extract all referenced types from the type string
						referencedTypes := extractReferencedTypes(typeStr)

						// Create references for each type
						for _, refType := range referencedTypes {
							for _, node := range kg.Nodes {
								if node.Type == "type_spec" && node.Name == refType {
									addEdge(kg, varNodeObj, node, "references")
								}
							}
						}
					}
				}
			}
		}

	case "type_declaration":
		// Process embedded types and type relationships
		typeNode := node.NamedChild(0)
		if typeNode != nil {
			typeName := getNodeText(typeNode.ChildByFieldName("name"), content)
			var typeNodeObj *Node

			// Find the existing type node
			for _, n := range kg.Nodes {
				if n.Type == "type_spec" && n.Name == typeName {
					typeNodeObj = n
					typeNodeObj.Name = typeName
					break
				}
			}

			if typeNodeObj != nil {
				typeDefNode := typeNode.ChildByFieldName("type")
				if typeDefNode != nil && typeDefNode.Type() == "struct_type" {
					fieldListNode := typeDefNode.NamedChild(0)
					if fieldListNode != nil {
						for i := 0; i < int(fieldListNode.NamedChildCount()); i++ {
							fieldNode := fieldListNode.NamedChild(i)
							if fieldNode.Type() == "field_declaration" {
								nameNode := fieldNode.ChildByFieldName("name")
								typeRef := fieldNode.ChildByFieldName("type")

								if typeRef != nil && nameNode == nil {
									// This is an embedded type
									embeddedTypeName := getNodeText(typeRef, content)
									embeddedTypeName = strings.TrimPrefix(embeddedTypeName, "*")

									// Look for the embedded type in our nodes
									for _, node := range kg.Nodes {
										if node.Type == "type_spec" && node.Name == embeddedTypeName {
											addEdge(kg, typeNodeObj, node, "extends")
											break
										}
									}
								} else {
									// Build reference relationships for the field
									typeName := getNodeText(typeRef, content)
									referencedTypes := extractReferencedTypes(typeName)
									for _, refType := range referencedTypes {
										for _, node := range kg.Nodes {
											if node.Type == "type_spec" && node.Name == refType {
												// Build "references" relationships for the field node to struct node
												fieldType := getNodeText(typeRef, content)
												fieldName := getNodeText(nameNode, content)
												fieldDesc := fmt.Sprintf("%s %s", fieldName, fieldType)
												fieldNodeKey := fmt.Sprintf("%s:%s:%s:%d", FieldNode, fieldDesc, filePath, typeRef.StartPoint().Row+1)
												fmt.Printf("fieldNodeKey: %s for %s\n", fieldNodeKey, refType)
												if n, exists := kg.Nodes[fieldNodeKey]; exists {
													fmt.Printf("Found field node: %s\n", fieldNodeKey)
													addEdge(kg, n, node, "references")
												}
											}
										}
									}
								}
							}
						}
					}
				}
			}
		}
	}

	// Recursively process children
	for i := 0; i < int(node.NamedChildCount()); i++ {
		processOtherNodes(node.NamedChild(i), content, filePath, kg, debug)
	}
}

func processImports(node *sitter.Node, filePath string, content []byte, kg *KnowledgeGraph, packageName string) {
	for i := 0; i < int(node.NamedChildCount()); i++ {
		child := node.NamedChild(i)
		if child.Type() == "import_spec" {
			importPath := getNodeText(child.NamedChild(0), content)
			importPath = strings.Trim(importPath, "\"")

			// Check if the importNode already exists in the structured knowledge graph
			nodeExists := false
			nodeID := generateNodeID(ImportNode, importPath, filePath)
			for _, n := range structuredKG.Nodes {
				if n.Type == ImportNode && n.ID == nodeID {
					// If it exists, we don't need to create a new one
					nodeExists = true
					break
				}
			}
			if nodeExists {
				// If it exists, we don't need to create a new one
				continue
			}

			// Create the import node
			importNode := addNode(kg, "import", importPath, filePath, child.StartPoint(), child.EndPoint(), "", packageName)

			// Update the ImportInfo in the structured knowledge graph
			for i, n := range structuredKG.Nodes {
				if n.Type == ImportNode && n.ID == nodeID {
					if importInfo, ok := n.Data.(ImportInfo); ok {
						importInfo.PackageName = packageName
						structuredKG.Nodes[i].Data = importInfo
					}
					break
				}
			}

			// Find the package node for this file
			var packageNode *Node
			for _, n := range kg.Nodes {
				if n.Type == "package" && n.FilePath == filePath {
					packageNode = n
					break
				}
			}

			// Create has_import relationship if package node exists
			if packageNode != nil {
				addEdge(kg, packageNode, importNode, "has_import")
			}
		}
	}
}

func processFunctionBody(node *sitter.Node, funcNode *Node, content []byte, kg *KnowledgeGraph) {
	cursor := sitter.NewTreeCursor(node)
	defer cursor.Close()

	if cursor.GoToFirstChild() {
		for {
			if cursor.CurrentNode().Type() == "call_expression" {
				callNode := cursor.CurrentNode()
				functionName := getNodeText(callNode.ChildByFieldName("function"), content)

				// Add edge representing function call
				calledFunc := addNode(kg, "function_call", functionName, funcNode.FilePath, callNode.StartPoint(), callNode.EndPoint(), "", "")
				addEdge(kg, funcNode, calledFunc, "calls")
			}

			if !cursor.GoToNextSibling() {
				break
			}
		}
	}
}

// addNode will update both the knowledge graph and the structured knowledge graph
func addNode(
	kg *KnowledgeGraph, nodeType, name, filePath string, startPos sitter.Point, endPos sitter.Point,
	parentStruct string, packageName string) *Node {
	key := fmt.Sprintf("%s:%s:%s:%d", nodeType, name, filePath, startPos.Row+1)
	if node, exists := kg.Nodes[key]; exists {
		return node
	}

	node := &Node{
		Type:         nodeType,
		Name:         name,
		FilePath:     filePath,
		Line:         startPos.Row + 1,
		Column:       startPos.Column + 1,
		EndLine:      endPos.Row + 1,
		EndColumn:    endPos.Column + 1,
		ParentStruct: parentStruct,
		PackageName:  packageName,
	}
	kg.Nodes[key] = node

	// Add to structured graph
	location := CodeLocation{
		FilePath: filePath,
		Line:     int(startPos.Row + 1),
		Col:      int(startPos.Column + 1),
		LineEnd:  int(endPos.Row + 1),
	}

	var structNodeType NodeType
	var nodeData interface{}
	var nodeID string

	switch nodeType {
	case "package":
		structNodeType = PackageNode
		nodeData = PackageInfo{
			PackageName: name,
			Location:    location,
		}
		nodeID = generateNodeID(structNodeType, name, filePath)
	case "import":
		structNodeType = ImportNode
		location.FilePath = ""
		nodeData = ImportInfo{
			ImportPath: name,
			Location:   location,
		}
		// We don't need the file path for import nodes ID
		nodeID = generateNodeID(structNodeType, name, "")
	case "type_spec":
		structNodeType = StructNode
		nodeData = StructInfo{
			PackageName: packageName,
			StructName:  name,
			Fields:      make([]string, 0),
			Location:    location,
		}
		nodeID = generateNodeID(structNodeType, name, filePath)
	case "function":
		structNodeType = FunctionNode
		nodeData = Function{
			PackageName:  packageName,
			FunctionName: name,
			InputParams:  "",
			ReturnParams: "",
			Location:     location,
		}
		nodeID = generateNodeID(structNodeType, name, filePath)
	case "field":
		parts := strings.SplitN(name, " ", 2)
		if len(parts) == 2 {
			// Generate parent struct ID if we have a parent struct
			var parentStructID string
			if parentStruct != "" {
				parentStructID = generateNodeID(StructNode, parentStruct, filePath)
			}

			structNodeType = FieldNode
			nodeData = FieldInfo{
				FieldName:    parts[0],
				FieldType:    parts[1],
				ParentStruct: parentStructID,
			}
			nodeID = generateNodeID(structNodeType, fmt.Sprintf("%s.%s", parentStruct, name), filePath)
		}
	case "variable":
		parts := strings.SplitN(name, " ", 2)
		if len(parts) == 2 {
			structNodeType = VariableNode
			nodeData = Variable{
				VarName:  parts[0],
				VarType:  parts[1],
				Location: location,
			}
			nodeID = generateNodeID(structNodeType, name, filePath)
		}
	}

	// Only add to structured graph if we have valid node data and it doesn't already exist
	if nodeData != nil {
		structuredNode := GraphNode{
			ID:   nodeID,
			Type: structNodeType,
			Data: nodeData,
		}
		structuredKG.Nodes = append(structuredKG.Nodes, structuredNode)
	}

	return node
}

func getNodeText(node *sitter.Node, content []byte) string {
	if node == nil {
		return ""
	}

	// Special handling for struct types
	if node.Type() == "struct_type" {
		return "struct"
	}

	// Special handling for slice types
	if node.Type() == "slice_type" {
		elementType := node.ChildByFieldName("element")
		if elementType != nil && elementType.Type() == "struct_type" {
			return "[]struct"
		}
	}

	// Special handling for maps with struct values
	if node.Type() == "map_type" {
		keyType := node.ChildByFieldName("key")
		valueType := node.ChildByFieldName("value")
		if valueType != nil && valueType.Type() == "struct_type" {
			return fmt.Sprintf("map[%s]struct", getNodeText(keyType, content))
		}
	}

	start := node.StartByte()
	end := node.EndByte()
	// Add a special treatment for `interface{}` because dot doesn't support `{}` well.
	ret := strings.ReplaceAll(string(content[start:end]), "interface{}", "interface")
	return strings.ReplaceAll(ret, "<-", "")
}

// Print the knowledge graph in stdout.
func printKnowledgeGraph(kg *KnowledgeGraph) {
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

func isBuiltinType(typeName string) bool {
	builtinTypes := map[string]bool{
		"string":  true,
		"int":     true,
		"int8":    true,
		"int16":   true,
		"int32":   true,
		"int64":   true,
		"uint":    true,
		"uint8":   true,
		"uint16":  true,
		"uint32":  true,
		"uint64":  true,
		"float32": true,
		"float64": true,
		"bool":    true,
		"byte":    true,
		"rune":    true,
	}
	return builtinTypes[typeName]
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

// Update saveKnowledgeGraph function
func saveKnowledgeGraph() error {
	data, err := json.MarshalIndent(structuredKG, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal knowledge graph: %v", err)
	}

	return os.WriteFile("knowledge_graph.json", data, 0644)
}

// Add a helper function to add edges to both graphs
func addEdge(kg *KnowledgeGraph, from *Node, to *Node, edgeType string) {
	// Add to original graph
	kg.Edges = append(kg.Edges, &Edge{
		From: from,
		To:   to,
		Type: edgeType,
	})

	// Add to structured graph
	structuredEdge := GraphEdge{
		SourceType:   from.Type,
		SourceID:     generateNodeID(getNodeType(from.Type), from.Name, from.FilePath),
		TargetType:   to.Type,
		TargetID:     generateNodeID(getNodeType(to.Type), to.Name, to.FilePath),
		RelationType: EdgeType(edgeType),
	}
	structuredKG.Edges = append(structuredKG.Edges, structuredEdge)
}

// Helper function to convert string type to NodeType
func getNodeType(nodeType string) NodeType {
	switch nodeType {
	case "package":
		return PackageNode
	case "type_spec":
		return StructNode
	case "function":
		return FunctionNode
	case "field":
		return FieldNode
	case "variable":
		return VariableNode
	case "enum":
		return EnumNode
	case "enum_value":
		return EnumValueNode
	case "import":
		return ImportNode
	default:
		return NodeType(nodeType)
	}
}
