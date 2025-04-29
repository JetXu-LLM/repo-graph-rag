package mcp

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"
	"strings"

	"github.com/mark3labs/mcp-go/mcp"
)

// isSubpackage checks if the given package is a subpackage of the parent package
func isSubpackage(parentPath, currentPkgName, parentPkgName string) bool {
	// Check if parent path is a prefix of the current package name
	if parentPath != "" && strings.Contains(currentPkgName, parentPkgName+"/") {
		return true
	}

	// Check if the package name indicates a subpackage relationship
	return strings.HasPrefix(currentPkgName, parentPkgName+"/")
}

func LsSubpackages(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	packageID, ok := request.Params.Arguments["packageID"].(string)
	if !ok {
		return nil, errors.New("packageID must be a string")
	}

	weightedKG := GetKnowledgeGraph()
	if weightedKG == nil {
		return nil, errors.New("knowledge graph not loaded")
	}

	var sb strings.Builder
	var packageName string
	var parentPath string

	// First, find the package name for better display
	for _, node := range weightedKG.Nodes {
		if node.ID == packageID && node.Type == "package" {
			if pkgData, ok := node.Data.(map[string]interface{}); ok {
				packageName = pkgData["package_name"].(string)
				if location, ok := pkgData["location"].(map[string]interface{}); ok {
					if filePath, ok := location["file_path"].(string); ok {
						parentPath = filepath.Dir(filePath)
					}
				}
			}
			break
		}
	}

	if packageName == "" {
		packageName = packageID // Fallback if package name not found
	}

	sb.WriteString(fmt.Sprintf("Subpackages of %s:\n\n", packageName))

	// Now find all subpackages by checking if their path contains the parent path
	subpackageCount := 0
	for _, node := range weightedKG.Nodes {
		if node.Type == "package" && node.ID != packageID {
			if data, ok := node.Data.(map[string]interface{}); ok {
				currentPkgName := data["package_name"].(string)

				// Skip if this is not a subpackage
				if !isSubpackage(parentPath, currentPkgName, packageName) {
					continue
				}

				subpackageCount++
				sb.WriteString(fmt.Sprintf("Package id: %s\n", node.ID))
				sb.WriteString(fmt.Sprintf("\t- %s\n", currentPkgName))

				// Add importance if available
				if node.Weights.Importance > 0 {
					sb.WriteString(fmt.Sprintf("\t- Importance: %d\n", node.Weights.Importance))
				}

				// Add file and component counts if available
				sb.WriteString(fmt.Sprintf("\t- %d files, %d structs, %d interfaces, %d functions\n",
					node.Weights.GoFilesCount,
					node.Weights.StructCount,
					node.Weights.InterfaceCount,
					node.Weights.FunctionCount))

				// Add main components if available
				if len(node.Weights.MainFuncAndStructNames) > 0 {
					sb.WriteString("\t- Main components: ")
					for i, comp := range node.Weights.MainFuncAndStructNames {
						if i > 0 {
							sb.WriteString(", ")
						}
						sb.WriteString(comp)
					}
					sb.WriteString("\n")
				}

				sb.WriteString("\n")
			}
		}
	}

	if subpackageCount == 0 {
		sb.WriteString("No subpackages found for this package.\n")
	} else {
		sb.WriteString(fmt.Sprintf("Total: %d subpackages\n", subpackageCount))
	}

	return mcp.NewToolResultText(sb.String()), nil
}
