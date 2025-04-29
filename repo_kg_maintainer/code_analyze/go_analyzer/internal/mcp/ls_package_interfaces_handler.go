package mcp

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"
	"strings"

	"github.com/mark3labs/mcp-go/mcp"
)

func LsPackageInterfaceNames(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
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

	sb.WriteString(fmt.Sprintf("Interfaces in package %s:\n\n", packageName))

	// Now find all interfaces that belong to this package
	interfaceCount := 0
	for _, node := range weightedKG.Nodes {
		if node.Type == "interface" {
			if data, ok := node.Data.(map[string]interface{}); ok {
				if data["package_name"] != packageName {
					continue
				}
				interfaceCount++

				// Extract interface details
				interfaceName := data["interface_name"]

				sb.WriteString(fmt.Sprintf("Interface id: %s\n", node.ID))
				sb.WriteString(fmt.Sprintf("\t- %s\n", interfaceName))

				// Add importance if available
				if node.Weights.Importance > 0 {
					sb.WriteString(fmt.Sprintf("\t- Importance: %d\n", node.Weights.Importance))
				}

				// Get interface methods
				if methods, ok := data["methods"].([]interface{}); ok && len(methods) > 0 {
					sb.WriteString("\t- Methods:\n")
					for _, methodID := range methods {
						methodIDStr, ok := methodID.(string)
						if !ok {
							continue
						}

						// Find method details
						for _, methodNode := range weightedKG.Nodes {
							if methodNode.ID == methodIDStr && methodNode.Type == "interface_func" {
								if methodData, ok := methodNode.Data.(map[string]interface{}); ok {
									methodName := methodData["method"]
									sb.WriteString(fmt.Sprintf("\t  * %s\n", methodName))
								}
								break
							}
						}
					}
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

	if interfaceCount == 0 {
		sb.WriteString("No interfaces found for this package.\n")
	} else {
		sb.WriteString(fmt.Sprintf("Total: %d interfaces\n", interfaceCount))
	}

	return mcp.NewToolResultText(sb.String()), nil
}
