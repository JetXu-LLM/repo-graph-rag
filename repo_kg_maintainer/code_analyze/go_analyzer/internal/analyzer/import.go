package analyzer

import (
	"fmt"
	"path/filepath"
	"strings"

	sitter "github.com/smacker/go-tree-sitter"
)

func processImports(
	node *sitter.Node, filePath string, content []byte,
	packageName string, structuredKG *StructuredKnowledgeGraph) {
	for i := 0; i < int(node.NamedChildCount()); i++ {
		child := node.NamedChild(i)
		importPaths := []string{}
		if child.Type() == "import_spec_list" {
			for j := 0; j < int(child.NamedChildCount()); j++ {
				importSpec := child.NamedChild(j)
				if importSpec.Type() == "import_spec" {
					importPath := getNodeText(importSpec.NamedChild(0), content)
					importPath = strings.Trim(importPath, "\"")
					importPaths = append(importPaths, importPath)
				}
			}
		} else if child.Type() == "import_spec" {
			importPath := getNodeText(child.NamedChild(0), content)
			importPath = strings.Trim(importPath, "\"")
			importPaths = append(importPaths, importPath)
		}

		for _, importPath := range importPaths {
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
			var importNode *Node
			if nodeExists {
				importNode = structuredKG.Kg.Nodes[fmt.Sprintf("import:%s", importPath)]
			} else {
				// Create the import node
				importNode = addNode(
					"import",
					importPath,
					filePath,
					child.StartPoint(),
					child.EndPoint(),
					"",
					packageName,
					structuredKG,
				)
			}

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
