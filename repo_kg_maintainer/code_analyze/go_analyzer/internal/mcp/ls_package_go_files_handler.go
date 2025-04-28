package mcp

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"
	"strings"

	"github.com/mark3labs/mcp-go/mcp"
)

func LsPackageGoFiles(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	packageID, ok := request.Params.Arguments["packageID"].(string)
	if !ok {
		return nil, errors.New("packageID must be a string")
	}

	weightedKG := GetKnowledgeGraph()
	if weightedKG == nil {
		return nil, errors.New("knowledge graph not loaded")
	}

	var sb strings.Builder
	// Find the package node
	for _, node := range weightedKG.Nodes {
		if node.Type == "file" {
			if data, ok := node.Data.(map[string]interface{}); ok {
				if data["package_id"] != packageID {
					continue
				}
				sb.WriteString(fmt.Sprintf("File id: %s\n", node.ID))
				sb.WriteString(fmt.Sprintf("\t- File name: %s, %d lines, %d functions, %d structs, %d interfaces\n",
					filepath.Base(data["file_path"].(string)),
					node.Weights.CodeLineCount,
					node.Weights.FunctionCount,
					node.Weights.StructCount,
					node.Weights.InterfaceCount))
			}
		}
	}

	sb.WriteString("\nYou can navigate to a specific file by using the file id.")

	return mcp.NewToolResultText(sb.String()), nil
}
