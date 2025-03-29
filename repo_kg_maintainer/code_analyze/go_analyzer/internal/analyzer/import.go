package analyzer

import (
	"path/filepath"
	"strings"

	sitter "github.com/smacker/go-tree-sitter"
)

func processImports(
	node *sitter.Node, filePath string, content []byte,
	packageName string, structuredKG *StructuredKnowledgeGraph) {
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
			importNode := addNode(
				"import",
				importPath,
				filePath,
				child.StartPoint(),
				child.EndPoint(),
				"",
				packageName,
				structuredKG,
			)

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
			for _, n := range structuredKG.Kg.Nodes {
				if n.Type == "package" && filepath.Dir(filePath) == n.FilePath {
					packageNode = n
					break
				}
			}

			// Create has_import relationship if package node exists
			if packageNode != nil {
				addEdge(packageNode, importNode, "has_import", structuredKG)
			}
		}
	}
}
