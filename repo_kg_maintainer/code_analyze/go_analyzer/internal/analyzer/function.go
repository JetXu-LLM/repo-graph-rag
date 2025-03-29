package analyzer

import sitter "github.com/smacker/go-tree-sitter"

func processFunctionBody(
	node *sitter.Node,
	funcNode *Node,
	content []byte,
	structuredKG *StructuredKnowledgeGraph,
) {
	cursor := sitter.NewTreeCursor(node)
	defer cursor.Close()

	if cursor.GoToFirstChild() {
		for {
			if cursor.CurrentNode().Type() == "call_expression" {
				callNode := cursor.CurrentNode()
				functionName := getNodeText(callNode.ChildByFieldName("function"), content)

				// Add edge representing function call
				calledFunc := addNode(
					"function_call",
					functionName,
					funcNode.FilePath,
					callNode.StartPoint(),
					callNode.EndPoint(),
					"",
					"",
					structuredKG,
				)
				addEdge(funcNode, calledFunc, "calls", structuredKG)
			}

			if !cursor.GoToNextSibling() {
				break
			}
		}
	}
}
