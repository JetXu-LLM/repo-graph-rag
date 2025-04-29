package mcp

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"
	"strings"

	"github.com/mark3labs/mcp-go/mcp"
)

func LsPackageFunctionNames(
	ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
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

	sb.WriteString(fmt.Sprintf("Functions in package %s:\n\n", packageName))

	// Now find all functions that belong to this package
	funcCount := 0
	for _, node := range weightedKG.Nodes {
		if node.Type == "function" {
			if data, ok := node.Data.(map[string]interface{}); ok {
				if data["package_name"] != packageName {
					continue
				}
				funcCount++

				// Extract function details
				funcName := data["function_name"]
				inputParams := data["input_params"]
				returnParams := data["return_params"]

				sb.WriteString(fmt.Sprintf("Function id: %s\n", node.ID))
				sb.WriteString(fmt.Sprintf("\t- %s%s%s\n", funcName, inputParams, returnParams))

				// Add importance if available
				if node.Weights.Importance > 0 {
					sb.WriteString(fmt.Sprintf("\t- Importance: %d\n", node.Weights.Importance))
				}

				// Add caller/callee info if available
				if node.Weights.CallerCount > 0 || node.Weights.CalleeCount > 0 {
					sb.WriteString(fmt.Sprintf("\t- Called by %d functions, calls %d functions\n",
						node.Weights.CalleeCount,
						node.Weights.CallerCount))
				}

				// Add file location if available
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

	if funcCount == 0 {
		sb.WriteString("No functions found for this package.\n")
	} else {
		sb.WriteString(fmt.Sprintf("Total: %d functions\n", funcCount))
	}

	return mcp.NewToolResultText(sb.String()), nil
}
