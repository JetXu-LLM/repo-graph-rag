package analyzer

import (
	"fmt"
	"math"
	"path/filepath"
	"strings"

	sitter "github.com/smacker/go-tree-sitter"
)

func ProcessOtherNodes(
	node *sitter.Node,
	content []byte,
	filePath string,
	debug bool,
	structuredKG *StructuredKnowledgeGraph,
) {
	// Find the package name first
	var packageName string
	for _, n := range structuredKG.Kg.Nodes {
		if n.Type == "package" && filepath.Dir(filePath) == n.FilePath {
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
				pkgNode := addNode(
					"package",
					packageName,
					filePath,
					child.StartPoint(),
					child.EndPoint(),
					"",
					packageName,
					structuredKG,
				)
				pkgNode.PackageName = packageName // Set package name for package node
			} else if child.Type() == "import_declaration" {
				processImports(child, filePath, content, packageName, structuredKG)
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
						for _, node := range structuredKG.Kg.Nodes {
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
							fmt.Printf("Add temporary node %s:%s:%s\n", packageName, receiverType, filePath)
							typeNodeObj = addNode(
								"type_spec",
								receiverType,
								filePath,
								node.StartPoint(),
								node.EndPoint(),
								"",
								packageName,
								structuredKG,
							)
						}

						// Update parent_struct for existing function nodes with the same name
						for _, n := range structuredKG.Kg.Nodes {
							if n.Type == "function" && n.Name == funcName &&
								n.PackageName == packageName {
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
		funcNode = addNode(
			"function",
			funcName,
			filePath,
			node.StartPoint(),
			node.EndPoint(),
			parentStruct,
			packageName,
			structuredKG,
		)

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
			addEdge(typeNodeObj, funcNode, "has_method", structuredKG)
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
			processFunctionBody(body, funcNode, content, structuredKG)
		}

		// Find the package node for this file
		var packageNode *Node
		for _, n := range structuredKG.Kg.Nodes {
			if n.Type == "package" && filepath.Dir(filePath) == n.FilePath {
				packageNode = n
				break
			}
		}

		// Create has_function relationship if package node exists
		if packageNode != nil && node.Type() == "function_declaration" {
			addEdge(packageNode, funcNode, "has_function", structuredKG)
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
											enumValueNode := addNode(
												"enum_value",
												constName,
												filePath,
												identNode.StartPoint(),
												identNode.EndPoint(),
												"",
												packageName,
												structuredKG,
											)

											// Look for the type node
											for _, node := range structuredKG.Kg.Nodes {
												if node.Type == "type_spec" &&
													node.Name == typeName {
													addEdge(
														node,
														enumValueNode,
														"has_value",
														structuredKG,
													)
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
						varNodeObj := addNode(
							"variable",
							fmt.Sprintf("%s %s", varName, typeStr),
							filePath,
							varSpec.StartPoint(),
							varSpec.EndPoint(),
							"",
							packageName,
							structuredKG,
						)
						varNodeObj.PackageName = packageName // Set package name for variable node

						// Extract all referenced types from the type string
						referencedTypes := extractReferencedTypes(typeStr)

						// Create references for each type
						for _, refType := range referencedTypes {
							for _, node := range structuredKG.Kg.Nodes {
								if node.Type == "type_spec" && node.Name == refType {
									addEdge(varNodeObj, node, "references", structuredKG)
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
			for _, n := range structuredKG.Kg.Nodes {
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
									parentNodes := []*Node{}
									for _, node := range structuredKG.Kg.Nodes {
										if node.Type == "type_spec" &&
											node.Name == embeddedTypeName {
											parentNodes = append(parentNodes, node)

										}
									}
									if len(parentNodes) > 1 {
										parentNode := FindTheRightNode(parentNodes, typeNodeObj)
										addEdge(typeNodeObj, parentNode, "extends", structuredKG)
									} else if len(parentNodes) == 1 {
										addEdge(typeNodeObj, parentNodes[0], "extends", structuredKG)
									}
								} else {
									// Build reference relationships for the field
									typeName := getNodeText(typeRef, content)
									referencedTypes := extractReferencedTypes(typeName)
									fieldType := getNodeText(typeRef, content)
									fieldName := getNodeText(nameNode, content)
									fieldDesc := fmt.Sprintf("%s.%s %s", typeNodeObj.Name, fieldName, fieldType)
									fieldNodeKey := fmt.Sprintf("%s:%s:%s:%d", FieldNode, fieldDesc, filePath, typeRef.StartPoint().Row+1)
									if n, exists := structuredKG.Kg.Nodes[fieldNodeKey]; exists {
										for _, refType := range referencedTypes {
											refNodes := []*Node{}
											for _, node := range structuredKG.Kg.Nodes {
												if node.Type == "type_spec" && node.Name == refType {
													// Build "references" relationships for the field node to struct node
													refNodes = append(refNodes, node)
												}
											}
											if len(refNodes) > 1 {
												refNode := FindTheRightNode(refNodes, n)
												addEdge(n, refNode, "references", structuredKG)
											} else if len(refNodes) == 1 {
												addEdge(n, refNodes[0], "references", structuredKG)
											} else {
												fmt.Printf("No refNodes found for %s\n", refType)
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
		ProcessOtherNodes(node.NamedChild(i), content, filePath, debug, structuredKG)
	}
}

func FindTheRightNode(parentNodes []*Node, typeNodeObj *Node) *Node {
	// Sometimes we have struct nodes with the same name but in different packages and files
	// We need to find the parent node in the current package
	// If the package name is main, we need to return the node with the shortest path from the current file
	// Otherwise, we just return the first node
	if typeNodeObj.PackageName == "main" {
		shortestPath := math.MaxInt32
		var shortestNode *Node
		for _, node := range parentNodes {
			distance := CalculateDistance(node.FilePath, typeNodeObj.FilePath)
			if distance < shortestPath {
				shortestPath = distance
				shortestNode = node
			}
		}
		return shortestNode
	} else {
		for _, node := range parentNodes {
			if node.PackageName == typeNodeObj.PackageName {
				return node
			}
		}
	}
	return parentNodes[0]
}

func CalculateDistance(path1 string, path2 string) int {
	// Calculate the distance between two file paths
	// The distance is the number of directories between the two file paths
	distance := 0
	parts1 := strings.Split(path1, "/")
	parts2 := strings.Split(path2, "/")
	for i := 0; i < len(parts1) && i < len(parts2); i++ {
		if parts1[i] != parts2[i] {
			distance++
		}
	}
	return distance
}
