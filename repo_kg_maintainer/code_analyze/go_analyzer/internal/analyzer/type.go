package analyzer

import (
	"fmt"
	"path/filepath"

	sitter "github.com/smacker/go-tree-sitter"
)

func ProcessTypes(
	node *sitter.Node,
	content []byte,
	filePath string,
	kg *KnowledgeGraph,
	debug bool,
	structuredKG *StructuredKnowledgeGraph,
) {
	// Find the package name first
	var packageName string
	// for _, n := range structuredKG.Nodes {
	// 	if n.Type == PackageNode && filepath.Dir(filePath) == n.Data.(PackageInfo).Location.FilePath {
	// 		packageName = n.Data.(PackageInfo).PackageName
	// 		break
	// 	}
	// }
	for _, n := range kg.Nodes {
		if n.Type == "package" && filepath.Dir(filePath) == n.FilePath {
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
						if n.Type == "type_spec" && n.Name == typeName &&
							n.PackageName == packageName &&
							n.FilePath != filePath {
							oldNodeIDs = append(
								oldNodeIDs,
								generateNodeID(StructNode, typeName, n.FilePath),
							)
						}
					}

					// Remove temporary nodes as before
					for _, n := range kg.Nodes {
						if n.Type == "type_spec" && n.Name == typeName &&
							n.PackageName == packageName &&
							n.FilePath != filePath {
							nodeID := fmt.Sprintf("%s:%s:%s:%d", n.Type, n.Name, n.FilePath, n.Line)
							delete(kg.Nodes, nodeID)
							for i := len(structuredKG.Nodes) - 1; i >= 0; i-- {
								node := structuredKG.Nodes[i]
								if node.Type == StructNode {
									if structData, ok := node.Data.(StructInfo); ok {
										if structData.StructName == typeName &&
											structData.PackageName == packageName {
											structuredKG.Nodes = append(
												structuredKG.Nodes[:i],
												structuredKG.Nodes[i+1:]...)
										}
									}
								}
							}
						}
					}

					// Create the new struct node
					typeNodeObj := addNode(
						kg,
						"type_spec",
						typeName,
						filePath,
						typeNode.StartPoint(),
						typeNode.EndPoint(),
						"",
						packageName,
						structuredKG,
					)

					if packageNode != nil {
						addEdge(kg, packageNode, typeNodeObj, "has_struct", structuredKG)
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

					processStructFields(
						typeDefNode,
						content,
						filePath,
						kg,
						typeNodeObj,
						typeName,
						packageName,
						structuredKG,
					)
				} else if typeDefNode.Type() == "interface_type" {
					// Handle interface type
					interfaceNodeObj := addNode(
						kg, "interface", typeName, filePath, typeNode.StartPoint(), typeNode.EndPoint(),
						"", packageName, structuredKG)
					if packageNode != nil {
						addEdge(kg, packageNode, interfaceNodeObj, "has_interface", structuredKG)
					}
					processInterfaceMethods(
						typeDefNode,
						content,
						filePath,
						kg,
						interfaceNodeObj,
						packageName,
						structuredKG)
				} else if typeDefNode.Type() == "function_type" {
					// Handle function type
					functionNodeObj := addNode(kg, "function", typeName, filePath,
						typeNode.StartPoint(), typeNode.EndPoint(), "", packageName, structuredKG)

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
						addEdge(kg, packageNode, functionNodeObj, "has_function", structuredKG)

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
						if n.Type == "type_spec" && n.Name == typeName &&
							n.PackageName == packageName && n.FilePath != filePath {
							delete(kg.Nodes, fmt.Sprintf("%s:%s:%s:%d", n.Type, n.Name, n.FilePath, n.Line))

							for i := len(structuredKG.Nodes) - 1; i >= 0; i-- {
								node := structuredKG.Nodes[i]
								if node.Type == StructNode {
									if structData, ok := node.Data.(StructInfo); ok {
										if structData.StructName == typeName &&
											structData.PackageName == packageName {
											structuredKG.Nodes = append(
												structuredKG.Nodes[:i], structuredKG.Nodes[i+1:]...)
										}
									}
								}
							}
						}
					}
					// Handle other types. e.g, enum
					typeNodeObj := addNode(
						kg,
						"type_spec",
						typeName,
						filePath,
						typeNode.StartPoint(),
						typeNode.EndPoint(),
						"",
						packageName,
						structuredKG,
					)
					if packageNode != nil {
						addEdge(kg, packageNode, typeNodeObj, "has_type_spec", structuredKG)
					}
				}
			}
		}
	}

	// Recursively process children
	for i := 0; i < int(node.NamedChildCount()); i++ {
		ProcessTypes(node.NamedChild(i), content, filePath, kg, debug, structuredKG)
	}
}
