package analyzer

import (
	"path/filepath"

	sitter "github.com/smacker/go-tree-sitter"
)

var nilPoint = sitter.Point{Row: 0, Column: 0}

func ProcessPackageDecl(
	node *sitter.Node,
	content []byte,
	filePath string,
	structuredKG *StructuredKnowledgeGraph,
) {
	if node.Type() == "source_file" {
		var packageNode *Node
		// Find package clause
		for i := 0; i < int(node.NamedChildCount()); i++ {
			child := node.NamedChild(i)
			if child.Type() == "package_clause" {
				// The package identifier is the first named child of the package clause
				if child.NamedChildCount() > 0 {
					nameNode := child.NamedChild(0)
					if nameNode != nil {
						packageName := getNodeText(nameNode, content)
						packageNode = addNode(
							"package",
							packageName,
							filePath,
							child.StartPoint(),
							child.EndPoint(),
							"",
							packageName,
							structuredKG,
						)
					}
				}
				break // We only need the first package clause
			}
		}
		if packageNode != nil {
			packageName := packageNode.Name
			addNode("file", filepath.Base(filePath), filePath, nilPoint, nilPoint, "", packageName, structuredKG)
		}
	}
}
