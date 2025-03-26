package analyzer

import (
	"fmt"

	sitter "github.com/smacker/go-tree-sitter"
)

func processNestedStruct(
	fieldName string, typePrefix string, structNode *sitter.Node, content []byte,
	filePath string, kg *KnowledgeGraph, parentTypeNode *Node, parentTypeName string,
	packageName string, structuredKG *StructuredKnowledgeGraph) {
	// Create a field node for the struct field itself
	var fieldDesc string
	if typePrefix == "[]" {
		fieldDesc = fmt.Sprintf("%s.%s []struct", parentTypeName, fieldName)
	} else if typePrefix != "" {
		fieldDesc = fmt.Sprintf("%s.%s %sstruct", parentTypeName, fieldName, typePrefix)
	} else {
		fieldDesc = fmt.Sprintf("%s.%s struct", parentTypeName, fieldName)
	}

	fieldNodeObj := addNode(
		kg,
		"field",
		fieldDesc,
		filePath,
		structNode.StartPoint(),
		structNode.EndPoint(),
		parentTypeName,
		packageName,
		structuredKG,
	)
	fieldNodeObj.ParentStruct = parentTypeName

	addEdge(kg, parentTypeNode, fieldNodeObj, "has_field", structuredKG)

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
	nestedTypeNode := addNode(
		kg,
		"type_spec",
		nestedTypeName,
		filePath,
		structNode.StartPoint(),
		structNode.EndPoint(),
		"",
		packageName,
		structuredKG,
	)

	// Process the nested struct's fields
	processStructFields(
		structNode,
		content,
		filePath,
		kg,
		nestedTypeNode,
		nestedTypeName,
		packageName,
		structuredKG,
	)
}

func processStructFields(
	structNode *sitter.Node,
	content []byte,
	filePath string,
	kg *KnowledgeGraph,
	parentTypeNode *Node,
	parentTypeName string,
	packageName string,
	structuredKG *StructuredKnowledgeGraph,
) {
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
						processNestedStruct(
							fieldName,
							"",
							typeRef,
							content,
							filePath,
							kg,
							parentTypeNode,
							parentTypeName,
							packageName,
							structuredKG,
						)

					case "slice_type":
						// Array/slice of structs
						elementType := typeRef.ChildByFieldName("element")
						if elementType != nil && elementType.Type() == "struct_type" {
							processNestedStruct(
								fieldName,
								"[]",
								elementType,
								content,
								filePath,
								kg,
								parentTypeNode,
								parentTypeName,
								packageName,
								structuredKG,
							)
						} else {
							// Regular array field
							processRegularField(fieldName, typeRef, content, filePath, kg, parentTypeNode, parentTypeName, packageName, structuredKG)
						}

					case "map_type":
						// Map with struct value
						valueType := typeRef.ChildByFieldName("value")
						if valueType != nil && valueType.Type() == "struct_type" {
							keyType := getNodeText(typeRef.ChildByFieldName("key"), content)
							mapPrefix := fmt.Sprintf("map[%s]", keyType)
							processNestedStruct(
								fieldName,
								mapPrefix,
								valueType,
								content,
								filePath,
								kg,
								parentTypeNode,
								parentTypeName,
								packageName,
								structuredKG,
							)
						} else {
							// Regular map field
							processRegularField(fieldName, typeRef, content, filePath, kg, parentTypeNode, parentTypeName, packageName, structuredKG)
						}

					default:
						// Regular field
						processRegularField(
							fieldName,
							typeRef,
							content,
							filePath,
							kg,
							parentTypeNode,
							parentTypeName,
							packageName,
							structuredKG,
						)
					}
				}
			}
		}
	}
}
