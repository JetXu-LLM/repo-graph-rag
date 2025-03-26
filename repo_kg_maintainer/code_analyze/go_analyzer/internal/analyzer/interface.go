package analyzer

import (
	"fmt"

	sitter "github.com/smacker/go-tree-sitter"
)

func processInterfaceMethods(
	interfaceNode *sitter.Node,
	content []byte,
	filePath string,
	kg *KnowledgeGraph,
	parentTypeNode *Node,
	packageName string,
	structuredKG *StructuredKnowledgeGraph,
) {
	// Get parent graph node
	var parentGraphNode *GraphNode
	nodeID := generateNodeID(InterfaceNode, parentTypeNode.Name, filePath)
	for i := 0; i < len(structuredKG.Nodes); i++ {
		if structuredKG.Nodes[i].Type == InterfaceNode {
			if structuredKG.Nodes[i].ID == nodeID {
				parentGraphNode = &structuredKG.Nodes[i]
				break
			}
		}
	}

	// Insert interface methods into the interfaceNode
	for i := 0; i < int(interfaceNode.NamedChildCount()); i++ {
		interfaceMethodNode := interfaceNode.NamedChild(i)
		if interfaceMethodNode != nil && interfaceMethodNode.Type() == "method_elem" {
			var methodName string
			var methodParams string
			var methodReturns string
			if interfaceMethodNode.NamedChildCount() == 3 {
				methodName = interfaceMethodNode.NamedChild(0).Content(content)
				methodParams = interfaceMethodNode.NamedChild(1).Content(content)
				methodReturns = interfaceMethodNode.NamedChild(2).Content(content)
			} else if interfaceMethodNode.NamedChildCount() == 2 {
				methodName = interfaceMethodNode.NamedChild(0).Content(content)
				methodParams = interfaceMethodNode.NamedChild(1).Content(content)
			} else if interfaceMethodNode.NamedChildCount() == 1 {
				methodName = interfaceMethodNode.NamedChild(0).Content(content)
			}

			if interfaceData, ok := parentGraphNode.Data.(InterfaceInfo); ok {
				interfaceData.Methods = append(
					interfaceData.Methods, fmt.Sprintf("func %s%s%s", methodName, methodParams, methodReturns))
				parentGraphNode.Data = interfaceData
				addNode(
					kg,
					"interface_func",
					fmt.Sprintf("%s.%s", interfaceData.InterfaceName, methodName),
					filePath,
					interfaceMethodNode.StartPoint(),
					interfaceMethodNode.EndPoint(),
					interfaceData.InterfaceName,
					packageName,
					structuredKG)
			}
		}
	}
}
