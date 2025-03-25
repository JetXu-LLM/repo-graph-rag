package analyzer

import (
	"fmt"

	sitter "github.com/smacker/go-tree-sitter"
)

func processRegularField(
	fieldName string, typeRef *sitter.Node, content []byte, filePath string,
	kg *KnowledgeGraph, parentTypeNode *Node, parentTypeName string,
	packageName string, structuredKG *StructuredKnowledgeGraph) {
	fieldType := getNodeText(typeRef, content)
	fieldDesc := fmt.Sprintf("%s.%s %s", parentTypeName, fieldName, fieldType)
	fieldNodeObj := addNode(
		kg,
		"field",
		fieldDesc,
		filePath,
		typeRef.StartPoint(),
		typeRef.EndPoint(),
		parentTypeName,
		packageName,
		structuredKG,
	)
	fieldNodeObj.ParentStruct = parentTypeName

	// Create has_field relationship
	addEdge(kg, parentTypeNode, fieldNodeObj, "has_field", structuredKG)

	// Update the parent struct's Fields array
	fieldNodeID := generateNodeID(FieldNode, fieldDesc, filePath)
	parentNodeID := generateNodeID(StructNode, parentTypeName, filePath)
	for i, n := range structuredKG.Nodes {
		if n.Type == StructNode && n.ID == parentNodeID {
			if structData, ok := n.Data.(StructInfo); ok {
				structData.Fields = append(structData.Fields, fieldNodeID)
				structuredKG.Nodes[i].Data = structData
			}
			break
		}
	}
}
