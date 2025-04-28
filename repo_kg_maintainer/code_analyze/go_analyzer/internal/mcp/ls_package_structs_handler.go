package mcp

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"
	"strings"

	"github.com/mark3labs/mcp-go/mcp"
)

func LsPackageStructNames(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
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

	// First, find the package name for better display
	for _, node := range weightedKG.Nodes {
		if node.ID == packageID && node.Type == "package" {
			if pkgData, ok := node.Data.(map[string]interface{}); ok {
				packageName = pkgData["package_name"].(string)
			}
			break
		}
	}

	if packageName == "" {
		packageName = packageID // Fallback if package name not found
	}

	sb.WriteString(fmt.Sprintf("Structs in package %s:\n\n", packageName))

	// Now find all structs that belong to this package
	structCount := 0
	for _, node := range weightedKG.Nodes {
		if node.Type == "struct" {
			if data, ok := node.Data.(map[string]interface{}); ok {
				if data["package_name"] != packageName {
					continue
				}
				structCount++

				// Extract struct details
				structName := data["struct_name"]
				isGeneric, _ := data["is_generic"].(bool)

				sb.WriteString(fmt.Sprintf("Struct id: %s\n", node.ID))
				if isGeneric {
					sb.WriteString(fmt.Sprintf("\t- %s (generic)\n", structName))
				} else {
					sb.WriteString(fmt.Sprintf("\t- %s\n", structName))
				}

				// Add importance if available
				if node.Weights.Importance > 0 {
					sb.WriteString(fmt.Sprintf("\t- Importance: %d\n", node.Weights.Importance))
				}

				// Add field and method counts if available
				if node.Weights.FieldCount > 0 || node.Weights.MethodCount > 0 {
					sb.WriteString(fmt.Sprintf("\t- %d fields, %d methods\n",
						node.Weights.FieldCount,
						node.Weights.MethodCount))
				}

				// Add reference count if available
				if node.Weights.ReferenceCount > 0 {
					sb.WriteString(fmt.Sprintf("\t- Referenced %d times\n",
						node.Weights.ReferenceCount))
				}

				// Add location if available
				if location, ok := data["location"].(map[string]interface{}); ok {
					if filePath, ok := location["file_path"].(string); ok {
						lineNum, _ := location["line"].(float64)
						sb.WriteString(fmt.Sprintf("\t- Located at: %s:%d\n",
							filepath.Base(filePath),
							int(lineNum)))
					}
				}

				sb.WriteString("\n")
			}
		}
	}

	if structCount == 0 {
		sb.WriteString("No structs found for this package.\n")
	} else {
		sb.WriteString(fmt.Sprintf("Total: %d structs\n", structCount))
	}

	return mcp.NewToolResultText(sb.String()), nil
}
